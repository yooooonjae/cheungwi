"""차환 골든 테스트 — 만기 차환 가능 최대금리와 손익분기 공실률.

기대값은 엔진과 독립적으로 손계산·분수 산술로 확정했다. 엔진과 어긋나면
고쳐야 하는 쪽은 엔진이지 이 표가 아니다.

## 차환 가능 최대금리(refi_test)

| ID         | 입력                                   | 산식                        | 기대값          |
|------------|----------------------------------------|-----------------------------|-----------------|
| G-REFI-001 | NOI 121.125억·대출 1,485억             | max_rate = NOI/(DSCR×대출)  | 0.0627428127…   |
|            | 가치 2,700억·DSCR 1.3·LTV 60%          | ltv 한도 = 2,700억 × 0.60   | 1,620.0억       |
|            | 시장금리 5%                            | headroom = (max−시장)×10000 | 127.428127…bp   |
|            |                                        | 1,485억 ≤ 1,620억 · 6.27% > 5% | **pass**     |

max_rate 손계산: 분모 = 1.3 × 1,485억 = 1,930.5억. 121.125/1930.5 를 약분하면
**323/5148** 이고, 이 기약분수를 50자리로 펼치면

    0.06274281274281274281274281274281274281274281274281…

이다(순환마디 274281). 브리프의 골든 0.0627428127 과의 차는 4.3e−11 로 허용
오차 1e−9 안이다. 베이시스포인트로 옮기면 (323/5148 − 0.05) × 10000 =
127.42812742812742…bp 이고 골든 127.428127 과의 차는 4.3e−7(허용 1e−4).

**pass 는 두 관문의 AND 다.** 금리(max_rate > 시장금리)와 LTV(대출 ≤
가치×한도)가 **둘 다** 서야 True 다. 하나만 보면 "금리는 되는데 담보가치가
빠져 못 빌리는" 경우가 통과한다 — 만기 차환이 깨지는 전형적인 경로가 바로
그쪽이다. 등호 처리는 두 관문이 서로 다르다.

| 관문 | 조건                     | 등호일 때 | 이유                                    |
|------|--------------------------|-----------|-----------------------------------------|
| 금리 | max_rate > 시장금리      | **False** | 여유가 0 이면 차환 여력이 없다          |
| LTV  | 대출 ≤ 가치 × LTV 한도   | **True**  | 한도에 정확히 붙은 대출은 약정을 지킨다 |

등호 검증용 합성 입력은 float 에서 정확히 같은 값이 나오는 것으로 골랐다
(1.25·0.5 는 이진수로 딱 떨어진다).

| 입력                                              | 좌변      | 우변      | 결과   |
|---------------------------------------------------|-----------|-----------|--------|
| NOI 62.5억·대출 1,000억·DSCR 1.25·시장금리 5%     | max 0.05  | 시장 0.05 | 금리 실패 |
| 대출 1,500억·가치 3,000억·LTV 50%                 | 1,500억   | 1,500억   | LTV 통과 |

## 손익분기 공실률(breakeven_vacancy)

| ID        | 입력                                       | 산식                    | 기대값        |
|-----------|--------------------------------------------|-------------------------|---------------|
| G-BEV-001 | 유효임대료 25,000·GFA 100,000·전용률 0.5   | 필요 NOI = 1.3×1,485억×6% | 115.83억    |
|           | opex 15%·대출 1,485억·금리 6%·DSCR 1.3     | 필요 EGI = 115.83/0.85  | 136.270588…억 |
|           |                                            | 만실 EGI = 25,000×50,000×12 | 150.0억   |
|           |                                            | 1 − 136.270588…/150     | 0.0915294117… |

분수로 풀면 1 − 11,583,000,000/12,750,000,000 = 1 − 3861/4250 = **389/4250** =
0.09152941176470588235294117647… 이고 브리프 골든 0.0915294118 과의 차는
3.5e−11(허용 1e−9)이다.

`noi()` 를 거치지 않고 같은 산식을 다시 쓰므로, 두 모듈이 같은 산식인지는
**왕복**으로 확인한다 — 돌려받은 공실률을 `noi()` 에 넣으면 NOI 가 정확히
필요 NOI(= DSCR × 대출 × 금리)여야 하고, 그 지점에서 `refi_test` 의 headroom
은 0 이 된다(그래서 pass 는 False 다 — 위 등호 표).

**0 클램프.** 만실이어도 필요 NOI 를 못 채우면 산식이 음수를 낸다. 그때는
0 을 돌려준다(이미 불가). 예: 같은 건물에 대출 3,000억·금리 6%·DSCR 1.3 이면
필요 NOI 234억 > 만실 NOI 127.5억이라 원값이 −0.8352941176…이고 반환은 0.0 이다.
그래서 **0 은 두 상황이 겹친다** — "정확히 만실에서 겨우 맞음"과 "만실이어도
불가"가 같은 0 이다. 부르는 쪽이 구분해야 한다면 만실 DSCR 을 따로 봐야 한다.
"""

