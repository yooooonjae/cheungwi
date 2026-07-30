import json

import pytest

from src.collect.common import ROOT
from src.collect.buildings import parse_title_items, pick_main_building, bun_ji, physical_flags


def _xml():
    return (ROOT / "tests" / "fixtures" / "bldrgst_item_sample.xml").read_text()


def _shared_xml():
    return (ROOT / "tests" / "fixtures" / "bldrgst_shared_parcel_sample.xml").read_text()


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
    assert ledger["mgmBldrgstPk"] == "11680-100000001"
    assert set(ledger) == {"mgmBldrgstPk", "bldNm", "dongNm", "totArea", "archArea", "platArea",
                           "grndFlrCnt", "ugrndFlrCnt", "heit", "useAprDay",
                           "mainPurpsCdNm", "etcPurps", "vlRat", "bcRat", "parking", "hoCnt"}


# ── 필지 공유 시드의 중복 배정 방지 (IFC 3동·파크원 2동·마제스타 2동 형태) ────────────

def test_shared_parcel_alias_beats_area_max():
    """필지 전체 최대(브라이튼 200,000)를 제치고 이름이 걸린 동을 집는다."""
    from src.collect.buildings import pick_main_with_method
    items = parse_title_items(_shared_xml())
    assert len(items) == 5
    assert max(i["totArea"] for i in items) == 200000.0      # 브라이튼여의도 오피스동
    main, how = pick_main_with_method(items, {"name": "서울국제금융센터 ONE",
                                              "aliases": ["IFC ONE", "IFC 1"]})
    assert (main["dongNm"], main["totArea"], how) == ("ONE", 62000.0, "alias")


def test_alias_fallback_narrows_within_matched_not_whole_parcel():
    """매칭 부분집합 안에서 좁혀야 한다 — 필지 전체에서 고르면 남의 건물을 집는다.

    '서울국제금융센터'는 ONE·TWO·THREE 에만 걸린다. 그 안의 최대는 THREE(168,000)이고,
    필지 전체의 최대 업무시설은 브라이튼여의도(200,000)다. _fallback(items) 로 새면 후자가
    잡히므로, 이 단언이 두 경로를 실제로 갈라낸다.
    """
    from src.collect.buildings import pick_main_with_method
    items = parse_title_items(_shared_xml())
    main, how = pick_main_with_method(items, {"name": "서울국제금융센터"})
    assert how == "alias_fallback"
    assert (main["dongNm"], main["totArea"]) == ("THREE", 168000.0)
    assert main["bldNm"] != "브라이튼여의도", "필지 전체에서 골랐다 — 부분집합을 벗어났다"


def test_shared_parcel_three_seeds_get_three_different_dongs():
    """세 시드가 같은 응답을 받아도 서로 다른 동을 집어야 한다."""
    from src.collect.buildings import pick_main_with_method
    items = parse_title_items(_shared_xml())
    picked = {}
    for nm in ("서울국제금융센터 ONE", "서울국제금융센터 TWO", "서울국제금융센터 THREE"):
        main, how = pick_main_with_method(items, {"name": nm})
        picked[nm] = main["mgmBldrgstPk"]
        assert how == "alias"
    assert len(set(picked.values())) == 3, f"중복 배정: {picked}"


def test_fallback_is_reported_so_duplicates_are_visible():
    """이름이 안 걸리면 폴백이라는 사실이 드러나야 한다 — 조용히 넘어가면 안 된다."""
    from src.collect.buildings import pick_main_with_method
    items = parse_title_items(_shared_xml())
    main, how = pick_main_with_method(items, {"name": "이름이 전혀 안 걸리는 빌딩"})
    assert how == "fallback"
    assert main["bldNm"] == "브라이튼여의도"   # 필지 전체에서 업무시설 우선 + 연면적 최대
    # 같은 필지의 두 시드가 나란히 폴백하면 같은 동을 집는다 — 이게 바로 잡아야 할 사고다
    other, _ = pick_main_with_method(items, {"name": "역시 안 걸리는 빌딩"})
    assert other["mgmBldrgstPk"] == main["mgmBldrgstPk"]


