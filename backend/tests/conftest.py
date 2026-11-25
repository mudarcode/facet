"""Integration test fixtures: a real PostgreSQL database, real DuckDB, real storage.

Set FACET_TEST_DATABASE_URL to point at a disposable database (default: facet_test).
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

_DATA = Path(tempfile.mkdtemp(prefix="facet-test-"))
os.environ["FACET_DATABASE_URL"] = os.environ.get(
    "FACET_TEST_DATABASE_URL", "postgresql+psycopg://facet:facet@localhost:5432/facet_test"
)
os.environ["FACET_DATA_DIR"] = str(_DATA)
os.environ.setdefault("FACET_QUERY_WORKERS", "2")
os.environ.setdefault("FACET_QUERY_TIMEOUT_S", "5")
os.environ.setdefault("FACET_JOB_LEASE_S", "30")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, get_sessionmaker  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.bootstrap import ensure_user  # noqa: E402
from app.workers.main import Worker  # noqa: E402

DEV = {"Authorization": f"Bearer {get_settings().dev_token}"}
OTHER_TOKEN = "other-user-token"
OTHER = {"Authorization": f"Bearer {OTHER_TOKEN}"}
SAMPLES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    engine = get_engine()
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    yield
    shutil.rmtree(_DATA, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    engine = get_engine()
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} CASCADE"))
    shutil.rmtree(get_settings().objects_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def users() -> None:
    with get_sessionmaker()() as db:
        ensure_user(db, email="dev@facet.local", name="Developer", token=get_settings().dev_token)
        ensure_user(db, email="other@facet.local", name="Other", token=OTHER_TOKEN)


def run_jobs(max_jobs: int = 20) -> int:
    """Drain the job queue synchronously with a real worker."""
    w = Worker(worker_id="test-worker")
    n = 0
    while n < max_jobs and w.run_once():
        n += 1
    return n


def upload(client: TestClient, content: bytes, filename: str, headers=DEV, **params) -> dict:
    r = client.post(
        "/api/v1/datasets",
        params={"filename": filename, **params},
        content=content,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 202, r.text
    return r.json()


def upload_ready(client: TestClient, content: bytes, filename: str, headers=DEV, **params) -> dict:
    created = upload(client, content, filename, headers, **params)
    run_jobs()
    r = client.get(f"/api/v1/datasets/{created['dataset']['id']}", headers=headers)
    assert r.status_code == 200
    return r.json()


def sql(client: TestClient, query: str, headers=DEV, **kw):
    return client.post("/api/v1/queries/execute", json={"sql": query, **kw}, headers=headers)
