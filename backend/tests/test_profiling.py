"""Profiling accuracy: every statistic is checked against an independent Python computation."""

import math
import random
import statistics

from app.analytics.profile import profile_parquet
from tests.conftest import DEV, run_jobs, upload_ready


def _csv(rows):
    return (
        "num,cat,flag,day,txt\n"
        + "\n".join(",".join("" if v is None else str(v) for v in r) for r in rows)
    ).encode()


def _data(n=2000, seed=7):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        num = round(rnd.gauss(50, 12), 3) if i % 10 else None
        cat = rnd.choice(["red", "green", "blue", "amber"]) if i % 7 else None
        flag = rnd.choice(["true", "false"])
        day = f"2024-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
        txt = str(rnd.randint(1, 999))  # numeric-looking text, kept as VARCHAR below
        rows.append((num, cat, flag, day, f"x{txt}" if i == 0 else txt))
    return rows


def test_profile_matches_python(client):
    rows = _data()
    ds = upload_ready(client, _csv(rows), "prof.csv")
    run_jobs()  # profile job enqueued after ingest
    r = client.get(f"/api/v1/datasets/{ds['id']}/profile", headers=DEV).json()
    assert r["status"] == "ready", r
    prof = r["profile"]
    assert prof["row_count"] == len(rows)
    assert prof["sampled"] is False
    cols = {c["name"]: c for c in prof["columns"]}

    nums = [r[0] for r in rows if r[0] is not None]
    c = cols["num"]
    assert c["kind"] == "numeric"
    assert c["nulls"] == len(rows) - len(nums)
    assert math.isclose(c["null_pct"], (len(rows) - len(nums)) / len(rows) * 100)
    assert math.isclose(c["min"], min(nums)) and math.isclose(c["max"], max(nums))
    assert math.isclose(c["mean"], statistics.fmean(nums), rel_tol=1e-9)
    assert math.isclose(c["stddev"], statistics.stdev(nums), rel_tol=1e-9)
    assert c["distinct"] == len(set(nums))
    assert math.isclose(c["quantiles"]["p50"], statistics.median(nums), rel_tol=1e-9)
    q = statistics.quantiles(nums, n=4, method="inclusive")
    assert math.isclose(c["quantiles"]["p25"], q[0], rel_tol=1e-9)
    assert math.isclose(c["quantiles"]["p75"], q[2], rel_tol=1e-9)
    assert sum(b["count"] for b in c["histogram"]) == len(nums)

    cats = [r[1] for r in rows if r[1] is not None]
    c = cols["cat"]
    assert c["kind"] == "text" and c["distinct"] == 4
    expected_top = sorted(((v, cats.count(v)) for v in set(cats)), key=lambda x: (-x[1], x[0]))
    assert [(t["value"], t["count"]) for t in c["top_values"][:4]] == expected_top
    assert any(f["code"] == "has_nulls" for f in c["quality"])

    assert cols["flag"]["kind"] == "boolean"
    assert sum(t["count"] for t in cols["flag"]["top_values"]) == len(rows)
    assert cols["day"]["kind"] == "temporal"
    assert cols["day"]["min"] == min(r[3] for r in rows)
    txt = cols["txt"]
    assert txt["kind"] == "text"
    assert txt["numeric_like_pct"] > 99
    assert any(f["code"] == "numeric_text" for f in txt["quality"])


def test_profile_sampling_is_labelled(tmp_path):
    import duckdb

    path = str(tmp_path / "p.parquet")
    duckdb.sql(f"COPY (SELECT range AS id, range % 8 AS g FROM range(30000)) TO '{path}'")
    prof = profile_parquet(path, sample_threshold=10_000, sample_rows=5_000)
    assert prof["sampled"] is True
    assert prof["sample_rows"] == 5_000
    cols = {c["name"]: c for c in prof["columns"]}
    # Base statistics are always exact over the full table...
    assert cols["id"]["min"] == 0 and cols["id"]["max"] == 29_999
    assert cols["id"]["nulls"] == 0
    # ...while sample-based metrics say so.
    assert "sample" in cols["id"]["quantiles"]["method"]
    assert sum(t["count"] for t in cols["g"]["top_values"]) == 5_000
    # Deterministic: same seed, same sample.
    again = profile_parquet(path, sample_threshold=10_000, sample_rows=5_000)
    assert again["columns"][1]["top_values"] == cols["g"]["top_values"]


def test_profile_edge_cases(tmp_path):
    import duckdb

    path = str(tmp_path / "e.parquet")
    duckdb.sql(
        f"COPY (SELECT NULL::INTEGER AS empty, 5 AS const, range::VARCHAR AS uid "
        f"FROM range(500)) TO '{path}'"
    )
    cols = {c["name"]: c for c in profile_parquet(path)["columns"]}
    assert cols["empty"]["null_pct"] == 100
    assert any(f["code"] == "all_null" for f in cols["empty"]["quality"])
    assert any(f["code"] == "constant" for f in cols["const"]["quality"])
    assert cols["const"]["histogram"] == [{"start": 5.0, "end": 5.0, "count": 500}]
    assert any(f["code"] == "unique_like" for f in cols["uid"]["quality"])


def test_profile_refresh(client):
    ds = upload_ready(client, b"a\n1\n2\n", "r.csv")
    run_jobs()
    r = client.post(f"/api/v1/datasets/{ds['id']}/profile", headers=DEV)
    assert r.status_code == 202
    assert (
        client.get(f"/api/v1/datasets/{ds['id']}/profile", headers=DEV).json()["status"]
        == "pending"
    )
    run_jobs()
    assert (
        client.get(f"/api/v1/datasets/{ds['id']}/profile", headers=DEV).json()["status"] == "ready"
    )