def test_duplicate_assignments_detects_collision():
    from src.collect.buildings import duplicate_assignments
    rows = [{"id": "ifc-one", "ledger": {"mgmBldrgstPk": "PK-3"}},
            {"id": "ifc-two", "ledger": {"mgmBldrgstPk": "PK-3"}},
            {"id": "ifc-three", "ledger": {"mgmBldrgstPk": "PK-9"}},
            {"id": "no-ledger", "ledger": None}]
    assert duplicate_assignments(rows) == {"PK-3": ["ifc-one", "ifc-two"]}
    assert duplicate_assignments([{"id": "a", "ledger": {"mgmBldrgstPk": "X"}}]) == {}


# ── data.go.kr 200-봉투 오류 분기 ────────────────────────────────────────────

def _envelope(code, msg):
    return ('<?xml version="1.0"?><OpenAPI_ServiceResponse><cmmMsgHeader>'
            f'<errMsg>SERVICE ERROR</errMsg><returnAuthMsg>{msg}</returnAuthMsg>'
            f'<returnReasonCode>{code}</returnReasonCode>'
            '</cmmMsgHeader></OpenAPI_ServiceResponse>')


def test_envelope_error_parses_gateway_envelope():
    from src.collect.buildings import envelope_error
    assert envelope_error(_envelope("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")) \
        == ("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")
    # 정상 응답은 봉투가 아니다 — resultCode 경로로 가야 한다
    assert envelope_error(_xml()) is None
    assert envelope_error("") is None and envelope_error("<html>Forbidden</html>") is None


def test_classify_prefers_message_over_ambiguous_code():
    """사유코드 '030'은 앞 0을 떼면 30(권한없음), 뒤 0을 떼면 03(데이터없음)이라 뜻이 갈린다.

    코드로 단정하면 건별로 끝났어야 할 '데이터 없음'이 전역 차단으로 승격돼
    남은 전 동을 생략해 버린다 — 그래서 메시지를 먼저 본다.
    """
    from src.collect.buildings import classify_envelope, LedgerNoData, _raise_for_envelope
    assert classify_envelope("030", "NODATA_ERROR") == "nodata"
    assert classify_envelope("03", "NODATA_ERROR") == "nodata"
    assert classify_envelope("003", "NODATA_ERROR") == "nodata"
    assert classify_envelope("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR") == "denied"
    with pytest.raises(LedgerNoData):
        _raise_for_envelope("030", "NODATA_ERROR", "어디")
    # 메시지가 없어 코드에만 기대야 하는데 뜻이 갈리면, 한쪽으로 단정하지 않는다
    assert classify_envelope("030", "") == "unknown"
    assert classify_envelope("03", "") == "nodata" and classify_envelope("30", "") == "denied"


