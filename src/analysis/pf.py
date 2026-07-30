"""개발 PF — 월별 인출·이자 스케줄과 스트레스 표.

땅을 사서 짓고, 채우고, 파는 한 사업의 돈이 **매달** 어디서 나와 어디로 가는지
펼친 뒤(`pf_model`), 그 사업이 어느 충격에서 먼저 깨지는지 같은 모델을 열다섯
번 다시 돌려 보여준다(`stress`).

    총사업비 = 기본비용(토지 + 공사 + 간접비) + 취급수수료 + 건설기간 이자
    대출원금 = 총사업비 − 자기자본 = (월별 인출 합) + (준공 시 자본화 이자)
    매각가   = 안정화 NOI ÷ exit cap
    개발이익 = 매각가 − 총사업비

금융 산식은 스스로 쓰지 않고 `fin_core.irr_annual` 을 부른다(그쪽 엔진이 이미
골든 검증을 마쳤다). 이 모듈이 책임지는 것은 **월별 스케줄이 규약대로
조립되고, 그것이 분기 흐름으로 정확히 접히는가**다.

전부 순수 함수다 — I/O 도 전역 상태도 없다. 임포트는 `math`(표준 라이브러리),
`fin_core.irr_annual`, `caprate` 의 cap 게이트 상수 둘뿐이다.

## 규약 넷

1. **금액은 원, 기간은 개월(정수), 이율·비율은 소수다.** 금리 6% 는 `0.06`,
   exit cap 5% 는 `0.05`, 간접비율 12% 는 `0.12`. NOI 는 원/년.
2. **입력은 dict 하나다.** 필수 여덟(`land_won`, `hard_cost_won`,
   `months_build`, `equity_won`, `loan_rate`, `stabilized_noi_won_y`,
   `lease_up_months`, `exit_cap`) + 선택 둘(`soft_cost_ratio` 기본 0.12,
   `fee_rate` 기본 0.015). **모르는 키는 조용히 무시하지 않고 거절한다** —
   `lease_up_month` 같은 오타가 기본값으로 흘러가면 12개월 공백이 그대로
   사라진다.
3. **`monthly` 는 사업 전체 개월 수만큼이다** = `months_build +
   lease_up_months`. 0-based `month` 로 건설기간이 앞, 임대기간이 뒤다.
4. **분기 흐름은 `fin_core` 규약을 따른다** — `cashflows_q[0]` 이 0분기(사업
   개시)이고 IRR 은 연율이다. 월→분기 접기는 아래 D7.

## 설계 결정 여덟(브리프가 열어 둔 자리 — 여기서 못박는다)

계획은 "토지비 m0·공사비 균등·단리·준공 시 자본화"까지만 정했다. 나머지는
이 모듈이 정한다. **결정마다 대안이 있었고, 대안을 골랐으면 값이 달라진다** —
그래서 `assumptions["decisions"]` 에 같은 문장을 실어 보낸다.

| #  | 결정                                          | 고르지 않은 대안(과 그 방향)     |
|----|-----------------------------------------------|---------------------------------|
| D1 | 토지비 전액 m0, (공사비+간접비) 공사기간 균등 | S자 곡선(이자가 작아진다)        |
| D2 | 수수료 = fee_rate × (기본비용 − 자기자본), m0 | 총대출 기준(순환 참조가 생긴다)  |
| D3 | 조달은 **자기자본 선투입**, 남은 만큼만 대출  | 매월 정률 분담(이자가 는다)      |
| D4 | 인출은 월초, 이자 = **인출 후** 잔액 × 금리/12| 인출 전 잔액(이자 3.35억 작다)   |
| D5 | 건설기간 이자는 **단리**, 준공 시 일시 자본화 | 월복리·이자유보계정(원금이 큰다) |
| D6 | 임대기간 NOI 는 k/L 선형, 마지막 임대월 말 매각| (k−1)/L·즉시 만실(수입이 앞선다)|
| D7 | 인출은 `q = m//3`, 영업·매각은 `q = m//3 + 1` | 월 중앙(IRR 이 조금 높아진다)    |
| D8 | LLCR 은 준공 시점의 (잔여 NOI + 매각가) ÷ 대출| 영구 NOI(배수가 부푼다)          |

D2 를 총대출 기준으로 잡으면 수수료가 이자를, 이자가 수수료를 참조한다. D4 를
인출 전 잔액으로 바꾸면 G-PF-001 의 건설기간 이자가 48.188억에서 44.8385억으로
3.3495억 작아진다(= 마지막 달 인출 23.3333억의 이자 한 달치가 통째로 빠진다).
D5 의 대안인 이자유보계정(IRA)은 이자를 대출로 다시 인출해 원금을 키운다.

D4·D7 은 둘 다 **보수적인 쪽**(이자를 크게, 유입을 늦게)이다. D8 에 매각가를
넣는 이유는 이 대출의 상환 재원이 임대수입이 아니라 매각대금이기 때문이다 —
lease-up 12개월치 NOI 만으로는 어떤 사업도 LLCR 1 을 넘길 수 없어 지표가
의미를 잃는다.

**단리는 '이자에 이자가 붙지 않는다'는 뜻이다.** 건설기간 24개월 동안 발생한
이자는 매달 쌓이기만 하고 인출잔액을 키우지 않으며, 준공 달에 한 번에 원금으로
얹힌다. 그렇게 커진 원금은 임대기간 이자의 밑이 되지만, 그 이자는 다시
자본화되지 않고 현금으로 나간다. `tests/test_pf.py::
test_interest_is_simple_not_compounded` 가 월복리와의 차이로 이 규약을 고정한다.

## G-PF-001 월별 인출·이자 스케줄(손계산 — 이 모듈의 골든)

토지 300억 · 공사 500억 · 간접비 12%(60억) · 24개월 · 자기자본 200억 ·
금리 6% · 수수료 1.5% · NOI 60억/년 · lease-up 12개월 · exit cap 5%.

월 (공사 + 간접) = 560억 ÷ 24 = 70/3 = 23.3333…억,
수수료 = 0.015 × (860 − 200)억 = **9.9억**(m0).

단위는 억원(1억 = 1e8원), 이자는 인출 후 잔액 × 0.5%(= 6%/12).

| m  | 그 달 비용            | 자기자본 | 대출인출  | 인출 후 잔액 | 그 달 이자 |
|----|-----------------------|----------|-----------|--------------|------------|
| 0  | 300 + 70/3 + 9.9      | 200      | 133.2333… | 133.2333…    | 0.6661666… |
|    | = 333.2333…           |          |           |              |            |
| 1  | 23.3333…              | 0        | 23.3333…  | 156.5666…    | 0.7828333… |
| 2  | 23.3333…              | 0        | 23.3333…  | 179.9        | 0.8995     |
| …  | …                     | 0        | …         | …            | …          |
| 23 | 23.3333…              | 0        | 23.3333…  | 669.9        | 3.3495     |

잔액이 등차수열이라 닫힌형으로 접힌다(억 단위).

    B_m = (3997 + 700m)/30,   Σ_{m=0}^{23} B_m = (24×3997 + 700×276)/30
        = 289,128/30 = 9,637.6억·월
    건설기간 이자 = 9,637.6 × 0.005 = **48.188억**

| 항목         | 산식                              | 확정값                       |
|--------------|-----------------------------------|------------------------------|
| interest_won | 위 스케줄 합                      | 4,818,800,000원              |
| fee_won      | 0.015 × 660억                     | 990,000,000원                |
| total_cost   | 860 + 9.9 + 48.188억              | 91,808,800,000원             |
| loan_won     | 총사업비 − 200억 = 669.9 + 48.188 | 71,808,800,000원             |
| **ltc**      | 89,761/114,761                    | **0.782155958905900088009…** |
| exit_value   | 60억 ÷ 0.05                       | 120,000,000,000원            |
| **profit**   | 1,200 − 918.088억                 | **28,191,200,000원**         |
| margin       | 35,239/114,761                    | 0.307064246564599471946…     |
| **equity_irr**| 분기 13개 → (1+x)^4 − 1          | **0.3281989683422813656119…**|
| llcr         | (PV잔여NOI + PV매각) ÷ 718.088억  | 1.617443305735589418586…     |

llcr 의 분자 두 조각(준공 시점, 월이율 0.5% 할인 — 1.005^12 =
1.061677811864499568789707…): PV(잔여 NOI) = 3,118,022,092.9956394915…원,
PV(매각) = 113,028,640,759.910153949…원.

지분 분기 흐름 13개(월 현금이자 = 718.088억 × 0.005 = 3.59044억):
q0 = −200억, q1~q8 = 0, q9 = −8.27132억, q10 = −4.52132억, q11 = −0.77132억,
q12 = +484.89068억(= 13.75 − 10.77132 + (1,200 − 718.088)). 이 흐름의 분기이율
x = 0.073533953206652267660378469816… 을 `Decimal` 60자리 뉴턴법으로 풀고
같은 정밀도 이분법으로 교차검증했다(차 1.7e−60). 유도 전문은
`tests/test_pf.py` 모듈 docstring 에 있다.

## 두 지표의 범위가 다르다 — `profit` 과 `equity_irr`

`profit` 은 **매각가 − 총사업비**다(계획이 정한 정의). 임대기간의 순영업현금
(임대수입 − 대출이자)은 여기 들어 있지 않다. 반대로 `equity_irr` 은 그 흐름을
전부 싣는다. G-PF-001 에서 임대기간 순현금은 32.5 − 43.085 = **−10.585억**이라,
개발이익 281.912억과 지분수익률 32.82% 를 같은 문장에서 인용하면 그 −10.585억이
소리 없이 사라진다. 둘은 다른 질문의 답이다.

## 오류 유형 둘

- `ValueError` — 값이 물리적으로 말이 안 되거나 입력 형태가 틀렸다(음수 비용,
  NaN·inf, 필수 키 누락, 모르는 키, 개월이 정수가 아님 등). NaN 은 크기 비교가
  전부 False 라 도메인 검사와 게이트를 조용히 통과하므로 **가장 먼저** 유한성을
  확인한다.
- `RuntimeError` — 값 자체는 말이 되는데 단위·자릿수를 의심해야 한다. 물리
  게이트 둘이다: exit cap 0.02~0.12(`caprate` 상수를 임포트해 쓴다 — 여기 다시
  적으면 두 모듈이 따로 움직인다)와 **LTC 0~1**. LTC 가 1 을 넘으면 자기자본이
  음수이고, 0 을 밑돌면 자기자본이 총사업비를 넘는다 — 둘 다 억↔원 자릿수
  오입력에서 나온다.

검사 순서는 인자 순서가 아니라 **유형 순서**다. ① 키 → ② 유한성 → ③ 도메인 →
④ cap 게이트 → (계산) → ⑤ LTC 게이트.

**스트레스는 게이트를 만나면 멈춘다.** `stress` 는 열다섯 시나리오를 차례로
돌리는데, 어느 하나가 물리 게이트 밖으로 나가면(예: exit cap 11.5% 에 +1.0%p)
그 행만 조용히 빼지 않고 예외를 그대로 올린다. 빠진 행은 표에서 보이지 않고,
보이지 않는 행은 "그 시나리오는 괜찮았다"로 읽힌다.
"""

