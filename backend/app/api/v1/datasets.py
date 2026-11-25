import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import ValidationError

from app.api.deps import DB, CurrentPrincipal, Limit, Offset, Pool
from app.core.errors import InvalidInput
from app.schemas.common import Page
from app.schemas.datasets import (
    ColumnSchema,
    DatasetCreated,
    DatasetOut,
    DatasetPatch,
    DatasetVersionOut,
    IngestOptionsIn,
    PreviewOut,
    ProfileOut,
    ReprocessIn,
)
from app.services import datasets as svc
from app.services import queries
from app.services.serializers import dataset_out

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DatasetCreated,
    summary="Upload a CSV or Parquet file",
    description=(
        "Send the raw file bytes as the request body (``Content-Type: "
        "application/octet-stream``). The body is streamed to storage in bounded chunks; "
        "processing happens in a background job whose id is returned."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_dataset(
    request: Request,
    db: DB,
    p: CurrentPrincipal,
    filename: Annotated[str, Query(min_length=1, max_length=500)],
    name: Annotated[str | None, Query(max_length=200)] = None,
    options: Annotated[str | None, Query(description="JSON-encoded IngestOptions")] = None,
    content_length: Annotated[int | None, Header()] = None,
) -> DatasetCreated:
    try:
        opts = IngestOptionsIn.model_validate(json.loads(options)) if options else IngestOptionsIn()
    except (json.JSONDecodeError, ValidationError) as e:
        raise InvalidInput(f"Invalid ingest options: {e}") from e
    ds, job = await svc.create_from_upload(
        db,
        p.workspace_id,
        filename=filename,
        chunks=request.stream(),
        name=name,
        options=opts.model_dump(exclude_defaults=True),
        content_length=content_length,
    )
    return DatasetCreated(dataset=dataset_out(ds, job), job_id=job.id)


@router.get("", response_model=Page[DatasetOut])
def list_datasets(
    db: DB, p: CurrentPrincipal, limit: Limit = 50, offset: Offset = 0, q: str | None = None
) -> Page[DatasetOut]:
    items, total = svc.list_datasets(db, p.workspace_id, limit=limit, offset=offset, q=q)
    latest = svc.latest_jobs(db, p.workspace_id, [d.id for d in items])
    return Page(
        items=[dataset_out(d, latest.get(str(d.id))) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> DatasetOut:
    ds = svc.get(db, p.workspace_id, dataset_id)
    job = svc.latest_jobs(db, p.workspace_id, [ds.id]).get(str(ds.id))
    out = dataset_out(ds, job)
    if ds.current_version is None:
        v = svc.latest_version(db, ds.id)
        if v is not None and v.error:
            out.error = v.error
    return out


@router.patch("/{dataset_id}", response_model=DatasetOut)
def patch_dataset(
    dataset_id: uuid.UUID, body: DatasetPatch, db: DB, p: CurrentPrincipal
) -> DatasetOut:
    ds = svc.update(db, p.workspace_id, dataset_id, **body.model_dump(exclude_unset=True))
    return dataset_out(ds)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> None:
    svc.delete(db, p.workspace_id, dataset_id)


@router.get("/{dataset_id}/schema", response_model=list[ColumnSchema])
def get_schema(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> list[ColumnSchema]:
    ds = svc.get(db, p.workspace_id, dataset_id)
    if ds.current_version is None or not ds.current_version.schema_json:
        raise InvalidInput("Dataset has not finished processing.", code="not_ready")
    return [ColumnSchema.model_validate(c) for c in ds.current_version.schema_json]


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionOut])
def list_versions(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> list[DatasetVersionOut]:
    ds = svc.get(db, p.workspace_id, dataset_id)
    db.refresh(ds, ["versions"])
    return [
        DatasetVersionOut.model_validate(v)
        for v in sorted(ds.versions, key=lambda v: v.version, reverse=True)
    ]


@router.post("/{dataset_id}/reprocess", status_code=202, response_model=DatasetCreated)
def reprocess(
    dataset_id: uuid.UUID, body: ReprocessIn, db: DB, p: CurrentPrincipal
) -> DatasetCreated:
    ds, job = svc.reprocess(
        db, p.workspace_id, dataset_id, body.options.model_dump(exclude_defaults=True)
    )
    return DatasetCreated(dataset=dataset_out(ds, job), job_id=job.id)


@router.get("/{dataset_id}/preview", response_model=PreviewOut)
async def preview(
    dataset_id: uuid.UUID,
    db: DB,
    p: CurrentPrincipal,
    pool: Pool,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Offset = 0,
) -> PreviewOut:
    ds = svc.get(db, p.workspace_id, dataset_id)
    if ds.status != "ready":
        raise InvalidInput("Dataset has not finished processing.", code="not_ready")
    # Previews go through the same validated sandbox path as user SQL.
    res = await queries.execute(
        db,
        pool,
        p.workspace_id,
        f'SELECT * FROM "{ds.sql_name}"',
        offset=offset,
        limit=limit,
        record_history=False,
        max_rows=offset + limit,
    )
    total = ds.current_version.row_count if ds.current_version else res["total_rows"]
    return PreviewOut(
        columns=res["columns"],
        rows=res["rows"],
        total_rows=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{dataset_id}/profile", response_model=ProfileOut)
def get_profile(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> ProfileOut:
    """Column statistics for the current version, computed by a background job."""
    ds = svc.get(db, p.workspace_id, dataset_id)
    v = ds.current_version
    if v is None:
        raise InvalidInput("Dataset has not finished processing.", code="not_ready")
    if v.profile_json is not None:
        return ProfileOut(status="ready", version_id=v.id, profile=v.profile_json)
    job = svc.profile_job(db, p.workspace_id, v.id)
    if job is None:
        job = svc.request_profile(db, p.workspace_id, ds)
    status = "failed" if job.status == "failed" else "pending"
    return ProfileOut(status=status, version_id=v.id, job_id=job.id, error=job.error)


@router.post("/{dataset_id}/profile", status_code=202, response_model=ProfileOut)
def refresh_profile(dataset_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> ProfileOut:
    ds = svc.get(db, p.workspace_id, dataset_id)
    if ds.current_version is None:
        raise InvalidInput("Dataset has not finished processing.", code="not_ready")
    job = svc.request_profile(db, p.workspace_id, ds, force=True)
    return ProfileOut(status="pending", version_id=ds.current_version.id, job_id=job.id)
