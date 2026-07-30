"""Ⅲ장 시간의 층위 · 실험실 — 순수 함수 검사.

`tests/test_chapters.py` 와 같은 왕복 규약이다(node 한 프로세스, DOM 없음).
여기서 붙드는 것은 셋이다.

① **퇴적의 좌표.** 서장의 자본 지층 기둥이 마흔두 번 늘어서서 시간이 된다.
   달마다 층의 합이 누적 높이와 같은지, 층 사이에 틈이 없는지, 수면(대출잔액)이
   제자리에 놓이는지, 준공 달에 이자가 자본화되며 수면이 튀어오르는지.

② **스트레스 표의 두 LLCR.** 이 데이터는 "하나만 인용하지 말 것"을 원장에 적어
   두었다(D8). 화면이 하나만 싣는 순간 그 계약이 깨지므로, 표를 짓는 함수가 두
   값과 원문 주석을 함께 내는지를 검사가 붙든다.

③ **실험실의 세 갈래.** 게이트(RangeError)를 입력 오류(TypeError)보다 **먼저**
   잡는지, implausible 은 예외가 아니라 배너로 나가는지, 한 단계가 거절해도 앞
   단계의 판독이 살아 있는지.
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
            "node 를 찾을 수 없다 — 시간 검사는 건너뛰지 않는다. 게이트 갈래를 "
            "아무도 밟아 보지 않은 채 통과하는 편이 훨씬 나쁘다")
    spec = [{"mod": mod, "fn": fn, "args": list(args)}]
    proc = subprocess.run([NODE, RUNNER], input=json.dumps(spec),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("시간 러너 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)[0]


def value(mod, fn, *args):
    r = js(mod, fn, *args)
    assert r["ok"], "%s.%s 가 던졌다: %s" % (mod, fn, r.get("message"))
    return r["value"]


def _load(name):
    return json.loads((ROOT / "out" / name).read_text(encoding="utf-8"))


PF = _load("pf_case.json")
MARKET = _load("market.json")
UNDERWRITING = _load("underwriting.json")

WIDE = {"compact": False}
NARROW = {"compact": True}


def test_node_is_present_because_the_gate_branch_never_skips():
    assert NODE is not None


# ================================================================== #
# ① 퇴적 — 시간축으로 누운 지층
# ================================================================== #
def test_the_deposit_covers_every_month_and_sums_to_the_total_cost():
    m = value("chapter3", "depositModel", PF)
    assert m["months"] == 42
    assert m["buildMonths"] == 30 and m["leaseMonths"] == 12
    assert len(m["cols"]) == 42
    # 준공 달의 누적이 총사업비다 — 네 갈래(토지·공사·간접·금융)의 합.
    last_build = m["cols"][29]
    assert last_build["cum"] == pytest.approx(PF["model"]["total_cost"], rel=1e-9)
    parts = last_build["parts"]
    assert parts["land"] == pytest.approx(PF["model"]["assumptions"]["land_won"])
    assert parts["hard"] == pytest.approx(PF["model"]["assumptions"]["hard_cost_won"])
    assert parts["soft"] == pytest.approx(PF["model"]["assumptions"]["soft_cost_won"])
    assert parts["fin"] == pytest.approx(
        PF["model"]["fee_won"] + PF["model"]["interest_won"], rel=1e-9)


def test_the_deposit_stops_at_completion_but_the_operating_loss_keeps_growing():
    """준공은 퇴적이 멈추는 자리다 — 부정합면. 그 위에 다른 종류의 시간이 온다."""
    m = value("chapter3", "depositModel", PF)
    build = m["cols"][29]["parts"]
    for col in m["cols"][30:]:
        for key in ("land", "hard", "soft", "fin"):
            assert col["parts"][key] == pytest.approx(build[key], rel=1e-12)
    # 임대기간 순현금은 음수라 자기자본이 메운다 — 그 두께가 다섯 번째 층이다.
    losses = [c["parts"]["op"] for c in m["cols"][30:]]
    assert losses == sorted(losses), "운영손실은 달마다 누적된다"
    assert losses[-1] == pytest.approx(
        -PF["model"]["assumptions"]["lease_up_operating_cash_won"], rel=1e-9)
    assert m["cols"][29]["parts"]["op"] == 0


def test_the_water_is_the_loan_balance_and_the_dry_band_is_the_equity():
    """자기자본은 첫 달에 전액 들어간다(D3) — 그 뒤 쌓이는 것은 전부 빚이다."""
    m = value("chapter3", "depositModel", PF)
    eq = PF["model"]["assumptions"]["equity_won"]
    monthly = PF["model"]["monthly"]
    for i in (0, 1, 15, 29, 41):
        assert m["cols"][i]["loan"] == pytest.approx(monthly[i]["loan_balance_won"])
    # 준공 달: 발생이자가 한 번에 자본화되어 수면이 튀어오른다(D5).
    assert m["cols"][29]["loan"] - m["cols"][28]["loan"] > PF["model"]["interest_won"]
    # 자본화가 끝난 뒤의 마른 두께는 정확히 자기자본이다.
    assert m["cols"][29]["cum"] - m["cols"][29]["loan"] == pytest.approx(eq, rel=1e-9)
    # 그 전에는 아직 자본화되지 않은 발생이자만큼 더 두껍다.
    assert m["cols"][28]["cum"] - m["cols"][28]["loan"] > eq


def test_the_dry_band_equals_the_equity_in_exactly_one_month():
    """'마른 두께는 늘 자기자본'이 아니다 — 그 등식이 서는 달은 준공 달뿐이다.

    9개월째는 268.7억(+4.8%), 28개월째는 324.2억(+26%)이다. 앞은 아직 자본화되지
    않은 발생이자만큼, 뒤는 임대기간 순현금만큼 더 두껍다.
    """
    m = value("chapter3", "depositModel", PF)
    eq = PF["model"]["assumptions"]["equity_won"]
    same = [i for i, c in enumerate(m["cols"])
            if abs(c["cum"] - c["loan"] - eq) < 1e6]
    assert same == [29], "마른 두께가 자기자본과 같은 달: %s" % same
    assert m["cols"][9]["dry"] > eq * 1.04
    assert m["cols"][41]["dry"] > eq * 1.1


def test_the_callout_points_at_the_completion_month_and_measures_the_dry_band():
    """지시선은 등식이 성립하는 달을 짚고, 선 자체가 마른 두께를 잰다."""
    g = value("chapter3", "depositGeom", PF, WIDE)
    m = value("chapter3", "depositModel", PF)
    svg = value("chapter3", "renderDeposit", PF, WIDE)
    idx = m["buildMonths"] - 1
    col = g["cols"][idx]
    center = round(col["x"] + col["width"] / 2, 4)
    rails = re.findall(r'<line x1="([\d.]+)" x2="([\d.]+)" y1="([\d.]+)" '
                       r'y2="([\d.]+)" class="callout"/>', svg)
    dim = [r for r in rails if float(r[0]) == float(r[1])]
    assert len(dim) == 1, "치수선은 하나다: %s" % rails
    x1, _, y1, y2 = (float(v) for v in dim[0])
    assert x1 == pytest.approx(center, abs=1e-3), "준공 달을 짚지 않는다"
    assert y1 == pytest.approx(g["yOf"][idx]["cumY"], abs=1e-3)
    assert y2 == pytest.approx(g["yOf"][idx]["loanY"], abs=1e-3)
    label = re.search(r'class="lab lab-dry"[^>]*>([^<]+)<', svg).group(1)
    assert label == "준공 시점의 마른 두께 = 자기자본 256.3억"


def test_the_reading_line_no_longer_claims_the_dry_band_never_changes():
    m = value("chapter3", "depositModel", PF)
    said = " ".join(value("chapter3", "depositLines", m))
    assert "늘 그만큼" not in said
    assert "준공 달 하나뿐" in said
    # 다음 글줄의 '부풀어 있는 두께 = 미자본화 이자'와 같은 말을 해야 한다
    assert "자본화되지 않은 이자" in said


def test_the_bands_are_stacked_bottom_up_in_the_declared_order():
    m = value("chapter3", "depositModel", PF)
    assert [b["key"] for b in m["bands"]] == ["land", "hard", "soft", "fin", "op"]


def test_every_month_column_stacks_without_a_seam():
    """층의 높이를 따로 반올림하면 0.01px 틈으로 배경이 실선처럼 비친다."""
    g = value("chapter3", "depositGeom", PF, WIDE)
    for col in g["cols"]:
        rects = col["rects"]
        for a, b in zip(rects, rects[1:]):
            # 배열은 아래부터 — 윗층의 바닥이 아랫층의 천장과 같은 수여야 한다
            assert a["y"] == pytest.approx(b["y"] + b["height"], abs=1e-9)
        top = rects[-1]["y"]
        bottom = rects[0]["y"] + rects[0]["height"]
        assert bottom == pytest.approx(g["groundY"], abs=1e-9)
        assert top == pytest.approx(g["yOf"][col["month"]]["cumY"], abs=1e-9)


def test_the_columns_tile_the_time_axis_without_gaps():
    g = value("chapter3", "depositGeom", PF, WIDE)
    cols = g["cols"]
    assert len(cols) == 42
    for a, b in zip(cols, cols[1:]):
        assert a["x"] + a["width"] == pytest.approx(b["x"], abs=1e-9)
    assert cols[0]["x"] == pytest.approx(g["x0"], abs=1e-9)
    assert cols[-1]["x"] + cols[-1]["width"] == pytest.approx(g["x1"], abs=1e-9)


def test_the_unconformity_sits_exactly_at_the_completion_boundary():
    g = value("chapter3", "depositGeom", PF, WIDE)
    assert g["jointX"] == pytest.approx(g["cols"][30]["x"], abs=1e-9)


def test_the_exit_rule_stands_above_the_cost_line_and_the_gap_is_the_profit():
    g = value("chapter3", "depositGeom", PF, WIDE)
    assert g["exitY"] < g["costY"], "매각가가 총사업비 위에 있다(y 는 위에서 잰다)"
    span = g["groundY"] - g["topY"]
    gap = (g["costY"] - g["exitY"]) / span
    assert gap == pytest.approx(
        PF["model"]["profit"] / g["ceiling"], rel=1e-6)


def test_a_ceiling_below_the_pile_is_refused_instead_of_silently_clipped():
    """천장이 퇴적보다 낮으면 조용히 자르지 않고 멈춘다(strataLayout 규약)."""
    r = js("chapter3", "depositGeom", PF, {"compact": False, "ceiling": 1.0e9})
    assert not r["ok"] and r["error"] == "input"


def test_the_reading_lines_carry_the_numbers_the_narrow_plate_drops():
    m = value("chapter3", "depositModel", PF)
    lines = value("chapter3", "depositLines", m)
    joined = " ".join(lines)
    for token in ("자기자본", "총사업비", "매각", "준공"):
        assert token in joined
    assert "D5" in joined or "자본화" in joined


# ================================================================== #
# ② 스트레스 15행 — 두 LLCR 계약
# ================================================================== #
def test_the_stress_table_has_the_base_row_plus_fifteen_shocks():
    m = value("chapter3", "stressModel", PF)
    assert m["n"] == 15
    assert len(m["rows"]) == 15
    assert m["base"]["irr"] == pytest.approx(PF["model"]["equity_irr"])
    assert m["base"]["ltc"] == pytest.approx(PF["model"]["ltc"])


def test_the_base_row_carries_both_llcr_values_never_one_alone():
    m = value("chapter3", "stressModel", PF)
    assert m["base"]["llcr"] == pytest.approx(PF["model"]["llcr"])
    assert m["base"]["llcrNoiOnly"] == pytest.approx(PF["model"]["llcr_noi_only"])
    pair = value("chapter3", "llcrPair", m)
    # 값을 박지 않는다(금리·임대료가 갱신되면 움직인다) — 두 값이 **함께** 실렸는지를 본다
    assert "%.4f" % PF["model"]["llcr"] in pair
    assert "%.4f" % PF["model"]["llcr_noi_only"] in pair
    assert "하나만 인용하지 말 것" in pair


def test_the_stress_rows_say_which_llcr_definition_they_are():
    """행의 llcr 은 매각대금 포함 값 하나다 — 그 사실이 화면에 남아야 한다."""
    m = value("chapter3", "stressModel", PF)
    assert m["llcrNote"] == PF["stress"]["llcr_note"]
    assert m["modelLlcrNote"] == PF["model"]["llcr_note"]
    html = value("chapter3", "stressTableHtml", m)
    assert "매각대금" in html
    assert ("%.4f" % PF["model"]["llcr"] in html
            and "%.4f" % PF["model"]["llcr_noi_only"] in html), \
        "표 안에 두 값이 함께 있어야 한다"


def test_the_delta_sign_is_not_clipped_because_the_ladder_is_positive():
    m = value("chapter3", "stressModel", PF)
    ladder = [r for r in m["rows"] if r["group"] == "equity"]
    assert len(ladder) == 4
    assert all(r["delta"] > 0 for r in ladder), "자기자본을 줄이면 IRR 은 오른다"
    html = value("chapter3", "stressTableHtml", m)
    # 양수 델타에 부호가 남아 있는지가 요점이다 — 값은 데이터에서 받아 온다
    top = max(r["delta"] for r in ladder)
    assert ("+%.2f" % (top * 100)) in html or ("+%.4f" % top) in html


def test_a_missing_irr_is_a_dash_not_a_zero():
    """equity_irr None 은 '근을 찾지 못했다'는 뜻이지 0% 가 아니다."""
    pf = copy.deepcopy(PF)
    pf["stress"]["rows"][0]["equity_irr"] = None
    pf["stress"]["rows"][0]["delta"] = None
    m = value("chapter3", "stressModel", pf)
    assert m["rows"][0]["irr"] is None
    html = value("chapter3", "stressTableHtml", m)
    assert "―" in html
    assert "0.00%" not in html.split("</thead>")[-1].split("</tr>")[1]


def test_the_worst_row_is_read_from_the_data_not_written_by_hand():
    m = value("chapter3", "stressModel", PF)
    assert m["worst"]["name"] == "exit cap +1.0%p"
    pf = copy.deepcopy(PF)
    pf["stress"]["rows"][2]["equity_irr"] = -0.99
    pf["stress"]["rows"][2]["delta"] = -1.09
    assert value("chapter3", "stressModel", pf)["worst"]["name"] == "준공지연 +6개월"


def test_the_reading_lines_survive_a_table_where_no_irr_was_found():
    """근을 하나도 못 찾은 표에서 '최악'을 말하려다 화면 전체가 죽으면 안 된다."""
    pf = copy.deepcopy(PF)
    for row in pf["stress"]["rows"]:
        row["equity_irr"] = None
        row["delta"] = None
    m = value("chapter3", "stressModel", pf)
    assert m["worst"] is None and m["best"] is None
    said = " ".join(value("chapter3", "stressLines", m))
    assert "가장 나쁜 것은" not in said, "없는 값으로 최악을 지어내지 않는다"
    assert "구해진 행이 없다" in said
    assert "하나만 인용하지 말 것" in said


def test_the_operating_band_thins_again_when_a_month_turns_cash_positive():
    """다섯째 층은 손실의 합이 아니라 **누적 순유출**이다 — 돌아온 현금은 얇아진다."""
    pf = copy.deepcopy(PF)
    rows = pf["model"]["monthly"]
    lease = [r for r in rows if r["phase"] != "construction"]
    lease[-1]["operating_cash_won"] = 2_000_000_000.0
    m = value("chapter3", "depositModel", pf)
    assert m["cols"][-1]["parts"]["op"] < m["cols"][-2]["parts"]["op"]
    assert m["cols"][-1]["parts"]["op"] >= 0, "지층의 두께는 음수일 수 없다"


# ================================================================== #
# ③ 자기자본 제도 사다리 5 → 20%
# ================================================================== #
def test_an_empty_ladder_is_refused_instead_of_drawn_as_a_blank_figure():
    pf = copy.deepcopy(PF)
    pf["stress"]["rows"] = [r for r in pf["stress"]["rows"]
                            if not r["name"].startswith("자기자본")]
    r = js("chapter3", "ladderModel", pf)
    assert not r["ok"] and r["error"] == "input"



def test_the_ladder_has_four_rungs_plus_the_case_itself():
    m = value("chapter3", "ladderModel", PF)
    assert [r["equityShare"] for r in m["rungs"]] == pytest.approx([.05, .10, .15, .20])
    for r in m["rungs"]:
        assert r["ltc"] == pytest.approx(1 - r["equityShare"], abs=1e-9)
        assert sum(b["value"] for b in r["bands"]) == pytest.approx(100, abs=1e-9)
        assert [b["key"] for b in r["bands"]] == ["senior", "equity"]
    assert m["base"]["ltc"] == pytest.approx(PF["model"]["ltc"])
    assert m["base"]["equityShare"] == pytest.approx(1 - PF["model"]["ltc"])


def test_the_ladder_says_the_two_faces_of_one_rung():
    """자기자본을 올리면 지분 IRR 은 깎이고 대주 커버리지는 좋아진다."""
    m = value("chapter3", "ladderModel", PF)
    irrs = [r["irr"] for r in m["rungs"]]
    llcrs = [r["llcr"] for r in m["rungs"]]
    assert irrs == sorted(irrs, reverse=True)
    assert llcrs == sorted(llcrs)
    lines = " ".join(value("chapter3", "ladderLines", m))
    # 사다리의 양 끝이 글줄에 그대로 실려야 한다(값은 데이터에서 받는다 — 금리가 움직인다)
    assert "%.2f" % (irrs[0] * 100) in lines and "%.2f" % (irrs[-1] * 100) in lines
    assert "%.4f" % llcrs[0] in lines


def test_the_ladder_columns_are_strata_of_the_same_primitive():
    g = value("chapter3", "ladderGeom", PF, WIDE)
    for col in g["cols"]:
        rects = col["rects"]
        assert len(rects) == 2
        assert rects[0]["y"] == pytest.approx(rects[1]["y"] + rects[1]["height"],
                                              abs=1e-9)


# ================================================================== #
# ④ 손익분기 토지단가 — 프라임 필지에서는 서지 않는다
# ================================================================== #
def test_the_land_verdict_is_derived_not_hardcoded():
    m = value("chapter3", "landModel", PF)
    ctx = PF["land_price_context"]
    assert m["breakeven"] == pytest.approx(ctx["breakeven_land_price_won_m2"])
    assert m["seedMin"] == pytest.approx(ctx["seed_land_price_won_m2"]["min"])
    # 판정은 그날의 두 수의 비교다. 어느 쪽이 나올지를 상수로 박으면, 임대료·금리가 갱신돼
    # 손익분기 토지단가가 최저 필지를 넘어선 날(2026Q2 에 실제로 그랬다) 옳은 계산이 깨진다.
    assert m["stands"] is (m["seedMin"] <= m["breakeven"])
    # 시드가 손익분기 밑으로 내려가면 판정이 뒤집혀야 한다 — 문장이 아니라 계산이다
    pf = copy.deepcopy(PF)
    pf["land_price_context"]["seed_land_price_won_m2"]["min"] = 9_000_000
    assert value("chapter3", "landModel", pf)["stands"] is True
    pf["land_price_context"]["seed_land_price_won_m2"]["min"] = 900_000_000
    assert value("chapter3", "landModel", pf)["stands"] is False


def test_the_assumed_land_price_keeps_its_assumption_label():
    m = value("chapter3", "landModel", PF)
    assert m["assumed"] == pytest.approx(
        PF["land_price_context"]["assumed_land_price_won_m2"])
    marks = [p["kind"] for p in m["marks"] if p["key"] == "assumed"]
    assert marks == ["가정"]
    lines = " ".join(value("chapter3", "landLines", m))
    assert "가정" in lines
    assert "프라임" in lines


def test_the_values_outside_the_axis_are_labelled_with_a_break_not_dropped():
    m = value("chapter3", "landModel", PF)
    off = [p for p in m["marks"] if p["clipped"]]
    assert [p["key"] for p in off] == ["median", "max"]
    for p in off:
        assert p["won"] > m["axisMax"]
    g = value("chapter3", "landGeom", PF, WIDE)
    for p in g["marks"]:
        assert g["x0"] - 1e-6 <= p["x"] <= g["x1"] + 1e-6


SEED_PRICES = {"n": 3, "min": 16_940_000, "median": 70_590_000, "max": 95_640_000}


def test_the_land_verdict_kind_splits_the_same_four_ways_as_python():
    """갈래는 파이썬 쌍둥이(`build_out._land_verdict_kind`)와 같은 네 개다."""
    assert value("chapter3", "landVerdictKind", SEED_PRICES, 10_000_000) == "fails"
    assert value("chapter3", "landVerdictKind", SEED_PRICES, 17_029_258) == "partial"
    assert value("chapter3", "landVerdictKind", SEED_PRICES, 80_000_000) == "stands"
    assert value("chapter3", "landVerdictKind", SEED_PRICES, None) == "incomparable"
    assert value("chapter3", "landVerdictKind",
                 {"n": 0, "min": None, "median": None}, 10_000_000) == "incomparable"


def _land_model_at(breakeven):
    pf = copy.deepcopy(PF)
    pf["land_price_context"]["breakeven_land_price_won_m2"] = breakeven
    return value("chapter3", "landModel", pf)


def test_the_land_argument_moves_with_the_verdict():
    """논거도 판정과 같은 갈래에서 나온다.

    "완성 자산이 토지 원가를 덮지 못한다"는 시드 전부가 손익분기 위일 때만 참이다.
    한 문장으로 박아 두면, 손익분기가 올라와 각주(`ctx.note`)가 "아래쪽 끝만
    덮는다"로 갈린 날 **같은 목록 안에서** 두 줄이 서로 다른 말을 한다.
    """
    fails = _land_model_at(10_000_000)
    assert fails["kind"] == "fails"
    assert value("chapter3", "landRationale", fails).endswith("토지 원가를 덮지 못한다.")

    partial = _land_model_at(17_029_258)
    assert partial["kind"] == "partial"
    arg = value("chapter3", "landRationale", partial)
    assert "아래쪽 끝만 덮는다" in arg and "덮지 못한다" not in arg

    stands = _land_model_at(80_000_000)
    assert stands["kind"] == "stands"
    arg = value("chapter3", "landRationale", stands)
    assert "중위까지 덮는다" in arg and "덮지 못한다" not in arg
    # 함수만 갈리고 화면은 옛 문장이면 소용없다 — 글줄에 그대로 실려 나가야 한다
    assert arg in value("chapter3", "landLines", stands)

    assert "말할 수 없다" in value("chapter3", "landRationale", {"kind": "incomparable"})


def test_the_land_headline_never_contradicts_the_argument_below_it():
    """중위가 손익분기 아래인 날 판정 한 줄이 "대부분 서지 않는다"라 하면 안 된다."""
    stands = value("chapter3", "verdictHtml", _land_model_at(80_000_000))
    assert "중위 필지로도 이 사업이 선다" in stands
    assert "서지 않는다" not in stands
    partial = value("chapter3", "verdictHtml", _land_model_at(17_029_258))
    assert "가장 싼 필지라면 이 사업이 선다" in partial
    fails = value("chapter3", "verdictHtml", _land_model_at(10_000_000))
    assert "프라임 필지에서는 이 사업이 서지 않는다" in fails
    gone = value("chapter3", "verdictHtml", {"kind": "incomparable"})
    assert "견줄 수 없다" in gone


# ================================================================== #
# ⑤ 실험실 — 세 갈래와 체인
# ================================================================== #
def lab_defaults():
    return value("lab", "defaults", MARKET, UNDERWRITING)


def test_the_lab_starts_from_the_downtown_representative_numbers():
    """기본값은 도심 대표치다 — 다만 칸이 보이는 자릿수로 **내려서** 실린다."""
    d = lab_defaults()
    cbd = MARKET["regions"]["도심"]
    a = UNDERWRITING["assumptions"]
    noi = value("engine", "noi", cbd["effective_rent_won_m2_mo"], 50000.0,
                a["efficiency"], cbd["vacancy"], a["opex_ratio"])["noi_won_y"]
    price = value("engine", "appraise", noi, cbd["cap"]["cap_income_based"])
    dp = {f["key"]: f["dp"] for f in value("lab", "fields")}
    assert d["noi"] == value("lab", "quantize", {"dp": dp["noi"]}, noi / 1e8)
    assert d["price"] == value("lab", "quantize", {"dp": dp["price"]}, price / 1e8)
    # 내림이므로 잘린 폭은 한 자리 안이다 — 대표치에서 멀어지지 않는다
    assert 0 <= price / 1e8 - d["price"] < 10 ** -dp["price"]
    assert 0 <= noi / 1e8 - d["noi"] < 10 ** -dp["noi"]
    assert d["ltv"] == pytest.approx(a["ltv_max"] * 100)
    assert d["dscr"] == pytest.approx(a["dscr_min"])
    assert d["rate"] == pytest.approx(a["loan_rate"] * 100)
    assert d["exitCap"] == pytest.approx(cbd["cap"]["cap_income_based"] * 100)


def test_the_number_in_the_box_is_exactly_the_number_the_engine_receives():
    """칸이 `1540.0` 을 보이면서 엔진이 1540.0668 을 받으면 옆의 환산값
    `154,006,680,000원` 이 틀린 등식으로 읽힌다 — 보이는 수가 곧 엔진의 수다."""
    d = lab_defaults()
    for spec in value("lab", "fields"):
        html = value("lab", "fieldRow", spec, d[spec["key"]])
        shown = re.search(r'id="lab-f-%s"[^>]*?value="([^"]*)"' % spec["key"],
                          html).group(1)
        assert float(shown) == d[spec["key"]], "칸의 글자와 엔진의 수가 다르다"
        frac = shown.split(".")[1] if "." in shown else ""
        assert len(frac) <= spec["dp"], "%s 가 칸의 자릿수를 넘는다" % shown
        # 그 자리의 환산값도 보이는 수에서 나온다
        echo = value("lab", "engineEcho", spec, d[spec["key"]])
        digits = int(re.sub(r"[^0-9]", "", echo))
        if spec["scale"] == 1e8:
            assert digits == round(float(shown) * 1e8)
        else:
            assert digits == round(float(shown) * spec["scale"] *
                                   (10 ** 6 if spec["scale"] == 0.01 else 10 ** 4))


def test_the_units_are_converted_once_and_only_once():
    e = value("lab", "toEngine", {"price": 1540.1, "noi": 62.35, "ltv": 55,
                                  "dscr": 1.3, "rate": 4.27, "exitCap": 4.0485})
    assert e["price"] == pytest.approx(154_010_000_000.0)
    assert e["noi"] == pytest.approx(6_235_000_000.0)
    assert e["ltv"] == pytest.approx(0.55)
    assert e["rate"] == pytest.approx(0.0427)
    assert e["exitCap"] == pytest.approx(0.040485)


def test_the_chain_really_feeds_the_loan_into_the_hold_and_the_refi():
    d = lab_defaults()
    res = value("lab", "run", d)
    assert res["ok"] is True
    e = value("lab", "toEngine", d)
    loan = value("engine", "max_loan", e["noi"], e["price"], e["ltv"], e["dscr"],
                 res["fixed"]["debtYieldMin"], e["rate"])
    assert res["loan"]["won"] == pytest.approx(loan["loan_won"], rel=1e-12)
    hold = value("engine", "hold_model", e["price"], loan["loan_won"], e["rate"],
                 e["noi"], res["fixed"]["noiGrowth"], e["exitCap"],
                 res["fixed"]["holdYears"], res["fixed"]["costRate"])
    assert res["hold"]["irr"] == pytest.approx(hold["equity_irr"], rel=1e-9)
    refi = value("engine", "refi_test", e["noi"], loan["loan_won"], e["price"],
                 e["dscr"], res["fixed"]["refiLtvMax"], e["rate"])
    assert res["refi"]["headroomBp"] == pytest.approx(refi["headroom_bp"], rel=1e-9)


def test_a_decimal_typed_into_a_percent_box_is_caught_by_the_gate():
    """매각 cap 칸에 0.03 을 넣으면 0.03% 다 — 물리 게이트가 잡아야 한다."""
    d = dict(lab_defaults(), exitCap=0.03)
    res = value("lab", "run", d)
    assert res["ok"] is False
    gates = [b for b in res["banners"] if b["kind"] == "gate"]
    assert gates, "게이트가 잡히지 않았다: %s" % res["banners"]
    assert "단위를 의심하라" in gates[0]["head"] + gates[0]["text"]


def test_a_percent_typed_where_a_ratio_belongs_is_caught_too():
    d = dict(lab_defaults(), exitCap=304.52)
    res = value("lab", "run", d)
    assert res["ok"] is False
    assert any(b["kind"] == "gate" for b in res["banners"])


def test_an_out_of_domain_input_is_an_input_error_not_a_gate():
    d = dict(lab_defaults(), ltv=200)
    res = value("lab", "run", d)
    assert res["ok"] is False
    kinds = [b["kind"] for b in res["banners"]]
    assert "input" in kinds and "gate" not in kinds


def test_the_gate_is_caught_before_the_input_error_never_merged():
    """자바스크립트에서 RangeError·TypeError 는 둘 다 Error 의 하위형이다."""
    d = dict(lab_defaults(), dscr=130)
    res = value("lab", "run", d)
    assert [b["kind"] for b in res["banners"] if b["kind"] in ("gate", "input")] \
        == ["gate"]
    assert value("lab", "kindOf", "range") == "gate"
    assert value("lab", "kindOf", "type") == "input"
    assert value("lab", "kindOf", "plain") == "other"


def test_a_non_numeric_field_is_an_input_error():
    d = dict(lab_defaults(), price=None)
    res = value("lab", "run", d)
    assert res["ok"] is False
    assert any(b["kind"] == "input" for b in res["banners"])


def test_implausible_is_a_banner_with_its_reason_not_an_exception():
    d = dict(lab_defaults(), ltv=0.5)
    res = value("lab", "run", d)
    assert res["ok"] is True, "implausible 은 계산을 멈추지 않는다"
    imp = [b for b in res["banners"] if b["kind"] == "implausible"]
    assert imp, "사유 배너가 없다: %s" % res["banners"]
    assert "단위" in imp[0]["text"] or "자릿수" in imp[0]["text"]


def test_one_failed_stage_does_not_erase_the_readings_of_the_stages_before_it():
    d = dict(lab_defaults(), exitCap=0.03)   # hold_model 만 게이트에 걸린다
    res = value("lab", "run", d)
    assert res["loan"]["ok"] is True
    assert res["refi"]["ok"] is True
    assert res["hold"]["ok"] is False
    keys = [r["k"] for r in value("lab", "readings", res)]
    assert "대출가능액" in keys and "차환 여유" in keys


def test_a_row_that_cannot_be_computed_becomes_a_dash_never_a_missing_row():
    """행이 통째로 사라지면 묻지 않은 것으로 읽힌다 — 앞 장들의 줄표 규약."""
    ok = value("lab", "readings", value("lab", "run", lab_defaults()))
    gated = value("lab", "readings",
                  value("lab", "run", dict(lab_defaults(), exitCap=0.03)))
    assert [r["k"] for r in gated if r["k"] in ("매각가", "지분 IRR")] == \
        ["매각가", "지분 IRR"]
    assert [r["v"] for r in gated if r["k"] == "매각가"] == ["―"]
    assert [r["k"] for r in ok] == [r["k"] for r in gated], \
        "판독표의 줄 수와 순서는 상태에 따라 달라지지 않는다"


def test_the_banner_order_holds_even_when_the_implausible_flag_joins():
    """정렬은 마지막에 한 번 — 뒤에 밀어 넣은 배너만 순서 밖에 남으면 안 된다."""
    d = dict(lab_defaults(), exitCap=0.03, ltv=0.5)
    kinds = [b["kind"] for b in value("lab", "run", d)["banners"]]
    assert kinds == ["gate", "implausible"], kinds


def test_the_live_text_says_the_reason_when_nothing_can_be_computed():
    d = dict(lab_defaults(), ltv=200)
    res = value("lab", "run", d)
    said = value("lab", "liveText", res)
    assert "LTV" in said or "입력" in said
    assert said.strip() != ""


def test_the_field_row_binds_its_label_and_silences_the_output():
    """Ⅱ장이 파킹한 3중 낭독을 되풀이하지 않는다 — output 은 스스로 말하지 않는다."""
    specs = value("lab", "fields")
    assert [f["key"] for f in specs] == \
        ["price", "noi", "ltv", "dscr", "rate", "exitCap"]
    for spec in specs:
        html = value("lab", "fieldRow", spec, 1.0)
        assert 'for="lab-f-%s"' % spec["key"] in html
        assert 'id="lab-f-%s"' % spec["key"] in html
        assert 'aria-live="off"' in html


# ================================================================== #
# ⑥ Task 6 이월 — 도면 각주의 과장, 사라지는 행, 기본값의 사연
# ================================================================== #
def test_the_axis_footnote_does_not_call_the_whole_dry_band_equity():
    """수면 위 두께는 자기자본이 아니다.

    28개월째 마른 두께는 324억이고 자기자본은 256억이다 — 차이는 아직 원금으로
    얹히지 않은 발생이자이고, 준공 뒤에는 임대기간의 누적 순유출이다. 각주가
    "위가 자기자본이다"라고 말하면 그림 안의 지시선(준공 달 하나뿐)과 정면으로
    부딪힌다. 같은 판에서 두 문장이 다른 말을 하면 하나는 반드시 틀린다.
    """
    svg = value("chapter3", "renderDeposit", PF, WIDE)
    assert "위가 자기자본이다" not in svg
    labels = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
    joined = " ".join(labels)
    assert "대출잔액" in joined
    assert "자본화되지 않은 이자" in joined, "부푼 두께의 정체가 각주에 없다"
    assert "운영 순유출" in joined or "순현금" in joined, \
        "준공 뒤의 두께가 무엇인지도 같은 각주가 말해야 한다"


@pytest.mark.parametrize("hurt,kind", [
    ({"dscr": 130}, "gate"),      # 물리 게이트 — 배수 칸에 퍼센트를 적은 사고
    ({"ltv": 200}, "input"),      # 입력 오류 — 한도가 정의역 밖이다
])
def test_the_readings_keep_every_row_even_when_the_loan_stage_is_refused(hurt, kind):
    """대출이 거절되면 자기자본·DSCR 행이 통째로 사라지고 있었다.

    행이 사라지면 판독표의 줄 수가 상태마다 달라지고, 읽는 사람은 그 값을
    **묻지 않은 것**으로 읽는다. 없는 값은 0 도 아니고 침묵도 아니다 — 줄표다.
    """
    base = value("lab", "readings", value("lab", "run", lab_defaults()))
    res = value("lab", "run", dict(lab_defaults(), **hurt))
    assert res["loan"]["ok"] is False and res["loan"]["kind"] == kind
    rows = value("lab", "readings", res)
    assert [r["k"] for r in rows] == [r["k"] for r in base], \
        "거절 상태의 판독표가 기준 상태와 다른 줄을 낸다"
    got = {r["k"]: r["v"] for r in rows}
    assert got["자기자본"] == "―" and got["DSCR"] == "―"
    for key in ("자기자본", "DSCR"):
        note = [r["note"] for r in rows if r["k"] == key][0]
        assert note.strip(), "%s 가 왜 비었는지 사유가 없다" % key


def test_the_readings_survive_a_field_that_is_not_a_number_at_all():
    """빈 칸은 0 이 아니다 — 엔진 인자가 아예 만들어지지 않는 갈래다."""
    base = value("lab", "readings", value("lab", "run", lab_defaults()))
    res = value("lab", "run", dict(lab_defaults(), price=None))
    assert res["engine"] is None
    rows = value("lab", "readings", res)
    assert [r["k"] for r in rows] == [r["k"] for r in base]
    assert all(r["v"] == "―" for r in rows)


def test_the_lab_says_its_defaults_are_the_downtown_numbers_rounded_down():
    """Ⅱ장은 1,540.1·5.61%, 실험실은 1,540.0·5.58% 다 — 그 차이의 사연을 적는다.

    같은 데이터에서 나온 두 화면이 다른 수를 보이면, 사연이 없는 쪽은 오류로
    읽힌다. 사연은 하나다: 실험실의 칸은 **보이는 수가 곧 엔진의 수**여야 해서
    기본값을 칸의 자릿수로 내렸고, 파생 판독은 그 내린 수로 다시 계산된다.
    """
    fixed = value("lab", "fixedHtml", value("lab", "defaultFixed", UNDERWRITING))
    assert "도심 대표치" in fixed
    assert "자릿수" in fixed and ("내린" in fixed or "내림" in fixed)
    said = " ".join(value("lab", "lines", value("lab", "run", lab_defaults())))
    assert "Ⅱ장" in said, "글줄이 어느 장과 견주는지 밝히지 않는다"
    assert "자릿수" in said
