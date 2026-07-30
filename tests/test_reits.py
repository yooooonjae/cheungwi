import json

import pytest

from src.collect import reits
from src.collect.common import ROOT
from src.collect.reits import dividends, fin_series, pick_revenue


def _fixture(name):
    return json.load(open(ROOT / "tests" / "fixtures" / name, encoding="utf-8"))


def _stub_fetch(monkeypatch, payload, at):
    """_fetch 를 (연도, 보고서) 한 칸에서만 payload 를 돌려주는 가짜로 바꾼다.

    at 이 걸리지 않는 칸은 None — DART 의 "013"(자료 없음)과 같은 모양이라 수집기가
    빈 칸을 어떻게 다루는지까지 그대로 시험할 수 있다.
    """
    def fake(corp, op, year, reprt, rebuild=False):
        return payload if (year, reprt) == at else None
    monkeypatch.setattr(reits, "_fetch", fake)


def test_seed_reits_refers_valid_buildings():
    seeds = json.load(open(ROOT / "data" / "seed_reits.json"))["reits"]
    assert 8 <= len(seeds) <= 15
    bids = {b["id"] for b in json.load(open(ROOT / "data" / "seed_buildings.json"))["buildings"]}
    for t, r in seeds.items():
        assert t.isalnum() and r["name"]
        for a in r["office_assets"]:
            assert a["building_id"] is None or a["building_id"] in bids


def test_pick_revenue_prefers_operating():
    rows = [{"account_nm": "자산총계", "fs_div": "OFS", "thstrm_amount": "1,000"},
            {"account_nm": "영업수익", "fs_div": "OFS", "thstrm_amount": "52,300,000,000"},
            {"account_nm": "영업수익", "fs_div": "CFS", "thstrm_amount": "99"}]
    assert pick_revenue(rows) == 52_300_000_000.0


def test_pick_revenue_none_when_absent():
    assert pick_revenue([{"account_nm": "자산총계", "fs_div": "OFS", "thstrm_amount": "1"}]) is None


def test_pick_revenue_falls_back_to_sales():
    """실측 경로다 — 주요계정 API 는 리츠 10종 모두 '영업수익'이 아니라 '매출액'으로 돌려준다.

    연결(CFS) 매출액이 먼저 와도 별도(OFS) 값을 집어야 한다. 순서에 기대지 않는지 함께 본다.
    """
    rows = [{"account_nm": "매출액", "fs_div": "CFS", "thstrm_amount": "85,330,922,743"},
            {"account_nm": "매출액", "fs_div": "OFS", "thstrm_amount": "37,238,582,035"}]
    assert pick_revenue(rows) == 37_238_582_035.0
    # 값이 '-'(결측)면 0.0 으로 뭉개지 않고 없는 것으로 둔다
    assert pick_revenue([{"account_nm": "매출액", "fs_div": "OFS", "thstrm_amount": "-"}]) is None


def test_dividends_keeps_common_stock_only(monkeypatch):
    """우선주·종류주 배당이 보통주 블록을 덮어쓰지 않아야 한다.

    stock_knd 실측 분포는 {'-': 1233, '보통주': 320, '우선주': 116, '종류주': 56}이다.
    "종류주"만 막는 블랙리스트로 두면 우선주 dps 가 그대로 통과해 같은 결산기의 보통주 배당을
    소리 없이 갈아치운다. 그래서 통과 목록은 ("보통주", "-") 화이트리스트여야 한다 —
    현금배당금총액은 stock_knd 가 "-"로 오므로 "-"를 빼면 total_div 가 통째로 사라진다.
    """
    _stub_fetch(monkeypatch, _fixture("dart_alot_matter_sample.json"), (2025, "11011"))
    blocks = dividends("01535150")

    assert [b["stlm_dt"] for b in blocks] == ["2025-03-31", "2025-09-30"]  # 결산기순 정렬
    first = blocks[0]
    assert first["dps"] == 68.0        # 보통주 68원 — 우선주 9,999·종류주 5,555 가 아니다
    assert first["yld"] == 1.19        # 우선주 7.77 이 아니다
    assert first["total_div"] == 20469.0  # stock_knd "-" 로 오는 총액이 살아 있다
    assert blocks[1] == {"stlm_dt": "2025-09-30", "total_div": 21000.0, "dps": 70.0, "yld": 1.22}
    # 결산기가 비어 있는 행(stlm_dt "")은 블록을 만들지 않는다
    assert all(b["stlm_dt"] for b in blocks)