import math

from src.analysis.caprate import CAP_MAX, CAP_MIN
from src.analysis.fin_core import irr_annual

# 물리 게이트(계획 Global Constraints 의 자릿수 방어). 대출/총사업비는
# 정의상 0~1 이다 — 밖이면 금액 단위를 의심해야 한다.
LTC_MIN = 0.0
LTC_MAX = 1.0

MONTHS_PER_YEAR = 12
MONTHS_PER_QUARTER = 3

# 입력 계약(규약 2). 선택 키의 기본값은 계획이 정한 값이다.
REQUIRED_KEYS = (
    "land_won",
    "hard_cost_won",
    "months_build",
    "equity_won",
    "loan_rate",
    "stabilized_noi_won_y",
    "lease_up_months",
    "exit_cap",
)
OPTIONAL_DEFAULTS = {"soft_cost_ratio": 0.12, "fee_rate": 0.015}

# 자기자본 비율 제도 단계(계획: 5% → 20%). `stress` 가 이 순서로 사다리를 만든다.
EQUITY_SHARE_LADDER = (0.05, 0.10, 0.15, 0.20)

# 자기자본 비율 고정점 탐색(비율은 '그 시나리오 자신의' 총사업비 대비다).
_EQUITY_FIXED_POINT_TOL_WON = 1.0
_EQUITY_FIXED_POINT_MAX_ITER = 64

