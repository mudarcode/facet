"""Phase 1 acceptance: upload a CSV and run real SQL over it through the API."""

import csv
import io
from collections import defaultdict

from tests.conftest import DEV, SAMPLES, sql, upload_ready


def _expected_revenue() -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    with (SAMPLES / "sales.csv").open() as fh:
        for row in csv.DictReader(fh):
            totals[row["region"]] += int(row["qty"]) * float(row["price"])
    return totals


def test_upload_schema_preview_and_query(client):
    ds = upload_ready(client, (SAMPLES / "sales.csv").read_bytes(), "sales.csv")
    assert ds["status"] == "ready"
    assert ds["sql_name"] == "sales"
    assert ds["row_count"] == 5000
    assert ds["column_count"] == 6

    schema = client.get(f"/api/v1/datasets/{ds['id']}/schema", headers=DEV).json()
    types = {c["name"]: c["type"] for c in schema}
    assert types == {
        "order_id": "BIGINT",
        "region": "VARCHAR",
        "product": "VARCHAR",
        "qty": "BIGINT",
        "price": "DOUBLE",
        "order_date": "DATE",
    }

    prev = client.get(f"/api/v1/datasets/{ds['id']}/preview?limit=5", headers=DEV).json()
    assert len(prev["rows"]) == 5
    assert prev["total_rows"] == 5000
    assert prev["rows"][0][0] == 1  # insertion order preserved

    r = sql(client, "SELECT region, sum(qty * price) AS rev FROM sales GROUP BY region")
    assert r.status_code == 200, r.text
    body = r.json()
    got = {row[0]: row[1] for row in body["rows"]}
    expected = _expected_revenue()
    assert got.keys() == expected.keys()
    for k, v in expected.items():
        assert abs(got[k] - v) < 1e-6
    assert body["engine_ms"] > 0
    assert body["total_ms"] >= body["engine_ms"]


def test_pagination_preserves_order(client):
    upload_ready(client, (SAMPLES / "sales.csv").read_bytes(), "sales.csv")
    q = "SELECT order_id FROM sales ORDER BY price DESC, order_id"
    full = sql(client, q, limit=1000).json()
    p2 = sql(client, q, offset=10, limit=10).json()
    assert full["total_rows"] == 5000
    assert [r[0] for r in p2["rows"]] == [r[0] for r in full["rows"][10:20]]


def test_tsv_upload(client):
    data = b"a\tb\n1\tx\n2\ty\n"
    ds = upload_ready(client, data, "t.tsv")
    assert ds["row_count"] == 2
    r = sql(client, f"SELECT sum(a) FROM {ds['sql_name']}").json()
    assert r["rows"] == [[3]]


def test_unicode_and_quoted_values(client):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "note"])
    w.writerow(["Zoë", 'has "quotes", and commas'])
    w.writerow(["李", "multi\nline"])
    ds = upload_ready(client, buf.getvalue().encode(), "u.csv")
    rows = sql(client, f"SELECT * FROM {ds['sql_name']}").json()["rows"]
    assert rows == [["Zoë", 'has "quotes", and commas'], ["李", "multi\nline"]]
