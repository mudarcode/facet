import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentPrincipal, Limit, Offset, Pool
from app.schemas.common import Page
from app.schemas.queries import (
    ExplainOut,
    QueryExecuteIn,
    QueryResultOut,
    QueryRunOut,
    SavedQueryIn,
    SavedQueryOut,
    SavedQueryPatch,
)
from app.services import queries as svc
from app.services import saved_queries as saved

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("/execute", response_model=QueryResultOut)
async def execute_query(
    body: QueryExecuteIn, db: DB, p: CurrentPrincipal, pool: Pool
) -> QueryResultOut:
    """Validate and run read-only SQL over the caller's datasets in the DuckDB sandbox."""
    if body.saved_query_id:
        saved.get(db, p.workspace_id, body.saved_query_id)  # ownership check
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


@router.get("/history", response_model=Page[QueryRunOut])
def query_history(
    db: DB,
    p: CurrentPrincipal,
    limit: Limit = 50,
    offset: Offset = 0,
    status: Annotated[str | None, Query(pattern="^(succeeded|failed|rejected|timeout)$")] = None,
) -> Page[QueryRunOut]:
    items, total = saved.history(db, p.workspace_id, limit, offset, status)
    return Page(
        items=[QueryRunOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=Page[SavedQueryOut])
def list_saved_queries(
    db: DB, p: CurrentPrincipal, limit: Limit = 50, offset: Offset = 0
) -> Page[SavedQueryOut]:
    items, total = saved.list_saved(db, p.workspace_id, limit, offset)
    return Page(
        items=[SavedQueryOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SavedQueryOut)
def create_saved_query(body: SavedQueryIn, db: DB, p: CurrentPrincipal) -> SavedQueryOut:
    q = saved.create(db, p.workspace_id, name=body.name, sql=body.sql, description=body.description)
    return SavedQueryOut.model_validate(q)


@router.get("/{query_id}", response_model=SavedQueryOut)
def get_saved_query(query_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> SavedQueryOut:
    return SavedQueryOut.model_validate(saved.get(db, p.workspace_id, query_id))


@router.patch("/{query_id}", response_model=SavedQueryOut)
def update_saved_query(
    query_id: uuid.UUID, body: SavedQueryPatch, db: DB, p: CurrentPrincipal
) -> SavedQueryOut:
    q = saved.update(db, p.workspace_id, query_id, **body.model_dump(exclude_unset=True))
    return SavedQueryOut.model_validate(q)


@router.delete("/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_query(query_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> None:
    saved.delete(db, p.workspace_id, query_id)
