"""Dataset lifecycle: upload, registration, listing, rename, delete.

Every function takes a ``workspace_id`` and filters by it; there is no code path
that loads a dataset by id alone. This is what enforces ownership/isolation.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import Conflict, InvalidInput, NotFound, PayloadTooLarge
from app.models import Dataset, DatasetVersion, Job
from app.services import activity, jobs
from app.storage import (
    UploadTooLarge,
    dataset_prefixes,
    get_storage,
    raw_key,
)

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".parquet": "parquet"}
_RESERVED = {
    "select", "from", "where", "group", "order", "by", "table", "limit", "join", "union",
    "with", "as", "on", "and", "or", "not", "null", "true", "false", "case", "when", "end",
    "values", "having", "distinct", "all", "any", "in", "is", "like", "between", "offset",
    "pivot", "unpivot", "qualify", "window", "using", "natural", "cross", "into", "result",
}  # fmt: skip


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidInput(
            f"Unsupported file type '{ext or filename}'. Upload a .csv, .tsv or .parquet file.",
            details={"allowed": sorted(ALLOWED_EXTENSIONS)},
        )
    return ALLOWED_EXTENSIONS[ext]


def sniff_content(path: Path, fmt: str) -> None:
    """Cheap magic-byte validation so obviously wrong files fail fast, before a job."""
    size = path.stat().st_size
    if size == 0:
        raise InvalidInput("The uploaded file is empty.")
    with path.open("rb") as fh:
        head = fh.read(65536)
        if fmt == "parquet":
            fh.seek(max(0, size - 4))
            tail = fh.read(4)
            if not head.startswith(b"PAR1") or tail != b"PAR1":
                raise InvalidInput("This is not a valid Parquet file (missing PAR1 magic bytes).")
        else:
            utf16 = head.startswith((b"\xff\xfe", b"\xfe\xff"))
            if not utf16 and b"\x00" in head:
                raise InvalidInput("This looks like a binary file, not CSV text.")


def slugify_sql_name(name: str) -> str:
    stem = Path(name).stem if "." in name else name
    slug = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:50] or "dataset"
    if slug[0].isdigit():
        slug = "t_" + slug
    if slug in _RESERVED:
        slug += "_data"
    return slug


def unique_sql_name(db: Session, workspace_id: uuid.UUID, base: str) -> str:
    existing = set(
        db.scalars(
            select(Dataset.sql_name).where(
                Dataset.workspace_id == workspace_id, Dataset.sql_name.like(f"{base}%")
            )
        )
    )
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


async def create_from_upload(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    filename: str,
    chunks: AsyncIterator[bytes],
    name: str | None,
    options: dict[str, Any],
    content_length: int | None,
) -> tuple[Dataset, Job]:
    """Stream an upload to storage, then register dataset + version + ingest job atomically."""
    settings = get_settings()
    fmt = detect_format(filename)
    if content_length is not None and content_length > settings.max_upload_bytes:
        raise PayloadTooLarge(
            f"File is larger than the {settings.max_upload_bytes // 1024**2} MiB upload limit.",
            details={"max_upload_bytes": settings.max_upload_bytes},
        )

    storage = get_storage()
    tmp_key = f"uploads/{uuid.uuid4()}.part"
    try:
        size, sha = await storage.write_stream(tmp_key, chunks, max_bytes=settings.max_upload_bytes)
    except UploadTooLarge as e:
        raise PayloadTooLarge(
            str(e), details={"max_upload_bytes": settings.max_upload_bytes}
        ) from e

    try:
        sniff_content(storage.local_path(tmp_key), fmt)
        display = (name or Path(filename).stem or "Untitled").strip()[:200]
        dataset = Dataset(
            workspace_id=workspace_id,
            name=display,
            sql_name=unique_sql_name(db, workspace_id, slugify_sql_name(display)),
            status="pending",
        )
        db.add(dataset)
        db.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version=1,
            status="pending",
            source_format=fmt,
            original_filename=Path(filename).name[:500],
            raw_bytes=size,
            raw_sha256=sha,
            ingest_options=options,
        )
        db.add(version)
        db.flush()
        version.raw_key = raw_key(workspace_id, dataset.id, version.id, fmt)
        storage.commit_tmp(tmp_key, version.raw_key)
        job = jobs.enqueue(
            db,
            workspace_id,
            "ingest",
            {"dataset_id": str(dataset.id), "version_id": str(version.id)},
        )
        activity.record(
            db,
            workspace_id,
            "dataset.uploaded",
            "dataset",
            dataset.id,
            f"Uploaded {version.original_filename}",
        )
        db.commit()
    except BaseException:
        db.rollback()
        storage.delete(tmp_key)
        raise
    return dataset, job


def reprocess(
    db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, options: dict[str, Any]
) -> tuple[Dataset, Job]:
    """Create a new version from the current version's original file with new options."""
    dataset = get(db, workspace_id, dataset_id)
    base = dataset.current_version or _latest_version(db, dataset.id)
    if base is None or base.raw_key is None:
        raise InvalidInput("This dataset has no original file to reprocess.")
    next_no = (
        db.scalar(
            select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset.id)
        )
        or 0
    ) + 1
    version = DatasetVersion(
        dataset_id=dataset.id,
        version=next_no,
        status="pending",
        source_format=base.source_format,
        original_filename=base.original_filename,
        raw_key=base.raw_key,  # originals are immutable and shared between versions
        raw_bytes=base.raw_bytes,
        raw_sha256=base.raw_sha256,
        ingest_options=options,
    )
    db.add(version)
    db.flush()
    job = jobs.enqueue(
        db,
        workspace_id,
        "ingest",
        {"dataset_id": str(dataset.id), "version_id": str(version.id)},
    )
    if dataset.status != "ready":
        dataset.status = "pending"
    activity.record(
        db,
        workspace_id,
        "dataset.reprocessed",
        "dataset",
        dataset.id,
        f"Reprocessing {dataset.name} as version {next_no}",
    )
    db.commit()
    return dataset, job