_DECISIONS = (
    "D1 토지비는 전액 첫 달, 공사비와 간접비는 공사기간에 균등 분산한다"
    "(S자 곡선 분산이 아니다).",
    "D2 대출 취급수수료 = fee_rate × (기본비용 − 자기자본)이고 첫 달에 대출로 "
    "인출한다(총대출 기준으로 잡으면 수수료와 이자가 서로를 참조한다).",
    "D3 조달 순서는 자기자본 선투입이다 — 매월 소요액을 자기자본으로 먼저 채우고 "
    "남은 만큼만 대출을 인출한다(매월 정률 분담이 아니다).",
    "D4 인출은 월초이고, 그 달 이자는 인출 후 잔액 × 금리/12 다(인출 전 잔액 "
    "기준보다 이자가 크게 잡히는 보수적인 쪽).",
    "D5 건설기간 이자는 단리로 쌓아 준공 시 일시 자본화하고(이자에 이자가 붙지 "
    "않는다), 임대기간 이자는 자본화하지 않고 현금으로 지급한다.",
    "D6 임대기간 NOI 는 안정화 월NOI × k/L 로 선형 ramp-up 하고, 마지막 임대월 "
    "말에 안정화 NOI ÷ exit cap 으로 매각한다.",
    "D7 월 흐름을 분기로 접을 때 자기자본 인출은 월초라 q = m//3 에, 영업현금과 "
    "매각대금은 월말이라 q = m//3 + 1 에 넣는다.",
    "D8 LLCR 은 준공 시점 기준으로 잔여 NOI 와 매각대금을 월이율(금리/12)로 "
    "할인한 현재가치를 대출원금으로 나눈 값이다(영구 NOI 가 아니다).",
)


def _require_finite(x: float, what: str) -> None:
    """NaN·무한대를 입력 오류로 잡는다. 자기 자신과 다른 값은 NaN 뿐이다.

    NaN 은 크기 비교가 전부 False 라 도메인 검사(`0 <= x <= 1` 따위)를 조용히
    통과하고, 게이트에는 "범위 밖"으로 걸려 오류 유형까지 뒤바꾼다. inf 는
    비용·NOI 처럼 상한이 없는 인자에서 그대로 지나가 총사업비·IRR 을 inf/NaN
    으로 만든다. 둘 다 정상 float 처럼 생겨서 하류가 잡지 못한다.
    """
    if x != x:
        raise ValueError(f"{what} 값이 NaN 이다 — 검사를 조용히 통과하므로 막는다")
    if math.isinf(x):
        raise ValueError(f"{what} 값이 무한대다 — 검사를 조용히 통과하므로 막는다")


def _require_months(x, what: str, minimum: int) -> int:
    """개월 수가 정수인지 확인한다. bool 은 int 의 하위형이라 따로 막는다.

    `True` 를 그대로 두면 '1개월 공사'로 조용히 통과하고, 24.0 을 허용하면
    `range()` 에서 TypeError 가 나거나 소수 개월이 규약에 없는 채로 흘러간다.
    """
    if isinstance(x, bool) or not isinstance(x, int):
        raise ValueError(
            f"{what} 는 정수 개월이어야 한다: {x!r}. 월별로 전개하는 모델이라 "
            "반달과 참/거짓은 규약에 없다"
        )
    if x < minimum:
        raise ValueError(f"{what} 는 {minimum} 이상이어야 한다: {x}")
    return x


