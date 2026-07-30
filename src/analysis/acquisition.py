"""인수금융 — 삼중 제약 대출가능액과 보유기간 지분수익률.

한 동을 사는 데 얼마를 빌릴 수 있는지(`max_loan`)와, 그렇게 빌려 사서 몇 해
굴리다 팔면 지분이 얼마를 버는지(`hold_model`)를 계산한다.

    max_loan   : min(가격×LTV, (NOI÷DSCR)÷금리, NOI÷DY) — 셋 중 가장 작은 것
    hold_model : 분기 현금흐름 → fin_core.irr_annual → 지분 IRR

금융 산식은 스스로 쓰지 않고 `fin_core` 를 부른다(IRR 은 그쪽 엔진이 이미
골든 검증을 마쳤다). 이 모듈이 책임지는 것은 **현금흐름 배열이 규약대로
조립되는가**다.

전부 순수 함수다 — I/O 도 전역 상태도 없다. 임포트는 `fin_core` 의
`irr_annual`·`require_finite` 와 `caprate` 의 cap 게이트 상수 둘뿐이다.

규약이 넷 있다.

1. **금액은 원, 이율·비율은 소수 연율이다.** 금리 4.5% 는 `0.045`, LTV 55% 는
   `0.55`, DY 8% 는 `0.08`. NOI 는 원/년.
2. **현금흐름 원소는 분기다**(`fin_core` 규약 그대로). `cashflows_q[0]` 이
   0분기(취득 시점), `[1]` 이 1분기 뒤다. 반환 길이는 `4 × hold_years + 1`.
   연 단위 값을 그대로 넣으면 IRR 이 4배 어긋난다.
3. **원금은 갚지 않는다(IO, interest-only).** 두 함수 모두 대출 상환을
   이자만으로 본다. `max_loan` 의 DSCR 제약은 원리금이 아니라 이자를 덮고
   (`(NOI÷DSCR)÷금리`), `hold_model` 의 분기 흐름에는 원금 상환이 없다 —
   원금은 매각 시점에 한 번에 상계된다. 원리금균등을 가정하면 상환액이
   커져 대출가능액이 **작아지므로**, IO 를 조용히 쓰면 대출 여력이 과대
   평가된다. 그래서 `io=False` 는 계산하지 않고 `NotImplementedError` 다
   (상환 연수가 시그니처에 없어 원리금을 정의할 수 없다).
4. **NOI 성장은 연 단위 계단이다.** t년차 NOI = 기준 NOI × (1+g)^t 이고
   (1년차가 t=0), 한 해 안의 네 분기는 값이 같다. 매각가에 쓰는 NOI 는
   보유 마지막 해가 아니라 **그 다음 해**(t=hold_years)다 — 사는 쪽은 앞으로
   벌 돈을 보고 값을 매기기 때문이다.

오류 유형은 셋을 쓰지만 **서로소가 아니다**(아래 경고 참조).

- `ValueError` — 값이 물리적으로 말이 안 된다(음수 NOI, 가격 0, LTV 1.01,
  NaN·inf 등). NaN 은 크기 비교가 전부 False 라 도메인 검사와 게이트를 조용히
  통과하므로, 모든 인자에 대해 **가장 먼저** 유한성을 확인한다.
- `RuntimeError` — 값 자체는 말이 되는데 단위·자릿수를 의심해야 한다. 물리
  게이트 둘이다: DSCR 0~5(전역 제약), exit cap 0.02~0.12(`caprate` 상수를
  임포트해 쓴다 — 여기 다시 적으면 두 모듈이 따로 움직인다).
- `NotImplementedError` — `io=False`. 위 규약 3 참조.

**`NotImplementedError` 는 `RuntimeError` 의 하위형이다**(MRO:
NotImplementedError → RuntimeError → Exception). 이 저장소에서 `RuntimeError`
는 "단위·자릿수를 의심하라"는 뜻으로만 쓰이는데, `except RuntimeError` 로만
감싸면 `io=False`(애초에 계산할 수 없다는 신호)가 **거기 걸려 단위 오류로
조용히 오분류된다**. 그러니 부르는 쪽은 반드시

    except NotImplementedError:   # 계산 불가 — 입력을 고쳐도 안 된다
        ...
    except RuntimeError:          # 물리 게이트 위반 — 단위를 의심하라
        ...

순서로, **`NotImplementedError` 를 `RuntimeError` 보다 먼저** 잡아야 한다.
반대로 쓰면 두 상황이 한 갈래로 뭉개진다. 이 관계와 순서는
`tests/test_acquisition.py` 의
`test_not_implemented_is_a_runtime_error_subclass_so_order_the_handlers` 가
고정한다.

검사 순서는 인자 순서가 아니라 **유형 순서**다. ① 모든 인자의 유한성 →
② 도메인 → ③ 게이트. 그래서 인자 둘이 동시에 틀리면 먼저 나오는 오류는
"앞쪽 인자"가 아니라 "앞쪽 유형"이다(예: 금리 4.5 와 exit cap 4.5 를 함께
넣으면 금리 쪽 `ValueError` 가 먼저다).

이 순서의 예외가 하나 있다. `dscr_min` 은 **게이트를 도메인보다 먼저** 건다.
전역 제약이 "DSCR 0~5 밖은 RuntimeError"로 오류 유형을 못박고 있어서, 음수
DSCR 을 도메인 검사로 먼저 잡으면 유형이 어긋나기 때문이다. 게이트 안이면서도
계산이 안 되는 `dscr_min == 0`(요구 커버리지 없음 = 제약 무한대)만 그 뒤에서
`ValueError` 로 잡는다.
"""

