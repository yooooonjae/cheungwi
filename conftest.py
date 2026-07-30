# pytest 루트 설정: 저장소 루트를 sys.path 에 올려 `src.*` 임포트를 가능하게 한다.
# (별도 설정 없이 `from src.collect import common` 형태로 임포트)
#
# 그리고 산출물 가드가 여기에 있다. 이 스위트의 상당수는 out/·data/ 의 **실물**을
# 읽어 검증한다 — 실물이 없으면 그 검사들은 오류로 무너지지만, 순수 함수 검사는
# 그대로 통과해서 "일부 초록"이라는 애매한 그림이 남는다. CI 에서는 그 애매함이
# 곧 거짓 초록이다. 그래서 `CHEUNGWI_REQUIRE_ARTIFACTS=1` 인 세션은 산출물이 하나라도
# 없으면 **한 건도 돌기 전에** 끝난다(부재는 skip 이 아니라 실패다).
#
# 로컬에서 산출물 없이 순수 함수만 돌려 보는 길은 막지 않는다 — 가드는 환경변수를
# 켠 세션에서만 선다.

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# 저장소에 커밋돼 있어야 하는 산출물. checkout 만으로 실측이 되는 것이 계약이다.
REQUIRED_ARTIFACTS = (
    "out/market.json",
    "out/underwriting.json",
    "out/trades_analysis.json",
    "out/pf_case.json",
    "data/DATA_MANIFEST.json",
    "site/static/og.png",
)


def missing_artifacts(root=ROOT):
    """없는 산출물의 상대 경로 목록. 선언 순서를 그대로 지킨다."""
    return [rel for rel in REQUIRED_ARTIFACTS if not (Path(root) / rel).is_file()]


def pytest_sessionstart(session):
    if os.environ.get("CHEUNGWI_REQUIRE_ARTIFACTS") != "1":
        return
    missing = missing_artifacts()
    if missing:
        raise pytest.UsageError(
            "산출물 %d건 부재: %s — CHEUNGWI_REQUIRE_ARTIFACTS=1 인 세션은 "
            "건너뛰지 않고 여기서 멈춘다. make analyze·make manifest·make og 를 "
            "돌렸는지, 그 산출을 커밋했는지 보라."
            % (len(missing), " · ".join(missing)))