def _gate_exit_cap(cap: float) -> None:
    """매각 cap 이 물리 범위(0.02~0.12) 안인지 확인한다. 밖이면 멈춘다.

    범위 상수는 `caprate` 것을 그대로 쓴다(단일 출처). 매각가 = NOI ÷ cap 이라
    cap 이 100배 어긋나면 매각가가 100분의 1 이 되고, 그 값이 개발이익과 IRR 로
    흘러가 정상 float 처럼 나온다.
    """
    if not CAP_MIN <= cap <= CAP_MAX:
        raise RuntimeError(
            f"매각 cap {cap:.6f}(= {cap * 100:.4f}%)이 물리 범위"
            f"[{CAP_MIN}, {CAP_MAX}] 밖이다 — cap 이 아니라 단위(%↔소수)를 "
            "의심하라. 5 를 넣으면 매각가가 100분의 1, 0.0005 를 넣으면 100배가 "
            "되고 둘 다 개발이익까지 조용히 흘러간다"
        )


def _gate_ltc(ltc: float, loan_won: float, total_cost: float,
              equity_won: float) -> None:
    """LTC(대출 ÷ 총사업비)가 0~1 안인지 확인한다. 밖이면 멈춘다.

    1 초과는 자기자본이 음수라는 뜻이고, 0 미만은 자기자본이 총사업비를 넘어
    대출이 음수라는 뜻이다. 둘 다 자기자본을 억 단위로 넣는(200 vs 200억)
    전형적인 자릿수 오입력에서 나온다.
    """
    if not LTC_MIN <= ltc <= LTC_MAX:
        raise RuntimeError(
            f"LTC {ltc:,.6f}(대출 {loan_won:,.0f}원 ÷ 총사업비 "
            f"{total_cost:,.0f}원)이 물리 범위[{LTC_MIN}, {LTC_MAX}] 밖이다 — "
            f"자기자본 {equity_won:,.0f}원의 단위(억↔원)를 의심하라. 총사업비를 "
            "넘는 자기자본은 대출을 음수로, 음수 자기자본은 LTC 를 1 초과로 만든다"
        )


def _read_inputs(inputs) -> dict:
    """입력 dict 를 검증해 기본값이 채워진 사본을 돌려준다(원본은 건드리지 않는다).

    ① 키(누락·오타) → ② 유한성 → ③ 도메인 순서다. 게이트는 부르는 쪽이 건다.
    """
    try:
        given = dict(inputs)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"입력은 키가 있는 매핑이어야 한다: {type(inputs).__name__}"
        ) from exc

    missing = [k for k in REQUIRED_KEYS if k not in given]
    if missing:
        raise ValueError(f"필수 입력이 없다: {', '.join(missing)}")
    known = set(REQUIRED_KEYS) | set(OPTIONAL_DEFAULTS)
    unknown = [k for k in given if k not in known]
    if unknown:
        raise ValueError(
            f"모르는 입력 키다: {', '.join(sorted(unknown))}. 오타를 조용히 "
            "무시하면 기본값이 대신 쓰여 가정이 바뀐 줄 모른다"
        )

    p = dict(OPTIONAL_DEFAULTS)
    p.update(given)

    p["months_build"] = _require_months(p["months_build"], "공사기간", 1)
    p["lease_up_months"] = _require_months(p["lease_up_months"], "임대안정화기간", 0)

    for key, what in (
        ("land_won", "토지비"),
        ("hard_cost_won", "공사비"),
        ("soft_cost_ratio", "간접비율"),
        ("equity_won", "자기자본"),
        ("loan_rate", "대출금리"),
        ("fee_rate", "취급수수료율"),
        ("stabilized_noi_won_y", "안정화 NOI"),
        ("exit_cap", "매각 cap"),
    ):
        raw = p[key]
        # 수치가 아닌 값은 `float()` 에 맡기지 않고 여기서 막는다. None(JSON 의
        # null)은 TypeError 를 내 유형 규약(입력 오류 = ValueError)을 깨고,
        # 문자열 "30000000000" 은 조용히 통과해 오입력이 그대로 계산에 들어간다.
        # bool 은 int 의 하위형이라 True 가 1원으로 통과한다.
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{what} 는 수치여야 한다: {raw!r}")
        value = float(raw)
        _require_finite(value, what)
        p[key] = value

    if p["land_won"] < 0:
        raise ValueError(f"토지비는 음수일 수 없다: {p['land_won']}")
    if p["hard_cost_won"] <= 0:
        raise ValueError(f"공사비는 양수여야 한다: {p['hard_cost_won']}")
    if not 0 <= p["soft_cost_ratio"] <= 1:
        raise ValueError(
            f"간접비율은 [0, 1] 인 소수여야 한다(12% = 0.12): {p['soft_cost_ratio']}"
        )
    if p["equity_won"] < 0:
        raise ValueError(f"자기자본은 음수일 수 없다: {p['equity_won']}")
    if not 0 <= p["loan_rate"] <= 1:
        raise ValueError(f"대출금리는 [0, 1] 인 소수여야 한다(6% = 0.06): {p['loan_rate']}")
    if not 0 <= p["fee_rate"] < 1:
        raise ValueError(
            f"취급수수료율은 [0, 1) 인 소수여야 한다(1.5% = 0.015): {p['fee_rate']}"
        )
    if p["stabilized_noi_won_y"] < 0:
        raise ValueError(f"안정화 NOI 는 음수일 수 없다: {p['stabilized_noi_won_y']}")

    return p


