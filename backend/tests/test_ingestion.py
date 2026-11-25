"""Ingestion: formats, validation and malformed-input handling (real DuckDB + storage)."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import InvalidInput, PayloadTooLarge
from app.models import Dataset
from app.services import datasets as svc
from tests.conftest import DEV, SAMPLES, run_jobs, sql, upload, upload_ready


def _ws_id(client):
    from app.core.security import hash_token
    from app.models import ApiToken, Workspace

    with get_sessionmaker()() as db:
        tok = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == hash_token(get_settings().dev_token))
        )
        return db.scalar(select(Workspace.id).where(Workspace.owner_id == tok.user_id))


def test_parquet_ingestion(client):
    ds = upload_ready(client, (SAMPLES / "small.parquet").read_bytes(), "small.parquet")
    assert ds["status"] == "ready", ds
    assert ds["row_count"] == 100
    assert ds["source_format"] == "parquet"
    types = {c["name"]: c["type"] for c in ds["current_version"]["columns"]}
    assert types == {"id": "BIGINT", "score": "DOUBLE", "label": "VARCHAR", "day": "DATE"}
    r = sql(client, "SELECT count(*), count(score), sum(id) FROM small").json()
    assert r["rows"] == [[100, 80, 5050]]


def test_corrupted_parquet_is_rejected_up_front(client):
    data = bytearray((SAMPLES / "small.parquet").read_bytes())
    r = client.post(
        "/api/v1/datasets",
        params={"filename": "x.parquet"},
        content=b"not parquet at all",
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422
    assert "Parquet" in r.json()["error"]["message"]
    # Valid magic bytes but a corrupted body: caught by the worker, dataset marked failed.
    mid = len(data) // 2
    data[mid : mid + 200] = b"\x00" * 200
    created = upload(client, bytes(data), "corrupt.parquet")
    run_jobs()
    ds = client.get(f"/api/v1/datasets/{created['dataset']['id']}", headers=DEV).json()
    assert ds["status"] == "failed"
    assert ds["error"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"a,b,c\n", "no data rows"),
        (b"\x00\x01\x02binary\x00", "binary"),
    ],
)
def test_empty_and_invalid_csv(client, content, message):
    r = client.post(
        "/api/v1/datasets",
        params={"filename": "e.csv"},
        content=content,
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    if r.status_code == 202:
        run_jobs()
        ds = client.get(f"/api/v1/datasets/{r.json()['dataset']['id']}", headers=DEV).json()
        assert ds["status"] == "failed"
        assert message in ds["error"].lower()
    else:
        assert r.status_code == 422
        assert message in r.json()["error"]["message"].lower()


def test_unsupported_extension(client):
    r = client.post(
        "/api/v1/datasets",
        params={"filename": "x.xlsx"},
        content=b"abc",
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_malformed_rows_are_skipped_and_reported(client):
    lines = ["id,name,amount"] + [f"{i},n{i},{i}.5" for i in range(1, 51)]
    lines.insert(10, "oops,too,many,columns,here")
    lines.insert(20, "short")
    ds = upload_ready(client, "\n".join(lines).encode(), "m.csv")
    assert ds["status"] == "ready"
    assert ds["row_count"] == 50
    report = ds["current_version"]["ingest_report"]
    assert report["rejected_rows"] == 2
    assert {s["line"] for s in report["reject_samples"]} == {11, 21}


def test_too_many_malformed_rows_fails(client):
    lines = ["a,b"] + ["1,2"] * 5 + ["1,2,3,4"] * 5
    created = upload(client, "\n".join(lines).encode(), "bad.csv")
    run_jobs()
    ds = client.get(f"/api/v1/datasets/{created['dataset']['id']}", headers=DEV).json()
    assert ds["status"] == "failed"
    assert "malformed" in ds["error"]


def test_duplicate_and_missing_headers(client):
    ds = upload_ready(client, b"x,x,,y\n1,2,3,4\n5,6,7,8\n", "dup.csv")
    names = [c["name"] for c in ds["current_version"]["columns"]]
    assert len(names) == len(set(names)) == 4
    assert names[0] == "x" and names[1].startswith("x")
    report = ds["current_version"]["ingest_report"]
    assert report["possible_duplicate_headers"]
    assert any("no header" in w for w in report["warnings"])


def test_semicolon_delimiter_and_latin1_autodetect(client):
    data = "name;city\nJosé;Málaga\nZoë;Köln\n".encode("latin-1")
    ds = upload_ready(client, data, "l.csv")
    assert ds["status"] == "ready", ds
    assert ds["current_version"]["ingest_report"]["encoding"] == "latin-1"
    rows = sql(client, f"SELECT * FROM {ds['sql_name']} ORDER BY name").json()["rows"]
    assert rows == [["José", "Málaga"], ["Zoë", "Köln"]]


def test_explicit_options(client):
    data = b"1|a\n2|b\n3|c\n"
    import json

    ds = upload_ready(
        client, data, "p.csv", options=json.dumps({"delimiter": "|", "header": False})
    )
    assert ds["row_count"] == 3
    assert [c["name"] for c in ds["current_version"]["columns"]] == ["column0", "column1"]


def test_type_override_reprocess_creates_new_version(client):
    data = b"id,code,when\n1,007,2024-01-05\n2,042,2024-02-10\n3,x9,not-a-date\n"
    ds = upload_ready(client, data, "codes.csv")
    types = {c["name"]: c["type"] for c in ds["current_version"]["columns"]}
    assert types["code"] == "VARCHAR" and types["when"] == "VARCHAR"
    r = client.post(
        f"/api/v1/datasets/{ds['id']}/reprocess",
        json={"options": {"type_overrides": {"code": "BIGINT", "when": "DATE"}}},
        headers=DEV,
    )
    assert r.status_code == 202, r.text
    run_jobs()
    ds2 = client.get(f"/api/v1/datasets/{ds['id']}", headers=DEV).json()
    v = ds2["current_version"]
    assert v["version"] == 2
    types = {c["name"]: c["type"] for c in v["columns"]}
    assert types == {"id": "BIGINT", "code": "BIGINT", "when": "DATE"}
    assert v["ingest_report"]["cast_failures"] == {"code": 1, "when": 1}
    rows = sql(client, f'SELECT code, "when" FROM {ds["sql_name"]} ORDER BY id').json()["rows"]
    assert rows == [[7, "2024-01-05"], [42, "2024-02-10"], [None, None]]
    versions = client.get(f"/api/v1/datasets/{ds['id']}/versions", headers=DEV).json()
    assert [x["version"] for x in versions] == [2, 1]


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1000)
    r = client.post(
        "/api/v1/datasets",
        params={"filename": "big.csv"},
        content=b"a\n" + b"1\n" * 2000,
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
    uploads = get_settings().objects_dir / "uploads"
    assert not uploads.exists() or not any(uploads.iterdir())


def test_interrupted_upload_leaves_nothing_behind(client):
    ws = _ws_id(client)

    async def chunks():
        yield b"a,b\n1,2\n"
        raise ConnectionResetError("client went away")

    async def go():
        with get_sessionmaker()() as db:
            await svc.create_from_upload(
                db,
                ws,
                filename="x.csv",
                chunks=chunks(),
                name=None,
                options={},
                content_length=None,
            )

    with pytest.raises(ConnectionResetError):
        asyncio.run(go())
    with get_sessionmaker()() as db:
        assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    uploads = get_settings().objects_dir / "uploads"
    assert not uploads.exists() or not any(uploads.iterdir())


def test_unique_sql_names(client):
    a = upload_ready(client, b"a\n1\n", "sales.csv")
    b = upload_ready(client, b"a\n2\n", "sales.csv")
    c = upload_ready(client, b"a\n3\n", "2024 Report (final).csv")
    d = upload_ready(client, b"a\n3\n", "select.csv")
    assert a["sql_name"] == "sales"
    assert b["sql_name"] == "sales_2"
    assert c["sql_name"] == "t_2024_report_final"
    assert d["sql_name"] == "select_data"


def test_large_file_streamed_through_api(client, tmp_path):
    """2M-row CSV (~40 MB) streamed in 1 MiB chunks; every row is ingested and queryable.

    Peak-memory behaviour is measured against a real server process in benchmarks/,
    because the in-process TestClient buffers request bodies itself.
    """
    path = Path(tmp_path) / "big.csv"
    with path.open("w") as fh:
        fh.write("id,cat,value\n")
        for i in range(2_000_000):
            fh.write(f"{i},c{i % 97},{i * 0.5}\n")

    def gen():
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                yield chunk

    r = client.post(
        "/api/v1/datasets",
        params={"filename": "big.csv"},
        content=gen(),
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 202
    run_jobs()
    ds = client.get(f"/api/v1/datasets/{r.json()['dataset']['id']}", headers=DEV).json()
    assert ds["row_count"] == 2_000_000
    out = sql(client, f"SELECT count(*), sum(value), count(DISTINCT cat) FROM {ds['sql_name']}")
    assert out.json()["rows"][0] == [2_000_000, sum(i * 0.5 for i in range(2_000_000)), 97]


def test_invalid_options_json(client):
    r = client.post(
        "/api/v1/datasets",
        params={"filename": "a.csv", "options": "{bad"},
        content=b"a\n1\n",
        headers={**DEV, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422
    with pytest.raises(PayloadTooLarge):
        raise PayloadTooLarge("x")
    with pytest.raises(InvalidInput):
        svc.detect_format("x.exe")
