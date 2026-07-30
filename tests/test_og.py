"""OG 카드 검사 — 원본(og_card.html)·산출(og.png)·지면의 연결.

소셜 미리보기는 아무도 로컬에서 보지 않는다. 링크를 던진 뒤 상대의 화면에서
처음 보이고, 거기서 깨져 있으면 고칠 때까지 그 상태로 돌아다닌다. 그래서 이
파일이 붙드는 것은 그림의 아름다움이 아니라 **연결**이다.

  ① 원본이 1200×630 을 스스로 선언하는가 (스크린샷 창 크기와 카드 크기가 갈리면
     여백이 붙거나 잘린다)
  ② 원본이 외부를 부르지 않는가 (file:// 로 찍으므로 네트워크 자원은 빈칸이 된다)
  ③ 산출 PNG 가 실제로 1200×630 인가 (IHDR 을 직접 읽는다 — 이름만 og.png 인
     0바이트 파일이 커밋되는 사고를 막는다)
  ④ 빌드가 그 PNG 를 web/ 으로 옮기고, index 의 og:image 가 **그 자리**를
     가리키는가 (메타는 있는데 파일이 없는 404 미리보기가 가장 흔한 결말이다)
"""

import re
from pathlib import Path

import pytest

from src.build import assemble

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "build" / "og_card.html"
PNG = ROOT / "site" / "static" / "og.png"
SITE_URL = "https://cheungwi.pages.dev"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """산출 경로만 임시 디렉터리로 옮긴 assemble 모듈(test_assemble 과 같은 규약)."""
    monkeypatch.setattr(assemble, "WEB", tmp_path / "web")
    monkeypatch.setattr(assemble, "TMP", tmp_path / "web.tmp")
    return assemble


def png_size(path):
    """PNG 헤더(IHDR)에서 폭·높이를 읽는다. 외부 라이브러리 없이 8+8 바이트면 된다."""
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "PNG 매직이 아니다: %s" % path
    assert raw[12:16] == b"IHDR", "첫 청크가 IHDR 이 아니다"
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


# ------------------------------------------------------------------ #
# 원본 — 카드는 제 크기를 스스로 알고, 밖을 부르지 않는다
# ------------------------------------------------------------------ #
def test_the_card_source_exists_and_declares_its_own_size():
    assert CARD.is_file(), "카드 원본이 없다 — og.png 는 손으로 그린 그림이 아니다"
    html = CARD.read_text(encoding="utf-8")
    assert "1200px" in html and "630px" in html, \
        "카드가 제 크기를 선언하지 않으면 창 크기와 어긋난 여백이 찍힌다"


def test_the_card_says_who_it_is():
    html = CARD.read_text(encoding="utf-8")
    assert "층위" in html and "層位" in html
    assert "임대의 층이 쌓이고, 부채의 물이 차오른다" in html, "서장의 한 줄이 카드의 한 줄이다"
    assert "cheungwi.pages.dev" in html
    for sibling in ("수지", "순환", "시차"):
        assert sibling in html, "시리즈 계보가 카드에도 남는다: %s" % sibling


def test_the_card_calls_nothing_from_outside():
    """file:// 로 찍히므로 외부 자원은 그냥 빈칸이 된다 — 없는 것이 계약이다.

    같은 계약을 굽힌 사이트 전체에 건 것은
    `test_assemble.test_the_built_site_calls_nothing_from_outside` 다 — 카드 한 장만
    자족적이어도 지면이 밖을 부르면 소용이 없다.
    """
    html = CARD.read_text(encoding="utf-8")
    assert "http://" not in html
    assert not re.search(r"https://(?!cheungwi\.pages\.dev)", html), \
        "외부 호스트를 부른다 — 헤드리스 스크린샷에서 그 자리는 빈칸으로 찍힌다"
    for forbidden in ("<img", "@import", "fetch(", "<script"):
        assert forbidden not in html, "%s 는 카드에 있을 자리가 없다" % forbidden


def test_the_card_draws_the_tower_in_section():
    """타워 단면 미니어처 — 창·지층·수면이 다 있어야 서장의 축소판이다."""
    html = CARD.read_text(encoding="utf-8")
    assert "<svg" in html
    for token in ("win-lit", "win-off", "senior", "mezz", "equity", "waterline"):
        assert token in html, "%s 가 없으면 단면이 아니라 사각형이다" % token


# ------------------------------------------------------------------ #
# 산출 — 이름만 og.png 인 파일은 통과하지 못한다
# ------------------------------------------------------------------ #
def test_the_rendered_card_is_exactly_twelve_hundred_by_six_thirty():
    assert PNG.is_file(), "og.png 가 없다 — `make og` 로 굽고 커밋한다"
    assert png_size(PNG) == (1200, 630)


def test_the_rendered_card_is_small_enough_to_travel():
    kb = PNG.stat().st_size / 1024
    assert 8 < kb < 500, "og.png 가 %d KB 다 — 빈 그림이거나 저장소를 불린다" % kb


# ------------------------------------------------------------------ #
# 연결 — 메타가 가리키는 자리에 파일이 있어야 미리보기가 뜬다
# ------------------------------------------------------------------ #
def test_the_build_ships_the_card_to_the_web_root(sandbox):
    web = sandbox.build_dist()
    assert (web / "og.png").is_file(), "static/ 평면 복사가 og.png 를 빠뜨렸다"
    assert png_size(web / "og.png") == (1200, 630)


def test_the_index_points_at_the_card_that_is_actually_there(sandbox):
    web = sandbox.build_dist()
    html = (web / "index.html").read_text(encoding="utf-8")
    hit = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    assert hit, "og:image 가 없으면 링크는 글자만으로 돌아다닌다"
    url = hit.group(1)
    assert url.startswith(SITE_URL + "/"), "og:image 는 절대 URL 이어야 한다: %s" % url
    assert (web / url[len(SITE_URL) + 1:]).is_file(), \
        "메타가 가리키는 자리에 파일이 없다: %s" % url


def test_the_index_declares_the_card_size_and_the_large_card_type(sandbox):
    html = (sandbox.build_dist() / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert re.search(r'<meta property="og:image:alt" content="[^"]{10,}"', html), \
        "그림을 못 보는 사람에게도 카드는 한 줄을 남겨야 한다"
