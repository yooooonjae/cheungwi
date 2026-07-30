"""NOI 골든 테스트.

기대값은 손계산으로 확정했다. 엔진과 어긋나면 고쳐야 하는 쪽은 엔진이지
이 표가 아니다.

| ID        | 입력                                                      | 산식                          | 기대값          |
|-----------|-----------------------------------------------------------|-------------------------------|-----------------|
| G-NOI-001 | 유효 25,000원/㎡·월, GFA 100,000㎡, 전용률 0.5, 공실 5%, opex 15% | 임대면적 = 100000×0.5 = 50,000㎡ | 50,000.0        |
|           |                                                           | EGI = 25000×50000×12×0.95     | 14,250,000,000  |
|           |                                                           | NOI = 14.25e9×0.85            | 12,112,500,000  |
| G-NOI-002 | 위와 같되 공실 100%                                       | EGI = …×0 → NOI = 0×0.85      | 0.0             |

전용률 0.5·opex 0.15 는 골든 상수가 아니라 **조정 가능한 가정**이다(NLA 관행,
관리비 상계 후 미회수분). 값 자체가 아니라 결과에 가정이 동봉되는지를 검사한다.
"""

import pytest

from src.analysis.effective_rent import RENT_MAX_WON_M2_MO, RENT_MIN_WON_M2_MO
from src.analysis.noi import noi


# ── 브리프 확정 골든 2건(축자) ──────────────────────────────────────────

# | G-NOI-001 | 유효 25,000원/㎡·월, GFA 100,000㎡, 전용률 0.5, 공실 5%, opex 15% |
# | 임대면적 50,000 · EGI = 25000×50000×12×0.95 = 14,250,000,000 |
# | NOI = 14.25e9×0.85 = 12,112,500,000 |

def test_golden_noi():
    r = noi(25_000, 100_000, 0.5, 0.05, 0.15)
    assert r["egi_won_y"] == 14_250_000_000.0
    assert r["noi_won_y"] == 12_112_500_000.0
    assert r["assumptions"]["efficiency"] == 0.5


def test_full_vacancy_zero_noi():
    assert noi(25_000, 100_000, 0.5, 1.0, 0.15)["noi_won_y"] == 0.0


# ── 반환 계약 ───────────────────────────────────────────────────────────

def test_return_shape_is_the_contract():
    r = noi(25_000, 100_000, 0.5, 0.05, 0.15)
    assert set(r) == {"noi_won_y", "egi_won_y", "assumptions"}


def test_assumptions_carry_the_offset_convention():
    # 관리비 상계 가정(임차인 부담 관리비로 운영비 대부분 회수, opex_ratio 는
    # 미회수분)이 결과에 실려 나가야 한다. 라벨 없는 NOI 는 출고 금지다.
    a = noi(25_000, 100_000, 0.5, 0.05, 0.15)["assumptions"]
    assert a["efficiency"] == 0.5
    assert a["vacancy"] == 0.05
    assert a["opex_ratio"] == 0.15
    assert a["nla_m2"] == 50_000.0
    assert any("관리비" in n for n in a["notes"])
    assert a["caveats"]


def test_assumptions_are_not_shared_state():
    # 순수 함수 규약 — 부르는 쪽이 고쳐도 다음 호출이 오염되지 않아야 한다.
    r = noi(25_000, 100_000, 0.5, 0.05, 0.15)
    r["assumptions"]["notes"].append("오염")
    r["assumptions"]["efficiency"] = 9.9
    again = noi(25_000, 100_000, 0.5, 0.05, 0.15)
    assert again["assumptions"]["efficiency"] == 0.5
    assert "오염" not in again["assumptions"]["notes"]


# ── 산식(각 인자가 들어가는 자리) ───────────────────────────────────────

def test_zero_vacancy_and_zero_opex_is_pgi():
    # 공실 0·운영경비 0 이면 NOI = EGI = 유효임대료 × 임대면적 × 12.
    r = noi(25_000, 100_000, 0.5, 0.0, 0.0)
    assert r["egi_won_y"] == 15_000_000_000.0
    assert r["noi_won_y"] == 15_000_000_000.0


def test_vacancy_scales_egi_linearly():
    full = noi(25_000, 100_000, 0.5, 0.0, 0.15)["egi_won_y"]
    half = noi(25_000, 100_000, 0.5, 0.5, 0.15)["egi_won_y"]
    assert half == full * 0.5


def test_efficiency_scales_area_linearly():
    half = noi(25_000, 100_000, 0.5, 0.05, 0.15)["noi_won_y"]
    whole = noi(25_000, 100_000, 1.0, 0.05, 0.15)["noi_won_y"]
    assert whole == half * 2


