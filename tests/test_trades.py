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


def test_match_building_refuses_to_pick_when_ambiguous():
    """후보가 여럿이면 고르지 않는다 — building_id는 null이고 후보만 남는다.

    시드 파일 순서의 첫 후보를 돌려주면 서초동 '1***' 1,688행이 통째로 한 동에 붙어,
    소비자가 building_id로 groupby만 해도 오답이 나온다. 고를 수 없으면 고르지 않는다.
    """
    seeds = [{"id": "a", "umd": "역삼동", "jibun": "737", "sgg_cd": "11680"},
             {"id": "b", "umd": "역삼동", "jibun": "790", "sgg_cd": "11680"}]
    m = match_building({"umd": "역삼동", "jibun_masked": "7*", "sgg_cd": "11680"}, seeds)
    assert m["building_id"] is None                       # ← 첫 후보 'a'를 고르지 않는다
    assert m["candidates"] == ["a", "b"] and m["masked"] is True
    assert m["kind"] == "jibun_only" and m["area_ratio"] is None

    exact = match_building({"umd": "역삼동", "jibun_masked": "737", "sgg_cd": "11680"}, seeds)
    assert exact["building_id"] == "a" and exact["candidates"] == ["a"] and exact["masked"] is False
    # 마스킹돼 있어도 그 법정동에 후보가 하나뿐이면 특정된 것으로 본다.
    one = match_building({"umd": "역삼동", "jibun_masked": "79*", "sgg_cd": "11680"}, seeds)
    assert one["building_id"] == "b" and one["masked"] is True


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


def test_build_year_conflicts_flags_contaminated_matches():
    """한 시드에 붙은 거래의 건축년도가 갈리면 매칭이 오염된 것이다 — 세어서 신고한다.

    다른 건물을 끌어왔거나(마스킹 지번) 그 자리를 헐고 다시 지었거나 둘 중 하나다.
    동을 특정하지 못한 행(building_id=null)은 어느 시드의 것도 아니므로 세지 않는다.
    """
    rows = [{"build_year": 1980, "match": {"building_id": "concordian"}},
            {"build_year": 2018, "match": {"building_id": "concordian"}},
            {"build_year": 2010, "match": {"building_id": "centropolis"}},
            {"build_year": None, "match": {"building_id": "centropolis"}},
            {"build_year": 1975, "match": {"building_id": None, "candidates": ["a", "b"]}},
            {"build_year": 2020, "match": {"building_id": None, "candidates": ["a", "b"]}},
            {"build_year": 1999, "match": None}]
    assert build_year_conflicts(rows) == {"concordian": [1980, 2018]}


QUOTA_ENVELOPE = ("<OpenAPI_ServiceResponse><cmmMsgHeader>"
                  "<returnReasonCode>22</returnReasonCode>"
                  "<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
                  "</cmmMsgHeader></OpenAPI_ServiceResponse>")


def _isolate(T, tmp_path, monkeypatch, months=("202406",)):
    """수집기의 모든 입출력 경로를 tmp로 돌린다. raw 캐시는 비어 있는 채로 둔다(= 새 clone)."""
    monkeypatch.setattr(T, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(T, "SUJI_RAW", tmp_path / "suji")       # 남의 캐시도 없다
    monkeypatch.setattr(T, "OUT_PATH", tmp_path / "trades.json")
    monkeypatch.setattr(T, "PARTIAL_PATH", tmp_path / "trades.partial.json")
    monkeypatch.setattr(T, "PROG_PATH", tmp_path / "progress.json")
    monkeypatch.setattr(T, "SGG_LIST", ["11680"])
    monkeypatch.setattr(T, "month_range", lambda *a, **k: list(months))


def test_partial_run_does_not_overwrite_complete_output(tmp_path, monkeypatch):
    """부분 수집이 완성된 산출을 덮어쓰지 않는다 — 기존 trades.json이 살아남아야 한다.

    raw 캐시는 커밋하지 않고 산출 JSON만 커밋하므로, 새로 clone한 곳의 캐시는 비어 있는 게
    정상이다. 거기서 `make collect`를 돌리면 첫 실행은 쿼터·시간 때문에 반드시 일부만 받는다.
    그때 1,235셀짜리 산출을 0셀로 덮어쓰면 커밋된 데이터가 조용히 사라진다.
    """
    from src.collect import trades as T
    _isolate(T, tmp_path, monkeypatch)
    complete = {"trades": [{"deal_ymd": "2024-06-19", "amount_won": 1}],
                "meta": {"cells_done": 1235, "n_office": 14521}}
    (tmp_path / "trades.json").write_text(json.dumps(complete, ensure_ascii=False))
    (tmp_path / "progress.json").write_text('{"done": ["11680_202406"]}')

    result = T.collect(rebuild=True)          # rebuild는 네트워크를 쓰지 않는다
    assert result["meta"]["cells_done"] == 0 and result["meta"]["complete"] is False

    survived = json.loads((tmp_path / "trades.json").read_text())
    assert survived == complete               # ← 기존 산출은 한 글자도 바뀌지 않았다
    partial = json.loads((tmp_path / "trades.partial.json").read_text())
    assert partial["trades"] == [] and partial["meta"]["written_to"] == "trades.partial.json"
    assert "덮어쓰지 않았다" in partial["meta"]["partial_write_reason"]
    # 진행 파일도 줄어들지 않는다(캐시가 진실이므로 이어받기는 이 파일에 기대지 않는다).
    assert json.loads((tmp_path / "progress.json").read_text())["done"] == ["11680_202406"]


def test_quota_envelope_on_non_200_stops_immediately(tmp_path, monkeypatch):
    """쿼터 봉투가 429·5xx에 실려 와도 쿼터로 읽고, 한 셀에서 즉시 멈춘다.

    상태 코드부터 갈라 '일시 오류'로 분류하면 남은 1,200셀을 백오프까지 곁들여 계속 두드려
    다음 날 쿼터까지 태운다(G2B 실사고). 저장하고 RESUME_NEEDED로 끝나는 게 규약이다.
    """
    from src.collect import trades as T
    _isolate(T, tmp_path, monkeypatch, months=("202406", "202405", "202404"))
    monkeypatch.setattr(T, "load_config", lambda: {"service_key": "X"})
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    seen = []

    def fake_api_get(url, params, **kw):
        seen.append(params["DEAL_YMD"])
        return 429, QUOTA_ENVELOPE            # 비-200 + 봉투
    monkeypatch.setattr(T, "api_get", fake_api_get)

    result = T.collect()
    assert len(seen) == 1                     # 서킷브레이커: 남은 두 셀은 두드리지 않았다
    assert result["meta"]["stopped"] == "quota" and result["meta"]["complete"] is False
    assert result["meta"]["written_to"] == "trades.partial.json"
    assert (tmp_path / "trades.partial.json").exists()


def test_month_range_covers_2006_to_now():
    months = month_range("200601", "202607")
    assert months[0] == "200601" and months[-1] == "202607"
    assert len(months) == 20 * 12 + 7 and months == sorted(months)
    assert "200613" not in months
