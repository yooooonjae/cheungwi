"""차환 — 만기에 다시 빌릴 수 있는가, 공실은 어디까지 버티는가.

취득 때 계산이 맞았어도 대출은 만기가 온다. 그 시점에 같은 대출을 다시
세우려면 두 가지가 동시에 서야 한다. 소득이 이자를 요구 배수만큼 덮어야
하고(금리), 담보가치가 대출을 담아야 한다(LTV). `refi_test` 는 그 둘을 함께
판정하고, 견딜 수 있는 금리의 상한과 시장금리까지의 여유(bp)를 함께 낸다.

    max_rate         = NOI ÷ (요구 DSCR × 대출)        (IO — 이자만 덮는다)
    max_loan_by_ltv  = 가치 × LTV 한도
    headroom_bp      = (max_rate − 시장금리) × 10,000
    pass             = (max_rate > 시장금리) **AND** (대출 ≤ max_loan_by_ltv)

`breakeven_vacancy` 는 같은 관계를 공실률 축에서 되돌려 푼다 — DSCR 이 정확히
요구치가 되는 공실률이다.

    필요 NOI = 요구 DSCR × 대출 × 금리
    공실률   = 1 − 필요 NOI ÷ (임대료 × 임대면적 × 12 × (1 − opex))

전부 순수 함수다 — I/O 도 전역 상태도 없다. 임포트는 게이트 상수 넷
(`acquisition` 의 DSCR, `effective_rent` 의 임대료)과 `fin_core.require_finite`
뿐이다.

규약이 넷 있다.

1. **금액은 원, 이율·비율은 소수 연율, 임대료는 원/㎡·월이다.** NOI 는 원/년.
   금리 5% 는 `0.05`, LTV 60% 는 `0.60`. ×12 는 `breakeven_vacancy` 안에서
   한다(`noi()` 와 같은 규약).
2. **IO(이자만 상환) 가정이다.** `max_rate` 는 원리금이 아니라 이자를 덮는
   금리다(DSCR = NOI ÷ (대출 × 금리) ≥ 요구치를 금리에 대해 푼 것).
   원리금 상환 조건이면 상환액이 커져 견딜 수 있는 금리가 이보다 **낮다** —
   이 값을 원리금 조건에 그대로 인용하면 차환 여력이 과대 평가된다.
   `acquisition.max_loan` 의 DSCR 제약과 같은 가정이다.
3. **`pass` 는 두 관문의 AND 다.** 금리와 LTV 가 둘 다 서야 True 다. 하나만
   보면 "이자는 덮는데 담보가치가 빠져 대출을 못 세우는" 경우가 조용히
   통과한다 — 만기 차환이 실제로 깨지는 전형적인 경로가 그쪽이다. 등호는
   두 관문이 다르게 다룬다: 금리는 **초과**(`>`)여야 하고 LTV 는
   **이하**(`≤`)면 된다. 최대금리가 시장금리와 정확히 같으면 여유가 0 이라
   차환 여력이 없다고 보고, 대출이 한도에 정확히 붙으면 약정은 지킨 것이다.
   그래서 `headroom_bp == 0` 과 `pass is False` 는 서로 정합하다.
4. **`headroom_bp` 는 음수가 될 수 있다.** 시장금리가 최대금리를 넘은 만큼을
   부호로 그대로 보여준다(0 으로 자르지 않는다). 자르면 "겨우 통과"와 "크게
   미달"이 같은 0 으로 뭉개진다. 음수 headroom 은 `pass is False` 와 짝이다.

**등호 해석이 `acquisition` 과 반대인 지점이 하나 있다.** `max_loan` 의 DSCR
제약은 등호를 통과로 읽는다 — DSCR 이 정확히 요구치인 대출을 결속 조건으로
승인한다. 그렇게 승인된 대출을 같은 금리로 이 함수에 넣으면 `max_rate` 가
시장금리와 정확히 같아져 `headroom_bp == 0` 이 되고 `pass` 는 **False** 다.
한 엔진 안에서 같은 부등식을 반대로 읽는 셈이라, 일부러 남겨 둔 경계다:
취득 시점의 "지금 최대 얼마까지 빌릴 수 있나"와 만기의 "앞으로도 다시 빌릴 수
있나"는 묻는 것이 다르다. 뒤쪽은 금리가 1bp 만 올라도 깨지는 대출을 "차환
가능"이라 부르지 않는다 — 판정이 보수적인 방향으로 어긋난다. 같은 함수 안의
LTV 관문이 등호를 통과로 두는 것과도 어긋나 보이지만, 그쪽은 **여력**이 아니라
**약정 준수**를 묻기 때문에 한도에 정확히 붙은 대출이 위반은 아니다. 이 경계는
`test_refi_test_rejects_the_dscr_bound_loan_that_acquisition_approved` 가
`max_loan` → `refi_test` 로 실제 값을 흘려 고정한다.

**낙관 쪽 침묵은 게이트가 아니라 신호로 공시한다.** 대출 금액의 단위 오입력
(억↔원)은 계획이 정한 물리 게이트 셋(cap·임대료·DSCR) 어디에도 걸리지 않고,
하필 `pass` 를 True 로 만드는 방향이다. 새 게이트를 만들어 막는 대신
`implausible` 플래그를 둔다 — `max_rate` 가 1.0(이자만으로 연 100% 초과를
견딘다)을 넘거나 차환 LTV 가 1% 를 밑도는, 실무에서 나올 수 없는 조합에서만
켜진다. **판정(`pass`)은 건드리지 않는다**(값을 지어내지 않는다). 정상 건에서는
꺼져 있어 신호가 잡음에 묻히지 않는 것이 이 방식의 요점이다.

**대출이 가치를 넘어도 막지 않는다.** `acquisition.hold_model` 은 대출 > 가격을
`ValueError` 로 막지만(취득 시점에 LTV 100% 초과 구조는 이 모델에 없다),
차환 시점에는 자산가치가 대출 밑으로 빠지는 일이 실제로 일어난다. 그 판정이
이 함수가 존재하는 이유라서, 막으면 정작 찾아야 할 결과를 가린다 —
`assumptions.ltv_at_refi` 가 1 을 넘는 값으로 나오고 `pass` 는 False 다.

`breakeven_vacancy` 는 `noi()` 를 부르지 않고 같은 산식을 다시 쓴다(닫힌형
역산이라 공실률을 알기 전에는 `noi()` 를 부를 수 없다). 그래서 **임대료 물리
게이트를 이 함수가 직접 건다** — `noi()` 를 거치는 경로에만 게이트가 있으면
25(천원/㎡·월)나 연액을 넣은 입력이 여기서 조용히 통과해 손익분기 공실률이
배수로 어긋난다. 상수는 `effective_rent` 것을, DSCR 게이트 상수는
`acquisition` 것을 임포트해 쓴다 — 여기 다시 적으면 모듈들이 따로 움직인다.

오류 유형은 둘을 구분한다.

- `ValueError` — 값이 물리적으로 말이 안 된다(음수 NOI, 대출 0, 가치 0,
  LTV 1.01, 임대료 0, NaN·inf 등). NaN 은 크기 비교가 전부 False 라 도메인
  검사와 게이트를 조용히 통과하거나 오류 유형을 뒤바꾸므로 **가장 먼저**
  유한성을 확인한다.
- `RuntimeError` — 값 자체는 말이 되는데 단위·자릿수를 의심해야 한다. 물리
  게이트 둘이다: DSCR 0~5, 유효임대료 10,000~60,000원/㎡·월.

검사 순서는 인자 순서가 아니라 **유형 순서**다(`acquisition` 과 같다).
① 모든 인자의 유한성 → ② 도메인 → ③ 게이트. 그래서 인자 둘이 동시에 틀리면
먼저 나오는 오류는 "앞쪽 인자"가 아니라 "앞쪽 유형"이다(예: 임대료 25 와
GFA −1 을 함께 넣으면 GFA 쪽 `ValueError` 가 먼저다). 이 순서의 예외가 하나
있다 — `dscr_min` 은 게이트를 도메인보다 먼저 건다. 전역 제약이 "DSCR 0~5
밖은 RuntimeError" 로 오류 유형을 못박고 있어서 음수 DSCR 을 도메인 검사로
먼저 잡으면 유형이 어긋나기 때문이다. 게이트 안이면서도 쓸 수 없는
`dscr_min == 0` 만 그 뒤에서 `ValueError` 로 잡는다.
"""

