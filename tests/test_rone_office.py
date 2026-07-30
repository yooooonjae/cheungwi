import json
import pytest
from src.collect import rone_office
from src.collect.common import ROOT
from src.collect.rone_office import parse_rows, REGION_CLS_ID


def _rows():
    return json.load(open(ROOT / "tests" / "fixtures" / "rone_rows_sample.json"))


def test_region_cls_ids():
    assert REGION_CLS_ID == {"도심": 510003, "강남": 510004, "여의도마포": 510005}


def test_parse_rows_splits_levels():
    out = parse_rows([("rent_index", r) for r in _rows()])
    assert out["regions"]["서울"]["rent_index"] == [{"yq": "2026Q1", "value": 105.7524}]
    assert out["regions"]["도심"]["rent_index"][0]["value"] == 104.2
    assert out["regions"]["여의도마포"]["rent_index"][0]["value"] == 106.9
    assert out["sub_regions"]["서울>도심>광화문"]["rent_index"][0]["value"] == 103.1
    # 다른 시도·기타 권역은 섞이지 않는다
    assert "부산" not in out["regions"]


def test_parse_rows_yield_triplet():
    rows = [("yield", {"CLS_ID": 510004, "CLS_FULLNM": "서울>강남", "ITM_NM": itm,
                       "DTA_VAL": v, "WRTTIME_IDTFR_ID": "202601"})
            for itm, v in (("소득수익률", 0.9), ("자본수익률", 1.4), ("투자수익률", 2.3))]
    out = parse_rows(rows)
    assert out["regions"]["강남"]["yield"] == [
        {"yq": "2026Q1", "income": 0.9, "capital": 1.4, "total": 2.3}]


def _vac(cls_id, fullnm, value, wrttime="202601"):
    return ("vacancy", {"CLS_ID": cls_id, "CLS_FULLNM": fullnm, "ITM_NM": "공실률",
                        "DTA_VAL": value, "WRTTIME_IDTFR_ID": wrttime})


def test_parse_rows_drops_etc_region_and_other_sido():
    # '서울>기타'(510006)와 그 하위 상권, 서울 외 시도는 권역·하위 상권 어디에도 남지 않는다
    out = parse_rows([_vac(510006, "서울>기타", 9.9),
                      _vac(520099, "서울>기타>목동", 8.8),
                      _vac(530001, "부산>도심", 7.7),
                      _vac(530002, "부산>도심>서면", 6.6)])
    assert out == {"regions": {}, "sub_regions": {}}


def test_parse_rows_stitch_prefers_later_table():
    # 기간표를 이어붙일 때 같은 분기가 겹치면 뒤에 온 표(더 최근 개정)의 값을 쓴다
    out = parse_rows([_vac(510003, "서울>도심", 5.0, "202402"),
                      _vac(510003, "서울>도심", 5.5, "202402")])
    assert out["regions"]["도심"]["vacancy"] == [{"yq": "2024Q2", "value": 5.5}]


def test_fetch_table_refuses_truncated_pagination(tmp_path, monkeypatch):
    # 2페이지째가 조용히 비면 절단본이 캐시에 영구 박제된다 — 실패시키고 캐시를 남기지 않는다
    def fake_get_page(statbl_id, page):
        if page == 1:
            return 2000, [dict(_vac(510003, "서울>도심", 5.0)[1]) for _ in range(1000)]
        return 0, []  # RESULT-only(INFO-200) 응답

    monkeypatch.setattr(rone_office, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rone_office, "_get_page", fake_get_page)
    with pytest.raises(RuntimeError, match="절단"):
        rone_office._fetch_table("TT_TRUNCATED")
    assert not (tmp_path / "TT_TRUNCATED.json").exists()
