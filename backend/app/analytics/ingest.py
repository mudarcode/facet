"""Convert an uploaded CSV/Parquet file into a validated, columnar Parquet dataset.

Runs in the background worker. DuckDB streams the source file and writes Parquet
row group by row group, so peak memory is bounded by ``memory_limit`` (DuckDB spills
to ``temp_directory`` when needed) rather than by file size.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from app.analytics.engine import quote_ident, quote_literal

SUPPORTED_ENCODINGS = {"utf-8", "utf-16", "latin-1"}
# Types a user may choose when correcting inference. Keys are UI labels.
CASTABLE_TYPES = {
    "BOOLEAN",
    "BIGINT",
    "INTEGER",
    "DOUBLE",
    "DECIMAL(18,4)",
    "VARCHAR",
    "DATE",
    "TIMESTAMP",
}


class IngestError(Exception):
    """A user-facing ingestion failure (bad file, unsupported content, …)."""


@dataclass
class IngestOptions:
    delimiter: str | None = None  # None = auto-detect
    header: bool | None = None  # None = auto-detect
    encoding: str = "auto"  # auto | utf-8 | utf-16 | latin-1
    quote: str | None = None
    skip_rows: int = 0
    max_reject_ratio: float = 0.1
    type_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IngestOptions:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class IngestResult:
    schema: list[dict[str, Any]]
    row_count: int
    column_count: int
    report: dict[str, Any]
    duration_s: float


ProgressFn = Callable[[float, str], None]


def _connect(memory_limit: str, threads: int, temp_dir: Path) -> duckdb.DuckDBPyConnection:
    temp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(
        ":memory:",
        config={"autoload_known_extensions": False, "autoinstall_known_extensions": False},
    )
    con.execute(f"SET memory_limit = {quote_literal(memory_limit)}")
    con.execute(f"SET threads = {int(threads)}")
    con.execute(f"SET temp_directory = {quote_literal(str(temp_dir))}")
    con.execute("SET enable_progress_bar = false")
    return con


def _csv_source(
    path: Path, opts: IngestOptions, encoding: str, varchar_cols: list[str] | None = None
) -> str:
    args = [
        quote_literal(str(path)),
        "store_rejects = true",
        "sample_size = 20480",
        f"encoding = {quote_literal(encoding)}",
    ]
    if opts.delimiter:
        args.append(f"delim = {quote_literal(opts.delimiter)}")
    if opts.header is not None:
        args.append(f"header = {'true' if opts.header else 'false'}")
    if opts.quote:
        args.append(f"quote = {quote_literal(opts.quote)}")
    if opts.skip_rows:
        args.append(f"skip = {int(opts.skip_rows)}")
    if varchar_cols:
        types = ", ".join(f"{quote_literal(c)}: 'VARCHAR'" for c in varchar_cols)
        args.append(f"types = {{{types}}}")
    return f"read_csv({', '.join(args)})"


def _with_progress(
    con: duckdb.DuckDBPyConnection, sql: str, progress: ProgressFn | None, lo: float, hi: float
) -> None:
    """Run ``sql`` while a side thread reports DuckDB's own progress estimate."""
    if progress is None:
        con.execute(sql)
        return
    done = threading.Event()

    def _poll() -> None:
        while not done.wait(0.5):
            try:
                pct = con.query_progress()
            except Exception:
                return
            if pct is not None and pct >= 0:
                progress(lo + (hi - lo) * min(pct, 100) / 100, "Converting to Parquet")

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    try:
        con.execute(sql)
    finally:
        done.set()
        t.join(timeout=2)