from src.analysis.acquisition import DSCR_GATE_MAX, DSCR_GATE_MIN
from src.analysis.effective_rent import RENT_MAX_WON_M2_MO, RENT_MIN_WON_M2_MO
from src.analysis.fin_core import require_finite

# 소수 이율 1 = 10,000 베이시스포인트. headroom 의 단위 변환에만 쓴다.
BP_PER_UNIT = 10_000.0

# 실무에서 나올 수 없는 조합의 경계 — 게이트가 아니라 **신호**다(예외를 던지지도
# 판정을 바꾸지도 않는다). 대출 금액의 단위 오입력(억↔원)이 물리 게이트 셋에
# 걸리지 않고 pass 를 True 로 만드는 구멍을 여기서 드러낸다.
IMPLAUSIBLE_MAX_RATE_OVER = 1.0    # 이자만으로 연 100% 초과를 견딘다
IMPLAUSIBLE_LTV_UNDER = 0.01       # 대출이 가치의 1% 도 안 된다

# `noi()` 가 같은 값을 사적으로 들고 있다 — 두 모듈이 어긋나면
# `test_breakeven_vacancy_round_trips_through_noi` 의 왕복이 깨진다.
_MONTHS_PER_YEAR = 12


def _gate_dscr(dscr_min: float) -> None:
    """요구 DSCR 이 물리 범위(0~5) 안인지 확인한다. 밖이면 멈춘다.

    범위 상수는 `acquisition` 것을 그대로 쓴다(단일 출처 — 전역 제약이다).
    NaN 은 부르는 쪽이 먼저 `ValueError` 로 걸러 여기 오지 않는다.
    """
    if not DSCR_GATE_MIN <= dscr_min <= DSCR_GATE_MAX:
        raise RuntimeError(
            f"요구 DSCR {dscr_min:,.4f} 이 물리 범위"
            f"[{DSCR_GATE_MIN}, {DSCR_GATE_MAX}] 밖이다 — DSCR 이 아니라 "
            "단위(배수↔%)를 의심하라. 1.3 을 130 으로 넣으면 차환 가능 최대금리가 "
            "100분의 1 이 되어 멀쩡한 건물이 차환 불가로 나오고, 음수면 제약이 "
            "뒤집힌다"
        )


