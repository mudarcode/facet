# 0003. Defence in depth for untrusted SQL: AST guard plus process sandbox

Status: accepted (Phase 3)

## Context

The SQL workspace runs arbitrary user-written SQL. DuckDB can read local files and URLs
(`read_csv('/etc/passwd')`, `FROM 'https://…'`), write files (`COPY … TO`), load
extensions, attach databases and change its own configuration. Any single filter will
eventually miss something, so the design assumes each layer can fail.

## Decision

Three independent layers:

1. **AST guard** (`sql_guard.py`). sqlglot parses the query and the guard walks the full
   tree. The root must be a single `SELECT` or set operation. Insert, update, delete,
   create, drop, alter, copy, attach, set, pragma and similar nodes may not appear
   anywhere in the tree. File and introspection functions are on a denylist. Only `range`,
   `generate_series` and `unnest` are allowed as table functions. Every table reference
   must be a CTE or one of the caller's own dataset names. The guard then **re-renders**
   the validated tree, so comments, trailing statements and parser differences never
   reach DuckDB.
2. **DuckDB lockdown** (`engine.open_sandbox`). Each query gets a fresh in-memory
   database with `allowed_paths` set to exactly the Parquet files it needs and
   `enable_external_access=false`. Extension autoload and install are off, and so are
   community extensions. Memory and thread limits are set, then `lock_configuration=true`
   is applied before any user SQL runs.
3. **Process isolation** (`sandbox.py`). Queries run in a pool of forkserver child
   processes that don't inherit the API's sockets, threads or database pool. Each child
   has an `RLIMIT_AS` ceiling. The deadline calls `interrupt()` first. If the child is
   still unresponsive after a grace period, it is killed and replaced. The pool size
   bounds concurrency, and a full pool returns 503 within 10 s.

## Evidence

- `tests/test_sql_security.py` runs 47 attack strings through the API: file reads, URL
  reads, globbing, subquery and CTE smuggling, COPY and EXPORT, DDL and DML, INSTALL,
  LOAD and ATTACH, SET and PRAGMA, `getenv`, `current_setting`, other users' datasets,
  stacked statements and comments. All of them are rejected.
- `test_sandbox_blocks_filesystem_even_without_guard` calls the sandbox **directly**,
  skipping the guard, and shows that DuckDB itself refuses the file read.
- The timeout, memory limit, row cap, concurrency limit and cross-user saved-query tests
  all pass.
- Measured cost (`benchmarks/REPORT.md`): about 17 ms per query to open the locked-down
  connection, and 0.18 to 0.84 ms for the guard.

## Consequences

- Some valid DuckDB SQL is refused, such as table functions outside the allowlist,
  `DESCRIBE` and `SUMMARIZE`. The error message names the construct that was rejected.
- The 17 ms per query setup cost is paid on every query. Reusing connections would save
  it, but then state could leak between users.