from src.analysis.caprate import CAP_MAX, CAP_MIN
from src.analysis.fin_core import irr_annual, require_finite

# 물리 게이트(계획 Global Constraints): DSCR 0~5 밖은 RuntimeError.
# 차환(refi)도 같은 게이트를 써야 하므로 상수는 여기 한 곳에만 둔다.
DSCR_GATE_MIN = 0.0
DSCR_GATE_MAX = 5.0

# 결속 조건 이름과 동률 우선순위. `min` 은 최솟값이 여럿이면 **첫 번째**를
# 돌려주므로, 이 순서가 곧 동률 규칙(ltv > dscr > debt_yield)이다.
BINDING_PRIORITY = ("ltv", "dscr", "debt_yield")

_QUARTERS_PER_YEAR = 4


def _gate_dscr(dscr_min: float) -> None:
    """요구 DSCR 이 물리 범위(0~5) 안인지 확인한다. 밖이면 멈춘다.

    NaN 은 부르는 쪽이 먼저 `ValueError` 로 걸러 여기 오지 않는다.
    """
    if not DSCR_GATE_MIN <= dscr_min <= DSCR_GATE_MAX:
        raise RuntimeError(
            f"요구 DSCR {dscr_min:,.4f} 이 물리 범위"
            f"[{DSCR_GATE_MIN}, {DSCR_GATE_MAX}] 밖이다 — DSCR 이 아니라 "
            "단위(배수↔%)를 의심하라. 1.3 을 130 으로 넣으면 대출가능액이 "
            "100분의 1 이 되고, 음수면 제약이 뒤집혀 무한대가 된다"
        )


def _gate_exit_cap(cap: float) -> None:
    """매각 cap 이 물리 범위(0.02~0.12) 안인지 확인한다. 밖이면 멈춘다.

    범위 상수는 `caprate` 것을 그대로 쓴다(단일 출처). `value.appraise` 가
    감정가의 cap 에 거는 것과 같은 게이트다 — 매각가도 결국 NOI ÷ cap 이라
    cap 이 100배 어긋나면 매각가가 100분의 1 이 되고, 그 값이 IRR 로 흘러가
    정상 float 처럼 나온다.
    """
    if not CAP_MIN <= cap <= CAP_MAX:
        raise RuntimeError(
            f"매각 cap {cap:.6f}(= {cap * 100:.4f}%)이 물리 범위"
            f"[{CAP_MIN}, {CAP_MAX}] 밖이다 — cap 이 아니라 단위(%↔소수)를 "
            "의심하라. 4.5 를 넣으면 매각가가 100분의 1, 0.0045 를 넣으면 "
            "10배가 되고 둘 다 IRR 까지 조용히 흘러간다"
        )


