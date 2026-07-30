"""개발 PF 골든 테스트 — 월별 인출·이자 스케줄과 스트레스 표.

기대값은 엔진과 독립적으로 손계산(닫힌형 + `fractions.Fraction` 정확 산술 +
`decimal.Decimal` 60자리 IRR)으로 확정했다. 엔진과 어긋나면 고쳐야 하는 쪽은
엔진이지 이 표가 아니다.

## G-PF-001 입력

토지 300억 · 공사(hard) 500억 · 간접비 soft 12%(= 60억) · 공사기간 24개월 ·
equity 200억 · 금리 6% · 취급수수료 1.5% · 안정화 NOI 60억/년 ·
lease-up 12개월 · exit cap 5%.

## 이 골든이 전제하는 설계 결정 여덟

브리프가 "월별 전개"만 정하고 열어 둔 자리를 이렇게 못박았다(전부
`pf.py` docstring·`assumptions.decisions` 에 같은 문장으로 실려 있다).

| # | 결정 | 대안이었다면 |
|---|------|--------------|
| D1 | 토지비 전액 m0, (hard + soft)는 공사기간 균등 분산 | S자 곡선 분산 |
| D2 | 수수료 = fee_rate × (기본비용 − equity), m0 에 대출로 인출 | 총대출 기준(순환) |
| D3 | 월 소요액에 equity 를 월 순서대로 먼저 소진, 잔액이 대출 인출 | 매월 정률 분담 |
| D4 | 인출은 월초, 그 달 이자 = **인출 후** 잔액 × 금리/12 | 월초 잔액(=이자 4.8억 작다) |
| D5 | 건설기간 이자는 단리로 쌓아 준공 시 일시 자본화, 임대기간 이자는 현금 지급 | 월복리·이자유보계정 |
| D6 | NOI_k = 안정화 월NOI × k/L (k=1..L), 마지막 임대월 말 매각 | (k−1)/L·즉시 만실 |
| D7 | 분기 집계 — 인출은 월초라 q=m//3, 영업·매각은 월말이라 q=m//3+1 | 월 중앙 |
| D8 | LLCR = [Σ NOI_k/(1+r/12)^k + 매각가/(1+r/12)^L] ÷ 대출, 준공 시점 기준 | 영구 NOI |

## 월별 인출·이자 스케줄(건설기간 24개월)

월 공사+간접 = (500 + 60)억 ÷ 24 = 70/3 = 23.3333…억.
수수료 = 0.015 × (860 − 200)억 = 0.015 × 660억 = **9.9억**(m0 인출).

| m    | 그 달 비용(억)        | equity(억) | 대출인출(억) | 인출 후 잔액(억) | 그 달 이자 = 잔액×0.5%(억) |
|------|-----------------------|------------|--------------|------------------|----------------------------|
| 0    | 300 + 70/3 + 9.9 = 333.2333… | 200   | 133.2333…    | 133.2333…        | 0.6661666…                 |
| 1    | 23.3333…              | 0          | 23.3333…     | 156.5666…        | 0.7828333…                 |
| 2    | 23.3333…              | 0          | 23.3333…     | 179.9            | 0.8995                     |
| …    | …                     | 0          | …            | …                | …                          |
| 23   | 23.3333…              | 0          | 23.3333…     | 669.9            | 3.3495                     |

잔액이 등차수열이라 닫힌형으로 접힌다(억 단위).

    B_m = (3997 + 700m) / 30            (m = 0..23)
    Σ B_m = [24×3997 + 700×(0+1+…+23)] / 30 = (95,928 + 193,200)/30
          = 289,128/30 = **9,637.6억·월**
    건설기간 이자 = 9,637.6 × 0.06/12 = 9,637.6 × 0.005 = **48.188억**

총 대출인출(자본화 전) = 660 + 9.9 = 669.9억(= B_23 ✓).

## 골든 확정값

| 항목        | 산식                             | 값                                    |
|-------------|----------------------------------|---------------------------------------|
| interest_won| 위 스케줄 합                     | 4,818,800,000원 (48.188억)            |
| fee_won     | 0.015 × 660억                    | 990,000,000원 (9.9억)                 |
| total_cost  | 860억 + 9.9억 + 48.188억         | 91,808,800,000원 (918.088억)          |
| loan_won    | 총사업비 − equity = 669.9 + 48.188| 71,808,800,000원 (718.088억)          |
| ltc         | 89,761/114,761                   | 0.78215595890590008800899…            |
| exit_value  | 60억 ÷ 0.05                      | 120,000,000,000원 (1,200억)           |
| profit      | 1,200억 − 918.088억              | 28,191,200,000원 (281.912억)          |
| margin      | 35,239/114,761                   | 0.30706424656459947194604…            |

## 지분 분기 현금흐름과 IRR

월 현금이자(임대기간) = 718.088억 × 0.005 = 3.59044억. NOI_k = 5억 × k/12.
D7 의 분기 집계(임대 m24~m35 → q9~q12)로 접으면 흐름은 13개다.

| q      | 구성                                          | 값(원)          |
|--------|-----------------------------------------------|-----------------|
| q0     | −equity                                       | −20,000,000,000 |
| q1~q8  | 건설기간 — 지분 현금흐름 없음                 | 0               |
| q9     | (5/12)(1+2+3)억 − 3×3.59044억                 | −827,132,000    |
| q10    | (5/12)(4+5+6)억 − 3×3.59044억                 | −452,132,000    |
| q11    | (5/12)(7+8+9)억 − 3×3.59044억                 | −77,132,000     |
| q12    | (5/12)(10+11+12)억 − 3×3.59044억 + (1,200−718.088)억 | +48,489,068,000 |

Σ = 27,132,672,000원. 이 13개 흐름의 분기이율을 `Decimal`(정밀도 60) 뉴턴법으로
풀어

    x = 0.07353395320665226766037846981624616313189649361134898942806…

를 얻었고 같은 정밀도의 이분법(구간 [−0.5, 1.0], 400회)으로 교차검증했다(두 방법
차 1.7e−60, NPV(x) = 5e−49). 연율화하면

    (1 + x)^4 − 1 = **0.328198968342281365611986267680842715159…**

엑셀 대조 형태이기도 하다 — 위 13개 값을 A1:A13 에 세로로 넣고
`=(1+IRR(A1:A13))^4-1`.

## LLCR

준공 시점 기준, 월이율 0.5% 로 할인한다(1.005^12 = 1.061677811864499568789707…).

    PV(NOI)  = Σ_{k=1..12} (5억 × k/12) / 1.005^k = 3,118,022,092.9956394915…원
    PV(매각) = 1,200억 / 1.005^12               = 113,028,640,759.910153949…원
    llcr = (PV(NOI) + PV(매각)) ÷ 718.088억
         = 631,348,914,549,948,301,940,532,527,093,750
           / 390,337,585,441,871,240,372,768,544,556,161
         = **1.61744330573558941858626432704654083447…**

## 부동소수점 허용오차에 대하여

위 값은 전부 **정확한 유리수**다. 엔진은 float 로 월별 이자를 누적하므로
interest_won 이 4,818,799,999.999999 로, ltc 가 마지막 2 ulp 만큼 어긋난다.
그래서 금액은 1원, 비율·IRR 은 1e−12 를 허용오차로 둔다(브리프 초안의 `==` 를
그대로 쓰면 골든이 아니라 부동소수점 누적 순서를 시험하게 된다).
"""

