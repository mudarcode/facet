"""Chart specifications compiled to aggregate DuckDB SQL.

A chart never ships raw rows to the browser unless the chart type needs them
(scatter, capped). Bars/lines/areas aggregate in DuckDB; histograms bin in DuckDB.
Field roles are validated against the source schema so that, e.g., a line chart
over a text column or a sum over a VARCHAR is rejected with a clear message.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.analytics.engine import quote_ident, quote_literal
from app.analytics.profile import kind_of
from app.analytics.transforms import Condition, _condition
from app.core.errors import InvalidInput

ChartType = Literal["bar", "line", "area", "scatter", "histogram", "stat"]
Agg = Literal["count", "count_distinct", "sum", "avg", "min", "max", "median"]
Grain = Literal["none", "day", "week", "month", "quarter", "year"]

MAX_POINTS = 5000
MAX_SERIES = 8  # categorical palette size; extra series fold into "Other"
MAX_SCATTER_SERIES = 3  # all-pairs CVD-safe limit for scatter

AGG_SQL = {
    "count": "count({c})",
    "count_distinct": "count(DISTINCT {c})",
    "sum": "sum({c})",
    "avg": "avg({c})",
    "min": "min({c})",
    "max": "max({c})",
    "median": "median({c})",
}


class Measure(BaseModel):
    field: str | None = None  # None => count(*)
    agg: Agg = "count"
    label: str | None = None

    @model_validator(mode="after")
    def _field_required(self) -> Measure:
        if self.field is None and self.agg != "count":
            raise ValueError(f"{self.agg} needs a field")
        return self


class ChartOptions(BaseModel):
    title: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    stacked: bool = False
    bins: int = Field(default=20, ge=2, le=100)
    sort: Literal["x", "y_desc", "y_asc"] = "x"
    limit: int = Field(default=50, ge=1, le=MAX_POINTS)
    show_values: bool = False
    orientation: Literal["vertical", "horizontal"] = "vertical"


class ChartSpec(BaseModel):
    type: ChartType
    x: str | None = None
    y: list[Measure] = Field(default_factory=list, max_length=4)
    series: str | None = None
    grain: Grain = "none"
    filters: list[Condition] = Field(default_factory=list, max_length=20)
    options: ChartOptions = Field(default_factory=ChartOptions)


def _kinds(schema: list[dict[str, str]]) -> dict[str, str]:
    return {c["name"]: kind_of(c["type"]) for c in schema}


def validate_spec(spec: ChartSpec, schema: list[dict[str, str]]) -> None:
    kinds = _kinds(schema)

    def need(field: str | None, role: str, allowed: tuple[str, ...] | None = None) -> None:
        if field is None:
            raise InvalidInput(
                f"Choose a {role} field for a {spec.type} chart.", details={"role": role}
            )
        if field not in kinds:
            raise InvalidInput(f"Unknown field '{field}'.", details={"role": role, "field": field})
        if allowed and kinds[field] not in allowed:
            raise InvalidInput(
                f"'{field}' is {kinds[field]}; the {role} of a {spec.type} chart must be "
                f"{' or '.join(allowed)}.",
                details={"role": role, "field": field, "kind": kinds[field]},
            )

    for f in spec.filters:
        if f.column not in kinds:
            raise InvalidInput(f"Filter on unknown field '{f.column}'.")
    for m in spec.y:
        if m.field is not None:
            need(m.field, "measure")
            if m.agg in ("sum", "avg", "median") and kinds[m.field] != "numeric":
                raise InvalidInput(
                    f"Cannot {m.agg} '{m.field}' ({kinds[m.field]}). Use count or a numeric field.",
                    details={"role": "measure", "field": m.field},
                )
    keys = [measure_key(m) for m in spec.y]
    if len(set(keys)) != len(keys):
        raise InvalidInput("Two measures would have the same name; give one a label.")
    if spec.series is not None:
        need(spec.series, "series", ("text", "boolean", "temporal", "numeric"))

    t = spec.type
    if t in ("bar", "line", "area"):
        need(spec.x, "x-axis")
        if t in ("line", "area"):
            need(spec.x, "x-axis", ("temporal", "numeric"))
        if not spec.y:
            raise InvalidInput(f"Add at least one measure to the {t} chart.")
        if spec.series and len(spec.y) > 1:
            raise InvalidInput("Use either a series field or several measures, not both.")
        if spec.grain != "none" and kinds.get(spec.x or "") != "temporal":
            raise InvalidInput("Time grain only applies to date/timestamp x-axes.")
    elif t == "scatter":
        need(spec.x, "x-axis", ("numeric", "temporal"))
        if len(spec.y) != 1 or spec.y[0].field is None:
            raise InvalidInput("A scatter plot needs exactly one numeric y field.")
        need(spec.y[0].field, "y-axis", ("numeric",))
    elif t == "histogram":
        need(spec.x, "value", ("numeric",))
    elif t == "stat" and not spec.y:
        raise InvalidInput("A summary card needs at least one measure.")


NULL_SERIES = "(null)"


def _series_expr(field: str) -> str:
    """Series key as text. NULL gets its own visible label: it is a real group, and
    ``NULL IN (...)`` would otherwise silently fold it into "Other"."""
    return f"coalesce({quote_ident(field)}::VARCHAR, {quote_literal(NULL_SERIES)})"


def _where(spec: ChartSpec, extra: list[Condition]) -> str:
    conds = [*spec.filters, *extra]
    if not conds:
        return ""
    return " WHERE " + " AND ".join(f"({_condition(c, 0, spec)})" for c in conds)


def _x_expr(spec: ChartSpec) -> str:
    q = quote_ident(spec.x or "")
    if spec.grain != "none":
        return f"date_trunc('{spec.grain}', {q})"
    return q


def _measure_sql(m: Measure) -> str:
    arg = quote_ident(m.field) if m.field else "*"
    return AGG_SQL[m.agg].format(c=arg)


def measure_key(m: Measure, _i: int = 0) -> str:
    base = m.label or (f"{m.agg}_{m.field}" if m.field else "count")
    return base


def compile_chart(
    source_sql: str,
    spec: ChartSpec,
    schema: list[dict[str, str]],
    extra_filters: list[Condition] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (sql, meta). ``source_sql`` is a relation: a quoted dataset name or (subquery)."""
    validate_spec(spec, schema)
    extra = [f for f in (extra_filters or []) if f.column in _kinds(schema)]
    where = _where(spec, extra)
    src = f"{source_sql} AS src"
    o = spec.options
    meta: dict[str, Any] = {"type": spec.type, "x": "x", "measures": [], "series": None}

    if spec.type == "stat":
        cols = []
        for i, m in enumerate(spec.y):
            key = measure_key(m, i)
            cols.append(f"{_measure_sql(m)} AS {quote_ident(key)}")
            meta["measures"].append(key)
        meta["x"] = None
        return f"SELECT {', '.join(cols)} FROM {src}{where}", meta

    if spec.type == "histogram":
        q = quote_ident(spec.x or "")
        bins = o.bins
        # Round bin widths (1, 2, 2.5 or 5 x 10^n) starting on a multiple of the width,
        # so edges read 0, 20, 40 instead of 26.1, 66.3. Yields at most bins + 1 bins.
        sql = (
            f"WITH _c_r AS (SELECT min({q})::DOUBLE AS lo, max({q})::DOUBLE AS hi "
            f"FROM {src}{where}), "
            f"_c_m AS (SELECT lo, hi, CASE WHEN hi > lo THEN (hi - lo) / {bins} END AS raw, "
            f"CASE WHEN hi > lo THEN pow(10, floor(log10((hi - lo) / {bins}))) END AS mag "
            f"FROM _c_r), "
            f"_c_s AS (SELECT lo, hi, coalesce(CASE WHEN raw / mag <= 1 THEN 1 "
            f"WHEN raw / mag <= 2 THEN 2 WHEN raw / mag <= 2.5 THEN 2.5 "
            f"WHEN raw / mag <= 5 THEN 5 ELSE 10 END * mag, 1) AS step FROM _c_m), "
            f"_c_b AS (SELECT step, floor(lo / step) * step AS start, "
            f"floor((hi - floor(lo / step) * step) / step)::BIGINT + 1 AS n FROM _c_s), "
            f"_c_v AS (SELECT {q}::DOUBLE AS v FROM {src}{where}) "
            f"SELECT start + step * k AS bin_start, start + step * (k + 1) AS bin_end, "
            f"count(v.v) AS count "
            f"FROM _c_b CROSS JOIN range({bins + 1}) r(k) "
            f"LEFT JOIN _c_v AS v ON v.v IS NOT NULL "
            f"AND least(floor((v.v - start) / step)::BIGINT, n - 1) = k "
            f"WHERE k < n OR (n IS NULL AND k = 0) "
            f"GROUP BY k, start, step ORDER BY k"
        )
        meta.update({"x": "bin_start", "measures": ["count"]})
        return sql, meta

    if spec.type == "scatter":
        m = spec.y[0]
        cols = [f"{quote_ident(spec.x or '')} AS x", f"{quote_ident(m.field or '')} AS y"]
        series_note = None
        if spec.series:
            cols.append(f"{_series_expr(spec.series)} AS series")
            meta["series"] = "series"
            series_note = MAX_SCATTER_SERIES
        not_null = (
            f"{quote_ident(spec.x or '')} IS NOT NULL AND {quote_ident(m.field or '')} IS NOT NULL"
        )
        w = f"{where} AND {not_null}" if where else f" WHERE {not_null}"
        base = f"SELECT {', '.join(cols)} FROM {src}{w}"
        if spec.series:
            # Keep the 3 largest series (CVD-safe for overlapping marks); fold the rest.
            base = (
                f"WITH _c_p AS ({base}), _c_top AS (SELECT series FROM _c_p GROUP BY series "
                f"ORDER BY count(*) DESC, series LIMIT {series_note}) "
                f"SELECT x, y, CASE WHEN series IN (SELECT series FROM _c_top) THEN series "
                f"ELSE 'Other' END AS series FROM _c_p"
            )
        # Deterministic sample when there are more points than we render.
        sql = f"SELECT * FROM ({base}) USING SAMPLE reservoir({MAX_POINTS} ROWS) REPEATABLE (7)"
        meta["measures"] = ["y"]
        return sql, meta

    # bar / line / area
    x = _x_expr(spec)
    order_x = spec.type in ("line", "area") or o.sort == "x"
    if spec.series:
        m = spec.y[0]
        key = measure_key(m, 0)
        sql = (
            f"WITH _c_g AS (SELECT {x} AS x, {_series_expr(spec.series)} AS series, "
            f"{_measure_sql(m)} AS y "
            f"FROM {src}{where} GROUP BY 1, 2), "
            f"_c_top AS (SELECT series FROM _c_g GROUP BY series "
            f"ORDER BY sum(y) DESC NULLS LAST, series "
            f"LIMIT {MAX_SERIES - 1}), "
            f"_c_folded AS (SELECT x, CASE WHEN series IN (SELECT series FROM _c_top) "
            f"THEN series ELSE 'Other' END AS series, y FROM _c_g) "
            f"SELECT x, series, sum(y) AS y FROM _c_folded GROUP BY 1, 2 ORDER BY x, series "
            f"LIMIT {MAX_POINTS}"
        )
        meta.update({"series": "series", "measures": ["y"], "measure_labels": [key]})
        return sql, meta

    cols = [f"{x} AS x"]
    for i, m in enumerate(spec.y):
        key = measure_key(m, i)
        cols.append(f"{_measure_sql(m)} AS {quote_ident(key)}")
        meta["measures"].append(key)
    first = quote_ident(meta["measures"][0])
    if order_x:
        order = "ORDER BY x NULLS LAST"
    elif o.sort == "y_desc":
        order = f"ORDER BY {first} DESC NULLS LAST, x"
    else:
        order = f"ORDER BY {first} ASC NULLS LAST, x"
    limit = MAX_POINTS if spec.type in ("line", "area") else o.limit
    sql = f"SELECT {', '.join(cols)} FROM {src}{where} GROUP BY 1 {order} LIMIT {limit}"
    return sql, meta
