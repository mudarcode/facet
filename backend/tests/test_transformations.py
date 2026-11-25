"""Transformation plans: compiler correctness against Python, validation and materialisation."""

import csv
import io

import pytest

from app.analytics.transforms import Plan, compile_plan
from app.core.errors import InvalidInput
from tests.conftest import DEV, OTHER, run_jobs, sql, upload_ready

ROWS = [
    ("1", "North", "Widget", "3", "10.5", "2024-01-03"),
    ("2", "South", "Gadget", "", "4.0", "2024-01-04"),
    ("3", "North", "Gadget", "5", "", "2024-02-01"),
    ("4", "East", "Widget", "1", "99.9", "2024-02-11"),
    ("5", "North", "Widget", "3", "10.5", "2024-01-03"),
    ("6", "South", "Gizmo", "2", "7.25", "2024-03-15"),
]


def _upload(client, headers=DEV):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "region", "product", "qty", "price", "day"])
    w.writerows(ROWS)
    return upload_ready(client, buf.getvalue().encode(), "orders.csv", headers=headers)


def _preview(client, ds, steps, headers=DEV):
    return client.post(
        "/api/v1/transformations/preview",
        json={"dataset_id": ds["id"], "steps": steps, "limit": 1000},
        headers=headers,
    )


def test_each_step_matches_python(client):
    ds = _upload(client)
    run = lambda steps: _preview(client, ds, steps).json()  # noqa: E731

    r = run([{"op": "select", "columns": ["id", "region"]}])
    assert [c["name"] for c in r["columns"]] == ["id", "region"]

    r = run([{"op": "rename", "mapping": {"qty": "quantity"}}])
    assert "quantity" in [c["name"] for c in r["columns"]]

    r = run(
        [
            {
                "op": "filter",
                "conditions": [
                    {"column": "region", "op": "=", "value": "North"},
                    {"column": "price", "op": ">", "value": 10},
                ],
            }
        ]
    )
    assert sorted(row[0] for row in r["rows"]) == [1, 5]

    r = run(
        [
            {
                "op": "filter",
                "combine": "or",
                "conditions": [
                    {"column": "product", "op": "starts_with", "value": "Gi"},
                    {"column": "region", "op": "in", "value": ["East"]},
                ],
            }
        ]
    )
    assert sorted(row[0] for row in r["rows"]) == [4, 6]

    r = run([{"op": "drop_nulls", "columns": ["qty", "price"]}])
    assert sorted(row[0] for row in r["rows"]) == [1, 4, 5, 6]

    r = run([{"op": "sort", "keys": [{"column": "price", "desc": True}, {"column": "id"}]}])
    assert [row[0] for row in r["rows"]] == [4, 1, 5, 6, 2, 3]  # NULLS LAST

    r = run([{"op": "cast", "column": "qty", "to": "varchar"}])
    assert next(c for c in r["columns"] if c["name"] == "qty")["type"] == "VARCHAR"

    r = run(
        [
            {"op": "derive", "name": "revenue", "expression": "qty * price"},
            {"op": "select", "columns": ["id", "revenue"]},
            {"op": "sort", "keys": [{"column": "id"}]},
        ]
    )
    expected = [float(q) * float(p) if q and p else None for _, _, _, q, p, _ in ROWS]
    assert [row[1] for row in r["rows"]] == expected

    r = run(
        [
            {
                "op": "group",
                "by": ["region"],
                "aggregations": [
                    {"func": "count"},
                    {"column": "qty", "func": "sum", "alias": "units"},
                    {"column": "price", "func": "avg"},
                ],
            }
        ]
    )
    got = {row[0]: row[1:] for row in r["rows"]}
    assert got["North"][0] == 3 and got["North"][1] == 11
    assert got["South"][1] == 2 and got["South"][2] == pytest.approx((4.0 + 7.25) / 2)
    assert [row[0] for row in r["rows"]] == ["East", "North", "South"]  # deterministic order

    r = run(
        [
            {"op": "select", "columns": ["region", "product", "qty", "price", "day"]},
            {"op": "distinct"},
        ]
    )
    assert r["total_rows"] == 5  # rows 1 and 5 are duplicates once id is dropped

    r = run(
        [{"op": "distinct", "columns": ["region"]}, {"op": "sort", "keys": [{"column": "region"}]}]
    )
    assert [row[1] for row in r["rows"]] == ["East", "North", "South"]
    assert [row[0] for row in r["rows"]] == [4, 1, 2]  # deterministic tie-break

    r = run([{"op": "limit", "count": 2}])
    assert r["total_rows"] == 2


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([{"op": "select", "columns": ["nope"]}], "unknown column 'nope'"),
        (
            [
                {"op": "select", "columns": ["id"]},
                {"op": "filter", "conditions": [{"column": "region", "op": "=", "value": "x"}]},
            ],
            "Step 2",
        ),
        ([{"op": "derive", "name": "x", "expression": "(SELECT 1)"}], "subqueries"),
        ([{"op": "derive", "name": "x", "expression": "getenv('HOME')"}], "not allowed"),
        ([{"op": "derive", "name": "x", "expression": "nope + 1"}], "unknown column"),
        ([{"op": "rename", "mapping": {"id": "region"}}], "duplicate"),
        ([{"op": "group", "by": [], "aggregations": [{"func": "sum"}]}], "needs a column"),
        ([{"op": "filter", "conditions": [{"column": "id", "op": ">"}]}], "needs a value"),
    ],
)
def test_validation_errors(client, steps, message):
    ds = _upload(client)
    r = _preview(client, ds, steps)
    assert r.status_code == 422, r.text
    assert message in r.json()["error"]["message"]


