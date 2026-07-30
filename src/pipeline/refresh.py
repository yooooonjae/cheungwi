"""일일 갱신 파이프라인 — 무효화 → 수집 → 분석 → 원장 → 빌드 → 검증 → 스위트 → 배포.

실행:
  python3 src/pipeline/refresh.py                  # 전체 (launchd 가 매일 09:10 에 부르는 것)
  python3 src/pipeline/refresh.py --skip-collect   # 분석부터 (수집 없이 사이트만 다시 굽는다)
  python3 src/pipeline/refresh.py --only trades    # 한 수집기 + 이후 단계 전부
  python3 src/pipeline/refresh.py --no-deploy      # 배포 직전까지의 드라이런
  python3 src/pipeline/refresh.py --no-invalidate  # 캐시 무효화 없이 (쿼터를 아낄 때)

원칙(기존 시리즈의 운영 교훈):
- **소스별 독립.** `make collect` 은 `|| exit 1` 로 묶여 한 수집기가 죽으면 뒤가 통째로
  멈춘다. 여기서는 다섯이 각자 돌고 실패는 status 에 남는다 — 실패한 소스는 직전
  data/*.json 이 그대로 남아 사이트는 옛 데이터로 빌드된다. 대신 그 사실을 반드시 드러낸다
  (조용한 최신 위장 금지).
- **분석 실패는 out/ 을 되돌린다.** build_out 은 tmp→rename 이라 반쪽 파일은 안 남지만,
  네 산출 중 둘만 새것인 혼재는 남을 수 있다. 그래서 실행 전 메모리에 떠 둔 사본으로
  되돌리고 빌드를 중단한다 — 직전 사이트가 그대로 서빙된다.
- **실패가 하나라도 있으면 배포하지 않는다.** pages.dev 는 직전 배포를 계속 서빙하므로
  가만히 두는 쪽이 언제나 안전하다.
- **배포 직전에 계약 스위트를 돌린다.** `validate()` 가 보는 것은 index 가 있는가·오늘
  구웠는가·JSON 이 파싱되는가뿐이다. 그 셋은 "파일이 생겼다"는 증거지 "값이 말이 된다"는
  증거가 아니다. 새 분기 데이터로 구운 out/ 이 엔진의 계약(단위·게이트·사다리 항등식·
  파이썬↔자바스크립트 패리티)을 깼는지는 스위트만 안다 — 그것을 CI 에만 맡기면 CI 는
  **커밋된** 산출을 보고, 배포되는 것은 **방금 구운** 산출이라 검사받은 것과 나가는 것이
  갈린다. 그래서 배포 경로 안에서 한 번 더 돈다(`CHEUNGWI_REQUIRE_ARTIFACTS=1` 로).
- **상태 파일은 먼저 쓰고 마지막에 덮는다.** 시작하자마자 `ok:false, state:running` 을 써
  두고, 본문 전체를 try 로 감싸 예외까지 failures 로 환원한 뒤 finally 에서 최종 상태를
  쓴다. 트레이스백으로 즉사해 상태 파일이 갱신되지 않으면, 그 파일을 보라고 적어 둔 운영
  절차가 **전날의 ok:true** 를 오늘의 성공으로 읽는다(백업이 2주 동안 조용히 죽어 있던
  사고가 정확히 이 모양이었다).
- **마커 규약.** 수집기 stdout 마지막 줄의 COMPLETE / RESUME_NEEDED 를 읽어 기록한다.
  RESUME_NEEDED 는 실패가 아니라 "다음 실행이 이어받는다"는 뜻이다(대장이 잠긴 지금
  buildings 는 늘 이 마커로 끝난다 — 이걸 실패로 세면 영영 배포하지 못한다).
- **launchd 는 LANG 을 물려주지 않는다.** 자식이 한글을 찍는 순간 UnicodeEncodeError 로
  죽지 않도록 PYTHONIOENCODING·PYTHONUTF8 을 붙여 부른다. PATH(wrangler·node)는 plist 의
  EnvironmentVariables 가 맡는다 — docs/launchd-setup.md 참조.

기록: logs/refresh-YYYYMMDD-HHMM.log(자식 출력 전량) · logs/refresh-status.json(기계 판독).
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect import trades as trades_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable or "python3"

PROJECT = "cheungwi"                       # Cloudflare Pages 프로젝트명(첫 배포 때 생성된다)
SITE_URL = f"https://{PROJECT}.pages.dev"

# (이름, 인자, 타임아웃초). 순서가 의존 관계다 — buildings 가 trades 매칭의 입력이다.
COLLECTORS = [
    ("rone_office", ["src/collect/rone_office.py", "--refresh-latest"], 1800),
    ("rates",       ["src/collect/rates.py"],       900),
    ("buildings",   ["src/collect/buildings.py"],   3600),
    ("trades",      ["src/collect/trades.py"],      5400),
    ("reits",       ["src/collect/reits.py"],       1800),
]
ANALYZE_TIMEOUT, MANIFEST_TIMEOUT, BUILD_TIMEOUT, DEPLOY_TIMEOUT = 900, 300, 600, 900
# 스위트는 지금 2분대다(그 중 큰 몫이 terser 를 부르는 빌드 게이트). 검사가 늘어도
# 타임아웃이 먼저 터져 "실패로 오인"되지 않게 열 배 넘는 여유를 준다.
TEST_TIMEOUT = 1800

TRADES_INVALIDATE_MONTHS = 3   # 실거래는 뒤늦게 신고되는 달이 있어 최근 세 달을 다시 받는다
MARKERS = ("COMPLETE", "RESUME_NEEDED")
MIN_INDEX_BYTES = 10_000       # 지금 index.html 은 20KB 대다. 빈 껍데기·오류 페이지를 거른다.
VALIDATE_JSON = ("out/market.json", "out/underwriting.json", "out/trades_analysis.json",
                 "out/pf_case.json", "data/DATA_MANIFEST.json")


# ── 도구 ────────────────────────────────────────────────────────────────────

def _write_json(path: Path, payload: dict):
    """tmp → replace. 쓰다 만 JSON 을 남기지 않는다."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _restore_out(out_dir: Path, backup: dict):
    """out/*.json 을 백업 시점 그대로 되돌린다 — 원자 교체 + 신규 파일 삭제.

    되돌리는 쓰기가 반쯤 하다 멈추면(디스크 참·전원) 복원하려던 자리에 오히려 잘린 JSON 이
    남는다. 그래서 한 파일씩 tmp→replace 로 갈아 끼운다. 실패한 실행이 **새로** 만든 산출도
    지운다 — 백업에 없던 파일을 남겨 두면 옛 산출과 새 산출이 한 디렉터리에서 섞인다
    (out/ 을 되돌리는 이유 자체가 그 혼재를 막는 것이다).
    """
    for fname, data in backup.items():
        target = out_dir / fname
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    for p in out_dir.glob("*.json"):
        if p.name not in backup:
            p.unlink()


