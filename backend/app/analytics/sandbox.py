"""Process-isolated pool for executing untrusted SQL.

Each sandbox is a long-lived child process. Every request opens a *fresh* in-memory
DuckDB connection inside it (see ``engine.open_sandbox``), so no state leaks between
queries or users. The pool size is the concurrency limit.

Timeouts are enforced twice: DuckDB's ``interrupt()`` fires inside the child at the
deadline, and if the child still has not answered after a grace period (e.g. it is
stuck in a non-interruptible operation or blew past its memory), the parent kills
and respawns it. Killing is the only cancellation that cannot be ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing as mp
import os
import resource
import traceback
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from typing import Any

from app.core.errors import Busy, QueryFailed, QueryTimeout

log = logging.getLogger(__name__)

KILL_GRACE_S = 3.0


@dataclass
class SandboxRequest:
    sql: str
    views: dict[str, str]
    mode: str = "query"  # query | explain
    memory_limit: str = "1GB"
    threads: int = 2
    timeout_s: float = 30.0
    max_rows: int = 10_000
    offset: int = 0
    limit: int = 100
    extra: dict[str, Any] = field(default_factory=dict)


def _child_main(conn: Connection, address_space_bytes: int | None) -> None:  # pragma: no cover
    """Entry point of a sandbox process."""
    # Hard ceiling on the child's virtual memory, beyond DuckDB's own memory_limit.
    if address_space_bytes:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_AS, (address_space_bytes, address_space_bytes))
    from app.analytics import engine

    while True:
        try:
            req: SandboxRequest | None = conn.recv()
        except EOFError:
            return
        if req is None:
            return
        try:
            limits = engine.SandboxLimits(req.memory_limit, req.threads, req.timeout_s)
            con = engine.open_sandbox(req.views, limits)
            try:
                if req.mode == "explain":
                    plan = engine.run_explain(con, req.sql, timeout_s=req.timeout_s)
                    conn.send(("ok", {"plan": plan}))
                else:
                    result = engine.run_paged_query(
                        con,
                        req.sql,
                        max_rows=req.max_rows,
                        offset=req.offset,
                        limit=req.limit,
                        timeout_s=req.timeout_s,
                    )
                    conn.send(("ok", result))
            finally:
                con.close()
        except TimeoutError as e:
            conn.send(("timeout", str(e)))
        except Exception as e:
            # DuckDB error messages are useful to analysts; tracebacks are not.
            msg = str(e).strip() or type(e).__name__
            log.debug("sandbox error: %s", traceback.format_exc())
            conn.send(("error", msg))


class _Worker:
    def __init__(self, ctx: Any, address_space_bytes: int | None) -> None:
        self._ctx = ctx
        self._as_bytes = address_space_bytes
        self._spawn()

    def _spawn(self) -> None:
        parent, child = self._ctx.Pipe()
        self.conn: Connection = parent
        self.proc = self._ctx.Process(
            target=_child_main, args=(child, self._as_bytes), daemon=True, name="facet-sandbox"
        )
        self.proc.start()
        child.close()

    def call(self, req: SandboxRequest) -> tuple[str, Any]:
        """Blocking round-trip. Runs in a thread, never on the event loop."""
        self.conn.send(req)
        if self.conn.poll(req.timeout_s + KILL_GRACE_S):
            try:
                return self.conn.recv()  # type: ignore[no-any-return]
            except EOFError:
                self.restart()
                return ("error", "The query process exited unexpectedly (likely out of memory).")
        log.warning("sandbox pid=%s unresponsive past deadline; killing", self.proc.pid)
        self.restart()
        return ("timeout", f"Query exceeded the {req.timeout_s:g}s time limit and was killed")

    def restart(self) -> None:
        self.kill()
        self._spawn()

    def kill(self) -> None:
        if self.proc.is_alive():
            self.proc.kill()
        self.proc.join(timeout=5)
        self.conn.close()

    @property
    def alive(self) -> bool:
        return self.proc.is_alive()


class SandboxPool:
    def __init__(
        self,
        size: int,
        *,
        acquire_timeout_s: float = 10.0,
        address_space_bytes: int | None = None,
    ) -> None:
        self.size = size
        self.acquire_timeout_s = acquire_timeout_s
        self._as_bytes = address_space_bytes
        # forkserver: children don't inherit the API's threads, sockets or DB pool.
        method = "forkserver" if "forkserver" in mp.get_all_start_methods() else "spawn"
        self._ctx = mp.get_context(method)
        self._idle: asyncio.Queue[_Worker] | None = None
        self._workers: list[_Worker] = []

    async def start(self) -> None:
        self._idle = asyncio.Queue()
        loop = asyncio.get_running_loop()
        for _ in range(self.size):
            w = await loop.run_in_executor(None, _Worker, self._ctx, self._as_bytes)
            self._workers.append(w)
            self._idle.put_nowait(w)

    async def stop(self) -> None:
        for w in self._workers:
            with contextlib.suppress(OSError, BrokenPipeError):
                w.conn.send(None)
            w.kill()
        self._workers.clear()

    async def execute(self, req: SandboxRequest) -> dict[str, Any]:
        if self._idle is None:
            raise RuntimeError("SandboxPool not started")
        try:
            worker = await asyncio.wait_for(self._idle.get(), timeout=self.acquire_timeout_s)
        except TimeoutError as e:
            raise Busy(
                "All query workers are busy. Try again in a moment.",
                details={"max_concurrent_queries": self.size},
            ) from e
        try:
            if not worker.alive:
                await asyncio.to_thread(worker.restart)
            status, payload = await asyncio.to_thread(worker.call, req)
        finally:
            self._idle.put_nowait(worker)
        if status == "ok":
            return payload  # type: ignore[no-any-return]
        if status == "timeout":
            raise QueryTimeout(str(payload), details={"timeout_s": req.timeout_s})
        raise QueryFailed(_clean_duckdb_error(str(payload)))


def _clean_duckdb_error(msg: str) -> str:
    # Hide internal view/temp-table plumbing and absolute storage paths from users.
    cleaned = msg.replace("facet_result", "result").replace("facet_q", "query")
    data_root = os.environ.get("FACET_DATA_DIR")
    if data_root:
        cleaned = cleaned.replace(os.path.abspath(data_root), "<storage>")
    return cleaned
