"""사이트 빌드(site/ → web/) 검사 — 산출·게이트·원자성.

빌드는 저장소 루트의 web/ 을 통째로 갈아 끼우는 부작용이 있다. 그래서 테스트는
모듈 상수 WEB·TMP 를 임시 디렉터리로 갈아 끼우고 돌린다. 반면 데이터 원천
(out/*.json · data/DATA_MANIFEST.json)은 실물을 그대로 읽힌다 — 빌드가 실제
산출을 싣는지가 검사 대상이기 때문에 가짜 JSON 으로 바꾸면 검사가 헛돈다.

게이트 검사(미치환 플레이스홀더·조사 분리)만은 고의로 망가뜨린 템플릿이 필요해
SITE 를 임시 사이트로 갈아 끼운다.
"""

import json
import re
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from src.build import assemble

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "window.__DATA_MARKET = "


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """산출 경로만 임시 디렉터리로 옮긴 assemble 모듈."""
    monkeypatch.setattr(assemble, "WEB", tmp_path / "web")
    monkeypatch.setattr(assemble, "TMP", tmp_path / "web.tmp")
    return assemble


def _fake_site(tmp_path, body, js=None):
    """고의로 망가뜨릴 수 있는 최소 사이트 소스. CSS·JS 는 실물을 복사한다.

    선언(CSS_FILES·JS_FILES)에 적힌 파일이 없으면 빌드가 게이트에 닿기도 전에
    멈춘다. 여기서 검사하려는 것은 템플릿 게이트라, 자산은 실물을 그대로 둔다.
    """
    site = tmp_path / "site"
    (site / "css").mkdir(parents=True)
    (site / "static").mkdir()
    (site / "js").mkdir()
    for name in assemble.CSS_FILES:
        shutil.copy(ROOT / "site" / "css" / name, site / "css" / name)
    for name in assemble.JS_FILES:
        shutil.copy(ROOT / "site" / "js" / name, site / "js" / name)
    for name, src in (js or {}).items():
        (site / "js" / name).write_text(src, encoding="utf-8")
    (site / "index.template.html").write_text(
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        "{{ROBOTS}}\n{{CSS_LINKS}}\n</head>\n<body>\n"
        + body
        + "\n{{DATA_SCRIPTS}}\n{{JS_SCRIPTS}}\n</body>\n</html>\n",
        encoding="utf-8",
    )
    return site


# ------------------------------------------------------------------ #
# (a) 산출 — index.html + 데이터 5종 + CSS + static 평면 복사
# ------------------------------------------------------------------ #
def test_dist_produces_index_and_five_data_files(sandbox):
    web = sandbox.build_dist()
    assert (web / "index.html").is_file()
    assert sorted(p.name for p in (web / "data").glob("*.js")) == [
        "manifest.js", "market.js", "pf.js", "trades.js", "underwriting.js"]
    for name in sandbox.CSS_FILES:
        assert (web / "css" / name).is_file()
    assert (web / "_headers").is_file(), "static/ 은 web/ 루트로 평면 복사돼야 한다"


def test_index_links_every_declared_asset(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    for name in sandbox.CSS_FILES:
        assert 'href="css/%s"' % name in html
    for name, _ in sandbox.DATA_MAP.values():
        assert 'src="data/%s.js"' % name in html
    assert "noindex" in html, "기본은 색인 차단이다"


# ------------------------------------------------------------------ #
# (a') 외부 요청 0 — 밖을 부르지 않는 것이 이 사이트의 계약이다
# ------------------------------------------------------------------ #
SITE_URL = "https://cheungwi.pages.dev"

# 밖을 부르는 방법들. 하나라도 굽힌 산출에 남으면 그 사이트는 더 이상 자족적이지
# 않고, 상대의 화면에서 그 자리는 빈칸이 되거나 그의 방문이 남의 로그에 남는다.
NETWORK_CALLS = ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource",
                 "sendBeacon", "importScripts", "@import", "navigator.connection")
_PROTOCOL_RELATIVE = re.compile(r"""(?:src|href)\s*=\s*["']//|url\(\s*["']?//""")
_EXTERNAL_HTTPS = re.compile(r"https://(?!cheungwi\.pages\.dev)")


