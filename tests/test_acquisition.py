"""인수금융 골든 테스트 — 삼중 제약 대출가능액과 보유기간 지분수익률.

기대값은 엔진과 독립적으로 손계산·고정밀 산술로 확정했다. 엔진과 어긋나면
고쳐야 하는 쪽은 엔진이지 이 표가 아니다.

## 대출가능액

| ID         | 입력                                            | 산식                        | 기대값             |
|------------|-------------------------------------------------|-----------------------------|--------------------|
| G-LOAN-001 | NOI 121.125억·가격 2,700억                      | by_ltv = 2,700억 × 0.55     | 1,485.0억          |
|            | LTV 55%·DSCR 1.3·DY 8%·금리 4.5%                | by_dscr = (121.125/1.3)/.045| 2,070.51282051억   |
|            |                                                 | by_dy = 121.125/0.08        | 1,514.0625억       |
|            |                                                 | min → binding               | 1,485.0억 · ltv    |

by_dscr 손계산: 121.125/1.3 = 93.17307692307692억(= 연 지불 가능 이자),
93.17307692307692/0.045 = 2,070.5128205128204억. 브리프의 반올림 표기
207,051,282,051.28 과 엔진 산출의 차는 0.002원(< 1.0).

## 보유기간 현금흐름과 지분수익률

| ID         | 입력                                                        |
|------------|-------------------------------------------------------------|
| G-HOLD-001 | 가격 1,000억·대출 550억·금리 4%·NOI 45억·성장 0%             |
|            | Exit cap 4.5%·보유 5년·취득부대비용 5%                       |

분기 현금흐름 21개를 손으로 못박는다(엔진이 만드는 배열이 이 표와 원 단위로
같아야 한다).

| 분기   | 산식                                            | 값(원)          |
|--------|-------------------------------------------------|-----------------|
| q0     | −(1,000억 × 1.05 − 550억) = −(1,050 − 550)억     | −50,000,000,000 |
| q1~q19 | (연 NOI 45억 − 이자 550억×4% = 22억) ÷ 4         | +575,000,000    |
| q20    | 575,000,000 + (매각 1,000억 − 대출 550억)        | +45,575,000,000 |

exit_value = 종료 다음 해 NOI ÷ exit cap = 45억 ÷ 0.045 = 1,000억
(성장 0% 라 5년 뒤 NOI 도 45억이다).

**equity_irr 골든 확정 유도** — 브리프는 범위(0.02~0.04)로 적혀 있었다.
엔진(`fin_core.irr_annual`)을 쓰지 않고 위 21개 현금흐름에서 직접 풀었다.

    Σ_{q=0..20} cf_q / (1 + x)^q = 0

을 `decimal.Decimal`(정밀도 60)의 뉴턴법으로 풀어 분기이율

    x = 0.006816068035678323643781306399681727518685770982702…

를 얻었고, 같은 정밀도의 이분법(구간 [−0.5, 1.0], 300회)으로 교차검증했다
(두 방법 차 5.7e−61). 닫힌형(등비수열 합)으로 다시 쓴 NPV 도 이 x 에서
−2.8e−48 이다. 연율화하면

    (1 + x)^4 − 1 = 0.027544293666849693938459031728235625056…

이다. 이 값이 **엑셀 대조 형태**이기도 하다 — 위 21개 값을 A1:A21 에 세로로
넣고 `=IRR(A1:A21)` 이 분기이율 x, `=(1+IRR(A1:A21))^4-1` 이 연율이다.
브리프의 손검산 근사(분기 ≈ 0.68% → 연 ≈ 2.7%)와 일치한다. 취득부대비용
50억을 매각가가 회수하지 못해 IRR 이 낮은 것이 맞다(총유입 565억 / 유출
500억 = 5년 13.0%).

골든 상수는 **0.0275442936668497**(연율)이고 허용오차 1e−12 다. 엔진의
이분법(float, 200회)은 0.02754429366684885 로 이 값과 8.4e−16 차이다.

## 성장 있는 흐름(G-HOLD-002 — 연 단위 성장이 분기에 어떻게 실리는가)

같은 입력에 NOI 성장률만 2% 를 준다. 성장은 **연 단위 계단**이라 한 해 안의
네 분기는 같은 값이고, 해가 바뀔 때만 오른다.

| 연차(t) | 연 NOI = 45억 × 1.02^t | 이자    | 분기 = (NOI−이자)/4 | 값(원)      |
|---------|------------------------|---------|---------------------|-------------|
| 1(t=0)  | 45억                   | 22억    | 23억/4              | 575,000,000 |
| 2(t=1)  | 45.9억                 | 22억    | 23.9억/4            | 597,500,000 |
| 3(t=2)  | 46.818억               | 22억    | 24.818억/4          | 620,450,000 |
| 4(t=3)  | 47.75436억             | 22억    | 25.75436억/4        | 643,859,000 |
| 5(t=4)  | 48.70944720억          | 22억    | 26.70944720억/4     | 667,736,180 |

exit NOI = 45억 × 1.02^5 = 49.683636144억(1.02^5 = 1.1040808032) →
exit_value = 49.683636144억 / 0.045 = 1,104.0808032억. 마지막 분기 =
667,736,180 + (1,104.0808032 − 550)억 = 56,075,816,500원.

## 결속 조건(binding)의 동률 우선순위

셋 중 최솟값의 이름이 binding 이고, 동률이면 **ltv > dscr > debt_yield**
순서로 하나만 고른다. 동률은 다음 합성 입력으로 만든다(전부 float 에서
정확히 같은 값이 나오는 것을 확인했다).

| 입력                                                   | by_ltv | by_dscr | by_dy | binding |
|--------------------------------------------------------|--------|---------|-------|---------|
| NOI 100억·가격 1,000억·LTV 50%·DSCR 1.0·DY 20%·금리 20% | 500억  | 500억   | 500억 | ltv     |
| 같은 입력에 DY 10%                                      | 500억  | 500억   | 1000억| ltv     |
| 같은 입력에 LTV 80%                                     | 800억  | 500억   | 500억 | dscr    |
| 같은 입력에 LTV 50%·금리 10%                            | 500억  | 1000억  | 500억 | ltv     |
"""

