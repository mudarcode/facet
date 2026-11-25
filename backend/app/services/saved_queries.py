import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import QueryRun, SavedQuery
from app.services import activity


def list_saved(db: Session, ws: uuid.UUID, limit: int, offset: int) -> tuple[list[SavedQuery], int]:
    where = SavedQuery.workspace_id == ws
    total = db.scalar(select(func.count()).select_from(SavedQuery).where(where)) or 0
    items = db.scalars(
        select(SavedQuery)
        .where(where)
        .order_by(SavedQuery.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total


def get(db: Session, ws: uuid.UUID, qid: uuid.UUID) -> SavedQuery:
    q = db.scalar(select(SavedQuery).where(SavedQuery.id == qid, SavedQuery.workspace_id == ws))
    if q is None:
        raise NotFound("Saved query not found.")
    return q


def create(db: Session, ws: uuid.UUID, *, name: str, sql: str, description: str) -> SavedQuery:
    q = SavedQuery(workspace_id=ws, name=name, sql=sql, description=description)
    db.add(q)
    db.flush()
    activity.record(db, ws, "query.saved", "query", q.id, f"Saved query {name}")
    db.commit()
    return q


def update(db: Session, ws: uuid.UUID, qid: uuid.UUID, **fields: object) -> SavedQuery:
    q = get(db, ws, qid)
    for k, v in fields.items():
        if v is not None:
            setattr(q, k, v)
    db.commit()
    return q


def delete(db: Session, ws: uuid.UUID, qid: uuid.UUID) -> None:
    db.delete(get(db, ws, qid))
    db.commit()
    from app.services import dashboards  # charts on this query were removed by FK cascade

    dashboards.prune_missing(db, ws)


def history(
    db: Session, ws: uuid.UUID, limit: int, offset: int, status: str | None = None
) -> tuple[list[QueryRun], int]:
    where = [QueryRun.workspace_id == ws]
    if status:
        where.append(QueryRun.status == status)
    total = db.scalar(select(func.count()).select_from(QueryRun).where(*where)) or 0
    items = db.scalars(
        select(QueryRun)
        .where(*where)
        .order_by(QueryRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total
