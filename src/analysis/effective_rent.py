"""유효임대료 — 렌트프리 차감과 건물 특성 보정.

명목임대료는 계약서의 숫자일 뿐 실제로 들어오는 돈이 아니다. 서울 오피스는
렌트프리(무상임대) 관행이 붙어 있어, 임대인이 실제로 받는 돈은 명목보다
렌트프리 개월 수만큼 적다. 이 모듈은 그 차감(`effective_rent`)과, 같은
권역이라도 건물마다 다른 값이 붙는 세 특성 보정(`building_adjust`)을 한다.

전부 순수 함수다 — I/O 도 전역 상태도 없다. 표준 라이브러리만 쓴다.

규약이 셋 있다.

1. **단위는 원/㎡·월이다.** 평당도 아니고 연액도 아니다. 임대료를 넘길 때
   단위를 바꾸면 게이트가 잡아 준다(잡히지 않는 범위로 어긋나면 조용히
   틀린다 — 부르는 쪽에서 단위를 지켜야 한다).
2. **구간 경계는 [하한, 상한) 반열림이다.** 연식 "0~10년"은 [0, 10) 이라
   정확히 10년은 다음 구간(10~20년)에 들어간다. 연면적도 같아서
   정확히 10만㎡는 "10만㎡ 이상" 구간이다. 표의 마지막 구간만 위가 열려 있다.
3. **모름은 벌점이 아니다.** 역까지 거리를 모르는 건물(`dist_subway_m=None`)은
   1.0 을 받는다. 역세권이 아니라고 단정하는 것이 아니라 판단을 보류하는 것이다.
   결과적으로 400m 초과와 같은 계수지만 뜻이 다르므로 `caveats` 에 남긴다.

물리 게이트: 이 모듈이 내놓는 임대료는 10,000~60,000원/㎡·월 안에 있어야
한다. 밖이면 값을 돌려주지 않고 `RuntimeError` 를 던진다. 서울 오피스
임대료의 실측 범위를 넉넉히 감싼 값이라, 여기를 벗어났다면 임대료가 틀린
것이 아니라 단위나 자릿수가 틀린 것이다.
"""

# 물리 게이트 경계(원/㎡·월, 양끝 포함). 서울 오피스 실측 범위를 넉넉히 감쌌다.
RENT_MIN_WON_M2_MO = 10_000.0
RENT_MAX_WON_M2_MO = 60_000.0

# 구간표 — (상한 미만, 계수). 위에서부터 처음으로 상한을 밑도는 칸을 쓴다.
# 계수는 1.06 처럼 리터럴로 적는다(1 + 0.06 로 계산하면 부동소수 표현이
# 달라져 factors 비교가 어긋날 수 있다).
_AGE_FACTORS = (
    (10.0, 1.06),          # 0~10년: 신축 프리미엄 +6%
    (20.0, 1.0),           # 10~20년: 기준
    (30.0, 0.94),          # 20~30년: −6%
    (float("inf"), 0.88),  # 30년+: −12%
)
_SCALE_FACTORS = (
    (30_000.0, 0.96),      # 3만㎡ 미만: −4%
    (50_000.0, 1.0),       # 3만~5만㎡: 기준
    (100_000.0, 1.04),     # 5만~10만㎡: +4%
    (float("inf"), 1.08),  # 10만㎡+: +8%
)
_SUBWAY_RADIUS_M = 400.0   # 역세권 판정 반경(이내면 +3%)
_SUBWAY_FACTOR = 1.03

_REGION_RENT_FREE_MO = {
    "도심": 2.0,
    "강남": 1.5,
    "여의도마포": 2.5,
}


def _pick(table: tuple[tuple[float, float], ...], x: float) -> float:
    """구간표에서 계수를 고른다. 경계는 [하한, 상한) 반열림."""
    for upper, factor in table:
        if x < upper:
            return factor
    return table[-1][1]  # 도달 불가(마지막 상한이 inf) — 방어적 반환


def _gate(rent_won_m2_mo: float, what: str) -> float:
    """임대료가 물리 범위 안인지 확인하고 그대로 돌려준다. 밖이면 멈춘다."""
    if not RENT_MIN_WON_M2_MO <= rent_won_m2_mo <= RENT_MAX_WON_M2_MO:
        raise RuntimeError(
            f"{what} {rent_won_m2_mo:,.1f}원/㎡·월이 물리 범위"
            f"[{RENT_MIN_WON_M2_MO:,.0f}, {RENT_MAX_WON_M2_MO:,.0f}] 밖이다 — "
            "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라"
        )
    return rent_won_m2_mo


def effective_rent(nominal_won_m2_mo: float, rent_free_months_per_year: float) -> float:
    """렌트프리를 차감한 유효임대료.

    유효 = 명목 × (12 − 렌트프리개월) / 12

    렌트프리 2개월이면 1년 열두 달 중 열 달만 받으므로 명목의 10/12 다.
    보증금 운용수익은 여기에 넣지 않는다 — 임대료의 시간 구조와 성격이 달라
    현금흐름 쪽에서 따로 다룬다.

    결과는 물리 게이트를 통과해야 한다(10,000~60,000원/㎡·월).
    """
    if not 0 <= rent_free_months_per_year <= 12:
        raise ValueError(
            f"렌트프리는 연 0~12개월이어야 한다: {rent_free_months_per_year}"
        )
    effective = nominal_won_m2_mo * (12 - rent_free_months_per_year) / 12
    return _gate(effective, "유효임대료")