import math

import pytest

from src.analysis import acquisition, caprate
from src.analysis.acquisition import hold_model, max_loan
from src.analysis.fin_core import npv


# ── 브리프 확정 골든 2건(축자 — IRR 만 범위→상수) ───────────────────────

# | G-LOAN-001 | NOI 121.125억, 가격 2,700억, LTV 55%·DSCR 1.3·DY 8%·금리 4.5% |
# |   by_ltv = 1,485.0억 · by_dscr = (121.125/1.3)/0.045 = 2,070.5억 · by_dy = 121.125/0.08 = 1,514.06억 |
# |   → min = 1,485.0억, binding=ltv |

def test_golden_max_loan():
    r = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    assert r["loan_won"] == 148_500_000_000.0
    assert r["binding"] == "ltv"
    assert abs(r["by"]["dscr"] - 207_051_282_051.28) < 1.0


# | G-HOLD-001 | 가격 1,000억·대출 550억·금리 4%·NOI 45억·성장 0%·Exit cap 4.5%·5년·비용 5% |
# |   q0 = -(1050-550)억 = -500억 · 분기 순수익 = (45-22)억/4 = 5.75억 × 20분기 |
# |   매각 = 45/0.045 - 550 = 450억 · IRR 검산: 총유입 115+450+550(원금상계는 매각에 내재) |
def test_golden_hold_model():
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    cf = r["cashflows_q"]
    assert cf[0] == -50_000_000_000.0
    assert abs(cf[1] - 575_000_000.0) < 1.0          # (45e8-22e8)/4
    assert abs(r["exit_value"] - 100_000_000_000.0) < 1.0
    assert abs(cf[-1] - (575_000_000.0 + 45_000_000_000.0)) < 1.0  # 마지막 분기 = 순수익 + (매각-대출)
    # 범위 단언(0.02~0.04)을 Decimal 뉴턴법으로 확정한 골든 상수로 교체했다.
    # 분기이율 x = 0.0068160680356783236…, 연율 (1+x)^4−1 = 0.0275442936668497.
    # 엑셀 대조: 21개 분기 현금흐름에 =(1+IRR(A1:A21))^4-1.
    assert abs(r["equity_irr"] - 0.0275442936668497) < 1e-12


# ── 현금흐름 배열의 원소를 못박는다(IRR 상수보다 이쪽이 계약이다) ───────

