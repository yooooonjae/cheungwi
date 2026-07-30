"""파이썬 엔진 ↔ 자바스크립트 미러(`site/js/engine.js`) 패리티 검증.

대시보드 Ⅱ장·실험실은 슬라이더를 움직일 때마다 같은 계산을 브라우저에서 다시
돌린다. 그 자바스크립트 판이 파이썬 원본과 조금이라도 다르면 화면의 숫자와
`out/*.json` 의 숫자가 어긋나고, 어느 쪽이 맞는지는 아무도 모르게 된다. 그래서
아홉 함수를 무작위 입력으로 나란히 돌려 원소 단위로 대조한다.

**파이썬이 원본이다.** 불일치가 나오면 고칠 쪽은 언제나 자바스크립트다.

대조 규모
  · 무작위·경계 유효 입력 9함수 × 23조 = 207조
  · 골든 5종(G-NOI-001·G-LOAN-001·G-HOLD-001·G-REFI-001·G-BEV-001)
  · 오류 매핑 케이스(게이트·입력·미구현 세 갈래)

비교 규칙
  · 수치: `math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)`
  · None ↔ null: 양쪽 모두 None 일 때만 일치
  · 불리언·문자열: 완전 일치. dict 는 키집합까지, list 는 길이까지 같아야 한다.
  · 오류: 예외 유형의 **갈래**(gate·input·not_implemented)만 대조한다. 메시지
    본문은 대조하지 않는다 — 두 언어의 수치 표기 관행이 달라서다(아래 참조).

**node 가 없으면 건너뛰지 않고 실패한다.** 패리티는 CI 계약이라, 러너가 없어
검증이 통째로 사라지는 편이 어긋난 값이 나가는 것보다 나을 이유가 없다.

입력 생성의 규약이 하나 있다 — **문자열로 보간되는 인자는 파이썬 float 로
만든다**(정수 리터럴 금지). 반환 dict 의 `notes`·`assumptions` 는 인자를 문구에
그대로 박아 넣는데, 파이썬은 `str(0.5)`·`str(5.0)` 을 "0.5"·"5.0" 으로 쓰고
자바스크립트 `String(5)` 는 "5" 다. 미러는 파이썬 `repr` 규칙을 그대로 옮겨
정수값 float 도 "5.0" 으로 쓰므로, **JSON 을 건너가며 float 인 채로 남는 값**은
양쪽이 같아진다. 반대로 파이썬 **int** 를 넘기면 파이썬만 "5" 를 써서 어긋난다.
`{x:,.0f}` 같은 서식 자리에만 쓰이는 인자(임대료·연면적·금액)는 int 여도 안전해
골든은 원본 테스트의 정수 리터럴을 그대로 쓴다.

같은 이유로 **`hold_years` 는 JSON 경계에서 int/float 구분이 사라진다.**
파이썬은 `5.0` 을 정수가 아니라며 거절하지만 자바스크립트는 `5.0` 과 `5` 를
구분할 수 없어 통과시킨다. 언어가 아니라 표현 형식의 한계라 미러의 결함이
아니고, 소수 연수(`5.5`)는 양쪽 다 거절하는 것으로 대신 고정한다.
"""

import json
import math
import os
import random
import shutil
import subprocess

import pytest

from src.analysis.acquisition import hold_model, max_loan
from src.analysis.caprate import CAP_MAX, CAP_MIN, implied
from src.analysis.effective_rent import (
    _AGE_FACTORS,
    _SCALE_FACTORS,
    _SUBWAY_FACTOR,
    _SUBWAY_RADIUS_M,
    _pick,
    building_adjust,
    effective_rent,
)
from src.analysis.noi import noi
from src.analysis.refi import breakeven_vacancy, refi_test
from src.analysis.value import appraise

NODE = shutil.which("node")
RUNNER = os.path.abspath(os.path.join(os.path.dirname(__file__), "parity_runner.js"))
ENGINE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "site", "js", "engine.js")
)

REL_TOL = 1e-9
ABS_TOL = 1e-6
N_PER_FN = 23

FUNCTIONS = {
    "effective_rent": effective_rent,
    "building_adjust": building_adjust,
    "noi": noi,
    "appraise": appraise,
    "implied": implied,
    "max_loan": max_loan,
    "hold_model": hold_model,
    "refi_test": refi_test,
    "breakeven_vacancy": breakeven_vacancy,
}


# --------------------------------------------------------------------------- #
# 입력 생성 — 유효 도메인 안의 경계 + 무작위
# --------------------------------------------------------------------------- #
def _ba(target, age, gfa, dist):
    """`building_adjust` 인자. 보정 결과가 게이트 안에 떨어지도록 base 를 역산한다.

    세 계수의 곱을 미리 알 수 없으면 base 를 그냥 뽑았을 때 결과가 물리 범위를
    벗어나 게이트에 걸린다 — 그러면 유효 도메인 표본이 아니라 오류 표본이 된다.
    """
    subway = 1.0 if dist is None else (_SUBWAY_FACTOR if dist <= _SUBWAY_RADIUS_M else 1.0)
    factor = _pick(_AGE_FACTORS, age) * _pick(_SCALE_FACTORS, gfa) * subway
    return [target / factor, age, gfa, dist]


