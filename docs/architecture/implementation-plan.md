# Facet — Phase 0 implementation plan

Status: accepted (2026-11-25). This is the plan the build follows; deviations are
recorded as ADRs in `docs/decisions/`.

## 1. Environment inspected

| Tool | Version found | Notes |
|---|---|---|
| Python | 3.13 | managed with `uv` |
| Node / npm / pnpm | 22 / 10 / available | frontend uses npm |
| PostgreSQL | 16 (local binaries) | also `postgres:16-alpine` via Docker |
| Docker + Compose | 29.x | daemon must be started manually in the dev container |
| Redis | 7 (binary present) | **not used**, see ADR-0002 |
| Chromium + Playwright | 1.63 pre-installed | `@playwright/test` pinned to 1.63 to match |
| Hardware | 4 vCPU, 15 GiB RAM, no swap | used for all benchmark reports |

## 2. Chosen versions

Backend: FastAPI 0.165, Pydantic 2, SQLAlchemy 2.x + Alembic 1.x, psycopg 3,
DuckDB 2.0.1, PyArrow 26, sqlglot 30 (SQL parsing), pytest 9, ruff, mypy (strict).

Frontend: Next.js 16 (App Router) + React 19, TypeScript 5.9 (strict), Tailwind CSS 4,
Radix primitives, TanStack Query 5, TanStack Table 8, CodeMirror 6, Recharts 3,
react-grid-layout 2, Vitest + Testing Library, Playwright.

TypeScript 7 exists but Next.js tooling still targets 5.x, so 5.9 is used.

## 3. Architecture (one paragraph)

The **API** (FastAPI) owns HTTP, auth and all metadata in **PostgreSQL**. Raw uploads
are streamed to disk in 1 MiB chunks (never fully in memory) through a `Storage`
abstraction (local filesystem now, S3-compatible later). An **ingestion job** is
written to a Postgres `jobs` table in the same transaction as the dataset row. A
separate **worker** process claims jobs with `SELECT … FOR UPDATE SKIP LOCKED`, uses
DuckDB to convert CSV/Parquet → a validated Parquet file, extracts schema and row
counts, and atomically registers the new dataset version. **Queries** never touch
Postgres data: they run in a pool of sandboxed **DuckDB worker processes**, each
query on a fresh in-memory connection that can only see the requesting user's
dataset Parquet files through views.

```
browser ──HTTP──▶ Next.js (UI, /api rewrite) ──▶ FastAPI ──▶ PostgreSQL (metadata, jobs)
                                                  │
                                    ┌─────────────┼───────────────┐
                                    ▼             ▼               ▼
                         query sandbox pool   object storage   ingest worker(s)
                         (DuckDB, per query)  raw/ processed/  (DuckDB, jobs table)
```

## 4. Data model (PostgreSQL)

`users`, `workspaces` (owner_id), `api_tokens` (hashed), `datasets`
(workspace_id, name, `sql_name` unique per workspace, current_version_id,
status), `dataset_versions` (format, storage keys, schema JSONB, row/column
count, bytes, profile JSONB), `jobs` (kind, status, payload, attempts, lease
expiry, progress, error), `saved_queries`, `query_runs` (history), 
`transformations` (structured plan JSONB), `charts` (spec JSONB), `dashboards`
(layout JSONB), `export_jobs` via `jobs` + `exports`. UUID primary keys,
FK with `ON DELETE CASCADE` where ownership is hierarchical.

## 5. Analytical storage

```
data/objects/raw/{workspace}/{dataset}/{version}/original.{csv|parquet}
data/objects/processed/{workspace}/{dataset}/{version}/data.parquet
data/objects/exports/{workspace}/{export_id}.{csv|parquet}
```

Policy: originals are kept (for reprocessing with corrected types) until the
dataset is deleted. Processed files are written to a `.tmp` path and renamed only
after validation succeeds, then the version row is flipped to `ready` in one
transaction (atomic registration). Deletion marks the dataset `deleting`, commits,
then removes storage prefixes; a sweeper retries stragglers.

## 6. API contracts

Versioned under `/api/v1`, Pydantic request/response models, cursor-free
`limit/offset` pagination envelope `{items, total, limit, offset}`, structured
errors `{error: {code, message, details}}`. OpenAPI served at `/api/v1/openapi.json`
and `/docs`. Endpoints follow the spec list plus `PATCH /datasets/{id}`,
`/datasets/{id}/versions`, `/exports`, `/queries/history`.

## 7. Job architecture (ADR-0002)

Postgres-backed queue instead of Redis: enqueue is transactional with the
metadata it relates to, there is one fewer service, and the throughput need
(a few imports/minute) is tiny. Workers heartbeat a `lease_expires_at`; a job
whose lease expires is reclaimed (crash recovery) up to `max_attempts`.
Progress is written to the job row and polled by the UI.

## 8. Query security model (ADR-0003) — defence in depth

1. **Parse** with sqlglot (DuckDB dialect). Exactly one statement; root must be
   `SELECT` / set operation (with CTEs). Anything else is rejected.
2. **Allowlist relations**: every table reference must be a CTE name or a
   dataset `sql_name` the user owns. Table functions (`read_csv`, `glob`, …),
   schema-qualified names, and a denylist of side-effect/introspection
   functions are rejected.
3. **DuckDB sandbox**: fresh in-memory DB per query; `allowed_paths` limited to
   the exact Parquet files referenced; `enable_external_access=false`; extension
   autoload/install off; `lock_configuration=true`; `memory_limit`, `threads`.
4. **Process isolation**: queries run in separate worker processes; timeouts
   call `interrupt()` and, if that fails, the process is killed and respawned.
5. **Limits**: timeout, memory, max returned rows, max concurrent queries.

## 9. Frontend navigation

Sidebar: Home · Datasets · SQL · Charts · Dashboards · Settings & Help.
Routes: `/`, `/datasets`, `/datasets/[id]` (tabs: Overview, Schema, Preview,
Profile, Transform), `/sql`, `/charts`, `/charts/[id]`, `/dashboards`,
`/dashboards/[id]`, `/settings`. Server state via TanStack Query; no global store.

## 10. Benchmark plan

`benchmarks/generate.py` (seeded, configurable rows/cols/null rate/cardinality,
CSV + Parquet), `benchmarks/run.py` measuring ingest time, rows/s, peak RSS
(via `resource`/psutil on the worker process), query latency (engine vs API),
profiling time, export throughput; comparisons: CSV-direct vs Parquet, with and
without column projection. Raw JSON in `benchmarks/results/`, Markdown report
generated from it. Environment metadata captured automatically.

## 11. Phases

Follows the spec: 0 plan → 1 vertical slice → 2 ingestion/jobs/profiling →
3 SQL workspace/security/transforms → 4 charts/dashboards/export → 5 design →
6 benchmarks → 7 review/docs.
