"""Job queue state transitions, retries and crash recovery against real PostgreSQL."""

from datetime import timedelta

from sqlalchemy import select, update

from app.core.db import get_sessionmaker
from app.models import Dataset, Job
from app.models.base import utcnow
from app.services import jobs
from app.workers.main import Worker
from tests.conftest import DEV, upload


def _job(job_id):
    with get_sessionmaker()() as db:
        return db.get(Job, job_id)


def test_ingest_job_lifecycle(client):
    created = upload(client, b"a,b\n1,2\n", "j.csv")
    job_id = created["job_id"]
    j = client.get(f"/api/v1/jobs/{job_id}", headers=DEV).json()
    assert j["status"] == "queued" and j["attempts"] == 0
    assert Worker("w1").run_once()
    j = client.get(f"/api/v1/jobs/{job_id}", headers=DEV).json()
    assert j["status"] == "succeeded"
    assert j["progress"] == 1.0
    assert j["attempts"] == 1
    assert j["result"]["row_count"] == 1
    assert j["started_at"] and j["finished_at"]


def test_skip_locked_claims_each_job_once(client):
    for i in range(3):
        upload(client, f"a\n{i}\n".encode(), f"f{i}.csv")
    with get_sessionmaker()() as a, get_sessionmaker()() as b:
        j1 = jobs.claim(a, "A")
        j2 = jobs.claim(b, "B")
        assert j1 and j2 and j1.id != j2.id


def test_expired_lease_is_reclaimed_after_worker_crash(client):
    created = upload(client, b"a\n1\n", "c.csv")
    with get_sessionmaker()() as db:
        job = jobs.claim(db, "crashed-worker")
        assert job is not None and job.attempts == 1
        # Simulate the worker dying: its lease lapses without completion.
        db.execute(update(Job).where(Job.id == job.id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert Worker("rescuer").run_once()
    j = _job(created["job_id"])
    assert j.status == "succeeded"
    assert j.attempts == 2
    assert j.worker_id == "rescuer"


def test_exhausted_job_fails_and_marks_dataset(client):
    created = upload(client, b"a\n1\n", "x.csv")
    with get_sessionmaker()() as db:
        db.execute(
            update(Job)
            .where(Job.id == created["job_id"])
            .values(status="running", attempts=3, lease_expires_at=utcnow() - timedelta(seconds=1))
        )
        db.commit()
    Worker("w").run_once()
    assert _job(created["job_id"]).status == "failed"
    with get_sessionmaker()() as db:
        ds = db.get(Dataset, created["dataset"]["id"])
        assert ds.status == "failed"


def test_transient_failure_is_retried_with_backoff(client, monkeypatch):
    from app.workers import handlers

    calls = {"n": 0}
    real = handlers.HANDLERS["ingest"]

    def flaky(job, progress):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return real(job, progress)

    monkeypatch.setitem(handlers.HANDLERS, "ingest", flaky)
    created = upload(client, b"a\n1\n", "f.csv")
    Worker("w").run_once()
    j = _job(created["job_id"])
    assert j.status == "queued" and "disk hiccup" in j.error
    assert j.run_after > utcnow()
    with get_sessionmaker()() as db:
        db.execute(update(Job).where(Job.id == j.id).values(run_after=utcnow()))
        db.commit()
    Worker("w").run_once()
    assert _job(created["job_id"]).status == "succeeded"


def test_lost_lease_result_is_discarded(client, monkeypatch):
    """If another worker reclaimed the job, the original worker must not overwrite it."""
    from app.workers import handlers

    created = upload(client, b"a\n1\n", "l.csv")

    def steal(job, progress):
        with get_sessionmaker()() as db:
            db.execute(update(Job).where(Job.id == job.id).values(worker_id="thief"))
            db.commit()
        return {"stolen": False}

    monkeypatch.setitem(handlers.HANDLERS, "ingest", steal)
    Worker("orig").run_once()
    j = _job(created["job_id"])
    assert j.status == "running" and j.worker_id == "thief"


def test_jobs_are_workspace_scoped(client):
    from tests.conftest import OTHER

    created = upload(client, b"a\n1\n", "s.csv")
    assert client.get(f"/api/v1/jobs/{created['job_id']}", headers=OTHER).status_code == 404
    with get_sessionmaker()() as db:
        assert db.scalar(select(Job).where(Job.id == created["job_id"])) is not None