def test_hold_model_pins_every_cashflow_element():
    # G-HOLD-001 의 21개 원소를 하나씩 손계산값과 대조한다. IRR 은 이 배열의
    # 함수일 뿐이라, 배열이 규약대로 조립되는지가 먼저다.
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    expected = [-50_000_000_000.0] + [575_000_000.0] * 19 + [45_575_000_000.0]
    cf = r["cashflows_q"]
    assert len(cf) == 21
    for q, (got, want) in enumerate(zip(cf, expected)):
        assert abs(got - want) < 1e-6, f"{q}분기: {got} != {want}"


def test_hold_model_quarter_count_is_four_per_year_plus_zero():
    for years in (1, 3, 5, 7, 10):
        r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, years, 0.05)
        assert len(r["cashflows_q"]) == 4 * years + 1


def test_hold_model_growth_is_an_annual_step_not_quarterly():
    # G-HOLD-002: 성장 2%. 한 해 안의 네 분기는 같고 해가 바뀔 때만 오른다.
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.02, 0.045, 5, 0.05)
    cf = r["cashflows_q"]
    per_year = [575_000_000.0, 597_500_000.0, 620_450_000.0, 643_859_000.0, 667_736_180.0]
    for t, want in enumerate(per_year):
        for k in range(4):
            q = 1 + 4 * t + k
            if q == len(cf) - 1:      # 마지막 분기는 매각이 얹혀 있다
                continue
            assert abs(cf[q] - want) < 1e-3, f"{q}분기(연차 {t + 1}): {cf[q]} != {want}"
    # 매각가는 **종료 다음 해** NOI 를 쓴다: 45억×1.02^5 = 49.683636144억
    assert abs(r["exit_value"] - 110_408_080_320.0) < 1.0
    assert abs(cf[-1] - 56_075_816_500.0) < 1.0
    assert abs(cf[0] + 50_000_000_000.0) < 1e-6


def test_hold_model_exit_uses_the_year_after_the_hold_period():
    # 성장이 있으면 exit NOI 는 보유 마지막 해 NOI 가 아니라 그 다음 해다.
    r = hold_model(100_000_000_000, 0.0, 0.04, 4_500_000_000, 0.10, 0.045, 5, 0.0)
    exit_noi = 4_500_000_000 * 1.10 ** 5
    assert abs(r["exit_value"] - exit_noi / 0.045) < 1.0
    last_year_noi = 4_500_000_000 * 1.10 ** 4
    assert abs(r["exit_value"] - last_year_noi / 0.045) > 1.0   # 한 해 어긋나면 안 된다


def test_hold_model_q0_includes_acquisition_cost_and_nets_the_loan():
    # q0 = −(가격 × (1+비용률) − 대출). 비용률 0 이면 −(가격 − 대출).
    # 허용오차는 1e−3원이다 — 1,000억 규모에서 double 의 최소 간격이 1.5e−5원이라
    # 1e−6 은 float 로 표현조차 못 하는 정밀도다(1.1 이 이진수로 딱 떨어지지 않아
    # 100e9 × 1.1 = 110,000,000,000.00002 가 된다).
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.0)
    assert abs(r["cashflows_q"][0] + 45_000_000_000.0) < 1e-3
    r10 = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.10)
    assert abs(r10["cashflows_q"][0] + 55_000_000_000.0) < 1e-3


def test_hold_model_interest_is_io_principal_never_amortizes():
    # IO 가정: 매 분기 이자는 loan×rate/4 로 상수이고 원금은 매각 시점에
    # 한 번에 상계된다(중간 분기에 원금 상환이 섞여 있으면 값이 달라진다).
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    cf = r["cashflows_q"]
    assert len(set(cf[1:-1])) == 1                       # 중간 19분기 전부 동일
    assert abs(cf[-1] - cf[1] - (100_000_000_000.0 - 55_000_000_000.0)) < 1e-6


def test_hold_model_irr_makes_npv_zero():
    # IRR 정의의 왕복 — 엔진 IRR 로 할인한 NPV 는 0 이어야 한다.
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    assert abs(npv(r["cashflows_q"], r["equity_irr"])) < 1.0    # 원 단위


def test_hold_model_irr_is_none_when_there_is_no_sign_change():
    # 대출이 취득총액과 같으면 q0 = 0 이라 유출이 없다 — IRR 은 정의되지
    # 않는다. 엔진은 None 을 그대로 흘려보내야 한다(값을 지어내지 않는다).
    r = hold_model(100_000_000_000, 100_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.0)
    assert r["cashflows_q"][0] == 0.0
    assert r["equity_irr"] is None


