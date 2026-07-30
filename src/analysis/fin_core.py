"""금융 코어 — NPV·IRR·원리금균등 상환과 분석 계층 공용 입력 가드.

수지(~/개발 `src/analysis/feasibility.py`)에서 검증을 마친 NPV·IRR 을 그대로
이식하고, 대출 상환에 쓸 `pmt` 를 더했다. 이후 취득·리파이낸싱·PF 계산은
금융 산식을 스스로 쓰지 않고 이 세 함수만 부른다.

규약이 둘 있다. 지키지 않으면 값이 조용히 4배 어긋난다.

1. **현금흐름 원소는 분기다.** `cashflows[0]` 이 0분기(현재), `cashflows[1]` 이
   1분기 뒤다. 연 단위 흐름을 그대로 넣으면 안 된다.
2. **인자로 받는 할인율·반환하는 IRR 은 연율이다.** 분기 환산은 이 안에서
   `(1+r)**0.25-1` 로 하고, IRR 은 분기로 풀어 `(1+q)**4-1` 로 되돌린다.

`require_finite` 도 여기 산다. 분석 일곱 모듈이 저마다 같은 가드를 사적으로
들고 있었고, 그중 하나(`effective_rent`)만 NaN 은 막고 inf 는 통과시키는
변종이었다. 가드가 여러 벌이면 어긋난 한 벌이 곧 구멍이라, 이 모듈을 단일
출처로 삼는다. **이 모듈은 저장소 안의 어떤 모듈도 임포트하지 않는다**(표준
라이브러리 `math` 뿐) — 임포트 방향이 늘 여기로 들어오기만 해서, 일곱 모듈이
가드를 가져다 써도 순환이 생기지 않는다.

전부 순수 함수다 — I/O 도 전역 상태도 없다.
"""

import math


def require_finite(x: float, what: str) -> None:
    """NaN·±무한대를 입력 오류(`ValueError`)로 잡는다. 분석 계층의 단일 가드다.

    막는 이유는 두 값이 **정상 float 처럼 생겼다**는 데 있다.

    · NaN 은 크기 비교가 전부 False 라 도메인 검사(`0 < x <= 1` 따위)와 구간표
      선택(`x < upper`)을 조용히 통과한다. 통과하지 못하는 자리에서는 "범위
      밖"으로 걸려 오류 유형까지 뒤바꾼다 — 입력 오류(`ValueError`)여야 할 것이
      "단위를 의심하라"(`RuntimeError`)로 나간다.
    · ±inf 는 NOI·연면적·가격처럼 상한 검사가 없는 인자에서 그대로 지나가
      cap·대출가능액·IRR 을 inf/NaN 으로 만들고, 구간표에서는 마지막 칸(최대
      감가·최고 프리미엄)으로 조용히 떨어진다.

    둘 다 하류가 잡지 못하므로 계산에 들어가기 전에 여기서 멈춘다. 판정은
    `math.isnan`·`math.isinf` 한 쌍으로만 한다 — 같은 뜻을 모듈마다 다른
    관용구(`x != x`, `x == float("inf")`)로 쓰면 그 차이가 곧 동작 차이가 된다.

    수치가 아닌 값(None·문자열)은 `math.isnan` 이 `TypeError` 를 낸다. 유형
    검사가 필요한 진입점(`pf.pf_model` 처럼 dict 를 받는 자리)은 이 가드를
    부르기 전에 스스로 유형을 확인해 `ValueError` 로 바꾼다.
    """
    if math.isnan(x):
        raise ValueError(f"{what} 값이 NaN 이다 — 검사를 조용히 통과하므로 막는다")
    if math.isinf(x):
        raise ValueError(f"{what} 값이 무한대다 — 검사를 조용히 통과하므로 막는다")


def npv(cashflows: list[float], annual_rate: float) -> float:
    """분기 현금흐름의 순현재가치. 할인율은 연율로 받아 분기로 환산한다.

    NPV = Σ cf_q / (1 + r_q)^q,  r_q = (1 + annual_rate)^(1/4) − 1
    """
    rq = (1 + annual_rate) ** 0.25 - 1
    return sum(cf / (1 + rq) ** q for q, cf in enumerate(cashflows))


def _npv_at(cashflows: list[float], quarterly_rate: float) -> float:
    """분기이율에서의 현재가치 합(IRR 탐색 내부용 — 연율 환산을 하지 않는다)."""
    return sum(cf / (1 + quarterly_rate) ** q for q, cf in enumerate(cashflows))


def irr_annual(cashflows: list[float]) -> float | None:
    """분기 IRR 을 이분법(구간 [-0.5, 1.0], 200회)으로 구해 연율화한다.

    반환은 (1 + irr_q)^4 − 1. 뉴턴법 대신 고정 반복 이분법을 쓰는 이유는
    수렴이 입력에 좌우되지 않아 같은 흐름이면 항상 같은 값이 나오기 때문이다.

    다음 두 경우는 값을 지어내지 않고 None 을 돌려준다.
    · 현금흐름에 부호 변화가 없다(전부 유입이거나 전부 유출).
    · 구간 [-0.5, 1.0] 안에서 부호가 잡히지 않는다(근이 탐색 범위 밖).
    """
    nonzero = [c for c in cashflows if c != 0]
    if not nonzero or all(c > 0 for c in nonzero) or all(c < 0 for c in nonzero):
        return None  # 부호 변화 없음

    lo, hi = -0.5, 1.0
    flo = _npv_at(cashflows, lo)
    fhi = _npv_at(cashflows, hi)
    if flo == 0:
        return (1 + lo) ** 4 - 1
    if fhi == 0:
        return (1 + hi) ** 4 - 1
    if flo * fhi > 0:
        return None  # 범위 내 근 없음

    for _ in range(200):
        mid = (lo + hi) / 2
        fmid = _npv_at(cashflows, mid)
        if flo * fmid <= 0:
            hi = mid
        else:
            lo, flo = mid, fmid
    irr_q = (lo + hi) / 2
    return (1 + irr_q) ** 4 - 1


def pmt(principal: float, annual_rate: float, years: int) -> float:
    """연 원리금균등 상환액 = P·r / (1 − (1+r)^−n). 무이자면 원금을 n 년으로 나눈다.

    NPV·IRR 과 달리 여기서는 연 단위 상환을 가정한다(대출 조건이 연 기준으로
    주어지기 때문이다). 반환값은 양수이며 부호 규약은 부르는 쪽이 정한다.
    """
    if years <= 0:
        raise ValueError(f"상환 연수는 1 이상이어야 한다: years={years}")
    if annual_rate == 0:
        return principal / years
    return principal * annual_rate / (1 - (1 + annual_rate) ** -years)
