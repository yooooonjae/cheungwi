"""CI 계약 검사 — 무엇을 반드시 돌리고, 무엇을 절대 하지 않는가.

CI 는 사람이 안 볼 때 도는 유일한 검사다. 그래서 이 파일이 붙드는 것은 두 가지다.

  ① **조용한 통과를 만들지 않는다.** 산출물(out/·data/·og.png)이 없는 러너에서
     검사가 skip 으로 넘어가면 초록 체크는 "검사했다"가 아니라 "검사하지 않았다"는
     뜻이 된다. 산출물은 저장소에 커밋돼 있어야 하고(그래야 checkout 만으로 실측이
     가능하다), 그럼에도 없으면 `CHEUNGWI_REQUIRE_ARTIFACTS=1` 가 세션을 그 자리에서
     끝낸다.
  ② **CI 는 배포하지 않는다.** 배포는 로컬 `make refresh` 가 검증을 통과했을 때만
     한다. 워크플로에 wrangler 가 한 줄이라도 들어오면 초록 체크가 곧 배포가 되고,
     그때부터 "검증된 것만 나간다"는 순서가 뒤집힌다.

`make check` 는 이 워크플로의 로컬 동등물이다. 둘이 갈라지면 로컬 초록이 CI 초록을
보장하지 못하므로, 핵심 검사 넷이 양쪽에 다 있는지도 여기서 본다.
"""

import re
import subprocess
import sys
from pathlib import Path

import conftest

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = ROOT / "Makefile"


def ci_text():
    assert CI.is_file(), "CI 워크플로가 없다: %s" % CI
    return CI.read_text(encoding="utf-8")


