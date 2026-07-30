"""가치 — 소득접근 감정가와 추정 오차의 분포.

가치는 두 조각이다. `appraise` 는 소득을 cap 으로 나눠 한 동의 값을 만들고,
`error_dist` 는 그 추정이 실거래와 얼마나 어긋났는지를 분포로 공개한다.
둘째가 없으면 첫째는 소수점 열두 자리짜리 자신감일 뿐이다 — 추정치는 오차
분포와 함께 나가야 한다.

    appraise   : 가치 = NOI ÷ cap                (소득접근, 직접환원법)
    error_dist : err = (추정 − 실거래) / 실거래  의 사분위·평균절대오차

전부 순수 함수다 — I/O 도 전역 상태도 없다. 표준 라이브러리(`math`·
`statistics`)와 `caprate` 의 게이트 상수 둘만 쓴다(아래 규약 2).

규약이 셋 있다.

1. **금액은 원, cap 은 소수 연율이다.** NOI 는 원/년, 반환 가치는 원.
   cap 4.5% 는 `0.045` 이지 `4.5` 가 아니다.
2. **cap 게이트(0.02~0.12)를 인자에 건다.** `caprate.implied` 가 자기 산출에
   거는 것과 같은 범위를 `appraise` 는 **받는 인자**에 건다. 상수는
   `caprate` 것을 임포트해 쓴다 — 여기 다시 적으면 두 모듈이 따로 움직인다.

   `implied` 만 막으면 실거래 가격이 있는 경로만 덮인다. 정작 출고 경로는
   `appraise`(NOI ÷ cap)라서, 게이트가 없으면 cap 을 `4.5` 로 넣은 감정가가
   100분의 1 로, `0.0045` 로 넣은 감정가가 10배로 조용히 나간다. 결과는
   정상 float 이라 하류(대출 LTV·IRR)가 잡지 못한다.

   가치를 배수로 흔드는 또 하나의 축인 NOI 자체는 여기서 검사할 수 없다
   (건물 규모에 따라 몇 억부터 몇백 억까지 정상이다). 그쪽 방어선은 `noi()`
   진입의 임대료 물리 게이트다.
3. **오차율의 정의는 하나다: err = (추정 − 실거래) / 실거래.** 분모는 늘
   실거래이고 과대추정이 양수다. 뒤집으면 부호가 반대가 되고 분모가 바뀌어
   중앙값의 뜻이 달라진다.

NaN·무한대는 도메인 검사가 아니라 별도 가드로 막는다. 크기 비교가 전부
False 라 cap 게이트를 원인이 아닌 오류 유형으로 통과·차단하고, NaN 가치는
정상 float 처럼 생겨서 하류까지 그대로 흘러간다.

오류 유형은 둘을 구분한다. 값이 물리적으로 말이 안 되면(음수 NOI, 실거래가
0 이하, NaN·inf, 표본 3건 미만) `ValueError` 로 "입력이 틀렸다"고 하고, 값
자체는 말이 되는데 cap 이 범위 밖이면 `RuntimeError` 로 "단위를 의심하라"고
한다.
"""

import math
import statistics

from src.analysis.caprate import CAP_MAX, CAP_MIN

# 사분위수에 필요한 최소 표본. `statistics.quantiles` 자체는 2점으로도 돌지만
# 그때 나오는 p25·p75 는 사분위수가 아니라 두 점 사이의 내삽일 뿐이다.
MIN_PAIRS_FOR_QUANTILES = 3

_QUARTILES = 4
_QUANTILE_METHOD = "inclusive"


def _require_finite(x: float, what: str) -> None:
    """NaN·무한대를 입력 오류로 잡는다. 자기 자신과 다른 값은 NaN 뿐이다.

    NaN 은 크기 비교가 전부 False 라 cap 게이트에 "범위 밖"으로 걸리는데,
    그러면 오류 유형이 `RuntimeError`(단위 의심)가 되어 원인을 잘못 짚는다.
    inf 는 NOI 처럼 상한 검사가 없는 인자에서 그대로 지나가 가치를 inf 로
    만든다. 둘 다 정상 float 처럼 생겨 하류가 잡지 못한다.
    """
    if x != x:
        raise ValueError(f"{what} 값이 NaN 이다 — 검사를 조용히 통과하므로 막는다")
    if math.isinf(x):
        raise ValueError(f"{what} 값이 무한대다 — 검사를 조용히 통과하므로 막는다")


def _gate_cap(cap: float) -> None:
    """cap 인자가 물리 범위(0.02~0.12) 안인지 확인한다. 밖이면 멈춘다.

    범위 상수는 `caprate` 것을 그대로 쓴다(단일 출처). NaN 은 부르는 쪽이
    먼저 `ValueError` 로 걸러 여기 오지 않는다.
    """
    if not CAP_MIN <= cap <= CAP_MAX:
        raise RuntimeError(
            f"cap {cap:.6f}(= {cap * 100:.4f}%)이 물리 범위"
            f"[{CAP_MIN}, {CAP_MAX}] 밖이다 — cap 이 아니라 단위(%↔소수)를 "
            "의심하라. 4.5 를 넣으면 감정가가 100분의 1, 0.0045 를 넣으면 "
            "10배가 되고, 둘 다 정상 금액처럼 생겨서 대출·IRR 까지 그대로 "
            "흘러간다"
        )