def max_loan(
    noi_won_y: float,
    price_won: float,
    ltv_max: float,
    dscr_min: float,
    debt_yield_min: float,
    loan_rate: float,
    io: bool = True,
) -> dict:
    """삼중 제약(LTV·DSCR·Debt Yield) 중 가장 작은 대출가능액(원).

    | 제약        | 산식                    | 예(G-LOAN-001)               |
    |-------------|-------------------------|------------------------------|
    | ltv         | 가격 × LTV 한도         | 2,700억 × 0.55 = 1,485.0억   |
    | dscr        | (NOI ÷ DSCR) ÷ 금리     | (121.125/1.3)/0.045 = 2,070.51억 |
    | debt_yield  | NOI ÷ DY 하한           | 121.125/0.08 = 1,514.06억    |
    | **결과**    | min(셋)                 | **1,485.0억 · binding=ltv**  |

    `dscr` 제약이 나누기 두 번인 이유는 **IO 가정** 때문이다. 연 상환액이
    이자뿐(= 대출 × 금리)이므로 DSCR = NOI ÷ (대출 × 금리) ≥ 하한을 대출에
    대해 풀면 대출 ≤ (NOI ÷ 하한) ÷ 금리가 된다. 원리금균등이면 상환액이
    커져 이 값이 작아진다(그래서 `io=False` 는 `NotImplementedError` —
    규약 3). 그 예외는 `RuntimeError` 의 **하위형**이라 `except RuntimeError`
    에도 걸린다 — 잡는 순서는 모듈 docstring 을 볼 것.

    **binding 은 최솟값의 이름 하나다.** 동률이면 `ltv > dscr > debt_yield`
    순서로 앞선 하나만 고른다(`BINDING_PRIORITY`). 예컨대 NOI 0 이면
    `dscr`·`debt_yield` 가 둘 다 0 원이지만 binding 은 `dscr` 이다. 실무에서
    소수점까지 정확히 같은 동률은 드물지만, 규칙이 없으면 같은 입력에 다른
    이름이 나올 수 있어 순서를 못박는다.

    도메인: NOI ≥ 0 · 가격 > 0 · LTV 한도 ∈ (0, 1] · DY 하한 ∈ (0, 1] ·
    금리 ∈ (0, 1] · 요구 DSCR > 0. 밖이면 `ValueError`(NOI 0 은 허용 —
    소득이 없으면 소득 제약 두 개가 0 원을 돌려준다). 금리 0 을 막는 이유는
    무이자 대출에서 DSCR 제약이 무한대가 되어 삼중 제약이 이중 제약으로
    조용히 바뀌기 때문이다.

    게이트: 요구 DSCR 은 0~5(양끝 포함) 안이어야 한다. 밖이면 `RuntimeError`.

    반환: `{"loan_won", "binding", "by": {"ltv", "dscr", "debt_yield"},
    "assumptions": {...}}`. `by` 는 제약별 상한을 **전부** 실어 보낸다 —
    결속 조건만 보고 인용하면 "어디까지 여유가 있었는지"가 사라진다.
    """
    if not io:
        raise NotImplementedError(
            "원리금균등(io=False) 대출가능액은 상환 연수가 있어야 계산할 수 "
            "있는데 시그니처에 없다. 조용히 IO 로 처리하면 상환액을 이자로만 "
            "봐서 대출가능액이 과대(위험한 방향)로 나온다 — 계산하지 않는다"
        )

    require_finite(noi_won_y, "NOI")
    require_finite(price_won, "가격")
    require_finite(ltv_max, "LTV 한도")
    require_finite(dscr_min, "요구 DSCR")
    require_finite(debt_yield_min, "DY 하한")
    require_finite(loan_rate, "대출금리")

    if noi_won_y < 0:
        raise ValueError(f"NOI 는 음수일 수 없다: {noi_won_y}")
    if price_won <= 0:
        raise ValueError(f"가격은 양수여야 한다: {price_won}")
    if not 0 < ltv_max <= 1:
        raise ValueError(f"LTV 한도는 (0, 1] 인 소수여야 한다(55% = 0.55): {ltv_max}")
    if not 0 < debt_yield_min <= 1:
        raise ValueError(f"DY 하한은 (0, 1] 인 소수여야 한다(8% = 0.08): {debt_yield_min}")
    if not 0 < loan_rate <= 1:
        raise ValueError(
            f"대출금리는 (0, 1] 인 소수여야 한다(4.5% = 0.045): {loan_rate}. "
            "0(무이자)이면 DSCR 제약이 무한대가 되어 삼중 제약이 이중 제약으로 "
            "바뀐다"
        )

    _gate_dscr(dscr_min)
    if dscr_min <= 0:
        raise ValueError(
            f"요구 DSCR 은 양수여야 한다: {dscr_min}. 0 은 '커버리지를 요구하지 "
            "않는다'는 뜻이라 DSCR 제약이 무한대가 된다"
        )

    by = {
        "ltv": price_won * ltv_max,
        "dscr": (noi_won_y / dscr_min) / loan_rate,
        "debt_yield": noi_won_y / debt_yield_min,
    }
    # `min` 은 최솟값이 여럿이면 첫 번째를 돌려준다 — 순회 순서가 곧 동률
    # 우선순위다. 금액은 `by` 에서 다시 꺼내 binding 과 어긋날 수 없게 한다.
    binding = min(BINDING_PRIORITY, key=lambda name: by[name])
    loan_won = by[binding]

    interest_won_y = loan_won * loan_rate
    dscr_at_max_loan = noi_won_y / interest_won_y if interest_won_y > 0 else None

    return {
        "loan_won": loan_won,
        "binding": binding,
        "by": by,
        "assumptions": {
            "noi_won_y": noi_won_y,
            "price_won": price_won,
            "ltv_max": ltv_max,
            "dscr_min": dscr_min,
            "debt_yield_min": debt_yield_min,
            "loan_rate": loan_rate,
            "io": io,
            "ltv_at_max_loan": loan_won / price_won,
            "interest_won_y": interest_won_y,
            "dscr_at_max_loan": dscr_at_max_loan,
            "debt_yield_at_max_loan": (
                noi_won_y / loan_won if loan_won > 0 else None
            ),
            "notes": [
                "IO(이자만 상환) 가정이다 — DSCR 제약은 원리금이 아니라 "
                f"이자(대출 × 금리 {loan_rate})를 덮는다. 원리금균등이면 "
                "상환액이 커져 대출가능액이 이보다 작아진다.",
                f"결속 조건 {binding} — 셋 중 가장 작은 제약이다. 동률이면 "
                f"{' > '.join(BINDING_PRIORITY)} 순서로 하나를 고른다.",
                "세 제약의 상한을 `by` 에 모두 실었다. 결속 조건만 인용하면 "
                "나머지 두 제약까지 얼마나 여유가 있었는지가 사라진다.",
            ],
            "caveats": [
                "대출 조건(LTV 한도·요구 DSCR·DY 하한·금리)은 시장 관행 수준의 "
                "가정이며 실제 대주 심사 결과가 아니다. 넷 중 하나만 흔들려도 "
                "대출가능액이 두 자릿수 퍼센트로 움직인다.",
                "금리를 고정으로 봤다. 변동금리·금리 상한(cap) 비용·수수료·"
                "약정 수수료는 들어 있지 않다.",
                "선순위 한 트랜치만 본다 — 메자닌·후순위를 얹는 구조는 이 "
                "삼중 제약으로 설명되지 않는다.",
                "NOI 는 정상화 한 해의 값이다. 임대차 만기 구조·리스업 공백이 "
                "겹치는 해에는 실제 DSCR 이 이보다 낮아질 수 있다.",
            ],
        },
    }


