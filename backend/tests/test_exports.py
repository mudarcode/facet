"""Exports: real files written by DuckDB, formula-injection sanitising, signed downloads."""

import csv
import io
import time

import pyarrow.parquet as pq
import pytest

from app.core.config import get_settings
from tests.conftest import DEV, OTHER, SAMPLES, run_jobs, upload_ready


@pytest.fixture
def sales(client):
    return upload_ready(client, (SAMPLES / "sales.csv").read_bytes(), "sales.csv")


def _export(client, source: dict, fmt="csv", headers=DEV) -> dict:
    r = client.post("/api/v1/exports", json={"source": source, "format": fmt}, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued"
    run_jobs()
    done = client.get(f"/api/v1/exports/{r.json()['id']}", headers=headers).json()
    return done


def _download(client, e: dict):
    assert e["status"] == "succeeded", e
    return client.get(e["download_url"])  # no bearer token: the signature authorises it


def test_query_export_csv(client, sales):
    e = _export(
        client,
        {"kind": "query", "sql": "SELECT region, count(*) AS n FROM sales GROUP BY 1 ORDER BY 1"},
    )
    r = _download(client, e)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert e["filename"] in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    with open(SAMPLES / "sales.csv") as f:
        src = list(csv.DictReader(f))
    assert {row["region"]: int(row["n"]) for row in rows} == {
        reg: sum(1 for s in src if s["region"] == reg) for reg in {s["region"] for s in src}
    }
    assert e["row_count"] == len(rows)
    assert e["bytes"] == len(r.content)


def test_dataset_export_parquet_roundtrip(client, sales):
    e = _export(client, {"kind": "dataset", "dataset_id": sales["id"]}, fmt="parquet")
    r = _download(client, e)
    assert r.status_code == 200
    table = pq.read_table(io.BytesIO(r.content))
    assert table.num_rows == 5000
    assert table.column_names == ["order_id", "region", "product", "qty", "price", "order_date"]
    assert e["filename"].startswith("sales-") and e["filename"].endswith(".parquet")


def test_csv_formula_injection_is_neutralised(client):
    content = (
        b"name,note,n\n"
        b'a,"=HYPERLINK(""http://evil"")",1\n'
        b"b,+1+2,2\n"
        b"c,-3,3\n"
        b"d,@SUM(A1),4\n"
        b"e,plain,5\n"
    )
    ds = upload_ready(client, content, "evil.csv")
    e = _export(client, {"kind": "dataset", "dataset_id": ds["id"]})
    rows = list(csv.DictReader(io.StringIO(_download(client, e).text)))
    notes = {r["name"]: r["note"] for r in rows}
    assert notes == {
        "a": '\'=HYPERLINK("http://evil")',
        "b": "'+1+2",
        "c": "'-3",
        "d": "'@SUM(A1)",
        "e": "plain",
    }
    # Numeric columns are not text, so negative numbers stay numbers.
    assert [r["n"] for r in rows] == ["1", "2", "3", "4", "5"]


def test_chart_export_matches_chart_data(client, sales):
    chart = client.post(
        "/api/v1/charts",
        json={
            "name": "Qty by region",
            "dataset_id": sales["id"],
            "spec": {"type": "bar", "x": "region", "y": [{"field": "qty", "agg": "sum"}]},
        },
        headers=DEV,
    ).json()
    data = client.post(f"/api/v1/charts/{chart['id']}/data", headers=DEV).json()
    e = _export(client, {"kind": "chart", "chart_id": chart["id"]})
    rows = list(csv.reader(io.StringIO(_download(client, e).text)))
    assert rows[0] == ["x", "sum_qty"]
    assert [[r[0], int(r[1])] for r in rows[1:]] == data["rows"]
    assert e["filename"].startswith("Qty_by_region-")


def test_unsafe_query_rejected_before_queueing(client, sales):
    for bad in ("COPY sales TO '/tmp/x.csv'", "SELECT * FROM read_csv('/etc/passwd')"):
        r = client.post(
            "/api/v1/exports", json={"source": {"kind": "query", "sql": bad}}, headers=DEV
        )
        assert r.status_code == 400, r.text
    assert run_jobs() == 0


def test_signed_link_tamper_and_expiry(client, sales, monkeypatch):
    e = _export(client, {"kind": "dataset", "dataset_id": sales["id"]})
    url = e["download_url"]
    assert _download(client, e).status_code == 200
    sig = url.split("sig=")[1]
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert client.get(url.replace(sig, flipped)).status_code == 401
    # Extending the expiry invalidates the signature.
    expires = int(url.split("expires=")[1].split("&")[0])
    assert client.get(url.replace(str(expires), str(expires + 3600))).status_code == 401
    # Expired links are refused even with a valid signature.
    monkeypatch.setattr(get_settings(), "export_link_ttl_s", -5)
    stale = client.get(f"/api/v1/exports/{e['id']}", headers=DEV).json()["download_url"]
    assert int(stale.split("expires=")[1].split("&")[0]) < time.time()
    assert client.get(stale).status_code == 401


def test_export_isolation(client, sales):
    e = _export(client, {"kind": "dataset", "dataset_id": sales["id"]})
    assert client.get(f"/api/v1/exports/{e['id']}", headers=OTHER).status_code == 404
    r = client.post(
        "/api/v1/exports",
        json={"source": {"kind": "dataset", "dataset_id": sales["id"]}},
        headers=OTHER,
    )
    assert r.status_code == 404
    # Other user's workspace has no 'sales' dataset, so the query is rejected.
    r = client.post(
        "/api/v1/exports",
        json={"source": {"kind": "query", "sql": "SELECT * FROM sales"}},
        headers=OTHER,
    )
    assert r.status_code == 400


def test_export_row_cap(client, sales, monkeypatch):
    monkeypatch.setattr(get_settings(), "export_max_rows", 100)
    e = _export(client, {"kind": "dataset", "dataset_id": sales["id"]})
    rows = list(csv.reader(io.StringIO(_download(client, e).text)))
    assert len(rows) == 101
    assert e["row_count"] == 100