import json
import math

import pytest

from src.analysis import pf
from src.analysis.caprate import CAP_MAX, CAP_MIN
from src.analysis.pf import pf_model, stress

# G-PF-001 입력 — 아래 테스트 전부가 이 한 벌을 쓴다.
G_PF_001 = {
    "land_won": 30_000_000_000,
    "hard_cost_won": 50_000_000_000,
    "soft_cost_ratio": 0.12,
    "months_build": 24,
    "equity_won": 20_000_000_000,
    "loan_rate": 0.06,
    "fee_rate": 0.015,
    "stabilized_noi_won_y": 6_000_000_000,
    "lease_up_months": 12,
    "exit_cap": 0.05,
}

# 손계산 확정값(위 docstring 유도 표).
G_INTEREST = 4_818_800_000.0
G_FEE = 990_000_000.0
G_TOTAL_COST = 91_808_800_000.0
G_LOAN = 71_808_800_000.0
G_LTC = 0.7821559589059000880089926020163644443670   # 89,761/114,761
G_PROFIT = 28_191_200_000.0
G_MARGIN = 0.3070642465645994719460443879018133337981  # 35,239/114,761
G_IRR = 0.328198968342281365611986267680842715159
G_LLCR = 1.61744330573558941858626432704654083447


# ── 브리프 확정 골든 2건(축자 — `...` 를 손계산으로 채웠다) ──────────────

