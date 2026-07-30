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

from src.analysis.acquisition import max_loan

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


def test_waterline_without_a_top_draws_from_zero_like_the_geometry_does():
    """좌표는 y 없이도 나오는데 그림만 NaN 이면, 물은 조용히 사라진다."""
    svg = value("charts", "waterline", 40.0,
                {"x0": 0, "x1": 100, "height": 200, "total": 100})
    assert "NaN" not in svg and "undefined" not in svg
    assert 'data-part="water"' in svg
    assert " L100 200 L0 200 Z" in svg, "기둥의 바닥은 y 기본값 0 + 높이 200 이다"
    same = value("charts", "waterline", 40.0,
                 {"x0": 0, "x1": 100, "y": 0, "height": 200, "total": 100})
    assert svg == same, "y 를 생략한 그림과 0 을 준 그림은 같아야 한다"


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
    """게이지의 세 수는 시장 산출의 그 자리에서 그대로 온다.

    값을 상수로 박아 두지 않는다 — R-ONE 은 분기마다 갱신되고 파이프라인이 매일 돌기
    때문에, 박아 두면 데이터가 옳게 움직인 날 테스트가 깨진다. 여기서 지켜야 할 것은
    '어느 자리를 읽는가'(단위·필드)이지 그 날의 수치가 아니다.
    """
    mk = market()
    src = mk["regions"]["도심"]
    m = value("hero", "regionModel", mk, underwriting(), "도심")
    assert m["name"] == "도심" and m["buildings"] == 20
    assert m["vacancy"] == pytest.approx(src["vacancy"])
    assert m["vacancy"] == pytest.approx(src["vacancy_pct"] / 100)   # 소수와 %를 뒤섞지 않는다
    assert m["cap"] == pytest.approx(src["cap"]["cap_income_based"])
    assert m["spreadBp"] == pytest.approx(src["spread_vs_treasury10y_bp"])
    assert m["rent"]["effective"] == pytest.approx(src["effective_rent_won_m2_mo"])
    assert m["rent"]["effective"] < m["rent"]["nominal"], "렌트프리를 뺀 값이 명목보다 작다"
    assert m["rent"]["rentFreeMo"] == src["rent_free_mo"]
    assert m["rent"]["source"], "렌트프리 가정의 출처가 모델에 실려야 한다"


def test_region_model_stack_is_the_engine_triple_constraint():
    """자본 지층은 그림을 위해 지어낸 숫자가 아니라 엔진의 삼중 제약이다.

    기대값은 파이썬 엔진을 같은 입력으로 불러 만든다 — 상수를 박으면 cap 이 움직인 날
    깨지고, 그림이 제 손으로 만든 수를 그려도 잡지 못한다.
    """
    mk, uw = market(), underwriting()
    a = uw["assumptions"]
    cap = mk["regions"]["도심"]["cap"]["cap_income_based"]
    expect = max_loan(cap * 100, 100, a["ltv_max"], a["dscr_min"],
                      a["debt_yield_min"], a["loan_rate"], io=True)
    m = value("hero", "regionModel", mk, uw, "도심")
    s = m["stack"]
    assert s["senior"] == pytest.approx(expect["loan_won"])
    assert s["binding"] == expect["binding"]
    assert s["ltvCap"] == pytest.approx(a["ltv_max"] * 100)
    assert s["mezzRoom"] == pytest.approx(s["ltvCap"] - s["senior"])
    assert s["equity"] == pytest.approx(100 - s["ltvCap"])
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


def test_the_titleblock_scale_is_read_off_the_grid_not_written_by_hand():
    """표제란의 축척은 격자에서 나온다 — 20×6 을 옮기면 그 줄도 함께 움직인다."""
    t = value("hero", "regionModel", market(), underwriting(), "도심")["tower"]
    note = value("hero", "scaleNote")
    assert "가치 100 = %d층" % t["floors"] in note
    assert "창 1칸 = %.2f%%p" % (100 / t["cells"]) in note


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
    assert "120칸" in joined and "%d칸" % m["tower"]["dark"] in joined
    # 글줄이 그림과 같은 수를 말하는지만 본다 — 수 자체는 분기마다 움직인다
    assert "%.2f" % m["vacancyPct"] in joined                 # 공실률
    assert "%.1f" % m["stack"]["senior"] in joined            # 선순위 = 수면
    assert "%.1f" % m["stack"]["equity"] in joined            # 지분
    assert "Debt Yield" in joined      # 묶는 제약


def test_the_mezzanine_is_marked_as_an_assumption_in_words_not_only_in_hatching():
    """해칭은 낭독기에 들리지 않고 좁은 판형에서는 부속 라벨이 통째로 빠진다.

    그러니 "메자닌 자리는 관측이 아니다"라는 말은 폭과 사용자를 가리지 않고
    남는 두 곳 — 판독 글줄과 aria — 에 글자로 있어야 한다.
    """
    m = value("hero", "regionModel", market(), underwriting(), "도심")
    caveat = "메자닌 자리는 관측이 아니라 LTV 한도까지 남은 자리라는 가정이다."

    second = value("hero", "readingLines", m)[1]
    assert "메자닌 자리 %.1f(가정)" % m["stack"]["mezzRoom"] in second
    assert caveat in second

    for compact in (False, True):
        svg = value("hero", "render", m, {"compact": compact})
        aria = svg.split('aria-label="')[1].split('"')[0]
        assert "메자닌 자리(가정)" in aria
        assert caveat in aria


