# Architecture decision records

| # | Decision | Status |
|---|---|---|
| [0001](0001-parquet-as-analytical-storage.md) | Convert every upload to Parquet and query it with DuckDB | Accepted |
| [0002](0002-postgres-job-queue.md) | PostgreSQL job queue with leases instead of Redis or Celery | Accepted |
| [0003](0003-query-sandbox.md) | Defence in depth for untrusted SQL: AST guard plus process sandbox | Accepted |
| [0004](0004-charts-compile-to-aggregate-sql.md) | Charts are declarative specs compiled to aggregate SQL | Accepted |
| [0005](0005-token-auth-and-workspaces.md) | Bearer tokens and workspace scoping instead of a login flow | Accepted |
| [0006](0006-exports-as-jobs-with-signed-links.md) | Exports run as jobs and download through signed links | Accepted |

## Deviations from the original specification

- **No Redis or Celery.** The spec suggested a "background jobs" system. A Postgres table
  with `SKIP LOCKED` covers the need with one fewer service and transactional enqueue
  (ADR-0002).
- **No user registration or login UI.** The API is fully workspace-scoped and tests prove
  that two users are isolated, but the app seeds one development token (ADR-0005).
- **Local filesystem storage only.** The `Storage` interface is in place, but no S3
  backend is implemented.
- **The results grid shows raw numbers** (`374616.85`, not `374,616.85`), matching psql
  and the DuckDB CLI, so years and IDs aren't rendered as `2,024`. Charts, stat tiles and
  the profile use grouped, compact formatting.
