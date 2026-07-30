"""조형 프리미티브 검사 — 지층 기둥·수면·스파크와 서장 모델.

화면을 눈으로 보는 검사가 아니다. 이 파일이 붙드는 것은 **좌표**다. 지층이
주어진 비율만큼의 높이를 갖는지, 층과 층 사이에 틈이 생기지 않는지, 수면이
부채 비율의 자리에 정확히 놓이는지 — 그림은 이 좌표의 결과일 뿐이라 좌표가
틀리면 그림은 조용히 거짓말을 한다. 눈으로는 2px 어긋난 지층을 잡을 수 없다.

DOM 이 필요 없는 순수 함수만 다룬다. `node tests/charts_runner.js` 한 프로세스를
왕복시켜 자바스크립트 쪽 값을 그대로 받아 온다(패리티 러너와 같은 규약).

**node 가 없으면 건너뛰지 않고 실패한다** — 패리티와 같은 이유다.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = str(Path(__file__).resolve().parent / "charts_runner.js")
NODE = shutil.which("node")


def js(mod, fn, *args):
    """자바스크립트 순수 함수 하나를 부르고 결과(또는 오류 갈래)를 돌려준다."""
    if NODE is None:
        raise RuntimeError(
            "node 를 찾을 수 없다 — 조형 검사는 건너뛰지 않는다. 좌표를 아무도 "
            "보지 않은 채 통과하는 편이 훨씬 나쁘다")
    spec = [{"mod": mod, "fn": fn, "args": list(args)}]
    proc = subprocess.run([NODE, RUNNER], input=json.dumps(spec),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("조형 러너 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)[0]


def value(mod, fn, *args):
    r = js(mod, fn, *args)
    assert r["ok"], "%s.%s 가 던졌다: %s" % (mod, fn, r.get("message"))
    return r["value"]


def market():
    return json.loads((ROOT / "out" / "market.json").read_text(encoding="utf-8"))


def underwriting():
    return json.loads((ROOT / "out" / "underwriting.json").read_text(encoding="utf-8"))


def test_node_is_present_because_shapes_never_skip():
    assert NODE is not None, "node 가 없다 — 조형 검사는 건너뛰지 않고 실패한다"


# ------------------------------------------------------------------ #
# strataLayout — 지층의 높이는 비율이고, 층과 층 사이에는 틈이 없다
# ------------------------------------------------------------------ #
BANDS = [{"key": "senior", "label": "선순위", "value": 50.0},
         {"key": "mezz", "label": "메자닌", "value": 30.0},
         {"key": "equity", "label": "지분", "value": 20.0}]
BOX = {"x": 0, "y": 0, "width": 40, "height": 100}


def test_strata_stacks_from_the_bottom_up():
    """첫 지층은 바닥에 앉고, 마지막 지층의 윗면이 기둥의 천장이다."""
    out = value("charts", "strataLayout", BANDS, BOX)
    assert [b["key"] for b in out] == ["senior", "mezz", "equity"]
    assert out[0]["y"] + out[0]["height"] == 100      # 바닥
    assert out[-1]["y"] == 0                          # 천장
    assert [b["height"] for b in out] == [50.0, 30.0, 20.0]
    assert [b["y"] for b in out] == [50.0, 20.0, 0.0]


def test_strata_leaves_no_seam_between_layers():
    """층의 아랫면과 아래층의 윗면은 같은 좌표여야 한다 — 반올림해도."""
    bands = [{"key": "a", "value": 50.606249999999996},
             {"key": "b", "value": 4.39375},
             {"key": "c", "value": 45.0}]
    out = value("charts", "strataLayout", bands,
                {"x": 0, "y": 60, "width": 40, "height": 392, "total": 100})
    for lower, upper in zip(out, out[1:]):
        assert lower["y"] == pytest.approx(upper["y"] + upper["height"]), "틈이 생겼다"
    assert out[0]["y"] + out[0]["height"] == pytest.approx(452)
    assert out[-1]["y"] == pytest.approx(60)


def test_strata_share_is_the_value_over_total():
    out = value("charts", "strataLayout", BANDS, dict(BOX, total=200))
    assert [b["share"] for b in out] == [0.25, 0.15, 0.10]
    assert out[0]["height"] == 25.0                   # 전체가 커지면 높이는 줄어든다
    assert out[-1]["y"] == pytest.approx(50.0), "합이 전체에 못 미치면 위가 빈다"


def test_strata_keeps_the_box_x_and_width():
    out = value("charts", "strataLayout", BANDS, {"x": 560, "y": 60,
                                                  "width": 140, "height": 392})
    assert all(b["x"] == 560 and b["width"] == 140 for b in out)


def test_strata_of_nothing_is_nothing():
    assert value("charts", "strataLayout", [], BOX) == []


def test_strata_rejects_a_negative_layer():
    r = js("charts", "strataLayout", [{"key": "a", "value": -1.0}], BOX)
    assert not r["ok"] and r["error"] == "input"


def test_strata_rejects_a_sum_that_overflows_the_column():
    """합이 전체를 넘으면 기둥 밖으로 삐져나간다 — 조용히 자르지 않는다."""
    r = js("charts", "strataLayout", BANDS, dict(BOX, total=99.0))
    assert not r["ok"] and r["error"] == "input"
    assert "넘는다" in r["message"]


def test_strata_rejects_a_nonfinite_value():
    r = js("charts", "strataLayout", [{"key": "a", "value": "__nan__"}], BOX)
    assert not r["ok"] and r["error"] == "input"


def test_strata_rejects_a_column_without_height():
    r = js("charts", "strataLayout", BANDS, dict(BOX, height=0))
    assert not r["ok"] and r["error"] == "input"


# ------------------------------------------------------------------ #
# waterline — 수면은 부채 비율의 자리에 놓인다
# ------------------------------------------------------------------ #
def test_waterline_sits_at_the_debt_share():
    g = value("charts", "waterlineGeom", 55.0, {"y": 0, "height": 100, "total": 100})
    assert g["share"] == 0.55
    assert g["y"] == 45.0            # 위에서 재는 좌표라 1 − 비율
    assert g["overflow"] is False


def test_waterline_scales_with_the_column():
    g = value("charts", "waterlineGeom", 50.60625,
              {"y": 60, "height": 392, "total": 100})
    assert g["y"] == pytest.approx(60 + 392 * (1 - 0.5060625))


def test_waterline_that_tops_the_column_is_flagged_not_hidden():
    """부채가 가치를 넘으면 물은 기둥 위로 넘친다 — 잘라 두고 표식을 남긴다."""
    g = value("charts", "waterlineGeom", 120.0, {"y": 0, "height": 100, "total": 100})
    assert g["y"] == 0.0 and g["share"] == 1.0
    assert g["overflow"] is True and g["level"] == 120.0


def test_waterline_below_zero_is_flagged_too():
    g = value("charts", "waterlineGeom", -5.0, {"y": 0, "height": 100, "total": 100})
    assert g["y"] == 100.0 and g["share"] == 0.0 and g["underflow"] is True


# ------------------------------------------------------------------ #
# SVG 조각 — 외부 의존 0, 문자열만 낸다
# ------------------------------------------------------------------ #
def test_strata_column_draws_one_rect_per_layer():
    svg = value("charts", "strataColumn", BANDS, BOX)
    assert svg.count("<rect") == 3
    for key in ("senior", "mezz", "equity"):
        assert 'data-key="%s"' % key in svg


def test_spark_is_a_standalone_svg_with_a_path():
    svg = value("charts", "spark", [1.0, 2.0, 1.5, 3.0],
                {"width": 120, "height": 28, "aria": "열두 달 추이"})
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'viewBox="0 0 120 28"' in svg
    assert 'role="img"' in svg and 'aria-label="열두 달 추이"' in svg
    assert svg.count(' d="M') == 1


def test_spark_of_a_flat_series_still_draws():
    """모든 값이 같으면 분모가 0 이다 — 납작한 선을 그리고 넘어간다."""
    svg = value("charts", "spark", [2.0, 2.0, 2.0], {"width": 100, "height": 20})
    assert "<path" in svg and "NaN" not in svg


def test_line_labels_its_axis_with_text_not_only_geometry():
    svg = value("charts", "line",
                [{"key": "a", "label": "국고채", "points":
                  [{"label": "2025.07", "y": 2.84}, {"label": "2026.06", "y": 4.181}]}],
                {"width": 400, "height": 160, "aria": "금리"})
    assert "<text" in svg and "2026.07" not in svg
    assert 'role="img"' in svg


def test_bar_and_scatter_exist_as_primitives():
    bar = value("charts", "bar", [{"label": "도심", "value": 3.0},
                                  {"label": "강남", "value": 1.0}],
                {"width": 200, "height": 80})
    assert bar.count("<rect") >= 2
    sc = value("charts", "scatter", [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}],
               {"width": 200, "height": 200})
    assert sc.count("<circle") == 2


def test_text_is_escaped_so_a_label_cannot_close_a_tag():
    assert value("charts", "esc", '<b>"&\'') == "&lt;b&gt;&quot;&amp;&#39;"
    svg = value("charts", "spark", [1.0, 2.0], {"aria": '도심 <img onerror="x">'})
    assert "<img" not in svg


# ------------------------------------------------------------------ #
# 서장 모델 — 실데이터에서 단면 한 장이 나온다
# ------------------------------------------------------------------ #
def test_region_model_carries_the_three_numbers_of_the_gauge():
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    assert m["name"] == "도심" and m["buildings"] == 20
    assert m["vacancy"] == pytest.approx(0.063692)
    assert m["cap"] == pytest.approx(0.040485)
    assert m["spreadBp"] == pytest.approx(-13.25)
    assert m["rent"]["effective"] == pytest.approx(26114.083333333332)
    assert m["rent"]["rentFreeMo"] == 2.0
    assert m["rent"]["source"], "렌트프리 가정의 출처가 모델에 실려야 한다"


def test_region_model_stack_is_the_engine_triple_constraint():
    """자본 지층은 그림을 위해 지어낸 숫자가 아니라 엔진의 삼중 제약이다."""
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    s = m["stack"]
    assert s["senior"] == pytest.approx(50.60625)
    assert s["binding"] == "debt_yield"
    assert s["ltvCap"] == pytest.approx(55.0)
    assert s["mezzRoom"] == pytest.approx(55.0 - 50.60625)
    assert s["equity"] == pytest.approx(45.0)
    assert s["senior"] + s["mezzRoom"] + s["equity"] == pytest.approx(100.0)
    assert s["waterline"] == pytest.approx(s["senior"]), "수면은 선순위 실선까지다"


def test_every_region_has_a_negative_spread_and_the_model_says_so():
    for name in ("도심", "강남", "여의도마포"):
        m = value("hero", "regionModel", market(), underwriting(), name)
        assert m["spreadBp"] < 0
        assert m["spreadBelowTreasury"] is True


def test_dark_windows_are_exactly_the_vacancy_share():
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    t = m["tower"]
    assert t["cells"] == t["floors"] * t["perFloor"]
    assert t["dark"] == round(m["vacancy"] * t["cells"])
    assert len(t["darkCells"]) == t["dark"]
    assert len(set(t["darkCells"])) == t["dark"], "같은 칸을 두 번 끄지 않는다"
    assert all(0 <= i < t["cells"] for i in t["darkCells"])


def test_dark_windows_are_deterministic():
    a = value("hero", "pickDarkCells", 120, 8)
    b = value("hero", "pickDarkCells", 120, 8)
    assert a == b, "같은 입력에 같은 그림 — 새로고침마다 창이 옮겨 다니면 안 된다"
    assert value("hero", "pickDarkCells", 120, 0) == []
    assert len(value("hero", "pickDarkCells", 120, 120)) == 120


def test_dark_windows_do_not_clump_into_one_floor():
    """8칸이 한 층에 몰리면 공실이 아니라 폐쇄된 층으로 읽힌다."""
    cells = value("hero", "pickDarkCells", 120, 8)
    floors = set(i // 6 for i in cells)
    assert len(floors) >= 6


def test_region_model_rejects_an_unknown_region():
    r = js("hero", "regionModel", market(), underwriting(), "판교")
    assert not r["ok"] and r["error"] == "input"


def test_hero_renders_both_halves_and_the_waterline():
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    svg = value("hero", "render", m, {})
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert 'data-part="tower"' in svg and 'data-part="strata"' in svg
    assert 'data-part="water"' in svg
    assert 'role="img"' in svg and "aria-label=" in svg
    assert "{" + "{" not in svg, "미치환 플레이스홀더 게이트에 걸릴 문자열"
    assert "undefined" not in svg and "NaN" not in svg


def test_hero_draws_one_window_per_cell():
    m = value("hero", "regionModel", market(), underwriting(), "강남")
    svg = value("hero", "render", m, {})
    assert svg.count('class="win"') + svg.count('class="win off"') == m["tower"]["cells"]
    assert svg.count('class="win off"') == m["tower"]["dark"]


def test_hero_compact_layout_is_narrower_but_keeps_both_halves():
    """390px 에서도 단면은 단면이다 — 좁은 판형은 라벨만 덜어 낸다."""
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    wide = value("hero", "render", m, {"compact": False})
    tight = value("hero", "render", m, {"compact": True})
    assert 'data-part="tower"' in tight and 'data-part="strata"' in tight
    assert value("hero", "viewBoxWidth", {"compact": True}) < \
        value("hero", "viewBoxWidth", {"compact": False})
    assert tight.count("<text") < wide.count("<text")


def test_hero_reading_puts_every_drawn_number_into_words():
    """그림이 말하는 것을 글도 말해야 한다 — 화면 낭독기는 rect 를 읽지 못한다."""
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    lines = value("hero", "readingLines", m)
    joined = " ".join(lines)
    assert "120칸" in joined and "8칸" in joined
    assert "6.37" in joined            # 공실률
    assert "50.6" in joined            # 선순위 = 수면
    assert "45.0" in joined            # 지분
    assert "Debt Yield" in joined      # 묶는 제약


def test_rate_series_for_the_gauge_are_twelve_months():
    rows = value("hero", "rateSeries", market())
    assert len(rows) == 3
    for row in rows:
        assert len(row["points"]) == 12
        assert row["latest"]["ym"] == "2026-06"
        assert row["name"] and row["key"]
