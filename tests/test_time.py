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
    assert "1.4002" in pair and "0.0232" in pair
    assert "하나만 인용하지 말 것" in pair


def test_the_stress_rows_say_which_llcr_definition_they_are():
    """행의 llcr 은 매각대금 포함 값 하나다 — 그 사실이 화면에 남아야 한다."""
    m = value("chapter3", "stressModel", PF)
    assert m["llcrNote"] == PF["stress"]["llcr_note"]
    assert m["modelLlcrNote"] == PF["model"]["llcr_note"]
    html = value("chapter3", "stressTableHtml", m)
    assert "매각대금" in html
    assert "1.4002" in html and "0.0232" in html, "표 안에 두 값이 함께 있어야 한다"


def test_the_delta_sign_is_not_clipped_because_the_ladder_is_positive():
    m = value("chapter3", "stressModel", PF)
    ladder = [r for r in m["rows"] if r["group"] == "equity"]
    assert len(ladder) == 4
    assert all(r["delta"] > 0 for r in ladder), "자기자본을 줄이면 IRR 은 오른다"
    html = value("chapter3", "stressTableHtml", m)
    assert "+10.64" in html or "+0.1064" in html


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


# ================================================================== #
# ③ 자기자본 제도 사다리 5 → 20%
# ================================================================== #
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
    assert "21.08" in lines and "10.98" in lines
    assert "1.099" in lines or "1.0988" in lines


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
    assert m["stands"] is False, "시드 최저조차 손익분기를 넘는다"
    # 시드가 손익분기 밑으로 내려가면 판정이 뒤집혀야 한다 — 문장이 아니라 계산이다
    pf = copy.deepcopy(PF)
    pf["land_price_context"]["seed_land_price_won_m2"]["min"] = 9_000_000
    assert value("chapter3", "landModel", pf)["stands"] is True


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


# ================================================================== #
# ⑤ 실험실 — 세 갈래와 체인
# ================================================================== #
def lab_defaults():
    return value("lab", "defaults", MARKET, UNDERWRITING)


def test_the_lab_starts_from_the_downtown_representative_numbers():
    d = lab_defaults()
    cbd = MARKET["regions"]["도심"]
    a = UNDERWRITING["assumptions"]
    noi = value("engine", "noi", cbd["effective_rent_won_m2_mo"], 50000.0,
                a["efficiency"], cbd["vacancy"], a["opex_ratio"])["noi_won_y"]
    price = value("engine", "appraise", noi, cbd["cap"]["cap_income_based"])
    assert d["noi"] == pytest.approx(noi / 1e8, rel=1e-9)
    assert d["price"] == pytest.approx(price / 1e8, rel=1e-9)
    assert d["ltv"] == pytest.approx(a["ltv_max"] * 100)
    assert d["dscr"] == pytest.approx(a["dscr_min"])
    assert d["rate"] == pytest.approx(a["loan_rate"] * 100)
    assert d["exitCap"] == pytest.approx(cbd["cap"]["cap_income_based"] * 100)


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