def _monthly_schedule(p: dict) -> dict:
    """월별 인출·이자·NOI 를 전개한다(D1~D6). 매각은 마지막 달에 얹는다."""
    land = p["land_won"]
    hard = p["hard_cost_won"]
    soft = hard * p["soft_cost_ratio"]
    base_cost = land + hard + soft
    equity_won = p["equity_won"]
    rate_m = p["loan_rate"] / MONTHS_PER_YEAR
    months_build = p["months_build"]
    lease_up_months = p["lease_up_months"]

    # D2 — 수수료는 기본비용에서 자기자본을 뺀 '약정 원금' 기준이다. 총대출
    # (= 수수료·이자를 포함한 값) 기준으로 잡으면 수수료가 자기 자신을 참조한다.
    # 자기자본이 기본비용을 넘으면 빌릴 것이 없어 0 이다(LTC 게이트가 뒤에서 잡는다).
    fee_won = p["fee_rate"] * max(0.0, base_cost - equity_won)
    build_cost_per_month = (hard + soft) / months_build

    rows: list[dict] = []
    equity_left = equity_won
    balance = 0.0            # 인출잔액(자본화 전)
    interest_construction = 0.0

    for m in range(months_build):
        cost = build_cost_per_month + (land + fee_won if m == 0 else 0.0)
        equity_draw = min(equity_left, cost)      # D3 자기자본 선투입
        equity_left -= equity_draw
        loan_draw = cost - equity_draw
        balance += loan_draw                      # D4 인출은 월초
        interest_m = balance * rate_m             # D4 이자는 인출 후 잔액에
        interest_construction += interest_m       # D5 단리 — 잔액을 키우지 않는다
        rows.append({
            "month": m,
            "phase": "construction",
            "cost_won": cost,
            "equity_draw_won": equity_draw,
            "loan_draw_won": loan_draw,
            "capitalization_won": 0.0,
            "loan_balance_won": balance,
            "interest_won": interest_m,
            "interest_capitalized": True,
            "noi_won": 0.0,
            "operating_cash_won": 0.0,
            "exit_cash_won": 0.0,
        })

    # D5 — 준공 달 말에 건설기간 이자를 한 번에 원금으로 얹는다. 그 달 이자는
    # 자본화 **전** 잔액에서 이미 계산됐다(자본화가 자기 이자를 낳지 않는다).
    loan_principal = balance + interest_construction
    rows[-1]["capitalization_won"] = interest_construction
    rows[-1]["loan_balance_won"] = loan_principal

    noi_month_stabilized = p["stabilized_noi_won_y"] / MONTHS_PER_YEAR
    interest_month = loan_principal * rate_m
    lease_up_noi: list[float] = []
    for k in range(1, lease_up_months + 1):
        noi = noi_month_stabilized * k / lease_up_months     # D6 선형 ramp-up
        lease_up_noi.append(noi)
        rows.append({
            "month": months_build + k - 1,
            "phase": "lease_up",
            "cost_won": 0.0,
            "equity_draw_won": 0.0,
            "loan_draw_won": 0.0,
            "capitalization_won": 0.0,
            "loan_balance_won": loan_principal,
            "interest_won": interest_month,
            "interest_capitalized": False,       # D5 임대기간 이자는 현금 지급
            "noi_won": noi,
            "operating_cash_won": noi - interest_month,
            "exit_cash_won": 0.0,
        })

    return {
        "rows": rows,
        "base_cost": base_cost,
        "fee_won": fee_won,
        "interest_construction": interest_construction,
        "drawn_won": balance,
        "loan_principal": loan_principal,
        "lease_up_noi": lease_up_noi,
        "build_cost_per_month": build_cost_per_month,
        "soft_cost_won": soft,
        "interest_month_lease_up": interest_month,
    }


def _fold_to_quarters(rows: list[dict]) -> list[float]:
    """월 흐름을 분기로 접는다(D7). 반환은 `fin_core` 규약의 분기 배열이다.

    자기자본 인출은 **월초**라 그 달이 속한 분기의 시작(`q = m//3`)에, 영업현금과
    매각대금은 **월말**이라 그 분기의 끝(`q = m//3 + 1`)에 놓는다. 유출은 앞으로,
    유입은 뒤로 — 둘 다 IRR 을 낮추는 보수적인 방향이다.
    """
    n_quarters = (len(rows) - 1) // MONTHS_PER_QUARTER + 2
    cashflows_q = [0.0] * n_quarters
    for row in rows:
        q = row["month"] // MONTHS_PER_QUARTER
        cashflows_q[q] -= row["equity_draw_won"]
        cashflows_q[q + 1] += row["operating_cash_won"] + row["exit_cash_won"]
    return cashflows_q