import math

import pytest

from src.analysis import acquisition, effective_rent, refi
from src.analysis.noi import noi
from src.analysis.refi import breakeven_vacancy, refi_test


# ── 브리프 확정 골든 2건(축자) ──────────────────────────────────────────

# | G-REFI-001 | NOI 121.125억·대출 1,485억·가치 2,700억·DSCR 1.3·LTV 60%·시장금리 5% |
# |   max_rate = 12.1125e9/(1.3×148.5e9) = 12.1125/193.05 = 0.0627428127 → pass, LTV 1620>1485 pass |
# |   headroom = (0.0627428127−0.05)×10000 = 127.428bp |
def test_golden_refi():
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    assert r["pass"] is True
    assert abs(r["max_rate"] - 0.0627428127) < 1e-9
    assert abs(r["headroom_bp"] - 127.428127) < 1e-4


# | G-BEV-001 | 유효 25,000·GFA 100,000·전용 0.5·opex 15%·대출 1,485억·금리 6%·DSCR 1.3 |
# |   필요 NOI = 1.3×148.5e9×0.06 = 11.583e9 → 필요 EGI = 11.583e9/0.85 = 13.6270588e9 |
# |   만실 EGI = 25000×50000×12 = 15e9 → 공실률 = 1 − 13.6270588/15 = 0.0915294118 |
def test_golden_breakeven_vacancy():
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    assert abs(v - 0.0915294118) < 1e-9


# ── refi_test: 반환 형태와 산식 ─────────────────────────────────────────

def test_refi_test_return_shape():
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    assert {"pass", "max_rate", "max_loan_by_ltv", "headroom_bp"} <= set(r)
    assert isinstance(r["pass"], bool)
    assert r["assumptions"]["caveats"]      # 가정 없는 판정은 출고 금지
    assert r["assumptions"]["notes"]


def test_refi_test_formulas_are_the_brief_definitions():
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    assert r["max_rate"] == 12_112_500_000 / (1.3 * 148_500_000_000)
    assert r["max_loan_by_ltv"] == 270_000_000_000 * 0.60
    assert r["headroom_bp"] == (r["max_rate"] - 0.05) * 10_000
    assert abs(r["max_loan_by_ltv"] - 162_000_000_000.0) < 1e-6


def test_refi_test_max_rate_is_interest_only_coverage():
    # max_rate 는 "이자만 갚아도 요구 DSCR 을 지킬 수 있는" 최대 금리다.
    # 그 금리로 빌리면 DSCR 이 정확히 요구치가 된다: NOI/(대출×max_rate) = DSCR.
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    dscr_at_max = 12_112_500_000 / (148_500_000_000 * r["max_rate"])
    assert abs(dscr_at_max - 1.3) < 1e-12


# ── refi_test: pass 는 금리와 LTV **둘 다** ─────────────────────────────

def test_refi_test_pass_requires_both_rate_and_ltv():
    # 금리는 통과하는데 LTV 가 깨지는 경우 — 가치가 2,700억에서 2,000억으로
    # 빠지면 한도가 1,200억이라 1,485억을 다시 빌릴 수 없다. headroom 은
    # 여전히 양수지만 pass 는 False 여야 한다(둘 다 봐야 하는 이유).
    r = refi_test(12_112_500_000, 148_500_000_000, 200_000_000_000, 1.3, 0.60, 0.05)
    assert r["headroom_bp"] > 0
    assert r["max_rate"] > 0.05
    assert r["max_loan_by_ltv"] == 120_000_000_000.0
    assert r["pass"] is False
    assert r["assumptions"]["rate_pass"] is True
    assert r["assumptions"]["ltv_pass"] is False


