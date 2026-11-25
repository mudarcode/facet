import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentPrincipal, Limit, Offset
from app.schemas.common import Page
from app.schemas.visuals import DashboardIn, DashboardOut, DashboardPatch
from app.services import dashboards as svc

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("", response_model=Page[DashboardOut])
def list_dashboards(
    db: DB, p: CurrentPrincipal, limit: Limit = 50, offset: Offset = 0
) -> Page[DashboardOut]:
    items, total = svc.list_dashboards(db, p.workspace_id, limit, offset)
    return Page(
        items=[DashboardOut.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DashboardOut)
def create_dashboard(body: DashboardIn, db: DB, p: CurrentPrincipal) -> DashboardOut:
    d = svc.create(
        db,
        p.workspace_id,
        name=body.name,
        description=body.description,
        layout=[i.model_dump(mode="json") for i in body.layout],
        filters=[f.model_dump(mode="json") for f in body.filters],
    )
    return DashboardOut.model_validate(d)


@router.get("/{dashboard_id}", response_model=DashboardOut)
def get_dashboard(dashboard_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> DashboardOut:
    return DashboardOut.model_validate(svc.get(db, p.workspace_id, dashboard_id))


@router.patch("/{dashboard_id}", response_model=DashboardOut)
def update_dashboard(
    dashboard_id: uuid.UUID, body: DashboardPatch, db: DB, p: CurrentPrincipal
) -> DashboardOut:
    fields = body.model_dump(mode="json", exclude_unset=True)
    return DashboardOut.model_validate(svc.update(db, p.workspace_id, dashboard_id, fields))


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard(dashboard_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> None:
    svc.delete(db, p.workspace_id, dashboard_id)