def _bounds():
    """함수별 경계·특수 입력. 무작위가 좀처럼 밟지 않는 자리를 명시로 고정한다."""
    return {
        "effective_rent": [
            [10_000.0, 0.0],                 # 게이트 하한 정확히
            [60_000.0, 0.0],                 # 게이트 상한 정확히
            [12_000.0, 2.0],                 # 렌트프리 차감 후 하한
            [72_000.0, 2.0],                 # 렌트프리 차감 후 상한
            [3_600_000.0, 11.9],             # 렌트프리 상한 근처(차감 후 30,000)
        ],
        "building_adjust": [
            _ba(25_000.0, 10.0, 40_000.0, 400.0),      # 연식·역세권 경계 정확히
            _ba(25_000.0, 20.0, 30_000.0, 400.0001),   # 역세권 경계 바로 밖
            _ba(25_000.0, 30.0, 50_000.0, None),       # 거리 모름
            _ba(25_000.0, 0.0, 100_000.0, 0.0),        # 신축·10만㎡·역 앞
            _ba(25_000.0, 44.5, 29_999.9, 1_200.0),    # 최고 감가·최소 규모
            _ba(10_000.0, 12.5, 60_000.0, None),       # 게이트 하한에 붙인 결과
            _ba(60_000.0, 12.5, 60_000.0, None),       # 게이트 상한에 붙인 결과
            # 아래 여섯은 값이 아니라 **문구의 수치 표기**를 겨눈다. 연식은 문구에
            # 파이썬 `repr` 로 박히고(지수 전환 경계 −4·16), 연면적·거리는
            # `f"{x:,.0f}"` 로 박힌다. 통상 입력은 전부 소수 두어 자리라 표기
            # 규칙이 어긋나도 드러나지 않는다.
            _ba(25_000.0, 1e15, 12_345_678.9, 987_654.3),   # repr 소수점 유지 경계
            _ba(25_000.0, 1e16, 1e15, 1e12),                # repr 지수 전환 경계
            _ba(25_000.0, 0.0001, 40_000.0, 0.4),           # repr 지수 전환 직전
            _ba(25_000.0, 0.00001, 40_000.0, 0.5),          # repr 지수 전환 직후
            _ba(25_000.0, 1.5e-7, 40_000.0, 1_234.5),       # 지수 두 자리 표기
            _ba(25_000.0, 0.1 + 0.2, 999.5, 1_000.5),       # 17자리 유효숫자·반올림 경계
        ],
        "noi": [
            [10_000.0, 1_000.0, 1.0, 0.0, 0.0],          # 전 경계 최소
            [60_000.0, 300_000.0, 1.0, 0.0, 0.0],        # 임대료 상한·전용률 1
            [25_000.0, 100_000.0, 0.5, 1.0, 0.15],       # 공실 100% → NOI 0
            [25_000.0, 100_000.0, 0.5, 0.05, 0.999],     # opex 상한 근처
        ],
        "appraise": [
            [0.0, 0.02],                     # NOI 0 → 가치 0
            [0.0, 0.12],
            [1.2e10, 0.02],                  # cap 게이트 양끝
            [1.2e10, 0.12],
        ],
        "implied": [
            [2e9, 1e11],                     # cap 정확히 0.02
            [1.2e10, 1e11],                  # cap 정확히 0.12
            [1.0, 50.0],                     # 자릿수가 작아도 cap 은 0.02
        ],
        "max_loan": [
            [0.0, 1e11, 0.55, 1.3, 0.08, 0.045],       # NOI 0 → 소득 제약 동률(binding=dscr)
            [1.2e10, 1e11, 1.0, 5.0, 1.0, 1.0],        # 전 인자 상한(DSCR 게이트 끝)
            [1.2e10, 2.7e11, 0.55, 1.3, 0.08, 0.045],  # 통상 구간(ltv 결속)
            [5e11, 1e10, 0.55, 1.3, 0.08, 0.045],      # 소득이 커서 ltv 결속
        ],
        "hold_model": [
            [1e11, 0.0, 0.04, 4.5e9, 0.0, 0.045, 5, 0.05],      # 무차입
            [1e11, 1e11, 0.04, 4.5e9, 0.0, 0.045, 5, 0.0],      # 대출=가격·비용 0 → 지분 0
            [1e11, 5.5e10, 0.0, 4.5e9, 0.0, 0.045, 1, 0.0],     # 금리 0·1년·비용 0
            [1e11, 5.5e10, 0.04, 0.0, 0.0, 0.045, 5, 0.05],     # NOI 0
            [1e11, 5.5e10, 0.04, 4.5e9, 1.0, 0.045, 3, 0.05],   # 성장률 상한
            [1e11, 5.5e10, 0.04, 4.5e9, -0.999, 0.12, 4, 0.05], # 성장률 하한 근처·cap 상한
            [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.02, 15, 0.05],   # cap 하한·장기 보유
            # 아래 둘은 이분법 **구간 자체**를 겨눈다. 위 케이스들의 근은 전부
            # 0 부근이라 탐색 구간을 [−0.4, 1.0] 으로 좁혀도 같은 근으로 수렴해
            # 어긋남이 드러나지 않는다.
            [1e11, 0.0, 0.0, 1e9, 0.0, 0.12, 1, 0.0],    # 분기 근 −0.455(구간 하단)
            [1.6e11, 0.0, 0.0, 1e9, 0.0, 0.12, 1, 0.0],  # 근이 구간 아래로 벗어남 → None
            [1.44e10, 0.0, 0.0, 1e10, 0.0, 0.02, 1, 0.0],  # 근이 구간 위로 벗어남 → None
            # 전 원소가 0 인 흐름 — 부호 변화가 없다는 판정이 **0 밖에 없는 흐름**을
            # 먼저 걸러야 한다. `flo == 0` 분기로 새면 IRR 이 −0.9375 로 지어진다.
            [1e11, 1e11, 0.045, 4.5e9, 0.0, 0.045, 5, 0.0],
            # 아래 둘은 **기본 인자**를 겨눈다. 여덟 인자를 늘 다 넘기면 미러의
            # 기본값(hold_years 5·cost_rate 0.05)이 한 번도 실행되지 않아, 파이썬
            # 쪽 기본값이 바뀌어도 스위트가 초록인 채 화면만 어긋난다. 러너는
            # `apply` 로 넘기므로 짧은 배열이 그대로 기본값 경로를 탄다.
            [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045],          # 여섯 인자 → 기본값 둘 다
            [2.7e11, 1.485e11, 0.045, 1.2e10, 0.02, 0.05, 7],  # 일곱 인자 → cost_rate 기본
        ],
        "refi_test": [
            [0.0, 1e11, 2.7e11, 1.3, 0.6, 0.05],        # NOI 0 → max_rate 0 → 부결
            [1.2e10, 1.485e11, 2.7e11, 1.3, 0.6, 0.0],  # 시장금리 0 → dscr_at_market None
            [1.2e10, 1485.0, 2.7e11, 1.3, 0.6, 0.05],   # implausible 두 사유 동시
            [1.2e10, 3e11, 2.7e11, 1.3, 0.6, 0.05],     # 대출 > 가치(막지 않는다)
            [1.2e10, 1e11, 2.7e11, 5.0, 1.0, 1.0],      # DSCR 게이트 끝·전 한도 최대
            # 차환 LTV 를 2 의 거듭제곱 분수로 떨어뜨려 문구의 반올림을 겨눈다.
            # 파이썬 서식은 정확히 반이면 짝수 쪽으로 붙이고 `toFixed` 는 큰 쪽으로
            # 붙는다 — 1/32 는 `.4f`, 1/128 은 `.6f` 자리에서 정확히 반이다.
            [1.2e10, 1e10, 3.2e11, 1.3, 0.6, 0.05],     # ltv 0.03125 → .4f 반값
            [1.2e10, 1e9, 1.28e11, 1.3, 0.6, 0.05],     # ltv 0.0078125 → .6f 반값
            # 두 관문의 등호를 겨눈다 — 금리는 **초과**여야 하고(여유 0 은 부결)
            # LTV 는 **이하**면 된다(한도에 붙어도 약정 준수). 반대로 읽으면
            # `acquisition` 이 승인한 DSCR 결속 대출이 여기서도 통과해 버린다.
            [1e10, 2e11, 1e12, 1.0, 0.6, 0.05],         # max_rate 정확히 0.05 → 부결
            [1.2e10, 1e11, 2e11, 1.3, 0.5, 0.05],       # 대출 = 한도 정확히 → 통과
        ],
        "breakeven_vacancy": [
            [25_000.0, 100_000.0, 0.5, 0.15, 0.0, 0.06, 1.3],    # 대출 0 → 1.0
            [25_000.0, 100_000.0, 0.5, 0.15, 1.485e11, 0.0, 1.3],  # 금리 0 → 1.0
            [25_000.0, 100_000.0, 0.5, 0.15, 5e11, 0.15, 5.0],   # 이미 불가 → 0 으로 절단
            [10_000.0, 1_000.0, 1.0, 0.0, 1e8, 0.06, 0.1],       # 게이트 하한·opex 0
            [60_000.0, 300_000.0, 1.0, 0.0, 1e10, 0.06, 5.0],    # 게이트 상한·DSCR 끝
        ],
    }