def _shipped(web):
    """구워진 산출 가운데 브라우저가 실행·해석하는 것 전부(index·css·js·data)."""
    return sorted(p for p in web.rglob("*")
                  if p.suffix in {".html", ".css", ".js"} and p.is_file())


def _outside_calls(name, src):
    """밖을 부르는 자리 목록. 빈 리스트면 그 파일은 자족적이다."""
    bad = []
    if "http://" in src:
        bad.append("%s: 평문 http" % name)
    hit = _EXTERNAL_HTTPS.search(src)
    if hit:
        bad.append("%s: 외부 호스트 %r" % (name, src[hit.start():hit.start() + 48]))
    if _PROTOCOL_RELATIVE.search(src):
        bad.append("%s: 프로토콜 상대 주소" % name)
    for call in NETWORK_CALLS:
        if call in src:
            bad.append("%s: %s" % (name, call))
    return bad


def test_the_built_site_calls_nothing_from_outside(sandbox):
    """`test_og` 가 카드 원본에 걸어 둔 계약을 굽힌 사이트 전체로 옮긴 것이다.

    카드 한 장만 자족적이어도 소용이 없다. 지면이 폰트 하나를 밖에서 끌어오는
    순간 그 요청은 방문자의 화면에서 남의 로그가 되고, 그 호스트가 죽는 날 지면도
    함께 무너진다. 그래서 "외부 요청 0"은 눈으로 지키는 규율이 아니라 빌드마다
    기계가 세는 수여야 한다.
    """
    files = _shipped(sandbox.build_dist())
    assert len(files) >= 15, "굽힌 산출이 이렇게 적을 리 없다: %d개" % len(files)
    bad = []
    for path in files:
        bad += _outside_calls(path.name, path.read_text(encoding="utf-8"))
    assert bad == [], "굽힌 산출이 밖을 부른다 — %s" % " · ".join(bad)


def test_the_outside_call_check_is_not_vacuous():
    """검사가 헛돌지 않는다는 증거 — 심어 둔 다섯 갈래를 전부 잡는다."""
    for planted in ('<img src="http://example.com/a.png">',
                    '<link href="https://fonts.googleapis.com/css2?f=X">',
                    '<script src="//cdn.example.com/x.js"></script>',
                    "<script>fetch('/x')</script>",
                    "<style>@import url(x.css);</style>"):
        assert _outside_calls("심은 것", planted), planted
    # 제 집을 가리키는 절대 URL 은 외부 호출이 아니다(og:image 가 그렇다)
    assert _outside_calls("자기 자신", '<meta content="%s/og.png">' % SITE_URL) == []


