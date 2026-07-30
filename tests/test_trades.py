import json

from src.collect.common import ROOT
from src.collect.trades import (build_trades, build_year_conflicts, jibun_match, match_building,
                                month_range, parse_items)


def _xml():
    return (ROOT / "tests" / "fixtures" / "nrg_item_sample.xml").read_text()


def test_parse_items_units_and_cancel():
    rows = parse_items(_xml())
    office = [r for r in rows if r["use"] == "업무"]
    assert office and office[0]["amount_won"] == 33_200_000_000   # 만원×콤마 → 원
    assert office[0]["deal_ymd"].count("-") == 2
    assert any(r["canceled"] for r in rows)                        # 해제 행은 보존 + 플래그
    assert all(r["per_m2_won"] > 0 for r in rows if not r["canceled"])


def test_jibun_match_masking():
    assert jibun_match("7*", "737")
    assert jibun_match("737", "737")
    assert not jibun_match("7*", "60-1")
    assert not jibun_match("8*", "737")
    assert jibun_match("60*", "60-1")


def test_match_building_same_umd_only():
    seeds = [{"id": "gfc", "umd": "역삼동", "jibun": "737", "sgg_cd": "11680"}]
    row = {"umd": "역삼동", "jibun_masked": "7*", "sgg_cd": "11680"}
    assert match_building(row, seeds)["building_id"] == "gfc"
    assert match_building({**row, "umd": "삼성동"}, seeds) is None


# ── 위 3개는 브리프 축자. 아래는 선행 태스크에서 확정된 함정을 못박는 테스트 ──────────

def test_match_kind_needs_ledger():
    """buildings.json이 있어도 ledger가 null인 제3상태가 있다 — 그때는 jibun_only다.

    대장 API 활용신청이 아직 승인되지 않아 55동 전 행의 ledger가 null이다.
    r["ledger"]["totArea"] 를 직접 짚으면 TypeError로 죽는다.
    """
    row = {"umd": "역삼동", "jibun_masked": "7*", "sgg_cd": "11680", "building_ar_m2": 1807.24}
    no_ledger = [{"id": "gfc", "umd": "역삼동", "jibun": "737", "sgg_cd": "11680", "ledger": None}]
    m = match_building(row, no_ledger)
    assert m["kind"] == "jibun_only" and m["area_ratio"] is None

    filled = [{**no_ledger[0], "ledger": {"totArea": 213822.0}}]
    m = match_building(row, filled)
    assert m["kind"] == "partial" and round(m["area_ratio"], 5) == round(1807.24 / 213822.0, 5)

    whole = [{**no_ledger[0], "ledger": {"totArea": 2000.0}}]
    assert match_building(row, whole)["kind"] == "whole"      # 1807.24/2000 = 0.90 ≥ 0.8


def test_match_building_records_ambiguity():
    """마스킹된 지번은 한 동을 가리킨다는 보장이 없다 — 후보가 여럿이면 남긴다."""
    seeds = [{"id": "a", "umd": "역삼동", "jibun": "737", "sgg_cd": "11680"},
             {"id": "b", "umd": "역삼동", "jibun": "790", "sgg_cd": "11680"}]
    m = match_building({"umd": "역삼동", "jibun_masked": "7*", "sgg_cd": "11680"}, seeds)
    assert m["candidates"] == ["a", "b"] and m["masked"] is True
    exact = match_building({"umd": "역삼동", "jibun_masked": "737", "sgg_cd": "11680"}, seeds)
    assert exact["building_id"] == "a" and exact["candidates"] == ["a"] and exact["masked"] is False


def test_build_trades_keeps_office_only_and_gates_price():
    seeds = [{"id": "x", "umd": "논현동", "jibun": "70", "sgg_cd": "11680", "ledger": None}]
    rows = parse_items(_xml())
    trades, excl = build_trades(rows, seeds)
    assert {r["use"] for r in trades} == {"업무"}                 # 근생은 raw 캐시에만 남는다
    assert sum(1 for r in trades if r["canceled"]) == 1           # 해제 업무 행도 보존
    assert trades[0]["match"]["building_id"] == "x"
    assert excl == {"price_gate": 0, "parse": 0}

    cheap = dict(rows[0], per_m2_won=100_000)                     # ㎡당 10만 원 = 게이트 하한 밖
    huge = dict(rows[0], per_m2_won=300_000_000)
    broken = dict(rows[0], parse_error="면적 없음", per_m2_won=0)
    trades, excl = build_trades([cheap, huge, broken], seeds)
    assert trades == [] and excl == {"price_gate": 2, "parse": 1}


def test_build_year_conflicts_flags_rebuilt_sites():
    """한 지번에 시대가 다른 건물이 차례로 선 자리(재건축)를 신고하는가.

    콘코디언(신문로1가)은 옛 사옥을 헐고 2018년에 다시 지었다. 지번이 같아 2008년 거래가
    그대로 붙는다 — 매칭이 필지 정체성일 뿐이라는 사실을 데이터가 스스로 신고해야 한다.
    """
    rows = [{"build_year": 1980, "match": {"building_id": "concordian"}},
            {"build_year": 2018, "match": {"building_id": "concordian"}},
            {"build_year": 2010, "match": {"building_id": "centropolis"}},
            {"build_year": None, "match": {"building_id": "centropolis"}},
            {"build_year": 1999, "match": None}]
    assert build_year_conflicts(rows) == {"concordian": [1980, 2018]}


def test_stale_progress_file_does_not_fake_completion(tmp_path, monkeypatch):
    """진행 파일이 '다 받았다'고 해도 raw 캐시가 없으면 완료로 치지 않는다.

    raw 캐시(data/raw/trades)는 용량 때문에 커밋하지 않고 진행 파일은 커밋한다. 저장소를 새로
    clone한 뒤 수집기를 돌렸을 때 진행 파일을 믿어 버리면 한 건도 받지 않고 **빈 trades.json으로
    기존 산출을 덮어쓴다.** 판단 근거는 언제나 디스크에 실제로 있는 캐시여야 한다.
    """
    from src.collect import trades as T
    monkeypatch.setattr(T, "RAW_DIR", tmp_path / "raw")       # 비어 있는 캐시
    monkeypatch.setattr(T, "OUT_PATH", tmp_path / "trades.json")
    monkeypatch.setattr(T, "PROG_PATH", tmp_path / "progress.json")
    monkeypatch.setattr(T, "SGG_LIST", ["11680"])
    monkeypatch.setattr(T, "month_range", lambda *a, **k: ["202406"])
    (tmp_path / "progress.json").write_text('{"done": ["11680_202406"]}')

    result = T.collect(rebuild=True)          # rebuild는 네트워크를 쓰지 않는다
    assert result["meta"]["cells_done"] == 0 and result["meta"]["complete"] is False
    assert json.loads((tmp_path / "progress.json").read_text())["done"] == []


def test_month_range_covers_2006_to_now():
    months = month_range("200601", "202607")
    assert months[0] == "200601" and months[-1] == "202607"
    assert len(months) == 20 * 12 + 7 and months == sorted(months)
    assert "200613" not in months
