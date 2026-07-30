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


def test_seed_maps_regions_to_rone_names():
    """권역 조인 키다. 시드 권역(CBD·GBD·YBD)과 R-ONE 권역명은 글자가 겹치지 않아, 매핑을
    데이터에 적어 두지 않으면 소비자가 코드에 문자열을 다시 박는다."""
    meta = _load()["meta"]
    assert meta["rone_region"] == {"CBD": "도심", "GBD": "강남", "YBD": "여의도마포"}
    assert set(meta["rone_region"]) == set(meta["region_def"])
    rone = json.load(open(ROOT / "data" / "rone_office.json"))["regions"]
    for region, name in meta["rone_region"].items():
        assert name in rone, f"{region}: R-ONE 권역 {name} 이 산출에 없다"
    # 근사 매핑이라는 사실은 값 옆에 붙어 있어야 한다 — 여의도마포는 마포를 포함한 합성 권역이다
    assert "여의도마포" in meta["rone_region_caveat"] and "근사" in meta["rone_region_caveat"]


def test_seed_ids_unique():
    rows = _load()["buildings"]
    ids = [b["id"] for b in rows]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids)