def test_hold_model_return_shape_and_assumptions():
    r = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    assert {"cashflows_q", "equity_irr", "exit_value", "assumptions"} <= set(r)
    a = r["assumptions"]
    assert a["caveats"]                       # 가정 없는 IRR 은 출고 금지
    assert a["notes"]
    joined = " ".join(a["notes"]) + " ".join(a["caveats"])
    assert "IO" in joined or "원금" in joined  # 원금 미상환 가정 명시
    assert "매각비용" in joined                # 매각비용 미반영 명시
    assert abs(a["equity_won"] - 50_000_000_000.0) < 1e-6
    assert abs(a["interest_won_y"] - 2_200_000_000.0) < 1e-6


def test_hold_model_returns_a_fresh_list_each_call():
    a = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    b = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    assert a["cashflows_q"] == b["cashflows_q"]
    assert a["cashflows_q"] is not b["cashflows_q"]
    a["cashflows_q"].append(9.9)
    c = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    assert len(c["cashflows_q"]) == 21


def test_hold_model_zero_leverage_irr_is_the_unlevered_return():
    # 대출 0 이면 지분 IRR 은 무차입 수익률이다. 비용 0·성장 0 이면 매수가와
    # 매각가가 같으므로(45억/0.045 = 1,000억) IRR 은 소득수익률 4.5% 에
    # 분기 복리만 얹힌 값이 된다: (1+0.045/4)^4−1 = 0.045764…
    r = hold_model(100_000_000_000, 0.0, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.0)
    assert abs(r["equity_irr"] - ((1 + 0.045 / 4) ** 4 - 1)) < 1e-9


# ── max_loan: 삼중 제약과 결속 조건 ─────────────────────────────────────

def test_max_loan_return_shape():
    r = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    assert {"loan_won", "binding", "by"} <= set(r)
    assert set(r["by"]) == {"ltv", "dscr", "debt_yield"}
    assert r["loan_won"] == min(r["by"].values())
    assert r["loan_won"] == r["by"][r["binding"]]
    assert r["assumptions"]["caveats"]


def test_max_loan_each_constraint_can_bind():
    # dscr 결속: NOI 100억·가격 1,000억·LTV 80%(800억)·DSCR 2.0·금리 10%
    #            → by_dscr = (100/2)/0.1 = 500억 · by_dy(8%) = 1,250억
    r = max_loan(10_000_000_000, 100_000_000_000, 0.8, 2.0, 0.08, 0.1)
    assert r["binding"] == "dscr"
    assert abs(r["loan_won"] - 50_000_000_000.0) < 1e-6
    # debt_yield 결속: DY 15% → 666.67억 · by_ltv 800억 · by_dscr(1.0/5%) 2,000억
    r2 = max_loan(10_000_000_000, 100_000_000_000, 0.8, 1.0, 0.15, 0.05)
    assert r2["binding"] == "debt_yield"
    assert abs(r2["loan_won"] - 10_000_000_000 / 0.15) < 1e-6


def test_max_loan_by_values_are_the_three_formulas():
    r = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    assert r["by"]["ltv"] == 270_000_000_000 * 0.55
    assert r["by"]["dscr"] == (12_112_500_000 / 1.3) / 0.045
    assert r["by"]["debt_yield"] == 12_112_500_000 / 0.08
    assert abs(r["by"]["debt_yield"] - 151_406_250_000.0) < 1e-6


def test_max_loan_tie_break_priority_is_ltv_then_dscr_then_debt_yield():
    # 세 값이 모두 500억(동률) → ltv
    three = max_loan(10_000_000_000, 100_000_000_000, 0.5, 1.0, 0.2, 0.2)
    assert three["by"] == {"ltv": 50e9, "dscr": 50e9, "debt_yield": 50e9}
    assert three["binding"] == "ltv"
    # ltv == dscr < debt_yield → ltv
    assert max_loan(10_000_000_000, 100_000_000_000, 0.5, 1.0, 0.1, 0.2)["binding"] == "ltv"
    # dscr == debt_yield < ltv → dscr
    assert max_loan(10_000_000_000, 100_000_000_000, 0.8, 1.0, 0.2, 0.2)["binding"] == "dscr"
    # ltv == debt_yield < dscr → ltv
    assert max_loan(10_000_000_000, 100_000_000_000, 0.5, 1.0, 0.2, 0.1)["binding"] == "ltv"
    assert acquisition.BINDING_PRIORITY == ("ltv", "dscr", "debt_yield")


