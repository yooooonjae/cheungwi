"""Cap Rate·가치 골든 테스트.

기대값은 손계산으로 확정했다. 엔진과 어긋나면 고쳐야 하는 쪽은 엔진이지
이 표가 아니다.

| ID        | 입력                                   | 산식                                  | 기대값             |
|-----------|----------------------------------------|---------------------------------------|--------------------|
| G-CAP-001 | 분기 소득수익률 [0.94, 0.95, 0.96, 0.96]% | 합 0.94+0.95+0.96+0.96 = 3.81% → ÷100 | 0.0381             |
| G-VAL-001 | NOI 121.125억, cap 4.5%                | 12,112,500,000 / 0.045                | 269,166,666,666.67 |
| G-IMP-001 | NOI 121.125억, 가격 2,700억            | 12,112,500,000 / 270,000,000,000      | 0.0448611111…      |

G-IMP-001 손계산: 12,112,500,000 / 270,000,000,000 = 121.125/2700 = 0.0448611111…
(2700 × 0.0448611111 = 121.12499997 — 역산으로 확인)

G-VAL-001 손계산: 12,112,500,000 / 0.045 = 12,112,500,000 × 1000/45
= 12,112,500,000,000/45 = 269,166,666,666.67

오차율 정의는 하나뿐이다 — **err = (추정 − 실거래) / 실거래**. 과대추정이
양수다. `quantiles` 는 `statistics.quantiles(n=4, method="inclusive")` 를
쓴다(표본이 작아 exclusive 는 양끝을 못 낸다).

| ID        | 오차율 표본            | inclusive 사분위 손계산                     | p25    | median | p75   |
|-----------|------------------------|---------------------------------------------|--------|--------|-------|
| G-ERR-001 | [0.1, −0.05, 0.0]      | 정렬 [−0.05, 0, 0.1]; 위치 0.25×2=0.5·1·1.5 | −0.025 | 0.0    | 0.05  |
| G-ERR-002 | [−0.2, −0.1, 0, 0.1, 0.2] | 정렬 그대로; 위치 0.25×4=1·2·3            | −0.1   | 0.0    | 0.1   |

물리 게이트: cap rate 는 0.02~0.12(양끝 포함) 안이어야 한다. `implied` 와
`appraise` **양쪽**에 건다 — `implied` 만 막으면 실거래가 없는 출고 경로
(`appraise`)로 어긋난 cap 이 그대로 빠져나간다.
"""

import math

import pytest

from src.analysis import caprate, value


# ── 브리프 확정 골든 4건(축자) ──────────────────────────────────────────

# | G-CAP-001 | 분기 소득수익률 [0.94, 0.95, 0.96, 0.96]% | 합 3.81% | 0.0381 |
# | G-VAL-001 | NOI 121.125억, cap 4.5% | 12,112,500,000/0.045 | 269,166,666,666.67 |
# | G-IMP-001 | NOI 121.125억, 가격 2,700억 | /2.7e11 | 0.044861... |

def test_golden_benchmark():
    r = caprate.benchmark([0.94, 0.95, 0.96, 0.96])
    assert abs(r["cap_income_based"] - 0.0381) < 1e-9


def test_golden_appraise_and_implied():
    v = value.appraise(12_112_500_000, 0.045)
    assert abs(v - 269_166_666_666.67) < 1.0
    assert abs(caprate.implied(12_112_500_000, 270_000_000_000) - 0.0448611111) < 1e-9


def test_implied_gate():
    import pytest
    with pytest.raises(RuntimeError):
        caprate.implied(12_112_500_000, 60_000_000_000)   # cap 20% → 게이트 밖


def test_error_dist():
    d = value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)])
    assert d["n"] == 3 and abs(d["median_err"] - 0.0) < 1e-9


# ── benchmark: 반환 계약과 최근 4분기 규약 ──────────────────────────────

def test_benchmark_return_shape():
    r = caprate.benchmark([0.94, 0.95, 0.96, 0.96])
    assert {"cap_income_based", "quarters_used"} <= set(r)
    assert r["quarters_used"] == [0.94, 0.95, 0.96, 0.96]
    assert r["caveats"]          # 라벨 없는 벤치마크는 출고 금지(정직성 원칙)