# | G-PF-001 | 토지 300억·공사 500억·soft 12%(60억)·24개월·equity 200억·금리 6%·fee 1.5% |
# |   기본비용 = 860억 · 대출원금 = 860-200 = 660억 + fee 9.9억 + 이자 48.188억 |
# |   NOI 60억/y·lease_up 12개월·exit 5% → 매각 1,200억 |
def test_golden_pf_small():
    r = pf_model({"land_won": 30_000_000_000, "hard_cost_won": 50_000_000_000,
                  "soft_cost_ratio": 0.12, "months_build": 24,
                  "equity_won": 20_000_000_000, "loan_rate": 0.06, "fee_rate": 0.015,
                  "stabilized_noi_won_y": 6_000_000_000, "lease_up_months": 12,
                  "exit_cap": 0.05})
    assert abs(r["ltc"] - G_LTC) < 1e-12          # 71,808.8/91,808.8 = 89,761/114,761
    assert abs(r["profit"] - G_PROFIT) < 1.0      # 1,200억 − 918.088억 = 281.912억
    assert len(r["monthly"]) == 24 + 12


def test_stress_has_8_scenarios_and_equity_step():
    rows = stress(G_PF_001)
    assert len(rows) >= 8
    names = {r["name"] for r in rows}
    assert "자기자본 20%" in names and "공사비 +10%" in names


# ── 골든 나머지 항목(같은 케이스, 유도 표의 모든 칸) ────────────────────

def test_golden_pf_small_full_row():
    r = pf_model(G_PF_001)
    assert abs(r["interest_won"] - G_INTEREST) < 1.0
    assert abs(r["fee_won"] - G_FEE) < 1.0
    assert abs(r["total_cost"] - G_TOTAL_COST) < 1.0
    assert abs(r["loan_won"] - G_LOAN) < 1.0
    assert r["exit_value"] == 120_000_000_000.0
    assert abs(r["margin"] - G_MARGIN) < 1e-12
    assert abs(r["equity_irr"] - G_IRR) < 1e-12
    assert abs(r["llcr"] - G_LLCR) < 1e-12


def test_golden_quarterly_cashflows_match_the_hand_table():
    r = pf_model(G_PF_001)
    cf = r["cashflows_q"]
    assert len(cf) == 13                      # q0 + 36개월/3
    assert cf[0] == -20_000_000_000.0
    assert all(c == 0 for c in cf[1:9])       # 건설기간엔 지분 현금흐름이 없다
    assert abs(cf[9] - (-827_132_000.0)) < 1.0
    assert abs(cf[10] - (-452_132_000.0)) < 1.0
    assert abs(cf[11] - (-77_132_000.0)) < 1.0
    assert abs(cf[12] - 48_489_068_000.0) < 1.0


# ── 월별 스케줄 ─────────────────────────────────────────────────────────