def test_refi_test_fails_and_headroom_goes_negative_when_market_rate_is_high():
    # 시장금리 8% > 최대금리 6.27% → 이자를 못 덮는다. headroom 은 음수이고
    # pass 는 False 다(둘이 정합해야 한다).
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.08)
    assert r["pass"] is False
    assert r["headroom_bp"] < 0
    assert abs(r["headroom_bp"] - (12_112_500_000 / (1.3 * 148_500_000_000) - 0.08) * 10_000) < 1e-9
    assert r["assumptions"]["rate_pass"] is False
    assert r["assumptions"]["ltv_pass"] is True


def test_refi_test_rate_equality_is_a_failure_but_ltv_equality_is_a_pass():
    # 금리 등호: NOI 62.5억·대출 1,000억·DSCR 1.25 → max_rate 정확히 0.05.
    # 여유가 0 이면 차환 여력이 없다 → pass False, headroom 0.
    eq_rate = refi_test(6_250_000_000, 100_000_000_000, 300_000_000_000, 1.25, 0.60, 0.05)
    assert eq_rate["max_rate"] == 0.05
    assert eq_rate["headroom_bp"] == 0.0
    assert eq_rate["pass"] is False
    # LTV 등호: 대출 1,500억 = 가치 3,000억 × 50%. 한도에 정확히 붙은 대출은
    # 약정을 지킨 것이다 → LTV 관문 통과(금리 관문도 서면 pass True).
    eq_ltv = refi_test(12_112_500_000, 150_000_000_000, 300_000_000_000, 1.3, 0.50, 0.05)
    assert eq_ltv["max_loan_by_ltv"] == 150_000_000_000.0
    assert eq_ltv["assumptions"]["ltv_pass"] is True
    assert eq_ltv["pass"] is True


def test_refi_test_headroom_sign_matches_the_rate_leg_everywhere():
    # headroom 부호와 금리 관문은 같은 부등식이다 — 어긋나면 보고서가
    # "여유 있는데 실패"처럼 읽힌다.
    for market_rate in (0.0, 0.01, 0.05, 0.0627428127428, 0.0627428128, 0.07, 0.2):
        r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, market_rate)
        assert (r["headroom_bp"] > 0) == r["assumptions"]["rate_pass"]
        # 이 입력은 LTV 관문을 늘 통과하므로 pass 는 금리 관문과 같다
        assert r["assumptions"]["ltv_pass"] is True
        assert r["pass"] == r["assumptions"]["rate_pass"]


def test_refi_test_rate_leg_is_the_dscr_test_in_disguise():
    # max_rate > 시장금리 ⟺ 시장금리로 빌렸을 때 DSCR 이 요구치를 넘는다.
    # 같은 판정을 두 언어로 쓴 것이므로 어긋나면 둘 중 하나가 틀렸다.
    for loan in (50e9, 100e9, 148.5e9, 250e9):
        for market_rate in (0.03, 0.05, 0.08):
            r = refi_test(12_112_500_000, loan, 270_000_000_000, 1.3, 0.60, market_rate)
            dscr_at_market = 12_112_500_000 / (loan * market_rate)
            assert r["assumptions"]["rate_pass"] == (dscr_at_market > 1.3)
            assert abs(r["assumptions"]["dscr_at_market_rate"] - dscr_at_market) < 1e-12


def test_refi_test_zero_market_rate_is_allowed_and_never_divides():
    # 무이자(시장금리 0)는 물리적으로 가능한 값이고 여기서는 그것으로 나누지
    # 않는다(hold_model 과 같은 규칙). DSCR 은 정의되지 않아 None 이다.
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.0)
    assert r["pass"] is True
    assert abs(r["headroom_bp"] - r["max_rate"] * 10_000) < 1e-9
    assert r["assumptions"]["dscr_at_market_rate"] is None