def _marker(stdout) -> str | None:
    """수집기 stdout 마지막 비어 있지 않은 줄이 마커면 그것을, 아니면 None.

    줄 전체가 마커여야 한다 — 본문에 'COMPLETE' 가 섞인 문장을 완주로 읽으면 안 된다.
    """
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        return line if line in MARKERS else None
    return None


def notify(title: str, msg: str):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass  # 알림 실패가 파이프라인을 죽이면 안 된다


def run_step(name: str, cmd: list, timeout: int, log, root=ROOT, env_extra=None) -> dict:
    """자식 하나를 돌리고 (성공 여부·사유·초·마커)를 돌려준다. 출력은 전량 로그로 옮긴다."""
    t0 = datetime.datetime.now()
    log.write(f"\n===== {name} — {t0:%H:%M:%S} =====\n$ {' '.join(map(str, cmd))}\n")
    log.flush()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(env_extra or {})}
    out, marker = "", None
    try:
        r = subprocess.run(cmd, cwd=root, timeout=timeout, env=env,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        marker = _marker(r.stdout)
        ok, detail = r.returncode == 0, f"exit={r.returncode}"
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        ok, detail = False, f"timeout>{timeout}s"
    except Exception as e:  # 실행 자체가 안 된 경우(파일 없음 등)도 상태로 환원한다
        ok, detail = False, f"error: {e}"
    dur = (datetime.datetime.now() - t0).total_seconds()
    log.write(out if out.endswith("\n") or not out else out + "\n")
    log.write(f"----- {name}: {'OK' if ok else 'FAIL'} ({detail}, {dur:.0f}s"
              f"{', 마커 ' + marker if marker else ''})\n")
    log.flush()
    return {"ok": ok, "detail": detail, "seconds": round(dur), "marker": marker}


# ── 캐시 무효화 ─────────────────────────────────────────────────────────────

def recent_months(n: int = TRADES_INVALIDATE_MONTHS, today=None) -> list:
    """오늘이 든 달을 포함한 최근 n개월('YYYYMM', 오름차순)."""
    today = today or datetime.date.today()
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return sorted(out)


def invalidate_trades_cache(root=ROOT, months: int = TRADES_INVALIDATE_MONTHS,
                            today=None) -> dict:
    """실거래 최근 months 개월 캐시를 지우고, 진행 파일과 기록된 셀 수를 함께 낮춘다.

    실거래 수집기는 "캐시가 완결이면 부르지 않는다"라서, 지우지 않으면 최근 달이 영원히
    첫 수집 그대로 언다(신고가 뒤늦게 들어오는 달이라 실제로 계속 늘어난다).

    **셋을 함께 낮추는 것이 요점이다.** `save_result` 는 이번 실행이 담은 셀 수가 기존
    산출의 `meta.cells_done` 보다 적으면 산출을 `.partial` 로 비켜 쓴다(캐시 없는 clone 이
    커밋된 데이터를 지우지 못하게 하는 방어다). 캐시만 지우면 재수집이 실패한 날의 산출이
    바로 그 '얇은 결과'가 되어 제자리에 저장되지 못한다. 그래서 무효화한 셀 수만큼
    prior(cells_done)도 낮춰 둔다 — 방어는 그대로 살아 있고(더 얇아지면 여전히 비켜 쓴다)
    무효화분만 정상 경로로 되돌아온다.
    """
    root = Path(root)
    raw_dir = root / "data" / "raw" / "trades"
    yms = recent_months(months, today)
    cells, files = [], 0
    for sgg in trades_mod.SGG_LIST:
        for ym in yms:
            paths = sorted(raw_dir.glob(f"nrg_{sgg}_{ym}_p*.xml"))
            if not paths:
                continue
            for p in paths:
                p.unlink()
                files += 1
            cells.append(f"{sgg}_{ym}")
    info = {"months": yms, "cells": cells, "files": files,
            "cells_done_before": None, "cells_done_after": None}
    if not cells:
        return info

    dropped, counted = set(cells), len(cells)
    prog_path = root / "data" / "trades_progress.json"
    if prog_path.exists():
        try:
            done = json.loads(prog_path.read_text(encoding="utf-8"))["done"]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            done = None
        if done is not None:
            # 산출에 실제로 실려 있던 셀만 센다 — 캐시에 있었지만 절단이라 산출에서 빠진
            # 셀까지 세면 prior 를 필요 이상으로 깎는다.
            counted = len(dropped & set(done))
            # trades.write_progress 는 '줄어드는 쓰기'를 막는다(캐시 없는 clone 보호).
            # 여기서는 줄이는 것이 목적이므로 그 방어를 지나 직접 쓴다.
            _write_json(prog_path, {"done": sorted(set(done) - dropped)})

    out_path = root / "data" / "trades.json"
    if out_path.exists():
        try:
            doc = json.loads(out_path.read_text(encoding="utf-8"))
            before = doc["meta"]["cells_done"]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            doc, before = None, None
        if doc is not None and isinstance(before, int):
            after = max(0, before - counted)
            doc["meta"]["cells_done"] = after
            doc["meta"]["complete"] = False   # 방금 구멍을 냈으니 완결이 아니다
            doc["meta"]["cache_invalidated"] = {
                "at": (today or datetime.date.today()).isoformat(),
                "months": yms, "cells": len(cells), "cells_done_from": before}
            _write_json(out_path, doc)
            info["cells_done_before"], info["cells_done_after"] = before, after
    return info


# ── 검증 ────────────────────────────────────────────────────────────────────

def validate(root=ROOT, today=None) -> list:
    """빌드 산출의 신선도·무결성. 실패 사유 목록(비면 통과)."""
    root, today = Path(root), (today or datetime.date.today())
    probs = []
    idx = root / "web" / "index.html"
    if not idx.exists():
        probs.append("web/index.html 없음")
    elif idx.stat().st_size < MIN_INDEX_BYTES:
        probs.append(f"web/index.html 이 비정상적으로 작다({idx.stat().st_size:,}바이트)")
    elif datetime.date.fromtimestamp(idx.stat().st_mtime) != today:
        probs.append("web/index.html 이 오늘 빌드되지 않았다")
    for rel in VALIDATE_JSON:
        try:
            json.loads((root / rel).read_text(encoding="utf-8"))
        except Exception as e:
            probs.append(f"{rel} 읽기·파싱 실패: {e}")
    return probs


# ── 오케스트레이션 ──────────────────────────────────────────────────────────

def _parse_args(argv):
    p = argparse.ArgumentParser(prog="refresh", description="층위 일일 갱신 파이프라인")
    p.add_argument("--skip-collect", action="store_true", help="수집 단계를 건너뛴다")
    p.add_argument("--only", choices=[n for n, _, _ in COLLECTORS], help="이 수집기만 돌린다")
    p.add_argument("--no-deploy", action="store_true", help="배포하지 않는다(드라이런)")
    p.add_argument("--no-invalidate", action="store_true", help="캐시 무효화를 하지 않는다")
    return p.parse_args(argv)


def _run_pipeline(args, root: Path, log_path: Path, status: dict):
    """무효화 → 수집 → 분석 → 원장 → 빌드 → 검증 → 스위트 → 배포. 결과는 status 에 쌓는다.

    여기서 나는 예외는 main 이 받아 failures 로 환원한다 — 상태 파일이 반드시 갱신되도록.
    """
    with open(log_path, "w", encoding="utf-8") as log:
        # 0) 캐시 무효화 — 수집을 실제로 할 때만
        if not args.skip_collect and not args.no_invalidate and args.only in (None, "trades"):
            info = invalidate_trades_cache(root=root)
            status["invalidated"] = info
            log.write(f"\n===== invalidate — {info['files']}개 원문 · {len(info['cells'])}셀 "
                      f"({', '.join(info['months'])}) · cells_done "
                      f"{info['cells_done_before']}→{info['cells_done_after']}\n")

        # 1) 수집 — 소스별 독립. 하나가 죽어도 나머지는 간다.
        if not args.skip_collect:
            for name, cmd_args, timeout in COLLECTORS:
                if args.only and name != args.only:
                    continue
                res = run_step(f"collect:{name}", [PY, *cmd_args], timeout, log, root)
                status["stages"][f"collect:{name}"] = res
                if res["marker"] == "RESUME_NEEDED":
                    status["resume_needed"].append(name)
                if not res["ok"]:
                    status["failures"].append(
                        f"collect:{name} ({res['detail']}) — 직전 데이터로 빌드된다")

        aborted = False
        # 2) 분석 — 실패하면 out/ 을 되돌리고 빌드로 넘어가지 않는다
        out_dir = root / "out"
        backup = {p.name: p.read_bytes() for p in out_dir.glob("*.json")}
        res = run_step("analyze", [PY, "-m", "src.analysis.build_out"], ANALYZE_TIMEOUT, log, root)
        status["stages"]["analyze"] = res
        if not res["ok"]:
            _restore_out(out_dir, backup)
            status["failures"].append(
                f"analyze ({res['detail']}) — out/ 을 되돌리고 빌드를 중단했다(직전 사이트 유지)")
            aborted = True

        # 3) 원장 — 산출 메타를 사이트가 그대로 싣는다. 여기가 어긋나면 빌드로 가지 않는다.
        if not aborted:
            res = run_step("manifest", [PY, "src/build/manifest.py"], MANIFEST_TIMEOUT, log, root)
            status["stages"]["manifest"] = res
            if not res["ok"]:
                status["failures"].append(f"manifest ({res['detail']}) — 빌드 중단, 직전 사이트 유지")
                aborted = True

        # 4) 빌드 — assemble 자체가 원자적이라 실패해도 web/ 은 직전 것 그대로다
        if not aborted:
            res = run_step("build", [PY, "src/build/assemble.py"], BUILD_TIMEOUT, log, root)
            status["stages"]["build"] = res
            if not res["ok"]:
                status["failures"].append(f"build ({res['detail']}) — 직전 사이트 유지")
                aborted = True

        # 5) 검증
        if not aborted:
            probs = validate(root=root)
            status["stages"]["validate"] = {"ok": not probs, "detail": "; ".join(probs) or "clean",
                                            "seconds": 0, "marker": None}
            status["failures"].extend(probs)

        # 6) 계약 스위트 — 방금 구운 산출물을 실물로 놓고 전 검사를 돌린다.
        #    validate 가 보는 것은 "파일이 있고 오늘 것이고 파싱된다"까지다. 새 데이터가
        #    엔진의 계약을 깼는지는 여기서만 걸린다. 가드를 켜서 산출물 부재는 skip 이
        #    아니라 실패로 받는다(CI 와 같은 규약).
        if not aborted:
            res = run_step("test", [PY, "-m", "pytest", "tests/", "-q"], TEST_TIMEOUT, log, root,
                           env_extra={"CHEUNGWI_REQUIRE_ARTIFACTS": "1"})
            status["stages"]["test"] = res
            if not res["ok"]:
                status["failures"].append(
                    f"test ({res['detail']}) — 계약 스위트가 깨졌다. 배포하지 않는다"
                    f"(직전 사이트 유지, 로그 {log_path.name} 를 보라)")

        # 7) 배포 — 실패가 하나라도 있으면 하지 않는다(pages.dev 는 직전 배포를 계속 서빙한다)
        if not aborted and not status["failures"] and not args.no_deploy:
            npx = shutil.which("npx")   # 경로를 박아 두면 다른 기계에서 조용히 안 돈다
            if not npx:
                status["failures"].append("deploy: npx 를 PATH 에서 찾지 못했다 — 배포 생략"
                                          "(launchd 라면 plist 의 PATH 를 확인하라)")
            else:
                res = run_step("deploy", [npx, "--yes", "wrangler", "pages", "deploy", "web",
                                          "--project-name", PROJECT, "--branch", "main",
                                          "--commit-dirty=true"], DEPLOY_TIMEOUT, log, root)
                status["stages"]["deploy"] = res
                status["deployed"] = res["ok"]
                if not res["ok"]:
                    status["failures"].append(f"deploy ({res['detail']}) — {SITE_URL} 는 직전 배포 유지")


def main(argv=None, root=ROOT) -> int:
    args = _parse_args(argv)
    root = Path(root)
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    log_rel = f"logs/refresh-{now:%Y%m%d-%H%M%S}.log"   # 초까지 — 같은 분에 두 번 돌려도 안 겹친다
    status_path = logs / "refresh-status.json"
    status = {"started": now.isoformat(timespec="seconds"), "state": "running", "ok": False,
              "stages": {}, "failures": [], "resume_needed": [], "deployed": False,
              "log": log_rel}
    # 일하기 **전에** 한 번 쓴다. 이 뒤로 무엇이 터지든(로그 디렉터리 쓰기 실패·무효화 예외)
    # 이 파일이 어제의 ok:true 를 오늘의 성공으로 위장하지 못한다.
    _write_json(status_path, status)

    try:
        _run_pipeline(args, root, root / log_rel, status)
        status["state"] = "done"
    except Exception as e:   # 예외도 실패의 한 종류로 환원한다 — 조용한 즉사를 만들지 않는다
        status["state"] = "crashed"
        status["failures"].append(f"파이프라인이 예외로 멈췄다 — {type(e).__name__}: {e}")
        status["traceback"] = traceback.format_exc()
    finally:
        # Ctrl-C·SystemExit 로 빠져나가는 길에도 running 이 박제되지 않게
        if status["state"] == "running":
            status["state"] = "interrupted"
            status["failures"].append("파이프라인이 도중에 끊겼다 — 완주하지 못했다")
        status["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        status["ok"] = not status["failures"]
        _write_json(status_path, status)

    n_ok = sum(1 for v in status["stages"].values() if v["ok"])
    resume = f" · 재개 대기 {','.join(status['resume_needed'])}" if status["resume_needed"] else ""
    if status["ok"]:
        notify("층위 갱신 완료", f"{n_ok}단계 정상{resume} · {now:%m월 %d일}")
    else:
        notify("층위 갱신 실패 ⚠️", f"{len(status['failures'])}건 — logs/refresh-status.json 확인")
    print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
