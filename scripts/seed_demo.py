#!/usr/bin/env python3
"""Load the demo dataset and build a small dashboard through the public API.

    python scripts/seed_demo.py                       # against http://localhost:8000
    python scripts/seed_demo.py --api http://host:8000 --token <token>

Uses only the standard library, so it runs with any Python 3.10+. Everything it
creates goes through the same endpoints the UI uses; nothing is written to the
database directly.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "demo_orders.csv"


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.headers = {"Authorization": f"Bearer {token}"}

    def call(self, method: str, path: str, body: object = None, *, raw: bytes | None = None) -> dict:
        data, headers = raw, dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            headers["Content-Type"] = "application/octet-stream"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed scheme from CLI
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}")


def wait_ready(api: Api, dataset_id: str) -> dict:
    for _ in range(240):
        ds = api.call("GET", f"/datasets/{dataset_id}")
        if ds["status"] == "ready":
            return ds
        if ds["status"] == "failed":
            sys.exit(f"ingest failed: {ds}")
        time.sleep(0.5)
    sys.exit("timed out waiting for ingest; is the worker running?")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", default="facet-dev-token")
    args = ap.parse_args()
    api = Api(args.api, args.token)

    existing = api.call("GET", "/datasets?limit=200")["items"]
    if any(d["name"] == "Demo orders" for d in existing):
        print("Demo already loaded; delete the 'Demo orders' dataset to reseed.")
        return

    q = urllib.parse.urlencode({"filename": SAMPLE.name, "name": "Demo orders"})
    created = api.call("POST", f"/datasets?{q}", raw=SAMPLE.read_bytes())
    ds = wait_ready(api, created["dataset"]["id"])
    t = ds["sql_name"]
    print(f"dataset ready: {t} ({ds['id']})")

    revenue_sql = (
        f"SELECT region,\n       count(*) AS orders,\n       round(sum(qty * unit_price), 2) AS revenue\n"
        f"FROM {t}\nGROUP BY region\nORDER BY revenue DESC"
    )
    by_region = api.call("POST", "/queries", {"name": "Revenue by region", "sql": revenue_sql,
                                  "description": "Order count and revenue per region."})
    returning = api.call("POST", "/queries", {
        "name": "Returning vs new customers by month",
        "sql": (f"SELECT date_trunc('month', ordered_at) AS month, is_returning, count(*) AS orders\n"
                f"FROM {t}\nGROUP BY ALL\nORDER BY month"),
    })

    def chart(name: str, spec: dict, **source: str) -> str:
        body = {"name": name, "spec": spec, **(source or {"dataset_id": ds["id"]})}
        return api.call("POST", "/charts", body)["id"]

    charts = [
        chart("Orders", {"type": "stat", "y": [{"agg": "count", "label": "Orders"}]}),
        chart("Average discount", {"type": "stat", "y": [{"field": "discount_pct", "agg": "avg", "label": "Avg discount %"}]}),
        chart("Revenue by region", {"type": "bar", "x": "region",
                                    "y": [{"field": "revenue", "agg": "sum", "label": "Revenue"}],
                                    "options": {"sort": "y_desc"}}, saved_query_id=by_region["id"]),
        chart("Monthly orders by shipping", {"type": "line", "x": "ordered_at", "grain": "month",
                                             "y": [{"agg": "count", "label": "Orders"}], "series": "shipping"}),
        chart("Unit price distribution", {"type": "histogram", "x": "unit_price"}),
        chart("Returning customers", {"type": "area", "x": "month", "y": [{"field": "orders", "agg": "sum", "label": "Orders"}],
                                      "series": "is_returning", "options": {"stacked": True}},
              saved_query_id=returning["id"]),
        chart("Quantity vs unit price", {"type": "scatter", "x": "unit_price", "y": [{"field": "qty", "agg": "sum"}]}),
    ]
    layout = [
        {"i": "a", "chart_id": charts[0], "x": 0, "y": 0, "w": 3, "h": 3},
        {"i": "b", "chart_id": charts[1], "x": 3, "y": 0, "w": 3, "h": 3},
        {"i": "c", "chart_id": charts[2], "x": 6, "y": 0, "w": 6, "h": 7},
        {"i": "d", "chart_id": charts[3], "x": 0, "y": 3, "w": 6, "h": 8},
        {"i": "e", "chart_id": charts[4], "x": 6, "y": 7, "w": 6, "h": 7},
        {"i": "f", "chart_id": charts[5], "x": 0, "y": 11, "w": 6, "h": 7},
    ]
    dash = api.call("POST", "/dashboards", {
        "name": "Orders overview",
        "description": "Volume, mix and pricing for the demo orders dataset.",
        "layout": layout,
    })
    print(f"dashboard: {args.api.replace(':8000', ':3000')}/dashboards/{dash['id']}")


if __name__ == "__main__":
    main()