def hold_model(
    price_won: float,
    loan_won: float,
    loan_rate: float,
    noi_won_y: float,
    noi_growth_y: float,
    exit_cap: float,
    hold_years: int = 5,
    cost_rate: float = 0.05,
) -> dict:
    """보유기간 분기 현금흐름과 지분 IRR.

    | 분기      | 산식                                        | 예(G-HOLD-001)  |
    |-----------|---------------------------------------------|-----------------|
    | q0        | −(가격 × (1+비용률) − 대출)                 | −500억          |
    | q1~q19    | (t년차 NOI − 대출×금리) ÷ 4                 | +5.75억         |
    | q20(마지막)| 위 + (매각가 − 대출)                        | +455.75억       |

    G-HOLD-001(가격 1,000억·대출 550억·금리 4%·NOI 45억·성장 0%·exit cap
    4.5%·5년·비용 5%)의 손계산: q0 = −(1,050 − 550) = −500억, 분기 순수익 =
    (45 − 22)/4 = 5.75억, 매각가 = 45/0.045 = 1,000억, 마지막 분기 = 5.75 +
    (1,000 − 550) = 455.75억. 이 21개 흐름의 분기 IRR 은 0.6816068036%,
    연율은 **2.7544293667%** 다(고정밀 뉴턴법·이분법 교차검증, 엑셀
    `=(1+IRR(A1:A21))^4-1` 과 대조 가능한 형태). 취득부대비용 50억을 매각가가
    회수하지 못해 수익률이 낮은 것이 맞다.

    매각가(`exit_value`)는 **보유 종료 다음 해** NOI 를 exit cap 으로 나눈
    값이다 = 기준 NOI × (1+g)^hold_years ÷ exit_cap. 마지막 분기에
    `exit_value − loan_won` 을 더한다(원금 상계가 매각에 내재한다).

    도메인: 가격 > 0 · 0 ≤ 대출 ≤ 가격 · 0 ≤ 금리 ≤ 1 · NOI ≥ 0 ·
    성장률 ∈ (−1, 1] · 보유 연수는 1 이상의 **정수** · 비용률 ∈ [0, 1).
    밖이면 `ValueError`. 대출 0(전액 자기자본)과 금리 0 은 허용한다 —
    `max_loan` 과 달리 여기서는 금리로 나누지 않는다.

    게이트: exit cap 은 0.02~0.12(양끝 포함) 안이어야 한다. 밖이면
    `RuntimeError`.

    반환: `{"cashflows_q", "equity_irr", "exit_value", "assumptions"}`.
    **`equity_irr` 은 `None` 일 수 있다** — 부호 변화가 없거나(대출이 취득
    총액과 같아 유출이 0) 근이 분기이율 [−0.5, 1.0] 밖이면 `fin_core` 가
    값을 지어내지 않고 `None` 을 준다. 부르는 쪽이 `None` 을 처리해야 한다.
    """
    require_finite(price_won, "가격")
    require_finite(loan_won, "대출")
    require_finite(loan_rate, "대출금리")
    require_finite(noi_won_y, "NOI")
    require_finite(noi_growth_y, "NOI 성장률")
    require_finite(exit_cap, "매각 cap")
    require_finite(cost_rate, "취득부대비용률")

    if price_won <= 0:
        raise ValueError(f"가격은 양수여야 한다: {price_won}")
    if loan_won < 0:
        raise ValueError(f"대출은 음수일 수 없다: {loan_won}")
    if loan_won > price_won:
        raise ValueError(
            f"대출 {loan_won:,.0f}원이 가격 {price_won:,.0f}원을 넘는다 — "
            "LTV 100% 초과 구조는 이 모델에 없다(취득부대비용은 자기자본이다)"
        )
    if not 0 <= loan_rate <= 1:
        raise ValueError(f"대출금리는 [0, 1] 인 소수여야 한다(4% = 0.04): {loan_rate}")
    if noi_won_y < 0:
        raise ValueError(f"NOI 는 음수일 수 없다: {noi_won_y}")
    if not -1 < noi_growth_y <= 1:
        raise ValueError(
            f"NOI 성장률은 (−1, 1] 인 소수여야 한다(2% = 0.02): {noi_growth_y}. "
            "−1 이하면 NOI 가 0 이하로 무너지고, 1 초과면 연 100% 넘는 성장이라 "
            "% 를 소수 자리에 넣은 오입력을 의심해야 한다"
        )
    if isinstance(hold_years, bool) or not isinstance(hold_years, int):
        # bool 은 int 의 하위형이라 True 가 '1년'으로 조용히 통과한다 — 보유
        # 기간 자리에 참/거짓이 들어왔다면 부르는 쪽 실수다.
        raise ValueError(
            f"보유 기간은 정수 연이어야 한다: {hold_years!r}. 분기 흐름을 연 "
            "단위 NOI 성장에 묶어 조립하므로 반년은 규약에 없다"
        )
    if hold_years < 1:
        raise ValueError(f"보유 기간은 1년 이상이어야 한다: {hold_years}")
    if not 0 <= cost_rate < 1:
        raise ValueError(
            f"취득부대비용률은 [0, 1) 인 소수여야 한다(5% = 0.05): {cost_rate}"
        )

    _gate_exit_cap(exit_cap)

    interest_won_y = loan_won * loan_rate
    acquisition_cost_won = price_won * cost_rate
    equity_won = price_won * (1 + cost_rate) - loan_won

    cashflows_q = [-equity_won]
    noi_by_year_won = []
    for t in range(hold_years):
        noi_t = noi_won_y * (1 + noi_growth_y) ** t
        noi_by_year_won.append(noi_t)
        quarterly = (noi_t - interest_won_y) / _QUARTERS_PER_YEAR
        cashflows_q.extend([quarterly] * _QUARTERS_PER_YEAR)

    exit_noi_won_y = noi_won_y * (1 + noi_growth_y) ** hold_years
    exit_value = exit_noi_won_y / exit_cap
    cashflows_q[-1] += exit_value - loan_won

    equity_irr = irr_annual(cashflows_q)

    return {
        "cashflows_q": cashflows_q,
        "equity_irr": equity_irr,
        "exit_value": exit_value,
        "assumptions": {
            "price_won": price_won,
            "loan_won": loan_won,
            "loan_rate": loan_rate,
            "noi_won_y": noi_won_y,
            "noi_growth_y": noi_growth_y,
            "exit_cap": exit_cap,
            "hold_years": hold_years,
            "cost_rate": cost_rate,
            "equity_won": equity_won,
            "acquisition_cost_won": acquisition_cost_won,
            "interest_won_y": interest_won_y,
            "ltv_at_entry": loan_won / price_won,
            "noi_by_year_won": noi_by_year_won,
            "exit_noi_won_y": exit_noi_won_y,
            "exit_value_won": exit_value,
            "cashflow_points": len(cashflows_q),   # q0 포함 = 4 × hold_years + 1
            "notes": [
                f"IO(이자만 상환) 가정이다 — 보유 중 원금을 갚지 않는다. 매 "
                f"분기 이자는 대출 {loan_won:,.0f}원 × 금리 {loan_rate} ÷ 4 로 "
                "일정하고, 원금은 매각 시점에 한 번에 상계된다(마지막 분기의 "
                "매각 순유입 = 매각가 − 대출).",
                f"q0 = −(가격 × (1 + 비용률 {cost_rate}) − 대출) = "
                f"−{equity_won:,.0f}원. 취득부대비용 {acquisition_cost_won:,.0f}원"
                "(취득세·중개·실사·자문)은 전액 자기자본으로 본다.",
                f"NOI 는 연 {noi_growth_y} 로 **연 단위 계단** 성장한다 — 한 해 "
                "안의 네 분기는 값이 같고 해가 바뀔 때만 오른다.",
                f"매각가 = 보유 종료 **다음 해** NOI {exit_noi_won_y:,.0f}원 ÷ "
                f"exit cap {exit_cap} = {exit_value:,.0f}원. 마지막 해 NOI 가 "
                "아니라 다음 해 NOI 다.",
                "현금흐름 원소는 분기이고 IRR 은 연율이다(fin_core 규약). "
                "equity_irr 은 부호 변화가 없거나 근이 탐색 범위 밖이면 None 이다.",
            ],
            "caveats": [
                "**매각비용을 반영하지 않았다** — 매각 중개·양도 관련 비용이 "
                "빠져 있어 IRR 이 그만큼 낙관적이다(취득 쪽 비용만 cost_rate 로 "
                "넣었다).",
                "법인세·취득세 이연효과·감가상각·CapEx·임대차 수수료(TI/LC)·"
                "보증금 운용수익이 전부 빠져 있다. 세전·CapEx 전 지분 IRR 이다.",
                "대출 만기와 차환을 모델에 넣지 않았다. 보유 기간 내내 같은 "
                "금리의 IO 대출이 유지된다고 본다 — 만기가 보유 기간보다 짧으면 "
                "차환 위험이 이 IRR 에 들어 있지 않다.",
                "exit cap 은 가정이다. 진입 cap 과 같게 두면 자본이득이 NOI "
                "성장만큼만 생기고, 벌리면(cap expansion) IRR 이 급격히 나빠진다 "
                "— 민감도를 함께 보지 않은 단일 IRR 은 인용하지 말 것.",
                "공실·임대료는 정상화 한 해의 NOI 에 성장률 하나로 뭉갰다. "
                "임차인 교체·리스업 공백의 시점 분포는 들어 있지 않다.",
            ],
        },
    }
