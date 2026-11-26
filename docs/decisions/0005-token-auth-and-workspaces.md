# 0005. Bearer tokens and workspace scoping instead of a login flow

Status: accepted (Phase 1)

## Context

The spec asks for access restrictions. Building registration, password resets and
sessions is a lot of surface that does not demonstrate the analytics engine.

## Decision

- API tokens are random (`fct_` + 32 bytes, URL-safe). Only their SHA-256 is stored.
- Every request resolves to a `Principal(user_id, workspace_id)`. Every service function
  takes the workspace id, and every query filters by it. A dataset, chart, dashboard or
  export from another workspace returns 404, not 403, so its existence isn't revealed.
- The SQL guard resolves table names against the caller's datasets only. A saved query
  used as a chart source is re-validated in the caller's workspace.
- One development user and token are seeded so the app works out of the box.
- Outside `FACET_ENV=development`, the API **refuses to start** if `FACET_SECRET_KEY` or
  the seeded `FACET_DEV_TOKEN` still has a value published in this repository.

## Consequences

- Tests use two users and assert isolation for datasets, queries, saved queries, charts,
  dashboards and exports. The E2E suite repeats the check against the real UI.
- A real deployment would replace `get_principal` with OIDC or session auth. Nothing else
  changes, because nothing below it knows how the principal was obtained.
- The token ships in the frontend bundle (`NEXT_PUBLIC_FACET_TOKEN`). That is acceptable
  for a single-user local install, but not for a shared deployment.
