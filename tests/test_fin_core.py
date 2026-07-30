"""금융 코어 골든 테스트와 공용 유한성 가드.

수지(~/개발)에서 이미 독립 유도·외부 대조를 마친 상수를 그대로 가져온다.
기대값이 엔진과 어긋나면 고쳐야 하는 쪽은 엔진이지 이 표가 아니다.

`fin_core` 는 `require_finite` 의 집이기도 하다 — 분석 일곱 모듈이 같은 함수
객체를 쓰는지(가드가 한 벌인지)를 이 파일 끝에서 동일성으로 못박는다.

| ID        | 입력                        | 산식                         | 기대값                                          |
|-----------|-----------------------------|------------------------------|-------------------------------------------------|
| G-IRR-001 | [-1000, 500, 500, 500]      | 이분법, Excel IRR 대조       | 기간이율 23.3752% → 연율 (1.233752)^4-1 = 1.3169218123 |
| G-NPV-001 | 같은 흐름, 할인율 0         | Σcf                          | 500.0                                           |
| G-NPV-002 | 같은 흐름, 연 46.41%(분기 10%) | 500/1.1+500/1.21+500/1.331 | 243.4259954921                                  |
| G-PMT-001 | 10억, 연 5%, 10년           | 1e9×0.05/(1-1.05^-10)        | 129,504,574.97 (Excel PMT 대조)                 |
"""

import pytest

from src.analysis import (
    acquisition, caprate, effective_rent, fin_core, noi, pf, refi, value,
)
from src.analysis.fin_core import npv, irr_annual, pmt, require_finite


def test_golden_irr():
    assert abs(irr_annual([-1000, 500, 500, 500]) - 1.3169218123) < 1e-6


def test_golden_npv_zero_and_10pct_quarter():
    assert npv([-1000, 500, 500, 500], 0.0) == 500.0
    assert abs(npv([-1000, 500, 500, 500], 0.4641) - 243.4259954921) < 1e-4


def test_golden_pmt():
    assert abs(pmt(1_000_000_000, 0.05, 10) - 129_504_574.97) < 1.0
    assert pmt(1_000_000_000, 0.0, 10) == 100_000_000.0


def test_irr_none_when_no_sign_change():
    assert irr_annual([100, 100]) is None


def test_irr_none_when_root_outside_search_range():
    # 부호는 바뀌지만 근이 분기이율 [-0.5, 1.0] 밖(회수액이 원금에 턱없이 못 미침).
    # 이 경우 이분법을 강행하면 엉뚱한 경계값을 내놓으므로 None 이어야 한다.
    assert irr_annual([-1000, 1]) is None


# ── 유한성 가드는 한 벌이다 ──────────────────────────────────────────────────

def test_require_finite_rejects_nan_and_both_infinities():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            require_finite(bad, "시험값")
    require_finite(0.0, "시험값")        # 유한한 값은 통과한다(0 도 포함)
    require_finite(-1e300, "시험값")


def test_every_analysis_module_shares_one_finite_guard():
    """분석 일곱 모듈이 같은 함수 객체를 쓴다 — 가드는 한 벌이어야 한다.

    예전에는 모듈마다 사적인 `_require_finite` 를 들고 있었고, 그중
    `effective_rent._reject_nan` 만 NaN 은 막고 inf 는 통과시키는 변종이었다.
    가드가 여러 벌이면 어긋난 한 벌이 곧 구멍이라, 임포트인지를 동일성으로
    못박는다(게이트 상수에 쓰는 것과 같은 방식이다).
    """
    for module in (effective_rent, noi, caprate, value, acquisition, refi, pf):
        assert module.require_finite is fin_core.require_finite, module.__name__
        # 사적인 변종이 되살아나면 여기서 잡힌다.
        assert not hasattr(module, "_require_finite")
        assert not hasattr(module, "_reject_nan")


def test_unified_guard_now_rejects_infinity_in_effective_rent_too():
    """통일의 실질 — `effective_rent` 쪽 inf 가 조용히 지나가지 않는다.

    구간표는 마지막 상한이 `inf` 라 연면적 inf 가 **최고 프리미엄 칸**(1.08)으로,
    연식 inf 가 최대 감가 칸(0.88)으로 조용히 떨어졌다. 명목임대료 inf 는 물리
    게이트까지 흘러가 `RuntimeError`("단위를 의심하라")로 나왔는데, 무한대는
    단위를 고쳐서 될 값이 아니라 입력이 틀린 것이다 — 둘 다 이제 `ValueError` 다.
    """
    for bad in (float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            effective_rent.building_adjust(25_000, bad, 40_000, 300)
        with pytest.raises(ValueError):
            effective_rent.building_adjust(25_000, 5, bad, 300)
        with pytest.raises(ValueError):
            effective_rent.building_adjust(25_000, 5, 40_000, bad)
        with pytest.raises(ValueError):
            effective_rent.effective_rent(bad, 2.0)
