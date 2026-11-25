"""Column profiling computed entirely inside DuckDB.

Design:
* One wide aggregate query computes the cheap per-column statistics for every
  column in a single scan of the Parquet file (null counts, min/max, mean, stddev,
  string lengths, distinct counts).
* Per-column follow-ups (histograms, top values, quantiles) run only for a bounded
  number of columns, and against a reproducible reservoir sample when the dataset
  is larger than ``sample_threshold`` rows.
* Every metric records whether it is exact, approximate (HyperLogLog / t-digest)
  or sampled, and the UI labels it accordingly.
"""

from __future__ import annotations

import math
import time
from typing import Any

import duckdb

from app.analytics.engine import quote_ident, quote_literal, to_json_value

NUMERIC = (
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
    "UINTEGER", "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "REAL", "DECIMAL",
)  # fmt: skip
TEMPORAL = ("DATE", "TIMESTAMP", "TIME")
EXACT_DISTINCT_MAX_ROWS = 1_000_000
MAX_DETAIL_COLUMNS = 60
HISTOGRAM_BINS = 20
TOP_K = 10


def kind_of(t: str) -> str:
    u = t.upper()
    if u.startswith(NUMERIC):
        return "numeric"
    if u.startswith(TEMPORAL):
        return "temporal"
    if u == "BOOLEAN":
        return "boolean"
    if u.startswith("VARCHAR"):
        return "text"
    return "other"


