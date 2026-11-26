"""Render benchmarks/REPORT.md and plots from a raw results JSON (default: results/latest.json).

Every number in the report is copied from the JSON; nothing is computed beyond ratios
and unit conversions, which are labelled as such.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
# Validated categorical palette (light theme), fixed order; see frontend/app/globals.css.
C1, C2, C3 = "#257de0", "#f47230", "#00b894"
INK, GRID, MUTED = "#121722", "#e3e6ec", "#646c7e"


def fmt_int(n: float | None) -> str:
    return "—" if n is None else f"{n:,.0f}"


def fmt_ms(x: float) -> str:
    return f"{x:,.1f}" if x < 100 else f"{x:,.0f}"


def mib(b: int | None) -> str:
    return "—" if b is None else f"{b / 2**20:,.1f} MiB"


def style(ax: Any, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=12)
    ax.set_ylabel(ylabel, fontsize=9, color=MUTED)
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def bar_labels(ax: Any, bars: Any, fmt: str = "{:,.0f}") -> None:
    for b in bars:
        ax.annotate(
            fmt.format(b.get_height()),
            (b.get_x() + b.get_width() / 2, b.get_height()),
            ha="center",
            va="bottom",
            fontsize=8,
            color=MUTED,
            xytext=(0, 2),
            textcoords="offset points",
        )


def plots(d: dict[str, Any], out: Path) -> list[str]:
    out.mkdir(exist_ok=True)
    runs = d["runs"]
    files = []
    labels = [f"{r['rows']:,}" for r in runs]
    x = range(len(runs))
    w = 0.38

    # 1. Ingest throughput (worker-side), CSV vs Parquet input
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    b1 = ax.bar(
        [i - w / 2 for i in x],
        [r["ingest_csv"]["rows_per_s_worker"] / 1e3 for r in runs],
        w,
        color=C1,
        label="CSV upload",
    )
    b2 = ax.bar(
        [i + w / 2 for i in x],
        [r["ingest_parquet"]["rows_per_s_worker"] / 1e3 for r in runs],
        w,
        color=C2,
        label="Parquet upload",
    )
    bar_labels(ax, b1)
    bar_labels(ax, b2)
    ax.set_xticks(list(x), labels)
    ax.set_xlabel("rows in file", fontsize=9, color=MUTED)
    style(ax, "Ingest throughput (worker: validate, type, write Parquet)", "thousand rows / s")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "ingest_throughput.svg")
    plt.close(fig)
    files.append("plots/ingest_throughput.svg")

    # 2. Warm query latency at the largest size: engine vs round trip
    big = runs[-1]
    names = list(big["queries"])
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=150)
    xi = range(len(names))
    e = [big["queries"][n]["warm_engine_ms"]["p50"] for n in names]
    rt = [big["queries"][n]["warm_round_trip_ms"]["p50"] for n in names]
    b1 = ax.bar([i - w / 2 for i in xi], e, w, color=C1, label="DuckDB engine")
    b2 = ax.bar([i + w / 2 for i in xi], rt, w, color=C2, label="HTTP round trip")
    bar_labels(ax, b1, "{:,.0f}")
    bar_labels(ax, b2, "{:,.0f}")
    ax.set_xticks(list(xi), [n.replace("_", "\n") for n in names], fontsize=8)
    style(
        ax,
        f"Warm query latency, median of {big['queries'][names[0]]['warm_engine_ms']['n']} runs ({big['rows']:,} rows)",
        "milliseconds",
    )
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "query_latency.svg")
    plt.close(fig)
    files.append("plots/query_latency.svg")

    # 3. CSV vs Parquet scan time at the largest size
    eng = big["engine"]["results"]
    kinds = list(eng)
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    xi = range(len(kinds))
    b1 = ax.bar(
        [i - w / 2 for i in xi],
        [eng[k]["csv_ms"]["p50"] for k in kinds],
        w,
        color=C1,
        label="read_csv",
    )
    b2 = ax.bar(
        [i + w / 2 for i in xi],
        [eng[k]["parquet_ms"]["p50"] for k in kinds],
        w,
        color=C2,
        label="read_parquet",
    )
    bar_labels(ax, b1)
    bar_labels(ax, b2)
    ax.set_xticks(list(xi), [k.replace("_", " ") for k in kinds])
    style(
        ax,
        f"Same query over CSV vs Parquet ({big['rows']:,} rows, 2 threads)",
        "milliseconds (median)",
    )
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "csv_vs_parquet.svg")
    plt.close(fig)
    files.append("plots/csv_vs_parquet.svg")
    return files


def report(d: dict[str, Any], src: Path) -> str:
    env, runs = d["environment"], d["runs"]
    s = env["api_settings"]
    L: list[str] = []
    a = L.append
    a("# Facet benchmark report\n")
    a(f"Generated from [`{src.relative_to(HERE)}`]({src.relative_to(HERE)}) by `report.py`. ")
    a("All figures are measured on the machine below. Nothing is extrapolated.\n")
    a("## Environment\n")
    a("| | |\n|---|---|")
    for k, v in (
        ("Run at (UTC)", env["timestamp_utc"]),
        (
            "Git revision",
            f"`{env['git_rev']}`" + (" (uncommitted changes)" if env["git_dirty"] else ""),
        ),
        ("CPU", f"{env['cpu_model']}, {env['logical_cpus']} logical CPUs"),
        ("Memory", f"{env['memory_gib']} GiB"),
        ("OS", env["platform"]),
        ("Python / DuckDB / sqlglot", f"{env['python']} / {env['duckdb']} / {env['sqlglot']}"),
        ("PostgreSQL", env["postgres_client"]),
        (
            "Query sandbox limits",
            f"{s['query_memory_limit']} memory, {s['query_timeout_s']} s timeout, {s['max_concurrent_queries']} concurrent sandboxes",
        ),
    ):
        a(f"| {k} | {v} |")
    a(f"\n> {env['note']}\n")

    a("## Data\n")
    a(
        "Synthetic orders tables from `generate.py`: 11 columns (BIGINT, TIMESTAMP, DATE, 4 × VARCHAR, INTEGER, DOUBLE, BOOLEAN, DOUBLE), "
        "skewed category cardinality, 5% nulls in two columns. Every value is a hash of (row, seed), so files are reproducible byte-for-byte.\n"
    )
    a("| Rows | CSV size | Parquet size (zstd) |\n|---:|---:|---:|")
    for r in runs:
        m = r["dataset"]
        a(f"| {r['rows']:,} | {mib(m['csv_bytes'])} | {mib(m['parquet_bytes'])} |")

    a("\n## Ingestion\n")
    a(
        "Upload streams the file to disk through the API, then a worker validates it, infers types, records rejected rows and writes zstd Parquet. "
        "*Worker* time is the job's own start→finish; *end to end* also includes the upload, queueing and polling. "
        "RSS figures are the peak increase over the process tree's baseline while the file was ingested, sampled every 50 ms, with the absolute peak in brackets (API includes its pre-forked sandbox processes). "
        "The API's memory does not grow with file size because uploads are streamed to disk in chunks; the worker's growth is DuckDB's CSV reader and Parquet writer, bounded by its memory limit.\n"
    )
    a(
        "| Rows | Input | Upload | Worker | End to end | Rows/s (worker) | API peak RSS Δ | Worker peak RSS Δ |\n|---:|---|---:|---:|---:|---:|---:|---:|"
    )
    for r in runs:
        for key, label in (("ingest_csv", "CSV"), ("ingest_parquet", "Parquet")):
            g = r[key]
            a(
                f"| {r['rows']:,} | {label} ({mib(g['file_bytes'])}) | {g['upload_s']:.2f} s | {g['worker_ingest_s']:.2f} s | {g['end_to_end_s']:.2f} s | "
                f"{fmt_int(g['rows_per_s_worker'])} | {g['api_rss']['delta_mib']:,.1f} MiB (of {g['api_rss']['peak_mib']:,.0f}) | {g['worker_rss']['delta_mib']:,.1f} MiB (of {g['worker_rss']['peak_mib']:,.0f}) |"
            )
    a("\n![Ingest throughput](plots/ingest_throughput.svg)\n")

    a("## Profiling\n")
    a("| Rows | Profile time (worker) | Sampled? |\n|---:|---:|---|")
    for r in runs:
        p = r["profile"]
        a(
            f"| {r['rows']:,} | {p['profile_s']:.2f} s | {'yes (seeded reservoir)' if p['sampled'] else 'no, exact'} |"
        )

    a("\n## SQL query latency\n")
    a(
        "Each query was run once cold (first run after ingest) and then repeated. *Engine* is DuckDB execution inside the sandbox, including writing the capped result to a temp table. "
        "*API* is the server-side total, including SQL validation, sandbox dispatch and history logging. *Round trip* is measured by the HTTP client. Medians and p95 of warm runs.\n"
    )
    for r in runs:
        a(f"\n**{r['rows']:,} rows**\n")
        a(
            "| Query | Rows out | Cold engine | Warm engine p50 | Warm engine p95 | Warm API p50 | Warm round trip p50 |\n|---|---:|---:|---:|---:|---:|---:|"
        )
        for n, q in r["queries"].items():
            a(
                f"| `{n}` | {q['rows_returned']:,} | {fmt_ms(q['cold']['engine_ms'])} ms | {fmt_ms(q['warm_engine_ms']['p50'])} ms | {fmt_ms(q['warm_engine_ms']['p95'])} ms | "
                f"{fmt_ms(q['warm_api_ms']['p50'])} ms | {fmt_ms(q['warm_round_trip_ms']['p50'])} ms |"
            )
    a("\n![Query latency](plots/query_latency.svg)\n")
    a("<details><summary>Benchmark queries</summary>\n")
    for n, q in runs[0]["queries"].items():
        a(f"- `{n}`: `{q['sql']}`")
    a("\n</details>\n")

    a("### Fixed per-query cost of isolation\n")
    a(
        "Each query gets a fresh, locked-down in-memory DuckDB (allowed paths, no external access, configuration locked) in a pre-forked worker process. "
        "Opening and closing that connection with one Parquet view, measured in-process:\n"
    )
    a("| Rows | p50 | p95 |\n|---:|---:|---:|")
    for r in runs:
        ss = r["sandbox_setup"]["open_and_close_ms"]
        a(f"| {r['rows']:,} | {ss['p50']:.1f} ms | {ss['p95']:.1f} ms |")
    g = d["guard"]["microseconds_per_query"]
    a(
        f"\nSQL guard (parse with sqlglot, walk the AST, re-render) over {d['guard']['iterations']:,} iterations: "
        f"{min(g.values()):.0f}–{max(g.values()):.0f} µs per query (`count` {g['count']:.0f} µs, `window_rank` {g['window_rank']:.0f} µs).\n"
    )

    a("## Concurrency\n")
    a(
        "More clients than sandbox slots, all running `top_categories`. Requests that cannot get a slot within the acquire timeout receive HTTP 503.\n"
    )
    a(
        "| Rows | Clients | Requests | Status codes | Wall time | Throughput | Round trip p50 / p95 |\n|---:|---:|---:|---|---:|---:|---:|"
    )
    for r in runs:
        c = r["concurrency"]
        rt = c["round_trip_ms"]
        codes = ", ".join(f"{k}: {v}" for k, v in sorted(c["status_counts"].items()))
        a(
            f"| {r['rows']:,} | {c['parallel_clients']} | {c['requests']} | {codes} | {c['wall_s']:.2f} s | {c['throughput_qps']:.1f} q/s | "
            f"{fmt_ms(rt['p50'])} / {fmt_ms(rt['p95'])} ms |"
        )

    a("\n## Exports\n")
    a(
        "Full-dataset export as a background job (CSV includes formula-injection sanitising of text cells).\n"
    )
    a(
        "| Rows | Format | Worker | End to end | Rows/s (worker) | File size | Worker peak RSS Δ |\n|---:|---|---:|---:|---:|---:|---:|"
    )
    for r in runs:
        for fmt, e in r["exports"].items():
            a(
                f"| {r['rows']:,} | {fmt.upper()} | {e['worker_s']:.2f} s | {e['end_to_end_s']:.2f} s | {fmt_int(e['rows_per_s_worker'])} | {mib(e['bytes'])} | {e['worker_rss']['delta_mib']:,.1f} MiB |"
            )

    a("\n## Why store Parquet: same query over CSV vs Parquet\n")
    a("In-process DuckDB with the sandbox's memory limit and 2 threads, OS cache warm. Medians.\n")
    a(
        "| Rows | Query | read_csv | read_parquet | Ratio (CSV ÷ Parquet) |\n|---:|---|---:|---:|---:|"
    )
    for r in runs:
        for k, v in r["engine"]["results"].items():
            a(
                f"| {r['rows']:,} | {k.replace('_', ' ')} | {fmt_ms(v['csv_ms']['p50'])} ms | {fmt_ms(v['parquet_ms']['p50'])} ms | {v['parquet_speedup_p50']}× |"
            )
    a("\n![CSV vs Parquet](plots/csv_vs_parquet.svg)\n")

    a("## Reproduce\n")
    a(
        "```bash\n# terminal 1-2: API and worker (see README)\ncd backend\nuv run --group bench python ../benchmarks/run.py --rows 100000 1000000 5000000\nuv run --group bench python ../benchmarks/report.py\n```\n"
    )
    a("## Caveats\n")
    a(
        "- One shared cloud VM; the API, worker, PostgreSQL and the load generator compete for the same 4 vCPUs. Expect run-to-run variation; compare runs from the same machine."
    )
    a(
        "- Upload time is loopback HTTP, so it measures the server's streaming path, not a real network."
    )
    a("- RSS is sampled every 50 ms; very short spikes can be missed.")
    a("- Warm query numbers benefit from the OS page cache holding the Parquet file.")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", type=Path, default=HERE / "results" / "latest.json")
    a = ap.parse_args()
    src = a.results.resolve()
    d = json.loads(src.read_text())
    plots(d, HERE / "plots")
    (HERE / "REPORT.md").write_text(report(d, src))
    print(f"wrote {HERE / 'REPORT.md'}")


if __name__ == "__main__":
    main()
