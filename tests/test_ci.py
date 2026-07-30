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

`make check` 는 이 워크플로의 로컬 동등물이다. 둘을 **대조**하는 대신 CI 가 `make check` 를
그대로 부르게 했다 — 동등이 검사가 아니라 정의가 되면 갈라질 자리가 없다. 그래서 여기서
보는 것은 "CI 가 make check 를 부르는가"와 "make check 가 넷을 다 돌리는가" 둘이다.

세 번째로, **커밋된 산출물이 낡지 않았는가**도 본다. 산출물을 커밋해 두는 계약은
checkout 만으로 실측을 가능하게 하지만, `src/analysis` 를 고치고 `make analyze` 를 잊으면
CI 는 낡은 산출물끼리의 정합만 초록으로 증명한다.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import conftest
from src.analysis.build_out import OUT_FILES, build_all

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = ROOT / "Makefile"


def ci_text():
    assert CI.is_file(), "CI 워크플로가 없다: %s" % CI
    return CI.read_text(encoding="utf-8")


def ci_commands():
    """워크플로에서 **실제로 실행되는** 줄만. 주석은 뺀다(주석은 검사를 돌리지 않는다)."""
    return "\n".join(line for line in ci_text().splitlines()
                     if not line.lstrip().startswith("#"))


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


def test_the_workflow_calls_make_check():
    """CI 와 로컬을 대조하는 대신 **같은 것**을 부르게 한다 — 동등이 정의가 된다."""
    assert re.search(r"^\s*run:\s*make check\s*$", ci_commands(), re.M), \
        "CI 가 make check 를 부르지 않는다 — 스텝을 따로 나열하면 로컬과 갈라진다"


def test_the_check_target_is_the_single_source_of_the_core_four():
    """검사 넷의 정의는 Makefile 한 곳에 있다. CI 는 그것을 부르기만 한다."""
    recipe = make_target("check")
    for name, pattern in CORE_CHECKS.items():
        assert re.search(pattern, recipe), "make check 가 %s 를 돌리지 않는다" % name
    assert "CHEUNGWI_REQUIRE_ARTIFACTS=1" in recipe, \
        "로컬 검증만 가드 없이 돌면 CI 에서 처음 걸리는 부재가 생긴다"


def test_the_workflow_does_not_restate_the_core_checks():
    """워크플로에 검사를 다시 적는 순간 둘은 조용히 갈라진다 — 부르는 줄 하나로 족하다."""
    commands = ci_commands()
    for name, pattern in CORE_CHECKS.items():
        assert not re.search(pattern, commands), \
            "CI 가 %s 를 직접 적고 있다 — make check 안으로 옮겨라" % name


def test_the_script_syntax_check_looks_at_every_file():
    """`node --check a.js b.js` 는 첫 파일만 본다 — 반드시 파일마다 돌려야 한다."""
    recipe = make_target("check")
    assert re.search(r"for f in site/js/\*\.js", recipe), \
        "사이트 스크립트를 파일별로 돌지 않는다 — 둘째 파일부터는 검사되지 않는다"
    assert not re.search(r"node --check site/js/\*\.js", recipe)


def test_the_python_bytecompile_covers_every_source():
    """`src/*.py` 만 훑으면 하위 패키지가 통째로 빠진다 — find 로 전부 건다."""
    assert re.search(r"find src -name '\*\.py'", make_target("check")), \
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


def test_the_committed_out_is_what_the_current_engine_builds(tmp_path):
    """산출물이 **낡지 않았는가** — 있다는 것만으로는 부족하다.

    `src/analysis` 를 고치고 `make analyze` 를 잊은 커밋에서, CI 가 읽는 out/ 은 옛 코드의
    산물이다. 그러면 초록 체크가 증명하는 것은 "지금 코드가 옳다"가 아니라 "낡은 산출물끼리
    아귀가 맞는다"가 된다 — 배포되는 값과 검사받은 값이 갈리는, 가장 조용한 실패다.
    커밋된 데이터로 지금 코드가 다시 구운 넷을 바이트로 맞대면 그 자리에서 걸린다(1초 미만).
    """
    build_all(data_dir=ROOT / "data", out_dir=tmp_path)
    stale = []
    for name in OUT_FILES:
        fresh = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        committed = hashlib.sha256((ROOT / "out" / name).read_bytes()).hexdigest()
        if fresh != committed:
            stale.append("out/%s (커밋 %s… ≠ 재생성 %s…)" % (name, committed[:12], fresh[:12]))
    assert not stale, ("커밋된 산출물이 지금 코드·데이터가 만드는 것과 다르다: %s — "
                       "make analyze 를 돌리고 out/ 을 함께 커밋하라"
                       % " · ".join(stale))


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
