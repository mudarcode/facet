"""Read-only boundary: every attack must be rejected by the guard or contained by the sandbox."""

import asyncio

import pytest

from app.analytics.engine import SandboxLimits, open_sandbox
from app.analytics.sandbox import SandboxPool, SandboxRequest
from app.analytics.sql_guard import validate_query
from app.core.config import get_settings
from app.core.errors import Busy, QueryRejected
from tests.conftest import DEV, OTHER, sql, upload_ready

ATTACKS = [
    # filesystem & network reads
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_text('/etc/passwd')",
    "SELECT * FROM read_blob('/etc/passwd')",
    "SELECT * FROM read_parquet('/tmp/*.parquet')",
    "SELECT * FROM read_json('https://example.com/x.json')",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM 'https://example.com/data.csv'",
    "SELECT * FROM glob('/**')",
    "SELECT * FROM sales WHERE region IN (SELECT * FROM read_csv('/etc/hosts'))",
    "WITH x AS (SELECT * FROM read_csv('/etc/passwd')) SELECT * FROM x",
    # mutation / DDL / side effects
    "COPY sales TO '/tmp/out.csv'",
    "COPY (SELECT 1) TO '/tmp/x.csv'",
    "EXPORT DATABASE '/tmp/db'",
    "CREATE TABLE t AS SELECT 1",
    "CREATE MACRO m() AS 1",
    "INSERT INTO sales VALUES (1)",
    "UPDATE sales SET qty = 0",
    "DELETE FROM sales",
    "DROP VIEW sales",
    "ALTER TABLE sales ADD COLUMN x INT",
    "SELECT * INTO evil FROM sales",
    # extensions, attachments, configuration
    "INSTALL httpfs",
    "LOAD httpfs",
    "ATTACH '/tmp/evil.db' AS evil",
    "DETACH evil",
    "SET enable_external_access = true",
    "RESET allowed_paths",
    "PRAGMA database_list",
    "CALL pragma_version()",
    "SELECT current_setting('allowed_paths')",
    "SELECT getenv('HOME')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM duckdb_extensions()",
    "SELECT * FROM query('SELECT 1')",
    "SELECT * FROM query_table('sales')",
    "SELECT * FROM main.sales",
    "SELECT * FROM system.main.sales",
    "USE memory",
    "CHECKPOINT",
    "BEGIN TRANSACTION",
    "SUMMARIZE sales",
    "DESCRIBE sales",
    "SHOW TABLES",
    # stacking
    "SELECT 1; DROP VIEW sales",
    "SELECT 1; SELECT 2",
    # other workspaces' data
    "SELECT * FROM other_secret",
]


@pytest.fixture()
def datasets(client):
    upload_ready(client, b"region,qty\nN,1\nS,2\n", "sales.csv")
    upload_ready(client, b"secret\n42\n", "other_secret.csv", headers=OTHER)


@pytest.mark.parametrize("attack", ATTACKS)
def test_attack_is_rejected(client, datasets, attack):
    r = sql(client, attack)
    assert r.status_code in (400, 422), (attack, r.status_code, r.text)
    assert r.json()["error"]["code"] in ("query_rejected", "query_failed"), r.text


def test_legitimate_analytics_sql_is_allowed(client, datasets):
    queries = [
        "SELECT region, sum(qty) FROM sales GROUP BY ALL ORDER BY 1",
        "FROM sales SELECT * WHERE qty > 1",
        "WITH t AS (SELECT * FROM sales) SELECT count(*) FROM t",
        "SELECT *, row_number() OVER (ORDER BY qty) FROM sales QUALIFY qty > 0",
        "SELECT * FROM sales, range(3) r",
        "PIVOT sales ON region USING sum(qty)",
        "SELECT unnest([1, 2, 3]) AS x",
        "SELECT region FROM sales UNION SELECT 'X' ORDER BY 1",
        "SELECT regexp_extract(region, '[A-Z]') FROM sales",
    ]
    for q in queries:
        r = sql(client, q)
        assert r.status_code == 200, (q, r.text)


def test_sandbox_blocks_filesystem_even_without_guard(tmp_path):
    """Layer 2 on its own: raw DuckDB connection used by the sandbox."""
    import duckdb

    pq = str(tmp_path / "ok.parquet")
    duckdb.sql(f"COPY (SELECT 1 AS a) TO '{pq}'")
    con = open_sandbox({"ok": pq}, SandboxLimits())
    assert con.execute("SELECT * FROM ok").fetchall() == [(1,)]
    for stmt in [
        "SELECT * FROM read_csv('/etc/passwd')",
        f"COPY ok TO '{tmp_path}/leak.csv'",
        "ATTACH '/tmp/x.db'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "SET enable_external_access = true",
        "SET allowed_paths = ['/']",
        "SELECT * FROM read_text('/etc/hostname')",
    ]:
        with pytest.raises(duckdb.Error):
            con.execute(stmt)
    assert not (tmp_path / "leak.csv").exists()


def test_guard_renders_validated_ast(datasets):
    v = validate_query("select /* hi */ region from SALES -- trailing\n;", {"sales"})
    assert v.sql == "SELECT region FROM SALES"
    assert v.datasets == {"sales"}
    with pytest.raises(QueryRejected):
        validate_query("x" * 100_001, {"sales"})


def test_query_timeout(client, datasets, monkeypatch):
    monkeypatch.setattr(get_settings(), "query_timeout_s", 0.5)
    r = sql(client, "SELECT count(*) FROM range(100000000000) a")
    assert r.status_code == 408, r.text
    assert r.json()["error"]["code"] == "query_timeout"
    # The sandbox recovers: next query works.
    assert sql(client, "SELECT 1").status_code == 200
    hist = client.get("/api/v1/queries/history?status=timeout", headers=DEV).json()
    assert hist["total"] == 1


def test_memory_limit(client, datasets, monkeypatch):
    monkeypatch.setattr(get_settings(), "query_memory_limit", "64MB")
    r = sql(client, "SELECT list(range) FROM range(50000000)")
    assert r.status_code == 400, r.text
    assert "memory" in r.json()["error"]["message"].lower()
    assert sql(client, "SELECT 1").status_code == 200


def test_row_cap_and_truncation(client, datasets, monkeypatch):
    monkeypatch.setattr(get_settings(), "query_max_rows", 1000)
    body = sql(client, "SELECT * FROM range(5000)", limit=10).json()
    assert body["truncated"] is True
    assert body["total_rows"] == 1000
    assert len(body["rows"]) == 10
    assert sql(client, "SELECT 1", limit=5000).status_code == 422  # page size cap


def test_concurrency_limit_returns_busy():
    async def scenario():
        pool = SandboxPool(1, acquire_timeout_s=0.2)
        await pool.start()
        try:
            slow = SandboxRequest(sql="SELECT count(*) FROM range(100000000000)", views={}, timeout_s=3)
            fast = SandboxRequest(sql="SELECT 1", views={}, timeout_s=3)
            task = asyncio.create_task(pool.execute(slow))
            await asyncio.sleep(0.3)
            with pytest.raises(Busy):
                await pool.execute(fast)
            task.cancel()
        finally:
            await pool.stop()

    asyncio.run(scenario())


def test_saved_query_of_other_user_cannot_be_referenced(client, datasets):
    q = client.post("/api/v1/queries", json={"name": "x", "sql": "SELECT 1"}, headers=OTHER).json()
    r = sql(client, "SELECT 1", saved_query_id=q["id"])
    assert r.status_code == 404