def _randoms(rng):
    """함수별 무작위 유효 입력 한 조씩. 호출 순서가 곧 시드 소비 순서다."""
    return {
        "effective_rent": lambda: _rand_effective_rent(rng),
        "building_adjust": lambda: _rand_building_adjust(rng),
        "noi": lambda: _rand_noi(rng),
        "appraise": lambda: _rand_appraise(rng),
        "implied": lambda: _rand_implied(rng),
        "max_loan": lambda: _rand_max_loan(rng),
        "hold_model": lambda: _rand_hold_model(rng),
        "refi_test": lambda: _rand_refi_test(rng),
        "breakeven_vacancy": lambda: _rand_breakeven_vacancy(rng),
    }


def _rand_effective_rent(rng):
    """렌트프리 차감 후가 게이트 안이 되도록 명목임대료를 역산한다."""
    rent_free = rng.uniform(0.0, 11.5)
    effective = rng.uniform(10_500.0, 59_500.0)
    return [effective * 12 / (12 - rent_free), rent_free]


# 표기가 까다로운 값들 — 2 의 거듭제곱 분수(정확히 반이 되어 반올림 방향이
# 갈린다)와 지수 표기 경계. 무작위 실수는 이 자리를 거의 밟지 않는다.
_TRICKY = (
    0.5, 1.5, 2.5, 0.125, 0.375, 999.5, 1_000.5, 12_345.5, 0.0078125,
    1e-4, 1e-5, 1.5e-7, 1e15, 1e16, 0.1 + 0.2, 1 / 3,
    # 1e21 부터는 `toFixed` 가 지수 표기로 새어 나간다 — 파이썬은 자릿수를
    # 그대로 펼치므로 미러가 따로 손봐야 하는 구간이다.
    1e21, 1.5e22,
)


