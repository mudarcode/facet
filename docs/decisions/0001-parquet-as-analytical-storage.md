# 0001. Convert every upload to Parquet and query it with DuckDB

Status: accepted (Phase 0, confirmed by Phase 6 measurements)

## Context

Users upload CSV or Parquet files and then query them repeatedly: previews, profiles,
charts and dashboards that refresh. The options were:

1. Load rows into PostgreSQL tables.
2. Query the original files in place with DuckDB.
3. Convert once to Parquet (zstd) during ingest, then query that with DuckDB.

## Decision

Option 3. The worker reads the upload once with DuckDB, applies the inferred or
user-corrected types, records rejected rows, and writes one zstd-compressed Parquet file
per dataset version. Every later read goes through `read_parquet` views.

## Evidence

From `benchmarks/REPORT.md`, 5,000,000 rows, same DuckDB, same limits, median timings:

| Query | over CSV | over Parquet | Ratio |
|---|---:|---:|---:|
| group by | 610 ms | 46.4 ms | 13.1× |
| one column | 522 ms | 1.2 ms | 427× |
| all 11 columns | 1,205 ms | 335 ms | 3.6× |

The file also shrinks from 437.8 MiB of CSV to 92.0 MiB of Parquet. Conversion costs
2.20 s of worker time once.

PostgreSQL (option 1) would need a table per upload and row-oriented scans for aggregates.
It would also mix untrusted analytical SQL with the metadata database.

## Consequences

- Each query reads only the columns it touches, and the sandbox can allowlist exact file
  paths (ADR-0003).
- Type corrections mean a reprocess job, which is why originals are kept.
- Versions are immutable files, so a new upload never mutates data a running query is
  reading.
