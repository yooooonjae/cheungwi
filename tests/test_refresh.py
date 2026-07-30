"""파이프라인 오케스트레이션 — 단계 순서·독립 실패·복원·배포 생략·마커·캐시 무효화.

여기서 검증하는 것은 "무엇을 어떤 순서로 부르고, 실패했을 때 무엇을 하지 않는가"다.
그래서 subprocess.run 을 통째로 가로채 명령만 기록한다 — 수집기·엔진·빌더의 내용은
각자의 테스트가 이미 본다.
"""

import datetime
import json
import os
import subprocess

import pytest

from src.collect import trades as trades_mod
from src.pipeline import refresh


class _Done:
    """subprocess.CompletedProcess 대역."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def root(tmp_path):
    """분석 산출과 사이트가 이미 한 벌 있는 저장소 모양."""
    (tmp_path / "logs").mkdir()
    out = tmp_path / "out"
    out.mkdir()
    for name in ("market", "underwriting", "trades_analysis", "pf_case"):
        (out / f"{name}.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "DATA_MANIFEST.json").write_text(
        '{"data_cutoff": "2026-06"}', encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("x" * 30_000, encoding="utf-8")
    return tmp_path


class _Spy:
    """가로챈 subprocess 호출 기록 + 명령별 응답 규칙."""

    def __init__(self):
        self.calls = []
        self.rules = []

    def when(self, needle, result):
        """명령 문자열에 needle 이 들어 있으면 result(또는 result(cmd))를 돌려준다."""
        self.rules.append((needle, result))
        return self

    @property
    def cmds(self):
        return [c["cmd"] for c in self.calls if c["cmd"][0] != "osascript"]

    def ran(self, needle):
        return [c for c in self.cmds if any(needle in a for a in c)]


@pytest.fixture
def spy(monkeypatch):
    s = _Spy()

    def fake_run(cmd, **kw):
        cmd = [str(a) for a in cmd]
        s.calls.append({"cmd": cmd, "kw": kw})
        joined = " ".join(cmd)
        for needle, result in s.rules:
            if needle in joined:
                return result(cmd) if callable(result) else result
        return _Done(0, "한 줄\nCOMPLETE\n")

    monkeypatch.setattr(refresh.subprocess, "run", fake_run)
    monkeypatch.setattr(refresh.shutil, "which", lambda name: f"/fake/bin/{name}")
    return s


def _status(root):
    return json.loads((root / "logs" / "refresh-status.json").read_text(encoding="utf-8"))


# ── 단계 구성 ────────────────────────────────────────────────────────────────

def test_collectors_are_the_five_sources_in_dependency_order():
    """buildings 는 trades 매칭의 입력이라 trades 앞에 서야 한다."""
    names = [n for n, _, _ in refresh.COLLECTORS]
    assert names == ["rone_office", "rates", "buildings", "trades", "reits"]


def test_rone_is_asked_to_drop_its_latest_table_cache():
    """R-ONE 은 캐시 우선이라 무효화 플래그 없이는 새 분기를 영원히 못 받는다."""
    cmds = {n: c for n, c, _ in refresh.COLLECTORS}
    assert "--refresh-latest" in cmds["rone_office"]


# ── 소스별 독립 실패 ─────────────────────────────────────────────────────────

def test_one_collector_failing_does_not_stop_the_others(root, spy):
    spy.when("trades.py", _Done(1, "쿼터 소진\nRESUME_NEEDED\n"))
    code = refresh.main(["--no-deploy"], root=root)
    st = _status(root)
    assert st["stages"]["collect:trades"]["ok"] is False
    # 실패한 수집기 뒤의 수집기도, 분석·원장·빌드도 그대로 돈다
    assert st["stages"]["collect:reits"]["ok"] is True
    assert st["stages"]["analyze"]["ok"] and st["stages"]["build"]["ok"]
    assert any("collect:trades" in f for f in st["failures"])
    assert st["ok"] is False and code == 1


def test_collect_stage_never_chains_exit_1(root, spy):
    """make collect 의 `|| exit 1` 체인을 여기서는 쓰지 않는다 — 다섯 개가 다 돈다."""
    spy.when("rone_office.py", _Done(1, "터짐"))
    spy.when("rates.py", _Done(1, "터짐"))
    refresh.main(["--no-deploy"], root=root)
    for script in ("rone_office.py", "rates.py", "buildings.py", "trades.py", "reits.py"):
        assert spy.ran(script), script


# ── 분석 실패 시 out/ 복원 ───────────────────────────────────────────────────

def test_analysis_failure_restores_out_and_stops_before_build(root, spy):
    before = {p.name: p.read_bytes() for p in (root / "out").glob("*.json")}

    def corrupt(cmd):
        for p in (root / "out").glob("*.json"):
            p.write_text("반쯤 쓰다 만 것", encoding="utf-8")
        return _Done(1, "엔진 예외")

    spy.when("src.analysis.build_out", corrupt)
    code = refresh.main(["--skip-collect"], root=root)
    assert {p.name: p.read_bytes() for p in (root / "out").glob("*.json")} == before
    assert not spy.ran("assemble.py") and not spy.ran("wrangler")
    st = _status(root)
    assert st["stages"]["analyze"]["ok"] is False
    assert "build" not in st["stages"] and "manifest" not in st["stages"]
    assert code == 1


def test_restoring_out_removes_files_the_failed_run_added(root, spy):
    """복원은 백업 시점 그대로다 — 실패한 실행이 새로 만든 산출을 남기면 옛것과 섞인다."""
    def corrupt(cmd):
        (root / "out" / "새산출.json").write_text('{"신규": 1}', encoding="utf-8")
        (root / "out" / "market.json").write_text("반쯤 쓰다 만 것", encoding="utf-8")
        return _Done(1, "엔진 예외")

    spy.when("src.analysis.build_out", corrupt)
    refresh.main(["--skip-collect"], root=root)
    assert not (root / "out" / "새산출.json").exists()
    assert json.loads((root / "out" / "market.json").read_text(encoding="utf-8")) == {
        "name": "market"}
    assert not list((root / "out").glob("*.tmp"))      # 원자 교체의 tmp 를 남기지 않는다


def test_manifest_failure_stops_before_build(root, spy):
    spy.when("manifest.py", _Done(1, "원장 실패"))
    refresh.main(["--skip-collect"], root=root)
    st = _status(root)
    assert st["stages"]["manifest"]["ok"] is False
    assert "build" not in st["stages"] and not spy.ran("wrangler")


# ── 실패가 있으면 배포하지 않는다 ────────────────────────────────────────────

def test_any_failure_skips_deploy(root, spy):
    spy.when("reits.py", _Done(1, "DART 오류"))
    refresh.main([], root=root)
    assert not spy.ran("wrangler")
    st = _status(root)
    assert st["deployed"] is False and "deploy" not in st["stages"]


def test_validation_failure_skips_deploy(root, spy):
    (root / "out" / "market.json").write_text("{망가진", encoding="utf-8")
    refresh.main(["--skip-collect"], root=root)
    st = _status(root)
    assert st["stages"]["validate"]["ok"] is False
    assert not spy.ran("wrangler") and st["deployed"] is False


def test_clean_run_deploys_to_cheungwi(root, spy):
    code = refresh.main([], root=root)
    deploy = spy.ran("wrangler")
    assert len(deploy) == 1
    # npx 경로는 하드코딩이 아니라 which 가 찾은 것이어야 한다(수지 이식성 함정)
    assert deploy[0][0] == "/fake/bin/npx"
    assert deploy[0][1:] == ["--yes", "wrangler", "pages", "deploy", "web",
                             "--project-name", "cheungwi", "--branch", "main",
                             "--commit-dirty=true"]
    st = _status(root)
    assert st["deployed"] is True and st["ok"] is True and code == 0


def test_deploy_path_is_never_hardcoded(root, spy, monkeypatch):
    monkeypatch.setattr(refresh.shutil, "which", lambda name: "/somewhere/else/npx")
    refresh.main([], root=root)
    assert spy.ran("wrangler")[0][0] == "/somewhere/else/npx"


def test_missing_npx_is_recorded_not_crashed(root, spy, monkeypatch):
    monkeypatch.setattr(refresh.shutil, "which", lambda name: None)
    code = refresh.main([], root=root)
    st = _status(root)
    assert not spy.ran("wrangler")
    assert any("npx" in f for f in st["failures"]) and code == 1


def test_no_deploy_is_not_a_failure(root, spy):
    code = refresh.main(["--no-deploy"], root=root)
    st = _status(root)
    assert not spy.ran("wrangler")
    assert st["ok"] is True and st["deployed"] is False and code == 0


def test_deploy_failure_is_reported(root, spy):
    spy.when("wrangler", _Done(1, "인증 실패"))
    code = refresh.main([], root=root)
    st = _status(root)
    assert st["stages"]["deploy"]["ok"] is False and st["deployed"] is False
    assert code == 1


# ── 마커 규약 ────────────────────────────────────────────────────────────────

def test_resume_marker_is_recorded_and_is_not_a_failure(root, spy):
    """대장이 잠긴 동안 buildings 는 늘 RESUME_NEEDED 다 — 그걸 실패로 세면 영영 배포하지 못한다."""
    spy.when("buildings.py", _Done(0, "대장 잠김\nRESUME_NEEDED\n"))
    code = refresh.main(["--no-deploy"], root=root)
    st = _status(root)
    assert st["stages"]["collect:buildings"]["marker"] == "RESUME_NEEDED"
    assert st["resume_needed"] == ["buildings"]
    assert st["failures"] == [] and st["ok"] is True and code == 0


def test_complete_marker_is_recorded(root, spy):
    refresh.main(["--no-deploy"], root=root)
    st = _status(root)
    assert st["stages"]["collect:rates"]["marker"] == "COMPLETE"


def test_marker_is_none_when_the_collector_says_nothing(root, spy):
    spy.when("rates.py", _Done(0, "그냥 끝\n\n"))
    refresh.main(["--no-deploy"], root=root)
    assert _status(root)["stages"]["collect:rates"]["marker"] is None


def test_marker_reads_the_last_nonempty_line():
    assert refresh._marker("가\n나\nCOMPLETE\n\n") == "COMPLETE"
    assert refresh._marker("RESUME_NEEDED") == "RESUME_NEEDED"
    assert refresh._marker("COMPLETE 하다가 말았다") is None   # 마커는 그 줄 전체여야 한다
    assert refresh._marker("") is None
    assert refresh._marker(None) is None


# ── 선택 실행 ────────────────────────────────────────────────────────────────

def test_skip_collect_skips_only_the_collect_stage(root, spy):
    refresh.main(["--skip-collect", "--no-deploy"], root=root)
    assert not spy.ran("src/collect")
    st = _status(root)
    assert st["stages"]["analyze"]["ok"] and st["stages"]["build"]["ok"]


def test_only_runs_one_collector(root, spy):
    refresh.main(["--only", "rates", "--no-deploy"], root=root)
    assert spy.ran("rates.py") and not spy.ran("trades.py")


def test_unknown_collector_name_is_refused(root, spy):
    with pytest.raises(SystemExit):
        refresh.main(["--only", "없는수집기"], root=root)


# ── 실행 환경·기록 ───────────────────────────────────────────────────────────

def test_children_get_utf8_env_because_launchd_does_not_pass_lang(root, spy):
    """LANG 없이 발화되면 한글을 찍는 순간 자식이 UnicodeEncodeError 로 죽는다."""
    refresh.main(["--no-deploy"], root=root)
    env = spy.calls[0]["kw"]["env"]
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONUTF8"] == "1"


def test_children_run_from_the_repo_root(root, spy):
    refresh.main(["--no-deploy"], root=root)
    assert all(str(c["kw"]["cwd"]) == str(root) for c in spy.calls if c["cmd"][0] != "osascript")


def test_timeout_is_a_failure_not_a_crash(root, spy):
    def boom(cmd):
        raise subprocess.TimeoutExpired(cmd, 1)

    spy.when("assemble.py", boom)
    code = refresh.main(["--skip-collect"], root=root)
    st = _status(root)
    assert st["stages"]["build"]["ok"] is False and "timeout" in st["stages"]["build"]["detail"]
    assert code == 1


def test_log_holds_the_child_output_and_status_points_at_it(root, spy):
    spy.when("rates.py", _Done(0, "금리 세 계열 받았다\nCOMPLETE\n"))
    refresh.main(["--no-deploy"], root=root)
    st = _status(root)
    log = root / st["log"]
    assert log.exists() and "금리 세 계열 받았다" in log.read_text(encoding="utf-8")
    assert st["started"] and st["finished"]


# ── 상태 파일은 어제를 오늘로 위장하지 않는다 ────────────────────────────────

def _stale_ok_status(root):
    """전날의 성공이 그대로 남아 있는 상태 파일."""
    (root / "logs" / "refresh-status.json").write_text(
        json.dumps({"started": "2026-07-29T09:10:00", "state": "done", "ok": True,
                    "stages": {}, "failures": [], "deployed": True}, ensure_ascii=False),
        encoding="utf-8")


def test_a_crash_overwrites_yesterdays_ok_with_the_reason(root, spy, monkeypatch):
    """트레이스백으로 즉사해도 상태 파일은 오늘의 실패를 말해야 한다.

    상태 기록이 try 밖에 있으면 예외 한 번에 파일이 전날의 ok:true 로 남는다 —
    launchd 문서가 시킨 확인 절차가 어제의 성공을 오늘의 성공으로 읽는다(백업이 2주 동안
    조용히 죽어 있던 사고가 정확히 이 모양이었다).
    """
    _stale_ok_status(root)

    def boom(**kw):
        raise OSError("무효화 도중 파일이 잠겼다")

    monkeypatch.setattr(refresh, "invalidate_trades_cache", boom)
    code = refresh.main([], root=root)
    st = _status(root)
    assert st["ok"] is False and st["state"] == "crashed" and code == 1
    assert any("무효화 도중 파일이 잠겼다" in f for f in st["failures"])
    assert "OSError" in st["traceback"]
    assert st["started"] > "2026-07-29" and st["finished"]
    assert not spy.ran("wrangler")          # 크래시한 날에는 배포하지 않는다


def test_a_crash_before_the_log_opens_still_lands_in_the_status_file(root, spy, monkeypatch):
    """로그 파일을 열지 못하는 날에도 상태는 남는다 — 기록의 실패가 침묵이 되면 안 된다."""
    _stale_ok_status(root)
    monkeypatch.setattr(refresh, "_run_pipeline",
                        lambda *a, **kw: (_ for _ in ()).throw(PermissionError("logs/ 쓰기 거부")))
    assert refresh.main(["--skip-collect"], root=root) == 1
    st = _status(root)
    assert st["ok"] is False and any("logs/ 쓰기 거부" in f for f in st["failures"])


def test_the_status_file_says_running_while_the_work_is_still_going(root, spy, monkeypatch):
    """일하기 전에 먼저 쓴다 — 도중에 전원이 나가도 파일이 성공을 주장하지 않는다."""
    _stale_ok_status(root)
    seen = {}

    def peek(cmd, **kw):
        seen.setdefault("mid", _status(root))
        return _Done(0, "COMPLETE\n")

    monkeypatch.setattr(refresh.subprocess, "run", peek)
    monkeypatch.setattr(refresh.shutil, "which", lambda name: f"/fake/bin/{name}")
    refresh.main(["--skip-collect", "--no-deploy"], root=root)
    assert seen["mid"]["state"] == "running" and seen["mid"]["ok"] is False
    assert _status(root)["state"] == "done" and _status(root)["ok"] is True


# ── 검증 ─────────────────────────────────────────────────────────────────────

def test_validate_passes_on_a_fresh_build(root):
    assert refresh.validate(root=root) == []


def test_validate_catches_a_missing_or_tiny_index(root):
    (root / "web" / "index.html").write_text("빈 껍데기", encoding="utf-8")
    assert any("index.html" in p for p in refresh.validate(root=root))
    (root / "web" / "index.html").unlink()
    assert any("index.html" in p for p in refresh.validate(root=root))


def test_validate_catches_a_stale_index(root):
    old = datetime.datetime.now().timestamp() - 3 * 86400
    os.utime(root / "web" / "index.html", (old, old))
    assert any("오늘" in p for p in refresh.validate(root=root))


def test_validate_catches_broken_json(root):
    (root / "out" / "pf_case.json").write_text("{", encoding="utf-8")
    probs = refresh.validate(root=root)
    assert any("pf_case.json" in p for p in probs)


def test_validate_checks_the_manifest_too(root):
    (root / "data" / "DATA_MANIFEST.json").unlink()
    assert any("DATA_MANIFEST" in p for p in refresh.validate(root=root))


# ── 캐시 무효화 ──────────────────────────────────────────────────────────────

def _cells(root, yms, pages=1):
    raw = root / "data" / "raw" / "trades"
    raw.mkdir(parents=True, exist_ok=True)
    cells = []
    for sgg in trades_mod.SGG_LIST:
        for ym in yms:
            for p in range(1, pages + 1):
                (raw / f"nrg_{sgg}_{ym}_p{p}.xml").write_text("<response/>", encoding="utf-8")
            cells.append(f"{sgg}_{ym}")
    return cells


def _seed_trades(root, yms):
    cells = _cells(root, yms)
    (root / "data" / "trades_progress.json").write_text(
        json.dumps({"done": sorted(cells)}, ensure_ascii=False), encoding="utf-8")
    (root / "data" / "trades.json").write_text(
        json.dumps({"trades": [], "meta": {"cells_done": len(cells), "cells_total": len(cells)}},
                   ensure_ascii=False), encoding="utf-8")
    return cells


def test_recent_months_counts_backwards_from_today():
    assert refresh.recent_months(3, today=datetime.date(2026, 7, 31)) == \
        ["202605", "202606", "202607"]
    assert refresh.recent_months(3, today=datetime.date(2026, 2, 1)) == \
        ["202512", "202601", "202602"]
    assert refresh.recent_months(1, today=datetime.date(2026, 1, 9)) == ["202601"]


def test_invalidate_drops_recent_cells_from_cache_and_progress(root):
    all_yms = ["202603", "202604", "202605", "202606", "202607"]
    _seed_trades(root, all_yms)
    info = refresh.invalidate_trades_cache(root=root, months=3,
                                           today=datetime.date(2026, 7, 31))
    raw = root / "data" / "raw" / "trades"
    recent = {"202605", "202606", "202607"}
    assert set(info["cells"]) == {f"{s}_{y}" for s in trades_mod.SGG_LIST for y in recent}
    assert not list(raw.glob("nrg_*_202607_p*.xml"))
    assert not list(raw.glob("nrg_*_202605_p*.xml"))
    # 오래된 달은 건드리지 않는다 — 20년치를 매일 다시 받을 이유가 없다
    assert len(list(raw.glob("nrg_*_202604_p*.xml"))) == len(trades_mod.SGG_LIST)
    done = json.loads((root / "data" / "trades_progress.json").read_text(encoding="utf-8"))["done"]
    assert not [c for c in done if c.split("_")[1] in recent]
    assert len([c for c in done if c.split("_")[1] == "202604"]) == len(trades_mod.SGG_LIST)


def test_invalidate_shrinks_the_recorded_prior_by_the_same_count(root):
    """축소 방어(save_result)는 기존 cells_done 과 비교한다 — 무효화한 만큼 낮춰야 재수집분이 제자리에 저장된다."""
    all_yms = ["202604", "202605", "202606", "202607"]
    cells = _seed_trades(root, all_yms)
    info = refresh.invalidate_trades_cache(root=root, months=3,
                                           today=datetime.date(2026, 7, 31))
    meta = json.loads((root / "data" / "trades.json").read_text(encoding="utf-8"))["meta"]
    assert info["cells_done_before"] == len(cells)
    assert meta["cells_done"] == len(cells) - len(info["cells"]) == info["cells_done_after"]


def test_invalidated_rebuild_is_saved_in_place_not_pushed_aside(root, monkeypatch):
    """무효화 → 재수집이 한 셀도 못 받았어도, 남은 셀로 만든 산출은 .partial 로 밀리지 않는다."""
    all_yms = ["202604", "202605", "202606", "202607"]
    cells = _seed_trades(root, all_yms)
    monkeypatch.setattr(trades_mod, "OUT_PATH", root / "data" / "trades.json")
    monkeypatch.setattr(trades_mod, "PARTIAL_PATH", root / "data" / "trades.partial.json")
    monkeypatch.setattr(trades_mod, "PROG_PATH", root / "data" / "trades_progress.json")
    refresh.invalidate_trades_cache(root=root, months=3, today=datetime.date(2026, 7, 31))
    kept = [c for c in cells if c.split("_")[1] == "202604"]
    result = {"trades": [], "meta": {"cells_done": len(kept), "stopped": ""}}
    written = trades_mod.save_result(result, set(kept))
    assert written.name == "trades.json"
    assert not (root / "data" / "trades.partial.json").exists()


def test_invalidate_is_silent_when_there_is_nothing_cached(root):
    info = refresh.invalidate_trades_cache(root=root, months=3)
    assert info["cells"] == [] and info["files"] == 0


def test_invalidation_runs_before_collect_but_not_with_skip_collect(root, spy, monkeypatch):
    seen = []
    monkeypatch.setattr(refresh, "invalidate_trades_cache",
                        lambda **kw: seen.append(kw) or {"cells": [], "files": 0, "months": [],
                                 "cells_done_before": None, "cells_done_after": None})
    refresh.main(["--skip-collect", "--no-deploy"], root=root)
    assert seen == []
    refresh.main(["--no-deploy"], root=root)
    assert len(seen) == 1


def test_no_invalidate_flag_leaves_the_cache_alone(root, spy, monkeypatch):
    seen = []
    monkeypatch.setattr(refresh, "invalidate_trades_cache",
                        lambda **kw: seen.append(kw) or {"cells": [], "files": 0, "months": [],
                                 "cells_done_before": None, "cells_done_after": None})
    refresh.main(["--no-invalidate", "--no-deploy"], root=root)
    assert seen == []