def profile_parquet(
    path: str,
    *,
    memory_limit: str = "2GB",
    threads: int = 4,
    sample_threshold: int = 5_000_000,
    sample_rows: int = 1_000_000,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    con = duckdb.connect(
        ":memory:",
        config={"autoload_known_extensions": False, "autoinstall_known_extensions": False},
    )
    try:
        con.execute(f"SET memory_limit = {quote_literal(memory_limit)}")
        con.execute(f"SET threads = {int(threads)}")
        con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet({quote_literal(path)})")
        cols = [(r[0], r[1]) for r in con.execute("DESCRIBE t").fetchall()]
        total_row = con.execute("SELECT count(*) FROM t").fetchone()
        n = int(total_row[0]) if total_row else 0

        sampled = n > sample_threshold
        if sampled:
            # Reservoir sample with a fixed seed: reproducible across runs.
            con.execute(
                f"CREATE TEMP TABLE s AS SELECT * FROM t "
                f"USING SAMPLE reservoir({int(sample_rows)} ROWS) REPEATABLE (42)"
            )
            detail_src, detail_n = "s", sample_rows
        else:
            detail_src, detail_n = "t", n

        exact_distinct = n <= EXACT_DISTINCT_MAX_ROWS
        base = _base_stats(con, cols, exact_distinct)

        columns: list[dict[str, Any]] = []
        for i, (name, typ) in enumerate(cols):
            kind = kind_of(typ)
            st = base[name]
            non_null = st["non_null"]
            nulls = n - non_null
            col: dict[str, Any] = {
                "name": name,
                "type": typ,
                "kind": kind,
                "count": n,
                "nulls": nulls,
                "null_pct": (nulls / n * 100) if n else 0.0,
                "distinct": st["distinct"],
                "distinct_method": "exact" if exact_distinct else "approximate (HyperLogLog)",
            }
            for k in ("min", "max", "mean", "stddev", "min_length", "max_length", "avg_length"):
                if k in st:
                    col[k] = st[k]
            if i < MAX_DETAIL_COLUMNS and non_null > 0:
                if kind == "numeric":
                    col["quantiles"] = _quantiles(con, detail_src, name, approx=sampled)
                    col["histogram"] = _histogram(con, detail_src, name, st["min"], st["max"])
                if kind in ("text", "boolean") or (kind == "numeric" and st["distinct"] <= 20):
                    col["top_values"] = _top_values(con, detail_src, name)
                if kind == "temporal":
                    col["histogram"] = _temporal_histogram(con, detail_src, name)
                if kind == "text":
                    col["numeric_like_pct"] = _numeric_like(con, detail_src, name)
            col["quality"] = _quality_flags(col, n)
            columns.append(col)

        return {
            "row_count": n,
            "column_count": len(cols),
            "sampled": sampled,
            "sample_rows": detail_n if sampled else None,
            "sample_method": "reservoir, seed 42" if sampled else None,
            "detail_columns": min(len(cols), MAX_DETAIL_COLUMNS),
            "columns": columns,
            "duration_s": round(time.perf_counter() - t0, 4),
        }
    finally:
        con.close()


def _base_stats(
    con: duckdb.DuckDBPyConnection, cols: list[tuple[str, str]], exact_distinct: bool
) -> dict[str, dict[str, Any]]:
    """Single scan computing per-column aggregates for every column."""
    exprs: list[str] = []
    keys: list[tuple[str, str]] = []

    def add(col: str, key: str, expr: str) -> None:
        exprs.append(f"{expr} AS {quote_ident(f'{len(keys)}')}")
        keys.append((col, key))

    for name, typ in cols:
        q = quote_ident(name)
        kind = kind_of(typ)
        add(name, "non_null", f"count({q})")
        if kind in ("numeric", "temporal", "text", "boolean"):
            distinct = f"count(DISTINCT {q})" if exact_distinct else f"approx_count_distinct({q})"
            add(name, "distinct", distinct)
        else:
            add(name, "distinct", f"approx_count_distinct({q}::VARCHAR)")
        if kind in ("numeric", "temporal"):
            add(name, "min", f"min({q})")
            add(name, "max", f"max({q})")
        if kind == "numeric":
            add(name, "mean", f"avg({q}::DOUBLE)")
            add(name, "stddev", f"stddev_samp({q}::DOUBLE)")
        if kind == "text":
            add(name, "min_length", f"min(length({q}))")
            add(name, "max_length", f"max(length({q}))")
            add(name, "avg_length", f"avg(length({q}))")

    row = con.execute(f"SELECT {', '.join(exprs)} FROM t").fetchone() or ()
    out: dict[str, dict[str, Any]] = {name: {} for name, _ in cols}
    for (col, key), value in zip(keys, row, strict=True):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            value = None
        out[col][key] = to_json_value(value) if key in ("min", "max") else value
    for col in out.values():
        col["non_null"] = int(col.get("non_null") or 0)
        col["distinct"] = int(col.get("distinct") or 0)
    return out


def _quantiles(con: duckdb.DuckDBPyConnection, src: str, name: str, *, approx: bool) -> dict:
    q = quote_ident(name)
    fn = "approx_quantile" if approx else "quantile_cont"
    row = con.execute(
        f"SELECT {fn}({q}::DOUBLE, [0.05, 0.25, 0.5, 0.75, 0.95]) FROM {src}"
    ).fetchone()
    values = row[0] if row and row[0] is not None else [None] * 5
    return {
        "p05": values[0], "p25": values[1], "p50": values[2], "p75": values[3], "p95": values[4],
        "method": "approximate (t-digest, sample)" if approx else "exact (interpolated)",
    }  # fmt: skip


def _histogram(
    con: duckdb.DuckDBPyConnection, src: str, name: str, lo: Any, hi: Any
) -> list[dict[str, Any]]:
    if lo is None or hi is None:
        return []
    lo_f, hi_f = float(lo), float(hi)
    q = quote_ident(name)
    if lo_f == hi_f:
        row = con.execute(f"SELECT count({q}) FROM {src}").fetchone()
        return [{"start": lo_f, "end": hi_f, "count": int(row[0]) if row else 0}]
    width = (hi_f - lo_f) / HISTOGRAM_BINS
    rows = con.execute(
        f"SELECT least(floor(({q}::DOUBLE - ?) / ?)::INTEGER, ?) AS b, count(*) "
        f"FROM {src} WHERE {q} IS NOT NULL GROUP BY b ORDER BY b",
        [lo_f, width, HISTOGRAM_BINS - 1],
    ).fetchall()
    counts = {int(b): int(c) for b, c in rows}
    return [
        {"start": lo_f + i * width, "end": lo_f + (i + 1) * width, "count": counts.get(i, 0)}
        for i in range(HISTOGRAM_BINS)
    ]


def _temporal_histogram(
    con: duckdb.DuckDBPyConnection, src: str, name: str
) -> list[dict[str, Any]]:
    q = quote_ident(name)
    span = con.execute(f"SELECT datediff('day', min({q}), max({q})) FROM {src}").fetchone()
    days = int(span[0]) if span and span[0] is not None else 0
    unit = "day" if days <= 120 else "month" if days <= 365 * 8 else "year"
    rows = con.execute(
        f"SELECT date_trunc('{unit}', {q}) AS b, count(*) FROM {src} "
        f"WHERE {q} IS NOT NULL GROUP BY b ORDER BY b LIMIT 400"
    ).fetchall()
    return [{"start": to_json_value(b), "unit": unit, "count": int(c)} for b, c in rows]


def _top_values(con: duckdb.DuckDBPyConnection, src: str, name: str) -> list[dict[str, Any]]:
    q = quote_ident(name)
    rows = con.execute(
        f"SELECT {q} AS v, count(*) AS c FROM {src} GROUP BY v ORDER BY c DESC, v LIMIT {TOP_K}"
    ).fetchall()
    return [{"value": to_json_value(v), "count": int(c)} for v, c in rows]


def _numeric_like(con: duckdb.DuckDBPyConnection, src: str, name: str) -> float:
    """Share of non-null text values that parse as numbers (suggests a type fix)."""
    q = quote_ident(name)
    row = con.execute(
        f"SELECT count(TRY_CAST(trim({q}) AS DOUBLE)) / nullif(count({q}), 0) FROM {src}"
    ).fetchone()
    return round(float(row[0]) * 100, 2) if row and row[0] is not None else 0.0


def _quality_flags(col: dict[str, Any], n: int) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    non_null = n - col["nulls"]
    if n and col["nulls"] == n:
        flags.append({"level": "warning", "code": "all_null", "message": "Every value is null."})
    elif col["null_pct"] >= 50:
        flags.append(
            {
                "level": "warning",
                "code": "mostly_null",
                "message": f"{col['null_pct']:.0f}% of values are null.",
            }
        )
    elif col["nulls"]:
        flags.append(
            {"level": "info", "code": "has_nulls", "message": f"{col['nulls']:,} null values."}
        )
    if non_null and col["distinct"] == 1:
        flags.append({"level": "info", "code": "constant", "message": "Single distinct value."})
    if non_null > 100 and col["distinct"] >= non_null * 0.98 and col["kind"] in ("text", "numeric"):
        flags.append(
            {
                "level": "info",
                "code": "unique_like",
                "message": "Nearly every value is distinct (likely an identifier).",
            }
        )
    if col.get("numeric_like_pct", 0) >= 95:
        flags.append(
            {
                "level": "suggestion",
                "code": "numeric_text",
                "message": f"{col['numeric_like_pct']:.0f}% of values are numeric; "
                "consider correcting the type.",
            }
        )
    return flags
