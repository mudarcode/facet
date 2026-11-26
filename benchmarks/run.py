"""End-to-end Facet benchmarks against a running API + worker.

Measures, for each generated dataset size:
  * ingest: upload wall time, worker-side job time, rows/s, peak RSS of the worker
    and of the API process tree while the upload streams in
  * profiling: worker-side profile time
  * queries: cold and warm latency (DuckDB engine time, API time, client round trip)
  * concurrency: throughput and 503s with more parallel queries than sandbox slots
  * exports: CSV and Parquet export time and throughput
  * engine comparisons (in-process DuckDB, same limits as the sandbox): CSV vs Parquet,
    narrow vs wide projection
  * SQL guard overhead (parse + validate + re-render) per query

Nothing here is estimated: every number is measured on this machine and written raw
to results/<timestamp>-<rev>.json together with the environment it ran in.

    uv run --project ../backend --group bench python run.py --rows 100000 1000000
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import httpx
import psutil
import sqlglot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from generate import generate  # noqa: E402

from app.analytics.sql_guard import validate_query  # noqa: E402

QUERIES: dict[str, str] = {
    "count": "SELECT count(*) FROM {t}",
    "group_by_region": "SELECT region, sum(qty * unit_price) AS revenue, count(*) AS n "
    "FROM {t} GROUP BY region ORDER BY revenue DESC",
    "top_categories": "SELECT category, sum(qty * unit_price) AS revenue FROM {t} "
    "GROUP BY category ORDER BY revenue DESC LIMIT 20",
    "monthly_series": "SELECT date_trunc('month', ordered_at) AS m, sum(qty) AS units "
    "FROM {t} GROUP BY 1 ORDER BY 1",
    "selective_filter": "SELECT * FROM {t} WHERE customer_id = 'cust_123' ORDER BY order_id",
    "count_distinct": "SELECT count(DISTINCT customer_id) FROM {t}",
    "window_rank": "SELECT * FROM (SELECT region, category, sum(qty) AS units, "
    "rank() OVER (PARTITION BY region ORDER BY sum(qty) DESC) AS r FROM {t} "
    "GROUP BY region, category) WHERE r <= 3 ORDER BY region, r",
    "preview_page": "SELECT * FROM {t} LIMIT 100",
}


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(xs: list[float]) -> dict[str, float]:
    return {
        "n": len(xs),
        "min": round(min(xs), 3),
        "p50": round(statistics.median(xs), 3),
        "p95": round(pct(xs, 0.95), 3),
        "max": round(max(xs), 3),
        "mean": round(statistics.fmean(xs), 3),
    }


class RssSampler:
    """Samples peak RSS (bytes) of a process tree every ``interval`` seconds."""

    def __init__(self, pid: int, interval: float = 0.05) -> None:
        self.proc = psutil.Process(pid)
        self.interval = interval
        self.peak = 0
        self.baseline = self._rss()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _rss(self) -> int:
        total = 0
        try:
            procs = [self.proc, *self.proc.children(recursive=True)]
        except psutil.Error:
            return 0
        for p in procs:
            try:
                total += p.memory_info().rss
            except psutil.Error:
                pass
        return total

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._rss())
            time.sleep(self.interval)

    def __enter__(self) -> RssSampler:
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join()

    def report(self) -> dict[str, float]:
        return {
            "baseline_mib": round(self.baseline / 2**20, 1),
            "peak_mib": round(self.peak / 2**20, 1),
            "delta_mib": round((self.peak - self.baseline) / 2**20, 1),
        }


def find_pid(fragment: str) -> int | None:
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if fragment in cmd and "python" in (p.info["name"] or "") and " uv " not in f" {cmd} ":
            return int(p.info["pid"])
    return None


class Client:
    def __init__(self, base: str, token: str) -> None:
        self.http = httpx.Client(
            base_url=base.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=600,
        )

    def wait_job(self, job_id: str, timeout: float = 1800) -> dict[str, Any]:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            j = self.http.get(f"/jobs/{job_id}").json()
            if j["status"] in ("succeeded", "failed", "cancelled"):
                return j
            time.sleep(0.1)
        raise TimeoutError(job_id)

    def upload(self, path: Path, name: str) -> tuple[dict[str, Any], float]:
        def chunks() -> Iterator[bytes]:
            with open(path, "rb") as f:
                while b := f.read(1 << 20):
                    yield b

        t0 = time.perf_counter()
        r = self.http.post(
            "/datasets",
            params={"filename": path.name, "name": name},
            content=chunks(),
            headers={"Content-Type": "application/octet-stream"},
        )
        r.raise_for_status()
        return r.json(), time.perf_counter() - t0

    def query(self, sql: str) -> tuple[dict[str, Any], float]:
        t0 = time.perf_counter()
        r = self.http.post("/queries/execute", json={"sql": sql, "limit": 100})
        rt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return {"status": r.status_code, "error": r.json()}, rt
        return r.json(), rt


def job_seconds(j: dict[str, Any]) -> float | None:
    if not j.get("started_at") or not j.get("finished_at"):
        return None
    s = dt.datetime.fromisoformat(j["started_at"])
    f = dt.datetime.fromisoformat(j["finished_at"])
    return round((f - s).total_seconds(), 3)


def bench_ingest(
    c: Client, meta: dict[str, Any], fmt: str, api_pid: int, worker_pid: int
) -> dict[str, Any]:
    path = Path(meta[fmt])
    with RssSampler(api_pid) as api_mem, RssSampler(worker_pid) as worker_mem:
        t0 = time.perf_counter()
        created, upload_s = c.upload(path, f"bench {meta['rows']} {fmt}")
        job = c.wait_job(created["job_id"])
        total_s = time.perf_counter() - t0
    assert job["status"] == "succeeded", job
    ds = c.http.get(f"/datasets/{created['dataset']['id']}").json()
    assert ds["row_count"] == meta["rows"], (ds["row_count"], meta["rows"])
    worker_s = job_seconds(job)
    return {
        "format": fmt,
        "file_bytes": meta[f"{fmt}_bytes"],
        "upload_s": round(upload_s, 3),
        "worker_ingest_s": worker_s,
        "end_to_end_s": round(total_s, 3),
        "rows_per_s_worker": round(meta["rows"] / worker_s) if worker_s else None,
        "rows_per_s_end_to_end": round(meta["rows"] / total_s),
        "upload_mib_per_s": round(meta[f"{fmt}_bytes"] / 2**20 / upload_s, 1),
        "parquet_bytes_stored": ds.get("processed_bytes"),
        "api_rss": api_mem.report(),
        "worker_rss": worker_mem.report(),
        "dataset_id": ds["id"],
        "sql_name": ds["sql_name"],
    }


def bench_profile(c: Client, dataset_id: str) -> dict[str, Any]:
    p = c.http.get(f"/datasets/{dataset_id}/profile").json()
    deadline = time.monotonic() + 1800
    while p["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(0.2)
        p = c.http.get(f"/datasets/{dataset_id}/profile").json()
    assert p["status"] == "ready", p
    prof = p["profile"]
    return {
        "profile_s": prof["duration_s"],
        "sampled": prof["sampled"],
        "columns": prof["column_count"],
    }


def bench_queries(c: Client, table: str, repeats: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, tmpl in QUERIES.items():
        sql = tmpl.format(t=table)
        cold, cold_rt = c.query(sql)
        assert "engine_ms" in cold, cold
        engine, api, rt = [], [], []
        for _ in range(repeats):
            r, t = c.query(sql)
            engine.append(r["engine_ms"])
            api.append(r["total_ms"])
            rt.append(t)
        out[name] = {
            "sql": sql,
            "rows_returned": cold["total_rows"],
            "cold": {
                "engine_ms": round(cold["engine_ms"], 2),
                "api_ms": round(cold["total_ms"], 2),
                "round_trip_ms": round(cold_rt, 2),
            },
            "warm_engine_ms": summarize(engine),
            "warm_api_ms": summarize(api),
            "warm_round_trip_ms": summarize(rt),
        }
    return out


def bench_concurrency(c: Client, table: str, parallel: int, total: int) -> dict[str, Any]:
    sql = QUERIES["top_categories"].format(t=table)
    lat: list[float] = []
    codes: dict[str, int] = {}

    def one(_: int) -> None:
        r, t = c.query(sql)
        key = "200" if "engine_ms" in r else str(r.get("status"))
        codes[key] = codes.get(key, 0) + 1
        if key == "200":
            lat.append(t)

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(parallel) as ex:
        list(ex.map(one, range(total)))
    wall = time.perf_counter() - t0
    return {
        "query": "top_categories",
        "parallel_clients": parallel,
        "requests": total,
        "status_counts": codes,
        "wall_s": round(wall, 3),
        "throughput_qps": round(codes.get("200", 0) / wall, 2),
        "round_trip_ms": summarize(lat) if lat else None,
    }


def bench_exports(c: Client, dataset_id: str, rows: int, worker_pid: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fmt in ("csv", "parquet"):
        with RssSampler(worker_pid) as mem:
            t0 = time.perf_counter()
            r = c.http.post(
                "/exports",
                json={"source": {"kind": "dataset", "dataset_id": dataset_id}, "format": fmt},
            ).json()
            job = c.wait_job(r["job_id"])
            wall = time.perf_counter() - t0
        e = c.http.get(f"/exports/{r['id']}").json()
        assert e["status"] == "succeeded" and e["row_count"] == rows, e
        ws = job_seconds(job)
        out[fmt] = {
            "worker_s": ws,
            "end_to_end_s": round(wall, 3),
            "rows_per_s_worker": round(rows / ws) if ws else None,
            "bytes": e["bytes"],
            "worker_rss": mem.report(),
        }
    return out


def time_engine(con: duckdb.DuckDBPyConnection, sql: str, repeats: int) -> dict[str, float]:
    con.execute(sql).fetchall()  # warm the OS page cache / metadata
    xs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        xs.append((time.perf_counter() - t0) * 1000)
    return summarize(xs)


def bench_engine(meta: dict[str, Any], repeats: int, memory: str, threads: int) -> dict[str, Any]:
    """CSV-direct vs Parquet, and projection width, inside DuckDB with sandbox limits."""
    con = duckdb.connect(":memory:")
    con.execute(f"SET memory_limit = '{memory}'")
    con.execute(f"SET threads = {threads}")
    csv = f"read_csv('{meta['csv']}', header = true)"
    pq = f"read_parquet('{meta['parquet']}')"
    agg = "SELECT region, sum(qty * unit_price) FROM {s} GROUP BY region"
    narrow = "SELECT max(unit_price) FROM {s}"
    wide = (
        "SELECT max(order_id), max(ordered_at), max(ship_date), max(region), max(category), "
        "max(customer_id), max(qty), max(unit_price), bool_or(is_returning), max(shipping), "
        "max(discount_pct) FROM {s}"
    )
    res = {}
    for label, tmpl in (("group_by", agg), ("narrow_1_col", narrow), ("wide_11_cols", wide)):
        res[label] = {
            "csv_ms": time_engine(con, tmpl.format(s=csv), repeats),
            "parquet_ms": time_engine(con, tmpl.format(s=pq), repeats),
        }
        res[label]["parquet_speedup_p50"] = round(
            res[label]["csv_ms"]["p50"] / res[label]["parquet_ms"]["p50"], 1
        )
    con.close()
    return {"memory_limit": memory, "threads": threads, "repeats": repeats, "results": res}


def bench_guard(iterations: int) -> dict[str, Any]:
    allowed = {"orders"}
    out = {}
    for name, tmpl in QUERIES.items():
        sql = tmpl.format(t="orders")
        validate_query(sql, allowed)
        t0 = time.perf_counter()
        for _ in range(iterations):
            validate_query(sql, allowed)
        out[name] = round((time.perf_counter() - t0) / iterations * 1e6, 1)
    return {"iterations": iterations, "microseconds_per_query": out}


def bench_sandbox_setup(meta: dict[str, Any], iterations: int) -> dict[str, Any]:
    """Cost of the per-query isolation: a fresh locked-down DuckDB with one Parquet view."""
    from app.analytics.engine import SandboxLimits, open_sandbox

    limits = SandboxLimits("1GB", 2, 30)
    xs = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        con = open_sandbox({"orders": meta["parquet"]}, limits)
        con.close()
        xs.append((time.perf_counter() - t0) * 1000)
    return {"open_and_close_ms": summarize(xs)}


def environment(c: Client) -> dict[str, Any]:
    def run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return "unknown"

    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    pg = run(["psql", "--version"])
    return {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_rev": run(["git", "-C", str(HERE.parent), "rev-parse", "--short", "HEAD"]),
        "git_dirty": bool(run(["git", "-C", str(HERE.parent), "status", "--porcelain"])),
        "platform": platform.platform(),
        "cpu_model": cpu,
        "logical_cpus": psutil.cpu_count(),
        "memory_gib": round(psutil.virtual_memory().total / 2**30, 1),
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "sqlglot": sqlglot.__version__,
        "postgres_client": pg,
        "api_settings": c.http.get("/settings").json(),
        "note": "Shared cloud VM; numbers include noise from co-tenants. "
        "API, worker, PostgreSQL and this client all ran on the same machine.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, nargs="+", default=[100_000, 1_000_000, 5_000_000])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--api", default=os.environ.get("FACET_API", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("FACET_TOKEN", "facet-dev-token"))
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--keep", action="store_true", help="keep benchmark datasets afterwards")
    a = ap.parse_args()

    c = Client(a.api, a.token)
    api_pid, worker_pid = find_pid("uvicorn app.main"), find_pid("app.workers.main")
    if not api_pid or not worker_pid:
        sys.exit(
            "Start the API (uvicorn app.main:app) and the worker (python -m app.workers.main) first."
        )
    env = environment(c)
    print(json.dumps({k: env[k] for k in ("git_rev", "cpu_model", "logical_cpus", "memory_gib")}))
    settings = env["api_settings"]
    runs = []
    for rows in a.rows:
        print(f"== {rows:,} rows: generating")
        meta = generate(rows, a.seed, HERE / "data")
        run: dict[str, Any] = {"rows": rows, "dataset": meta}
        print("   ingest csv / parquet")
        run["ingest_csv"] = bench_ingest(c, meta, "csv", api_pid, worker_pid)
        run["ingest_parquet"] = bench_ingest(c, meta, "parquet", api_pid, worker_pid)
        ds_id, table = run["ingest_csv"]["dataset_id"], run["ingest_csv"]["sql_name"]
        print("   profile")
        run["profile"] = bench_profile(c, ds_id)
        print("   queries")
        run["queries"] = bench_queries(c, table, a.repeats)
        print("   concurrency")
        slots = int(settings["max_concurrent_queries"])
        run["concurrency"] = bench_concurrency(c, table, parallel=slots * 2, total=slots * 8)
        print("   exports")
        run["exports"] = bench_exports(c, ds_id, rows, worker_pid)
        print("   engine comparisons")
        run["engine"] = bench_engine(meta, a.repeats, settings["query_memory_limit"], 2)
        run["sandbox_setup"] = bench_sandbox_setup(meta, 50)
        runs.append(run)
        if not a.keep:
            for key in ("ingest_csv", "ingest_parquet"):
                c.http.delete(f"/datasets/{run[key]['dataset_id']}")
    result = {"environment": env, "guard": bench_guard(2000), "runs": runs}
    stamp = env["timestamp_utc"].replace(":", "").replace("-", "")[:15]
    out = HERE / "results" / f"{stamp}-{env['git_rev']}.json"
    out.write_text(json.dumps(result, indent=2))
    (HERE / "results" / "latest.json").write_text(json.dumps(result, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
