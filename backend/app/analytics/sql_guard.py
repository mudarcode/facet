"""Static validation of untrusted SQL before it reaches DuckDB.

This is the *first* of several layers (see docs/decisions/0003-query-sandbox.md).
It parses the statement with sqlglot and rejects anything that is not a single
read-only query over the caller's own datasets. It deliberately does not try to
be the only line of defence: the DuckDB sandbox (``sandbox.py``) independently
blocks filesystem, network and extension access even if a query slipped through.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.core.errors import QueryRejected

MAX_SQL_LENGTH = 100_000

# Statement roots that are read-only queries.
_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Pivot,  # DuckDB's PIVOT statement is a query
)

# Node types that may never appear anywhere in the tree.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Copy,
    exp.Command,
    exp.Set,
    exp.Pragma,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
    exp.Attach,
    exp.Detach,
    exp.LoadData,
    exp.Describe,
    exp.Summarize,
    exp.Show,
)

# Table-valued functions with no I/O that are safe and useful in analytics.
_ALLOWED_TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})

# Scalar functions that expose environment/configuration, have side effects,
# or touch files. Matched case-insensitively against the function name.
_DENIED_FUNCTIONS = frozenset(
    {
        "getenv",
        "current_setting",
        "getvariable",
        "setseed",
        "set_variable",
        "query",
        "query_table",
        "read_text",
        "read_blob",
        "glob",
        "load",
        "install",
        "pragma",
        "checkpoint",
        "force_checkpoint",
        "make_timestamp_from_file",
        "file_exists",
    }
)
_DENIED_PREFIXES = (
    "read_",
    "duckdb_",
    "pragma_",
    "parquet_",
    "sniff_",
    "iceberg_",
    "delta_",
    "postgres_",
    "sqlite_",
    "mysql_",
    "http",
    "s3",
    "json_execute",
)


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    """SQL re-rendered from the validated AST; this is what gets executed."""
    datasets: frozenset[str] = field(default_factory=frozenset)
    """Lower-cased dataset sql_names referenced by the query."""


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    if isinstance(node, exp.Func):
        return node.sql_name().lower()
    return ""


def _is_denied_function(name: str) -> bool:
    return name in _DENIED_FUNCTIONS or name.startswith(_DENIED_PREFIXES)


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def validate_query(sql: str, allowed_datasets: set[str] | frozenset[str]) -> ValidatedQuery:
    """Validate ``sql`` against the caller's dataset allowlist.

    Raises ``QueryRejected`` with a user-readable message on any violation.
    """
    if not sql or not sql.strip():
        raise QueryRejected("Query is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        raise QueryRejected(f"Query is longer than {MAX_SQL_LENGTH} characters.")

    try:
        statements = [
            s
            for s in sqlglot.parse(sql, read="duckdb")
            if s is not None and not isinstance(s, exp.Semicolon)
        ]
    except (ParseError, TokenError) as e:
        raise QueryRejected(f"Could not parse SQL: {str(e).splitlines()[0]}") from e

    if len(statements) != 1:
        raise QueryRejected("Exactly one SQL statement is allowed per execution.")
    tree = statements[0]

    if not isinstance(tree, _ALLOWED_ROOTS):
        kind = type(tree).__name__.upper()
        raise QueryRejected(
            f"Only read-only SELECT queries are allowed (got {kind}).",
            details={"statement": kind},
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise QueryRejected(
                f"{type(node).__name__.upper()} is not allowed in queries.",
                details={"node": type(node).__name__},
            )

    allowed = {d.lower() for d in allowed_datasets}
    ctes = _cte_names(tree)
    referenced: set[str] = set()

    for table in tree.find_all(exp.Table):
        target = table.this
        if not isinstance(target, exp.Identifier):
            # Table function, e.g. read_csv('/etc/passwd') or query_table('x').
            fname = _function_name(target) if isinstance(target, exp.Expression) else ""
            if fname not in _ALLOWED_TABLE_FUNCTIONS:
                raise QueryRejected(
                    f"Table function {fname or type(target).__name__}() is not allowed.",
                    details={"function": fname},
                )
            continue
        if table.args.get("db") or table.args.get("catalog"):
            raise QueryRejected(
                f"Qualified table names are not allowed: {table.sql(dialect='duckdb')}"
            )
        name = table.name.lower()
        if name in ctes:
            continue
        if name not in allowed:
            raise QueryRejected(
                f"Unknown dataset '{table.name}'. Query one of your datasets by its SQL name.",
                details={"dataset": table.name, "available": sorted(allowed)},
            )
        referenced.add(name)

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name and _is_denied_function(name):
            raise QueryRejected(f"Function {name}() is not allowed.", details={"function": name})

    # Execute the SQL *as sqlglot understood it*, so there is no parser differential between
    # what we validated and what DuckDB runs. Comments and trailing semicolons are dropped.
    rendered = tree.sql(dialect="duckdb", comments=False)
    return ValidatedQuery(sql=rendered, datasets=frozenset(referenced))
