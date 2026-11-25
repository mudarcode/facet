"""Job handlers. Each receives the claimed job and a progress callback."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.analytics.ingest import IngestError, IngestOptions, ingest_file
from app.core.config import get_settings
from app.core.db import session_scope
from app.models import Dataset, DatasetVersion, Job
from app.services import activity
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

    # Atomic registration: the Parquet file is moved into place first, then one DB
    # transaction flips the version to ready and points the dataset at it. A crash
    # between the two leaves an unreferenced file (cleaned with the dataset) but never
    # a "ready" dataset pointing at a missing or partial file.
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
    return {
        "dataset_id": str(dataset_id),
        "version_id": str(version_id),
        "row_count": result.row_count,
        "duration_s": result.duration_s,
    }


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
    if job.kind == "ingest" and "version_id" in job.payload:
        _mark_failed(uuid.UUID(job.payload["version_id"]), error)


HANDLERS: dict[str, Callable[[Job, Progress], dict[str, Any]]] = {
    "ingest": handle_ingest,
}