# ── 도메인 검사(경계 포함 여부까지 고정) ────────────────────────────────

def test_efficiency_domain_is_half_open_zero_to_one():
    noi(25_000, 100_000, 1.0, 0.05, 0.15)      # 전용률 100% 는 허용(경계)
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 0.0, 0.05, 0.15)  # 임대면적 0 은 건물이 아니다
    with pytest.raises(ValueError):
        noi(25_000, 100_000, -0.1, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 1.1, 0.05, 0.15)  # GFA 보다 큰 임대면적


def test_vacancy_domain_is_closed_zero_to_one():
    noi(25_000, 100_000, 0.5, 0.0, 0.15)       # 만실 허용(경계)
    noi(25_000, 100_000, 0.5, 1.0, 0.15)       # 전관 공실 허용(경계)
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 0.5, -0.01, 0.15)
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 0.5, 1.01, 0.15)


def test_opex_ratio_domain_excludes_one():
    noi(25_000, 100_000, 0.5, 0.05, 0.0)       # 전액 상계 허용(경계)
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 0.5, 0.05, 1.0)   # NOI 0 = 운영경비가 수입 전부
    with pytest.raises(ValueError):
        noi(25_000, 100_000, 0.5, 0.05, -0.01)


def test_rent_and_gfa_must_be_positive():
    with pytest.raises(ValueError):
        noi(0, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(-25_000, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(25_000, 0, 0.5, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(25_000, -100_000, 0.5, 0.05, 0.15)


# ── 임대료 물리 게이트(단위 오입력 차단) ────────────────────────────────

def test_gate_rejects_annual_rent_in_a_monthly_slot():
    # 연액(300,000원/㎡·년)을 월액 자리에 넣으면 NOI 가 12배로 부푼다.
    # 게이트가 없으면 1,453.5억이 조용히 나가고, 하류 value.appraise 는
    # 그것을 12배 감정가로 바꾼다.
    with pytest.raises(RuntimeError):
        noi(300_000, 100_000, 0.5, 0.05, 0.15)


def test_gate_rejects_pyeong_rent_in_a_m2_slot():
    # 평당가(약 3.3배)도 같은 자리에서 막힌다.
    with pytest.raises(RuntimeError):
        noi(82_500, 100_000, 0.5, 0.05, 0.15)


def test_gate_boundaries_are_inclusive():
    noi(RENT_MIN_WON_M2_MO, 100_000, 0.5, 0.05, 0.15)   # 양끝은 통과
    noi(RENT_MAX_WON_M2_MO, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(RuntimeError):
        noi(RENT_MIN_WON_M2_MO - 1, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(RuntimeError):
        noi(RENT_MAX_WON_M2_MO + 1, 100_000, 0.5, 0.05, 0.15)


def test_gate_constants_have_a_single_source():
    # 게이트 상수를 복제하지 않고 effective_rent 것을 그대로 쓴다.
    # (여기서 다시 적으면 두 모듈이 따로 움직여 드리프트가 생긴다.)
    import src.analysis.noi as noi_module

    assert noi_module.RENT_MIN_WON_M2_MO is RENT_MIN_WON_M2_MO
    assert noi_module.RENT_MAX_WON_M2_MO is RENT_MAX_WON_M2_MO


def test_input_error_is_not_dressed_up_as_a_gate_violation():
    # 0·음수 임대료도 게이트 범위 밖이지만 단위 문제가 아니라 입력 오류다 —
    # 부르는 쪽이 둘을 다르게 다룰 수 있어야 하므로 ValueError 를 유지한다.
    with pytest.raises(ValueError):
        noi(-25_000, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(float("nan"), 100_000, 0.5, 0.05, 0.15)


# ── NaN·무한대(조용한 통과 금지) ────────────────────────────────────────

def test_nan_inputs_are_rejected_not_silently_multiplied():
    # NaN 은 비교가 전부 False 라 도메인 검사를 통과하고, 곱셈 결과 NaN 은
    # 정상 float 처럼 하류(cap rate·가치·대출)로 흘러간다.
    nan = float("nan")
    for args in (
        (nan, 100_000, 0.5, 0.05, 0.15),
        (25_000, nan, 0.5, 0.05, 0.15),
        (25_000, 100_000, nan, 0.05, 0.15),
        (25_000, 100_000, 0.5, nan, 0.15),
        (25_000, 100_000, 0.5, 0.05, nan),
    ):
        with pytest.raises(ValueError):
            noi(*args)


def test_infinite_inputs_are_rejected():
    inf = float("inf")
    with pytest.raises(ValueError):
        noi(inf, 100_000, 0.5, 0.05, 0.15)
    with pytest.raises(ValueError):
        noi(25_000, inf, 0.5, 0.05, 0.15)