def test_max_loan_dscr_constraint_is_interest_only():
    # IO 가정이라 by_dscr 는 이자만 덮으면 된다. 같은 조건에서 원리금균등
    # (10년)을 가정하면 상환액이 커져 대출가능액이 작아져야 하므로, IO 값이
    # 원리금균등 값보다 크다는 것으로 가정을 못박는다.
    from src.analysis.fin_core import pmt
    noi, dscr, rate = 10_000_000_000.0, 1.3, 0.05
    io = max_loan(noi, 1_000_000_000_000, 0.99, dscr, 0.01, rate)["by"]["dscr"]
    assert abs(io - (noi / dscr) / rate) < 1e-6
    # 같은 원금의 원리금균등 상환액은 이자보다 크다 → 상환 가정에선 못 빌린다
    assert pmt(io, rate, 10) > io * rate


def test_max_loan_zero_noi_gives_zero_loan_by_income_constraints():
    r = max_loan(0.0, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    assert r["loan_won"] == 0.0
    assert r["binding"] == "dscr"          # 동률(dscr·debt_yield 둘 다 0) → 우선순위


def test_max_loan_amortizing_is_not_supported_silently():
    # io=False 를 조용히 IO 로 처리하면 대출가능액이 **과대**로 나온다
    # (원리금 > 이자). 상환 연수가 시그니처에 없어 계산할 수 없으므로 막는다.
    with pytest.raises(NotImplementedError):
        max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045, io=False)


def test_max_loan_reports_the_resulting_dscr():
    r = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    # 결속이 ltv 라 실제 DSCR 은 요구치보다 높다: 121.125/(1,485×4.5%) = 1.8126
    assert abs(r["assumptions"]["dscr_at_max_loan"] - 12_112_500_000 / (148_500_000_000 * 0.045)) < 1e-9
    assert r["assumptions"]["dscr_at_max_loan"] > 1.3


# ── max_loan: 도메인·게이트 ─────────────────────────────────────────────

def test_max_loan_dscr_gate_is_zero_to_five():
    # 전역 제약: DSCR 0~5 밖은 RuntimeError. 1.3 을 130(%)으로 넣은 오입력이
    # 게이트에 걸린다 — 통과시키면 by_dscr 가 100분의 1 이 된다.
    assert (acquisition.DSCR_GATE_MIN, acquisition.DSCR_GATE_MAX) == (0.0, 5.0)
    with pytest.raises(RuntimeError):
        max_loan(12_112_500_000, 270_000_000_000, 0.55, 130.0, 0.08, 0.045)
    with pytest.raises(RuntimeError):
        max_loan(12_112_500_000, 270_000_000_000, 0.55, -1.0, 0.08, 0.045)
    with pytest.raises(RuntimeError):
        max_loan(12_112_500_000, 270_000_000_000, 0.55, 5.01, 0.08, 0.045)
    max_loan(12_112_500_000, 270_000_000_000, 0.55, 5.0, 0.08, 0.045)   # 양끝 포함


def test_max_loan_dscr_zero_is_a_domain_error_not_a_gate_error():
    # 0 은 게이트 안이지만 "요구 DSCR 이 없다"는 뜻이라 제약이 무한대가 된다.
    with pytest.raises(ValueError):
        max_loan(12_112_500_000, 270_000_000_000, 0.55, 0.0, 0.08, 0.045)


def test_max_loan_domain_errors():
    base = dict(noi_won_y=12_112_500_000, price_won=270_000_000_000, ltv_max=0.55,
                dscr_min=1.3, debt_yield_min=0.08, loan_rate=0.045)
    bad = [
        {"noi_won_y": -1.0},          # 음수 NOI
        {"price_won": 0.0},
        {"price_won": -270_000_000_000.0},
        {"ltv_max": 0.0},
        {"ltv_max": 1.01},            # 100% 초과
        {"ltv_max": 55.0},            # % 를 소수 자리에
        {"debt_yield_min": 0.0},
        {"debt_yield_min": 8.0},      # % 를 소수 자리에
        {"loan_rate": 0.0},           # 무이자면 by_dscr 가 무한대
        {"loan_rate": 4.5},           # % 를 소수 자리에
    ]
    for override in bad:
        with pytest.raises(ValueError):
            max_loan(**{**base, **override})


