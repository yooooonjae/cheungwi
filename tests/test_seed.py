import json, re
from src.collect.common import ROOT, SEOUL_GU


def _load():
    return json.load(open(ROOT / "data" / "seed_buildings.json"))


def test_seed_schema_and_counts():
    d = _load()
    rows = d["buildings"]
    assert 45 <= len(rows) <= 55
    by_region = {}
    for b in rows:
        for key in ("id", "name", "region", "sgg_cd", "umd", "jibun", "address_road"):
            assert b.get(key), f"{b.get('name')}: {key} 누락"
        assert b["region"] in ("CBD", "GBD", "YBD")
        assert b["sgg_cd"] in d["meta"]["region_def"][b["region"]]
        assert b["sgg_cd"] in SEOUL_GU
        assert re.fullmatch(r"\d+(-\d+)?", b["jibun"]), f"{b['name']}: 지번 형식 {b['jibun']}"
        by_region[b["region"]] = by_region.get(b["region"], 0) + 1
    assert by_region["CBD"] >= 15 and by_region["GBD"] >= 15 and by_region["YBD"] >= 10


def test_seed_ids_unique():
    rows = _load()["buildings"]
    ids = [b["id"] for b in rows]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids)