def make_target(name):
    """Makefile 에서 타깃 하나의 레시피(탭으로 들여쓴 줄들)를 꺼낸다."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    body, seen = [], False
    for line in lines:
        if re.match(r"^%s:" % re.escape(name), line):
            seen = True
            continue
        if seen:
            if line.startswith("\t") or not line.strip():
                body.append(line)
            else:
                break
    assert seen, "Makefile 에 %s 타깃이 없다" % name
    return "\n".join(body)


# ------------------------------------------------------------------ #
# 문법 — PyYAML 없이 볼 수 있는 만큼은 본다
# ------------------------------------------------------------------ #
def test_the_workflow_is_yaml_shaped():
    text = ci_text()
    assert "\t" not in text, "YAML 에 탭이 들어가면 파서가 거부한다"
    top = {line.split(":")[0] for line in text.splitlines()
           if line and not line[0].isspace() and not line.startswith("#") and ":" in line}
    assert top <= {"name", "on", "env", "jobs", "permissions", "concurrency"}, \
        "모르는 최상위 키가 있다: %s" % top
    assert {"name", "on", "jobs"} <= top
    for line in text.splitlines():  # 들여쓰기는 2의 배수 — 손으로 어긋나면 파서가 죽는다
        indent = len(line) - len(line.lstrip(" "))
        assert indent % 2 == 0 or line.lstrip().startswith("#"), "홀수 들여쓰기: %r" % line


def test_the_workflow_runs_on_push_and_by_hand():
    text = ci_text()
    assert "runs-on: ubuntu-latest" in text
    for trigger in ("push:", "pull_request:", "workflow_dispatch:"):
        assert trigger in text, "%s 트리거가 없다" % trigger
    for action in ("actions/checkout@v", "actions/setup-python@v", "actions/setup-node@v"):
        assert action in text, "%s 가 없다" % action


# ------------------------------------------------------------------ #
# 무엇을 돌리는가 — 넷은 반드시 돈다
# ------------------------------------------------------------------ #
CORE_CHECKS = {
    "pytest": r"pytest tests/",       # 전체 스위트(패리티·조형 러너 포함 — node 필요)
    "node --check": r"node --check",  # 사이트 스크립트 문법
    "py_compile": r"py_compile",      # 파이썬 전 소스 바이트컴파일
    "assemble": r"src/build/assemble\.py",  # 빌드 게이트(미치환·조사 분리)
}


def test_the_workflow_runs_every_core_check():
    text = ci_text()
    for name, pattern in CORE_CHECKS.items():
        assert re.search(pattern, text), "CI 가 %s 를 돌리지 않는다" % name


def test_the_local_check_target_is_the_same_four():
    """`make check` 가 CI 의 로컬 동등물이 아니면 로컬 초록은 아무것도 보장하지 않는다."""
    recipe = make_target("check")
    for name, pattern in CORE_CHECKS.items():
        assert re.search(pattern, recipe), "make check 가 %s 를 돌리지 않는다" % name
    assert "CHEUNGWI_REQUIRE_ARTIFACTS=1" in recipe, \
        "로컬 검증만 가드 없이 돌면 CI 에서 처음 걸리는 부재가 생긴다"


def test_the_script_syntax_check_looks_at_every_file():
    """`node --check a.js b.js` 는 첫 파일만 본다 — 반드시 파일마다 돌려야 한다."""
    text = ci_text()
    assert re.search(r"for f in site/js/\*\.js", text), \
        "사이트 스크립트를 파일별로 돌지 않는다 — 둘째 파일부터는 검사되지 않는다"
    assert not re.search(r"node --check site/js/\*\.js", text)


def test_the_python_bytecompile_covers_every_source():
    """`src/*.py` 만 훑으면 하위 패키지가 통째로 빠진다 — find 로 전부 건다."""
    text = ci_text()
    assert re.search(r"find src -name '\*\.py'", text), \
        "py_compile 대상이 전 소스가 아니다"


# ------------------------------------------------------------------ #
# 무엇을 하지 않는가 — CI 는 배포하지 않는다
# ------------------------------------------------------------------ #
def test_the_workflow_never_deploys():
    text = ci_text()
    for forbidden in ("wrangler", "pages deploy", "secrets.", "make refresh", "make collect"):
        assert forbidden not in text, \
            "CI 에 %s 가 있다 — 배포와 수집은 로컬 refresh 의 몫이다" % forbidden


# ------------------------------------------------------------------ #
# 산출물 — 없으면 skip 이 아니라 실패다
# ------------------------------------------------------------------ #
def test_the_workflow_arms_the_artifact_guard():
    assert re.search(r'CHEUNGWI_REQUIRE_ARTIFACTS:\s*"1"', ci_text()), \
        "가드가 꺼져 있으면 산출물 없는 러너에서도 초록이 뜰 수 있다"


def test_every_required_artifact_is_committed():
    """checkout 만으로 실측이 되려면 산출물이 저장소에 있어야 한다."""
    tracked = set(subprocess.run(["git", "ls-files"], cwd=str(ROOT), text=True,
                                 capture_output=True, timeout=30).stdout.split())
    assert tracked, "git ls-files 가 비었다 — 저장소가 아니거나 git 이 없다"
    for rel in conftest.REQUIRED_ARTIFACTS:
        assert rel in tracked, "%s 가 커밋돼 있지 않다 — CI 러너에는 없는 파일이다" % rel


def test_the_guard_lists_what_is_missing():
    assert conftest.missing_artifacts(ROOT) == [], "실물 산출물이 비어 있다"


def test_the_guard_sees_an_empty_tree_as_all_missing(tmp_path):
    assert conftest.missing_artifacts(tmp_path) == list(conftest.REQUIRED_ARTIFACTS)


def _mini_suite(tmp_path):
    """conftest 만 복사한 최소 스위트 — 그 자리에서는 산출물이 하나도 없다."""
    (tmp_path / "conftest.py").write_text(
        (ROOT / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_trivial.py").write_text("def test_ok():\n    assert True\n",
                                              encoding="utf-8")


def _run_pytest(tmp_path, env_value):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path)}
    if env_value is not None:
        env["CHEUNGWI_REQUIRE_ARTIFACTS"] = env_value
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           str(tmp_path)], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


def test_the_guard_stops_a_session_that_has_no_artifacts(tmp_path):
    """가드가 켜진 세션은 산출물이 없으면 **한 건도 돌기 전에** 끝난다."""
    _mini_suite(tmp_path)
    proc = _run_pytest(tmp_path, "1")
    assert proc.returncode != 0, "산출물이 없는데 통과했다:\n%s" % proc.stdout
    assert "산출물" in (proc.stdout + proc.stderr)
    assert "out/market.json" in (proc.stdout + proc.stderr)


def test_without_the_guard_a_local_run_still_works(tmp_path):
    """로컬에서 산출물을 지우고 순수 함수만 돌려 보는 길은 막지 않는다."""
    _mini_suite(tmp_path)
    assert _run_pytest(tmp_path, None).returncode == 0