def appraise(noi_won_y: float, cap: float) -> float:
    """소득접근 감정가(원) = NOI ÷ cap.

    | 예(G-VAL-001)              | 산식                    | 값                 |
    |----------------------------|-------------------------|--------------------|
    | NOI 121.125억, cap 4.5%    | 12,112,500,000 / 0.045  | 269,166,666,666.67 |

    직접환원법(direct capitalization)이다 — 한 해의 정상화 NOI 를 cap 으로
    나눠 영구현금흐름의 현재가치로 본다. 임대차 만기 구조·리스업·CapEx 의
    시점은 들어 있지 않다(그쪽은 DCF 의 몫이다).

    도메인: NOI 는 0 이상이며 유한해야 한다. 음수·NaN·inf 는 `ValueError`.
    NOI 0(전관 공실)은 가치 0 을 돌려준다 — 소득이 없는 건물의 **소득**접근
    가치는 0 이라는 뜻이지 그 건물이 무가치하다는 뜻이 아니다(토지·재개발
    가치는 이 접근에 없다).

    게이트: cap 은 0.02~0.12(양끝 포함) 안이어야 한다. 밖이면 `RuntimeError`.
    """
    _require_finite(noi_won_y, "NOI")
    if noi_won_y < 0:
        raise ValueError(f"NOI 는 음수일 수 없다: {noi_won_y}")
    _require_finite(cap, "cap")
    _gate_cap(cap)

    return noi_won_y / cap


def error_dist(pairs: list[tuple[float, float]]) -> dict:
    """(추정, 실거래) 쌍의 오차율 분포.

    **오차율 정의: err = (추정 − 실거래) / 실거래.** 과대추정이 양수, 분모는
    늘 실거래다.

    | 예(G-ERR-001)                        | 오차율            | 결과                    |
    |--------------------------------------|-------------------|-------------------------|
    | (110, 100) · (95, 100) · (100, 100)  | 0.1 · −0.05 · 0.0 | p25 −0.025 · median 0.0 |
    |                                      |                   | p75 0.05 · MAE 0.05     |

    사분위수는 `statistics.quantiles(errs, n=4, method="inclusive")` 다.
    inclusive 는 표본의 최소·최대를 분포의 양끝으로 보고 위치
    `p·(m−1)` 에서 선형내삽한다. 표본이 작을 때 exclusive 가 양끝을
    외삽하지 못하는 문제가 없어 이쪽을 쓴다. `median_err` 는 같은 호출의
    가운데 값이라 p25·p75 와 정의가 어긋나지 않는다.

    도메인: 쌍이 3건 이상이어야 한다(사분위수의 최소 표본 — 2건이면
    `quantiles` 가 돌기는 하지만 두 점의 내삽일 뿐이다). 실거래가는 양수,
    추정가는 0 이상, 둘 다 유한해야 한다. 밖이면 `ValueError`.

    반환: `{"n", "median_err", "p25", "p75", "mean_abs_err"}`. `mean_abs_err`
    는 **절대오차의 평균**이지 평균오차의 절대값이 아니다(부호가 상쇄되지
    않는다). 표본이 작으면 사분위수 자체가 불안정하니 `n` 을 함께 인용하라.
    """
    if len(pairs) < MIN_PAIRS_FOR_QUANTILES:
        raise ValueError(
            f"오차 분포에는 (추정, 실거래) 쌍이 {MIN_PAIRS_FOR_QUANTILES}건 "
            f"이상 필요하다: {len(pairs)}건만 들어왔다"
        )

    errs = []
    for i, pair in enumerate(pairs):
        if len(pair) != 2:
            raise ValueError(f"{i}번째 쌍이 (추정, 실거래) 두 값이 아니다: {pair}")
        estimated, actual = pair
        _require_finite(estimated, f"{i}번째 추정가")
        if estimated < 0:
            raise ValueError(f"{i}번째 추정가는 음수일 수 없다: {estimated}")
        _require_finite(actual, f"{i}번째 실거래가")
        if actual <= 0:
            raise ValueError(f"{i}번째 실거래가는 양수여야 한다: {actual}")
        errs.append((estimated - actual) / actual)

    p25, median_err, p75 = statistics.quantiles(
        errs, n=_QUARTILES, method=_QUANTILE_METHOD
    )

    return {
        "n": len(errs),
        "median_err": median_err,
        "p25": p25,
        "p75": p75,
        "mean_abs_err": statistics.fmean(abs(e) for e in errs),
    }