def _gate_rent(rent_won_m2_mo: float) -> None:
    """임대료가 물리 범위(원/㎡·월) 안인지 확인한다. 밖이면 멈춘다.

    범위 상수는 `effective_rent` 것을 그대로 쓴다(단일 출처). 부호·NaN 은
    부르는 쪽이 먼저 `ValueError` 로 걸러 여기 오지 않는다 — 여기 걸리는 값은
    "임대료로는 말이 되는데 자릿수가 이상한" 값뿐이라 메시지가 단위를 짚는다.
    """
    if not RENT_MIN_WON_M2_MO <= rent_won_m2_mo <= RENT_MAX_WON_M2_MO:
        raise RuntimeError(
            f"유효임대료 {rent_won_m2_mo:,.1f}원/㎡·월이 물리 범위"
            f"[{RENT_MIN_WON_M2_MO:,.0f}, {RENT_MAX_WON_M2_MO:,.0f}] 밖이다 — "
            "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라. 이대로 두면 만실 "
            "수입이 배수로 어긋나 손익분기 공실률이 조용히 틀린다"
        )


def refi_test(
    noi_won_y: float,
    loan_won: float,
    value_won: float,
    dscr_min: float,
    ltv_max: float,
    market_rate: float,
) -> dict:
    """만기 차환 판정 — 견딜 수 있는 최대금리와 시장금리까지의 여유(bp).

    | 항목            | 산식                       | 예(G-REFI-001)                |
    |-----------------|----------------------------|-------------------------------|
    | max_rate        | NOI ÷ (요구 DSCR × 대출)   | 121.125/(1.3×1,485)억 = 6.2743% |
    | max_loan_by_ltv | 가치 × LTV 한도            | 2,700억 × 0.60 = 1,620.0억    |
    | headroom_bp     | (max_rate − 시장금리)×10000| (0.0627428−0.05)×10⁴ = 127.43bp |
    | **pass**        | 금리 AND LTV               | 6.27% > 5% · 1,485 ≤ 1,620 → **True** |

    `max_rate` 는 **IO 가정**의 금리다(규약 2). 그 금리로 빌리면 DSCR 이
    정확히 요구치가 된다 — NOI ÷ (대출 × max_rate) = 요구 DSCR. 금리 관문은
    "시장금리로 빌렸을 때 DSCR 이 요구치를 넘는가"와 같은 부등식을 금리 축에서
    쓴 것이라, `assumptions.dscr_at_market_rate` 와 판정이 어긋날 수 없다.

    **`pass` 는 두 관문의 AND 이고 등호 처리가 다르다**(규약 3): 금리는
    `max_rate > market_rate`, LTV 는 `loan_won <= max_loan_by_ltv`. 어느 쪽이
    깨졌는지는 `assumptions` 의 `rate_pass`·`ltv_pass` 로 갈라 실어 보낸다 —
    `pass` 만 인용하면 "금리가 올라서"인지 "가치가 빠져서"인지가 사라진다.

    등호 처리는 `acquisition.max_loan` 과 반대다. 그쪽이 DSCR 결속으로 승인한
    대출(DSCR 이 정확히 요구치)을 같은 금리로 여기 넣으면 `headroom_bp` 가 0 이
    되어 부결된다. 일부러 남긴 경계이고 사유는 모듈 docstring 에 있다.

    도메인: NOI ≥ 0 · 대출 > 0 · 가치 > 0 · LTV 한도 ∈ (0, 1] ·
    시장금리 ∈ [0, 1]. 밖이면 `ValueError`. NOI 0(전관 공실)은 최대금리 0 을
    돌려주고 판정은 False 다. 대출 0 은 막는다 — 갚을 대출이 없으면 차환
    판정이라는 것 자체가 없고, 최대금리가 0 으로 나누어 무한대가 된다.
    시장금리 0(무이자)은 허용한다 — 여기서는 그것으로 나누지 않는다
    (`hold_model` 과 같은 규칙, 이때 `dscr_at_market_rate` 는 `None` 이다).
    **대출 > 가치는 막지 않는다** — 그 상황의 판정이 이 함수의 목적이다.

    게이트: 요구 DSCR 은 0~5(양끝 포함) 안이어야 한다. 밖이면 `RuntimeError`.
    0 은 게이트 안이지만 최대금리가 무한대가 되므로 `ValueError` 다.

    반환: `{"pass", "max_rate", "max_loan_by_ltv", "headroom_bp", "implausible",
    "implausible_reasons", "assumptions": {...}}`. 판정 하나만 떼어 인용하면 안
    된다 — 가치 추정과 대출 조건 가정이 바뀌면 판정도 바뀐다.

    **`implausible` 이 True 면 판정보다 입력을 먼저 보라.** 최대금리가 1.0 을
    넘거나 차환 LTV 가 1% 를 밑도는, 실무에 없는 조합에서만 켜지는 신호다
    (`implausible_reasons` 에 사유 문구가 들어간다). 켜져도 예외를 던지지 않고
    `pass` 도 바꾸지 않는다 — 물리 게이트가 아니라 공시이기 때문이다. 정상
    입력에서는 꺼져 있고 사유는 빈 리스트다.
    """
    require_finite(noi_won_y, "NOI")
    require_finite(loan_won, "대출")
    require_finite(value_won, "가치")
    require_finite(dscr_min, "요구 DSCR")
    require_finite(ltv_max, "LTV 한도")
    require_finite(market_rate, "시장금리")

    if noi_won_y < 0:
        raise ValueError(f"NOI 는 음수일 수 없다: {noi_won_y}")
    if loan_won <= 0:
        raise ValueError(
            f"차환할 대출은 양수여야 한다: {loan_won}. 갚을 대출이 없으면 차환 "
            "판정이 없고, 최대금리가 0 으로 나누어 무한대가 된다"
        )
    if value_won <= 0:
        raise ValueError(f"가치는 양수여야 한다: {value_won}")
    if not 0 < ltv_max <= 1:
        raise ValueError(f"LTV 한도는 (0, 1] 인 소수여야 한다(60% = 0.60): {ltv_max}")
    if not 0 <= market_rate <= 1:
        raise ValueError(
            f"시장금리는 [0, 1] 인 소수여야 한다(5% = 0.05): {market_rate}"
        )

    _gate_dscr(dscr_min)
    if dscr_min <= 0:
        raise ValueError(
            f"요구 DSCR 은 양수여야 한다: {dscr_min}. 0 은 '커버리지를 요구하지 "
            "않는다'는 뜻이라 견딜 수 있는 금리가 무한대가 된다"
        )

    max_rate = noi_won_y / (dscr_min * loan_won)
    max_loan_by_ltv = value_won * ltv_max
    headroom_bp = (max_rate - market_rate) * BP_PER_UNIT

    # 규약 3 — 금리는 초과(여유 0 은 여력 없음), LTV 는 이하(한도에 붙어도 약정
    # 준수). 둘 다 서야 차환이 선다.
    rate_pass = max_rate > market_rate
    ltv_pass = loan_won <= max_loan_by_ltv

    ltv_at_refi = loan_won / value_won
    # 게이트가 아니라 신호다 — 판정(pass)을 바꾸지 않고 조건이 설 때만 켠다.
    implausible_reasons = []
    if max_rate > IMPLAUSIBLE_MAX_RATE_OVER:
        implausible_reasons.append(
            f"견딜 수 있는 최대금리가 {max_rate:,.2f}(= 연 "
            f"{max_rate * 100:,.0f}%)로 {IMPLAUSIBLE_MAX_RATE_OVER * 100:.0f}% 를 "
            f"넘는다 — 대출 {loan_won:,.0f}원이 NOI 에 비해 너무 작다. 금액 단위"
            "(억↔원)를 의심하라"
        )
    if ltv_at_refi < IMPLAUSIBLE_LTV_UNDER:
        implausible_reasons.append(
            f"차환 LTV 가 {ltv_at_refi:.6f}(= {ltv_at_refi * 100:.4f}%)로 "
            f"{IMPLAUSIBLE_LTV_UNDER * 100:.0f}% 를 밑돈다 — 대출 "
            f"{loan_won:,.0f}원과 가치 {value_won:,.0f}원의 자릿수가 맞지 않는다"
        )

    return {
        "pass": rate_pass and ltv_pass,
        "max_rate": max_rate,
        "max_loan_by_ltv": max_loan_by_ltv,
        "headroom_bp": headroom_bp,
        "implausible": bool(implausible_reasons),
        "implausible_reasons": implausible_reasons,
        "assumptions": {
            "noi_won_y": noi_won_y,
            "loan_won": loan_won,
            "value_won": value_won,
            "dscr_min": dscr_min,
            "ltv_max": ltv_max,
            "market_rate": market_rate,
            "rate_pass": rate_pass,
            "ltv_pass": ltv_pass,
            "ltv_at_refi": ltv_at_refi,
            "interest_at_market_rate_won_y": loan_won * market_rate,
            "dscr_at_market_rate": (
                noi_won_y / (loan_won * market_rate) if market_rate > 0 else None
            ),
            "notes": [
                f"max_rate = NOI ÷ (요구 DSCR {dscr_min} × 대출 "
                f"{loan_won:,.0f}원) = {max_rate:.6f} — **IO(이자만 상환)** "
                "가정이다. 원리금 상환 조건이면 상환액이 커져 견딜 수 있는 "
                "금리가 이보다 낮아진다.",
                f"pass 는 금리(max_rate > 시장금리 {market_rate}: {rate_pass})와 "
                f"LTV(대출 ≤ 가치 × 한도 {ltv_max} = {max_loan_by_ltv:,.0f}원: "
                f"{ltv_pass})의 **AND** 다. 등호는 금리 쪽이 실패(여유 0), "
                "LTV 쪽이 통과(한도 준수)로 갈린다.",
                f"headroom {headroom_bp:,.2f}bp 는 부호를 그대로 둔다 — 음수면 "
                "시장금리가 견딜 수 있는 금리를 그만큼 넘었다는 뜻이고 pass 는 "
                "False 다.",
                f"차환 시점 LTV = 대출 ÷ 가치 = {ltv_at_refi:.4f}. "
                "1 을 넘는 값도 막지 않는다 — 자산가치가 대출 밑으로 빠진 상황을 "
                "판정하는 것이 이 함수의 목적이다.",
                (
                    "**implausible 신호가 켜졌다** — 판정보다 입력을 먼저 보라: "
                    + " / ".join(implausible_reasons)
                    if implausible_reasons
                    else "implausible 신호는 꺼져 있다 — 최대금리와 차환 LTV 가 "
                    "실무 범위 안이다(신호는 max_rate > "
                    f"{IMPLAUSIBLE_MAX_RATE_OVER} 또는 차환 LTV < "
                    f"{IMPLAUSIBLE_LTV_UNDER} 에서만 켜진다)."
                ),
            ],
            "caveats": [
                "가치(value_won)가 감정가라면 그 자체가 추정치다 — cap 가정 하나가 "
                "움직이면 LTV 관문의 판정이 뒤집힌다. 실거래가 아닌 값을 넣었다면 "
                "cap 가정과 오차 분포를 함께 인용해야 한다.",
                "NOI 는 정상화 한 해의 값이다. 만기 시점에 임대차 만기·리스업 "
                "공백이 겹쳐 실제 NOI 가 낮으면 max_rate 는 그만큼 과대하다.",
                "시장금리 하나로 봤다 — 대주 스프레드·주선·약정 수수료·금리 상한"
                "(cap) 비용·중도상환 수수료는 들어 있지 않다. 실제 차환 금리는 "
                "여기 넣은 시장금리보다 높다.",
                "요구 DSCR·LTV 한도는 시장 관행 수준의 가정이며 실제 대주 심사 "
                "결과가 아니다. 만기 시점의 대출 시장이 조이면 둘 다 나빠진다.",
                "선순위 한 트랜치만 본다. 메자닌·후순위를 얹거나 자기자본을 더 "
                "넣어 대출을 줄이는(부분 상환) 대안은 이 판정에 없다 — pass 가 "
                "False 라도 구조를 바꾸면 차환이 될 수 있다.",
                "대출 금액의 단위 오입력(억↔원)은 물리 게이트가 없는 축이라 "
                "막지 못한다. 1,485억을 1,485 로 넣으면 max_rate 가 터무니없이 "
                "커지고 pass 가 True 로 나온다 — 그 조합에서 implausible 신호가 "
                "켜지지만 예외를 던지지는 않으므로, 부르는 쪽이 신호를 읽어야 한다.",
            ],
        },
    }


