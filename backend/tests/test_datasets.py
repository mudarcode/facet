"""Dataset management, deletion cleanup and cross-user isolation."""

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import Dataset, DatasetVersion
from tests.conftest import DEV, OTHER, run_jobs, sql, upload_ready


def test_list_rename_and_sql_name(client):
    ds = upload_ready(client, b"a\n1\n", "orders.csv")
    lst = client.get("/api/v1/datasets", headers=DEV).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == ds["id"]
    r = client.patch(
        f"/api/v1/datasets/{ds['id']}",
        json={"name": "Orders FY24", "sql_name": "orders_fy24"},
        headers=DEV,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Orders FY24"
    assert sql(client, "SELECT * FROM orders_fy24").status_code == 200
    assert sql(client, "SELECT * FROM orders").json()["error"]["code"] == "query_rejected"
    bad = client.patch(f"/api/v1/datasets/{ds['id']}", json={"sql_name": "Bad Name"}, headers=DEV)
    assert bad.status_code == 422


def test_sql_name_conflict(client):
    a = upload_ready(client, b"a\n1\n", "a.csv")
    upload_ready(client, b"a\n1\n", "b.csv")
    r = client.patch(f"/api/v1/datasets/{a['id']}", json={"sql_name": "b"}, headers=DEV)
    assert r.status_code == 409


def test_delete_removes_storage_and_rows(client):
    ds = upload_ready(client, b"a\n1\n", "gone.csv")
    run_jobs()
    root = get_settings().objects_dir
    assert any(root.rglob("*.parquet")) and any(root.rglob("original.csv"))
    assert client.delete(f"/api/v1/datasets/{ds['id']}", headers=DEV).status_code == 204
    assert client.get(f"/api/v1/datasets/{ds['id']}", headers=DEV).status_code == 404
    assert not any(root.rglob("*.parquet"))
    assert not any(root.rglob("original.csv"))
    with get_sessionmaker()() as db:
        assert db.scalar(select(func.count()).select_from(Dataset)) == 0
        assert db.scalar(select(func.count()).select_from(DatasetVersion)) == 0
    assert sql(client, "SELECT * FROM gone").json()["error"]["code"] == "query_rejected"


def test_interrupted_delete_is_swept(client):
    from app.services import datasets as svc

    ds = upload_ready(client, b"a\n1\n", "half.csv")
    with get_sessionmaker()() as db:
        row = db.get(Dataset, ds["id"])
        row.status = "deleting"  # crash after marking, before cleanup
        db.commit()
    assert client.get(f"/api/v1/datasets/{ds['id']}", headers=DEV).status_code == 404
    with get_sessionmaker()() as db:
        assert svc.sweep_deleting(db) == 1
        assert db.get(Dataset, ds["id"]) is None


def test_other_user_cannot_see_or_touch_datasets(client):
    ds = upload_ready(client, b"secret\n42\n", "private.csv")
    assert client.get("/api/v1/datasets", headers=OTHER).json()["total"] == 0
    for method, path in [
        ("get", f"/api/v1/datasets/{ds['id']}"),
        ("get", f"/api/v1/datasets/{ds['id']}/schema"),
        ("get", f"/api/v1/datasets/{ds['id']}/preview"),
        ("get", f"/api/v1/datasets/{ds['id']}/profile"),
        ("delete", f"/api/v1/datasets/{ds['id']}"),
    ]:
        assert getattr(client, method)(path, headers=OTHER).status_code == 404, path
    r = client.patch(f"/api/v1/datasets/{ds['id']}", json={"name": "pwned"}, headers=OTHER)
    assert r.status_code == 404
    # The same SQL name is simply unknown in the other workspace.
    r = sql(client, "SELECT * FROM private", headers=OTHER)
    assert r.status_code == 400 and r.json()["error"]["code"] == "query_rejected"
    assert client.get(f"/api/v1/datasets/{ds['id']}", headers=DEV).status_code == 200


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/datasets").status_code == 401
    assert (
        client.get("/api/v1/datasets", headers={"Authorization": "Bearer nope"}).status_code == 401
    )
    body = client.get("/api/v1/datasets").json()
    assert body["error"]["code"] == "unauthorized"


def test_pagination_envelope(client):
    for i in range(3):
        upload_ready(client, f"a\n{i}\n".encode(), f"p{i}.csv")
    r = client.get("/api/v1/datasets?limit=2&offset=0", headers=DEV).json()
    assert r["total"] == 3 and len(r["items"]) == 2 and r["limit"] == 2
    r2 = client.get("/api/v1/datasets?limit=2&offset=2", headers=DEV).json()
    assert len(r2["items"]) == 1
    assert client.get("/api/v1/datasets?limit=0", headers=DEV).status_code == 422