def test_refi_test_zero_noi_cannot_refinance():
    r = refi_test(0.0, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    assert r["max_rate"] == 0.0
    assert r["pass"] is False
    assert r["headroom_bp"] == -500.0


def test_refi_test_allows_loan_above_value_because_that_is_the_finding():
    # 만기에 자산가치가 대출을 밑도는 상황은 실제로 일어난다. hold_model 이
    # 대출 > 가격을 ValueError 로 막는 것과 달리 여기서는 막으면 안 된다 —
    # 이 함수가 존재하는 이유가 바로 그 판정이기 때문이다.
    r = refi_test(12_112_500_000, 200_000_000_000, 150_000_000_000, 1.3, 0.60, 0.05)
    assert r["pass"] is False
    assert r["assumptions"]["ltv_at_refi"] > 1.0


# ── refi_test: 도메인·게이트 ────────────────────────────────────────────

def test_refi_test_dscr_gate_shares_acquisition_constants():
    # 전역 제약(DSCR 0~5)의 상수는 acquisition 한 곳에만 산다 — 여기 다시
    # 적으면 두 모듈이 따로 움직인다.
    assert refi.DSCR_GATE_MIN is acquisition.DSCR_GATE_MIN
    assert refi.DSCR_GATE_MAX is acquisition.DSCR_GATE_MAX
    for bad_dscr in (130.0, -1.0, 5.01):
        with pytest.raises(RuntimeError):
            refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, bad_dscr, 0.60, 0.05)
    refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 5.0, 0.60, 0.05)  # 양끝 포함


def test_refi_test_dscr_zero_is_a_domain_error_not_a_gate_error():
    # 0 은 게이트 안이지만 최대금리가 무한대가 된다(0 으로 나눈다).
    with pytest.raises(ValueError):
        refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 0.0, 0.60, 0.05)


def test_refi_test_domain_errors():
    base = dict(noi_won_y=12_112_500_000, loan_won=148_500_000_000,
                value_won=270_000_000_000, dscr_min=1.3, ltv_max=0.60,
                market_rate=0.05)
    bad = [
        {"noi_won_y": -1.0},           # 음수 NOI
        {"loan_won": 0.0},             # 갚을 대출이 없으면 차환 판정이 없다
        {"loan_won": -1.0},
        {"value_won": 0.0},
        {"value_won": -270_000_000_000.0},
        {"ltv_max": 0.0},
        {"ltv_max": 1.01},             # 100% 초과
        {"ltv_max": 60.0},             # % 를 소수 자리에
        {"market_rate": -0.01},        # 음의 시장금리는 이 모델에 없다
        {"market_rate": 1.01},
        {"market_rate": 5.0},          # % 를 소수 자리에
    ]
    for override in bad:
        with pytest.raises(ValueError):
            refi_test(**{**base, **override})


def test_refi_test_rejects_nan_and_inf_in_every_argument():
    base = dict(noi_won_y=12_112_500_000, loan_won=148_500_000_000,
                value_won=270_000_000_000, dscr_min=1.3, ltv_max=0.60,
                market_rate=0.05)
    for name in base:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                refi_test(**{**base, name: bad})


# ── breakeven_vacancy: 산식·클램프·단조성 ───────────────────────────────

def test_breakeven_vacancy_is_the_closed_form():
    # 골든(1e−9)보다 여섯 자릿수 엄한 대조 — 값이 아니라 **산식**을 못박는다.
    # 곱셈 결합 순서가 엔진과 달라 최대 몇 ulp 는 벌어질 수 있으므로 등호 대신
    # 1e−15(값 0.09 에서 약 70ulp)로 둔다.
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    closed = 1 - (1.3 * 148_500_000_000 * 0.06) / (25_000 * 100_000 * 0.5 * 12 * 0.85)
    assert abs(v - closed) < 1e-15


