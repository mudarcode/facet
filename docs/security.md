# Security review

Reviewed at the end of Phase 7 (2026-11-26) against the code on `phase-7-release`. This
covers the threat model, what is enforced and where, what was fixed during the review,
and what remains out of scope.

## Threat model

| Actor | Can do | Must not be able to |
|---|---|---|
| Authenticated user | Upload files, write any SQL, build charts, export | Read or modify other workspaces, touch the host filesystem or network, exhaust the server |
| Holder of an export link | Download that one file for ≤10 min | Download anything else, or reuse it after expiry |
| Unauthenticated client | Reach `/health`, `/docs` | Everything else (401, tested in `test_security_basics.py`) |
| Malicious file | Be uploaded | Crash the API, escape storage, run code in a spreadsheet when exported |

## Controls

| Risk | Control | Where | Verified by |
|---|---|---|---|
| SQL reading files, URLs or other tenants | AST guard, then a re-rendered statement | `analytics/sql_guard.py` | 47 attack strings in `test_sql_security.py` |
| A guard bypass | DuckDB `allowed_paths`, `enable_external_access=false`, no extensions, `lock_configuration` | `analytics/engine.py` | `test_sandbox_blocks_filesystem_even_without_guard` |
| Runaway queries | Timeout with `interrupt()` then kill, `memory_limit` plus `RLIMIT_AS`, row cap, bounded pool returning 503 | `analytics/sandbox.py` | timeout, memory, row cap and busy tests |
| Cross-workspace access | Every service filters by `workspace_id`; foreign ids return 404 | `services/*` | `OTHER`-user tests in 8 test modules, plus the E2E isolation test |
| Token theft from the database | Only SHA-256 hashes of tokens are stored | `core/security.py` | `test_security_basics.py` |
| Path traversal in storage keys | Keys resolved and checked with `is_relative_to(root)` | `storage/local.py` | `test_security_basics.py` |
| Oversized uploads | Streamed in 1 MiB chunks, rejected past `max_upload_bytes`, partial file removed | `storage/local.py` | `test_upload_size_limit` |
| CSV formula injection | Text cells starting with `= + - @ \t \r` prefixed with `'` | `analytics/engine.py` | `test_csv_formula_injection_is_neutralised` |
| Forged or expired export links | HMAC-SHA256 over id and expiry, constant-time compare, 600 s TTL | `services/exports.py` | `test_signed_link_tamper_and_expiry` |
| Export files lingering | Worker deletes files after 24 h | `services/exports.sweep_expired` | `test_expired_exports_lose_their_file_but_keep_history` |
| Shipping with demo secrets | API refuses to boot outside development with published defaults | `core/config.py` | `test_config.py` |
| Clickjacking, MIME sniffing | `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff` on web and API | `next.config.ts`, `main.py` | header assertions; `curl -I` against Compose |
| Running as root in containers | Images run as uid 10001 (API) and `node` (web) | Dockerfiles | `docker compose up` |

## Changes made during this review

1. **Boot-time secret check.** A deployment with `FACET_ENV` set to anything other than
   `development` now fails at startup if `FACET_SECRET_KEY`, or the seeded
   `FACET_DEV_TOKEN`, is a value published in this repository.
2. **Export retention.** Export files used to accumulate forever. The worker now sweeps
   files older than `FACET_EXPORT_RETENTION_S` (default 24 h).
3. **Response headers** on the API and the web app, and `no-store` on downloads.
4. **Charts no longer hide NULLs.** A NULL series value was silently folded into
   "Other". That was a correctness bug rather than a security one, found while reviewing
   chart output against SQL.

## Dependency audit

Run on 2026-11-26:

- `pip-audit` on the exported backend lock file: **no known vulnerabilities**.
- `npm audit --omit=dev` in `frontend/`: **0 vulnerabilities**.

CI runs ruff, mypy (strict), pytest, ESLint, `tsc`, Vitest and Playwright. It does not
run the audits; add them as a scheduled job.

## Known limitations

- **Single-user auth.** The development token ships in the frontend bundle. This is
  fine for a local install and not for a shared one (ADR-0005).
- **No script CSP.** Next.js's inline bootstrap needs nonces for `script-src`, so the CSP
  doesn't restrict scripts. React escapes all user content, and nothing renders HTML
  from user data.
- **No rate limiting** beyond the bounded query pool. Put a reverse proxy in front of a
  public deployment.
- **The query denylist is a denylist.** A new DuckDB release could add a function the
  guard doesn't know. The sandbox layer exists for exactly that case. Re-run
  `test_sql_security.py` on every DuckDB upgrade.
- **Uploaded files aren't malware-scanned.** They are only parsed by DuckDB, never
  executed or served back as-is.
