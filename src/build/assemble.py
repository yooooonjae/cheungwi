"""사이트 빌드 — site/ 소스를 web/ dist 로 굽는다.

산출은 멀티파일이다. index.html 은 CSS·JS 를 링크로 참조하고, 분석 산출
(out/*.json · data/DATA_MANIFEST.json)은 `web/data/{name}.js` 에
`window.__{KEY} = {...};` 형태로 구워 넣는다 — 사이트가 외부로 아무것도 요청하지
않게 하려는 것이다(fetch 도 하지 않는다).

빌드는 두 개의 게이트를 통과해야 끝난다.
  - 미치환 플레이스홀더: `{{...}}` 가 하나라도 남으면 중단한다. 화면에 중괄호가
    그대로 나가는 사고를 배포 전에 잡는다.
  - 한국어 조사 분리: 강조 태그가 닫힌 뒤 줄바꿈을 끼고 조사가 오면 실화면에서
    "임대료 가 오른다"처럼 띄어쓰기가 생긴다. 소스에서는 보이지 않는 결함이라
    빌드가 대신 본다.

배치는 원자적이다. 전부 web.tmp/ 에 만든 뒤에야 기존 web/ 을 갈아 끼우므로,
어느 단계에서 실패하든 이미 서비스되던 web/ 은 손대지 않은 채로 남는다.

선언과 실재는 어긋날 수 없다. CSS_FILES·JS_FILES·DATA_MAP 에 적힌 파일이 없으면
있는 것만 추려 빌드하지 않고 그 자리에서 멈춘다 — 파일 하나가 조용히 빠진 사이트가
나가는 편이 훨씬 나쁘다.

실행: python3 src/build/assemble.py [--no-protect] [--index]
      --no-protect  CSS 최소화·JS 압축을 건너뛴다(디버깅용)
      --index       색인을 연다. 기본은 noindex 다.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
OUT = ROOT / "out"
DATA = ROOT / "data"
WEB = ROOT / "web"
TMP = ROOT / "web.tmp"

# 키 → (산출 파일명, 원천 경로). 키는 그대로 window.__{KEY} 가 된다.
DATA_MAP = {
    "DATA_MARKET": ("market", OUT / "market.json"),
    "DATA_UNDERWRITING": ("underwriting", OUT / "underwriting.json"),
    "DATA_TRADES": ("trades", OUT / "trades_analysis.json"),
    "DATA_PF": ("pf", OUT / "pf_case.json"),
    "DATA_MANIFEST": ("manifest", DATA / "DATA_MANIFEST.json"),
}
# 적힌 순서가 곧 로드 순서다. 뒤 파일이 앞 파일을 덮어쓴다.
CSS_FILES = ["tokens.css", "base.css", "hero.css", "chapters.css", "chapter3.css",
             "method.css"]
# JS 도 순서가 계약이다. hero 는 로드 시점에 window.CheungwiCharts·CheungwiEngine
# 을 이미 있는 것으로 읽고, 각 장은 거기에 hero(판형 부속·서식)까지 읽는다. 실험실은
# 한 걸음 더 나아가 chapter3(도면 활자 맞추기)까지 읽고, 방법론은 Ⅰ장의 배타
# 사다리를 같은 함수로 다시 그리므로 맨 뒤다. defer 스크립트는 문서 순서대로
# 실행되니 이 배열의 순서가 곧 실행 순서다.
JS_FILES = ["engine.js", "charts.js", "hero.js", "chapter1.js", "chapter2.js",
            "chapter3.js", "lab.js", "method.js"]

# 조사 분리 의심 패턴 — 강조 태그 닫힘과 조사 사이의 줄바꿈
_JOSA = re.compile(
    r"</(?:b|strong|em|i)>[ \t]*\n[ \t]*"
    r"(?:이|가|을|를|은|는|의|와|과|로|다|이다|한다|된다)[ .,<]"
)
_LEFTOVER = re.compile(r"\{\{[A-Z_:.\w\-]+\}\}")


def _minify_json(path: Path) -> str:
    """JSON 을 한 줄로 줄이고 <script> 안에 넣어도 안전하게 이스케이프한다.

    `<`·`>`·`&`·U+2028·U+2029 는 JSON 문법에서 문자열 안에만 나올 수 있어
    통째로 치환해도 값이 변하지 않는다. `</script>` 조기 종료와 자바스크립트가
    U+2028 을 줄바꿈으로 읽는 문제를 동시에 막는다.
    """
    obj = json.loads(path.read_text(encoding="utf-8"))
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (s.replace("<", "\\u003c").replace(">", "\\u003e")
             .replace("&", "\\u0026")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _robots_tag() -> str:
    """색인 정책. 기본은 차단이고 --index 를 준 실행만 연다.

    자동 갱신 파이프라인은 플래그 없이 돌기 때문에 사람이 한 번 열어 두어도
    다음 자동 빌드가 다시 닫는다 — 열려면 그때마다 명시해야 한다.
    """
    if "--index" in sys.argv:
        return '<meta name="robots" content="index, follow">'
    return '<meta name="robots" content="noindex, nofollow, noarchive">'


def _git_commit() -> str:
    """빌드 스탬프용 커밋 짧은 해시. git 이 없거나 실패하면 'nogit'(빌드는 계속)."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "nogit"


def _require_sources() -> None:
    """선언한 원천이 전부 있는지 먼저 본다. 없으면 아무것도 만들지 않고 멈춘다."""
    declared = [SITE / "index.template.html"]
    declared += [SITE / "css" / name for name in CSS_FILES]
    declared += [SITE / "js" / name for name in JS_FILES]
    declared += [path for _name, path in DATA_MAP.values()]
    missing = [p for p in declared if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "빌드 원천 %d건 없음: %s — make analyze·make manifest 를 먼저 돌렸는지 확인하라"
            % (len(missing), " · ".join(str(p) for p in missing)))