def test_monthly_schedule_first_and_last_construction_month():
    r = pf_model(G_PF_001)
    m = r["monthly"]
    per = (50_000_000_000 + 6_000_000_000) / 24          # 70/3 억

    assert m[0]["phase"] == "construction"
    assert abs(m[0]["cost_won"] - (30_000_000_000 + per + G_FEE)) < 1.0
    assert m[0]["equity_draw_won"] == 20_000_000_000.0    # equity 선투입 — 첫 달에 소진
    assert abs(m[0]["loan_draw_won"] - 13_323_333_333.333) < 1.0
    assert abs(m[0]["loan_balance_won"] - 13_323_333_333.333) < 1.0
    assert abs(m[0]["interest_won"] - 66_616_666.666) < 1.0

    assert m[1]["equity_draw_won"] == 0.0                 # 이미 다 썼다
    assert abs(m[1]["loan_balance_won"] - 15_656_666_666.666) < 1.0

    last = m[23]
    assert abs(last["interest_won"] - 334_950_000.0) < 1.0   # 669.9억 × 0.5%
    # 준공 달의 잔액은 자본화 뒤 값이다 = 669.9억 + 48.188억
    assert abs(last["loan_balance_won"] - G_LOAN) < 1.0
    assert last["interest_capitalized"] is True


def test_draws_plus_capitalized_interest_equal_the_loan_and_the_cost_gap():
    """대출원금의 두 정의(스케줄 합 · 총사업비−equity)가 같은 값이어야 한다."""
    r = pf_model(G_PF_001)
    drawn = sum(row["loan_draw_won"] for row in r["monthly"])
    capitalized = sum(row["interest_won"] for row in r["monthly"]
                      if row["interest_capitalized"])
    assert abs(drawn - 66_990_000_000.0) < 1.0
    assert abs(drawn + capitalized - r["loan_won"]) < 1.0
    assert abs(r["total_cost"] - r["assumptions"]["equity_won"] - r["loan_won"]) < 1.0
    assert abs(sum(row["equity_draw_won"] for row in r["monthly"])
               - r["assumptions"]["equity_won"]) < 1.0


def test_interest_is_simple_not_compounded():
    """단리 규약 — 총이자가 Σ(잔액)×r/12 와 같고, 월복리보다 작다."""
    r = pf_model(G_PF_001)
    con = [row for row in r["monthly"] if row["phase"] == "construction"]
    hand = sum(row["loan_balance_won"] for row in con[:-1]) + 66_990_000_000.0
    assert abs(r["interest_won"] - hand * 0.06 / 12) < 1.0

    # 같은 스케줄을 월복리로 굴리면(이자에 이자) 더 크다 — 그 차이가 곧 규약이다.
    bal = 0.0
    for row in con:
        bal += row["loan_draw_won"]
        bal *= 1 + 0.06 / 12
    assert bal - 66_990_000_000.0 > r["interest_won"]


def test_lease_up_noi_ramps_linearly_to_stabilization():
    r = pf_model(G_PF_001)
    m = r["monthly"]
    assert m[24]["phase"] == "lease_up"
    assert abs(m[24]["noi_won"] - 500_000_000 / 12) < 1e-6     # k=1
    assert abs(m[29]["noi_won"] - 500_000_000 * 6 / 12) < 1e-6  # k=6
    assert abs(m[35]["noi_won"] - 500_000_000) < 1e-6           # k=12 = 안정화
    assert sum(row["noi_won"] for row in m) == pytest.approx(3_250_000_000.0)
    # 임대기간 이자는 자본화하지 않고 현금으로 낸다.
    assert all(row["interest_capitalized"] is False
               for row in m if row["phase"] == "lease_up")
    assert abs(m[24]["interest_won"] - 359_044_000.0) < 1.0


def test_sale_lands_on_the_last_month_only():
    r = pf_model(G_PF_001)
    m = r["monthly"]
    assert all(row["exit_cash_won"] == 0.0 for row in m[:-1])
    assert abs(m[-1]["exit_cash_won"] - (120_000_000_000.0 - G_LOAN)) < 1.0


