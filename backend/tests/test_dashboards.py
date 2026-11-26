"""Dashboards: CRUD, layout validation, workspace isolation, pruning of deleted charts."""

import uuid

import pytest

from tests.conftest import DEV, OTHER, SAMPLES, upload_ready


@pytest.fixture
def sales(client):
    return upload_ready(client, (SAMPLES / "sales.csv").read_bytes(), "sales.csv")


def _chart(client, source: dict, name="c") -> dict:
    r = client.post(
        "/api/v1/charts",
        json={"name": name, **source, "spec": {"type": "stat", "y": [{"agg": "count"}]}},
        headers=DEV,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _item(chart_id: str, i: str = "a", **kw) -> dict:
    return {"i": i, "chart_id": chart_id, "x": 0, "y": 0, "w": 6, "h": 4, **kw}


def test_dashboard_crud_and_layout_persistence(client, sales):
    c1 = _chart(client, {"dataset_id": sales["id"]}, "one")
    c2 = _chart(client, {"dataset_id": sales["id"]}, "two")
    r = client.post(
        "/api/v1/dashboards",
        json={"name": "Ops", "layout": [_item(c1["id"])]},
        headers=DEV,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    layout = [_item(c1["id"], "a", x=6, y=2), _item(c2["id"], "b", w=12, h=6)]
    filters = [{"column": "region", "op": "=", "value": "North"}]
    r = client.patch(
        f"/api/v1/dashboards/{d['id']}", json={"layout": layout, "filters": filters}, headers=DEV
    )
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/dashboards/{d['id']}", headers=DEV).json()
    assert [(i["i"], i["x"], i["y"], i["w"], i["h"]) for i in got["layout"]] == [
        ("a", 6, 2, 6, 4),
        ("b", 0, 0, 12, 6),
    ]
    assert got["filters"] == [{"column": "region", "op": "=", "value": "North"}]
    assert got["name"] == "Ops"  # untouched by the partial update

    page = client.get("/api/v1/dashboards", headers=DEV).json()
    assert page["total"] == 1
    assert client.delete(f"/api/v1/dashboards/{d['id']}", headers=DEV).status_code == 204
    assert client.get(f"/api/v1/dashboards/{d['id']}", headers=DEV).status_code == 404


@pytest.mark.parametrize(
    "item",
    [
        {"w": 0},
        {"w": 13},
        {"h": 1},
        {"x": -1},
        {"i": ""},
    ],
)
def test_layout_bounds(client, sales, item):
    c = _chart(client, {"dataset_id": sales["id"]})
    r = client.post(
        "/api/v1/dashboards", json={"name": "x", "layout": [_item(c["id"], **item)]}, headers=DEV
    )
    assert r.status_code == 422


def test_layout_rejects_unknown_and_foreign_charts(client, sales):
    r = client.post(
        "/api/v1/dashboards",
        json={"name": "x", "layout": [_item(str(uuid.uuid4()))]},
        headers=DEV,
    )
    assert r.status_code == 422
    # Another user cannot place my chart on their dashboard.
    mine = _chart(client, {"dataset_id": sales["id"]})
    r = client.post(
        "/api/v1/dashboards", json={"name": "x", "layout": [_item(mine["id"])]}, headers=OTHER
    )
    assert r.status_code == 422


def test_duplicate_item_keys_rejected(client, sales):
    c = _chart(client, {"dataset_id": sales["id"]})
    r = client.post(
        "/api/v1/dashboards",
        json={"name": "x", "layout": [_item(c["id"], "a"), _item(c["id"], "a")]},
        headers=DEV,
    )
    assert r.status_code == 422


def test_isolation(client, sales):
    d = client.post("/api/v1/dashboards", json={"name": "Mine"}, headers=DEV).json()
    assert client.get(f"/api/v1/dashboards/{d['id']}", headers=OTHER).status_code == 404
    r = client.patch(f"/api/v1/dashboards/{d['id']}", json={"name": "x"}, headers=OTHER)
    assert r.status_code == 404
    assert client.delete(f"/api/v1/dashboards/{d['id']}", headers=OTHER).status_code == 404
    assert client.get("/api/v1/dashboards", headers=OTHER).json()["total"] == 0


def test_deleting_chart_prunes_layout(client, sales):
    c1 = _chart(client, {"dataset_id": sales["id"]})
    c2 = _chart(client, {"dataset_id": sales["id"]})
    d = client.post(
        "/api/v1/dashboards",
        json={"name": "x", "layout": [_item(c1["id"], "a"), _item(c2["id"], "b")]},
        headers=DEV,
    ).json()
    client.delete(f"/api/v1/charts/{c1['id']}", headers=DEV)
    got = client.get(f"/api/v1/dashboards/{d['id']}", headers=DEV).json()
    assert [i["chart_id"] for i in got["layout"]] == [c2["id"]]


def test_deleting_source_prunes_layout(client, sales):
    sq = client.post(
        "/api/v1/queries", json={"name": "q", "sql": "SELECT * FROM sales"}, headers=DEV
    ).json()
    by_query = _chart(client, {"saved_query_id": sq["id"]})
    by_dataset = _chart(client, {"dataset_id": sales["id"]})
    d = client.post(
        "/api/v1/dashboards",
        json={"name": "x", "layout": [_item(by_query["id"], "a"), _item(by_dataset["id"], "b")]},
        headers=DEV,
    ).json()
    assert client.delete(f"/api/v1/queries/{sq['id']}", headers=DEV).status_code == 204
    got = client.get(f"/api/v1/dashboards/{d['id']}", headers=DEV).json()
    assert [i["chart_id"] for i in got["layout"]] == [by_dataset["id"]]
    assert client.delete(f"/api/v1/datasets/{sales['id']}", headers=DEV).status_code == 204
    got = client.get(f"/api/v1/dashboards/{d['id']}", headers=DEV).json()
    assert got["layout"] == []


def test_activity_feed_and_summary(client, sales):
    _chart(client, {"dataset_id": sales["id"]}, "Feed chart")
    client.post("/api/v1/dashboards", json={"name": "Feed dash"}, headers=DEV)
    feed = client.get("/api/v1/activity", headers=DEV).json()
    kinds = [e["kind"] for e in feed]
    assert kinds[:2] == ["dashboard.created", "chart.saved"]
    assert "dataset.ready" in kinds or any(k.startswith("dataset.") for k in kinds)
    assert client.get("/api/v1/activity", headers=OTHER).json() == []
    s = client.get("/api/v1/workspace/summary", headers=DEV).json()
    assert s == {"datasets": 1, "saved_queries": 0, "charts": 1, "dashboards": 1}