def test_benchmark_uses_the_four_most_recent_quarters():
    # 입력은 오래된 → 최신 순서(R-ONE yq 오름차순 그대로). 앞의 낡은 분기는
    # 버리고 뒤 넷만 쓴다.
    r = caprate.benchmark([5.0, 5.0, 0.94, 0.95, 0.96, 0.96])
    assert r["quarters_used"] == [0.94, 0.95, 0.96, 0.96]
    assert abs(r["cap_income_based"] - 0.0381) < 1e-9


def test_benchmark_needs_four_quarters():
    with pytest.raises(ValueError):
        caprate.benchmark([0.95, 0.96, 0.96])
    with pytest.raises(ValueError):
        caprate.benchmark([])


def test_benchmark_percent_in_decimal_out():
    # 규약: 입력은 %(0.94 = 0.94%), 반환은 소수(0.0381 = 3.81%). 100배 차이라
    # 뒤집어 넣으면 결과가 100배/100분의 1 로 어긋난다.
    r = caprate.benchmark([1.0, 1.0, 1.0, 1.0])
    assert r["cap_income_based"] == 0.04


def test_benchmark_rejects_decimal_input_via_gate():
    # 소수(0.0094)를 % 자리에 넣으면 벤치마크가 0.000376 = 0.0376% 가 된다.
    # 게이트가 없으면 이 값이 하류 appraise 로 흘러가 감정가를 100배로 만든다.
    with pytest.raises(RuntimeError):
        caprate.benchmark([0.0094, 0.0095, 0.0096, 0.0096])


def test_benchmark_gate_rejects_annual_yield_in_a_quarterly_slot():
    # 연 소득수익률(3.81%)을 분기 자리에 넷 넣으면 15.24% 가 된다.
    with pytest.raises(RuntimeError):
        caprate.benchmark([3.81, 3.81, 3.81, 3.81])


def test_benchmark_rejects_nan_and_inf():
    with pytest.raises(ValueError):
        caprate.benchmark([0.94, float("nan"), 0.96, 0.96])
    with pytest.raises(ValueError):
        caprate.benchmark([0.94, 0.95, 0.96, float("inf")])


def test_benchmark_rejects_negative_quarter():
    # 자본수익률(음수 가능)을 소득수익률 자리에 넣은 오입력을 잡는다.
    with pytest.raises(ValueError):
        caprate.benchmark([0.94, -0.95, 0.96, 0.96])


def test_benchmark_checks_the_whole_series_not_just_the_last_four():
    # 계열 오입력(자본수익률) 판별은 뒤 4분기만 봐서는 새어 나간다 — 최근
    # 넷이 우연히 양수이고 합이 게이트 안(0.5+0.6+0.5+0.6 = 2.2%)이면
    # cap 0.022 가 조용히 나간다. 소득수익률은 정의상 음수가 없으므로 계열
    # 전체를 봐도 오탐 비용이 0 이다.
    with pytest.raises(ValueError):
        caprate.benchmark([-1.4, 0.8, 0.5, 0.6, 0.5, 0.6])
    with pytest.raises(ValueError):
        caprate.benchmark([float("nan"), 0.8, 0.94, 0.95, 0.96, 0.96])


def test_benchmark_does_not_mutate_or_share_input():
    src = [0.94, 0.95, 0.96, 0.96]
    r = caprate.benchmark(src)
    r["quarters_used"].append(9.9)
    assert src == [0.94, 0.95, 0.96, 0.96]
    assert caprate.benchmark(src)["quarters_used"] == src
    assert r["quarters_used"] is not src


# ── implied: 역산과 게이트 ──────────────────────────────────────────────

def test_implied_is_noi_over_price():
    assert caprate.implied(4_500_000_000, 100_000_000_000) == 0.045


def test_implied_gate_boundaries_are_inclusive():
    # 양끝(2%·12%)은 통과, 한 걸음 밖은 차단.
    assert caprate.implied(2_000_000_000, 100_000_000_000) == caprate.CAP_MIN
    assert caprate.implied(12_000_000_000, 100_000_000_000) == caprate.CAP_MAX
    with pytest.raises(RuntimeError):
        caprate.implied(1_900_000_000, 100_000_000_000)     # 1.9%
    with pytest.raises(RuntimeError):
        caprate.implied(12_100_000_000, 100_000_000_000)    # 12.1%


