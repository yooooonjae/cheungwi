"""유효임대료 골든 테스트.

기대값은 손계산으로 확정했다. 엔진과 어긋나면 고쳐야 하는 쪽은 엔진이지
이 표가 아니다.

| ID        | 입력                                              | 산식                     | 기대값    |
|-----------|---------------------------------------------------|--------------------------|-----------|
| G-ER-001  | 명목 30,000원/㎡·월, 렌트프리 연 2개월            | 30000×10/12              | 25,000.0  |
| G-ADJ-001 | 기준 25,000, 연식 5y(+6%)·GFA 12만㎡(+8%)·역 300m(+3%) | 25000×1.06×1.08×1.03 | 29,478.6  |

권역 렌트프리(도심 2.0·강남 1.5·여의도마포 2.5개월/년)는 골든이 아니라
조정 가능한 가정값이다 — 값 자체가 아니라 출처가 붙어 있는지를 검사한다.
"""

import pytest

from src.analysis.effective_rent import effective_rent, building_adjust, region_params


# ── 브리프 확정 골든 4건 ────────────────────────────────────────────────

def test_golden_effective_rent():
    assert effective_rent(30_000, 2.0) == 25_000.0


def test_golden_building_adjust():
    r = building_adjust(25_000, 5, 120_000, 300)
    assert abs(r["value"] - 29_478.6) < 0.1
    assert r["factors"] == {"age": 1.06, "scale": 1.08, "subway": 1.03}


def test_region_params_have_source():
    p = region_params()
    assert set(p) - {"_meta"} == {"도심", "강남", "여의도마포"}
    assert all("rent_free_mo" in v for k, v in p.items() if k != "_meta")
    assert p["_meta"]["source"]   # 가정의 출처는 필수


def test_gate_rejects_absurd_rent():
    import pytest
    with pytest.raises(RuntimeError):
        effective_rent(500_000, 2.0)   # 유효 41.7만원/㎡·월 → 게이트 위반


# ── 경계 규약(구간은 [하한, 상한) — 상한은 다음 구간 몫) ────────────────

def test_age_boundaries_are_half_open():
    # 0 과 9.99 는 같은 구간, 10.0 은 다음 구간.
    assert building_adjust(25_000, 0, 40_000, None)["factors"]["age"] == 1.06
    assert building_adjust(25_000, 9.99, 40_000, None)["factors"]["age"] == 1.06
    assert building_adjust(25_000, 10, 40_000, None)["factors"]["age"] == 1.0
    assert building_adjust(25_000, 20, 40_000, None)["factors"]["age"] == 0.94
    assert building_adjust(25_000, 30, 40_000, None)["factors"]["age"] == 0.88
    assert building_adjust(25_000, 99, 40_000, None)["factors"]["age"] == 0.88


def test_gfa_boundaries_are_half_open():
    assert building_adjust(25_000, 15, 29_999, None)["factors"]["scale"] == 0.96
    assert building_adjust(25_000, 15, 30_000, None)["factors"]["scale"] == 1.0
    assert building_adjust(25_000, 15, 50_000, None)["factors"]["scale"] == 1.04
    assert building_adjust(25_000, 15, 100_000, None)["factors"]["scale"] == 1.08


def test_subway_unknown_is_neutral_not_penalty():
    # 거리를 모르는 건물을 역세권 아님으로 단정하면 안 된다 — 둘 다 1.0 이되
    # 이유가 다르므로 caveat 에 남긴다.
    assert building_adjust(25_000, 15, 40_000, None)["factors"]["subway"] == 1.0
    assert building_adjust(25_000, 15, 40_000, 400)["factors"]["subway"] == 1.03
    assert building_adjust(25_000, 15, 40_000, 401)["factors"]["subway"] == 1.0


# ── 게이트·입력 검증 ────────────────────────────────────────────────────

def test_gate_rejects_too_low_rent():
    with pytest.raises(RuntimeError):
        effective_rent(10_000, 6.0)   # 유효 5,000원/㎡·월 → 하한 위반


def test_gate_applies_to_adjusted_rent_too():
    with pytest.raises(RuntimeError):
        building_adjust(58_000, 5, 120_000, 300)   # 보정 후 6.8만 → 상한 위반


def test_rent_free_out_of_domain_is_value_error():
    # 물리적으로 불가능한 입력은 게이트(RuntimeError)가 아니라 입력 오류다.
    with pytest.raises(ValueError):
        effective_rent(30_000, -1.0)
    with pytest.raises(ValueError):
        effective_rent(30_000, 13.0)


def test_nan_inputs_are_rejected_not_silently_bucketed():
    # NaN 은 모든 비교가 False 라 구간표를 조용히 통과한다. 막지 않으면
    # gfa=NaN 이 최고 프리미엄(1.08), age=NaN 이 최대 감가(0.88)로 떨어지고
    # 결과는 정상 float 이라 물리 게이트도 잡지 못한다.
    nan = float("nan")
    with pytest.raises(ValueError):
        building_adjust(25_000, nan, 40_000, 300)
    with pytest.raises(ValueError):
        building_adjust(25_000, 5, nan, 300)
    with pytest.raises(ValueError):
        building_adjust(25_000, 5, 40_000, nan)


def test_region_params_are_a_copy_not_shared_state():
    # 순수 함수 규약 — 부르는 쪽이 고쳐도 다음 호출이 오염되지 않아야 한다.
    p = region_params()
    p["도심"]["rent_free_mo"] = 99.0
    assert region_params()["도심"]["rent_free_mo"] == 2.0


def test_region_params_meta_flags_the_assumption():
    meta = region_params()["_meta"]
    assert "가정" in meta["source"]
    assert meta["caveat"]