def test_injection_through_values_is_escaped():
    sql_text, _ = compile_plan(
        "t",
        ["a"],
        Plan.model_validate(
            {
                "steps": [
                    {
                        "op": "filter",
                        "conditions": [{"column": "a", "op": "=", "value": "x'); DROP VIEW t; --"}],
                    },
                    {"op": "rename", "mapping": {"a": 'b"; DROP VIEW t; --'}},
                ]
            }
        ),
    )
    assert "'x''); DROP VIEW t; --'" in sql_text
    assert '"b""; DROP VIEW t; --"' in sql_text
    with pytest.raises(InvalidInput):
        compile_plan(
            "t", ["a"], Plan.model_validate({"steps": [{"op": "select", "columns": ["b"]}]})
        )


def test_save_reapply_and_materialize(client):
    ds = _upload(client)
    steps = [
        {"op": "drop_nulls", "columns": ["qty"]},
        {"op": "derive", "name": "revenue", "expression": "qty * coalesce(price, 0)"},
        {
            "op": "group",
            "by": ["region"],
            "aggregations": [{"column": "revenue", "func": "sum", "alias": "revenue"}],
        },
    ]
    r = client.post(
        "/api/v1/transformations",
        json={"dataset_id": ds["id"], "name": "Revenue by region", "steps": steps},
        headers=DEV,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["sql"].startswith("WITH s0 AS")
    assert (
        client.get(f"/api/v1/transformations?dataset_id={ds['id']}", headers=DEV).json()[0]["id"]
        == t["id"]
    )
    assert client.get(f"/api/v1/transformations/{t['id']}", headers=OTHER).status_code == 404

    m = client.post(
        f"/api/v1/transformations/{t['id']}/materialize",
        json={"name": "Regional revenue"},
        headers=DEV,
    )
    assert m.status_code == 202
    run_jobs()
    out = client.get(f"/api/v1/datasets/{m.json()['dataset_id']}", headers=DEV).json()
    assert out["status"] == "ready", out
    assert out["row_count"] == 3
    rows = sql(client, f"SELECT * FROM {out['sql_name']} ORDER BY region").json()["rows"]
    assert rows == [["East", 99.9], ["North", 3 * 10.5 + 0 + 3 * 10.5], ["South", 2 * 7.25]]

    # Reapply after editing the plan: same output dataset, new version.
    client.patch(f"/api/v1/transformations/{t['id']}", json={"steps": steps[:2]}, headers=DEV)
    client.post(f"/api/v1/transformations/{t['id']}/materialize", json={}, headers=DEV)
    run_jobs()
    out2 = client.get(f"/api/v1/datasets/{out['id']}", headers=DEV).json()
    assert out2["current_version"]["version"] == 2
    assert out2["row_count"] == 5


def test_cannot_transform_other_users_dataset(client):
    ds = _upload(client, headers=OTHER)
    assert _preview(client, ds, []).status_code == 404
    r = client.post(
        "/api/v1/transformations",
        json={"dataset_id": ds["id"], "name": "x", "steps": []},
        headers=DEV,
    )
    assert r.status_code == 404