def pf_model(inputs: dict) -> dict:
    """개발 사업의 월별 현금흐름·총사업비·지분수익률.

    | 항목        | 산식                                        | G-PF-001         |
    |-------------|---------------------------------------------|------------------|
    | 기본비용    | 토지 + 공사 + 공사×간접비율                 | 860억            |
    | fee_won     | fee_rate × (기본비용 − 자기자본)            | 9.9억            |
    | interest_won| Σ(월 인출잔액) × 금리/12 (단리·건설기간)    | 48.188억         |
    | total_cost  | 기본비용 + fee + interest                   | 918.088억        |
    | loan_won    | total_cost − 자기자본                       | 718.088억        |
    | ltc         | loan_won ÷ total_cost                       | 0.7821559589…    |
    | exit_value  | 안정화 NOI ÷ exit cap                       | 1,200억          |
    | profit      | exit_value − total_cost                     | 281.912억        |
    | margin      | profit ÷ total_cost                         | 0.3070642466…    |
    | equity_irr  | 분기 13개 → `fin_core.irr_annual`           | 0.3281989683…    |
    | llcr        | (잔여 NOI + 매각가)의 준공시점 현재가치 ÷ 대출 | 1.6174433058…  |

    월별 인출·이자 스케줄과 이 값들의 손계산 유도는 **모듈 docstring** 에 있다.
    가정 여덟(D1~D8)도 그쪽이 원본이고, 반환에는 `assumptions["decisions"]` 로
    같은 문장이 실린다.

    도메인: 토지비 ≥ 0 · 공사비 > 0 · 간접비율 ∈ [0, 1] · 공사기간 ≥ 1(정수) ·
    자기자본 ≥ 0 · 금리 ∈ [0, 1] · 수수료율 ∈ [0, 1) · NOI ≥ 0 ·
    임대안정화기간 ≥ 0(정수). 밖이거나 NaN·inf 면 `ValueError`. 필수 키가 없거나
    모르는 키가 있어도 `ValueError` 다.

    게이트: exit cap 0.02~0.12, LTC 0~1(양끝 포함). 밖이면 `RuntimeError`.

    반환: `{"total_cost", "loan_won", "ltc", "interest_won", "fee_won",
    "exit_value", "profit", "margin", "llcr", "equity_irr", "cashflows_q",
    "monthly", "assumptions"}`.

    **`equity_irr` 은 `None` 일 수 있다** — 자기자본이 0 이면 유출이 없어
    부호 변화가 생기지 않고, 근이 분기이율 [−0.5, 1.0] 밖이면 `fin_core` 가 값을
    지어내지 않고 `None` 을 준다. **`llcr` 도 대출이 0 이면 `None` 이다**(나눌
    분모가 없다). 부르는 쪽이 `None` 을 처리해야 한다.

    `monthly` 원소는 `{"month"(0-based), "phase"("construction"|"lease_up"),
    "cost_won", "equity_draw_won", "loan_draw_won", "capitalization_won",
    "loan_balance_won", "interest_won", "interest_capitalized"(bool),
    "noi_won", "operating_cash_won", "exit_cash_won"}` 이다. 준공 달의
    `loan_balance_won` 은 자본화까지 반영한 값이고(그 달 `interest_won` 은
    자본화 전 잔액에서 나왔다), `capitalization_won` 이 그때 얹힌 금액이다.
    """
    p = _read_inputs(inputs)
    _gate_exit_cap(p["exit_cap"])

    s = _monthly_schedule(p)
    rows = s["rows"]

    total_cost = s["base_cost"] + s["fee_won"] + s["interest_construction"]
    loan_won = total_cost - p["equity_won"]
    ltc = loan_won / total_cost
    _gate_ltc(ltc, loan_won, total_cost, p["equity_won"])

    exit_value = p["stabilized_noi_won_y"] / p["exit_cap"]
    rows[-1]["exit_cash_won"] = exit_value - s["loan_principal"]

    profit = exit_value - total_cost
    margin = profit / total_cost

    cashflows_q = _fold_to_quarters(rows)
    equity_irr = irr_annual(cashflows_q)

    # D8 — 준공 시점에서 본 상환 재원의 현재가치. 할인은 월이율(금리/12)이다.
    rate_m = p["loan_rate"] / MONTHS_PER_YEAR
    pv_noi = sum(noi / (1 + rate_m) ** k
                 for k, noi in enumerate(s["lease_up_noi"], start=1))
    pv_exit = exit_value / (1 + rate_m) ** p["lease_up_months"]
    llcr = (pv_noi + pv_exit) / loan_won if loan_won > 0 else None

    return {
        "total_cost": total_cost,
        "loan_won": loan_won,
        "ltc": ltc,
        "interest_won": s["interest_construction"],
        "fee_won": s["fee_won"],
        "exit_value": exit_value,
        "profit": profit,
        "margin": margin,
        "llcr": llcr,
        "equity_irr": equity_irr,
        "cashflows_q": cashflows_q,
        "monthly": rows,
        "assumptions": {
            "land_won": p["land_won"],
            "hard_cost_won": p["hard_cost_won"],
            "soft_cost_ratio": p["soft_cost_ratio"],
            "soft_cost_won": s["soft_cost_won"],
            "months_build": p["months_build"],
            "equity_won": p["equity_won"],
            "loan_rate": p["loan_rate"],
            "fee_rate": p["fee_rate"],
            "stabilized_noi_won_y": p["stabilized_noi_won_y"],
            "lease_up_months": p["lease_up_months"],
            "exit_cap": p["exit_cap"],
            "base_cost_won": s["base_cost"],
            "build_cost_per_month_won": s["build_cost_per_month"],
            "drawn_won": s["drawn_won"],
            "loan_principal_won": s["loan_principal"],
            "interest_month_lease_up_won": s["interest_month_lease_up"],
            "lease_up_noi_won": sum(s["lease_up_noi"]),
            "lease_up_operating_cash_won": sum(
                row["operating_cash_won"] for row in rows),
            "pv_lease_up_noi_won": pv_noi,
            "pv_exit_won": pv_exit,
            "months_total": len(rows),
            "cashflow_points": len(cashflows_q),
            "decisions": list(_DECISIONS),
            "notes": [
                f"총사업비 {total_cost:,.0f}원 = 기본비용 {s['base_cost']:,.0f}원 "
                f"+ 취급수수료 {s['fee_won']:,.0f}원 + 건설기간 이자 "
                f"{s['interest_construction']:,.0f}원. 대출원금은 이 값에서 "
                f"자기자본 {p['equity_won']:,.0f}원을 뺀 {loan_won:,.0f}원이고, "
                f"월별 인출 합 {s['drawn_won']:,.0f}원 + 자본화 이자와 같다.",
                "건설기간 이자는 단리다 — 이자에 이자가 붙지 않고, 준공 달에 한 "
                "번에 원금으로 얹힌다(D5). 임대기간 이자는 자본화하지 않고 현금으로 "
                f"나간다(월 {s['interest_month_lease_up']:,.0f}원).",
                f"매각가 {exit_value:,.0f}원 = 안정화 NOI "
                f"{p['stabilized_noi_won_y']:,.0f}원 ÷ exit cap {p['exit_cap']}. "
                "임대기간 마지막 달 말에 판다고 본다(D6).",
                "profit 은 매각가 − 총사업비다. 임대기간 순영업현금 "
                f"{sum(row['operating_cash_won'] for row in rows):,.0f}원은 여기 "
                "들어 있지 않고 equity_irr 에만 실린다 — 두 지표의 범위가 다르다.",
                "현금흐름 원소는 분기이고 IRR 은 연율이다(fin_core 규약). "
                "인출은 분기 시작, 영업·매각은 분기 끝에 놓는다(D7).",
                "LLCR 은 준공 시점에서 본 (잔여 NOI + 매각대금) ÷ 대출원금이다"
                "(D8). 이 대출의 상환 재원은 임대수입이 아니라 매각대금이라 "
                "매각가를 분자에 넣는다 — 빼면 어떤 사업도 1 을 넘지 못한다.",
            ],
            "caveats": [
                "**분양(선분양 수입)이 없는 임대형 개발 모델이다.** 준공 전 "
                "수입이 한 푼도 없다고 보므로, 분양대금으로 공사비를 충당하는 "
                "사업에는 그대로 쓸 수 없다.",
                "공사비 지출 곡선을 균등으로 뭉갰다(D1). 실제 기성은 S자에 "
                "가까워 초기 인출이 적고, 그만큼 건설기간 이자가 이보다 작다.",
                "이자를 단리로, 그것도 준공 시 한 번에 자본화한다(D5). 실제 PF "
                "대출은 월복리에 이자유보계정(IRA)을 세우는 경우가 많아 원금이 "
                "이보다 커진다 — 이 모델의 이자는 낙관 쪽이다.",
                "취득세·보존등기·분담금·예비비·임대차 수수료(TI/LC)·CapEx·"
                "법인세가 전부 빠져 있다. 간접비율 하나로 뭉갠 값이다.",
                "매각비용(중개·양도 관련)을 반영하지 않았다 — 개발이익과 지분 "
                "IRR 이 그만큼 낙관적이다.",
                "임대기간 순현금이 음수인 달을 자기자본이 메운다고 본다(별도 "
                "이자유보계정을 세우지 않는다). 실제 구조에서는 그 몫이 대출로 "
                "들어와 원금이 커진다.",
                "exit cap 과 안정화 NOI 는 가정이다. 매각가 = NOI ÷ cap 이라 cap "
                "0.5%p 가 매각가를 10% 안팎으로 움직인다 — 단일 시나리오의 "
                "profit·IRR 은 stress() 표와 함께가 아니면 인용하지 말 것.",
                "대출 만기·기표 조건·중도상환 수수료·변동금리를 모델에 넣지 "
                "않았다. 금리는 사업 기간 내내 고정이다.",
            ],
        },
    }


