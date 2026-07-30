from src.collect.common import ROOT
from src.collect.buildings import parse_title_items, pick_main_building, bun_ji, physical_flags


def _xml():
    return (ROOT / "tests" / "fixtures" / "bldrgst_item_sample.xml").read_text()


def test_bun_ji():
    assert bun_ji("737") == ("0737", "0000")
    assert bun_ji("60-1") == ("0060", "0001")


def test_parse_and_pick_main():
    items = parse_title_items(_xml())
    assert len(items) == 2
    seed = {"name": "테스트타워"}
    main = pick_main_building(items, seed)
    assert main["mainPurpsCdNm"] == "업무시설"
    assert main["totArea"] == max(i["totArea"] for i in items)
    assert isinstance(main["grndFlrCnt"], int) and isinstance(main["totArea"], float)


def test_physical_flags():
    ok = {"totArea": 100000.0, "grndFlrCnt": 30, "ugrndFlrCnt": 7, "useAprDay": "20010601"}
    assert physical_flags(ok) == []
    bad = {"totArea": 100000.0, "grndFlrCnt": 2, "ugrndFlrCnt": 0, "useAprDay": "20010601"}
    assert any("층당면적" in f for f in physical_flags(bad))      # 100000/2=50000㎡/층 → 게이트 위반
    assert any("층수" in f for f in physical_flags({**ok, "grndFlrCnt": 3}))  # 프라임인데 3층
    assert any("사용승인일" in f for f in physical_flags({**ok, "useAprDay": ""}))


# ── 아래는 필지 공유 건물(아셈타워·마제스타시티 등) 대응 규칙의 회귀 방지 ──────────────

def test_pick_main_prefers_discriminating_alias():
    """단지명처럼 필지 안의 여러 동에 다 걸리는 이름은 변별력이 없다 — 한 동만 집는 키를 쓴다."""
    items = parse_title_items(_xml())
    # "가나타워"는 두 동 모두에 걸리지만 "부속동"은 한 동만 집는다
    seed = {"name": "가나타워 부속동", "aliases": ["가나타워", "부속동"]}
    main = pick_main_building(items, seed)
    assert main["bldNm"] == "가나타워 부속동"
    assert main["totArea"] == 1820.5     # 연면적 최대(212615.6)를 고르지 않는다


def test_pick_main_falls_back_within_matched_when_alias_not_discriminating():
    """변별력 없는 이름만 걸리면 걸린 동들 안에서 업무시설·연면적 최대로 좁힌다."""
    items = parse_title_items(_xml())
    main = pick_main_building(items, {"name": "가나타워"})   # 두 동 모두에 걸린다
    assert main["mainPurpsCdNm"] == "업무시설"
    assert main["totArea"] == 212615.6


def test_pick_main_respects_seed_note_ban_on_area_max():
    """시드 note가 연면적 최대 선택을 금지했는데 이름이 안 걸리면, 엉뚱한 동을 집지 말고 포기한다."""
    items = parse_title_items(_xml())
    seed = {"name": "아셈타워", "aliases": ["ASEM"],
            "note": "대장 표제부에서 동을 고를 때 반드시 이름으로 매칭할 것 — 연면적 최대 선택 금지."}
    assert pick_main_building(items, seed) is None
    # 같은 note여도 이름이 걸리면 정상 선택된다
    assert pick_main_building(items, {**seed, "aliases": ["가나타워 부속동"]})["dongNm"] == "부속동"


def test_pick_main_none_on_empty():
    assert pick_main_building([], {"name": "무엇이든"}) is None


def test_pnu_parts_splits_code():
    from src.collect.buildings import pnu_parts
    p = pnu_parts("1168010100107370000")          # 강남구 역삼동 737
    assert p == {"sgg_cd": "11680", "bjdong": "10100", "san": False, "jibun": "737"}
    assert pnu_parts("1168010600108910010")["jibun"] == "891-10"   # 대치동 891-10
    assert pnu_parts("") is None and pnu_parts("11680") is None


def test_ledger_parking_is_sum_of_four_counts():
    from src.collect.buildings import to_ledger
    items = parse_title_items(_xml())
    main = pick_main_building(items, {"name": "테스트타워"})
    ledger = to_ledger(main)
    assert ledger["parking"] == 0 + 0 + 1462 + 36
    assert ledger["useAprDay"] == "20010601"
    assert ledger["bldNm"] == "가나타워"
    assert set(ledger) == {"bldNm", "dongNm", "totArea", "archArea", "platArea",
                           "grndFlrCnt", "ugrndFlrCnt", "heit", "useAprDay",
                           "mainPurpsCdNm", "etcPurps", "vlRat", "bcRat", "parking", "hoCnt"}
