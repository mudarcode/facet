"""Saved transformation plans: preview through the sandbox, materialise as new datasets."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.sandbox import SandboxPool
from app.analytics.transforms import Plan, Step, compile_plan
from app.core.errors import InvalidInput, NotFound
from app.models import Dataset, DatasetVersion, Job, Transformation
from app.services import activity, jobs, queries
from app.services import datasets as ds_svc

_steps = TypeAdapter(list[Step])


def _columns(ds: Dataset) -> list[str]:
    v = ds.current_version
    if v is None or ds.status != "ready" or not v.schema_json:
        raise InvalidInput("Dataset has not finished processing.", code="not_ready")
    return [c["name"] for c in v.schema_json]


def compile_for(ds: Dataset, steps: list[Any]) -> tuple[str, list[str]]:
    plan = Plan(steps=_steps.validate_python(steps))
    return compile_plan(ds.sql_name, _columns(ds), plan)


async def preview(
    db: Session,
    pool: SandboxPool,
    ws: uuid.UUID,
    dataset_id: uuid.UUID,
    steps: list[Any],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    ds = ds_svc.get(db, ws, dataset_id)
    sql, _ = compile_for(ds, [s.model_dump() if hasattr(s, "model_dump") else s for s in steps])
    res = await queries.execute(db, pool, ws, sql, offset=offset, limit=limit, record_history=False)
    return {**res, "sql": sql}


def list_for(db: Session, ws: uuid.UUID, dataset_id: uuid.UUID | None) -> list[Transformation]:
    q = select(Transformation).where(Transformation.workspace_id == ws)
    if dataset_id:
        q = q.where(Transformation.dataset_id == dataset_id)
    return list(db.scalars(q.order_by(Transformation.updated_at.desc())))


def get(db: Session, ws: uuid.UUID, tid: uuid.UUID) -> Transformation:
    t = db.scalar(
        select(Transformation).where(Transformation.id == tid, Transformation.workspace_id == ws)
    )
    if t is None:
        raise NotFound("Transformation not found.")
    return t


def create(
    db: Session, ws: uuid.UUID, dataset_id: uuid.UUID, name: str, steps: list[Any]
) -> Transformation:
    ds = ds_svc.get(db, ws, dataset_id)
    dumped = [s.model_dump() for s in steps]
    compile_for(ds, dumped)  # validate before saving
    t = Transformation(workspace_id=ws, dataset_id=ds.id, name=name, steps=dumped)
    db.add(t)
    db.flush()
    activity.record(
        db, ws, "transformation.saved", "transformation", t.id, f"Saved transformation {name}"
    )
    db.commit()
    return t


def update(
    db: Session, ws: uuid.UUID, tid: uuid.UUID, name: str | None, steps: list[Any] | None
) -> Transformation:
    t = get(db, ws, tid)
    if steps is not None:
        dumped = [s.model_dump() for s in steps]
        compile_for(ds_svc.get(db, ws, t.dataset_id), dumped)
        t.steps = dumped
    if name is not None:
        t.name = name
    db.commit()
    return t


def delete(db: Session, ws: uuid.UUID, tid: uuid.UUID) -> None:
    db.delete(get(db, ws, tid))
    db.commit()


def output_dataset(db: Session, ws: uuid.UUID, tid: uuid.UUID) -> Dataset | None:
    return db.scalar(
        select(Dataset).where(
            Dataset.workspace_id == ws,
            Dataset.source_transformation_id == tid,
            Dataset.status != "deleting",
        )
    )


def materialize(
    db: Session, ws: uuid.UUID, tid: uuid.UUID, name: str | None
) -> tuple[Dataset, Job]:
    """Run the plan to a new Parquet dataset (or a new version of its previous output)."""
    t = get(db, ws, tid)
    src = ds_svc.get(db, ws, t.dataset_id)
    compile_for(src, t.steps)  # fail fast on an invalid plan
    out = output_dataset(db, ws, t.id)
    if out is None:
        display = name or f"{src.name} · {t.name}"
        out = Dataset(
            workspace_id=ws,
            name=display[:200],
            sql_name=ds_svc.unique_sql_name(db, ws, ds_svc.slugify_sql_name(display)),
            status="pending",
            source_transformation_id=t.id,
            description=f"Derived from {src.name} by transformation '{t.name}'.",
        )
        db.add(out)
        db.flush()
        next_no = 1
    else:
        latest = ds_svc.latest_version(db, out.id)
        next_no = (latest.version if latest else 0) + 1
    version = DatasetVersion(
        dataset_id=out.id,
        version=next_no,
        status="pending",
        source_format="derived",
        original_filename="",
        ingest_options={"transformation_id": str(t.id), "source_dataset_id": str(src.id)},
    )
    db.add(version)
    db.flush()
    job = jobs.enqueue(
        db,
        ws,
        "materialize",
        {"dataset_id": str(out.id), "version_id": str(version.id), "transformation_id": str(t.id)},
    )
    activity.record(
        db, ws, "transformation.applied", "dataset", out.id, f"Applied {t.name} → {out.name}"
    )
    db.commit()
    return out, job