def test_dividends_merges_same_settlement_across_years(monkeypatch):
    """여러 bsns_year 가 같은 결산기를 중복 보고해도 결산기 하나로 합쳐야 한다."""
    payload = _fixture("dart_alot_matter_sample.json")
    monkeypatch.setattr(reits, "_fetch",
                        lambda corp, op, year, reprt, rebuild=False:
                        payload if year in (2025, 2026) else None)
    assert [b["stlm_dt"] for b in dividends("01535150")] == ["2025-03-31", "2025-09-30"]


def test_fin_series_takes_separate_statements(monkeypatch):
    """별도(OFS) 재무상태표·손익을 집고, basis 는 자산총계 행의 기준일이어야 한다."""
    _stub_fetch(monkeypatch, _fixture("dart_fnltt_single_acnt_sample.json"), (2026, "11011"))
    rows, skipped = fin_series("01276594")

    assert skipped == 0 and len(rows) == 1
    assert rows[0] == {"year": 2026, "reprt": "11011",
                       "assets": 1_314_610_219_598.0,   # 연결 3,131,675,302,293 이 아니다
                       "liab": 603_569_310_216.0,
                       "equity": 711_040_909_382.0,
                       "revenue": 37_238_582_035.0,     # 연결 85,330,922,743 이 아니다
                       "basis": "2026.03.31 현재"}


def test_fin_series_drops_rows_without_separate_figures(monkeypatch):
    """연결만 담긴 응답은 행으로 남기지 않고 버린 수를 센다 — 0.0 으로 채워 넣지 않는다."""
    payload = _fixture("dart_fnltt_single_acnt_sample.json")
    payload["list"] = [i for i in payload["list"] if i["fs_div"] == "CFS"]
    _stub_fetch(monkeypatch, payload, (2026, "11011"))

    rows, skipped = fin_series("01276594")
    assert rows == [] and skipped == 1


def test_reits_output_schema():
    """산출 data/reits.json 의 계약 — 소비자가 기대는 필드와 값 범위."""
    path = ROOT / "data" / "reits.json"
    if not path.exists():
        pytest.skip("data/reits.json 이 없다 (python3 src/collect/reits.py 로 만든다)")
    doc = json.load(open(path, encoding="utf-8"))
    bids = {b["id"] for b in json.load(open(ROOT / "data" / "seed_buildings.json"))["buildings"]}
    meta = doc["meta"]
    assert meta["source"] == "OpenDART" and meta["collected_at"]
    assert set(meta["holdings"]) == {"direct", "indirect", "mixed"}

    fin_rows = div_rows = links = 0
    for ticker, reit in doc["reits"].items():
        assert ticker.isalnum() and reit["name"]
        assert len(reit["corp_code"]) == 8 and reit["corp_code"].isdigit()
        # 재간접 여부는 note 산문이 아니라 이 필드로 읽는다(캘리브레이션 가중치의 근거)
        assert reit["holding"] in ("direct", "indirect", "mixed")
        assert reit["office_assets"]
        for asset in reit["office_assets"]:
            assert asset["building_id"] is None or asset["building_id"] in bids
            assert asset["note"]
            links += bool(asset["building_id"])
        for row in reit["fin"]:
            assert set(row) == {"year", "reprt", "assets", "liab", "equity", "revenue", "basis"}
            assert 2020 <= row["year"] <= meta["years"][1]
            assert row["reprt"] in meta["reprt_codes"]
            assert row["assets"] is None or row["assets"] > 0
            assert row["revenue"] is None or row["revenue"] >= 0
            fin_rows += 1
        for block in reit["div"]:
            assert block["stlm_dt"]
            assert "dps" in block or "total_div" in block
            div_rows += 1

    assert meta["reits_count"] == len(doc["reits"])
    assert (meta["fin_rows"], meta["div_rows"], meta["building_links"]) == (
        fin_rows, div_rows, links)
    assert meta["fin_rows_with_revenue"] <= meta["fin_rows"]