def _rand_building_adjust(rng):
    """연식은 문구에 `repr` 로, 연면적·거리는 `f"{x:,.0f}"` 로 박힌다.

    보정값 자체보다 **문구의 수치 표기**가 어긋나기 쉬운 자리라, 넷 중 하나는
    표기가 까다로운 값에서 뽑는다.
    """
    def draw(lo, hi):
        return rng.choice(_TRICKY) if rng.random() < 0.25 else rng.uniform(lo, hi)

    age = draw(0.0, 45.0)
    gfa = draw(5_000.0, 250_000.0)
    dist = None if rng.random() < 0.2 else draw(30.0, 1_500.0)
    return _ba(rng.uniform(11_000.0, 55_000.0), age, gfa, dist)


def _rand_noi(rng):
    return [
        rng.uniform(10_000.0, 60_000.0),
        rng.uniform(1_000.0, 300_000.0),
        rng.uniform(0.15, 1.0),
        rng.uniform(0.0, 1.0),
        rng.uniform(0.0, 0.9),
    ]


def _rand_appraise(rng):
    return [rng.uniform(0.0, 5e11), rng.uniform(CAP_MIN, CAP_MAX)]


def _rand_implied(rng):
    """역산 cap 이 게이트 안이 되도록 가격을 NOI 와 cap 에서 되돌린다."""
    noi_won_y = rng.uniform(1e9, 5e11)
    return [noi_won_y, noi_won_y / rng.uniform(0.021, 0.119)]


def _rand_max_loan(rng):
    return [
        rng.uniform(0.0, 5e11),
        rng.uniform(1e10, 1e12),
        rng.uniform(0.05, 1.0),
        rng.uniform(0.1, 5.0),
        rng.uniform(0.01, 1.0),
        rng.uniform(0.005, 1.0),
    ]


def _rand_hold_model(rng):
    price = rng.uniform(1e10, 5e11)
    return [
        price,
        price * rng.uniform(0.0, 1.0),
        rng.uniform(0.0, 0.15),
        rng.uniform(0.0, price * 0.1),
        rng.uniform(-0.2, 0.2),
        rng.uniform(CAP_MIN, CAP_MAX),
        rng.randint(1, 15),
        rng.uniform(0.0, 0.2),
    ]


def _rand_refi_test(rng):
    """대출 > 가치도 유효 도메인이다 — 그 판정이 이 함수의 목적이라 막지 않는다."""
    value = rng.uniform(1e10, 1e12)
    return [
        rng.uniform(0.0, 1e11),
        value * rng.uniform(0.05, 1.4),
        value,
        rng.uniform(0.1, 5.0),
        rng.uniform(0.05, 1.0),
        rng.uniform(0.0, 0.2),
    ]


def _rand_breakeven_vacancy(rng):
    return [
        rng.uniform(10_000.0, 60_000.0),
        rng.uniform(1_000.0, 300_000.0),
        rng.uniform(0.15, 1.0),
        rng.uniform(0.0, 0.9),
        rng.uniform(0.0, 5e11),
        rng.uniform(0.0, 0.15),
        rng.uniform(0.1, 5.0),
    ]


