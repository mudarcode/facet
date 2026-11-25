"""Background worker: ``python -m app.workers.main``.

Polls the jobs table, runs handlers, heartbeats leases. Run several processes for
parallelism; ``SKIP LOCKED`` guarantees each job is claimed by one worker.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import traceback

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import Job
from app.services import datasets, jobs
from app.workers.handlers import HANDLERS, PermanentJobError, on_final_failure

log = logging.getLogger("facet.worker")


class Worker:
    def __init__(self, worker_id: str | None = None, kinds: list[str] | None = None) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.kinds = kinds
        self._stop = threading.Event()

    def stop(self, *_: object) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        """Claim and run at most one job. Returns True if a job was processed."""
        with session_scope() as db:
            for dead in jobs.reap_exhausted(db):
                db.expunge(dead)
                on_final_failure(dead, dead.error or "worker lost")
            job = jobs.claim(db, self.worker_id, self.kinds)
            if job is None:
                return False
            db.expunge(job)
        self._run(job)
        return True

    def _run(self, job: Job) -> None:
        handler = HANDLERS.get(job.kind)
        state = {"progress": 0.0, "message": "Running", "lost": False}
        done = threading.Event()

        def progress(p: float, msg: str) -> None:
            state["progress"], state["message"] = p, msg

        def beat() -> None:
            # Send progress when it changes, and renew the lease at least every lease/4.
            interval = max(1.0, get_settings().job_lease_s / 4)
            last: tuple[float, str] = (-1.0, "")
            last_sent = time.monotonic()
            while not done.wait(1.0):
                cur = (float(state["progress"]), str(state["message"]))
                now = time.monotonic()
                if cur != last or now - last_sent >= interval:
                    with session_scope() as db:
                        if not jobs.heartbeat(db, job.id, self.worker_id, *cur):
                            state["lost"] = True
                    last, last_sent = cur, now

        hb = threading.Thread(target=beat, daemon=True)
        hb.start()
        try:
            if handler is None:
                raise PermanentJobError(f"No handler for job kind {job.kind!r}")
            result = handler(job, progress)
            outcome: tuple[str, object] = ("ok", result)
        except PermanentJobError as e:
            outcome = ("permanent", str(e))
        except Exception as e:
            log.error("job %s failed: %s", job.id, traceback.format_exc())
            outcome = ("transient", f"{type(e).__name__}: {e}")
        finally:
            done.set()
            hb.join(timeout=5)

        final = False
        with session_scope() as db:
            fresh = db.get(Job, job.id)
            if fresh is None or fresh.worker_id != self.worker_id or fresh.status != "running":
                log.warning("job %s was reclaimed by another worker; discarding result", job.id)
                return
            if outcome[0] == "ok":
                jobs.complete(db, fresh, outcome[1])  # type: ignore[arg-type]
            else:
                jobs.fail(db, fresh, str(outcome[1]), retry=outcome[0] == "transient")
                final = fresh.status == "failed"
        if outcome[0] != "ok" and final:
            on_final_failure(job, str(outcome[1]))
        log.info("job %s (%s) -> %s", job.id, job.kind, outcome[0])

    def run_forever(self) -> None:
        settings = get_settings()
        with session_scope() as db:
            swept = datasets.sweep_deleting(db)
            if swept:
                log.info("finished %d interrupted dataset deletions", swept)
        log.info("worker %s started", self.worker_id)
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                log.exception("worker loop error")
                worked = False
            if not worked:
                self._stop.wait(settings.worker_poll_interval_s)
        log.info("worker %s stopped", self.worker_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    w = Worker()
    signal.signal(signal.SIGTERM, w.stop)
    signal.signal(signal.SIGINT, w.stop)
    w.run_forever()


if __name__ == "__main__":
    main()
