"""DuckDB execution primitives shared by the query sandbox and background workers.

Everything here runs *inside* a sandbox or worker process, never on the API event loop.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import math
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import duckdb

JS_SAFE_INT = 2**53 - 1


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class SandboxLimits:
    memory_limit: str = "1GB"
    threads: int = 2
    timeout_s: float = 30.0


def open_sandbox(
    views: Mapping[str, str],
    limits: SandboxLimits,
    *,
    writable_paths: tuple[str, ...] = (),
) -> duckdb.DuckDBPyConnection:
    """Open a locked-down in-memory DuckDB connection exposing ``views``.

    ``views`` maps a SQL name to an absolute Parquet path. Only those files (plus
    ``writable_paths`` for exports) are reachable; external access, extension
    loading and configuration changes are disabled before user SQL runs.
    """
    con = duckdb.connect(
        ":memory:",
        config={
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            "allow_community_extensions": False,
            "python_enable_replacements": False,
        },
    )
    paths = [*views.values(), *writable_paths]
    con.execute(f"SET memory_limit = {quote_literal(limits.memory_limit)}")
    con.execute(f"SET threads = {int(limits.threads)}")
    con.execute("SET enable_progress_bar = false")
    # Allow exactly the files this query needs; everything else on disk is invisible.
    paths_sql = ", ".join(quote_literal(p) for p in paths)
    con.execute(f"SET allowed_paths = [{paths_sql}]")
    con.execute("SET enable_external_access = false")
    for name, path in views.items():
        con.execute(
            f"CREATE VIEW {quote_ident(name)} AS SELECT * FROM read_parquet({quote_literal(path)})"
        )
    con.execute("SET lock_configuration = true")
    return con


@contextmanager
def deadline(con: duckdb.DuckDBPyConnection, timeout_s: float) -> Iterator[threading.Event]:
    """Interrupt ``con`` if the block runs longer than ``timeout_s``.

    Yields an Event that is set if the interrupt fired.
    """
    fired = threading.Event()

    def _interrupt() -> None:
        fired.set()
        con.interrupt()

    timer = threading.Timer(timeout_s, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        yield fired
    finally:
        timer.cancel()


def to_json_value(value: Any) -> Any:
    """Convert a DuckDB Python value into something JSON-serialisable without losing meaning."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value if abs(value) <= JS_SAFE_INT else str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, decimal.Decimal):
        # Keep exactness for large decimals; small ones are fine as floats in a UI.
        f = float(value)
        return f if abs(f) < 1e15 else str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    return str(value)


def describe_columns(con: duckdb.DuckDBPyConnection, relation_sql: str) -> list[dict[str, str]]:
    rows = con.execute(f"DESCRIBE {relation_sql}").fetchall()
    return [{"name": r[0], "type": r[1]} for r in rows]


def run_paged_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    max_rows: int,
    offset: int,
    limit: int,
    timeout_s: float,
) -> dict[str, Any]:
    """Execute validated ``sql`` and return one page of results.

    The full result is materialised into a temp table capped at ``max_rows + 1`` rows,
    so we can report an exact total (or "more than max_rows") and serve the page in
    the query's own order without running it twice.
    """
    t0 = time.perf_counter()
    with deadline(con, timeout_s) as fired:
        try:
            con.execute(
                "CREATE TEMP TABLE facet_result AS "
                f"SELECT * FROM ({sql}) AS facet_q LIMIT {int(max_rows) + 1}"
            )
            total = con.execute("SELECT count(*) FROM facet_result").fetchone()
            rows = con.execute(
                f"SELECT * FROM facet_result LIMIT {int(limit)} OFFSET {int(offset)}"
            ).fetchall()
            columns = describe_columns(con, "facet_result")
        except duckdb.InterruptException as e:
            raise TimeoutError(f"Query exceeded the {timeout_s:g}s time limit") from e
        except duckdb.Error:
            if fired.is_set():
                raise TimeoutError(f"Query exceeded the {timeout_s:g}s time limit") from None
            raise
    engine_ms = (time.perf_counter() - t0) * 1000
    total_rows = int(total[0]) if total else 0
    truncated = total_rows > max_rows
    return {
        "columns": columns,
        "rows": [[to_json_value(v) for v in row] for row in rows],
        "total_rows": min(total_rows, max_rows),
        "truncated": truncated,
        "offset": offset,
        "limit": limit,
        "engine_ms": engine_ms,
    }


def run_explain(con: duckdb.DuckDBPyConnection, sql: str, *, timeout_s: float) -> str:
    with deadline(con, timeout_s):
        rows = con.execute(f"EXPLAIN {sql}").fetchall()
    return "\n".join(str(r[1]) for r in rows)


def copy_query_to_file(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    out_path: str,
    fmt: str,
    *,
    max_rows: int,
    timeout_s: float,
    sanitize_csv: bool = True,
) -> int:
    """Stream the result of validated ``sql`` to ``out_path`` (csv|parquet). Returns row count.

    For CSV, string cells starting with = + - @ (or tab/CR) are prefixed with a single
    quote to neutralise spreadsheet formula injection (OWASP "CSV injection").
    """
    cols = describe_columns(con, f"SELECT * FROM ({sql}) AS facet_q LIMIT 0")
    if fmt == "csv" and sanitize_csv:
        parts = []
        for c in cols:
            q = quote_ident(c["name"])
            if c["type"].upper().startswith("VARCHAR"):
                parts.append(
                    f"CASE WHEN regexp_matches({q}, '^[=+\\-@\\t\\r]') THEN '''' || {q} "
                    f"ELSE {q} END AS {q}"
                )
            else:
                parts.append(q)
        select = f"SELECT {', '.join(parts)} FROM ({sql}) AS facet_q"
    else:
        select = f"SELECT * FROM ({sql}) AS facet_q"
    select += f" LIMIT {int(max_rows)}"
    options = "FORMAT csv, HEADER true" if fmt == "csv" else "FORMAT parquet, COMPRESSION zstd"
    with deadline(con, timeout_s) as fired:
        try:
            written = con.execute(
                f"COPY ({select}) TO {quote_literal(out_path)} ({options})"
            ).fetchone()
        except duckdb.InterruptException as e:
            raise TimeoutError(f"Export exceeded the {timeout_s:g}s time limit") from e
        except duckdb.Error:
            if fired.is_set():
                raise TimeoutError(f"Export exceeded the {timeout_s:g}s time limit") from None
            raise
    # COPY reports the number of rows it wrote.
    return int(written[0]) if written else 0