def test_implied_zero_noi_hits_the_gate_not_a_silent_zero():
    # 전관 공실(NOI 0)은 입력으로는 말이 되지만 역산 cap 0 은 게이트 밖이다.
    with pytest.raises(RuntimeError):
        caprate.implied(0.0, 270_000_000_000)


def test_implied_price_must_be_positive():
    for price in (0.0, -270_000_000_000):
        with pytest.raises(ValueError):
            caprate.implied(12_112_500_000, price)


def test_implied_rejects_nan_and_inf():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            caprate.implied(bad, 270_000_000_000)
        with pytest.raises(ValueError):
            caprate.implied(12_112_500_000, bad)


def test_implied_rejects_negative_noi():
    with pytest.raises(ValueError):
        caprate.implied(-12_112_500_000, 270_000_000_000)


# ── appraise: 게이트가 양쪽에 있어야 하는 이유 ──────────────────────────

def test_appraise_is_noi_over_cap():
    assert value.appraise(4_500_000_000, 0.045) == 100_000_000_000.0


def test_appraise_gate_catches_percent_in_a_decimal_slot():
    # cap 4.5(%)를 소수 자리에 넣으면 감정가가 100분의 1(26.9억)이 되고,
    # 0.0045 를 넣으면 10배(2.69조)가 된다. 둘 다 정상 float 이라 하류가
    # 잡지 못한다 — 여기서 막는다.
    with pytest.raises(RuntimeError):
        value.appraise(12_112_500_000, 4.5)
    with pytest.raises(RuntimeError):
        value.appraise(12_112_500_000, 0.0045)


def test_appraise_gate_boundaries_are_inclusive():
    value.appraise(12_112_500_000, value.CAP_MIN)
    value.appraise(12_112_500_000, value.CAP_MAX)
    with pytest.raises(RuntimeError):
        value.appraise(12_112_500_000, 0.0199)
    with pytest.raises(RuntimeError):
        value.appraise(12_112_500_000, 0.1201)


def test_appraise_gate_constants_have_a_single_source():
    # cap 게이트 상수는 caprate 것을 그대로 쓴다(복제하면 두 모듈이 따로 움직인다).
    assert value.CAP_MIN is caprate.CAP_MIN
    assert value.CAP_MAX is caprate.CAP_MAX
    assert (caprate.CAP_MIN, caprate.CAP_MAX) == (0.02, 0.12)


def test_appraise_zero_noi_is_zero_value():
    # 전관 공실 건물의 소득접근 가치는 0 이다(입력 오류가 아니다).
    assert value.appraise(0.0, 0.045) == 0.0


def test_appraise_rejects_negative_noi_and_nonfinite():
    with pytest.raises(ValueError):
        value.appraise(-12_112_500_000, 0.045)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            value.appraise(bad, 0.045)
        with pytest.raises(ValueError):
            value.appraise(12_112_500_000, bad)
    with pytest.raises(ValueError):
        value.appraise(12_112_500_000, float("nan"))


def test_appraise_and_implied_are_inverses():
    # 감정가로 되사면 같은 cap 이 나와야 한다(정의의 왕복).
    cap = 0.0448611111
    v = value.appraise(12_112_500_000, cap)
    assert abs(caprate.implied(12_112_500_000, v) - cap) < 1e-12


# ── error_dist: 오차율 정의와 분포 ──────────────────────────────────────

def test_error_dist_return_shape():
    d = value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)])
    assert set(d) == {"n", "median_err", "p25", "p75", "mean_abs_err"}


def test_error_dist_sign_convention_overestimate_is_positive():
    # err = (추정 − 실거래)/실거래. 과대추정이 양수다.
    d = value.error_dist([(120.0, 100.0), (120.0, 100.0), (120.0, 100.0)])
    assert abs(d["median_err"] - 0.2) < 1e-12
    d2 = value.error_dist([(80.0, 100.0), (80.0, 100.0), (80.0, 100.0)])
    assert abs(d2["median_err"] + 0.2) < 1e-12


def test_error_dist_quartiles_match_inclusive_hand_calc():
    # G-ERR-001: 오차율 [0.1, −0.05, 0.0] → p25 −0.025 · median 0.0 · p75 0.05
    d = value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)])
    assert abs(d["p25"] + 0.025) < 1e-12
    assert abs(d["median_err"]) < 1e-12
    assert abs(d["p75"] - 0.05) < 1e-12
    assert abs(d["mean_abs_err"] - 0.05) < 1e-12   # (0.1+0.05+0)/3