def test_breakeven_vacancy_round_trips_through_noi():
    # 이 함수는 noi() 를 부르지 않고 같은 산식을 다시 쓴다. 두 모듈이 정말
    # 같은 산식인지는 왕복으로 확인한다 — 돌려받은 공실률을 noi() 에 넣으면
    # 필요 NOI(= DSCR × 대출 × 금리)가 정확히 나와야 한다.
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    got = noi(25_000, 100_000, 0.5, v, 0.15)["noi_won_y"]
    required = 1.3 * 148_500_000_000 * 0.06
    assert abs(got - required) < 1.0                       # 원 단위
    assert abs(got - 11_583_000_000.0) < 1.0
    # 그 지점의 DSCR 은 정확히 요구치다
    assert abs(got / (148_500_000_000 * 0.06) - 1.3) < 1e-12


def test_breakeven_vacancy_is_where_refi_headroom_becomes_zero():
    # 손익분기 공실률에서 NOI 는 필요 NOI 와 같으므로, 그 NOI 로 같은 금리를
    # 차환하면 최대금리가 시장금리와 정확히 만난다(여유 0 → pass False).
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    n = noi(25_000, 100_000, 0.5, v, 0.15)["noi_won_y"]
    r = refi_test(n, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.06)
    assert abs(r["headroom_bp"]) < 1e-6
    assert r["pass"] is False


def test_breakeven_vacancy_clamps_to_zero_when_already_impossible():
    # 대출 3,000억·금리 6%·DSCR 1.3 이면 필요 NOI 234억 > 만실 NOI 127.5억.
    # 산식 원값은 −0.8352941176…이지만 반환은 0.0 이다.
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 300_000_000_000, 0.06, 1.3)
    assert v == 0.0
    raw = 1 - (1.3 * 300_000_000_000 * 0.06) / (25_000 * 50_000 * 12 * 0.85)
    assert raw < 0                      # 클램프가 실제로 음수를 덮었다
    assert abs(raw + 0.8352941176470587) < 1e-12
    # 만실(공실 0)에서도 필요 NOI 에 못 미친다는 뜻이다
    full = noi(25_000, 100_000, 0.5, 0.0, 0.15)["noi_won_y"]
    assert full < 1.3 * 300_000_000_000 * 0.06


def test_breakeven_vacancy_stays_within_zero_and_one():
    for loan in (0.0, 1e9, 50e9, 148.5e9, 300e9, 1e12):
        for rate in (0.0, 0.03, 0.06, 0.12):
            v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, loan, rate, 1.3)
            assert 0.0 <= v <= 1.0


def test_breakeven_vacancy_falls_as_debt_service_rises():
    # 갚을 이자가 커질수록 견딜 수 있는 공실이 줄어든다(단조 감소).
    loans = [50e9, 100e9, 148.5e9, 200e9, 250e9]
    vs = [breakeven_vacancy(25_000, 100_000, 0.5, 0.15, L, 0.06, 1.3) for L in loans]
    assert vs == sorted(vs, reverse=True)
    assert vs[0] > vs[-1]
    # 금리·요구 DSCR 도 같은 방향이다
    assert (breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148.5e9, 0.03, 1.3)
            > breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148.5e9, 0.06, 1.3))
    assert (breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148.5e9, 0.06, 1.0)
            > breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148.5e9, 0.06, 1.3))


def test_breakeven_vacancy_zero_debt_tolerates_any_vacancy():
    # 무차입이면 공실률로 깨질 DSCR 자체가 없다 → 1.0(어떤 공실도 견딘다).
    # 금리 0 도 같다. hold_model 이 대출 0·금리 0 을 허용하는 것과 같은 규칙이다.
    assert breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 0.0, 0.06, 1.3) == 1.0
    assert breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.0, 1.3) == 1.0


# ── breakeven_vacancy: 도메인·게이트 ────────────────────────────────────

