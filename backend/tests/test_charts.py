"""Chart specs: compile correctness (checked against Python), field validation, sources."""

import csv
import itertools
from collections import Counter, defaultdict
from datetime import date

import pytest

from app.analytics.charts import ChartSpec, compile_chart
from app.core.errors import InvalidInput
from tests.conftest import DEV, OTHER, SAMPLES, upload_ready

SCHEMA = [
    {"name": "order_id", "type": "BIGINT"},
    {"name": "region", "type": "VARCHAR"},
    {"name": "product", "type": "VARCHAR"},
    {"name": "qty", "type": "BIGINT"},
    {"name": "price", "type": "DOUBLE"},
    {"name": "order_date", "type": "DATE"},
]


def _rows() -> list[dict]:
    with open(SAMPLES / "sales.csv") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def sales(client):
    return upload_ready(client, (SAMPLES / "sales.csv").read_bytes(), "sales.csv")


def _data(client, ds, spec, headers=DEV, **kw):
    return client.post(
        "/api/v1/charts/data", json={"dataset_id": ds["id"], "spec": spec, **kw}, headers=headers
    )


# --- validation (pure) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ({"type": "line", "x": "region", "y": [{"agg": "count"}]}, "must be temporal or numeric"),
        ({"type": "bar", "x": "region", "y": [{"field": "region", "agg": "sum"}]}, "Cannot sum"),
        ({"type": "bar", "x": "nope", "y": [{"agg": "count"}]}, "Unknown field"),
        ({"type": "bar", "x": "region", "y": []}, "at least one measure"),
        ({"type": "bar", "y": [{"agg": "count"}]}, "Choose a x-axis"),
        ({"type": "histogram", "x": "region"}, "must be numeric"),
        ({"type": "scatter", "x": "qty", "y": [{"field": "region", "agg": "min"}]}, "numeric"),
        (
            {"type": "bar", "x": "region", "grain": "month", "y": [{"agg": "count"}]},
            "Time grain",
        ),
        (
            {
                "type": "bar",
                "x": "region",
                "series": "product",
                "y": [{"agg": "count"}, {"field": "qty", "agg": "sum"}],
            },
            "not both",
        ),
        (
            {"type": "bar", "x": "region", "y": [{"agg": "count"}, {"agg": "count"}]},
            "same name",
        ),
        ({"type": "stat", "y": []}, "at least one measure"),
    ],
)
def test_spec_validation(spec, fragment):
    with pytest.raises(InvalidInput) as e:
        compile_chart('"sales"', ChartSpec.model_validate(spec), SCHEMA)
    assert fragment in e.value.message


def test_identifiers_are_quoted():
    schema = [{"name": 'we"ird', "type": "VARCHAR"}]
    spec = ChartSpec.model_validate({"type": "bar", "x": 'we"ird', "y": [{"agg": "count"}]})
    sql, _ = compile_chart('"t"', spec, schema)
    assert '"we""ird"' in sql


# --- end to end against DuckDB ------------------------------------------------------------


def test_bar_sum_matches_python(client, sales):
    spec = {"type": "bar", "x": "region", "y": [{"field": "qty", "agg": "sum"}]}
    r = _data(client, sales, spec)
    assert r.status_code == 200, r.text
    body = r.json()
    expected: Counter[str] = Counter()
    for row in _rows():
        expected[row["region"]] += int(row["qty"])
    got = {x: y for x, y in body["rows"]}
    assert got == dict(expected)
    assert body["meta"]["measures"] == ["sum_qty"]
    assert [x for x, _ in body["rows"]] == sorted(expected)  # sort=x by default


def test_bar_sort_desc_and_limit(client, sales):
    spec = {
        "type": "bar",
        "x": "product",
        "y": [{"agg": "count"}],
        "options": {"sort": "y_desc", "limit": 2},
    }
    rows = _data(client, sales, spec).json()["rows"]
    counts = Counter(r["product"] for r in _rows())
    assert [tuple(r) for r in rows] == sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]


