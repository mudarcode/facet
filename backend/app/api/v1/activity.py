import uuid
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentPrincipal, Limit
from app.models import ActivityEvent, Chart, Dashboard, Dataset, SavedQuery
from app.schemas.common import ApiModel

router = APIRouter(tags=["activity"])


class ActivityOut(ApiModel):
    id: uuid.UUID
    kind: str
    subject_type: str
    subject_id: uuid.UUID | None
    summary: str
    created_at: datetime


class WorkspaceSummary(ApiModel):
    datasets: int
    saved_queries: int
    charts: int
    dashboards: int


@router.get("/activity", response_model=list[ActivityOut])
def recent_activity(db: DB, p: CurrentPrincipal, limit: Limit = 20) -> list[ActivityOut]:
    """Most recent workspace events, newest first (for the home page)."""
    rows = db.scalars(
        select(ActivityEvent)
        .where(ActivityEvent.workspace_id == p.workspace_id)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id)
        .limit(limit)
    )
    return [ActivityOut.model_validate(r) for r in rows]


@router.get("/workspace/summary", response_model=WorkspaceSummary)
def summary(db: DB, p: CurrentPrincipal) -> WorkspaceSummary:
    def count(model: type, *extra: object) -> int:
        q = select(func.count()).select_from(model).where(model.workspace_id == p.workspace_id)  # type: ignore[attr-defined]
        for cond in extra:
            q = q.where(cond)  # type: ignore[arg-type]
        return int(db.scalar(q) or 0)

    return WorkspaceSummary(
        datasets=count(Dataset, Dataset.status != "deleting"),
        saved_queries=count(SavedQuery),
        charts=count(Chart),
        dashboards=count(Dashboard),
    )
