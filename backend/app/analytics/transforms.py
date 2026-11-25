"""Visual transformation plans compiled to DuckDB SQL.

A plan is an ordered list of typed steps. Each step becomes one CTE that reads
from the previous one, so the generated SQL is readable, deterministic and
inspectable in the UI. The compiler tracks the column set through the plan and
rejects references to columns that do not exist at that point, so users get a
precise error ("step 3 (filter): unknown column 'amout'") instead of a DuckDB
binder error.

All identifiers are quoted and all literal values are escaped here; derived
column expressions are parsed with sqlglot and restricted to column references,
literals, operators and non-denied scalar functions. The final SQL is *also*
passed through ``sql_guard.validate_query`` before execution.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import sqlglot
from pydantic import BaseModel, Field, field_validator
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.analytics.engine import quote_ident, quote_literal
from app.analytics.sql_guard import function_name, is_denied_function
from app.core.errors import InvalidInput

CAST_TYPES = ("BOOLEAN", "BIGINT", "INTEGER", "DOUBLE", "DECIMAL(18,4)", "VARCHAR", "DATE",
              "TIMESTAMP")  # fmt: skip
FilterOp = Literal[
    "=", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "starts_with", "ends_with",
    "is_null", "is_not_null", "in", "not_in",
]  # fmt: skip
AggFunc = Literal["count", "count_distinct", "sum", "avg", "min", "max", "median", "stddev"]


class SelectStep(BaseModel):
    op: Literal["select"]
    columns: list[str] = Field(min_length=1)


class RenameStep(BaseModel):
    op: Literal["rename"]
    mapping: dict[str, str] = Field(min_length=1)

    @field_validator("mapping")
    @classmethod
    def _non_empty_names(cls, v: dict[str, str]) -> dict[str, str]:
        if any(not new.strip() for new in v.values()):
            raise ValueError("new column names must not be empty")
        return v


class Condition(BaseModel):
    column: str
    op: FilterOp
    value: Any = None


class FilterStep(BaseModel):
    op: Literal["filter"]
    conditions: list[Condition] = Field(min_length=1)
    combine: Literal["and", "or"] = "and"


class DropNullsStep(BaseModel):
    op: Literal["drop_nulls"]
    columns: list[str] = Field(default_factory=list, description="Empty = any column")


class SortKey(BaseModel):
    column: str
    desc: bool = False


class SortStep(BaseModel):
    op: Literal["sort"]
    keys: list[SortKey] = Field(min_length=1)


class CastStep(BaseModel):
    op: Literal["cast"]
    column: str
    to: str

    @field_validator("to")
    @classmethod
    def _type(cls, v: str) -> str:
        v = v.upper().replace(" ", "")
        if v not in CAST_TYPES:
            raise ValueError(f"type must be one of {', '.join(CAST_TYPES)}")
        return v


class DeriveStep(BaseModel):
    op: Literal["derive"]
    name: str = Field(min_length=1, max_length=120)
    expression: str = Field(min_length=1, max_length=2000)


class Aggregation(BaseModel):
    column: str | None = None  # None only for count
    func: AggFunc
    alias: str | None = None


class GroupStep(BaseModel):
    op: Literal["group"]
    by: list[str] = Field(default_factory=list)
    aggregations: list[Aggregation] = Field(min_length=1)


class DistinctStep(BaseModel):
    op: Literal["distinct"]
    columns: list[str] = Field(default_factory=list, description="Empty = all columns")


class LimitStep(BaseModel):
    op: Literal["limit"]
    count: int = Field(ge=1, le=10_000_000)


Step = Annotated[
    SelectStep
    | RenameStep
    | FilterStep
    | DropNullsStep
    | SortStep
    | CastStep
    | DeriveStep
    | GroupStep
    | DistinctStep
    | LimitStep,
    Field(discriminator="op"),
]


class Plan(BaseModel):
    steps: list[Step] = Field(default_factory=list, max_length=50)


def _err(i: int, step: BaseModel, msg: str) -> InvalidInput:
    op = getattr(step, "op", "?")
    return InvalidInput(f"Step {i + 1} ({op}): {msg}", details={"step": i, "op": op})


def _need(cols: list[str], names: list[str], i: int, step: BaseModel) -> None:
    missing = [n for n in names if n not in cols]
    if missing:
        raise _err(i, step, f"unknown column {', '.join(repr(m) for m in missing)}")


def _literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return quote_literal(str(v))


def _condition(c: Condition, i: int, step: BaseModel) -> str:
    q = quote_ident(c.column)
    if c.op == "is_null":
        return f"{q} IS NULL"
    if c.op == "is_not_null":
        return f"{q} IS NOT NULL"
    if c.op in ("in", "not_in"):
        values = c.value if isinstance(c.value, list) else [c.value]
        if not values:
            raise _err(i, step, f"'{c.op}' needs at least one value")
        neg = "NOT " if c.op == "not_in" else ""
        return f"{q} {neg}IN ({', '.join(_literal(v) for v in values)})"
    if c.value is None:
        raise _err(i, step, f"filter on {c.column!r} with '{c.op}' needs a value")
    if c.op in ("contains", "not_contains", "starts_with", "ends_with"):
        s = quote_literal(str(c.value))
        fn = {
            "contains": f"contains({q}::VARCHAR, {s})",
            "not_contains": f"NOT contains({q}::VARCHAR, {s})",
            "starts_with": f"starts_with({q}::VARCHAR, {s})",
            "ends_with": f"ends_with({q}::VARCHAR, {s})",
        }
        return fn[c.op]
    return f"{q} {c.op} {_literal(c.value)}"


def _check_expression(expr_sql: str, cols: list[str], i: int, step: BaseModel) -> str:
    try:
        tree = sqlglot.parse_one(expr_sql, read="duckdb", into=exp.Condition)
    except (ParseError, TokenError) as e:
        raise _err(i, step, f"invalid expression: {str(e).splitlines()[0]}") from e
    for node in tree.walk():
        if isinstance(node, (exp.Select, exp.Subquery, exp.Table, exp.Query)):
            raise _err(i, step, "expressions cannot contain subqueries")
        if isinstance(node, exp.Func):
            name = function_name(node)
            if is_denied_function(name):
                raise _err(i, step, f"function {name}() is not allowed")
        if isinstance(node, exp.Star):
            raise _err(i, step, "'*' is not allowed in a derived column")
    lower = {c.lower(): c for c in cols}
    for col in tree.find_all(exp.Column):
        if col.table:
            raise _err(i, step, "qualified column references are not allowed")
        if col.name.lower() not in lower:
            raise _err(i, step, f"unknown column {col.name!r}")
    return tree.sql(dialect="duckdb")


AGG_SQL = {
    "count": "count({c})",
    "count_distinct": "count(DISTINCT {c})",
    "sum": "sum({c})",
    "avg": "avg({c})",
    "min": "min({c})",
    "max": "max({c})",
    "median": "median({c})",
    "stddev": "stddev_samp({c})",
}


def compile_plan(source: str, columns: list[str], plan: Plan) -> tuple[str, list[str]]:
    """Compile ``plan`` over dataset ``source`` (a SQL name). Returns (sql, output columns)."""
    cols = list(columns)
    ctes = [f"s0 AS (SELECT * FROM {quote_ident(source)})"]
    for i, step in enumerate(plan.steps):
        prev = f"s{i}"
        sql: str
        if isinstance(step, SelectStep):
            _need(cols, step.columns, i, step)
            sql = f"SELECT {', '.join(quote_ident(c) for c in step.columns)} FROM {prev}"
            cols = list(step.columns)
        elif isinstance(step, RenameStep):
            _need(cols, list(step.mapping), i, step)
            new_cols = [step.mapping.get(c, c) for c in cols]
            if len(set(new_cols)) != len(new_cols):
                raise _err(i, step, "renaming would create duplicate column names")
            sel = ", ".join(
                f"{quote_ident(c)} AS {quote_ident(step.mapping[c])}"
                if c in step.mapping
                else quote_ident(c)
                for c in cols
            )
            sql = f"SELECT {sel} FROM {prev}"
            cols = new_cols
        elif isinstance(step, FilterStep):
            _need(cols, [c.column for c in step.conditions], i, step)
            joiner = f" {step.combine.upper()} "
            where = joiner.join(f"({_condition(c, i, step)})" for c in step.conditions)
            sql = f"SELECT * FROM {prev} WHERE {where}"
        elif isinstance(step, DropNullsStep):
            target = step.columns or cols
            _need(cols, target, i, step)
            sql = f"SELECT * FROM {prev} WHERE " + " AND ".join(
                f"{quote_ident(c)} IS NOT NULL" for c in target
            )
        elif isinstance(step, SortStep):
            _need(cols, [k.column for k in step.keys], i, step)
            order = ", ".join(
                f"{quote_ident(k.column)} {'DESC' if k.desc else 'ASC'} NULLS LAST"
                for k in step.keys
            )
            sql = f"SELECT * FROM {prev} ORDER BY {order}"
        elif isinstance(step, CastStep):
            _need(cols, [step.column], i, step)
            sel = ", ".join(
                f"TRY_CAST({quote_ident(c)} AS {step.to}) AS {quote_ident(c)}"
                if c == step.column
                else quote_ident(c)
                for c in cols
            )
            sql = f"SELECT {sel} FROM {prev}"
        elif isinstance(step, DeriveStep):
            expr = _check_expression(step.expression, cols, i, step)
            if step.name in cols:
                sel = ", ".join(
                    f"({expr}) AS {quote_ident(c)}" if c == step.name else quote_ident(c)
                    for c in cols
                )
                sql = f"SELECT {sel} FROM {prev}"
            else:
                sql = f"SELECT *, ({expr}) AS {quote_ident(step.name)} FROM {prev}"
                cols = [*cols, step.name]
        elif isinstance(step, GroupStep):
            _need(cols, step.by, i, step)
            out = list(step.by)
            parts = [quote_ident(c) for c in step.by]
            for a in step.aggregations:
                if a.column is None and a.func != "count":
                    raise _err(i, step, f"{a.func} needs a column")
                if a.column is not None:
                    _need(cols, [a.column], i, step)
                arg = quote_ident(a.column) if a.column else "*"
                alias = a.alias or (f"{a.func}_{a.column}" if a.column else "count")
                if alias in out:
                    raise _err(i, step, f"duplicate output column {alias!r}")
                parts.append(f"{AGG_SQL[a.func].format(c=arg)} AS {quote_ident(alias)}")
                out.append(alias)
            group = f" GROUP BY {', '.join(quote_ident(c) for c in step.by)}" if step.by else ""
            # Deterministic output order for grouped results.
            order = f" ORDER BY {', '.join(quote_ident(c) for c in step.by)}" if step.by else ""
            sql = f"SELECT {', '.join(parts)} FROM {prev}{group}{order}"
            cols = out
        elif isinstance(step, DistinctStep):
            if step.columns:
                _need(cols, step.columns, i, step)
                keys = ", ".join(quote_ident(c) for c in step.columns)
                # One row per key; ties broken by every column so the result is deterministic.
                tiebreak = ", ".join(f"{quote_ident(c)} NULLS LAST" for c in cols)
                sql = (
                    f"SELECT * FROM {prev} QUALIFY row_number() OVER "
                    f"(PARTITION BY {keys} ORDER BY {tiebreak}) = 1"
                )
            else:
                sql = f"SELECT DISTINCT * FROM {prev}"
        elif isinstance(step, LimitStep):
            sql = f"SELECT * FROM {prev} LIMIT {int(step.count)}"
        else:  # pragma: no cover - exhaustive union
            raise _err(i, step, "unsupported step")
        ctes.append(f"s{i + 1} AS ({sql})")
    final = f"s{len(plan.steps)}"
    return "WITH " + ",\n     ".join(ctes) + f"\nSELECT * FROM {final}", cols
