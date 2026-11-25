"""Model -> response schema helpers that need more than ``from_attributes``."""

from app.models import Dataset, Job
from app.schemas.datasets import DatasetOut, DatasetVersionOut


def dataset_out(ds: Dataset, job: Job | None = None) -> DatasetOut:
    v = ds.current_version
    out = DatasetOut.model_validate(ds)
    if v is not None:
        out.current_version = DatasetVersionOut.model_validate(v)
        out.row_count = v.row_count
        out.column_count = v.column_count
        out.processed_bytes = v.processed_bytes
        out.source_format = v.source_format
    if job is not None:
        out.latest_job_id = job.id
        if job.status == "failed":
            out.error = job.error
    return out