# ------------------------------------------------------------------ #
# 라벨의 실렌더 크기 — viewBox 안의 px 는 화면 px 이 아니다
# ------------------------------------------------------------------ #
def rendered_min(plate_px, compact):
    """이 폭에서 가장 작은 라벨이 화면에 몇 px 로 찍히는지."""
    layout = value("hero", "layoutOf", {"compact": compact})
    k = value("hero", "plateLabelScale", plate_px, {"compact": compact})
    return layout["minLabel"] * k * plate_px / layout["w"]


def test_squeezed_wide_plate_lifts_its_labels_to_the_nine_px_floor():
    """768 뷰포트 실측: 도면 실폭 662px · 배율 0.752 — 계수 없이는 7.15px 이었다."""
    assert value("hero", "plateLabelScale", 662, {"compact": False}) == \
        pytest.approx(1.2597, abs=1e-3)
    assert rendered_min(662, False) == pytest.approx(9.0, abs=0.02)
    assert 662 / 880 * 9.5 == pytest.approx(7.15, abs=0.02), "고치기 전의 크기"


def test_compact_plate_at_a_phone_width_also_reaches_nine_px():
    """390 뷰포트 실측: 도면 실폭 308px · 배율 0.716 — 계수 없이는 8.60px 이었다."""
    assert rendered_min(308, True) == pytest.approx(9.0, abs=0.02)
    assert 308 / 430 * 12 == pytest.approx(8.60, abs=0.02), "고치기 전의 크기"
    # 375px 화면(도면 293px)도 흔하다 — 여기서도 하한이 지켜져야 한다.
    assert rendered_min(293, True) >= 9 - 1e-6


def test_a_wide_screen_does_not_shrink_the_drawing_that_was_approved():
    """1440 뷰포트(실폭 1134px)는 이미 14px 이다 — 계수는 1 이고 조형은 그대로."""
    assert value("hero", "plateLabelScale", 1134, {"compact": False}) == 1
    assert value("hero", "plateLabelScale", 900, {"compact": True}) == 1


def test_no_viewport_leaves_a_label_under_nine_px():
    """실제로 나올 수 있는 모든 폭에서 하한이 지켜지는지 훑는다.

    좁은 판형은 362px 화면(도면 280px)부터, 넓은 판형은 760px 화면(654px)부터다.
    그보다 좁은 화면은 아래 테스트가 따로 붙든다 — 거기서는 하한이 아니라
    "라벨이 잘리지 않는다"가 규칙이다.
    """
    for px in range(281, 480, 6):
        assert rendered_min(px, True) >= 9 - 1e-6, "좁은 판형 %dpx" % px
    for px in range(540, 1200, 20):
        assert rendered_min(px, False) >= 9 - 1e-6, "넓은 판형 %dpx" % px


def test_the_factor_stops_before_a_label_gets_cut_off():
    """작은 글자보다 **잘린** 글자가 나쁘다 — 320px 화면에서는 계수가 멈춘다.

    좁은 판형에서 가장 긴 라벨 '메자닌 자리 4.4' 는 실측 74.2 단위이고 자리는
    430 − 342 = 88 단위다. 계수 1.186 부터 잘리기 시작하므로 천장은 그 아래다.
    """
    layout = value("hero", "layoutOf", {"compact": True})
    longest = 74.2
    room = layout["w"] - layout["labelX"]
    assert layout["kMax"] * longest < room, "천장까지 키워도 판형 안에 있어야 한다"
    assert value("hero", "plateLabelScale", 238, {"compact": True}) == layout["kMax"]
    # 390px 화면(도면 308px)이 필요로 하는 계수는 천장 아래다 — 하한이 지켜진다.
    assert value("hero", "plateLabelScale", 308, {"compact": True}) < layout["kMax"]


def test_the_rate_chart_labels_get_the_same_floor():
    """금리 도면의 기준선 이름은 10px 선언이라 768 에서 8.67px 이었다."""
    k = value("hero", "ratesLabelScale", 728, False)
    assert 10 * k * 728 / 840 == pytest.approx(9.0, abs=0.02)
    assert value("hero", "ratesLabelScale", 840, False) == 1


def test_label_scale_of_an_unlaid_out_plate_is_one_not_infinity():
    """폭이 0 인 순간(그리기 전·숨은 탭)에 1/0 을 계수로 쓰면 글자가 사라진다."""
    for bad in (0, -10, "__nan__"):
        assert value("hero", "plateLabelScale", bad, {"compact": False}) == 1


def test_rate_series_for_the_gauge_are_twelve_months():
    rows = value("hero", "rateSeries", market())
    assert len(rows) == 3
    for row in rows:
        assert len(row["points"]) == 12
        assert row["latest"]["ym"] == "2026-06"
        assert row["name"] and row["key"]