def _equity_for_share(inputs: dict, share: float, seed_total_cost: float) -> dict:
    """자기자본을 '그 시나리오 자신의' 총사업비 대비 `share` 로 맞춘 실행 결과.

    자기자본을 줄이면 대출 인출이 늘어 건설기간 이자가 늘고, 그러면 총사업비가
    늘어 자기자본 목표액도 움직인다 — 순환이라 고정점으로 푼다. 기울기가
    `share × d(총사업비)/d(자기자본)` ≈ 0.01 수준의 축약사상이라 몇 번이면
    1원 이내로 붙는다. 붙지 않으면 값을 지어내지 않고 `RuntimeError` 다.

    기준 총사업비 대비로 한 번만 계산하지 않는 이유는, "자기자본비율 20%" 라는
    제도 요건이 **그 사업의** 총사업비 대비이기 때문이다. 고정점에서 LTC 는
    정확히 1 − share 가 된다.
    """
    total_cost = seed_total_cost
    for _ in range(_EQUITY_FIXED_POINT_MAX_ITER):
        equity_won = share * total_cost
        result = pf_model({**inputs, "equity_won": equity_won})
        if abs(equity_won - share * result["total_cost"]) < _EQUITY_FIXED_POINT_TOL_WON:
            return result
        total_cost = result["total_cost"]
    raise RuntimeError(
        f"자기자본 비율 {share:.0%} 고정점이 {_EQUITY_FIXED_POINT_MAX_ITER}회 "
        "안에 수렴하지 않았다 — 입력의 자릿수를 의심하라"
    )


