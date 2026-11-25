"""Job handlers. Each receives the claimed job and a progress callback."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.analytics.engine import SandboxLimits, copy_query_to_file, describe_columns, open_sandbox
from app.analytics.ingest import IngestError, IngestOptions, IngestResult, ingest_file
from app.analytics.profile import profile_parquet
from app.analytics.sql_guard import validate_query
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import FacetError
from app.models import Dataset, DatasetVersion, Job
from app.services import activity, jobs
from app.services import datasets as ds_svc
from app.services import transformations as tx_svc
from app.storage import get_storage, processed_key

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


class PermanentJobError(Exception):
    """Failure caused by the input (bad file, missing dataset); retrying will not help."""


def handle_ingest(job: Job, progress: Progress) -> dict[str, Any]:
    settings = get_settings()
    storage = get_storage()
    dataset_id = uuid.UUID(job.payload["dataset_id"])
    version_id = uuid.UUID(job.payload["version_id"])

    with session_scope() as db:
        version = db.scalar(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                DatasetVersion.id == version_id,
                Dataset.id == dataset_id,
                Dataset.workspace_id == job.workspace_id,
            )
        )
        if version is None or version.raw_key is None:
            raise PermanentJobError("Dataset version no longer exists.")
        dataset = version.dataset
        if dataset.status == "deleting":
            raise PermanentJobError("Dataset is being deleted.")
        version.status = "processing"
        if dataset.current_version_id is None:
            dataset.status = "processing"
        raw = storage.local_path(version.raw_key)
        fmt = version.source_format
        options = IngestOptions.from_dict(version.ingest_options or {})
        final_key = processed_key(job.workspace_id, dataset_id, version_id)

    tmp_key = final_key + ".tmp"
    try:
        result = ingest_file(
            raw,
            fmt,
            storage.local_path(tmp_key),
            options,
            memory_limit=settings.ingest_memory_limit,
            threads=settings.ingest_threads,
            temp_dir=settings.tmp_dir / "duckdb" / str(job.id),
            progress=progress,
        )
    except IngestError as e:
        storage.delete(tmp_key)
        raise PermanentJobError(str(e)) from e

    _register_version(job, dataset_id, version_id, tmp_key, final_key, result)
    return {
        "dataset_id": str(dataset_id),
        "version_id": str(version_id),
        "row_count": result.row_count,
        "duration_s": result.duration_s,
    }


def _register_version(
    job: Job,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    tmp_key: str,
    final_key: str,
    result: IngestResult,
) -> None:
    """Atomic registration of a finished Parquet file as the dataset's current version.

    The file is moved into place first, then one DB transaction flips the version to
    ready and points the dataset at it. A crash between the two leaves an unreferenced
    file (removed with the dataset) but never a "ready" dataset pointing at a missing
    or partial file.
    """
    storage = get_storage()
    storage.commit_tmp(tmp_key, final_key)
    with session_scope() as db:
        version = db.get(DatasetVersion, version_id)
        dataset = db.get(Dataset, dataset_id)
        if version is None or dataset is None or dataset.status == "deleting":
            storage.delete(final_key)
            raise PermanentJobError("Dataset was deleted during processing.")
        version.status = "ready"
        version.processed_key = final_key
        version.processed_bytes = storage.size(final_key)
        version.row_count = result.row_count
        version.column_count = result.column_count
        version.schema_json = result.schema
        version.ingest_report = {**result.report, "duration_s": round(result.duration_s, 3)}
        version.profile_json = None
        version.error = None
        dataset.current_version_id = version.id
        dataset.status = "ready"
        activity.record(
            db,
            job.workspace_id,
            "dataset.ready",
            "dataset",
            dataset.id,
            f"{dataset.name} is ready ({result.row_count:,} rows)",
        )
        # Profile in the background so the dataset is queryable immediately.
        jobs.enqueue(
            db,
            job.workspace_id,
            "profile",
            {"dataset_id": str(dataset_id), "version_id": str(version_id)},
        )


def handle_materialize(job: Job, progress: Progress) -> dict[str, Any]:
    """Run a saved transformation through the sandbox and store the result as Parquet."""
    settings = get_settings()
    storage = get_storage()
    dataset_id = uuid.UUID(job.payload["dataset_id"])
    version_id = uuid.UUID(job.payload["version_id"])
    tid = uuid.UUID(job.payload["transformation_id"])
    with session_scope() as db:
        try:
            t = tx_svc.get(db, job.workspace_id, tid)
            src = ds_svc.get(db, job.workspace_id, t.dataset_id)
            sql, _ = tx_svc.compile_for(src, t.steps)
        except FacetError as e:
            raise PermanentJobError(e.message) from e
        allow = ds_svc.queryable_datasets(db, job.workspace_id)
        version = db.get(DatasetVersion, version_id)
        if version is None:
            raise PermanentJobError("Dataset version no longer exists.")
        version.status = "processing"
    try:
        validated = validate_query(sql, set(allow))
    except FacetError as e:
        raise PermanentJobError(e.message) from e

    final_key = processed_key(job.workspace_id, dataset_id, version_id)
    tmp_key = final_key + ".tmp"
    tmp_path = storage.local_path(tmp_key)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    progress(0.1, "Running transformation")
    t0 = time.perf_counter()
    con = open_sandbox(
        {n: allow[n] for n in validated.datasets},
        SandboxLimits(settings.ingest_memory_limit, settings.ingest_threads, 3600),
        writable_paths=(str(tmp_path),),
    )
    try:
        rows = copy_query_to_file(
            con,
            validated.sql,
            str(tmp_path),
            "parquet",
            max_rows=2**62,
            timeout_s=3600,
            sanitize_csv=False,
        )
        schema = [
            {"name": c["name"], "type": c["type"], "nullable": True}
            for c in describe_columns(con, f"SELECT * FROM ({validated.sql}) AS q LIMIT 0")
        ]
    except Exception as e:
        storage.delete(tmp_key)
        raise PermanentJobError(f"Transformation failed: {str(e).splitlines()[0]}") from e
    finally:
        con.close()
    result = IngestResult(
        schema=schema,
        row_count=rows,
        column_count=len(schema),
        report={"warnings": [], "sql": validated.sql, "transformation_id": str(tid)},
        duration_s=time.perf_counter() - t0,
    )
    _register_version(job, dataset_id, version_id, tmp_key, final_key, result)
    return {"dataset_id": str(dataset_id), "row_count": rows}


def handle_profile(job: Job, progress: Progress) -> dict[str, Any]:
    settings = get_settings()
    version_id = uuid.UUID(job.payload["version_id"])
    with session_scope() as db:
        version = db.scalar(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(DatasetVersion.id == version_id, Dataset.workspace_id == job.workspace_id)
        )
        if version is None or version.status != "ready" or not version.processed_key:
            raise PermanentJobError("Dataset version is not available for profiling.")
        path = str(get_storage().local_path(version.processed_key))
    progress(0.1, "Profiling columns")
    profile = profile_parquet(
        path,
        memory_limit=settings.ingest_memory_limit,
        threads=settings.ingest_threads,
        sample_threshold=settings.profile_sample_threshold,
        sample_rows=settings.profile_sample_rows,
    )
    with session_scope() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            raise PermanentJobError("Dataset version was deleted during profiling.")
        version.profile_json = profile
    return {"version_id": str(version_id), "duration_s": profile["duration_s"]}


def _mark_failed(version_id: uuid.UUID, error: str) -> None:
    with session_scope() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            return
        version.status = "failed"
        version.error = error
        dataset = version.dataset
        # A failed re-process leaves the previous good version serving queries.
        if dataset.current_version_id is None and dataset.status != "deleting":
            dataset.status = "failed"
        activity.record(
            db,
            dataset.workspace_id,
            "dataset.failed",
            "dataset",
            dataset.id,
            f"Import of {dataset.name} failed",
        )


def on_final_failure(job: Job, error: str) -> None:
    """Called once a job has permanently failed (no more retries)."""
    if job.kind in ("ingest", "materialize") and "version_id" in job.payload:
        _mark_failed(uuid.UUID(job.payload["version_id"]), error)


HANDLERS: dict[str, Callable[[Job, Progress], dict[str, Any]]] = {
    "ingest": handle_ingest,
    "profile": handle_profile,
    "materialize": handle_materialize,
}