# 골든 5종 — 원본 골든 테스트의 인자를 축자로 옮긴다. 성장률만 `0.0` 으로 적는다
# (int 0 은 문구에 "0" 으로 박혀 미러의 "0.0" 과 어긋난다 — 모듈 독스트링 참조).
GOLDENS = [
    ("G-NOI-001", "noi", [25_000, 100_000, 0.5, 0.05, 0.15]),
    ("G-LOAN-001", "max_loan", [12_112_500_000, 270_000_000_000, 0.55, 1.3, 0.08, 0.045]),
    ("G-HOLD-001", "hold_model", [100e9, 55e9, 0.04, 4.5e9, 0.0, 0.045, 5, 0.05]),
    ("G-REFI-001", "refi_test",
     [12_112_500_000, 148_500_000_000, 270_000_000_000, 1.3, 0.60, 0.05]),
    ("G-BEV-001", "breakeven_vacancy",
     [25_000, 100_000, 0.5, 0.15, 148_500_000_000, 0.06, 1.3]),
]

# 오류 매핑 — (함수, 인자, 기대 갈래). 파이썬 ValueError→input,
# RuntimeError→gate, NotImplementedError→not_implemented 에 자바스크립트
# TypeError·RangeError·Error("미구현 …") 가 각각 대응해야 한다.
ERROR_CASES = [
    ("effective_rent", [5_000.0, 0.0], "gate"),
    ("effective_rent", [9_999.99, 0.0], "gate"),     # 게이트 하한 바로 밑
    ("effective_rent", [60_000.01, 0.0], "gate"),    # 게이트 상한 바로 위
    ("effective_rent", [30_000.0, 12.0], "gate"),
    ("effective_rent", [30_000.0, 13.0], "input"),
    ("effective_rent", [30_000.0, -1.0], "input"),
    ("building_adjust", [25_000.0, -1.0, 40_000.0, None], "input"),
    ("building_adjust", [25_000.0, 5.0, 0.0, None], "input"),
    ("building_adjust", [25_000.0, 5.0, 40_000.0, -1.0], "input"),
    ("building_adjust", [9_000.0, 15.0, 40_000.0, None], "gate"),
    ("noi", [25_000.0, 100_000.0, 0.0, 0.0, 0.0], "input"),
    ("noi", [25_000.0, 100_000.0, 1.5, 0.0, 0.0], "input"),
    ("noi", [25_000.0, 100_000.0, 0.5, 1.5, 0.0], "input"),
    ("noi", [25_000.0, 100_000.0, 0.5, 0.0, 1.0], "input"),
    ("noi", [25_000.0, 0.0, 0.5, 0.0, 0.0], "input"),
    ("noi", [0.0, 100_000.0, 0.5, 0.0, 0.0], "input"),
    ("noi", [5_000.0, 100_000.0, 0.5, 0.0, 0.0], "gate"),
    ("noi", [9_999.99, 100_000.0, 0.5, 0.0, 0.0], "gate"),
    ("noi", [60_000.01, 100_000.0, 0.5, 0.0, 0.0], "gate"),
    ("noi", [70_000.0, 100_000.0, 0.5, 0.0, 0.0], "gate"),
    ("appraise", [-1.0, 0.045], "input"),
    ("appraise", [1.2e10, 4.5], "gate"),
    ("appraise", [1.2e10, 0.0045], "gate"),
    ("appraise", [1.2e10, 0.015], "gate"),           # cap 게이트 하한 바로 밑
    ("appraise", [1.2e10, 0.125], "gate"),           # cap 게이트 상한 바로 위
    ("implied", [1.2e10, 0.0], "input"),
    ("implied", [-1.0, 1e11], "input"),
    ("implied", [0.0, 1e11], "gate"),
    ("implied", [1e11, 1e11], "gate"),
    ("implied", [1.5e9, 1e11], "gate"),              # 역산 cap 0.015
    ("implied", [1.25e10, 1e11], "gate"),            # 역산 cap 0.125
    ("max_loan", [1.2e10, 1e11, 0.55, 1.3, 0.08, 0.045, False], "not_implemented"),
    ("max_loan", [-1.0, 1e11, 0.55, 1.3, 0.08, 0.045], "input"),
    ("max_loan", [1.2e10, 0.0, 0.55, 1.3, 0.08, 0.045], "input"),
    ("max_loan", [1.2e10, 1e11, 1.5, 1.3, 0.08, 0.045], "input"),
    ("max_loan", [1.2e10, 1e11, 0.55, 1.3, 1.5, 0.045], "input"),
    ("max_loan", [1.2e10, 1e11, 0.55, 1.3, 0.08, 0.0], "input"),
    ("max_loan", [1.2e10, 1e11, 0.55, 6.0, 0.08, 0.045], "gate"),
    ("max_loan", [1.2e10, 1e11, 0.55, -1.0, 0.08, 0.045], "gate"),
    ("max_loan", [1.2e10, 1e11, 0.55, 5.0001, 0.08, 0.045], "gate"),  # DSCR 게이트 끝 바로 위
    ("max_loan", [1.2e10, 1e11, 0.55, 0.0, 0.08, 0.045], "input"),
    ("hold_model", [0.0, 0.0, 0.04, 4.5e9, 0.0, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, -1.0, 0.04, 4.5e9, 0.0, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 2e11, 0.04, 4.5e9, 0.0, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 1.5, 4.5e9, 0.0, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, -1.0, 0.0, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 1.5, 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045, 5.5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045, 0, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045, 5, 1.0], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.2, 5, 0.05], "gate"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.015, 5, 0.05], "gate"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.125, 5, 0.05], "gate"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045, True, 0.05], "input"),
    ("refi_test", [-1.0, 1e11, 2.7e11, 1.3, 0.6, 0.05], "input"),
    ("refi_test", [1.2e10, 0.0, 2.7e11, 1.3, 0.6, 0.05], "input"),
    ("refi_test", [1.2e10, 1e11, 0.0, 1.3, 0.6, 0.05], "input"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, 1.3, 1.5, 0.05], "input"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, 1.3, 0.6, 1.5], "input"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, 6.0, 0.6, 0.05], "gate"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, 5.0001, 0.6, 0.05], "gate"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, -0.0001, 0.6, 0.05], "gate"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, 0.0, 0.6, 0.05], "input"),
    ("breakeven_vacancy", [0.0, 1e5, 0.5, 0.15, 1e11, 0.06, 1.3], "input"),
    ("breakeven_vacancy", [25_000.0, 0.0, 0.5, 0.15, 1e11, 0.06, 1.3], "input"),
    ("breakeven_vacancy", [25_000.0, 1e5, 1.5, 0.15, 1e11, 0.06, 1.3], "input"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 1.0, 1e11, 0.06, 1.3], "input"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, -1.0, 0.06, 1.3], "input"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, 1e11, 1.5, 1.3], "input"),
    ("breakeven_vacancy", [5_000.0, 1e5, 0.5, 0.15, 1e11, 0.06, 1.3], "gate"),
    ("breakeven_vacancy", [9_999.99, 1e5, 0.5, 0.15, 1e11, 0.06, 1.3], "gate"),
    ("breakeven_vacancy", [60_000.01, 1e5, 0.5, 0.15, 1e11, 0.06, 1.3], "gate"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, 1e11, 0.06, 6.0], "gate"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, 1e11, 0.06, 5.0001], "gate"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, 1e11, 0.06, 0.0], "input"),
    # 유한성 가드 — NaN 은 크기 비교가 전부 거짓이라 도메인 검사와 게이트를
    # 조용히 통과하고, ±무한대는 상한 검사가 없는 인자를 그대로 지나간다.
    # 둘 다 정상 실수처럼 생겨서 하류가 잡지 못하므로 진입에서 막아야 한다.
    ("effective_rent", ["__nan__", 0.0], "input"),
    ("effective_rent", ["__inf__", 0.0], "input"),
    ("building_adjust", [25_000.0, "__nan__", 40_000.0, None], "input"),
    ("building_adjust", [25_000.0, 12.5, "__inf__", None], "input"),
    ("building_adjust", [25_000.0, 12.5, 40_000.0, "__nan__"], "input"),
    ("noi", ["__nan__", 1e5, 0.5, 0.05, 0.15], "input"),
    ("noi", [25_000.0, 1e5, "__nan__", 0.05, 0.15], "input"),
    ("noi", [25_000.0, 1e5, 0.5, "__inf__", 0.15], "input"),
    ("appraise", [1.2e10, "__nan__"], "input"),
    ("implied", ["__inf__", 1e11], "input"),
    ("max_loan", [1.2e10, 1e11, 0.55, "__nan__", 0.08, 0.045], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, "__nan__", 0.045, 5, 0.05], "input"),
    ("hold_model", [1e11, 5.5e10, 0.04, 4.5e9, 0.0, 0.045, "__nan__", 0.05], "input"),
    ("refi_test", [1.2e10, 1e11, 2.7e11, "__inf__", 0.6, 0.05], "input"),
    ("breakeven_vacancy", [25_000.0, 1e5, 0.5, 0.15, "__nan__", 0.06, 1.3], "input"),
]


