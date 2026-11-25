from fastapi import APIRouter

from app.api.deps import DB, CurrentPrincipal, Pool
from app.schemas.queries import ExplainOut, QueryExecuteIn, QueryResultOut
from app.services import queries as svc

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("/execute", response_model=QueryResultOut)
async def execute_query(
    body: QueryExecuteIn, db: DB, p: CurrentPrincipal, pool: Pool
) -> QueryResultOut:
    res = await svc.execute(
        db,
        pool,
        p.workspace_id,
        body.sql,
        offset=body.offset,
        limit=body.limit,
        saved_query_id=body.saved_query_id,
        record_history=body.record_history,
    )
    return QueryResultOut.model_validate(res)


@router.post("/explain", response_model=ExplainOut)
async def explain_query(
    body: QueryExecuteIn, db: DB, p: CurrentPrincipal, pool: Pool
) -> ExplainOut:
    return ExplainOut(plan=await svc.explain(db, pool, p.workspace_id, body.sql))
