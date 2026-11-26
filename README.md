# Facet

**Upload a CSV or Parquet file, query it with SQL, chart it, and pin it to a dashboard.**
Facet is a self-hosted analytics workbench built on FastAPI, DuckDB, PostgreSQL and
Next.js. Untrusted SQL runs in a layered sandbox, and large imports run as background
jobs.

![Dashboard](docs/screenshots/dashboard.png)

> Every screenshot here was taken from the running app (`docker compose up`, then
> `scripts/seed_demo.py`). Every number comes from [`benchmarks/REPORT.md`](benchmarks/REPORT.md)
> and is reproducible. The data is synthetic. Facet has no production users.

## Contents

[Quick start](#quick-start) · [Features](#features) · [Demo walkthrough](#demo-walkthrough) ·
[Architecture](#architecture) · [Benchmarks](#benchmarks) · [Testing](#testing) ·
[Local development](#local-development) · [Configuration](#configuration) ·
[Trade-offs and limitations](#trade-offs-and-limitations) · [Docs](#documentation)

## Quick start

Requires Docker with Compose v2.

```bash
git clone https://github.com/mudarcode/facet && cd facet
docker compose up --build        # Postgres, API, worker, web
python3 scripts/seed_demo.py     # optional: demo dataset, queries, charts, dashboard
```

Open **http://localhost:3000**. API docs are at http://localhost:8000/docs.

### Verified fresh install

On 2026-11-26 a clean clone of this branch was built and started with
`docker compose up --build`. All four services became healthy, and the Playwright
end-to-end suite passed (2 of 2) against the containers. That sandbox had two network
limits, neither of which is part of the project:

- Docker Hub rate-limited anonymous pulls, so the base images were pulled from
  `mirror.gcr.io` and tagged locally.
- Outbound TLS went through an intercepting proxy, so the build trusted its CA through a
  local, uncommitted `compose.override.yaml`.

The committed Dockerfiles and `compose.yaml` were used unchanged otherwise. On a normal
machine, neither workaround is needed.

## Features

| | |
|---|---|
| **Import** | CSV (delimiter, encoding, header and type detection) or Parquet, streamed upload up to 2 GiB, background ingest with live progress, rejected-row reporting, type overrides and reprocess, versioned datasets |
| **Explore** | Schema with inferred types, paginated preview, a column profile per type (null %, distinct count, min/max, mean, quantiles, histograms, top values, length stats, hints such as "likely an identifier") |
| **SQL** | CodeMirror editor with schema-aware autocomplete, read-only DuckDB SQL, EXPLAIN, saved queries, history, result paging, timing (engine vs total) |
| **Transform** | Select, rename, filter, drop nulls, cast, derive, group, distinct, sort and limit steps, previewed live and materialised into a new dataset by a background job |
| **Charts** | Bar, line, area, scatter, histogram and stat; time grains; series split with "Other" folding; filters; a Data tab and a SQL tab showing exactly what ran |
| **Dashboards** | Drag and resize grid, dashboard-wide filters, layout saved automatically, stacked layout on phones |
| **Export** | CSV or Parquet from a query, dataset or chart, run as a job, downloaded via a signed link that expires in 10 minutes, with CSV formula-injection protection |
| **UI** | Light and dark themes, keyboard accessible, axe-clean (WCAG 2 AA rules), responsive down to 390 px |

<table>
<tr><td><img src="docs/screenshots/sql-workspace.png" alt="SQL workspace"/><br/><sub>SQL workspace: read-only DuckDB, sandboxed per query</sub></td>
<td><img src="docs/screenshots/dataset-profile.png" alt="Column profile"/><br/><sub>Column profile computed by a background job</sub></td></tr>
<tr><td><img src="docs/screenshots/chart-builder.png" alt="Chart builder"/><br/><sub>Chart builder: the spec compiles to one aggregate query</sub></td>
<td><img src="docs/screenshots/dashboard-dark.png" alt="Dashboard, dark theme"/><br/><sub>Dark theme</sub></td></tr>
<tr><td><img src="docs/screenshots/home.png" alt="Workspace home"/><br/><sub>Workspace home with activity feed</sub></td>
<td><img src="docs/screenshots/dataset-schema.png" alt="Inferred schema"/><br/><sub>Inferred schema</sub></td></tr>
</table>

## Demo walkthrough

The example workflow: **Upload → schema inference → SQL query → visualization → saved
dashboard.** The same steps are automated in
[`frontend/e2e/workflow.spec.ts`](frontend/e2e/workflow.spec.ts).

1. **Upload.** Go to **Datasets → Import dataset**, choose
   [`samples/demo_orders.csv`](samples/demo_orders.csv) (5,000 rows, 11 columns) and name
   it. The upload streams to disk and a worker job converts it to Parquet. The status
   changes from *Processing* to *Ready*.
2. **Schema inference.** The **Schema** tab shows `order_id BIGINT`,
   `ordered_at TIMESTAMP`, `ship_date DATE`, `is_returning BOOLEAN` and so on, all
   inferred from the CSV. **Profile** shows per-column statistics. For example, `shipping`
   has 222 missing values out of 5,000.
3. **SQL.** Click **Query** and run:
   ```sql
   SELECT region, count(*) AS orders, round(sum(qty * unit_price), 2) AS revenue
   FROM demo_orders
   GROUP BY region
   ORDER BY revenue DESC
   ```
   Try `DROP VIEW demo_orders` or `SELECT * FROM read_csv('/etc/passwd')`. Both are
   rejected with an explanation. **Save** the query as "Revenue by region".
4. **Visualize.** Go to **Charts → New chart**, pick the saved query as the source, then
   *Bar*, x = `region`, measure = sum of `revenue`. Or chart the dataset directly: *Line*,
   x = `ordered_at` by month, split by `shipping`.
5. **Dashboard.** Go to **Dashboards → New**, add both charts, drag and resize them, and
   add a dashboard filter such as `region = North`. Reload the page: the layout and
   filter persist. Use **Export** on any tile to download its data.

`scripts/seed_demo.py` builds this end state (plus a histogram, stat tiles and an area
chart) through the public API.

### Example datasets

| File | Rows | Notes |
|---|---:|---|
| `samples/demo_orders.csv` / `.parquet` | 5,000 | Same data in both formats; deterministic (seed 7); nulls in `shipping` and `discount_pct` |
| `benchmarks/generate.py` | any | `python benchmarks/generate.py --rows 1000000 --out data/`: byte-for-byte reproducible synthetic orders |
| `backend/tests/fixtures/` | small | `sales.csv` and `small.parquet`; other edge cases (semicolon delimiters, Latin-1, malformed rows) are generated inside `test_ingestion.py` |

### SQL examples

```sql
-- Month-over-month order growth
SELECT month, orders,
       round(100.0 * (orders - lag(orders) OVER w) / lag(orders) OVER w, 1) AS growth_pct
FROM (SELECT date_trunc('month', ordered_at) AS month, count(*) AS orders
      FROM demo_orders GROUP BY 1)
WINDOW w AS (ORDER BY month)
ORDER BY month;

-- Top 3 categories per region
SELECT * FROM (
  SELECT region, category, sum(qty) AS units,
         rank() OVER (PARTITION BY region ORDER BY sum(qty) DESC) AS r
  FROM demo_orders GROUP BY region, category
) WHERE r <= 3 ORDER BY region, r;

-- Returning vs new customers, with missing shipping methods counted
SELECT is_returning,
       count(*) AS orders,
       round(avg(discount_pct), 1) AS avg_discount_pct,
       count(*) FILTER (WHERE shipping IS NULL) AS missing_shipping
FROM demo_orders GROUP BY ALL ORDER BY is_returning;
```

## Architecture

```mermaid
flowchart LR
    B[Browser] --> W[Next.js web]
    B -->|JSON + bearer token| A[FastAPI API]
    A --> P[(PostgreSQL<br/>metadata + job queue)]
    A -->|streamed upload| S[(Parquet storage)]
    A --> Q[DuckDB sandbox pool]
    Q -->|allowed paths only| S
    K[Worker] -->|SKIP LOCKED| P
    K -->|ingest · profile · transform · export| S
```

- **PostgreSQL** holds metadata and the job queue. **Parquet files** hold the data.
  **DuckDB** is the only thing that reads them.
- **Uploads** stream to disk in 1 MiB chunks. The dataset row and its ingest job are
  committed in one transaction.
- **Workers** claim jobs with `FOR UPDATE SKIP LOCKED`, heartbeat a 60 s lease, and
  recover crashed jobs.
- **Queries** pass an AST guard (sqlglot, re-rendered), then run on a fresh, locked-down
  in-memory DuckDB inside a pre-forked process with time, memory and row limits.
- **Charts** are specs compiled to one aggregate query, so the browser never receives raw
  rows.

Details: [architecture overview](docs/architecture/overview.md) ·
[decision records](docs/decisions/README.md) · [security review](docs/security.md)

### Technologies

| Layer | Choices |
|---|---|
| Backend | Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3, DuckDB 2.0, PyArrow, sqlglot, uv |
| Frontend | Next.js 16 (App Router, standalone), React 19, TypeScript (strict), Tailwind CSS 4, Radix, TanStack Query and Table, CodeMirror 6, Recharts, react-grid-layout |
| Data | PostgreSQL 16, Parquet (zstd) on a pluggable `Storage` interface |
| Quality | pytest, Vitest and Testing Library, Playwright and axe-core, ruff, mypy strict, ESLint, GitHub Actions |
| Ops | Docker multi-stage images (non-root), Compose with health checks |

## Benchmarks

Synthetic orders data (11 columns) on one shared 4-vCPU VM, with the API, worker,
PostgreSQL and client co-located. Full report with environment, methodology and caveats:
**[benchmarks/REPORT.md](benchmarks/REPORT.md)**.

| 5,000,000 rows | Result |
|---|---|
| CSV ingest (437.8 MiB) | 2.20 s worker (2.27M rows/s), 3.62 s end to end |
| Parquet ingest (92.0 MiB) | 1.02 s worker (4.88M rows/s) |
| API memory during upload | +0.0 MiB peak RSS (streamed) |
| Warm query, engine p50 | 5.4 ms (count) to 329 ms (count distinct) |
| Warm query, HTTP round trip p50 | 40 to 360 ms |
| Concurrency (8 clients, 4 sandboxes) | 26.4 queries/s, 32 of 32 returned 200 |
| Parquet vs CSV for the same query | 13.1× (group by), 427× (one column), 3.6× (all columns) |
| Sandbox setup per query | ≈17 ms; SQL guard 0.18 to 0.84 ms |
| Export | CSV 4.38 s, Parquet 3.64 s |

![Query latency](benchmarks/plots/query_latency.svg)

Reproduce with the API and worker running (see [Local development](#local-development)):

```bash
cd backend
uv run --group bench python ../benchmarks/run.py --rows 100000 1000000 5000000
uv run --group bench python ../benchmarks/report.py
```

## Testing

| Suite | Count | Command |
|---|---:|---|
| Backend (pytest, real PostgreSQL and DuckDB) | 181 | `cd backend && uv run pytest` |
| SQL security (subset of the above) | 47 attacks plus sandbox, limit and isolation tests | `uv run pytest tests/test_sql_security.py` |
| Frontend unit (Vitest) | 16 | `cd frontend && npm test` |
| End to end (Playwright, no mocks) | 2 | `cd frontend && npx playwright test` (stack running) |
| Static checks | | `uv run ruff check . && uv run mypy app`; `npm run lint && npm run typecheck` |

The E2E test drives the real UI: it uploads the demo CSV, checks the inferred schema,
profile and preview, compares SQL results against the source file, confirms two attack
queries are rejected, builds a chart and a dashboard, reloads to confirm they persist,
downloads a CSV export and counts its rows, and runs an axe scan. A second test checks
that another user's token sees none of it. CI runs all of this on every push
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Local development

Requires Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22, and PostgreSQL 16
with a `facet` user (password `facet`) owning the databases `facet` and `facet_test`.

```bash
# API
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# worker (second terminal)
cd backend && uv run python -m app.workers.main

# web (third terminal)
cd frontend && npm ci && npm run dev
```

## Configuration

All settings are environment variables prefixed `FACET_` (`backend/app/core/config.py`).

| Variable | Default | |
|---|---|---|
| `FACET_ENV` | `development` | Anything else enables the boot-time check that refuses default secrets |
| `FACET_DATABASE_URL` | `postgresql+psycopg://facet:facet@localhost:5432/facet` | |
| `FACET_DATA_DIR` | `./data` | Raw, processed and export files |
| `FACET_SECRET_KEY` | dev value | Signs export links. **Set this for any shared deployment.** |
| `FACET_DEV_TOKEN` / `FACET_SEED_DEV_USER` | `facet-dev-token` / `true` | The seeded user's token |
| `FACET_CORS_ORIGINS` | `["http://localhost:3000"]` | |
| `FACET_MAX_UPLOAD_BYTES` | 2 GiB | |
| `FACET_QUERY_TIMEOUT_S` / `_MEMORY_LIMIT` / `_WORKERS` / `_MAX_ROWS` | 30 / 1GB / 4 / 10000 | Sandbox limits |
| `FACET_EXPORT_LINK_TTL_S` / `FACET_EXPORT_RETENTION_S` | 600 / 86400 | |

The web image takes `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_FACET_TOKEN` as **build**
arguments.

## Trade-offs and limitations

- **Single-user auth.** Everything is scoped by workspace and isolation is tested, but
  there is no login UI. A seeded token is baked into the web build (ADR-0005).
- **Local disk storage only.** S3 would plug into the `Storage` interface, but isn't
  implemented.
- **Polling, not push.** Job progress and dashboards poll. There are no WebSockets.
- **Some DuckDB SQL is refused on purpose**, such as file table functions, `DESCRIBE`,
  `PRAGMA` and unlisted table functions (ADR-0003).
- **Chart limits.** At most 5,000 points per chart, 7 series plus "Other" (3 for scatter),
  and one y-axis. There are no dual axes, by design.
- **Benchmarks stop at 5M rows on 4 vCPUs.** Nothing here claims behaviour beyond that.
- **No rate limiting and no script CSP.** See [security review](docs/security.md).

## Documentation

- [Architecture overview](docs/architecture/overview.md), including request flows and the
  storage layout
- [Decision records](docs/decisions/README.md) and deviations from the original spec
- [Security review](docs/security.md)
- [Benchmark report](benchmarks/REPORT.md)
- [Resume impact report](docs/resume-impact.md)
- [Phase 0 implementation plan](docs/architecture/implementation-plan.md)

## License

[MIT](LICENSE)
