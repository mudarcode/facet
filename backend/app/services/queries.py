"""Execute untrusted SQL: validate -> resolve allowlist -> sandbox -> record history."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.sandbox import SandboxPool, SandboxRequest
from app.analytics.sql_guard import validate_query
from app.core.config import get_settings
from app.core.errors import FacetError, QueryRejected, QueryTimeout
from app.models import QueryRun
from app.services import datasets


async def execute(
    db: Session,
    pool: SandboxPool,
    workspace_id: uuid.UUID,
    sql: str,
    *,
    offset: int = 0,
    limit: int = 100,
    saved_query_id: uuid.UUID | None = None,
    record_history: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    t0 = time.perf_counter()
    run = QueryRun(workspace_id=workspace_id, sql=sql, saved_query_id=saved_query_id, status="")
    try:
        allow = datasets.queryable_datasets(db, workspace_id)
        validated = validate_query(sql, set(allow))
        req = SandboxRequest(
            sql=validated.sql,
            views={name: allow[name] for name in validated.datasets},
            memory_limit=settings.query_memory_limit,
            threads=settings.query_threads,
            timeout_s=settings.query_timeout_s,
            max_rows=max_rows or settings.query_max_rows,
            offset=offset,
            limit=min(limit, settings.query_page_size_max),
        )
        result = await pool.execute(req)
    except FacetError as e:
        run.status = (
            "rejected"
            if isinstance(e, QueryRejected)
            else "timeout"
            if isinstance(e, QueryTimeout)
            else "failed"
        )
        run.error = e.message
        run.total_ms = (time.perf_counter() - t0) * 1000
        if record_history:
            db.add(run)
            db.commit()
        raise
    total_ms = (time.perf_counter() - t0) * 1000
    run.status = "succeeded"
    run.row_count = result["total_rows"]
    run.engine_ms = result["engine_ms"]
    run.total_ms = total_ms
    if record_history:
        db.add(run)
        db.commit()
    return {
        **result,
        "max_rows": req.max_rows,
        "total_ms": total_ms,
        "datasets": sorted(validated.datasets),
        "run_id": run.id if record_history else None,
    }


async def explain(db: Session, pool: SandboxPool, workspace_id: uuid.UUID, sql: str) -> str:
    settings = get_settings()
    allow = datasets.queryable_datasets(db, workspace_id)
    validated = validate_query(sql, set(allow))
    req = SandboxRequest(
        sql=validated.sql,
        views={name: allow[name] for name in validated.datasets},
        mode="explain",
        memory_limit=settings.query_memory_limit,
        threads=settings.query_threads,
        timeout_s=settings.query_timeout_s,
    )
    res = await pool.execute(req)
    return str(res["plan"])