def test_breakeven_vacancy_rent_gate_shares_effective_rent_constants():
    # noi() 를 거치지 않으므로 임대료 물리 게이트를 여기서 다시 건다 —
    # 없으면 25(천원/㎡·월)나 연액을 넣은 입력이 조용히 통과해 손익분기
    # 공실률이 배수로 어긋난다.
    assert refi.RENT_MIN_WON_M2_MO is effective_rent.RENT_MIN_WON_M2_MO
    assert refi.RENT_MAX_WON_M2_MO is effective_rent.RENT_MAX_WON_M2_MO
    for bad_rent in (25.0, 9_999.0, 60_001.0, 300_000.0):
        with pytest.raises(RuntimeError):
            breakeven_vacancy(bad_rent, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    breakeven_vacancy(effective_rent.RENT_MIN_WON_M2_MO, 100_000, 0.5, 0.15, 1e9, 0.06, 1.3)
    breakeven_vacancy(effective_rent.RENT_MAX_WON_M2_MO, 100_000, 0.5, 0.15, 1e9, 0.06, 1.3)


def test_breakeven_vacancy_zero_rent_is_a_domain_error_not_a_gate_error():
    # 0·음수 임대료는 범위 밖이기도 하지만 단위 문제가 아니다(noi() 와 같다).
    for bad_rent in (0.0, -25_000.0):
        with pytest.raises(ValueError):
            breakeven_vacancy(bad_rent, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)


def test_breakeven_vacancy_dscr_gate_and_zero():
    for bad_dscr in (130.0, -1.0, 5.01):
        with pytest.raises(RuntimeError):
            breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, bad_dscr)
    breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 1e9, 0.06, 5.0)      # 양끝 포함
    with pytest.raises(ValueError):
        # 0 은 게이트 안이지만 "커버리지를 요구하지 않는다"는 뜻이라 손익분기
        # 공실률이 1 로 나온다 — 낙관 쪽 침묵이라 막는다(max_loan 과 같은 규칙).
        breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 0.0)


def test_breakeven_vacancy_domain_errors():
    base = dict(eff_rent=25_000, gfa=100_000, efficiency=0.5, opex_ratio=0.15,
                loan_won=148_500_000_000, loan_rate=0.06, dscr_min=1.3)
    bad = [
        {"eff_rent": 0.0},
        {"gfa": 0.0},
        {"gfa": -100_000.0},
        {"efficiency": 0.0},
        {"efficiency": 1.01},
        {"efficiency": 50.0},          # % 를 소수 자리에
        {"opex_ratio": -0.01},
        {"opex_ratio": 1.0},           # 운영경비가 수입 전부면 소득이 0 이다
        {"opex_ratio": 15.0},          # % 를 소수 자리에
        {"loan_won": -1.0},
        {"loan_rate": -0.01},
        {"loan_rate": 1.01},
        {"loan_rate": 6.0},            # % 를 소수 자리에
    ]
    for override in bad:
        with pytest.raises(ValueError):
            breakeven_vacancy(**{**base, **override})


def test_breakeven_vacancy_rejects_nan_and_inf_in_every_argument():
    base = dict(eff_rent=25_000, gfa=100_000, efficiency=0.5, opex_ratio=0.15,
                loan_won=148_500_000_000, loan_rate=0.06, dscr_min=1.3)
    for name in base:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                breakeven_vacancy(**{**base, name: bad})


# ── 모듈 규약(순수 함수·유한성·연결) ───────────────────────────────────

def test_no_nan_leaks_into_results():
    r = refi_test(12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    assert math.isfinite(r["max_rate"])
    assert math.isfinite(r["max_loan_by_ltv"])
    assert math.isfinite(r["headroom_bp"])
    v = breakeven_vacancy(25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3)
    assert math.isfinite(v)


def test_refi_test_is_a_pure_function():
    args = (12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05)
    a, b = refi_test(*args), refi_test(*args)
    assert a == b
    assert a is not b
    a["assumptions"]["notes"].append("오염")
    assert len(refi_test(*args)["assumptions"]["notes"]) == len(b["assumptions"]["notes"])


def test_pipeline_max_loan_feeds_refi_test():
    # 취득 시점 대출(1,485억·ltv 결속)을 5년 뒤 같은 NOI·같은 가치로 차환한다.
    # 두 함수가 같은 단위(원·소수 연율)로 맞물린다.
    loan = acquisition.max_loan(12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045)
    r = refi_test(12_112_500_000, loan["loan_won"], 270_000_000_000, 1.3, 0.60, 0.05)
    assert r["pass"] is True
    # 취득 LTV 55% 로 빌린 대출은 차환 한도 60% 안에 있다
    assert r["assumptions"]["ltv_at_refi"] < 0.60
