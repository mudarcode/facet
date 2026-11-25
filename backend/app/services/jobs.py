"""PostgreSQL-backed job queue (see docs/decisions/0002-postgres-job-queue.md).

* ``enqueue`` inserts in the caller's transaction, so a job exists iff the
  metadata it refers to was committed.
* ``claim`` uses ``FOR UPDATE SKIP LOCKED`` so many workers can poll safely.
* Running jobs hold a lease; workers heartbeat to extend it. A job whose lease
  expired (worker crashed / was killed) becomes claimable again until
  ``max_attempts`` is reached, then it is failed.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Job
from app.models.base import utcnow

TERMINAL = {"succeeded", "failed", "cancelled"}


def enqueue(db: Session, workspace_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> Job:
    job = Job(
        workspace_id=workspace_id,
        kind=kind,
        payload=payload,
        status="queued",
        max_attempts=get_settings().job_max_attempts,
        run_after=utcnow(),
    )
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str, kinds: list[str] | None = None) -> Job | None:
    """Atomically claim the oldest runnable job. Commits."""
    now = utcnow()
    lease = timedelta(seconds=get_settings().job_lease_s)
    runnable = or_(
        (Job.status == "queued") & ((Job.run_after.is_(None)) | (Job.run_after <= now)),
        (Job.status == "running")
        & (Job.lease_expires_at < now)
        & (Job.attempts < Job.max_attempts),
    )
    q = (
        select(Job)
        .where(runnable)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if kinds:
        q = q.where(Job.kind.in_(kinds))
    job = db.scalar(q)
    if job is None:
        db.commit()
        return None
    job.status = "running"
    job.attempts += 1
    job.worker_id = worker_id
    job.started_at = job.started_at or now
    job.lease_expires_at = now + lease
    job.message = "Starting"
    db.commit()
    return job


def reap_exhausted(db: Session) -> list[Job]:
    """Fail running jobs whose lease expired on their final attempt (crash-looping input).

    Returns the newly failed jobs so the caller can run kind-specific cleanup.
    """
    now = utcnow()
    rows = list(
        db.scalars(
            select(Job)
            .where(
                Job.status == "running",
                Job.lease_expires_at < now,
                Job.attempts >= Job.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for job in rows:
        job.status = "failed"
        job.error = job.error or "Worker stopped responding on the final attempt."
        job.message = "Failed"
        job.finished_at = now
        job.lease_expires_at = None
    db.commit()
    return rows


def heartbeat(
    db: Session, job_id: uuid.UUID, worker_id: str, progress: float, message: str
) -> bool:
    """Extend the lease and record progress. Returns False if we lost the job."""
    lease = timedelta(seconds=get_settings().job_lease_s)
    res = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.worker_id == worker_id, Job.status == "running")
        .values(
            progress=max(0.0, min(progress, 1.0)),
            message=message[:500],
            lease_expires_at=utcnow() + lease,
        )
    )
    db.commit()
    return bool(res.rowcount)  # type: ignore[attr-defined]


def complete(db: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = "succeeded"
    job.progress = 1.0
    job.message = "Done"
    job.result = result
    job.finished_at = utcnow()
    job.lease_expires_at = None


def fail(db: Session, job: Job, error: str, *, retry: bool = False) -> None:
    job.error = error[:4000]
    job.lease_expires_at = None
    if retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = utcnow() + timedelta(seconds=2**job.attempts)
        job.message = "Retrying"
    else:
        job.status = "failed"
        job.message = "Failed"
        job.finished_at = utcnow()


def get_for_workspace(db: Session, job_id: uuid.UUID, workspace_id: uuid.UUID) -> Job | None:
    return db.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id))