def test_zero_lease_up_sells_at_completion():
    r = pf_model({**G_PF_001, "lease_up_months": 0})
    assert len(r["monthly"]) == 24
    assert r["monthly"][-1]["phase"] == "construction"
    assert abs(r["monthly"][-1]["exit_cash_won"]
               - (120_000_000_000.0 - r["loan_won"])) < 1.0
    # 잔여 NOI 가 없으니 LLCR 은 매각가 하나로 결정된다(할인 0개월).
    assert abs(r["llcr"] - 120_000_000_000.0 / r["loan_won"]) < 1e-12


def test_equity_spills_into_later_months_when_it_exceeds_month_zero():
    """equity 선투입 — 첫 달 소요를 넘는 자기자본은 다음 달로 넘어가 소진된다."""
    r = pf_model({**G_PF_001, "equity_won": 40_000_000_000})
    m = r["monthly"]
    assert abs(m[0]["equity_draw_won"] - m[0]["cost_won"]) < 1.0   # 첫 달은 전액 자기자본
    assert m[0]["loan_draw_won"] == 0.0
    assert m[1]["equity_draw_won"] > 0.0                            # 남은 자기자본이 이월
    assert sum(row["equity_draw_won"] for row in m) == pytest.approx(40_000_000_000.0)


# ── 입력 가드(ValueError) ───────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(G_PF_001))
def test_nan_in_any_input_is_a_value_error(key):
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, key: float("nan")})


@pytest.mark.parametrize("key", ["land_won", "hard_cost_won", "loan_rate",
                                 "stabilized_noi_won_y", "exit_cap"])
def test_infinite_input_is_a_value_error(key):
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, key: float("inf")})


def test_missing_required_key_is_a_value_error_naming_it():
    bad = {k: v for k, v in G_PF_001.items() if k != "exit_cap"}
    with pytest.raises(ValueError, match="exit_cap"):
        pf_model(bad)


def test_unknown_key_is_a_value_error_so_typos_do_not_default_silently():
    with pytest.raises(ValueError, match="lease_up_month"):
        pf_model({**G_PF_001, "lease_up_month": 12})


def test_optional_keys_default_to_the_planned_values():
    lean = {k: v for k, v in G_PF_001.items()
            if k not in ("soft_cost_ratio", "fee_rate")}
    r = pf_model(lean)
    assert r["assumptions"]["soft_cost_ratio"] == 0.12
    assert r["assumptions"]["fee_rate"] == 0.015
    assert abs(r["total_cost"] - G_TOTAL_COST) < 1.0


@pytest.mark.parametrize("bad", [0, -1, 24.0, True])
def test_months_build_must_be_a_positive_int(bad):
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, "months_build": bad})


@pytest.mark.parametrize("bad", [-1, 12.0, True])
def test_lease_up_months_must_be_a_nonnegative_int(bad):
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, "lease_up_months": bad})


@pytest.mark.parametrize("key,bad", [
    ("land_won", -1.0),
    ("hard_cost_won", -1.0),
    ("hard_cost_won", 0.0),
    ("soft_cost_ratio", -0.01),
    ("soft_cost_ratio", 1.5),
    ("equity_won", -1.0),
    ("loan_rate", -0.01),
    ("loan_rate", 1.5),
    ("fee_rate", -0.01),
    ("fee_rate", 1.0),
    ("stabilized_noi_won_y", -1.0),
])
def test_out_of_domain_inputs_are_value_errors(key, bad):
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, key: bad})


def test_inputs_must_be_a_mapping():
    with pytest.raises(ValueError):
        pf_model([("land_won", 1)])


@pytest.mark.parametrize("bad", [None, "30000000000", True, object()])
def test_non_numeric_input_is_a_value_error_not_a_type_error(bad):
    """JSON 의 null·문자열이 흘러와도 유형 규약(입력 오류 = ValueError)을 지킨다.

    `float()` 에 맡기면 None 은 TypeError(하류의 `except ValueError` 를 빠져나간다),
    "30000000000" 은 조용한 통과, True 는 1원이 된다.
    """
    with pytest.raises(ValueError):
        pf_model({**G_PF_001, "land_won": bad})


