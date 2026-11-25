import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentPrincipal, Pool
from app.schemas.transformations import (
    MaterializeIn,
    MaterializeOut,
    TransformationIn,
    TransformationOut,
    TransformationPatch,
    TransformPreviewIn,
    TransformPreviewOut,
)
from app.services import datasets as ds_svc
from app.services import transformations as svc

router = APIRouter(prefix="/transformations", tags=["transformations"])


def _out(db: DB, p: CurrentPrincipal, t: object) -> TransformationOut:
    out = TransformationOut.model_validate(t)
    try:
        out.sql, _ = svc.compile_for(ds_svc.get(db, p.workspace_id, out.dataset_id), out.steps)
    except Exception:  # source dataset re-imported with different columns
        out.sql = None
    derived = svc.output_dataset(db, p.workspace_id, out.id)
    out.output_dataset_id = derived.id if derived else None
    return out


@router.post("/preview", response_model=TransformPreviewOut)
async def preview(
    body: TransformPreviewIn, db: DB, p: CurrentPrincipal, pool: Pool
) -> TransformPreviewOut:
    """Compile steps to SQL and run them through the same sandbox as user queries."""
    res = await svc.preview(
        db, pool, p.workspace_id, body.dataset_id, list(body.steps), body.offset, body.limit
    )
    return TransformPreviewOut.model_validate(res)


@router.get("", response_model=list[TransformationOut])
def list_transformations(
    db: DB, p: CurrentPrincipal, dataset_id: uuid.UUID | None = None
) -> list[TransformationOut]:
    return [_out(db, p, t) for t in svc.list_for(db, p.workspace_id, dataset_id)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransformationOut)
def create_transformation(body: TransformationIn, db: DB, p: CurrentPrincipal) -> TransformationOut:
    t = svc.create(db, p.workspace_id, body.dataset_id, body.name, list(body.steps))
    return _out(db, p, t)


@router.get("/{transformation_id}", response_model=TransformationOut)
def get_transformation(
    transformation_id: uuid.UUID, db: DB, p: CurrentPrincipal
) -> TransformationOut:
    return _out(db, p, svc.get(db, p.workspace_id, transformation_id))


@router.patch("/{transformation_id}", response_model=TransformationOut)
def update_transformation(
    transformation_id: uuid.UUID, body: TransformationPatch, db: DB, p: CurrentPrincipal
) -> TransformationOut:
    t = svc.update(
        db,
        p.workspace_id,
        transformation_id,
        body.name,
        list(body.steps) if body.steps is not None else None,
    )
    return _out(db, p, t)


@router.delete("/{transformation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transformation(transformation_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> None:
    svc.delete(db, p.workspace_id, transformation_id)


@router.post("/{transformation_id}/materialize", status_code=202, response_model=MaterializeOut)
def materialize(
    transformation_id: uuid.UUID, body: MaterializeIn, db: DB, p: CurrentPrincipal
) -> MaterializeOut:
    """Apply the saved plan and store the output as a dataset (re-running adds a version)."""
    ds, job = svc.materialize(db, p.workspace_id, transformation_id, body.name)
    return MaterializeOut(dataset_id=ds.id, job_id=job.id)