def test_envelope_branches_by_reason_code():
    """권한·쿼터·데이터없음은 성격이 달라 서로 다른 예외로 갈라져야 한다."""
    from src.collect.buildings import (_raise_for_envelope, LedgerAccessDenied,
                                       LedgerQuotaExceeded, LedgerNoData)
    with pytest.raises(LedgerAccessDenied):
        _raise_for_envelope("30", "SERVICE_ACCESS_DENIED_ERROR", "어디")
    with pytest.raises(LedgerQuotaExceeded):
        _raise_for_envelope("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", "어디")
    with pytest.raises(LedgerNoData):
        _raise_for_envelope("03", "NODATA_ERROR", "어디")
    # 사유코드를 못 읽어도 메시지로 판정한다
    with pytest.raises(LedgerQuotaExceeded):
        _raise_for_envelope("", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", "어디")
    # 모르는 코드는 삼키지 않고 올린다
    with pytest.raises(RuntimeError):
        _raise_for_envelope("99", "WHAT_IS_THIS", "어디")


def test_fetch_page_raises_typed_error_on_200_envelope(tmp_path, monkeypatch):
    """HTTP 200 + 오류 봉투가 '빈 응답'으로 오인돼 재시도만 하다 죽지 않아야 한다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "RAW_DIR", tmp_path)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def fake_api_get(url, params, **kw):
        calls["n"] += 1
        return 200, _envelope("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")
    monkeypatch.setattr(B, "api_get", fake_api_get)

    with pytest.raises(B.LedgerQuotaExceeded):
        B._fetch_page("11560", "11000", "0023", "0000", 1, "KEY")
    assert calls["n"] == 1, f"봉투는 재시도해도 같은 답이다 — 1회로 끝나야 하는데 {calls['n']}회"
    assert list(tmp_path.glob("*.xml")) == [], "오류 응답을 캐시에 박제하면 안 된다"


def test_quota_stops_ledger_but_saves(tmp_path, monkeypatch):
    """쿼터 소진은 실패가 아니다 — 저장까지 가고 RESUME_NEEDED 로 끝나야 한다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "OUT_PATH", tmp_path / "buildings.json")
    monkeypatch.setattr(B, "load_config", lambda: {"service_key": "K", "vworld_key": "V"})
    monkeypatch.setattr(B, "_ensure_ldong", lambda: [])
    monkeypatch.setattr(B, "bjdong_index", lambda lines: {("11560", "여의도동"): "11000"})
    monkeypatch.setattr(B, "SEED_PATH", tmp_path / "seed.json")
    (tmp_path / "seed.json").write_text(json.dumps({"buildings": [
        {"id": "a", "name": "가", "region": "YBD", "sgg_cd": "11560", "umd": "여의도동",
         "jibun": "23", "address_road": "서울 영등포구 국제금융로 10"},
        {"id": "b", "name": "나", "region": "YBD", "sgg_cd": "11560", "umd": "여의도동",
         "jibun": "22", "address_road": "서울 영등포구 여의대로 108"}]}, ensure_ascii=False))

    def boom(*a, **kw):
        raise B.LedgerQuotaExceeded("일일 쿼터 소진")
    monkeypatch.setattr(B, "fetch_title_items", boom)
    monkeypatch.setattr(B, "_vworld_cached", lambda key, seed, pnu: {
        "lat": 37.5, "lon": 126.9, "zones": ["일반상업지역"], "pnu": pnu,
        "land_price_won_m2": 1, "land_price_year": "2025",
        "pnu_at_point": pnu, "jibun_check": ""})

    result = B.collect()
    assert result["meta"]["complete"] is False           # → main() 이 RESUME_NEEDED 를 찍는다
    assert "쿼터" in result["meta"]["ledger_status"]
    assert (tmp_path / "buildings.json").exists(), "쿼터 소진 시에도 저장에 도달해야 한다"
    assert len(result["buildings"]) == 2