# ── 물리 게이트(RuntimeError) ───────────────────────────────────────────

@pytest.mark.parametrize("cap", [0.019, 0.121, 4.5])
def test_exit_cap_outside_the_gate_is_a_runtime_error(cap):
    with pytest.raises(RuntimeError, match="cap"):
        pf_model({**G_PF_001, "exit_cap": cap})


@pytest.mark.parametrize("cap", [CAP_MIN, CAP_MAX])
def test_exit_cap_gate_edges_are_inclusive(cap):
    pf_model({**G_PF_001, "exit_cap": cap})   # 예외가 나면 실패다


def test_exit_cap_gate_uses_the_caprate_constants():
    """게이트 상수는 caprate 것을 임포트해 쓴다 — 여기 다시 적으면 따로 움직인다."""
    assert (pf.CAP_MIN, pf.CAP_MAX) == (CAP_MIN, CAP_MAX)


def test_equity_above_total_cost_trips_the_ltc_gate():
    with pytest.raises(RuntimeError, match="LTC"):
        pf_model({**G_PF_001, "equity_won": 90_000_000_000})


def test_all_equity_leaves_no_loan_no_fee_no_interest_and_no_llcr():
    """자기자본이 기본비용과 같으면 빌릴 것이 없다 — 수수료·이자도 0 이다."""
    r = pf_model({**G_PF_001, "equity_won": 86_000_000_000})
    assert r["ltc"] == 0.0
    assert r["fee_won"] == 0.0
    # 월 소요액을 자기자본으로 정확히 다 채우고도 8.6e10 위의 float 간격(≈1.5e−5원)
    # 만큼이 마지막 달에 남아 대출로 인출된다 — 1원 미만의 잔여이지 구조가 아니다.
    assert abs(r["interest_won"]) < 1.0
    assert r["total_cost"] == 86_000_000_000.0
    assert r["llcr"] is None            # 나눌 대출이 없으면 값을 지어내지 않는다
    assert r["equity_irr"] is not None


def test_zero_equity_gives_ltc_one_and_passes_the_gate():
    r = pf_model({**G_PF_001, "equity_won": 0})
    assert r["ltc"] == 1.0
    assert r["equity_irr"] is None      # 지분 유출이 없으면 IRR 이 정의되지 않는다


# ── 출력 계약 ───────────────────────────────────────────────────────────

def test_result_carries_assumptions_notes_caveats_and_decisions():
    a = pf_model(G_PF_001)["assumptions"]
    for key in ("land_won", "hard_cost_won", "soft_cost_ratio", "months_build",
                "equity_won", "loan_rate", "fee_rate", "stabilized_noi_won_y",
                "lease_up_months", "exit_cap", "notes", "caveats", "decisions"):
        assert key in a
    assert len(a["decisions"]) == 8      # D1~D8
    assert a["notes"] and a["caveats"]


def test_result_is_json_serializable():
    json.dumps(pf_model(G_PF_001))
    json.dumps(stress(G_PF_001))


def test_inputs_are_not_mutated():
    before = dict(G_PF_001)
    pf_model(G_PF_001)
    stress(G_PF_001)
    assert G_PF_001 == before


# ── 스트레스 ────────────────────────────────────────────────────────────

def test_stress_rows_carry_the_contracted_keys():
    rows = stress(G_PF_001)
    for row in rows:
        assert set(row) == {"name", "shock", "delta", "equity_irr", "ltc", "llcr"}
        assert isinstance(row["name"], str) and isinstance(row["shock"], str)


def test_stress_covers_every_planned_scenario():
    names = [r["name"] for r in stress(G_PF_001)]
    assert names == [
        "공사비 +5%", "공사비 +10%",
        "준공지연 +6개월", "준공지연 +12개월",
        "금리 +1%p", "금리 +2%p",
        "임대개시 +6개월",
        "안정화 NOI −10%",
        "exit cap +0.5%p", "exit cap +1.0%p",
        "매각가 −10%",
        "자기자본 5%", "자기자본 10%", "자기자본 15%", "자기자본 20%",
    ]