def test_every_asset_the_index_points_at_is_shipped_beside_it(sandbox):
    """가리키는 자리에 파일이 없으면 그 요청은 404 이거나 밖으로 나간다."""
    web = sandbox.build_dist()
    html = (web / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert refs, "index 가 아무 자산도 가리키지 않는다"
    for ref in refs:
        if ref.startswith("#"):
            continue
        rel = ref[len(SITE_URL) + 1:] if ref.startswith(SITE_URL + "/") else ref
        assert not rel.startswith(("http", "//")), "밖을 가리킨다: %s" % ref
        assert (web / rel).is_file(), "가리키는 자리에 파일이 없다: %s" % ref


# ------------------------------------------------------------------ #
# (d) window.__DATA_* 접두 정확성
# ------------------------------------------------------------------ #
def test_data_wrapper_prefix_is_exact(sandbox):
    web = sandbox.build_dist()
    src = (web / "data" / "market.js").read_text(encoding="utf-8")
    assert src.startswith(PREFIX)
    assert src.endswith(";\n")
    payload = json.loads(src[len(PREFIX):-2])
    assert "regions" in payload and "rates" in payload


def test_every_key_wraps_its_own_file(sandbox):
    web = sandbox.build_dist()
    for key, (name, path) in sandbox.DATA_MAP.items():
        src = (web / "data" / ("%s.js" % name)).read_text(encoding="utf-8")
        head = "window.__%s = " % key
        assert src.startswith(head)
        assert json.loads(src[len(head):-2]) == json.loads(path.read_text(encoding="utf-8"))


def test_data_is_escaped_for_script_context(sandbox):
    """<·>·U+2028 은 JSON 유니코드 이스케이프로 굽는다(문법 동등, 삽입 안전)."""
    src = (sandbox.build_dist() / "data" / "manifest.js").read_text(encoding="utf-8")
    assert "<" not in src and ">" not in src
    assert "\u2028" not in src and "\u2029" not in src


# ------------------------------------------------------------------ #
# (b) 미치환 플레이스홀더 게이트
# ------------------------------------------------------------------ #
def test_unreplaced_placeholder_fails(sandbox, tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SITE", _fake_site(tmp_path, "<p>{{UNKNOWN_TOKEN}}</p>"))
    with pytest.raises(RuntimeError, match="미치환"):
        sandbox.build_dist()


# ------------------------------------------------------------------ #
# (b') 산문 속의 수 — 지면이 제 상수를 들고 있지 않다
# ------------------------------------------------------------------ #
def _artifact_counts():
    man = json.loads((ROOT / "data" / "DATA_MANIFEST.json").read_text(encoding="utf-8"))
    pf = json.loads((ROOT / "out" / "pf_case.json").read_text(encoding="utf-8"))
    seed = [s for s in man["sources"] if s["key"] == "seed_buildings"][0]["rows"]
    return seed, pf["land_price_context"]["seed_land_price_won_m2"]["n"], pf["stress"]["n"]


def test_the_prose_numbers_are_counted_from_the_artifacts(sandbox):
    """메타 설명·표제란처럼 스크립트가 닿지 않는 자리도 제 수를 지어내지 않는다."""
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    seed_n, parcels, stress_n = _artifact_counts()
    assert "프라임 오피스 %d동" % seed_n in html
    assert "부채의 물이 차오른다 — 서울 프라임 오피스 %d동" % seed_n in html
    assert "시드 %d동의 대표 필지" % seed_n in html
    assert "시드 %d필지" % parcels in html
    assert "스트레스 %d행" % stress_n in html


def test_a_grown_seed_moves_every_sentence_that_counts_it(sandbox, tmp_path, monkeypatch):
    """시드가 늘어난 날 문장만 옛 목록을 가리키면, 틀린 것은 데이터가 아니라 설명이다."""
    man = json.loads((ROOT / "data" / "DATA_MANIFEST.json").read_text(encoding="utf-8"))
    seed_n = _artifact_counts()[0]
    for src in man["sources"]:
        if src["key"] == "seed_buildings":
            src["rows"] = 41
    path = tmp_path / "DATA_MANIFEST.json"
    path.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    moved = dict(sandbox.DATA_MAP)
    moved["DATA_MANIFEST"] = ("manifest", path)
    monkeypatch.setattr(sandbox, "DATA_MAP", moved)

    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    assert "프라임 오피스 41동" in html and "시드 41동" in html
    assert "%d동" % seed_n not in html, "지면 어딘가가 아직 옛 동수를 들고 있다"


def test_a_ledger_without_the_seed_source_stops_the_build(sandbox, tmp_path, monkeypatch):
    """세지 못하면 짓지 않는다 — 빈칸이나 지어낸 수가 배포로 나가지 않게."""
    man = json.loads((ROOT / "data" / "DATA_MANIFEST.json").read_text(encoding="utf-8"))
    man["sources"] = [s for s in man["sources"] if s["key"] != "seed_buildings"]
    path = tmp_path / "DATA_MANIFEST.json"
    path.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    moved = dict(sandbox.DATA_MAP)
    moved["DATA_MANIFEST"] = ("manifest", path)
    monkeypatch.setattr(sandbox, "DATA_MAP", moved)
    with pytest.raises(RuntimeError, match="시드 원천"):
        sandbox.build_dist()


# ------------------------------------------------------------------ #
# (c) 한국어 조사 분리 게이트
# ------------------------------------------------------------------ #
def test_josa_separation_fails(sandbox, tmp_path, monkeypatch):
    body = "<p><strong>유효임대료</strong>\n가 국고채를 밑돈다.</p>"
    monkeypatch.setattr(sandbox, "SITE", _fake_site(tmp_path, body))
    with pytest.raises(RuntimeError, match="조사 분리"):
        sandbox.build_dist()


def test_josa_attached_passes(sandbox, tmp_path, monkeypatch):
    body = "<p><strong>유효임대료</strong>가 국고채를 밑돈다.</p>"
    monkeypatch.setattr(sandbox, "SITE", _fake_site(tmp_path, body))
    assert (sandbox.build_dist() / "index.html").is_file()


# ------------------------------------------------------------------ #
# (e) 원자 스왑 — 실패한 빌드는 기존 web/ 을 건드리지 않는다
# ------------------------------------------------------------------ #
def test_failed_build_leaves_previous_web_intact(sandbox, monkeypatch):
    web = sandbox.build_dist()
    (web / "index.html").write_text("SENTINEL", encoding="utf-8")

    def boom(_path):
        raise RuntimeError("고의 실패")

    monkeypatch.setattr(sandbox, "_minify_json", boom)  # 데이터 굽기 = 스왑 직전 단계
    with pytest.raises(RuntimeError, match="고의 실패"):
        sandbox.build_dist()
    assert (web / "index.html").read_text(encoding="utf-8") == "SENTINEL"
    assert sorted(p.name for p in (web / "data").glob("*.js")) != [], "기존 산출도 그대로다"


@pytest.mark.parametrize("boom", [OSError, KeyboardInterrupt])
def test_swap_failure_restores_previous_web(sandbox, monkeypatch, boom):
    """스왑 한복판에서 끊겨도 web/ 이 빈자리로 남지 않는다.

    직전 산출을 옆으로 밀어 둔 뒤 새것을 제자리에 넣기 전에 실패하는 구간이 이
    빌드에서 web/ 이 사라질 수 있는 유일한 창이다. rename 두 번 중 두 번째만
    터뜨려 그 창을 정확히 겨눈다. KeyboardInterrupt 까지 보는 이유는, 사람이
    Ctrl-C 를 누른 시점이 하필 그 창일 때도 사이트는 남아 있어야 하기 때문이다.
    """
    web = sandbox.build_dist()
    (web / "index.html").write_text("SENTINEL", encoding="utf-8")

    real_rename = Path.rename
    calls = []

    def rename(self, target):
        calls.append((self.name, Path(target).name))
        if len(calls) == 2:  # ① web→web.old ② web.tmp→web ③ 복원 web.old→web
            raise boom("고의 실패: 스왑 중단")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(boom, match="스왑 중단"):
        sandbox.build_dist()

    assert calls[1] == ("web.tmp", "web"), "두 번째 rename 이 스왑이어야 겨냥이 맞다"
    assert len(calls) == 3 and calls[2] == ("web.old", "web"), "복원 rename 이 돌아야 한다"
    assert (web / "index.html").read_text(encoding="utf-8") == "SENTINEL"
    assert not web.with_name("web.old").exists(), "밀어 둔 자리는 비어 있어야 한다"


# ------------------------------------------------------------------ #
# 선언과 실재 — 상수에 적힌 파일이 없으면 시끄럽게 멈춘다
# ------------------------------------------------------------------ #
def test_declared_css_must_exist(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "CSS_FILES", list(sandbox.CSS_FILES) + ["없는파일.css"])
    with pytest.raises(FileNotFoundError, match="없는파일"):
        sandbox.build_dist()


def test_declared_data_must_exist(sandbox, monkeypatch):
    bogus = dict(sandbox.DATA_MAP)
    bogus["DATA_NOWHERE"] = ("nowhere", ROOT / "out" / "nowhere.json")
    monkeypatch.setattr(sandbox, "DATA_MAP", bogus)
    with pytest.raises(FileNotFoundError, match="nowhere.json"):
        sandbox.build_dist()


# ------------------------------------------------------------------ #
# 토큰 — 라이트·다크 두 벌, 수동 토글이 시스템 설정을 이긴다
# ------------------------------------------------------------------ #
def test_tokens_define_both_themes():
    css = (ROOT / "site" / "css" / "tokens.css").read_text(encoding="utf-8")
    for token in ("--paper", "--ink", "--stratum-1", "--stratum-2", "--stratum-3",
                  "--senior", "--mezz", "--equity", "--waterline", "--alert"):
        assert css.count(token + ":") >= 4, "%s 는 네 벌(기본·미디어·수동 2종) 다 있어야 한다" % token
    assert "#f7f5f1" in css and "#14120f" in css      # 낮의 종이 · 밤의 종이
    assert "#3d6b8e" in css and "#4f9bb8" in css      # 수면 · 야간 수면
    # 수동 토글이 미디어쿼리 뒤에 와야 양방향으로 이긴다
    assert css.index('[data-theme="dark"]') > css.index("prefers-color-scheme")
    assert '[data-theme="light"]' in css


def test_minified_css_keeps_theme_switches(sandbox):
    css = (sandbox.build_dist() / "css" / "tokens.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme" in css
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css
    assert "/*" not in css, "주석은 압축에서 빠진다"


# ------------------------------------------------------------------ #
# 서장 — 조형이 붙을 자리와 그것을 채울 스크립트가 함께 나가야 한다
# ------------------------------------------------------------------ #
def test_prologue_has_the_mounts_the_hero_writes_into(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    for mount in ('id="hero-tabs"', 'id="hero-plate"', 'id="hero-reading"',
                  'id="hero-scale"', 'id="gauge"'):
        assert mount in html, "%s 가 없으면 hero.js 는 조용히 아무것도 그리지 않는다" % mount
    assert 'role="tablist"' in html and 'role="tabpanel"' in html
    assert "임대의 층이 쌓이고, 부채의 물이 차오른다." in html
    assert "수지" in html and "순환" in html and "시차" in html, "시리즈 계보"


def test_scripts_load_in_dependency_order(sandbox):
    """hero 는 로드 시점에 엔진과 조형을 이미 있는 것으로 읽는다."""
    assert sandbox.JS_FILES[:3] == ["engine.js", "charts.js", "hero.js"]
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    order = [html.index('src="js/%s"' % f) for f in sandbox.JS_FILES]
    assert order == sorted(order)
    assert all(html.index('src="data/%s.js"' % n) < order[0]
               for n, _ in sandbox.DATA_MAP.values()), "데이터가 스크립트보다 앞선다"


def test_hero_css_ships_and_keeps_both_themes(sandbox):
    css = (sandbox.build_dist() / "css" / "hero.css").read_text(encoding="utf-8")
    assert "--win-lit" in css and "--win-off" in css
    assert css.count("--win-lit:") >= 4, "창의 불빛도 네 벌(기본·미디어·수동 2종)이다"
    assert "prefers-color-scheme" in css and '[data-theme="dark"]' in css


def test_every_in_figure_label_size_goes_through_the_scale_factor(sandbox):
    """도면 라벨의 font-size 는 hero.js 가 넘기는 `--fig-k` 를 곱해야 한다.

    한 줄이라도 맨 px 로 남으면 그 라벨만 좁은 화면에서 8px 로 찍힌다 — 눈으로는
    "작네" 로 지나가고 검사는 통과하는, 가장 오래 사는 종류의 결함이다.
    """
    css = (sandbox.build_dist() / "css" / "hero.css").read_text(encoding="utf-8")
    labels = re.findall(r"\.(?:lab|is-compact \.lab|chart \.lab)[\w-]*[^{}]*"
                        r"\{[^{}]*font-size:([^;}]+)", css)
    assert len(labels) >= 10, "라벨 규칙이 이만큼은 있어야 한다: %d" % len(labels)
    for size in labels:
        assert "--fig-k" in size, "계수를 안 거치는 라벨 크기가 있다: %s" % size.strip()


# ------------------------------------------------------------------ #
# Ⅰ장·Ⅱ장 — 마운트와 활자 규약
# ------------------------------------------------------------------ #
def test_the_chapters_have_the_mounts_their_scripts_write_into(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    for mount in ('id="ch1-filter"', 'id="ch1-cards"', 'id="ch1-ledger-reading"',
                  'id="ch1-trades-plot"', 'id="ch1-ladder-plate"',
                  'id="ch2-plate"', 'id="ch2-knobs"', 'id="ch2-readings"',
                  'id="ch2-banners"', 'id="ch2-spec"'):
        assert mount in html, "%s 가 없으면 그 장은 조용히 비어 있는다" % mount
    # 슬라이더의 결과는 눈으로만 읽히지 않는다
    assert 'id="ch2-live"' in html and 'aria-live="polite"' in html
    assert "대장 개통 대기" in html, "정직성 표기는 스크립트가 아니라 지면에도 있다"


def test_chapter_scripts_load_after_the_shapes_they_borrow(sandbox):
    """장은 charts·engine 에 더해 hero(판형 부속·서식)까지 읽는다.

    실험실은 한 걸음 더 나아가 chapter3 의 `fitFigures` 를 빌려 쓰므로 반드시 그
    뒤에 온다 — 순서가 뒤집히면 실험실의 도면만 계수를 못 받아 라벨이 작아진다.
    """
    assert sandbox.JS_FILES == ["engine.js", "charts.js", "hero.js",
                                "chapter1.js", "chapter2.js", "chapter3.js",
                                "lab.js", "method.js"]
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    order = [html.index('src="js/%s"' % f) for f in sandbox.JS_FILES]
    assert order == sorted(order)


def test_chapters_css_ships_and_keeps_both_themes(sandbox):
    css = (sandbox.build_dist() / "css" / "chapters.css").read_text(encoding="utf-8")
    # 계측기는 `.hero` 밖에 서므로 창의 불빛을 스스로 선언해야 한다
    assert css.count("--win-lit:") >= 4
    assert "prefers-color-scheme" in css and '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css


def test_chapter_figures_have_exactly_one_lettering_height_per_plate(sandbox):
    """장 도면의 활자 높이는 판형마다 하나다 — `--fig-k` 의 하한이 그 위에 선다.

    크기가 둘 이상이면 최소 선언값이 무엇인지가 CSS 와 JS 두 곳에서 갈리고,
    계수는 계속 1 인 채로 가장 작은 라벨만 조용히 8px 로 찍힌다.
    """
    css = (sandbox.build_dist() / "css" / "chapters.css").read_text(encoding="utf-8")
    sizes = re.findall(r"\.ch-fig[\w.-]* text\{[^{}]*font-size:([^;}]+)", css)
    assert len(sizes) == 2, "판형 둘, 규칙 둘이어야 한다: %s" % sizes
    for size in sizes:
        assert "--fig-k" in size, "계수를 안 거치는 라벨 크기가 있다: %s" % size.strip()
    assert any("11px" in s for s in sizes) and any("12px" in s for s in sizes)
    # 낱개 라벨 클래스가 제 크기를 따로 선언하면 위의 "하나"가 깨진다
    stray = re.findall(r"\.lab[\w-]*[^{}]*\{[^{}]*font-size:([^;}]+)", css)
    assert not stray, "장 도면의 라벨이 제 크기를 따로 선언했다: %s" % stray


# ------------------------------------------------------------------ #
# Ⅲ장·실험실 — 마운트·활자 규약·낭독
# ------------------------------------------------------------------ #
def test_the_time_chapter_and_the_lab_have_the_mounts_their_scripts_write_into(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    for mount in ('id="ch3-deposit"', 'id="ch3-legend"', 'id="ch3-deposit-reading"',
                  'id="ch3-stress"', 'id="ch3-stress-reading"', 'id="ch3-ladder"',
                  'id="ch3-ladder-reading"', 'id="ch3-land"', 'id="ch3-land-reading"',
                  'id="ch3-land-verdict"', 'id="ch3-spec"',
                  'id="lab-fields"', 'id="lab-plate"', 'id="lab-readings"',
                  'id="lab-banners"', 'id="lab-reading"', 'id="lab-fixed"',
                  'id="lab-reset"'):
        assert mount in html, "%s 가 없으면 그 자리는 조용히 빈다" % mount
    assert 'id="lab-live"' in html and 'role="status"' in html
    assert 'href="#lab"' in html, "실험실은 앱바에서 닿을 수 있어야 한다"
    assert "가상 사업지" in html, "정직성 표기는 스크립트가 아니라 지면에도 있다"


def test_chapter3_css_ships_and_keeps_both_themes(sandbox):
    css = (sandbox.build_dist() / "css" / "chapter3.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme" in css
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css
    for token in ("--stratum-3", "--senior", "--alert", "--pos", "--waterline"):
        assert token in css, "%s 를 쓰지 않는다면 색이 어디선가 하드코딩됐다" % token
    assert not re.findall(r"#[0-9a-fA-F]{6}\b", css), \
        "Ⅲ장이 새로 만드는 색은 없다 — 팔레트의 단일 출처는 tokens.css 다"


def test_the_time_plates_declare_no_lettering_height_of_their_own(sandbox):
    """활자 높이는 chapters.css 의 두 줄뿐이다 — 여기서 다시 적으면 규약이 깨진다.

    한 줄이라도 여기에 크기를 선언하면 `--fig-k` 의 하한 계산이 두 곳으로 갈리고,
    계수는 1 인 채로 그 라벨만 좁은 화면에서 8px 로 찍힌다.
    """
    css = (sandbox.build_dist() / "css" / "chapter3.css").read_text(encoding="utf-8")
    stray = re.findall(r"\.(?:lab|ch-fig)[\w.-]*[^{}]*text?[^{}]*"
                       r"\{[^{}]*font-size:([^;}]+)", css)
    assert not stray, "Ⅲ장 도면이 제 활자 높이를 따로 선언했다: %s" % stray
    plates = re.findall(r"\.ch-fig[\w.-]* text\{[^{}]*font-size:([^;}]+)", css)
    assert not plates


# ------------------------------------------------------------------ #
# terser — 압축 실패는 침묵하지 않는다
# ------------------------------------------------------------------ #
def _terser_stub(returncode, stdout, stderr=""):
    real = subprocess.run

    def run(cmd, *a, **kw):
        if cmd and cmd[0] == "npx":
            return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        return real(cmd, *a, **kw)

    return run


def test_terser_failure_stops_the_build(sandbox, tmp_path, monkeypatch):
    site = _fake_site(tmp_path, "<p>본문</p>", js={"app.js": "console.log(1)\n"})
    monkeypatch.setattr(sandbox, "SITE", site)
    monkeypatch.setattr(sandbox, "JS_FILES", ["app.js"])
    monkeypatch.setattr(sandbox.subprocess, "run", _terser_stub(1, "", "구문 오류"))
    with pytest.raises(RuntimeError, match="terser"):
        sandbox.build_dist()


def test_terser_output_is_written(sandbox, tmp_path, monkeypatch):
    site = _fake_site(tmp_path, "<p>본문</p>", js={"app.js": "console.log(1)\n"})
    monkeypatch.setattr(sandbox, "SITE", site)
    monkeypatch.setattr(sandbox, "JS_FILES", ["app.js"])
    monkeypatch.setattr(sandbox.subprocess, "run", _terser_stub(0, "console.log(1);"))
    web = sandbox.build_dist()
    assert (web / "js" / "app.js").read_text(encoding="utf-8") == "console.log(1);"
    assert '<script defer src="js/app.js"></script>' in \
        (web / "index.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# 멱등 — 같은 날 두 번 구우면 같은 바이트
# ------------------------------------------------------------------ #
def test_build_is_idempotent(sandbox):
    first = {p.relative_to(sandbox.WEB): p.read_bytes()
             for p in sandbox.build_dist().rglob("*") if p.is_file()}
    second = {p.relative_to(sandbox.WEB): p.read_bytes()
              for p in sandbox.build_dist().rglob("*") if p.is_file()}
    assert first == second


# ------------------------------------------------------------------ #
# 방법론 — 인용의 자리와 그것을 채울 스크립트
# ------------------------------------------------------------------ #
def _rule(css, selector):
    """압축된 CSS 에서 선택자 하나의 선언 블록을 꺼낸다(정확 일치·첫 규칙)."""
    hit = re.search(re.escape(selector) + r"\{([^{}]*)\}", css)
    return hit.group(1) if hit else ""


def test_the_method_page_has_the_mounts_its_script_writes_into(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    for mount in ('id="method-manifest"', 'id="method-manifest-lines"',
                  'id="method-estimate"', 'id="method-ladder"',
                  'id="method-matching-reading"', 'id="method-checks"',
                  'id="method-checks-tally"',
                  'id="method-ledger"', 'id="method-parked"', 'id="method-spec"'):
        assert mount in html, "%s 가 없으면 방법론은 조용히 빈다" % mount
    assert "잘 맞는 척하지 않는다" in html
    assert 'href="#method"' in html, "방법론은 앱바에서 닿을 수 있어야 한다"
    assert "chapter-slot" not in html, "채워진 자리에는 임시 상자가 남지 않는다"


def test_the_method_script_loads_after_everything_it_quotes(sandbox):
    """방법론은 Ⅰ장의 배타 사다리를 **같은 함수로** 다시 그린다."""
    assert sandbox.JS_FILES[-1] == "method.js"
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/method.js"') > html.index('src="js/chapter1.js"')


def test_method_css_ships_and_keeps_both_themes(sandbox):
    css = (sandbox.build_dist() / "css" / "method.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme" in css
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css
    assert not re.findall(r"#[0-9a-fA-F]{6}\b", css), \
        "방법론이 새로 만드는 색은 없다 — 팔레트의 단일 출처는 tokens.css 다"


# ------------------------------------------------------------------ #
# 이월 — 눈금의 겹침과 빈 셀
# ------------------------------------------------------------------ #
def test_the_reference_tick_label_sits_on_a_line_of_its_own(sandbox):
    """「기준」 글자와 최소·최대 라벨이 한 줄에 있으면 좁은 손잡이에서 겹친다.

    강남·여의도마포의 공실 눈금에서 「기준」과 「0.0%」가 4.5~9.2px 겹치는 것이
    1020px 이상 전 구간에서 실측됐다(Task 4 이월). 삼각 표식은 트랙 바로 아래에
    남기고 글자만 둘째 줄로 내린다 — 둘 다 같은 `--rest` 를 본다.
    """
    css = (sandbox.build_dist() / "css" / "chapters.css").read_text(encoding="utf-8")
    rest = _rule(css, ".knob-rest")
    top = re.search(r"top:(\d+(?:\.\d+)?)px", rest)
    assert top and float(top.group(1)) >= 13, \
        "「기준」이 첫 줄을 벗어나지 못했다: %s" % rest
    scale = _rule(css, ".knob-scale")
    assert "padding-bottom" in scale, "둘째 줄 자리를 미리 비워 두지 않았다"
    assert ".knob-rest{display:none}" not in css, \
        "겹침이 해소됐으므로 좁은 화면에서 기준값을 지울 이유가 없다"


def test_the_gauge_grid_never_paints_a_cell_that_has_no_card(sandbox):
    """권역 셋이 2열로 접히면 넷째 칸이 빈다(768px).

    격자에 바탕을 깔아 1px 괘선을 만드는 수법은 그 빈칸을 **hairline 블록**으로
    남긴다 — 화면에서는 "카드가 하나 더 있는데 비어 있다"로 읽힌다. 괘선은
    격자가 아니라 카드가 들고 있어야 빈칸이 그냥 종이로 남는다.
    """
    css = (sandbox.build_dist() / "css" / "hero.css").read_text(encoding="utf-8")
    grid = _rule(css, ".g-grid")
    assert "background" not in grid, "격자가 바탕을 칠하면 빈 셀이 블록으로 남는다"
    card = _rule(css, ".g-card")
    assert "outline" in card or "box-shadow" in card, \
        "괘선을 카드가 들지 않으면 칸막이가 사라진다"
