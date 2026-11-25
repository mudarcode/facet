import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import InvalidInput, NotFound
from app.models import Chart, Dashboard
from app.services import activity


def _check_charts(db: Session, ws: uuid.UUID, layout: list[dict[str, Any]]) -> None:
    ids = {str(item["chart_id"]) for item in layout}
    if not ids:
        return
    found = {
        str(i)
        for i in db.scalars(
            select(Chart.id).where(
                Chart.workspace_id == ws, Chart.id.in_([uuid.UUID(x) for x in ids])
            )
        )
    }
    missing = ids - found
    if missing:
        raise InvalidInput(
            "Layout references charts that do not exist.", details={"missing": sorted(missing)}
        )
    keys = [item["i"] for item in layout]
    if len(keys) != len(set(keys)):
        raise InvalidInput("Layout item keys must be unique.")


def list_dashboards(
    db: Session, ws: uuid.UUID, limit: int, offset: int
) -> tuple[list[Dashboard], int]:
    where = Dashboard.workspace_id == ws
    total = db.scalar(select(func.count()).select_from(Dashboard).where(where)) or 0
    items = db.scalars(
        select(Dashboard)
        .where(where)
        .order_by(Dashboard.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total


def get(db: Session, ws: uuid.UUID, did: uuid.UUID) -> Dashboard:
    d = db.scalar(select(Dashboard).where(Dashboard.id == did, Dashboard.workspace_id == ws))
    if d is None:
        raise NotFound("Dashboard not found.")
    return d


def create(
    db: Session,
    ws: uuid.UUID,
    *,
    name: str,
    description: str,
    layout: list[dict[str, Any]],
    filters: list[dict[str, Any]],
) -> Dashboard:
    _check_charts(db, ws, layout)
    d = Dashboard(
        workspace_id=ws, name=name, description=description, layout=layout, filters=filters
    )
    db.add(d)
    db.flush()
    activity.record(db, ws, "dashboard.created", "dashboard", d.id, f"Created dashboard {name}")
    db.commit()
    return d


def update(db: Session, ws: uuid.UUID, did: uuid.UUID, fields: dict[str, Any]) -> Dashboard:
    d = get(db, ws, did)
    if fields.get("layout") is not None:
        _check_charts(db, ws, fields["layout"])
    for k, v in fields.items():
        if v is not None:
            setattr(d, k, v)
    db.commit()
    return d


def delete(db: Session, ws: uuid.UUID, did: uuid.UUID) -> None:
    db.delete(get(db, ws, did))
    db.commit()


def prune_chart(db: Session, ws: uuid.UUID, chart_id: uuid.UUID) -> None:
    """Remove a deleted chart from every dashboard layout in the workspace."""
    for d in db.scalars(select(Dashboard).where(Dashboard.workspace_id == ws)):
        kept = [i for i in d.layout if str(i.get("chart_id")) != str(chart_id)]
        if len(kept) != len(d.layout):
            d.layout = kept


def prune_missing(db: Session, ws: uuid.UUID) -> None:
    """Drop layout items whose chart no longer exists (e.g. its dataset was deleted)."""
    existing = {str(i) for i in db.scalars(select(Chart.id).where(Chart.workspace_id == ws))}
    for d in db.scalars(select(Dashboard).where(Dashboard.workspace_id == ws)):
        kept = [i for i in d.layout if str(i.get("chart_id")) in existing]
        if len(kept) != len(d.layout):
            d.layout = kept
    db.commit()
