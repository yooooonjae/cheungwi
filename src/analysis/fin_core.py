"""금융 코어 — NPV·IRR·원리금균등 상환.

수지(~/개발 `src/analysis/feasibility.py`)에서 검증을 마친 NPV·IRR 을 그대로
이식하고, 대출 상환에 쓸 `pmt` 를 더했다. 이후 취득·리파이낸싱·PF 계산은
금융 산식을 스스로 쓰지 않고 이 세 함수만 부른다.

규약이 둘 있다. 지키지 않으면 값이 조용히 4배 어긋난다.

1. **현금흐름 원소는 분기다.** `cashflows[0]` 이 0분기(현재), `cashflows[1]` 이
   1분기 뒤다. 연 단위 흐름을 그대로 넣으면 안 된다.
2. **인자로 받는 할인율·반환하는 IRR 은 연율이다.** 분기 환산은 이 안에서
   `(1+r)**0.25-1` 로 하고, IRR 은 분기로 풀어 `(1+q)**4-1` 로 되돌린다.

전부 순수 함수다 — I/O 도 전역 상태도 없다.
"""


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