def make_inputs():
    """시드 42 로 유효 207조 + 골든 5조 + 오류 케이스를 이 순서로 만든다."""
    rng = random.Random()
    rng.seed(42)
    bounds = _bounds()
    makers = _randoms(rng)

    cases = []
    for name in FUNCTIONS:
        args_list = list(bounds[name])
        while len(args_list) < N_PER_FN:
            args_list.append(makers[name]())
        for args in args_list[:N_PER_FN]:
            cases.append({"fn": name, "args": args})

    for _id, name, args in GOLDENS:
        cases.append({"fn": name, "args": args})
    for name, args, _kind in ERROR_CASES:
        cases.append({"fn": name, "args": args})
    return cases


INPUTS = make_inputs()
N_VALID = N_PER_FN * len(FUNCTIONS)
N_GOLDEN = len(GOLDENS)
N_ERROR = len(ERROR_CASES)
GOLDEN_AT = {gid: N_VALID + i for i, (gid, _fn, _args) in enumerate(GOLDENS)}


# --------------------------------------------------------------------------- #
# 실행 — 파이썬은 직접, 자바스크립트는 node 러너 한 프로세스로 왕복
# --------------------------------------------------------------------------- #
SENTINELS = {"__nan__": float("nan"), "__inf__": float("inf"), "__-inf__": float("-inf")}


