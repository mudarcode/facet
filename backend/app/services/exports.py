"""Exports run as background jobs and are downloaded through short-lived signed links."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.sql_guard import validate_query
from app.core.config import get_settings
from app.core.errors import NotFound, Unauthorized
from app.models import Export
from app.services import activity, jobs
from app.services import charts as chart_svc
from app.services import datasets as ds_svc
from app.storage import get_storage


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")[:60] or "export"


def create(db: Session, ws: uuid.UUID, source: dict[str, Any], fmt: str) -> Export:
    kind = source["kind"]
    if kind == "dataset":
        ds = ds_svc.get(db, ws, uuid.UUID(str(source["dataset_id"])))
        base = ds.sql_name
    elif kind == "chart":
        c = chart_svc.get(db, ws, uuid.UUID(str(source["chart_id"])))
        base = _slug(c.name)
    else:
        # Reject non-read-only SQL up front; the worker validates again before running it.
        validate_query(str(source["sql"]), set(ds_svc.queryable_datasets(db, ws)))
        base = "query_result"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    exp = Export(
        workspace_id=ws,
        source={
            k: (str(v) if isinstance(v, uuid.UUID) else v)
            for k, v in source.items()
            if v is not None
        },
        format=fmt,
        status="queued",
        filename=f"{base}-{stamp}.{fmt}",
    )
    db.add(exp)
    db.flush()
    job = jobs.enqueue(db, ws, "export", {"export_id": str(exp.id)})
    exp.job_id = job.id
    activity.record(db, ws, "export.requested", "export", exp.id, f"Exporting {exp.filename}")
    db.commit()
    return exp


def get(db: Session, ws: uuid.UUID, export_id: uuid.UUID) -> Export:
    e = db.scalar(select(Export).where(Export.id == export_id, Export.workspace_id == ws))
    if e is None:
        raise NotFound("Export not found.")
    return e


def _sig(export_id: str, expires: int) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{export_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def signed_url(export_id: uuid.UUID) -> str:
    expires = int(time.time()) + get_settings().export_link_ttl_s
    sig = _sig(str(export_id), expires)
    return f"/api/v1/exports/{export_id}/download?expires={expires}&sig={sig}"


def verify(export_id: uuid.UUID, expires: int, sig: str) -> None:
    if expires < time.time():
        raise Unauthorized("Download link expired.")
    if not hmac.compare_digest(_sig(str(export_id), expires), sig):
        raise Unauthorized("Invalid download link.")


def sweep_expired(db: Session, now: datetime | None = None) -> int:
    """Delete export files past the retention window; the row stays as history."""
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=get_settings().export_retention_s)
    stale = db.scalars(
        select(Export).where(Export.created_at < cutoff, Export.storage_key.is_not(None))
    ).all()
    storage = get_storage()
    for e in stale:
        storage.delete(e.storage_key)  # type: ignore[arg-type]
        e.storage_key = None
        if e.status == "succeeded":
            e.status = "expired"
    db.commit()
    return len(stale)