def test_stress_delta_is_the_irr_gap_against_the_base_case():
    base = pf_model(G_PF_001)["equity_irr"]
    rows = {r["name"]: r for r in stress(G_PF_001)}
    row = rows["금리 +2%p"]
    assert abs(row["delta"] - (row["equity_irr"] - base)) < 1e-15
    assert row["delta"] < 0                      # 금리가 오르면 지분수익률이 내린다


def test_stress_hard_cost_scenario_equals_a_direct_rerun():
    rows = {r["name"]: r for r in stress(G_PF_001)}
    direct = pf_model({**G_PF_001, "hard_cost_won": 55_000_000_000})
    assert abs(rows["공사비 +10%"]["equity_irr"] - direct["equity_irr"]) < 1e-15
    assert abs(rows["공사비 +10%"]["ltc"] - direct["ltc"]) < 1e-15
    assert abs(rows["공사비 +10%"]["llcr"] - direct["llcr"]) < 1e-15


def test_stress_price_cut_is_exactly_a_ten_percent_lower_sale():
    """매각가 −10% 는 같은 NOI 에 cap ÷ 0.9 다(매각가 = NOI/cap 이므로 정확히 0.9배)."""
    direct = pf_model({**G_PF_001, "exit_cap": 0.05 / 0.9})
    assert abs(direct["exit_value"] - 0.9 * 120_000_000_000.0) < 1.0
    rows = {r["name"]: r for r in stress(G_PF_001)}
    assert abs(rows["매각가 −10%"]["llcr"] - direct["llcr"]) < 1e-15


def test_stress_noi_cut_moves_both_operation_and_sale():
    direct = pf_model({**G_PF_001, "stabilized_noi_won_y": 5_400_000_000})
    assert abs(direct["exit_value"] - 108_000_000_000.0) < 1.0
    rows = {r["name"]: r for r in stress(G_PF_001)}
    assert abs(rows["안정화 NOI −10%"]["equity_irr"] - direct["equity_irr"]) < 1e-15


def test_stress_delay_stretches_the_same_cost_over_more_months():
    direct = pf_model({**G_PF_001, "months_build": 30})
    assert len(direct["monthly"]) == 30 + 12
    assert abs(direct["monthly"][1]["cost_won"] - 56_000_000_000 / 30) < 1.0
    assert direct["interest_won"] > G_INTEREST       # 인출 기간이 길어 이자가 늘어난다


def test_equity_ladder_resets_equity_to_a_share_of_that_case_total_cost():
    """자기자본 20% 는 '그 시나리오 자신의' 총사업비 대비 20% 다 → ltc = 0.80."""
    rows = {r["name"]: r for r in stress(G_PF_001)}
    for name, ratio in (("자기자본 5%", 0.05), ("자기자본 10%", 0.10),
                        ("자기자본 15%", 0.15), ("자기자본 20%", 0.20)):
        assert abs(rows[name]["ltc"] - (1 - ratio)) < 1e-9
    # 자기자본이 두꺼워질수록 레버리지가 줄어 지분 IRR 이 낮아진다.
    irrs = [rows[f"자기자본 {p}%"]["equity_irr"] for p in (5, 10, 15, 20)]
    assert irrs == sorted(irrs, reverse=True)


def test_stress_scenario_outside_a_physical_gate_raises_instead_of_hiding():
    """게이트 밖으로 나가는 시나리오는 조용히 건너뛰지 않는다."""
    with pytest.raises(RuntimeError, match="cap"):
        stress({**G_PF_001, "exit_cap": 0.115})


def test_llcr_is_finite_and_positive_in_every_stress_row():
    for row in stress(G_PF_001):
        assert math.isfinite(row["llcr"]) and row["llcr"] > 0
