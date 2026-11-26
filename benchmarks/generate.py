"""Deterministic synthetic dataset generator for Facet benchmarks.

Every value is a pure function of (row index, seed) via DuckDB's ``hash()``, so the
output is byte-identical across runs and thread counts. Usage:

    uv run --project ../backend python generate.py --rows 1000000 --seed 7 --out data/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import duckdb


def _u(seed: int, salt: int) -> str:
    """Uniform [0, 1) value derived from the row index."""
    return f"(hash(i, {seed}, {salt}) % 1000000007) / 1000000007.0"


def build_sql(rows: int, seed: int, categories: int, null_rate: float) -> str:
    u = lambda s: _u(seed, s)  # noqa: E731
    return f"""
    SELECT
      i AS order_id,
      TIMESTAMP '2023-01-01' + to_seconds(CAST(floor({u(1)} * 63072000) AS BIGINT)) AS ordered_at,
      CAST(DATE '2023-01-01' + CAST(floor({u(2)} * 730) AS INTEGER) AS DATE) AS ship_date,
      ['North', 'South', 'East', 'West', 'Central'][1 + CAST(floor({u(3)} * 5) AS INTEGER)] AS region,
      'cat_' || lpad(CAST(CAST(floor(pow({u(4)}, 2) * {categories}) AS INTEGER) AS VARCHAR), 4, '0')
        AS category,
      'cust_' || CAST(CAST(floor({u(5)} * {max(rows // 4, 1)}) AS BIGINT) AS VARCHAR) AS customer_id,
      1 + CAST(floor({u(6)} * 9) AS INTEGER) AS qty,
      round(5 + exp({u(7)} * 6), 2) AS unit_price,
      {u(8)} < 0.3 AS is_returning,
      CASE WHEN {u(9)} < {null_rate} THEN NULL
           ELSE ['standard', 'express', 'pickup', 'freight'][1 + CAST(floor({u(10)} * 4) AS INTEGER)]
      END AS shipping,
      CASE WHEN {u(11)} < {null_rate} THEN NULL ELSE round({u(12)} * 100, 1) END AS discount_pct
    FROM range({rows}) t(i)
    """


def generate(
    rows: int, seed: int, out: Path, categories: int = 200, null_rate: float = 0.05
) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    stem = f"orders_{rows}_s{seed}"
    csv_path, pq_path = out / f"{stem}.csv", out / f"{stem}.parquet"
    con = duckdb.connect()
    con.execute("SET threads = 4")
    sql = build_sql(rows, seed, categories, null_rate)
    t0 = time.perf_counter()
    con.execute(f"COPY ({sql} ORDER BY order_id) TO '{csv_path}' (FORMAT csv, HEADER true)")
    con.execute(f"COPY ({sql} ORDER BY order_id) TO '{pq_path}' (FORMAT parquet, COMPRESSION zstd)")
    elapsed = time.perf_counter() - t0
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest() if rows <= 2_000_000 else None
    meta = {
        "rows": rows,
        "seed": seed,
        "categories": categories,
        "null_rate": null_rate,
        "columns": 11,
        "csv": str(csv_path),
        "csv_bytes": csv_path.stat().st_size,
        "csv_sha256": digest,
        "parquet": str(pq_path),
        "parquet_bytes": pq_path.stat().st_size,
        "generate_s": round(elapsed, 3),
    }
    (out / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, nargs="+", default=[100_000, 1_000_000])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--categories", type=int, default=200)
    ap.add_argument("--null-rate", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    a = ap.parse_args()
    for n in a.rows:
        print(json.dumps(generate(n, a.seed, a.out, a.categories, a.null_rate)))


if __name__ == "__main__":
    main()