def ingest_file(
    src: Path,
    fmt: str,
    out: Path,
    options: IngestOptions,
    *,
    memory_limit: str,
    threads: int,
    temp_dir: Path,
    progress: ProgressFn | None = None,
) -> IngestResult:
    """Validate ``src`` and write it as Parquet to ``out``. Raises IngestError.

    Pipeline (all inside DuckDB, streaming):
      1. sniff / open the source and read its inferred schema
      2. COPY source -> Parquet (CSV: malformed rows go to ``reject_errors``)
      3. if the user corrected types: COPY stage Parquet -> final Parquet with TRY_CAST
         (a separate pass, because DuckDB pushes casts into the CSV reader, which would
         turn a failed cast into a rejected row instead of a NULL)
    """
    t0 = time.perf_counter()
    if not src.exists() or src.stat().st_size == 0:
        raise IngestError("The file is empty.")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = out.with_name(out.name + ".stage.parquet")
    con = _connect(memory_limit, threads, temp_dir)
    report: dict[str, Any] = {"warnings": []}
    try:
        if fmt == "csv":
            encoding = "utf-8" if options.encoding == "auto" else options.encoding
            if encoding not in SUPPORTED_ENCODINGS:
                raise IngestError(f"Unsupported encoding {options.encoding!r}")
            cols = _csv_columns(con, src, options, encoding)
            overrides = _validate_overrides(cols, options.type_overrides)
            target = stage if overrides else out
            _copy_csv(con, src, options, encoding, overrides, target, progress)
            if options.encoding == "auto" and _encoding_errors(con) > 0:
                # Invalid UTF-8 can appear anywhere in a file; retry the whole pass as Latin-1.
                encoding = "latin-1"
                con.execute("DELETE FROM reject_errors")
                con.execute("DELETE FROM reject_scans")
                cols = _csv_columns(con, src, options, encoding)
                _copy_csv(con, src, options, encoding, overrides, target, progress)
                report["warnings"].append("File is not valid UTF-8; decoded as Latin-1.")
            report["encoding"] = encoding
            kept_row = con.execute(
                f"SELECT count(*) FROM read_parquet({quote_literal(str(target))})"
            ).fetchone()
            _collect_rejects(
                con, report, int(kept_row[0]) if kept_row else 0, options.max_reject_ratio
            )
            staged_src = target
        elif fmt == "parquet":
            pq = f"read_parquet({quote_literal(str(src))})"
            try:
                cols = [(c["name"], c["type"]) for c in _describe(con, pq)]
                meta = con.execute(
                    f"SELECT count(DISTINCT row_group_id) "
                    f"FROM parquet_metadata({quote_literal(str(src))})"
                ).fetchone()
            except duckdb.Error as e:
                raise IngestError(f"Not a valid Parquet file: {_first_line(e)}") from e
            report["source_row_groups"] = int(meta[0]) if meta else None
            overrides = _validate_overrides(cols, options.type_overrides)
            if not overrides:
                # Rewriting (rather than copying bytes) decodes every page, so corrupted
                # data fails here instead of later inside a user's query.
                _run_copy(con, f"SELECT * FROM {pq}", out, progress)
            staged_src = src
        else:
            raise IngestError(f"Unsupported format: {fmt}")

        if not cols:
            raise IngestError("The file has no columns.")
        _check_headers(cols, report)

        if overrides:
            staged = f"read_parquet({quote_literal(str(staged_src))})"
            select_list = ", ".join(
                f"TRY_CAST({quote_ident(n)} AS {overrides[n]}) AS {quote_ident(n)}"
                if n in overrides
                else quote_ident(n)
                for n, _ in cols
            )
            _run_copy(con, f"SELECT {select_list} FROM {staged}", out, progress)
            report["type_overrides"] = overrides
            report["cast_failures"] = _cast_failures(
                con, staged, f"read_parquet({quote_literal(str(out))})", overrides
            )

        out_src = f"read_parquet({quote_literal(str(out))})"
        row = con.execute(f"SELECT count(*) FROM {out_src}").fetchone()
        row_count = int(row[0]) if row else 0
        if row_count == 0:
            raise IngestError("The file contains no data rows.")

        schema = [
            {"name": c["name"], "type": c["type"], "nullable": True}
            for c in _describe(con, out_src)
        ]
        if progress:
            progress(0.95, "Finalising")
        return IngestResult(
            schema=schema,
            row_count=row_count,
            column_count=len(schema),
            report=report,
            duration_s=time.perf_counter() - t0,
        )
    except duckdb.Error as e:
        out.unlink(missing_ok=True)
        raise IngestError(f"Could not read the file: {_first_line(e)}") from e
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        stage.unlink(missing_ok=True)
        con.close()


def _validate_overrides(cols: list[tuple[str, str]], overrides: dict[str, str]) -> dict[str, str]:
    names = {c for c, _ in cols}
    unknown = set(overrides) - names
    if unknown:
        raise IngestError(f"Type override for unknown column(s): {', '.join(sorted(unknown))}")
    inferred = dict(cols)
    applied: dict[str, str] = {}
    for name, target in overrides.items():
        t = target.upper().replace(" ", "")
        if t not in CASTABLE_TYPES:
            raise IngestError(f"Unsupported target type {target!r} for column {name!r}")
        if t != inferred[name].upper().replace(" ", ""):
            applied[name] = t
    return applied