def stress(base_inputs: dict) -> list[dict]:
    """같은 모델을 열다섯 번 다시 돌린 스트레스 표.

    | 묶음      | 시나리오                          | 바꾸는 입력               |
    |-----------|-----------------------------------|---------------------------|
    | 공사비    | +5% · +10%                        | hard_cost_won × 1.05/1.10 |
    | 준공지연  | +6개월 · +12개월                  | months_build + 6/12       |
    | 금리      | +1%p · +2%p                       | loan_rate + 0.01/0.02     |
    | 임대      | 임대개시 +6개월                   | lease_up_months + 6       |
    | 임대      | 안정화 NOI −10%                   | 안정화 NOI × 0.9          |
    | 매각      | exit cap +0.5%p · +1.0%p          | exit_cap + 0.005/0.01     |
    | 매각      | 매각가 −10%                       | exit_cap ÷ 0.9            |
    | 제도      | 자기자본 5% · 10% · 15% · 20%     | equity = 비율 × 총사업비  |

    각 행은 `{"name", "shock", "delta", "equity_irr", "ltc", "llcr"}` 다.
    `delta` 는 **기준 대비 지분 IRR 의 차이**(연율 소수, 예 −0.05 = −5%p)이고,
    어느 한쪽이 `None` 이면 `None` 이다. `shock` 은 무엇을 어떻게 바꿨는지 적은
    한 줄이다 — 이름만 보고 인용하면 "임대개시 +6개월"이 lease-up 기간 연장인지
    공백 6개월인지 알 수 없다.

    세 시나리오는 해석을 못박아 둔다.

    - **준공지연**은 같은 공사비를 더 긴 기간에 균등 분산하는 것으로 본다
      (기간 연장에 따른 추가 공사비는 "공사비 +x%" 가 따로 다룬다). 인출이
      길어져 건설기간 이자가 늘고 매각도 그만큼 늦어진다.
    - **임대개시 +6개월**은 안정화 도달이 6개월 늦어지는 것(`lease_up_months`
      + 6)으로 본다. 램프가 완만해지고 매각 시점이 6개월 밀린다.
    - **매각가 −10%** 는 `exit_cap ÷ 0.9` 다. 매각가 = NOI ÷ cap 이므로 정확히
      0.9배가 되고, 운영 NOI 는 건드리지 않는다(cap 5% → 5.5556%).

    자기자본 사다리는 **그 시나리오 자신의** 총사업비 대비 비율이라 고정점으로
    푼다(`_equity_for_share`). 그래서 "자기자본 20%" 행의 LTC 는 정확히 0.80 이다.

    시나리오 하나가 물리 게이트 밖으로 나가면(예: exit cap 11.5% 에 +1.0%p) 그
    행을 빼지 않고 예외를 그대로 올린다 — 빠진 행은 "괜찮았다"로 읽힌다.

    반환 순서는 위 표 순서로 고정이다(같은 입력이면 항상 같은 표).
    """
    base = pf_model(base_inputs)
    base_irr = base["equity_irr"]
    p = base["assumptions"]

    scenarios: list[tuple[str, str, dict]] = [
        ("공사비 +5%", "hard_cost_won × 1.05",
         {"hard_cost_won": p["hard_cost_won"] * 1.05}),
        ("공사비 +10%", "hard_cost_won × 1.10",
         {"hard_cost_won": p["hard_cost_won"] * 1.10}),
        ("준공지연 +6개월", "months_build + 6 (같은 공사비를 더 긴 기간에 균등 분산)",
         {"months_build": p["months_build"] + 6}),
        ("준공지연 +12개월", "months_build + 12 (같은 공사비를 더 긴 기간에 균등 분산)",
         {"months_build": p["months_build"] + 12}),
        ("금리 +1%p", "loan_rate + 0.01", {"loan_rate": p["loan_rate"] + 0.01}),
        ("금리 +2%p", "loan_rate + 0.02", {"loan_rate": p["loan_rate"] + 0.02}),
        ("임대개시 +6개월", "lease_up_months + 6 (안정화 도달이 6개월 늦어진다)",
         {"lease_up_months": p["lease_up_months"] + 6}),
        ("안정화 NOI −10%", "stabilized_noi_won_y × 0.9",
         {"stabilized_noi_won_y": p["stabilized_noi_won_y"] * 0.9}),
        ("exit cap +0.5%p", "exit_cap + 0.005", {"exit_cap": p["exit_cap"] + 0.005}),
        ("exit cap +1.0%p", "exit_cap + 0.01", {"exit_cap": p["exit_cap"] + 0.01}),
        ("매각가 −10%", "exit_cap ÷ 0.9 (매각가 = NOI ÷ cap 이라 정확히 0.9배)",
         {"exit_cap": p["exit_cap"] / 0.9}),
    ]

    rows = []
    for name, shock, override in scenarios:
        rows.append(_stress_row(name, shock, pf_model({**base_inputs, **override}),
                                base_irr))
    for share in EQUITY_SHARE_LADDER:
        result = _equity_for_share(base_inputs, share, base["total_cost"])
        rows.append(_stress_row(
            f"자기자본 {share:.0%}",
            f"equity_won = 총사업비 × {share:.0%} (그 시나리오 자신의 총사업비 대비)",
            result, base_irr))
    return rows


def _stress_row(name: str, shock: str, result: dict, base_irr: float | None) -> dict:
    """스트레스 한 행. `delta` 는 기준 대비 지분 IRR 차이(둘 중 하나가 None 이면 None)."""
    irr = result["equity_irr"]
    delta = None if irr is None or base_irr is None else irr - base_irr
    return {
        "name": name,
        "shock": shock,
        "delta": delta,
        "equity_irr": irr,
        "ltc": result["ltc"],
        "llcr": result["llcr"],
    }