def _substitute(tpl: str) -> str:
    """템플릿 플레이스홀더를 빌드 시점 값으로 바꾼다.

    데이터·스크립트 모두 defer 라 문서 순서대로 실행된다. 데이터 태그를 앞에 두면
    뒤따르는 스크립트가 window.__DATA_* 를 이미 있는 것으로 읽을 수 있다.
    """
    man = json.loads(DATA_MAP["DATA_MANIFEST"][1].read_text(encoding="utf-8"))
    cutoff = (man.get("data_cutoff") or "―").replace("-", ".")
    built = datetime.date.today().isoformat()
    subs = {
        "{{ROBOTS}}": _robots_tag(),
        "{{CSS_LINKS}}": "\n".join(
            '<link rel="stylesheet" href="css/%s">' % f for f in CSS_FILES),
        "{{DATA_SCRIPTS}}": "\n".join(
            '<script defer src="data/%s.js"></script>' % name
            for name, _path in DATA_MAP.values()),
        "{{JS_SCRIPTS}}": "\n".join(
            '<script defer src="js/%s"></script>' % f for f in JS_FILES),
        "{{DATA_CUTOFF}}": cutoff,
        "{{BUILT_AT}}": built,
        "{{BUILD_STAMP}}": "Commit %s · Data cutoff %s · Built %s"
                           % (_git_commit(), cutoff, built),
    }
    for ph, val in subs.items():
        tpl = tpl.replace(ph, val)
    return tpl


def _gate(tpl: str) -> None:
    """배포 전 마지막 두 검사. 하나라도 걸리면 빌드는 여기서 끝난다."""
    bad = _JOSA.findall(tpl)
    if bad:
        raise RuntimeError(
            "조사 분리 의심 %d건 — 태그와 조사를 붙이거나 조사를 태그 안으로: %s"
            % (len(bad), bad[:3]))
    leftover = _LEFTOVER.findall(tpl)
    if leftover:
        raise RuntimeError("미치환 플레이스홀더: %s" % sorted(set(leftover)))


def _minify_css(src: str) -> str:
    """주석과 불필요한 공백만 걷어내는 간이 최소화."""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"\s*([{}:;,>])\s*", r"\1", src)
    return re.sub(r";}", "}", src).strip() + "\n"


def _compress_js(src: Path) -> str:
    """terser 압축. 실패는 침묵하지 않는다 — 압축 안 된 소스를 몰래 내보내지 않는다."""
    r = subprocess.run(["npx", "--yes", "terser", str(src), "-c", "-m", "--comments", "false"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("terser 실패 %s: %s" % (src.name, (r.stderr or "")[:200]))
    return r.stdout


def build_dist() -> Path:
    """site/ → web/. 전 단계를 web.tmp/ 에 쌓은 뒤 마지막에 한 번 갈아 끼운다."""
    _require_sources()
    tpl = _substitute((SITE / "index.template.html").read_text(encoding="utf-8"))
    _gate(tpl)

    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "css").mkdir(parents=True)
    (TMP / "js").mkdir()
    (TMP / "data").mkdir()
    protect = "--no-protect" not in sys.argv

    (TMP / "index.html").write_text(tpl, encoding="utf-8")
    for name in CSS_FILES:
        src = (SITE / "css" / name).read_text(encoding="utf-8")
        (TMP / "css" / name).write_text(_minify_css(src) if protect else src,
                                        encoding="utf-8")
    for name in JS_FILES:
        src = SITE / "js" / name
        if protect:
            (TMP / "js" / name).write_text(_compress_js(src), encoding="utf-8")
        else:
            shutil.copy(src, TMP / "js" / name)
    static = SITE / "static"
    if static.is_dir():  # _headers·robots.txt·og.png — web/ 루트로 평면 복사
        for f in static.iterdir():
            # 하위 디렉터리를 조용히 건너뛰면 나중에 넣을 이미지 폴더가 소리 없이 사라진다
            if f.is_dir():
                shutil.copytree(f, TMP / f.name)
            else:
                shutil.copy(f, TMP / f.name)
    for key, (name, path) in DATA_MAP.items():
        (TMP / "data" / ("%s.js" % name)).write_text(
            "window.__%s = %s;\n" % (key, _minify_json(path)), encoding="utf-8")

    # 여기까지 왔으면 산출은 완성이다. 기존 web/ 은 지우지 않고 옆으로 밀어 둔 뒤
    # 새것을 제자리에 넣는다 — 지우다 실패해 반쪽만 남는 web/ 을 만들지 않으려는 것이다.
    old = WEB.with_name(WEB.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    retired = WEB.exists()
    if retired:
        WEB.rename(old)
    try:
        TMP.rename(WEB)
    except BaseException:
        # 새것을 못 넣었으면 밀어 둔 직전 산출을 제자리로 되돌린다. OSError 만 잡으면
        # 두 rename 사이에 Ctrl-C 가 들어왔을 때 web/ 이 사라진 채로 끝난다 —
        # 여기서 걸러야 할 것은 예외의 종류가 아니라 "web/ 이 빈자리로 남는 상태"다.
        if retired and not WEB.exists():
            old.rename(WEB)
        raise
    if old.exists():
        shutil.rmtree(old)

    files = [p for p in WEB.rglob("*") if p.is_file()]
    print("dist 빌드: %s (%.0f KB, %d개 파일)"
          % (WEB, sum(p.stat().st_size for p in files) / 1024, len(files)))
    return WEB


if __name__ == "__main__":
    build_dist()
