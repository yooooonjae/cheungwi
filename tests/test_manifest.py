import copy
import datetime
import json

import pytest

from src.build.manifest import (
    _fmt_month, _quarter_end_month, _scan_months, _to_ym, build_manifest,
)


def test_manifest_covers_all_sources():
    m = build_manifest(write=False)
    keys = {s["key"] for s in m["sources"]}
    assert keys == {"seed_buildings", "buildings", "trades", "rone_office", "reits", "rates"}
    for s in m["sources"]:
        assert s["observed_through"] and s["rows"] >= 1, s["key"]


def test_manifest_cutoff_is_month():
    m = build_manifest(write=False)
    assert len(m["data_cutoff"]) == 7 and m["data_cutoff"][4] == "-"   # "YYYY-MM"


# ── 순수 함수 ────────────────────────────────────────────────────────────────
def test_to_ym_parses_every_shape_and_rejects_the_rest():
    assert _to_ym("2026-07-23") == "202607"       # 실거래 계약일
    assert _to_ym("2026.05.31 현재") == "202605"  # 리츠 재무 기준일
    assert _to_ym("2026-06") == "202606"          # 금리 월
    assert _to_ym("202607") == "202607"
    assert _to_ym("2016Q3") is None               # 분기는 월 스캐너가 집으면 안 된다
    assert _to_ym("2026-13-01") is None           # 13월
    assert _to_ym(2026) is None
    assert _to_ym(None) is None


def test_quarter_end_month():
    assert _quarter_end_month("2026Q1") == "2026-03"
    assert _quarter_end_month("2025Q4") == "2025-12"
    assert _quarter_end_month(None) is None
    assert _fmt_month("202603") == "2026-03"


def test_scan_months_only_reads_the_keys_it_is_given():
    """키를 한정하지 않으면 수집일이 관측월을 밀어낸다 — 스캐너에 keys 인자가 있는 이유."""
    doc = {"rows": [{"basis": "2026.05.31 현재"}, {"basis": "2026.02.28 현재"}],
           "meta": {"collected_at": "2026-07-30"}}
    out = []
    _scan_months(doc, ("basis",), out)
    assert max(out) == "202605"
    loose = []
    _scan_months(doc, ("basis", "collected_at"), loose)
    assert max(loose) == "202607"   # 수집일까지 긁으면 이렇게 밀린다


# ── 합성 입력 ────────────────────────────────────────────────────────────────
TODAY = datetime.date(2026, 7, 30)

SYNTH = {
    "seed_buildings": {
        "buildings": [{"id": "a", "region": "CBD", "sgg_cd": "11140"},
                      {"id": "b", "region": "GBD", "sgg_cd": "11680"}],
        "meta": {"as_of": "2026-07-30"},
    },
    "buildings": {
        "buildings": [{"id": "a", "ledger": None, "vworld": {"lat": 1}},
                      {"id": "b", "ledger": {"area": 1}, "vworld": {"lat": 2}}],
        "meta": {"collected_at": "2026-07-30", "complete": False, "source": "건축HUB+VWorld"},
    },
    "trades": {
        "trades": [{"deal_ymd": "2026-07-23", "match": {"building_id": "a"}},
                   {"deal_ymd": "2006-01-02", "match": {"building_id": None}}],
        "meta": {"collected_at": "2026-07-30", "sgg_list": ["11140"], "complete": True,
                 "cells_done": 2, "cells_total": 2, "ledger_ready": False, "source": "RTMS"},
    },
    "rone_office": {
        "regions": {"도심": {"rent_index": [{"yq": "2025Q4", "value": 1},
                                            {"yq": "2026Q1", "value": 2}]}},
        "sub_regions": {"서울>도심>광화문": {"rent_index": [{"yq": "2025Q4", "value": 1},
                                                        {"yq": "2026Q1", "value": 2}]},
                        "서울>도심>남대문": {"rent_index": [{"yq": "2025Q4", "value": 1}]}},
        "meta": {"collected_at": "2026-07-30", "source": "R-ONE"},
    },
    "reits": {
        "reits": {"X": {"name": "가리츠", "holding": "direct",
                        "fin": [{"basis": "2026.05.31 현재", "revenue": 10}],
                        "div": [{"stlm_dt": "2026-05-31"}]}},
        "meta": {"collected_at": "2026-07-30", "years": [2020, 2026], "source": "OpenDART"},
    },
    "rates": {
        "treasury10y": [{"ym": "2026-05", "value": 1}, {"ym": "2026-06", "value": 2}],
        "cd91": [{"ym": "2026-05", "value": 1}, {"ym": "2026-06", "value": 2}],
        "meta": {"collected_at": "2026-07-30", "source": "ECOS",
                 "stat_codes": {"treasury10y": ["721Y001"], "cd91": ["721Y001"]}},
    },
}


def _write(tmp_path, **patch):
    """합성 산출 6종을 디렉터리에 쓰고 그 경로를 돌려준다. patch 로 원천을 갈아 끼운다."""
    for key, doc in SYNTH.items():
        d = patch.get(key, copy.deepcopy(doc))
        (tmp_path / f"{key}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _by_key(m, key):
    return next(s for s in m["sources"] if s["key"] == key)


def test_reits_observed_month_comes_from_basis_not_collected_at(tmp_path):
    """리츠 관측월은 재무 기준일 2026-05다. 수집일 2026-07이 새면 원장이 두 달을 부풀린다."""
    m = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path))
    reits = _by_key(m, "reits")
    assert reits["observed_through"] == "2026-05"
    assert reits["collected_at"] == "2026-07-30"


