import datetime

from src.build.manifest import build_manifest


def test_manifest_covers_all_sources():
    m = build_manifest(write=False)
    keys = {s["key"] for s in m["sources"]}
    assert keys == {"seed_buildings", "buildings", "trades", "rone_office", "reits", "rates"}
    for s in m["sources"]:
        assert s["observed_through"] and s["rows"] >= 1, s["key"]


def test_manifest_cutoff_is_month():
    m = build_manifest(write=False)
    assert len(m["data_cutoff"]) == 7 and m["data_cutoff"][4] == "-"   # "YYYY-MM"


def test_cutoff_is_latest_completed_month():
    """진행 중인 달은 부분 관측이라 기준월에서 빠지고, 나머지 중 최신 월이 기준월이다."""
    m = build_manifest(write=False)
    cur = datetime.date.today().strftime("%Y-%m")
    done = [s["observed_through"] for s in m["sources"] if s["observed_through"] < cur]
    assert m["data_cutoff"] == max(done) < cur
    # 관측월과 수집일은 다른 축이다 — 분기 원천(R-ONE)은 같은 날 받아도 몇 달 뒤처진다.
    rone = next(s for s in m["sources"] if s["key"] == "rone_office")
    assert rone["observed_through"] < rone["collected_at"][:7]
