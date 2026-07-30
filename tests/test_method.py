"""방법론 — 원장·추정·매칭·점검표의 렌더 모델 검사.

`tests/test_time.py` 와 같은 왕복 규약이다(node 한 프로세스, DOM 없음). 이 페이지는
그림이 거의 없고 대부분이 **인용**이라, 검사가 붙드는 것도 좌표가 아니라 인용의
정확성이다.

① **원장은 스스로를 센다.** 여섯 원천의 관측월·수집일·단위·캐시 정책이 화면에
   원문으로 오는지, 그리고 원장이 적어 둔 `source_count` 와 실린 원천의 수가
   어긋나면 조용히 다섯 줄만 그리지 않고 멈추는지.

② **추정은 다시 계산해서 데이터에 착지한다.** 유효임대료 사다리(명목 → 렌트프리
   가정 → 유효)의 마지막 칸이 `out/market.json` 의 값과 같아야 한다. 지면이 제
   숫자를 따로 들고 있으면 언젠가 데이터와 갈라진다.

③ **매칭 한계는 새 숫자가 아니라 재게시다.** Ⅰ장의 배타 사다리를 **같은 함수**로
   다시 그린다 — 두 장이 서로 다른 그림으로 같은 사실을 말하기 시작하면 그중
   하나는 반드시 틀린다.

④ **빈 리스트는 무죄 증명이 아니다.** 0건인 목록에는 "검증됨으로 읽지 말 것"이
   반드시 함께 실려야 하고, 한 줄이라도 생기면 그 문장은 사라지고 사유 원문이
   그 자리에 온다.
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = str(Path(__file__).resolve().parent / "charts_runner.js")
NODE = shutil.which("node")


def js(mod, fn, *args):
    if NODE is None:
        raise RuntimeError(
            "node 를 찾을 수 없다 — 방법론 검사는 건너뛰지 않는다. 정직성 표기를 "
            "아무도 읽어 보지 않은 채 통과하는 편이 훨씬 나쁘다")
    spec = [{"mod": mod, "fn": fn, "args": list(args)}]
    proc = subprocess.run([NODE, RUNNER], input=json.dumps(spec),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("방법론 러너 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)[0]


def value(mod, fn, *args):
    r = js(mod, fn, *args)
    assert r["ok"], "%s.%s 가 던졌다: %s" % (mod, fn, r.get("message"))
    return r["value"]


MANIFEST = json.loads((ROOT / "data" / "DATA_MANIFEST.json").read_text(encoding="utf-8"))
MARKET = json.loads((ROOT / "out" / "market.json").read_text(encoding="utf-8"))
UNDERWRITING = json.loads((ROOT / "out" / "underwriting.json").read_text(encoding="utf-8"))
TRADES = json.loads((ROOT / "out" / "trades_analysis.json").read_text(encoding="utf-8"))
DATA = {"manifest": MANIFEST, "market": MARKET,
        "underwriting": UNDERWRITING, "trades": TRADES}

WIDE = {"compact": False}


def test_node_is_present_because_the_quotations_are_never_skipped():
    assert NODE is not None


# ================================================================== #
# ① 원장 — 여섯 원천
# ================================================================== #
def test_the_ledger_lists_every_source_in_the_manifest_order():
    rows = value("method", "manifestRows", MANIFEST)
    assert len(rows) == MANIFEST["source_count"] == 6
    assert [r["key"] for r in rows] == [s["key"] for s in MANIFEST["sources"]]
    for row, src in zip(rows, MANIFEST["sources"]):
        assert row["dataset"] == src["dataset"]
        assert row["institution"] == src["institution"]
        assert row["observed"] == src["observed_through"]
        assert row["collected"] == src["collected_at"]
        assert row["rows"] == src["rows"]


def test_the_unit_column_quotes_the_manifest_and_never_invents_one():
    """단위는 원장의 `units` 가 단일 출처다(핸드오프 계약).

    천원/㎡ 와 백만원이 섞여 있는 것이 이 데이터의 사실이라, 지면이 그것을 "원"
    하나로 정리해 버리면 계약이 화면에서 사라진다.
    """
    rows = value("method", "manifestRows", MANIFEST)
    for row, src in zip(rows, MANIFEST["sources"]):
        assert row["units"] == src["units"]
    html = value("method", "manifestTable", MANIFEST)
    assert "천원/㎡" in html, "R-ONE 의 천원 단위가 표에 없다"
    assert "백만원" in html, "리츠 total_div 의 백만원이 표에 없다"


def test_a_source_without_a_unit_shows_a_dash_not_a_blank():
    """단위가 없는 원천(시드)은 빈칸이 아니라 줄표다 — 빈칸은 누락으로 읽힌다."""
    seed = [r for r in value("method", "manifestRows", MANIFEST)
            if r["key"] == "seed_buildings"][0]
    assert seed["units"] == "-"
    assert seed["unitsText"] == "―"


def test_a_manifest_that_miscounts_its_own_sources_stops_the_page():
    """원장이 적어 둔 수와 실린 수가 어긋나면 다섯 줄만 조용히 그리지 않는다."""
    broken = copy.deepcopy(MANIFEST)
    broken["source_count"] = 5
    r = js("method", "manifestRows", broken)
    assert r["ok"] is False and r["error"] == "gate", r


def test_the_page_refuses_to_draw_a_ledger_it_was_not_given():
    r = js("method", "manifestRows", None)
    assert r["ok"] is False and r["error"] == "input", r


def test_the_cache_policy_rides_along_because_a_frozen_quarter_is_a_limit():
    """R-ONE 캐시는 무효화가 없다 — 여기 실린 분기가 곧 데이터층의 한계다."""
    rows = value("method", "manifestRows", MANIFEST)
    rone = [r for r in rows if r["key"] == "rone_office"][0]
    assert rone["cache"] == MANIFEST["sources"][3]["cache"]
    assert "무효화가 없다" in rone["cache"]
    html = value("method", "manifestTable", MANIFEST)
    assert "무효화가 없다" in html, "캐시 정책이 표 밖으로 밀려났다"


def test_the_observation_months_do_not_agree_and_the_page_says_so():
    """관측월이 하나가 아니다 — R-ONE 은 2026-03, 금리는 2026-06 이다."""
    rows = value("method", "manifestRows", MANIFEST)
    observed = {r["observed"] for r in rows}
    assert len(observed) > 1
    lines = value("method", "manifestLines", MANIFEST)
    joined = " ".join(lines)
    assert "관측월" in joined and "수집일" in joined
    assert any(r["observed"] in joined for r in rows)


# ================================================================== #
# ② 추정 — 관측에서 추정까지의 사다리
# ================================================================== #
def test_the_estimate_ladder_recomputes_and_lands_exactly_on_the_data():
    """지면이 제 숫자를 따로 들고 있으면 언젠가 데이터와 갈라진다."""
    steps = value("method", "estimationSteps", MARKET, "도심")
    cbd = MARKET["regions"]["도심"]
    assert [s["kind"] for s in steps] == ["관측", "가정", "추정", "가정"]
    assert steps[0]["value"] == pytest.approx(cbd["nominal_rent_won_m2_mo"])
    assert steps[1]["value"] == pytest.approx(cbd["rent_free_mo"])
    assert steps[2]["value"] == pytest.approx(cbd["effective_rent_won_m2_mo"])
    # 마지막 칸은 앞의 두 칸에서 나온다 — 지면이 그 산술을 실제로 한다
    assert steps[2]["value"] == pytest.approx(
        cbd["nominal_rent_won_m2_mo"] * (12 - cbd["rent_free_mo"]) / 12)


def test_the_rent_free_assumption_carries_its_source_and_caveat_verbatim():
    steps = value("method", "estimationSteps", MARKET, "도심")
    meta = MARKET["regions"]["도심"]["rent_free_meta"]
    assumption = steps[1]
    assert assumption["source"] == meta["source"]
    assert assumption["caveat"] == meta["caveat"]
    html = value("method", "estimationHtml", MARKET, "도심")
    assert meta["source"] in html, "가정의 출처가 화면 글자로 없다"


def test_the_building_adjustment_is_named_as_the_fourth_rung():
    """건물 보정(연식·규모·역세권)은 관측이 아니라 곱해 얹은 가정이다."""
    steps = value("method", "estimationSteps", MARKET, "도심")
    assert steps[3]["kind"] == "가정"
    assert "역세권" in steps[3]["note"] and "상관" in steps[3]["note"]


def test_an_unknown_region_is_an_input_error_not_a_silent_zero():
    r = js("method", "estimationSteps", MARKET, "판교")
    assert r["ok"] is False and r["error"] == "input", r


# ================================================================== #
# ③ 매칭 — 배타 사다리 재게시
# ================================================================== #
def test_the_matching_section_republishes_the_very_same_ladder():
    """Ⅰ장과 방법론이 서로 다른 그림으로 같은 사실을 말하면 하나는 틀린다."""
    here = value("method", "matchingPlate", TRADES, WIDE)
    there = value("chapter1", "ladderPlate",
                  value("chapter1", "tradesModel", TRADES), WIDE)
    assert here == there


def test_only_fifty_seven_rows_reach_the_parcel_and_the_page_says_only():
    m = value("method", "matchingModel", TRADES)
    lad = TRADES["matching"]["ladder_exclusive"]
    assert m["exact"] == lad["exact"] == 57
    assert m["resolvedOnly"] == lad["resolved_only"]
    assert m["ambiguous"] == lad["ambiguous"]
    assert m["exact"] + m["resolvedOnly"] + m["ambiguous"] == m["total"] == lad["sum"]
    joined = " ".join(value("method", "matchingLines", TRADES))
    assert "57" in joined and "필지" in joined
    assert "부분집합" in joined or "더하면" in joined, "겹침 계약이 사라졌다"


def test_the_matching_lines_keep_the_canceled_rows_visible():
    """해제 2건 때문에 사다리의 57 과 산점의 55 가 다르다 — 그 차이를 적는다."""
    joined = " ".join(value("method", "matchingLines", TRADES))
    assert "해제" in joined and "55" in joined


# ================================================================== #
# ④ 점검표 — 비어 있는 목록
# ================================================================== #
CHECK_KEYS = ["gate_violations", "errors", "implausible_refi",
              "sub_regions_cap_skipped"]


def test_the_checklist_covers_the_four_lists_in_a_fixed_order():
    checks = value("method", "checkModel", DATA)
    assert [c["key"] for c in checks] == CHECK_KEYS


def test_an_empty_list_is_never_a_clean_bill_of_health():
    checks = value("method", "checkModel", DATA)
    empty = [c for c in checks if c["count"] == 0]
    assert len(empty) == 3, "오늘 실데이터에서 비어 있는 목록은 셋이다"
    note = value("method", "EMPTY_NOTE")
    assert "0건" in note and "검증됨으로 읽지 말 것" in note
    for c in empty:
        assert c["empty"] is True
        assert note in c["emptyNote"]


def test_each_check_quotes_the_engines_own_note_not_a_paraphrase():
    checks = {c["key"]: c for c in value("method", "checkModel", DATA)}
    assert checks["errors"]["note"] == UNDERWRITING["errors_note"]
    assert checks["implausible_refi"]["note"] == UNDERWRITING["implausible_refi_note"]
    assert "검증됨" in checks["implausible_refi"]["note"], \
        "엔진이 스스로 적어 둔 경고다 — 이 문장이 인용의 근거다"


def test_a_list_with_rows_shows_them_and_drops_the_empty_sentence():
    checks = {c["key"]: c for c in value("method", "checkModel", DATA)}
    skipped = checks["sub_regions_cap_skipped"]
    assert skipped["count"] == 1 and skipped["empty"] is False
    assert skipped["emptyNote"] == ""
    row = MARKET["sub_regions_cap_skipped"][0]
    assert skipped["rows"][0]["head"] == row["name"]
    assert skipped["rows"][0]["body"] == row["reason"]


def test_a_violation_that_appears_flips_the_check_by_itself():
    """오늘 0 인 것은 데이터의 사실이지 화면의 상수가 아니다."""
    hurt = copy.deepcopy(DATA)
    hurt["market"]["gate_violations"] = [
        {"name": "합성 위반", "reason": "유효임대료 게이트 밖 — 단위를 의심하라"}]
    checks = {c["key"]: c for c in value("method", "checkModel", hurt)}
    gate = checks["gate_violations"]
    assert gate["count"] == 1 and gate["empty"] is False
    assert gate["rows"][0]["body"] == "유효임대료 게이트 밖 — 단위를 의심하라"
    assert value("method", "EMPTY_NOTE") not in gate["emptyNote"]


def test_the_blank_is_struck_through_so_nobody_fills_it_later():
    """제도 도면에서 의도된 빈칸에는 사선을 긋는다 — 미기입과 구분하려는 것이다."""
    html = value("method", "checkHtml", value("method", "checkModel", DATA))
    assert html.count("is-blank") == 3
    assert "검증됨으로 읽지 말 것" in html
    assert MARKET["sub_regions_cap_skipped"][0]["reason"] in html


# ================================================================== #
# ⑤ 대장 — 대기 상태와 승격 경로
# ================================================================== #
def test_the_ledger_wait_states_its_http_reason_and_a_way_out():
    m = value("method", "ledgerModel", UNDERWRITING)
    assert m["n"] == 55 and m["pending"] == 55
    assert m["underwritten"] == 0 and m["failed"] == 0
    assert m["status"] == UNDERWRITING["summary"]["ledger_status"]
    assert "403" in m["status"]
    assert len(m["path"]) >= 3
    joined = " ".join(m["path"])
    assert "활용신청" in joined and "승격" in joined


def test_the_promotion_counts_are_derived_from_the_rows_never_written_down():
    """대장이 열리는 날 이 수는 저절로 움직여야 한다."""
    fake = {"summary": {"ledger_status": "합성"},
            "buildings": [
                {"pending_ledger": True, "pending_reason": "대장 대기"},
                {"pending_ledger": False, "underwriting": {"noi": {}}},
                {"pending_ledger": False,
                 "underwriting_error": {"kind": "RuntimeError", "reason": "게이트"}}]}
    m = value("method", "ledgerModel", fake)
    assert m["n"] == 3 and m["pending"] == 1
    assert m["underwritten"] == 1 and m["failed"] == 1


def test_the_blocked_calculations_are_named_while_the_ledger_is_shut():
    m = value("method", "ledgerModel", UNDERWRITING)
    assert m["blocked"], "막힌 계산 이름이 없으면 무엇을 못 하는지 알 수 없다"
    assert "NOI" in m["blocked"]


# ================================================================== #
# ⑥ 파킹된 한계
# ================================================================== #
def test_the_parked_limits_are_listed_with_the_place_they_live_in():
    items = value("method", "PARKED")
    assert len(items) >= 5
    for it in items:
        assert it["where"].strip() and it["what"].strip()
    html = value("method", "parkedHtml")
    assert "plan2-3-handoff" in html, "파킹 목록의 출처 문서를 밝힌다"
    assert items[0]["what"] in html


# ================================================================== #
# ⑦ 지면 — 표제란과 스크롤 영역
# ================================================================== #
def test_the_wide_table_can_be_pushed_with_a_keyboard():
    """가로로 넘치는 표는 초점과 이름을 가져야 한다(Ⅲ장 스트레스 표 규약)."""
    html = value("method", "manifestTable", MANIFEST)
    assert 'role="region"' in html and 'tabindex="0"' in html
    assert "aria-labelledby" in html or "aria-label" in html


def test_the_title_block_dates_the_page_from_the_manifest():
    rows = value("method", "specRows", DATA)
    keys = [r[0] for r in rows]
    assert "데이터 기준월" in keys and "원천" in keys
    flat = " ".join(r[1] for r in rows)
    assert MANIFEST["data_cutoff"].replace("-", ".") in flat
    assert "6" in flat


def test_the_page_refuses_when_its_own_arithmetic_and_the_data_disagree():
    """지면이 조용히 데이터 쪽 수를 보이면, 산술이 틀렸다는 사실이 영영 사라진다."""
    drifted = copy.deepcopy(MARKET)
    drifted["regions"]["도심"]["effective_rent_won_m2_mo"] = 30000.0
    r = js("method", "estimationSteps", drifted, "도심")
    assert r["ok"] is False and r["error"] == "gate", r