def breakeven_vacancy(
    eff_rent: float,
    gfa: float,
    efficiency: float,
    opex_ratio: float,
    loan_won: float,
    loan_rate: float,
    dscr_min: float,
) -> float:
    """DSCR 이 정확히 요구치가 되는 공실률(소수). 이미 불가면 0.

    | 단계      | 산식                              | 예(G-BEV-001)                 |
    |-----------|-----------------------------------|-------------------------------|
    | 필요 NOI  | 요구 DSCR × 대출 × 금리           | 1.3×1,485억×0.06 = 115.83억   |
    | 필요 EGI  | 필요 NOI ÷ (1 − opex)             | 115.83/0.85 = 136.270588…억   |
    | 만실 EGI  | 임대료 × (GFA × 전용률) × 12      | 25,000×50,000×12 = 150.0억    |
    | **공실률**| 1 − 필요 EGI ÷ 만실 EGI           | **0.0915294117…**             |

    닫힌형 한 줄로 쓰면

        1 − (요구 DSCR × 대출 × 금리) ÷ (임대료 × GFA × 전용률 × 12 × (1 − opex))

    이다. 공실률을 알기 전에는 `noi()` 를 부를 수 없어(그 값이 답이다) 같은
    산식을 다시 쓴다 — 그래서 **임대료 물리 게이트를 이 함수가 직접 건다**
    (모듈 docstring 참조). 돌려받은 공실률을 `noi()` 에 넣으면 NOI 가 정확히
    필요 NOI 로 나오는 것이 두 모듈이 같은 산식이라는 증거다.

    `noi()` 와 같은 세 가정을 쓴다 — 전용률은 GFA 대비 **임대면적** 비율이고,
    `opex_ratio` 는 총 운영경비가 아니라 관리비 상계 후 **미회수분**이다.

    **반환값은 [0, 1] 이고 0 은 두 상황이 겹친다.** 산식이 음수를 내면(만실
    이어도 필요 NOI 를 못 채운다) 0 으로 자른다. 그래서 "정확히 만실에서 겨우
    맞는 건물"과 "만실이어도 불가한 건물"이 같은 0 이 된다 — 구분이 필요하면
    공실 0 의 `noi()` 를 필요 NOI 와 직접 비교해야 한다. 위쪽은 자를 필요가
    없다(필요 NOI ≥ 0 이라 산식이 1 을 넘지 못한다). 대출 0 이나 금리 0 이면
    1.0 이다 — 갚을 이자가 없으면 공실률로 깨질 DSCR 자체가 없다.

    도메인: 유효임대료 > 0 · GFA > 0 · 전용률 ∈ (0, 1] · opex_ratio ∈ [0, 1) ·
    대출 ≥ 0 · 금리 ∈ [0, 1]. 밖이면 `ValueError`. 대출 0·금리 0 을 허용하는
    것은 여기서 그것으로 나누지 않기 때문이다(`hold_model` 과 같은 규칙).

    게이트: 유효임대료 10,000~60,000원/㎡·월, 요구 DSCR 0~5(양끝 포함). 밖이면
    `RuntimeError`. 요구 DSCR 0 은 게이트 안이지만 `ValueError` 다 — 커버리지를
    요구하지 않으면 공실률이 1(어떤 공실에도 안 깨진다)로 나오는데, 그것은
    안전한 쪽이 아니라 **낙관 쪽 침묵**이다(`max_loan` 과 같은 규칙).

    이 함수만 `assumptions` 봉투 없이 float 하나를 돌려준다. 임대료·전용률·
    opex·대출 조건 가정은 부르는 쪽이 이미 들고 있는 값이므로, 이 숫자를
    인용할 때 그 가정들을 함께 실어야 한다.
    """
    require_finite(eff_rent, "유효임대료")
    require_finite(gfa, "연면적")
    require_finite(efficiency, "전용률")
    require_finite(opex_ratio, "운영경비율")
    require_finite(loan_won, "대출")
    require_finite(loan_rate, "대출금리")
    require_finite(dscr_min, "요구 DSCR")

    if eff_rent <= 0:
        raise ValueError(f"유효임대료는 양수여야 한다: {eff_rent}")
    if gfa <= 0:
        raise ValueError(f"연면적은 양수여야 한다: {gfa}")
    if not 0 < efficiency <= 1:
        raise ValueError(f"전용률은 (0, 1] 이어야 한다: {efficiency}")
    if not 0 <= opex_ratio < 1:
        raise ValueError(f"운영경비율은 [0, 1) 이어야 한다: {opex_ratio}")
    if loan_won < 0:
        raise ValueError(f"대출은 음수일 수 없다: {loan_won}")
    if not 0 <= loan_rate <= 1:
        raise ValueError(f"대출금리는 [0, 1] 인 소수여야 한다(6% = 0.06): {loan_rate}")

    _gate_rent(eff_rent)
    _gate_dscr(dscr_min)
    if dscr_min <= 0:
        raise ValueError(
            f"요구 DSCR 은 양수여야 한다: {dscr_min}. 0 은 '커버리지를 요구하지 "
            "않는다'는 뜻이라 손익분기 공실률이 1(어떤 공실에도 안 깨진다)로 "
            "나오는데, 안전한 쪽이 아니라 낙관 쪽 침묵이다"
        )

    nla = gfa * efficiency
    full_egi_won_y = eff_rent * nla * _MONTHS_PER_YEAR   # 공실 0 의 EGI = PGI
    required_noi_won_y = dscr_min * loan_won * loan_rate

    # 분모는 도메인 검사가 양수를 보장한다(임대료·면적 > 0, opex < 1).
    vacancy = 1 - required_noi_won_y / (full_egi_won_y * (1 - opex_ratio))

    # 음수는 "만실이어도 못 맞춘다"는 뜻이다 — 0 으로 자른다(이미 불가).
    return max(0.0, vacancy)