def _csv_columns(
    con: duckdb.DuckDBPyConnection, src: Path, opts: IngestOptions, encoding: str
) -> list[tuple[str, str]]:
    try:
        return [(c["name"], c["type"]) for c in _describe(con, _csv_source(src, opts, encoding))]
    except duckdb.Error as e:
        raise IngestError(f"Could not parse CSV: {_first_line(e)}") from e


def _copy_csv(
    con: duckdb.DuckDBPyConnection,
    src: Path,
    opts: IngestOptions,
    encoding: str,
    overrides: dict[str, str],
    target: Path,
    progress: ProgressFn | None,
) -> None:
    # Columns being re-typed are read as raw text so the later TRY_CAST sees the original.
    source = _csv_source(src, opts, encoding, varchar_cols=list(overrides))
    _run_copy(con, f"SELECT * FROM {source}", target, progress)


def _run_copy(
    con: duckdb.DuckDBPyConnection, select_sql: str, target: Path, progress: ProgressFn | None
) -> None:
    if progress:
        progress(0.1, "Converting to Parquet")
    _with_progress(
        con,
        f"COPY ({select_sql}) TO {quote_literal(str(target))} "
        "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)",
        progress,
        0.1,
        0.85,
    )


def _encoding_errors(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute(
        "SELECT count(*) FROM reject_errors WHERE error_type = 'INVALID ENCODING'"
    ).fetchone()
    return int(row[0]) if row else 0


def _describe(con: duckdb.DuckDBPyConnection, source: str) -> list[dict[str, str]]:
    return [
        {"name": r[0], "type": r[1]}
        for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
    ]


def _check_headers(cols: list[tuple[str, str]], report: dict[str, Any]) -> None:
    import re

    renamed = [n for n, _ in cols if re.fullmatch(r".+_\d+", n)]
    generated = [n for n, _ in cols if re.fullmatch(r"column\d+", n)]
    if generated:
        report["warnings"].append(
            f"{len(generated)} column(s) had no header and were named automatically: "
            + ", ".join(generated[:5])
        )
    if renamed:
        report["possible_duplicate_headers"] = renamed


def _collect_rejects(
    con: duckdb.DuckDBPyConnection, report: dict[str, Any], kept: int, max_ratio: float
) -> None:
    try:
        rows = con.execute(
            "SELECT line, error_type, error_message FROM reject_errors ORDER BY line LIMIT 20"
        ).fetchall()
        total_row = con.execute("SELECT count(DISTINCT line) FROM reject_errors").fetchone()
    except duckdb.Error:
        return
    rejected = int(total_row[0]) if total_row else 0
    report["rejected_rows"] = rejected
    if rejected:
        report["reject_samples"] = [
            {"line": int(r[0]), "type": str(r[1]), "message": str(r[2]).split("\n")[0]}
            for r in rows
        ]
        report["warnings"].append(f"{rejected} malformed row(s) were skipped.")
        total = rejected + kept
        if total and rejected / total > max_ratio:
            raise IngestError(
                f"{rejected} of {total} rows are malformed "
                f"({rejected / total:.0%}, limit {max_ratio:.0%}). "
                "Check the delimiter, quoting and header settings."
            )


def _cast_failures(
    con: duckdb.DuckDBPyConnection, source: str, out_src: str, applied: dict[str, str]
) -> dict[str, int]:
    # Both sides are Parquet with identical row sets, so the difference in non-null
    # counts is exactly the number of values TRY_CAST could not convert.
    """Count values that were non-null before a type correction and null after it."""
    result: dict[str, int] = {}
    for name in applied:
        q = quote_ident(name)
        before = con.execute(f"SELECT count({q}) FROM {source}").fetchone()
        after = con.execute(f"SELECT count({q}) FROM {out_src}").fetchone()
        result[name] = int(before[0] if before else 0) - int(after[0] if after else 0)
    return result


def _first_line(e: Exception | None) -> str:
    return str(e).strip().split("\n")[0] if e else "unknown error"