def _decode(args):
    """NaN·±무한대 표식을 실제 값으로 되돌린다(러너와 같은 규약)."""
    return [SENTINELS[a] if isinstance(a, str) and a in SENTINELS else a for a in args]


def run_py(case):
    """파이썬 결과를 러너와 같은 봉투로 감싼다.

    **NotImplementedError 를 RuntimeError 보다 먼저 잡는다** — 전자가 후자의
    하위형이라 순서를 뒤집으면 "계산 불가"가 "단위 오류"로 뭉개진다.
    """
    try:
        return {"ok": True, "value": FUNCTIONS[case["fn"]](*_decode(case["args"]))}
    except NotImplementedError as exc:
        return {"ok": False, "error": "not_implemented", "message": str(exc)}
    except RuntimeError as exc:
        return {"ok": False, "error": "gate", "message": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error": "input", "message": str(exc)}


def run_node(cases):
    if NODE is None:
        raise RuntimeError(
            "node 를 찾을 수 없다 — 패리티 테스트는 건너뛰지 않는다. 러너가 없어 "
            "검증이 사라지는 것이 어긋난 값이 나가는 것보다 나을 이유가 없다"
        )
    if not os.path.isfile(ENGINE):
        raise RuntimeError(f"미러가 없다: {ENGINE}")
    proc = subprocess.run(
        [NODE, RUNNER],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("node 러너 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)


PY_RESULTS = [run_py(case) for case in INPUTS]

_JS_CACHE = {}


def js_results():
    if "value" not in _JS_CACHE:
        _JS_CACHE["value"] = run_node(INPUTS)
    return _JS_CACHE["value"]


# --------------------------------------------------------------------------- #
# 비교
# --------------------------------------------------------------------------- #
WORST = {"rel": 0.0, "path": "―"}


def _compare(py, js, path):
    """구조를 따라 내려가며 원소 단위로 대조한다."""
    if isinstance(py, bool) or isinstance(js, bool):
        assert isinstance(py, bool) and isinstance(js, bool), (
            f"{path}: 불리언 유형 불일치 py={py!r} js={js!r}"
        )
        assert py == js, f"{path}: 불리언 불일치 py={py!r} js={js!r}"
        return
    if py is None or js is None:
        assert py is None and js is None, f"{path}: None 불일치 py={py!r} js={js!r}"
        return
    if isinstance(py, str) or isinstance(js, str):
        assert py == js, f"{path}: 문자열 불일치\n  py={py!r}\n  js={js!r}"
        return
    if isinstance(py, dict) or isinstance(js, dict):
        assert isinstance(py, dict) and isinstance(js, dict), (
            f"{path}: dict 유형 불일치 py={type(py)} js={type(js)}"
        )
        assert set(py) == set(js), (
            f"{path}: 키집합 불일치 py-js={set(py) - set(js)} js-py={set(js) - set(py)}"
        )
        for key in py:
            _compare(py[key], js[key], f"{path}.{key}")
        return
    if isinstance(py, (list, tuple)) or isinstance(js, list):
        assert len(py) == len(js), f"{path}: 길이 불일치 py={len(py)} js={len(js)}"
        for i, (a, b) in enumerate(zip(py, js)):
            _compare(a, b, f"{path}[{i}]")
        return

    assert isinstance(py, (int, float)) and isinstance(js, (int, float)), (
        f"{path}: 수치 유형 불일치 py={py!r} js={js!r}"
    )
    scale = max(abs(py), abs(js))
    rel = abs(py - js) / scale if scale else 0.0
    if rel > WORST["rel"]:
        WORST["rel"], WORST["path"] = rel, path
    assert math.isclose(py, js, rel_tol=REL_TOL, abs_tol=ABS_TOL), (
        f"{path}: 수치 불일치 py={py!r} js={js!r} Δ={py - js!r}"
    )


def _compare_case(idx):
    py, js = PY_RESULTS[idx], js_results()[idx]
    path = f"case[{idx}]({INPUTS[idx]['fn']})"
    assert py["ok"] == js["ok"], (
        f"{path}: 성패 불일치 py={py} js={{'ok': {js['ok']}, "
        f"'error': {js.get('error')!r}}}"
    )
    if py["ok"]:
        _compare(py["value"], js["value"], path)
    else:
        assert py["error"] == js["error"], (
            f"{path}: 오류 갈래 불일치 py={py['error']} js={js['error']}\n"
            f"  py msg: {py['message']}\n  js msg: {js['message']}"
        )
        assert js["message"], f"{path}: 자바스크립트 오류에 문구가 없다"


# --------------------------------------------------------------------------- #
# 테스트
# --------------------------------------------------------------------------- #
def test_node_is_present_because_parity_never_skips():
    assert NODE is not None, (
        "node 가 없다 — 패리티는 건너뛰지 않고 실패한다(CI 계약)"
    )
    assert os.path.isfile(RUNNER), f"러너가 없다: {RUNNER}"
    assert os.path.isfile(ENGINE), f"미러가 없다: {ENGINE}"


def test_case_count_is_two_hundred_or_more():
    assert N_VALID >= 200, f"유효 도메인 표본이 200조에 못 미친다: {N_VALID}"
    assert len(INPUTS) == N_VALID + N_GOLDEN + N_ERROR
    assert len(PY_RESULTS) == len(INPUTS)
    assert len(js_results()) == len(INPUTS)
    assert set(INPUTS[i]["fn"] for i in range(N_VALID)) == set(FUNCTIONS)


@pytest.mark.parametrize("idx", range(len(INPUTS)))
def test_parity(idx):
    _compare_case(idx)


def test_valid_domain_samples_never_raised():
    """207조가 실제로 유효 도메인이었는지 — 오류로 새면 표본이 줄어든 것이다."""
    failed = [
        (i, INPUTS[i]["fn"], PY_RESULTS[i]["error"])
        for i in range(N_VALID)
        if not PY_RESULTS[i]["ok"]
    ]
    assert not failed, f"유효 표본이 오류를 냈다: {failed[:5]}"


def test_worst_relative_error_stays_under_tolerance():
    """전 케이스를 한 번 더 훑어 최대 상대오차를 기록한다(보고용 단일 숫자)."""
    WORST["rel"], WORST["path"] = 0.0, "―"
    for idx in range(len(INPUTS)):
        _compare_case(idx)
    assert WORST["rel"] <= REL_TOL, (
        f"최대 상대오차 {WORST['rel']:.3e} 가 허용 {REL_TOL:.0e} 를 넘었다 "
        f"({WORST['path']})"
    )


def test_error_kinds_are_all_three_branches():
    """게이트·입력·미구현 세 갈래가 실제로 다 검증되는지."""
    kinds = {kind for _fn, _args, kind in ERROR_CASES}
    assert kinds == {"gate", "input", "not_implemented"}
    for offset, (name, _args, kind) in enumerate(ERROR_CASES):
        idx = N_VALID + N_GOLDEN + offset
        assert PY_RESULTS[idx]["ok"] is False, f"{name} 이 오류를 내지 않았다"
        assert PY_RESULTS[idx]["error"] == kind, (
            f"{name}: 파이썬 오류 갈래가 기대와 다르다 "
            f"{PY_RESULTS[idx]['error']} ≠ {kind}"
        )


# ── 골든 재검(자바스크립트 쪽 단언) ─────────────────────────────────────

def _golden(gid):
    return js_results()[GOLDEN_AT[gid]]["value"]


def test_golden_noi_in_js():
    r = _golden("G-NOI-001")
    assert r["assumptions"]["nla_m2"] == 50_000.0
    assert r["egi_won_y"] == 14_250_000_000.0
    assert r["noi_won_y"] == 12_112_500_000.0


def test_golden_max_loan_in_js():
    r = _golden("G-LOAN-001")
    assert r["binding"] == "ltv"
    assert r["loan_won"] == 148_500_000_000.0
    assert r["by"]["debt_yield"] == 151_406_250_000.0
    assert abs(r["by"]["dscr"] - 207_051_282_051.28204) < 1e-3


def test_golden_hold_model_irr_in_js():
    """G-HOLD-001 의 연율 지분 IRR — 이분법 200회를 그대로 옮겼는지의 시금석."""
    r = _golden("G-HOLD-001")
    assert r["assumptions"]["cashflow_points"] == 21
    assert len(r["cashflows_q"]) == 21
    assert r["cashflows_q"][0] == -50_000_000_000.0
    assert r["cashflows_q"][1] == 575_000_000.0
    assert r["cashflows_q"][20] == 45_575_000_000.0
    assert r["exit_value"] == 100_000_000_000.0
    assert math.isclose(r["equity_irr"], 0.0275442936668497, rel_tol=1e-9)
    assert math.isclose(
        r["equity_irr"],
        PY_RESULTS[GOLDEN_AT["G-HOLD-001"]]["value"]["equity_irr"],
        rel_tol=0.0,
        abs_tol=0.0,
    )


def test_golden_refi_in_js():
    r = _golden("G-REFI-001")
    assert r["pass"] is True
    assert abs(r["max_rate"] - 0.0627428127) < 1e-9
    assert abs(r["headroom_bp"] - 127.428127) < 1e-4
    assert r["implausible"] is False
    assert r["implausible_reasons"] == []


def test_golden_breakeven_vacancy_in_js():
    assert abs(_golden("G-BEV-001") - 0.0915294118) < 1e-9


def test_engine_passes_node_syntax_check():
    proc = subprocess.run([NODE, "--check", ENGINE], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