def _latest_version(db: Session, dataset_id: uuid.UUID) -> DatasetVersion | None:
    return db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
        .limit(1)
    )


def get(db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    ds = db.scalar(
        select(Dataset)
        .options(selectinload(Dataset.current_version))
        .where(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
            Dataset.status != "deleting",
        )
    )
    if ds is None:
        raise NotFound("Dataset not found.")
    return ds


def list_datasets(
    db: Session, workspace_id: uuid.UUID, *, limit: int, offset: int, q: str | None = None
) -> tuple[list[Dataset], int]:
    where = [Dataset.workspace_id == workspace_id, Dataset.status != "deleting"]
    if q:
        where.append(Dataset.name.ilike(f"%{q}%") | Dataset.sql_name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(Dataset).where(*where)) or 0
    items = list(
        db.scalars(
            select(Dataset)
            .options(selectinload(Dataset.current_version))
            .where(*where)
            .order_by(Dataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def latest_jobs(db: Session, workspace_id: uuid.UUID, dataset_ids: list[uuid.UUID]) -> dict:
    """Most recent ingest job per dataset, for status/progress display."""
    if not dataset_ids:
        return {}
    ids = [str(i) for i in dataset_ids]
    rows = db.execute(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.kind == "ingest",
            Job.payload["dataset_id"].astext.in_(ids),
        )
        .order_by(Job.created_at.desc())
    ).scalars()
    out: dict[str, Job] = {}
    for job in rows:
        out.setdefault(job.payload["dataset_id"], job)
    return out


def latest_version(db: Session, dataset_id: uuid.UUID) -> DatasetVersion | None:
    return _latest_version(db, dataset_id)


def update(db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID, **fields: Any) -> Dataset:
    ds = get(db, workspace_id, dataset_id)
    for k, v in fields.items():
        if v is not None:
            setattr(ds, k, v)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("Another dataset already uses that SQL name.") from e
    return ds


def delete(db: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID) -> None:
    """Deletion policy: mark ``deleting`` (hides it everywhere), remove storage, drop rows.

    If storage removal fails the row stays ``deleting`` and ``sweep_deleting`` retries it.
    Charts and transformations built on the dataset are removed by FK cascade.
    """
    ds = get(db, workspace_id, dataset_id)
    ds.status = "deleting"
    activity.record(db, workspace_id, "dataset.deleted", "dataset", None, f"Deleted {ds.name}")
    db.commit()
    _purge(db, ds)


def _purge(db: Session, ds: Dataset) -> None:
    storage = get_storage()
    try:
        for prefix in dataset_prefixes(ds.workspace_id, ds.id):
            storage.delete_prefix(prefix)
    except OSError:
        log.exception("storage cleanup failed for dataset %s; will retry", ds.id)
        return
    db.delete(ds)
    db.commit()


def sweep_deleting(db: Session) -> int:
    """Finish deletions interrupted by a crash. Called by workers on start-up."""
    pending = list(db.scalars(select(Dataset).where(Dataset.status == "deleting")))
    for ds in pending:
        _purge(db, ds)
    return len(pending)


def queryable_datasets(db: Session, workspace_id: uuid.UUID) -> dict[str, str]:
    """Map of sql_name -> absolute Parquet path for every ready dataset in the workspace.

    This is the *only* source of the allowlist handed to the SQL guard and sandbox.
    """
    storage = get_storage()
    rows = db.execute(
        select(Dataset.sql_name, DatasetVersion.processed_key)
        .join(DatasetVersion, DatasetVersion.id == Dataset.current_version_id)
        .where(
            Dataset.workspace_id == workspace_id,
            Dataset.status == "ready",
            DatasetVersion.status == "ready",
        )
    ).all()
    return {name: str(storage.local_path(key)) for name, key in rows if key}