def test_max_loan_rejects_nan_and_inf_in_every_argument():
    base = dict(noi_won_y=12_112_500_000, price_won=270_000_000_000, ltv_max=0.55,
                dscr_min=1.3, debt_yield_min=0.08, loan_rate=0.045)
    for name in base:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                max_loan(**{**base, name: bad})


# ── hold_model: 도메인·게이트 ───────────────────────────────────────────

def test_hold_model_exit_cap_gate_shares_caprate_constants():
    assert acquisition.CAP_MIN is caprate.CAP_MIN
    assert acquisition.CAP_MAX is caprate.CAP_MAX
    for bad_cap in (4.5, 0.0045, 0.0, 0.0199, 0.1201):
        with pytest.raises(RuntimeError):
            hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, bad_cap)
    hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, caprate.CAP_MIN)
    hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, caprate.CAP_MAX)


def test_hold_model_domain_errors():
    base = dict(price_won=100_000_000_000, loan_won=55_000_000_000, loan_rate=0.04,
                noi_won_y=4_500_000_000, noi_growth_y=0.0, exit_cap=0.045,
                hold_years=5, cost_rate=0.05)
    bad = [
        {"price_won": 0.0},
        {"price_won": -100.0},
        {"loan_won": -1.0},
        {"loan_won": 100_000_000_001.0},   # 가격 초과 대출
        {"loan_rate": -0.01},
        {"loan_rate": 4.0},                # % 를 소수 자리에
        {"noi_won_y": -1.0},
        {"noi_growth_y": -1.0},            # NOI 가 0 이하로 무너지는 성장률
        {"noi_growth_y": 2.0},             # 2(%)를 소수 자리에
        {"hold_years": 0},
        {"hold_years": -5},
        {"hold_years": 5.5},               # 반년은 분기 조립 규약에 없다
        {"hold_years": True},              # bool 은 int 의 하위형 — 1년으로 새면 안 된다
        {"cost_rate": -0.01},
        {"cost_rate": 1.0},
        {"cost_rate": 5.0},                # % 를 소수 자리에
    ]
    for override in bad:
        with pytest.raises(ValueError):
            hold_model(**{**base, **override})


def test_hold_model_rejects_nan_and_inf_in_every_numeric_argument():
    base = dict(price_won=100_000_000_000, loan_won=55_000_000_000, loan_rate=0.04,
                noi_won_y=4_500_000_000, noi_growth_y=0.0, exit_cap=0.045,
                hold_years=5, cost_rate=0.05)
    for name in ("price_won", "loan_won", "loan_rate", "noi_won_y", "noi_growth_y",
                 "exit_cap", "cost_rate"):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                hold_model(**{**base, name: bad})


def test_hold_model_allows_zero_loan_and_zero_cost():
    r = hold_model(100_000_000_000, 0.0, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.0)
    assert r["cashflows_q"][0] == -100_000_000_000.0
    assert abs(r["cashflows_q"][1] - 4_500_000_000 / 4) < 1e-6


# ── 모듈 규약(순수 함수·유한성·연결) ───────────────────────────────────

def test_no_nan_leaks_into_results():
    r = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    assert math.isfinite(r["loan_won"])
    assert all(math.isfinite(v) for v in r["by"].values())
    h = hold_model(100_000_000_000, 55_000_000_000, 0.04, 4_500_000_000, 0.0, 0.045, 5, 0.05)
    assert all(math.isfinite(c) for c in h["cashflows_q"])
    assert math.isfinite(h["exit_value"]) and math.isfinite(h["equity_irr"])


def test_pipeline_max_loan_feeds_hold_model():
    # NOI 121.125억(G-NOI-001)·가격 2,700억 → 대출 1,485억(ltv 결속) →
    # 그 대출로 5년 보유. 두 함수가 같은 단위(원·소수 연율)로 맞물린다.
    loan = max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    h = hold_model(270_000_000_000, loan["loan_won"], 0.045, 12_112_500_000, 0.02, 0.045)
    assert len(h["cashflows_q"]) == 21
    assert h["cashflows_q"][0] == -(270_000_000_000 * 1.05 - 148_500_000_000)
    assert h["equity_irr"] is not None and math.isfinite(h["equity_irr"])
