# 0002. PostgreSQL job queue with leases instead of Redis or Celery

Status: accepted (Phase 0)

## Context

Ingest, profiling, transform materialisation and exports all take longer than a
request should. They need to survive API restarts, report progress, and recover when a
worker crashes partway through. The expected volume is a few jobs a minute.

## Decision

A `jobs` table in the same PostgreSQL database as the metadata (`app/services/jobs.py`):

- **Enqueue is transactional.** The dataset or export row and its job are inserted in the
  same transaction. A crash can never leave a dataset without its ingest job.
- **Claiming** uses `SELECT … FOR UPDATE SKIP LOCKED`, ordered by creation time. Any
  number of worker processes can poll without double-claiming a job.
- **Leases and heartbeats.** A claimed job gets `lease_expires_at = now + 60 s`. A
  heartbeat thread renews it at least every 15 s and writes progress on each beat. If a
  heartbeat finds the job has been reclaimed, the worker discards its result.
- **Retries.** Transient errors retry up to `job_max_attempts`. Errors classed as
  `PermanentJobError` (such as a malformed file) fail at once. `reap_exhausted` finishes
  jobs whose lease expired on the last attempt, and `on_final_failure` marks the owning
  dataset or export failed so the UI never spins forever.

## Alternatives rejected

- **Redis with RQ or Celery** adds a service to run and secure. Enqueueing can't share a
  transaction with the metadata write, so it needs an outbox pattern to be correct.
- **FastAPI `BackgroundTasks`** dies with the API process, so a deploy would lose the job.

## Consequences

- Throughput tops out at Postgres polling rates (one claim query per idle worker every
  0.5 s). That is far beyond what this workload needs.
- Tests cover concurrent claiming, lease expiry and reclaim, retry and permanent failure
  (`tests/test_jobs.py`).
