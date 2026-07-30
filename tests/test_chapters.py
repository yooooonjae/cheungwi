"""Ⅰ장·Ⅱ장의 순수 함수 검사 — 원장의 세 변종과 계측기의 기하.

`tests/test_charts.py` 와 같은 왕복 규약이다(node 한 프로세스, DOM 없음). 여기서
붙드는 것은 두 가지다.

① **행 변종 3종.** 지금 실데이터는 55동 전부가 pending 이라, 승격 행과 실패 행을
   그리는 코드는 아무도 실행하지 않은 채로 배포된다. 그러면 대장이 열리는 날
   화면이 처음으로 깨진다. 그래서 승격 행을 **합성**한다 — 손으로 쓴 dict 가
   아니라 파이썬 파이프라인의 `_underwrite_one` 을 그대로 돌려 만든다. 대장이
   채워지면 실제로 나올 그 모양이어야 검사가 뜻을 갖는다.

② **슬라이더 → 엔진 → 침수 기하.** 슬라이더 값이 어떤 좌표가 되는지, 엔진이
   던진 오류가 어느 갈래로 분류되는지(**RangeError 를 TypeError 보다 먼저**),
   문구에 박히는 인자가 부동소수 꼬리를 달고 나가지 않는지.
"""

import copy
import json
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
            "node 를 찾을 수 없다 — 장 검사는 건너뛰지 않는다. 승격 행을 아무도 "
            "그려 보지 않은 채 통과하는 편이 훨씬 나쁘다")
    spec = [{"mod": mod, "fn": fn, "args": list(args)}]
    proc = subprocess.run([NODE, RUNNER], input=json.dumps(spec),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("장 러너 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)[0]


def value(mod, fn, *args):
    r = js(mod, fn, *args)
    assert r["ok"], "%s.%s 가 던졌다: %s" % (mod, fn, r.get("message"))
    return r["value"]


def _load(name):
    return json.loads((ROOT / "out" / name).read_text(encoding="utf-8"))


UNDERWRITING = _load("underwriting.json")
TRADES = _load("trades_analysis.json")
MARKET = _load("market.json")


# ------------------------------------------------------------------ #
# 합성 승격 — 대장이 열린 뒤의 행을 지금 만들어 둔다
# ------------------------------------------------------------------ #
SYNTH_LEDGER = {
    "totArea": 84250.0,
    "platArea": 6120.0,
    "grndFlrCnt": 30,
    "ugrndFlrCnt": 6,
    "useAprDay": "20030815",
    "mainPurpsCdNm": "업무시설",
    "strctCdNm": "철골철근콘크리트구조",
}


def promoted_row():
    """실제 파이프라인 함수로 승격 행 하나를 만든다(손으로 쓴 모양이 아니다)."""
    from src.analysis.build_out import _underwrite_one

    row = copy.deepcopy(UNDERWRITING["buildings"][0])
    row.pop("pending_reason", None)
    row.pop("blocked", None)
    row["pending_ledger"] = False
    row["ledger"] = dict(SYNTH_LEDGER)
    rf = row["region_figures"]
    a = UNDERWRITING["assumptions"]
    row["underwriting"] = _underwrite_one(
        rf["effective_rent_won_m2_mo"], SYNTH_LEDGER["totArea"], 22.6,
        rf["vacancy"], rf["cap_income_based"], a["loan_rate"], a["market_rate"])
    return row


def failed_row():
    """계산 중 예외로 멈춘 행 — `pending_ledger` 는 False 인데 `underwriting` 이 없다."""
    row = copy.deepcopy(UNDERWRITING["buildings"][1])
    row.pop("pending_reason", None)
    row.pop("blocked", None)
    row["pending_ledger"] = False
    row["ledger"] = dict(SYNTH_LEDGER, totArea=1200.0)
    row["underwriting_error"] = {
        "kind": "RuntimeError",
        "reason": "유효임대료 8,120.0원/㎡·월이 물리 범위[10000, 60000] 밖이다 — "
                  "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라",
    }
    return row


def pending_row():
    return copy.deepcopy(UNDERWRITING["buildings"][0])


def test_node_is_present_because_variants_never_skip():
    assert NODE is not None


# ================================================================== #
# Ⅰ장 — 원장의 세 변종
# ================================================================== #
def test_the_variant_is_decided_by_the_underwriting_key_not_by_pending_ledger():
    """실패 행도 `pending_ledger` 가 False 다 — 그 플래그만 보면 승격으로 읽힌다."""
    assert value("chapter1", "variantOf", pending_row()) == "pending"
    assert value("chapter1", "variantOf", promoted_row()) == "underwritten"
    assert value("chapter1", "variantOf", failed_row()) == "failed"


def test_every_real_row_is_pending_today_and_the_card_says_so():
    rows = UNDERWRITING["buildings"]
    kinds = [value("chapter1", "variantOf", r) for r in rows]
    assert kinds.count("pending") == 55 == len(rows)


def test_the_pending_card_stamps_the_wait_and_names_what_is_blocked():
    html = value("chapter1", "card", value("chapter1", "cardModel", pending_row(), 0))
    assert "대장 개통 대기" in html
    assert "card-rows" not in html, "없는 값의 자리를 만들어 두지 않는다"
    assert "억원" not in html, "빈 자리를 0 으로도 평균으로도 메우지 않는다"
    # 무엇이 막혀 있는지는 이름으로 남는다
    assert "NOI" in html and "막힌 계산" in html


def test_the_promoted_card_carries_area_floors_noi_and_value():
    row = promoted_row()
    model = value("chapter1", "cardModel", row, 3)
    assert model["variant"] == "underwritten"
    html = value("chapter1", "card", model)
    for label in ("연면적", "층수", "NOI", "추정가치"):
        assert label in html, "승격 카드에 %s 가 없다" % label
    assert "대장 개통 대기" not in html
    assert "84,250" in html                    # 연면적 ㎡
    assert "30" in html                        # 지상 층수
    uw = row["underwriting"]
    assert model["ltv"] == pytest.approx(uw["loan"]["loan_won"] / uw["value_won"])


def test_the_failed_card_shows_the_kind_and_the_reason():
    model = value("chapter1", "cardModel", failed_row(), 7)
    assert model["variant"] == "failed"
    html = value("chapter1", "card", model)
    assert "RuntimeError" in html or "물리 게이트" in html
    assert "단위" in html, "사유 원문이 카드에 남아야 한다"


def test_the_ledger_counts_agree_with_the_summary():
    m = value("chapter1", "ledgerModel", UNDERWRITING)
    s = UNDERWRITING["summary"]
    assert m["n"] == s["n"] == 55
    assert m["pending"] == s["pending_ledger"] == 55
    assert m["underwritten"] == s["underwritten"] == 0
    assert m["failed"] == 0
    assert {r["name"]: r["n"] for r in m["byRegion"]} == \
        {k: v["n"] for k, v in s["by_region"].items()}


def test_the_blocked_calculations_are_named_in_body_text_not_only_in_a_tooltip():
    """카드에는 수만 적는다 — 그러면 일곱 이름은 판독 글줄이 받아야 한다.

    손끝(title)에만 있는 정보는 좁은 화면과 낭독기에서 사라진다. 이 작품에서
    "무엇이 막혀 있는가"는 사라져도 되는 정보가 아니다.
    """
    m = value("chapter1", "ledgerModel", UNDERWRITING)
    assert len(m["blocked"]) == 7
    lines = " ".join(value("chapter1", "ledgerLines", m))
    for name in ("건물 특성 보정", "NOI", "추정가치", "대출가능액", "보유 모델",
                 "차환 판정", "손익분기 공실률"):
        assert name in lines, "막힌 계산 '%s' 이 글줄에 없다" % name


def test_the_ledger_model_counts_a_synthetic_mix_of_all_three_variants():
    """대장이 열린 날의 원장 — 지금 없는 조합이지만 집계는 이미 맞아야 한다."""
    doc = copy.deepcopy(UNDERWRITING)
    doc["buildings"] = [pending_row(), promoted_row(), failed_row()]
    m = value("chapter1", "ledgerModel", doc)
    assert (m["n"], m["pending"], m["underwritten"], m["failed"]) == (3, 1, 1, 1)


# ================================================================== #
# Ⅰ장 — 배타 사다리와 거래 산점
# ================================================================== #
def test_the_ladder_uses_the_exclusive_rungs_not_the_nested_counts():
    m = value("chapter1", "tradesModel", TRADES)
    ex = TRADES["matching"]["ladder_exclusive"]
    assert [b["value"] for b in m["ladder"]["bands"]] == \
        [ex["exact"], ex["resolved_only"], ex["ambiguous"]]
    assert m["ladder"]["total"] == ex["sum"] == TRADES["matching"]["n_matched"]
    naive = TRADES["matching"]["exact"]["n"] + TRADES["matching"]["resolved"]["n"] \
        + TRADES["matching"]["ambiguous"]["n"]
    assert naive != m["ladder"]["total"], "겹치는 세 수를 더하면 4,580 이 된다"


def test_the_ladder_says_in_words_that_the_ambiguous_rows_cannot_be_attributed():
    m = value("chapter1", "tradesModel", TRADES)
    lines = " ".join(value("chapter1", "ladderLines", m))
    assert "3,789" in lines and "귀속" in lines
    svg = value("chapter1", "ladderPlate", m, {})
    assert "3,789" in svg and "귀속" in svg


def test_the_ambiguous_caveat_is_assembled_from_the_ladder_not_written_by_hand():
    """경고문의 수는 데이터에서 온다 — 손으로 박으면 다음 수집에서 그림과 어긋난다."""
    m = value("chapter1", "tradesModel", TRADES)
    assert m["caveat"] == value("chapter1", "ambiguousCaveat", m["ladder"])
    assert "3,789" in m["caveat"] and "귀속" in m["caveat"]
    assert "**" not in m["caveat"], "마크다운은 이 자리에서 해석되지 않는다"
    # 아무도 그리지 않는 문장은 정직성 표기가 아니다 — 판독 글줄이 실제로 싣는다
    assert m["caveat"] in value("chapter1", "ladderLines", m)
    other = value("chapter1", "ambiguousCaveat", dict(m["ladder"], ambiguous=1234))
    assert "1,234" in other and "3,789" not in other


def test_the_blocked_names_are_the_union_across_rows_not_the_longest_row():
    """대장이 일부만 열리면 행마다 막힌 계산이 다르다 — 한 행만 말하면 나머지가 사라진다."""
    a, b = pending_row(), pending_row()
    a["blocked"] = ["noi", "value"]
    b["blocked"] = ["building_adjust", "hold_model"]
    doc = copy.deepcopy(UNDERWRITING)
    doc["buildings"] = [a, b]
    m = value("chapter1", "ledgerModel", doc)
    # 합집합이고, 늘어놓는 차례는 파이프라인이 부르는 순서다
    assert m["blocked"] == ["건물 특성 보정", "NOI", "추정가치", "보유 모델"]
    lines = " ".join(value("chapter1", "ledgerLines", m))
    for name in m["blocked"]:
        assert name in lines


def test_the_tiny_exact_rung_is_still_labelled():
    """57 은 전체의 1.3% 라 3.8px 이다 — 높이로는 못 읽으니 지시선이 받는다."""
    m = value("chapter1", "tradesModel", TRADES)
    svg = value("chapter1", "ladderPlate", m, {})
    assert "57" in svg
    assert "leader" in svg


def test_the_ladder_bands_are_proportional_and_seamless():
    m = value("chapter1", "tradesModel", TRADES)
    laid = value("charts", "strataLayout", m["ladder"]["bands"],
                 {"x": 0, "y": 0, "width": 40, "height": 300,
                  "total": m["ladder"]["total"]})
    assert laid[0]["height"] == pytest.approx(300 * 57 / 4523, abs=0.01)
    for lower, upper in zip(laid, laid[1:]):
        assert lower["y"] == pytest.approx(upper["y"] + upper["height"])


def test_the_scatter_carries_every_region_year_and_every_exact_case():
    m = value("chapter1", "tradesModel", TRADES)
    assert [s["name"] for s in m["regions"]] == ["도심", "강남", "여의도마포"]
    for s in m["regions"]:
        assert len(s["points"]) == len(TRADES["by_region"][s["name"]]["by_year"])
    assert len(m["dots"]) == len(TRADES["exact_cases"]) == 55
    assert m["exact"]["n"] == 57 and m["exact"]["live"] == 55
    assert len(m["exact"]["buildings"]) == 4


def test_the_scatter_plot_stays_inside_its_viewbox():
    m = value("chapter1", "tradesModel", TRADES)
    geom = value("chapter1", "tradesGeom", m, {})
    for p in geom["dots"] + [q for s in geom["series"] for q in s["points"]]:
        assert 0 <= p["x"] <= geom["width"]
        assert 0 <= p["y"] <= geom["height"]


def test_chapter_figures_use_one_lettering_height():
    """도면의 활자 높이는 한 종류다 — 그래야 `--fig-k` 의 하한이 정확해진다."""
    m = value("chapter1", "tradesModel", TRADES)
    for svg in (value("chapter1", "tradesPlot", m, {}),
                value("chapter1", "ladderPlate", m, {})):
        assert 'class="ch-fig' in svg
        for cls in ("lab-sub", "lab-unit", "lab-head", "lab-foot"):
            assert cls not in svg, "장 도면은 %s 를 쓰지 않는다(높이가 갈린다)" % cls


# ================================================================== #
# Ⅱ장 — 계측기
# ================================================================== #
def base_region(name="도심"):
    return value("chapter2", "regionBase", MARKET, UNDERWRITING, name)


def evaluate(base, knobs):
    return value("chapter2", "evaluate", base, knobs)


def test_the_gauge_at_rest_reproduces_the_prologue_binding():
    base = base_region("도심")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["loan"]["binding"] == "debt_yield"
    assert m["ltv"] == pytest.approx(m["loan"]["won"] / m["value"]["won"])
    assert m["value"]["ok"] and m["noi"]["ok"]


def test_pulling_the_vacancy_slider_lowers_noi_value_and_equity_but_not_the_loan():
    base = base_region("도심")
    rest = value("chapter2", "defaultKnobs", base)
    worse = dict(rest, vacancy=0.30)
    a, b = evaluate(base, rest), evaluate(base, worse)
    assert b["noi"]["won"] < a["noi"]["won"]
    assert b["value"]["won"] < a["value"]["won"]
    assert b["equity"]["won"] < a["equity"]["won"]
    # 대출은 취득 시점에 정해진 뒤 움직이지 않는다 — 수면이 오르는 이유가 그것이다
    assert b["loan"]["won"] == pytest.approx(a["loan"]["won"])
    assert b["ltv"] > a["ltv"]


def test_the_water_sits_at_the_loan_and_the_bands_sum_to_the_value():
    base = base_region("강남")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    idx = 100.0 / m["value"]["baseWon"]
    assert m["water"]["level"] == pytest.approx(m["loan"]["won"] * idx, abs=1e-3)
    assert sum(b["value"] for b in m["bands"]) == \
        pytest.approx(m["value"]["won"] * idx, abs=1e-3)
    assert m["water"]["total"] == m["columnTotal"] == 130


# ---- 침수 — 실데이터로는 닿지 않는다. 합성 가정으로 기하를 고정한다 ---- #
def drownable_base():
    """LTV 한도 0.95 인 가상의 대주 — 슬라이더 범위 안에서 지분이 잠긴다."""
    base = base_region("도심")
    base["ltvMax"] = 0.95
    base["dyMin"] = 0.02
    base["dscrMin"] = 0.5      # 셋 중 LTV 가 묶어야 대출이 0.95 가치까지 올라간다
    return base


def test_the_equity_drowns_when_the_value_falls_under_the_fixed_loan():
    base = drownable_base()
    knobs = dict(value("chapter2", "defaultKnobs", base), vacancy=0.30)
    m = evaluate(base, knobs)
    assert m["value"]["won"] < m["loan"]["won"]
    assert m["equity"]["won"] < 0
    assert m["equity"]["submerged"] is True
    keys = [b["key"] for b in m["bands"]]
    assert keys[0] == "senior"
    # 잠긴 자산은 가치까지만 그린다 — 없는 자산을 물이 덮게 두지 않는다
    assert m["bands"][0]["value"] == pytest.approx(
        m["value"]["won"] * 100.0 / m["value"]["baseWon"])
    assert [b for b in m["bands"] if b["key"] == "equity"][0]["value"] == 0


def test_the_gauge_reports_the_vacancy_at_which_the_equity_drowns():
    base = drownable_base()
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    v0 = base["vacancy0"]
    expected = 1 - (m["loan"]["won"] / m["value"]["baseWon"]) * (1 - v0)
    assert m["drown"]["vacancy"] == pytest.approx(expected)
    assert m["drown"]["reachable"] is True


def test_the_real_regions_cannot_drown_inside_the_slider_and_say_so():
    base = base_region("도심")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["drown"]["vacancy"] > 0.30
    assert m["drown"]["reachable"] is False
    assert any("완전" in b["text"] or "잠기" in b["text"] for b in m["banners"])


# ---- 지분 IRR 의 두 기준 — 엔진 원본과 직접 대조한다 ---- #
def hold_direct(m, base, cost_rate):
    """장을 거치지 않고 엔진을 직접 부른다 — 장이 무엇을 넘겼는지 붙들기 위해."""
    return value("engine", "hold_model", m["value"]["won"], m["loan"]["won"],
                 m["loanRate"], m["noi"]["won"], base["noiGrowth"], m["exitCap"],
                 base["holdYears"], cost_rate)


def irr_note(m):
    rows = value("chapter2", "readings", m)
    return [r for r in rows if r["k"] == "지분 IRR"][0]["note"]


def test_at_rest_the_irr_is_the_acquisition_irr_with_the_fee_on_the_equity():
    """손잡이가 제자리면 그 가격은 취득가다 — 부대비용이 자기자본에 얹히는 것이 옳다."""
    base = base_region("도심")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["atRest"] is True
    assert m["hold"]["basis"] == "acquisition"
    assert m["hold"]["costRate"] == base["costRate"]
    assert m["hold"]["equityWon"] == pytest.approx(
        m["value"]["won"] * (1 + base["costRate"]) - m["loan"]["won"])
    assert m["hold"]["irr"] == pytest.approx(
        hold_direct(m, base, base["costRate"])["equity_irr"])
    assert "취득 시점 IRR" in irr_note(m) and "전향 IRR" in irr_note(m)


def test_after_the_knobs_move_the_irr_enters_at_the_market_equity_it_reports():
    """조작 후는 취득이 아니라 보유 중이다 — 끝난 취득에 부대비용을 다시 물리지 않는다.

    옛 계산은 하락한 시가에 비용률을 또 곱해 진입 유출을 판독의 「지분」보다
    크게 잡았고, 그만큼 손해를 과장했다.
    """
    base = base_region("도심")
    pulled = dict(value("chapter2", "defaultKnobs", base),
                  vacancy=0.30, rate=0.015, exitCap=0.0075)
    m = evaluate(base, pulled)
    assert m["atRest"] is False
    assert m["hold"]["basis"] == "forward" and m["hold"]["costRate"] == 0
    # 진입 지분이 판독의 「지분」과 **같은 수**여야 한다
    assert m["hold"]["equityWon"] == pytest.approx(m["equity"]["won"])
    assert m["hold"]["irr"] == pytest.approx(hold_direct(m, base, 0.0)["equity_irr"])
    overstated = hold_direct(m, base, base["costRate"])["equity_irr"]
    assert m["hold"]["irr"] > overstated, "부대비용 재부과가 손해를 부풀렸다"
    assert "취득 시점 IRR" in irr_note(m) and "전향 IRR" in irr_note(m)


# ---- 오류 갈래 — RangeError 를 TypeError 보다 먼저 ---- #
def test_a_physical_gate_is_reported_as_a_gate_not_as_something_else():
    """매각 cap 이 물리 범위 밖이면 RangeError 다. Error 를 먼저 잡으면 뭉개진다."""
    base = base_region("강남")           # cap 0.0305 — −1%p 면 0.0205, 아슬아슬하다
    base["cap"] = 0.025
    knobs = dict(value("chapter2", "defaultKnobs", base), exitCap=-0.01)
    m = evaluate(base, knobs)
    assert m["hold"]["ok"] is False
    assert m["hold"]["kind"] == "gate", "게이트가 '그 밖'으로 뭉개졌다"
    assert "매각 cap" in m["hold"]["message"]
    assert any(b["kind"] == "gate" for b in m["banners"])


def test_an_input_error_is_reported_as_an_input_error():
    base = base_region("도심")
    base["ltvMax"] = 0.0                 # (0, 1] 밖 — 입력 오류다
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["loan"]["ok"] is False and m["loan"]["kind"] == "input"


def test_one_broken_stage_does_not_take_the_whole_instrument_down():
    """대출이 가치를 넘으면 보유 모델은 거절한다 — 나머지 판독은 살아 있어야 한다."""
    base = drownable_base()
    knobs = dict(value("chapter2", "defaultKnobs", base), vacancy=0.30)
    m = evaluate(base, knobs)
    assert m["hold"]["ok"] is False and m["hold"]["kind"] == "input"
    assert m["noi"]["ok"] and m["value"]["ok"] and m["refi"]["ok"]
    assert m["bev"]["ok"]


def test_the_implausible_signal_becomes_a_banner_with_its_reason():
    base = base_region("도심")
    base["dscrMin"] = 0.3                # 실무에 없는 조합 — 신호가 켜진다
    base["dyMin"] = 1.0
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["refi"]["implausible"] is True
    banner = [b for b in m["banners"] if b["kind"] == "implausible"]
    assert banner and "최대금리" in banner[0]["text"]


# ---- 문구에 박히는 인자는 부동소수 꼬리를 달지 않는다 ---- #
def test_the_rate_that_goes_into_the_prose_is_a_clean_float():
    base = base_region("도심")
    knobs = dict(value("chapter2", "defaultKnobs", base), rate=0.0007)
    m = evaluate(base, knobs)
    assert m["loanRate"] == 0.0434, "0.0427 + 0.0007 의 꼬리를 잘라야 한다"
    notes = " ".join(m["hold"]["notes"])
    assert "0.0434" in notes
    assert "0.043400000000000005" not in notes


def test_the_exit_cap_that_goes_into_the_prose_is_a_clean_float():
    base = base_region("도심")
    knobs = dict(value("chapter2", "defaultKnobs", base), exitCap=0.0003)
    m = evaluate(base, knobs)
    assert m["exitCap"] == 0.040785
    assert "0.040785" in " ".join(m["hold"]["notes"])


# ---- 슬라이더와 낭독 ---- #
def test_the_knobs_are_clamped_to_their_declared_range():
    base = base_region("도심")
    clamped = value("chapter2", "clampKnobs",
                    {"rate": 9.0, "vacancy": -1.0, "exitCap": 9.0}, base)
    specs = {s["key"]: s for s in value("chapter2", "knobSpecs")}
    assert clamped["rate"] == specs["rate"]["max"]
    assert clamped["vacancy"] == specs["vacancy"]["min"]
    assert clamped["exitCap"] == specs["exitCap"]["max"]


def test_the_slider_speaks_its_value_with_a_unit_and_a_distance_from_rest():
    base = base_region("도심")
    specs = {s["key"]: s for s in value("chapter2", "knobSpecs")}
    text = value("chapter2", "ariaValueText", specs["rate"], 0.01, base)
    assert "%p" in text and "기준" in text
    html = value("chapter2", "sliderRow", specs["vacancy"], 0.12, base)
    assert 'type="range"' in html
    assert "aria-valuetext=" in html
    assert 'aria-describedby=' in html or "<label" in html


def test_the_readings_exist_as_text_for_the_live_region():
    base = base_region("도심")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    rows = value("chapter2", "readings", m)
    keys = [r["k"] for r in rows]
    for want in ("NOI", "가치", "대출", "LTV", "DSCR", "Debt Yield", "차환 여유"):
        assert any(want in k for k in keys), "판독값에 %s 가 없다" % want
    assert all(isinstance(r["v"], str) and r["v"] for r in rows)
    live = value("chapter2", "liveText", m)
    assert "수면" in live and "지분" in live


def test_the_plate_draws_the_windows_that_the_vacancy_slider_turns_off():
    base = base_region("도심")
    knobs = dict(value("chapter2", "defaultKnobs", base), vacancy=0.25)
    m = evaluate(base, knobs)
    assert m["tower"]["dark"] == round(0.25 * m["tower"]["cells"])
    svg = value("chapter2", "render", m, {})
    assert svg.count('class="win off"') == m["tower"]["dark"]
    assert "plate-svg" in svg


def test_the_refinancing_limit_is_a_line_on_the_value_column():
    base = base_region("도심")
    m = evaluate(base, value("chapter2", "defaultKnobs", base))
    assert m["refi"]["ltvLimitWon"] == pytest.approx(
        m["loan"]["won"] / base["refiLtvMax"])
    svg = value("chapter2", "render", m, {})
    assert "refi-limit" in svg, "차환 한계선이 그림에 없다"


def test_the_label_scale_keeps_chapter_figures_above_the_floor():
    """390·768 실측 폭에서 인-피겨 라벨이 9px 아래로 내려가지 않는다."""
    for width, compact in ((350.0, True), (728.0, False), (1200.0, False)):
        k = value("chapter2", "plateLabelScale", width, {"compact": compact})
        declared = 12.0 if compact else 11.0
        vb = 430.0 if compact else 880.0
        assert declared * k * (width / vb) >= 8.99, "%d px 에서 하한이 깨진다" % width
        assert k >= 1.0
