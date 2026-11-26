# 0006. Exports run as jobs and download through signed links

Status: accepted (Phase 4, retention added in Phase 7)

## Context

Exporting 5 million rows takes seconds and produces hundreds of MiB. Holding an HTTP
request open for that is fragile. Downloading through `fetch` would buffer the whole file
in browser memory, and a plain link can't carry an `Authorization` header.

## Decision

- `POST /exports` validates the source (SQL goes through the guard **before** queueing),
  then creates an `export` job and returns 202.
- The worker runs DuckDB `COPY` to `exports/{ws}/{id}.{csv|parquet}`, with that one path
  added to the sandbox's writable paths. In CSV output, text cells starting with
  `= + - @` or a tab or carriage return are prefixed with `'`, which blocks spreadsheet
  formula injection.
- When the export succeeds, the API returns a download URL signed with HMAC-SHA256 that
  expires after `export_link_ttl_s` (600 s). The signature is checked with
  `hmac.compare_digest`. Downloads are sent with `Cache-Control: private, no-store`.
- The worker deletes export files older than `export_retention_s` (24 h). The row stays
  as history with status `expired`.

## Consequences

- The browser's own download manager streams the file, so it works for any size.
- Anyone holding a link can use it for up to 10 minutes. That is the usual trade-off with
  pre-signed URLs, and it is why the TTL is short.
- Measured at 5 M rows: CSV in 4.38 s, Parquet in 3.64 s of worker time
  (`benchmarks/REPORT.md`).
