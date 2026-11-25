import uuid

from fastapi import APIRouter, status

from app.analytics.charts import ChartSpec
from app.api.deps import DB, CurrentPrincipal, Pool
from app.schemas.visuals import (
    ChartDataFilters,
    ChartDataIn,
    ChartDataOut,
    ChartIn,
    ChartOut,
    ChartPatch,
    ChartSource,
    SourceColumnsOut,
)
from app.services import charts as svc
from app.services import dashboards as dash_svc

router = APIRouter(prefix="/charts", tags=["charts"])


@router.post("/source-columns", response_model=SourceColumnsOut)
async def source_columns(
    body: ChartSource, db: DB, p: CurrentPrincipal, pool: Pool
) -> SourceColumnsOut:
    """Columns (name + DuckDB type) of a dataset or saved query, for field mapping."""
    _, schema, _ = await svc.resolve_source(
        db, pool, p.workspace_id, body.dataset_id, body.saved_query_id
    )
    return SourceColumnsOut.model_validate({"columns": schema})


@router.post("/data", response_model=ChartDataOut)
async def preview_data(body: ChartDataIn, db: DB, p: CurrentPrincipal, pool: Pool) -> ChartDataOut:
    """Compile an unsaved chart spec and return its aggregated data (live preview)."""
    res = await svc.chart_data(
        db,
        pool,
        p.workspace_id,
        dataset_id=body.dataset_id,
        saved_query_id=body.saved_query_id,
        spec=body.spec,
        filters=body.filters,
    )
    return ChartDataOut.model_validate(res)


@router.get("", response_model=list[ChartOut])
def list_charts(db: DB, p: CurrentPrincipal) -> list[ChartOut]:
    out = []
    for c, source_name in svc.list_charts(db, p.workspace_id):
        o = ChartOut.model_validate(c)
        o.source_name = source_name
        out.append(o)
    return out


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChartOut)
async def create_chart(body: ChartIn, db: DB, p: CurrentPrincipal, pool: Pool) -> ChartOut:
    c = await svc.create(
        db,
        pool,
        p.workspace_id,
        name=body.name,
        dataset_id=body.dataset_id,
        saved_query_id=body.saved_query_id,
        spec=body.spec,
    )
    return ChartOut.model_validate(c)


@router.get("/{chart_id}", response_model=ChartOut)
def get_chart(chart_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> ChartOut:
    return ChartOut.model_validate(svc.get(db, p.workspace_id, chart_id))


@router.patch("/{chart_id}", response_model=ChartOut)
async def update_chart(
    chart_id: uuid.UUID, body: ChartPatch, db: DB, p: CurrentPrincipal, pool: Pool
) -> ChartOut:
    c = await svc.update(db, pool, p.workspace_id, chart_id, body.name, body.spec)
    return ChartOut.model_validate(c)


@router.delete("/{chart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chart(chart_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> None:
    svc.delete(db, p.workspace_id, chart_id)
    dash_svc.prune_missing(db, p.workspace_id)


@router.post("/{chart_id}/data", response_model=ChartDataOut)
async def saved_chart_data(
    chart_id: uuid.UUID,
    db: DB,
    p: CurrentPrincipal,
    pool: Pool,
    body: ChartDataFilters | None = None,
) -> ChartDataOut:
    """Data for a saved chart, optionally narrowed by dashboard-level filters."""
    c = svc.get(db, p.workspace_id, chart_id)
    res = await svc.chart_data(
        db,
        pool,
        p.workspace_id,
        dataset_id=c.dataset_id,
        saved_query_id=c.saved_query_id,
        spec=ChartSpec.model_validate(c.spec),
        filters=body.filters if body else [],
    )
    return ChartDataOut.model_validate(res)
