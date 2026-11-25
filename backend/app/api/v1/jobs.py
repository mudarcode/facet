import uuid

from fastapi import APIRouter

from app.api.deps import DB, CurrentPrincipal
from app.core.errors import NotFound
from app.schemas.jobs import JobOut
from app.services import jobs as svc

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DB, p: CurrentPrincipal) -> JobOut:
    job = svc.get_for_workspace(db, job_id, p.workspace_id)
    if job is None:
        raise NotFound("Job not found.")
    return JobOut.model_validate(job)
