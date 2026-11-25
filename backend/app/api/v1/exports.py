import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse

from app.api.deps import DB, CurrentPrincipal
from app.core.errors import InvalidInput, NotFound
from app.models import Export
from app.schemas.visuals import ExportIn, ExportOut
from app.services import exports as svc
from app.storage import get_storage

router = APIRouter(prefix="/exports", tags=["exports"])


def _out(e: Export) -> ExportOut:
    o = ExportOut.model_validate(e)
    if e.status == "succeeded":
        o.download_url = svc.signed_url(e.id)
    return o


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ExportOut)
def create_export(body: ExportIn, db: DB, p: CurrentPrincipal) -> ExportOut:
    """Queue an export of a query result, a dataset or a chart's data (CSV or Parquet)."""
    return _out(svc.create(db, p.workspace_id, body.source.model_dump(mode="json"), body.format))


@router.get("/{export_id}", response_model=ExportOut)
def get_export(export_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> ExportOut:
    return _out(svc.get(db, p.workspace_id, export_id))


@router.get("/{export_id}/download", response_class=FileResponse)
def download_export(
    export_id: uuid.UUID,
    db: DB,
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query(min_length=64, max_length=64)],
) -> FileResponse:
    """Download via a short-lived HMAC-signed link (lets the browser download natively)."""
    svc.verify(export_id, expires, sig)
    e = db.get(Export, export_id)
    if e is None or e.storage_key is None:
        raise NotFound("Export not found.")
    if e.status != "succeeded":
        raise InvalidInput("Export is not ready.")
    media = "text/csv" if e.format == "csv" else "application/vnd.apache.parquet"
    return FileResponse(
        get_storage().local_path(e.storage_key), media_type=media, filename=e.filename
    )