def test_line_monthly_grain(client, sales):
    spec = {
        "type": "line",
        "x": "order_date",
        "grain": "month",
        "y": [{"field": "price", "agg": "avg", "label": "Avg price"}],
    }
    body = _data(client, sales, spec).json()
    sums: dict[str, list[float]] = defaultdict(list)
    for row in _rows():
        d = date.fromisoformat(row["order_date"])
        sums[d.replace(day=1).isoformat()].append(float(row["price"]))
    got = {x[:10]: y for x, y in body["rows"]}
    assert got.keys() == sums.keys()
    for k, vals in sums.items():
        assert got[k] == pytest.approx(sum(vals) / len(vals))
    assert body["meta"]["measures"] == ["Avg price"]
    assert [r[0] for r in body["rows"]] == sorted(r[0] for r in body["rows"])


def test_series_split_and_fold(client):
    # 10 categories -> top 7 kept, the rest folded into "Other" (8 colours max).
    lines = ["cat,day,v"]
    for i in range(10):
        for d in range(1, 3):
            lines.append(f"c{i},2024-01-0{d},{(i + 1) * 10}")
    ds = upload_ready(client, "\n".join(lines).encode(), "cats.csv")
    spec = {
        "type": "area",
        "x": "day",
        "series": "cat",
        "y": [{"field": "v", "agg": "sum"}],
    }
    body = _data(client, ds, spec).json()
    series = {r[1] for r in body["rows"]}
    assert len(series) == 8
    assert "Other" in series
    assert {"c9", "c8", "c7", "c6", "c5", "c4", "c3"} <= series
    other = [r[2] for r in body["rows"] if r[1] == "Other"]
    assert other == [10 + 20 + 30, 10 + 20 + 30]
    assert body["meta"]["series"] == "series"


def test_null_series_is_its_own_group_not_other(client):
    # Two categories plus missing values: nothing to fold, so no "Other" may appear.
    csv = "cat,day,v\na,2024-01-01,1\nb,2024-01-01,2\n,2024-01-01,4\n,2024-01-02,8\n"
    ds = upload_ready(client, csv.encode(), "nulls.csv")
    for kind in ("bar", "scatter"):
        spec = {"type": kind, "x": "day" if kind == "bar" else "v", "series": "cat",
                "y": [{"field": "v", "agg": "sum"}]}  # fmt: skip
        rows = _data(client, ds, spec).json()["rows"]
        series = {r[1] if kind == "bar" else r[2] for r in rows}
        assert series == {"a", "b", "(null)"}, (kind, rows)


def test_histogram_bins_cover_all_rows(client, sales):
    body = _data(client, sales, {"type": "histogram", "x": "price", "options": {"bins": 10}}).json()
    rows = body["rows"]
    assert 1 <= len(rows) <= 11
    assert sum(r[2] for r in rows) == len(_rows())
    prices = [float(r["price"]) for r in _rows()]
    width = rows[0][1] - rows[0][0]
    # Round width, bins aligned on multiples of it, contiguous, covering min..max.
    assert any(width == pytest.approx(f * 10**e) for f in (1, 2, 2.5, 5) for e in range(-3, 6))
    assert rows[0][0] % width == pytest.approx(0) or rows[0][0] % width == pytest.approx(width)
    assert all(a[1] == pytest.approx(b[0]) for a, b in itertools.pairwise(rows))
    assert rows[0][0] <= min(prices) and max(prices) < rows[-1][1]


def test_scatter_is_sampled_and_capped(client, sales):
    spec = {
        "type": "scatter",
        "x": "qty",
        "y": [{"field": "price", "agg": "min"}],
        "series": "product",
    }
    body = _data(client, sales, spec).json()
    assert len(body["rows"]) == len(_rows())  # 5000 rows == cap, nothing dropped
    assert len({r[2] for r in body["rows"]}) <= 4  # 3 largest + Other