def test_nodata_is_per_building_and_keeps_going(tmp_path, monkeypatch):
    """데이터 없음은 그 건만 failed 로 남기고 나머지는 계속한다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "OUT_PATH", tmp_path / "buildings.json")
    monkeypatch.setattr(B, "load_config", lambda: {"service_key": "K", "vworld_key": "V"})
    monkeypatch.setattr(B, "_ensure_ldong", lambda: [])
    monkeypatch.setattr(B, "bjdong_index", lambda lines: {("11560", "여의도동"): "11000"})
    monkeypatch.setattr(B, "SEED_PATH", tmp_path / "seed.json")
    (tmp_path / "seed.json").write_text(json.dumps({"buildings": [
        {"id": "a", "name": "서울국제금융센터 ONE", "region": "YBD", "sgg_cd": "11560",
         "umd": "여의도동", "jibun": "23", "address_road": "서울 영등포구 국제금융로 10"},
        {"id": "b", "name": "나", "region": "YBD", "sgg_cd": "11560", "umd": "여의도동",
         "jibun": "22", "address_road": "서울 영등포구 여의대로 108"}]}, ensure_ascii=False))

    def fetch(sgg, bj, bun, ji, key):
        if bun == "0022":
            raise B.LedgerNoData("대장 조회 결과 없음 — 사유코드 03 NODATA_ERROR")
        return parse_title_items(_shared_xml())
    monkeypatch.setattr(B, "fetch_title_items", fetch)
    monkeypatch.setattr(B, "_vworld_cached", lambda key, seed, pnu: {
        "lat": 37.5, "lon": 126.9, "zones": ["일반상업지역"], "pnu": pnu,
        "land_price_won_m2": 1, "land_price_year": "2025",
        "pnu_at_point": pnu, "jibun_check": ""})

    result = B.collect()
    assert result["meta"]["matched"] == 1
    assert [f["id"] for f in result["meta"]["failed"]] == ["b"]
    assert result["buildings"][0]["ledger"]["dongNm"] == "ONE"
    assert result["buildings"][0]["match_method"] == "alias"


# ── VWorld 캐시 ─────────────────────────────────────────────────────────────

def test_vworld_cache_refetches_when_input_changed(tmp_path, monkeypatch):
    """캐시 키가 시드 id 뿐이면 주소·PNU가 바뀌어도 옛 결과를 준다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "VWORLD_RAW_DIR", tmp_path)
    seed = {"id": "x", "address_road": "서울 강남구 테헤란로 152"}
    calls = []

    def fake_lookup(key, road, pnu=""):
        calls.append((road, pnu))
        return {"lat": 37.5, "lon": 127.0, "zones": ["일반상업지역"], "pnu": pnu,
                "land_price_won_m2": 1, "land_price_year": "2025",
                "pnu_at_point": "", "jibun_check": ""}
    monkeypatch.setattr(B, "vworld_lookup", fake_lookup)

    B._vworld_cached("K", seed, "PNU-A")
    B._vworld_cached("K", seed, "PNU-A")            # 캐시 적중 — 호출 없음
    assert len(calls) == 1
    B._vworld_cached("K", seed, "PNU-B")            # PNU 바뀜 → 재조회
    assert len(calls) == 2
    B._vworld_cached("K", {**seed, "address_road": "서울 강남구 테헤란로 999"}, "PNU-B")
    assert len(calls) == 3, "주소가 바뀌면 재조회해야 한다"


def test_vworld_cache_skips_incomplete_results(tmp_path, monkeypatch):
    """반쪽 결과(공시지가 오류·빈 용도지역)를 캐시에 박제하면 영구히 반쪽이 된다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "VWORLD_RAW_DIR", tmp_path)
    seed = {"id": "y", "address_road": "서울 어딘가"}
    bad = [
        {"error": "지오코딩 실패(NOT_FOUND)"},
        {"lat": None, "lon": None, "zones": [], "pnu": "P", "land_price_won_m2": 0},
        {"lat": 37.5, "lon": 127.0, "zones": [], "pnu": "P", "land_price_won_m2": 1},
        {"lat": 37.5, "lon": 127.0, "zones": ["상업"], "pnu": "P", "land_price_won_m2": 0,
         "land_price_error": "2025년 공시지가 행 없음"},
    ]
    for payload in bad:
        monkeypatch.setattr(B, "vworld_lookup", lambda k, r, p="", _v=payload: dict(_v))
        B._vworld_cached("K", seed, "P")
        assert list(tmp_path.glob("*.json")) == [], f"캐시하면 안 되는 결과를 캐시했다: {payload}"

    good = {"lat": 37.5, "lon": 127.0, "zones": ["일반상업지역"], "pnu": "P",
            "land_price_won_m2": 67300000, "land_price_year": "2025",
            "pnu_at_point": "P", "jibun_check": "737 대"}
    monkeypatch.setattr(B, "vworld_lookup", lambda k, r, p="": dict(good))
    B._vworld_cached("K", seed, "P")
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_transient_envelope_retries_then_isolates(tmp_path, monkeypatch):
    """일시 오류(04·05·21)는 재시도하고, 끝내 안 되면 그 동만 격리한다 — 전역 사망 금지."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "RAW_DIR", tmp_path)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    for code, msg in (("04", "HTTP_ERROR"), ("05", "SERVICETIMEOUT_ERROR"),
                      ("21", "TEMPORARILY_DISABLE_THE_SERVICEKEY_ERROR")):
        calls = {"n": 0}

        def fake(url, params, _c=code, _m=msg, **kw):
            calls["n"] += 1
            return 200, _envelope(_c, _m)
        monkeypatch.setattr(B, "api_get", fake)
        with pytest.raises(B.LedgerTransient):
            B._fetch_page("11560", "11000", "0023", "0000", 1, "KEY")
        assert calls["n"] == B.EMPTY_RETRIES + 1, f"{msg}: 재시도해야 한다({calls['n']}회)"
    assert list(tmp_path.glob("*.xml")) == []

    # 재시도 도중 회복하면 정상 반환한다
    seq = {"n": 0}

    def flaky(url, params, **kw):
        seq["n"] += 1
        return (200, _envelope("05", "SERVICETIMEOUT_ERROR")) if seq["n"] < 3 else (200, _shared_xml())
    monkeypatch.setattr(B, "api_get", flaky)
    assert len(parse_title_items(B._fetch_page("11560", "11000", "0023", "0000", 1, "KEY"))) == 5


