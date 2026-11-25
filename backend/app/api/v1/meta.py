from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DB, CurrentPrincipal
from app.core.config import get_settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(db: DB) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/settings")
def workspace_settings(_: CurrentPrincipal) -> dict[str, Any]:
    """Effective limits, shown on the Settings page."""
    s = get_settings()
    return {
        "max_upload_bytes": s.max_upload_bytes,
        "query_timeout_s": s.query_timeout_s,
        "query_memory_limit": s.query_memory_limit,
        "query_max_rows": s.query_max_rows,
        "query_page_size_max": s.query_page_size_max,
        "max_concurrent_queries": s.query_workers,
        "export_max_rows": s.export_max_rows,
        "export_link_ttl_s": s.export_link_ttl_s,
        "profile_sample_threshold": s.profile_sample_threshold,
        "supported_formats": ["csv", "tsv", "parquet"],
        "supported_encodings": ["auto", "utf-8", "utf-16", "latin-1"],
    }
