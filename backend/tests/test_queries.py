"""Saved queries, history and EXPLAIN."""

from tests.conftest import DEV, OTHER, sql, upload_ready


def test_saved_query_crud(client):
    r = client.post("/api/v1/queries", json={"name": "Top", "sql": "SELECT 1", "description": "d"}, headers=DEV)
    assert r.status_code == 201
    qid = r.json()["id"]
    assert client.get("/api/v1/queries", headers=DEV).json()["total"] == 1
    r = client.patch(f"/api/v1/queries/{qid}", json={"sql": "SELECT 2"}, headers=DEV)
    assert r.json()["sql"] == "SELECT 2"
    assert client.get(f"/api/v1/queries/{qid}", headers=OTHER).status_code == 404
    assert client.patch(f"/api/v1/queries/{qid}", json={"name": "x"}, headers=OTHER).status_code == 404
    assert client.delete(f"/api/v1/queries/{qid}", headers=OTHER).status_code == 404
    assert client.delete(f"/api/v1/queries/{qid}", headers=DEV).status_code == 204
    assert client.get(f"/api/v1/queries/{qid}", headers=DEV).status_code == 404


def test_history_records_every_outcome(client):
    upload_ready(client, b"a\n1\n", "h.csv")
    sql(client, "SELECT * FROM h")
    sql(client, "DROP VIEW h")
    sql(client, "SELECT nope FROM h")
    sql(client, "SELECT * FROM h", offset=0, record_history=False)
    hist = client.get("/api/v1/queries/history", headers=DEV).json()
    assert [i["status"] for i in hist["items"]] == ["failed", "rejected", "succeeded"]
    ok = hist["items"][2]
    assert ok["row_count"] == 1 and ok["engine_ms"] > 0 and ok["total_ms"] >= ok["engine_ms"]
    assert "nope" in hist["items"][0]["error"]
    assert client.get("/api/v1/queries/history", headers=OTHER).json()["total"] == 0


def test_explain(client):
    upload_ready(client, b"a,b\n1,2\n", "e.csv")
    r = client.post("/api/v1/queries/explain", json={"sql": "SELECT a FROM e WHERE b > 1"}, headers=DEV)
    assert r.status_code == 200
    assert "PARQUET_SCAN" in r.json()["plan"].upper() or "READ_PARQUET" in r.json()["plan"].upper()


def test_error_messages_hide_storage_paths(client):
    upload_ready(client, b"a\n1\n", "p.csv")
    r = sql(client, "SELECT a + 'x' FROM p")
    assert r.status_code == 400
    assert "/objects/" not in r.json()["error"]["message"]