def test_error_dist_quartiles_five_point_hand_calc():
    # G-ERR-002: 오차율 [−0.2, −0.1, 0, 0.1, 0.2] → p25 −0.1 · p75 0.1
    pairs = [(80.0, 100.0), (90.0, 100.0), (100.0, 100.0), (110.0, 100.0), (120.0, 100.0)]
    d = value.error_dist(pairs)
    assert d["n"] == 5
    assert abs(d["p25"] + 0.1) < 1e-12
    assert abs(d["median_err"]) < 1e-12
    assert abs(d["p75"] - 0.1) < 1e-12
    assert abs(d["mean_abs_err"] - 0.12) < 1e-12   # (0.2+0.1+0+0.1+0.2)/5


def test_error_dist_mean_abs_is_not_abs_of_mean():
    # 부호가 상쇄되면 평균오차는 0 이지만 평균절대오차는 0 이 아니다.
    d = value.error_dist([(110.0, 100.0), (90.0, 100.0), (100.0, 100.0)])
    assert abs(d["median_err"]) < 1e-12
    assert abs(d["mean_abs_err"] - 0.2 / 3) < 1e-12


def test_error_dist_order_does_not_matter():
    a = value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)])
    b = value.error_dist([(100.0, 100.0), (110.0, 100.0), (95.0, 100.0)])
    assert a == b


def test_error_dist_uses_each_pairs_own_actual():
    # 실거래가가 제각각이어도 오차율은 쌍마다 자기 실거래로 나눈다.
    d = value.error_dist([(220.0, 200.0), (50.0, 100.0), (300.0, 300.0)])
    # errs = [0.1, −0.5, 0.0]
    assert abs(d["median_err"]) < 1e-12
    assert abs(d["mean_abs_err"] - 0.6 / 3) < 1e-12


def test_error_dist_needs_three_pairs():
    # statistics.quantiles(n=4) 는 2점으로도 돌지만 그것은 사분위수가 아니라
    # 두 점의 내삽이다 — 도메인 검사로 3점을 요구한다.
    with pytest.raises(ValueError):
        value.error_dist([(110.0, 100.0), (95.0, 100.0)])
    with pytest.raises(ValueError):
        value.error_dist([])


def test_error_dist_actual_price_must_be_positive():
    for bad_actual in (0.0, -100.0):
        with pytest.raises(ValueError):
            value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, bad_actual)])


def test_error_dist_rejects_nan_and_inf():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            value.error_dist([(110.0, 100.0), (95.0, 100.0), (bad, 100.0)])
        with pytest.raises(ValueError):
            value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, bad)])


def test_error_dist_rejects_negative_estimate():
    with pytest.raises(ValueError):
        value.error_dist([(110.0, 100.0), (95.0, 100.0), (-100.0, 100.0)])


def test_error_dist_rejects_malformed_pairs():
    with pytest.raises(ValueError):
        value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0, 3.0)])


def test_error_dist_does_not_mutate_input():
    pairs = [(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)]
    value.error_dist(pairs)
    assert pairs == [(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)]


# ── 모듈 규약(순수 함수·표준 라이브러리) ────────────────────────────────

def test_no_nan_leaks_through_any_public_function():
    # NaN 은 크기 비교가 전부 False 라 게이트를 조용히 통과한다. 세 함수 모두
    # 게이트 이전에 막아야 한다 — 통과하면 하류(대출·IRR)까지 NaN 이 흐른다.
    nan = float("nan")
    for call in (
        lambda: caprate.benchmark([0.94, 0.95, 0.96, nan]),
        lambda: caprate.implied(nan, 270_000_000_000),
        lambda: value.appraise(12_112_500_000, nan),
        lambda: value.error_dist([(nan, 100.0), (95.0, 100.0), (100.0, 100.0)]),
    ):
        with pytest.raises(ValueError):
            call()


def test_results_are_finite_numbers():
    assert math.isfinite(caprate.benchmark([0.94, 0.95, 0.96, 0.96])["cap_income_based"])
    assert math.isfinite(caprate.implied(12_112_500_000, 270_000_000_000))
    assert math.isfinite(value.appraise(12_112_500_000, 0.045))
    d = value.error_dist([(110.0, 100.0), (95.0, 100.0), (100.0, 100.0)])
    assert all(math.isfinite(v) for k, v in d.items() if k != "n")