def test_stat_and_filters(client, sales):
    spec = {
        "type": "stat",
        "y": [{"agg": "count"}, {"field": "price", "agg": "max"}],
        "filters": [{"column": "region", "op": "=", "value": "North"}],
    }
    north = [r for r in _rows() if r["region"] == "North"]
    body = _data(client, sales, spec).json()
    assert body["rows"][0][0] == len(north)
    assert body["rows"][0][1] == pytest.approx(max(float(r["price"]) for r in north))
    # Extra (dashboard) filters AND with the chart's own filters.
    extra = [{"column": "product", "op": "=", "value": "Gizmo"}]
    body = _data(client, sales, spec, filters=extra).json()
    assert body["rows"][0][0] == sum(1 for r in north if r["product"] == "Gizmo")


def test_dashboard_filter_on_missing_column_is_ignored(client, sales):
    spec = {"type": "stat", "y": [{"agg": "count"}]}
    extra = [{"column": "not_here", "op": "=", "value": 1}]
    assert _data(client, sales, spec, filters=extra).json()["rows"][0][0] == len(_rows())


def test_filter_values_are_escaped(client, sales):
    spec = {
        "type": "stat",
        "y": [{"agg": "count"}],
        "filters": [{"column": "region", "op": "=", "value": "x' OR '1'='1"}],
    }
    r = _data(client, sales, spec)
    assert r.status_code == 200
    assert r.json()["rows"][0][0] == 0


def test_chart_from_saved_query_with_comment(client, sales):
    sq = client.post(
        "/api/v1/queries",
        json={
            "name": "big orders",
            "sql": "SELECT region, qty FROM sales WHERE qty >= 5; -- big ones",
        },
        headers=DEV,
    )
    assert sq.status_code == 201, sq.text
    cols = client.post(
        "/api/v1/charts/source-columns", json={"saved_query_id": sq.json()["id"]}, headers=DEV
    )
    assert [c["name"] for c in cols.json()["columns"]] == ["region", "qty"]
    r = client.post(
        "/api/v1/charts/data",
        json={
            "saved_query_id": sq.json()["id"],
            "spec": {"type": "stat", "y": [{"agg": "count"}]},
        },
        headers=DEV,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] == sum(1 for row in _rows() if int(row["qty"]) >= 5)


def test_chart_crud_and_isolation(client, sales):
    spec = {"type": "bar", "x": "region", "y": [{"agg": "count"}]}
    r = client.post(
        "/api/v1/charts",
        json={"name": "By region", "dataset_id": sales["id"], "spec": spec},
        headers=DEV,
    )
    assert r.status_code == 201, r.text
    chart = r.json()
    listed = client.get("/api/v1/charts", headers=DEV).json()
    assert listed[0]["source_name"] == sales["name"]
    assert client.get(f"/api/v1/charts/{chart['id']}", headers=OTHER).status_code == 404
    assert client.post(f"/api/v1/charts/{chart['id']}/data", headers=OTHER).status_code == 404
    assert _data(client, sales, spec, headers=OTHER).status_code == 404

    data = client.post(f"/api/v1/charts/{chart['id']}/data", headers=DEV).json()
    assert len(data["rows"]) == len({r["region"] for r in _rows()})

    bad = {"spec": {"type": "line", "x": "region", "y": [{"agg": "count"}]}}
    assert client.patch(f"/api/v1/charts/{chart['id']}", json=bad, headers=DEV).status_code == 422
    ok = client.patch(f"/api/v1/charts/{chart['id']}", json={"name": "Regions"}, headers=DEV)
    assert ok.json()["name"] == "Regions"
    assert client.delete(f"/api/v1/charts/{chart['id']}", headers=DEV).status_code == 204
    assert client.get(f"/api/v1/charts/{chart['id']}", headers=DEV).status_code == 404


def test_saving_invalid_spec_is_rejected(client, sales):
    r = client.post(
        "/api/v1/charts",
        json={
            "name": "bad",
            "dataset_id": sales["id"],
            "spec": {"type": "bar", "x": "nope", "y": [{"agg": "count"}]},
        },
        headers=DEV,
    )
    assert r.status_code == 422
    assert "Unknown field" in r.json()["error"]["message"]


def test_source_must_be_exactly_one(client, sales):
    r = client.post("/api/v1/charts/data", json={"spec": {"type": "stat", "y": []}}, headers=DEV)
    assert r.status_code == 422