def region_params() -> dict:
    """권역별 렌트프리 관행(개월/년)과 그 출처·유보.

    키는 R-ONE 상업용부동산 임대동향조사의 권역 명칭(도심·강남·여의도마포)을
    그대로 쓴다. CBD/GBD/YBD 코드로 부르지 않는다 — 코드↔명칭 매핑은
    `data/seed_buildings.json` 의 `meta.rone_region` 에 있고, 그 매핑 자체가
    근사다(여의도마포는 마포를 포함한 합성 권역).

    값은 골든 상수가 아니라 **조정 가능한 가정**이다. 호출할 때마다 새
    사전을 만들어 돌려주므로 부르는 쪽이 고쳐도 다음 호출은 오염되지 않는다.
    """
    return {
        region: {"rent_free_mo": months}
        for region, months in _REGION_RENT_FREE_MO.items()
    } | {
        "_meta": {
            "unit": "개월/년",
            "source": (
                "공개 시장 보고서들의 관행 수준을 반영한 가정값, "
                "리츠 앵커 캘리브레이션으로 조정 예정"
            ),
            "caveat": (
                "권역 대표값 한 숫자로 개별 계약의 렌트프리를 대신한 것이다. "
                "실제 렌트프리는 같은 권역 안에서도 공실률·신축 공급·임차인 "
                "신용도에 따라 갈리고 경기 국면에 따라 움직인다. 값을 확정된 "
                "관측치로 인용하지 말고, 리츠 실적 임대수익 앵커에 맞추는 "
                "캘리브레이션의 초기값으로만 쓰라. 권역 명칭은 R-ONE 기준이며 "
                "seed_buildings.meta.rone_region 매핑은 근사다."
            ),
        }
    }


def building_adjust(
    base: float,
    age_years: float,
    gfa_m2: float,
    dist_subway_m: float | None,
) -> dict:
    """건물 세 특성(연식·규모·역세권)으로 기준임대료를 보정한다.

    보정값 = base × 연식계수 × 규모계수 × 역세권계수 (세 계수는 곱으로 겹친다)

    | 특성   | 구간                    | 계수 |
    |--------|-------------------------|------|
    | 연식   | 0~10년                  | 1.06 |
    |        | 10~20년                 | 1.00 |
    |        | 20~30년                 | 0.94 |
    |        | 30년+                   | 0.88 |
    | 연면적 | 10만㎡+                 | 1.08 |
    |        | 5만~10만㎡              | 1.04 |
    |        | 3만~5만㎡               | 1.00 |
    |        | 3만㎡ 미만              | 0.96 |
    | 역세권 | 400m 이내               | 1.03 |
    |        | 400m 초과 / 모름        | 1.00 |

    구간 경계는 [하한, 상한) 반열림이다(정확히 10년은 10~20년 구간).

    반환: `{"value": 보정임대료, "factors": {"age", "scale", "subway"},
    "assumptions": [...], "caveats": [...]}`. 보정 결과도 물리 게이트를
    통과해야 한다.
    """
    if age_years < 0:
        raise ValueError(f"연식은 음수일 수 없다: {age_years}")
    if gfa_m2 <= 0:
        raise ValueError(f"연면적은 양수여야 한다: {gfa_m2}")
    if dist_subway_m is not None and dist_subway_m < 0:
        raise ValueError(f"역까지 거리는 음수일 수 없다: {dist_subway_m}")

    age = _pick(_AGE_FACTORS, age_years)
    scale = _pick(_SCALE_FACTORS, gfa_m2)
    if dist_subway_m is None:
        subway = 1.0
    else:
        subway = _SUBWAY_FACTOR if dist_subway_m <= _SUBWAY_RADIUS_M else 1.0

    value = _gate(base * age * scale * subway, "보정임대료")

    caveats = [
        "세 계수를 곱으로 겹쳤다 — 특성 간 상관(신축일수록 크고 역세권인 "
        "경향)을 무시했으므로 셋이 함께 좋은 건물은 프리미엄이 과대평가된다.",
        "계수 폭(±6%·±4%·+3%)은 시장 관행 수준의 가정이며 회귀로 추정한 "
        "값이 아니다. 리모델링 이력·공용부 효율·임차인 구성은 넣지 않았다.",
    ]
    if dist_subway_m is None:
        caveats.append(
            "역까지 거리를 몰라 역세권 계수를 1.0 으로 보류했다 — 400m 초과와 "
            "같은 값이지만 '역세권 아님'이 아니라 '판단 유보'다."
        )

    return {
        "value": value,
        "factors": {"age": age, "scale": scale, "subway": subway},
        "assumptions": [
            f"연식 {age_years}년 → {age}",
            f"연면적 {gfa_m2:,.0f}㎡ → {scale}",
            (
                "역까지 거리 모름 → 1.0"
                if dist_subway_m is None
                else f"역까지 {dist_subway_m:,.0f}m → {subway}"
            ),
            "구간 경계는 [하한, 상한) 반열림",
        ],
        "caveats": caveats,
    }