def test_transient_is_per_building_and_keeps_going(tmp_path, monkeypatch):
    """한 동의 일시 오류가 나머지 54동 수집과 저장을 막으면 안 된다."""
    from src.collect import buildings as B
    monkeypatch.setattr(B, "OUT_PATH", tmp_path / "buildings.json")
    monkeypatch.setattr(B, "load_config", lambda: {"service_key": "K", "vworld_key": "V"})
    monkeypatch.setattr(B, "_ensure_ldong", lambda: [])
    monkeypatch.setattr(B, "bjdong_index", lambda lines: {("11560", "여의도동"): "11000"})
    monkeypatch.setattr(B, "SEED_PATH", tmp_path / "seed.json")
    (tmp_path / "seed.json").write_text(json.dumps({"buildings": [
        {"id": "a", "name": "서울국제금융센터 ONE", "region": "YBD", "sgg_cd": "11560",
         "umd": "여의도동", "jibun": "23", "address_road": "서울 영등포구 국제금융로 10"},
        {"id": "b", "name": "나", "region": "YBD", "sgg_cd": "11560", "umd": "여의도동",
         "jibun": "22", "address_road": "서울 영등포구 여의대로 108"}]}, ensure_ascii=False))

    def fetch(sgg, bj, bun, ji, key):
        if bun == "0022":
            raise B.LedgerTransient("대장 API 일시 오류 — 사유코드 05 SERVICETIMEOUT_ERROR")
        return parse_title_items(_shared_xml())
    monkeypatch.setattr(B, "fetch_title_items", fetch)
    monkeypatch.setattr(B, "_vworld_cached", lambda key, seed, pnu: {
        "lat": 37.5, "lon": 126.9, "zones": ["일반상업지역"], "pnu": pnu,
        "land_price_won_m2": 1, "land_price_year": "2025",
        "pnu_at_point": pnu, "jibun_check": ""})

    result = B.collect()
    assert result["meta"]["matched"] == 1                     # a는 살아남았다
    assert [f["id"] for f in result["meta"]["failed"]] == ["b"]
    assert "일시 오류" in result["meta"]["failed"][0]["reason"]
    # 일시 오류는 그 건만 격리한다 — 전역 차단(ledger_blocked)으로 승격되지 않으므로
    # 대장 상태는 여전히 OK 다. 여기가 OK 가 아니면 뒤따르는 동들이 통째로 미조회가 된다.
    assert result["meta"]["ledger_status"] == "OK"
    assert result["buildings"][1]["ledger"] is None
    assert (tmp_path / "buildings.json").exists(), "일시 오류에도 저장에 도달해야 한다"