def test_cutoff_takes_latest_completed_month_of_time_axis_sources(tmp_path):
    m = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path))
    # 시점축 원천: trades 2026-07(수집 당월·미완결)·rone 2026-03·reits 2026-05·rates 2026-06
    assert m["data_cutoff"] == "2026-06"
    assert _by_key(m, "trades")["observed_through"] == "2026-07"   # 관측월 자체는 그대로 적는다
    assert [s["key"] for s in m["sources"] if not s["time_axis"]] == ["seed_buildings", "buildings"]


def test_cutoff_does_not_advance_when_only_the_month_rolls_over(tmp_path):
    """재수집 없이 8월이 되어도 기준월은 2026-06이다. 여기서 뛰면 없는 데이터를 내걸게 된다."""
    d = _write(tmp_path)
    before = build_manifest(write=False, today=TODAY, data_dir=d)["data_cutoff"]
    after = build_manifest(write=False, today=datetime.date(2026, 8, 1), data_dir=d)["data_cutoff"]
    assert before == after == "2026-06"


def test_cutoff_advances_after_a_real_recollection(tmp_path):
    """8월에 다시 받아 7월 거래가 완결되면 그때는 기준월이 2026-07로 간다."""
    trades = copy.deepcopy(SYNTH["trades"])
    trades["meta"]["collected_at"] = "2026-08-03"
    m = build_manifest(write=False, today=datetime.date(2026, 8, 3),
                       data_dir=_write(tmp_path, trades=trades))
    assert m["data_cutoff"] == "2026-07"


def test_empty_source_stops_the_manifest(tmp_path):
    rates = copy.deepcopy(SYNTH["rates"])
    rates["treasury10y"], rates["cd91"] = [], []
    with pytest.raises(RuntimeError, match="rates"):
        build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path, rates=rates))


def test_no_completed_month_stops_the_manifest(tmp_path):
    """시점축 원천이 전부 수집 당월만 보고 있으면 기준월을 지어내지 않고 실패한다."""
    patch = {k: copy.deepcopy(SYNTH[k]) for k in ("rone_office", "reits", "rates")}
    patch["rone_office"]["regions"]["도심"]["rent_index"] = [{"yq": "2026Q3", "value": 1}]
    patch["rone_office"]["sub_regions"] = {}
    patch["reits"]["reits"]["X"]["fin"] = [{"basis": "2026.07.31 현재", "revenue": 1}]
    patch["rates"]["treasury10y"] = [{"ym": "2026-07", "value": 1}]
    patch["rates"]["cd91"] = [{"ym": "2026-07", "value": 1}]
    with pytest.raises(RuntimeError, match="완결된 관측월"):
        build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path, **patch))


def test_missing_output_is_named(tmp_path):
    _write(tmp_path)
    (tmp_path / "reits.json").unlink()
    with pytest.raises(FileNotFoundError, match="reits.json"):
        build_manifest(write=False, today=TODAY, data_dir=tmp_path)


def test_rates_coverage_shows_series_with_different_latest_month(tmp_path):
    """한 계열만 먼저 갱신되면 관측월은 최댓값이 되므로, 뒤처진 계열을 커버리지가 밝힌다."""
    rates = copy.deepcopy(SYNTH["rates"])
    rates["cd91"] = [{"ym": "2026-05", "value": 1}]
    m = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path, rates=rates))
    cov = _by_key(m, "rates")["coverage"]
    assert "계열별 최신월 상이" in cov and "CD91일 2026-05" in cov and "그 외 2026-06" in cov
    assert _by_key(m, "rates")["observed_through"] == "2026-06"
    # 계열이 갈리지 않으면 그 문구는 나오지 않는다
    clean = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path))
    assert "계열별 최신월 상이" not in _by_key(clean, "rates")["coverage"]


def test_rates_series_come_from_stat_codes_not_from_leftover_keys(tmp_path):
    """상위 키가 하나 늘어도 계열 수·행수는 그대로여야 한다."""
    rates = copy.deepcopy(SYNTH["rates"])
    rates["memo"] = [{"ym": "2026-07", "value": 99}]   # 계열이 아닌 새 키
    m = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path, rates=rates))
    s = _by_key(m, "rates")
    assert s["rows"] == 4 and "2계열" in s["coverage"] and s["observed_through"] == "2026-06"


def test_rone_coverage_separates_surviving_sub_regions_from_dead_keys(tmp_path):
    """최신 분기까지 살아 있는 상권만 '곳'으로 세고, 끊긴 키는 키 수로만 남긴다."""
    m = build_manifest(write=False, today=TODAY, data_dir=_write(tmp_path))
    cov = _by_key(m, "rone_office")["coverage"]
    assert "2026Q1 기준 1곳" in cov and "끊긴 키 포함 2키" in cov and "3/4점" in cov


def test_real_manifest_reports_the_known_gaps():
    """실산출 기준: 대장 미개통과 실거래 매칭의 후보 다수가 그대로 드러나야 한다."""
    m = build_manifest(write=False)
    assert "대장 0/55" in _by_key(m, "buildings")["coverage"]
    assert "후보 다수" in _by_key(m, "trades")["coverage"]
