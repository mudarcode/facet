"""Chart persistence and data: resolve a source, compile the spec, run it in the sandbox."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.charts import MAX_POINTS, ChartSpec, compile_chart
from app.analytics.engine import quote_ident
from app.analytics.sandbox import SandboxPool
from app.analytics.sql_guard import validate_query
from app.analytics.transforms import Condition
from app.core.errors import InvalidInput, NotFound
from app.models import Chart, Dataset, SavedQuery
from app.services import activity, queries
from app.services import datasets as ds_svc
from app.services import saved_queries as sq_svc


async def resolve_source(
    db: Session,
    pool: SandboxPool,
    ws: uuid.UUID,
    dataset_id: uuid.UUID | None,
    saved_query_id: uuid.UUID | None,
) -> tuple[str, list[dict[str, str]], str]:
    """Return (relation SQL, schema, display name) for a chart source owned by ``ws``."""
    if dataset_id is not None:
        ds = ds_svc.get(db, ws, dataset_id)
        v = ds.current_version
        if ds.status != "ready" or v is None or not v.schema_json:
            raise InvalidInput("Dataset has not finished processing.", code="not_ready")
        return (
            quote_ident(ds.sql_name),
            [{"name": c["name"], "type": c["type"]} for c in v.schema_json],
            ds.name,
        )
    assert saved_query_id is not None
    sq = sq_svc.get(db, ws, saved_query_id)
    # Re-render through the guard first: strips comments/trailing semicolons so the query
    # can be embedded as a subquery, and rejects it early if it is not a read-only SELECT.
    inner = validate_query(sq.sql, set(ds_svc.queryable_datasets(db, ws))).sql
    # Discover the saved query's output columns (the guard validates it like any query).
    res = await queries.execute(
        db, pool, ws, f"SELECT * FROM ({inner}) AS q LIMIT 0", limit=1, record_history=False
    )
    return f"({inner})", list(res["columns"]), sq.name


async def chart_data(
    db: Session,
    pool: SandboxPool,
    ws: uuid.UUID,
    *,
    dataset_id: uuid.UUID | None,
    saved_query_id: uuid.UUID | None,
    spec: ChartSpec,
    filters: list[Condition] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    relation, schema, _ = await resolve_source(db, pool, ws, dataset_id, saved_query_id)
    sql, meta = compile_chart(relation, spec, schema, filters)
    res = await queries.execute(
        db,
        pool,
        ws,
        sql,
        max_rows=MAX_POINTS,
        record_history=False,
        page_size=MAX_POINTS,
    )
    return {
        "columns": res["columns"],
        "rows": res["rows"],
        "meta": {**meta, "truncated": res["truncated"]},
        "sql": sql,
        "engine_ms": res["engine_ms"],
        "total_ms": (time.perf_counter() - t0) * 1000,
    }


def list_charts(db: Session, ws: uuid.UUID) -> list[tuple[Chart, str | None]]:
    rows = db.execute(
        select(Chart, Dataset.name, SavedQuery.name)
        .outerjoin(Dataset, Dataset.id == Chart.dataset_id)
        .outerjoin(SavedQuery, SavedQuery.id == Chart.saved_query_id)
        .where(Chart.workspace_id == ws)
        .order_by(Chart.updated_at.desc())
    ).all()
    return [(c, dn or qn) for c, dn, qn in rows]


def get(db: Session, ws: uuid.UUID, chart_id: uuid.UUID) -> Chart:
    c = db.scalar(select(Chart).where(Chart.id == chart_id, Chart.workspace_id == ws))
    if c is None:
        raise NotFound("Chart not found.")
    return c


async def create(
    db: Session,
    pool: SandboxPool,
    ws: uuid.UUID,
    *,
    name: str,
    dataset_id: uuid.UUID | None,
    saved_query_id: uuid.UUID | None,
    spec: ChartSpec,
) -> Chart:
    relation, schema, _ = await resolve_source(db, pool, ws, dataset_id, saved_query_id)
    compile_chart(relation, spec, schema)  # validate fields against the source
    c = Chart(
        workspace_id=ws,
        name=name,
        dataset_id=dataset_id,
        saved_query_id=saved_query_id,
        spec=spec.model_dump(mode="json"),
    )
    db.add(c)
    db.flush()
    activity.record(db, ws, "chart.saved", "chart", c.id, f"Saved chart {name}")
    db.commit()
    return c


async def update(
    db: Session,
    pool: SandboxPool,
    ws: uuid.UUID,
    chart_id: uuid.UUID,
    name: str | None,
    spec: ChartSpec | None,
) -> Chart:
    c = get(db, ws, chart_id)
    if spec is not None:
        relation, schema, _ = await resolve_source(db, pool, ws, c.dataset_id, c.saved_query_id)
        compile_chart(relation, spec, schema)
        c.spec = spec.model_dump(mode="json")
    if name is not None:
        c.name = name
    db.commit()
    return c


def delete(db: Session, ws: uuid.UUID, chart_id: uuid.UUID) -> None:
    db.delete(get(db, ws, chart_id))
    db.commit()
