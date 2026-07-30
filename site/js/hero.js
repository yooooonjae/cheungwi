/**
 * 서장 — 타워의 세로 단면과 세 권역의 계기판.
 *
 * 이 페이지의 첫 화면은 그림 한 장이다. 왼쪽은 **물리 층위**(층이 쌓이고, 권역
 * 공실률만큼의 창이 꺼져 있다), 오른쪽은 **자본 층위**(가치 100 위에 선순위·
 * 메자닌 자리·지분이 지층으로 앉는다), 그리고 그 둘을 가로지르는 **하나의
 * 수면**이 부채의 높이에 그어진다. 가운데 눈금자는 같은 높이를 두 단위로 읽는다
 * — 왼쪽은 층, 오른쪽은 가치. 이 작품의 제목이 그 눈금자다.
 *
 * ── 그림이 지어낸 숫자는 하나도 없다 ──
 *   꺼진 창의 수      = round(권역 공실률 × 120칸)              R-ONE 2026Q1
 *   수면의 높이       = CheungwiEngine.max_loan(...).loan_won   가치 100 기준
 *   메자닌 자리       = LTV 한도 55 − 선순위                    **가정**이다
 *   지분              = 100 − LTV 한도
 * 선순위는 엔진의 삼중 제약(LTV·DSCR·Debt Yield) 최솟값 그대로다. 메자닌만
 * 관측이 아니라 "LTV 한도까지 남은 자리"라서, 채운 색이 아니라 **해칭**으로
 * 그린다 — 실선은 계산이고 해칭은 가정이라는 규칙을 형태로 못박는다.
 *
 * ── 순수 함수와 DOM 을 나눈 이유 ──
 * `regionModel`·`render`·`readingLines`·`rateSeries` 는 입력만 받아 값과 문자열을
 * 낸다. 그래서 `tests/test_charts.py` 가 브라우저 없이 좌표와 문구를 붙든다.
 * DOM 을 만지는 것은 `mount` 하나뿐이다.
 *
 * ── 두 판형 ──
 * 좁은 화면에서 880 폭 판형을 그대로 줄이면 글자가 5px 이 된다. 그래서 판형이
 * 둘이다(`LAYOUT.wide`·`LAYOUT.compact`). 좁은 판형은 **단면을 포기하지 않고
 * 라벨만 덜어 낸다** — 덜어 낸 수치는 그림 밑 글줄(`readingLines`)이 그대로
 * 받으므로 화면 폭에 따라 사라지는 숫자는 없다.
 *
 * 의존은 같은 사이트의 두 파일뿐이다(`charts.js`·`engine.js`). 로드 순서가
 * engine → charts → hero 여야 한다(assemble 의 JS_FILES 가 그 순서다).
 */

;(function (root, factory) {
  "use strict";
  var isNode = typeof module !== "undefined" && module.exports;
  var scope = typeof window !== "undefined" ? window : (root || {});
  var charts = isNode ? require("./charts.js") : scope.CheungwiCharts;
  var engine = isNode ? require("./engine.js") : scope.CheungwiEngine;
  var api = factory(charts, engine);
  if (isNode) module.exports = api;
  if (typeof window !== "undefined") window.CheungwiHero = api;
  else if (root) root.CheungwiHero = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, engine) {
  "use strict";

  var tag = charts.tag, text = charts.text, esc = charts.esc, r4 = charts.r4;

  // ── 모식도의 규격 ───────────────────────────────────────────────────────
  // 특정 건물이 아니다. 대장이 열리기 전이라 층수·연면적이 없고, 있더라도 권역
  // 대표 단면에 한 동의 층수를 쓰면 그 동의 그림으로 오독된다. 20층 × 6칸은
  // 공실률을 칸으로 셀 수 있는 최소 해상도(1칸 ≒ 0.83%p)로 고른 눈금이다.
  var FLOORS = 20;
  var CELLS_PER_FLOOR = 6;

  var BINDING_LABEL = {
    ltv: "LTV 한도",
    dscr: "요구 DSCR",
    debt_yield: "Debt Yield 하한"
  };

  var RATE_SERIES = [
    { key: "treasury10y", short: "국고채 10년", className: "s-treasury" },
    { key: "cd91", short: "CD 91일", className: "s-cd" },
    { key: "loan_corp_new", short: "기업대출 신규", className: "s-loan" }
  ];
  var RATE_MONTHS = 12;

  // ── 서식 ────────────────────────────────────────────────────────────────
  // 천단위 구분은 직접 넣는다. toLocaleString 은 로케일에 따라 결과가 갈려
  // node 검사와 브라우저 화면이 다른 문자열이 될 수 있다.
  function group(intStr) {
    return intStr.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function won(v) {
    var s = Math.round(Math.abs(v)).toFixed(0);
    return (v < 0 ? "-" : "") + group(s);
  }

  function fx(v, d) {
    return Number(v).toFixed(d === undefined ? 1 : d);
  }

  /** 소수 이율 → 퍼센트 문자열. 0.040485 → "4.05%" */
  function pct(v, d) {
    return fx(v * 100, d === undefined ? 2 : d) + "%";
  }

  /** 이미 퍼센트인 값 → 퍼센트 문자열. 6.3692 → "6.37%" */
  function pctp(v, d) {
    return fx(v, d === undefined ? 2 : d) + "%";
  }

  function bp(v) {
    return (v > 0 ? "+" : "") + fx(v, 0) + "bp";
  }

  function ymDot(ym) {
    return String(ym).replace(/-/g, ".");
  }

  // ── 꺼진 창 고르기 ──────────────────────────────────────────────────────
  /**
   * n 칸 중 k 칸을 고른다 — 무작위가 아니라 **황금비 저불일치 수열**로.
   *
   * 난수를 쓰면 새로고침마다 창이 옮겨 다녀 같은 데이터가 다른 그림이 된다.
   * 균등 간격으로 고르면 8칸이 한 줄로 서서 격자가 되어 버린다. 황금비 수열은
   * 결정적이면서 흩어져 보이는 유일한 값싼 선택이다 — 층에도 골고루 퍼진다.
   * 같은 칸을 두 번 고르면 옆칸으로 밀어(선형 탐사) 정확히 k 칸을 채운다.
   */
  function pickDarkCells(n, k) {
    if (typeof n !== "number" || !isFinite(n) || n <= 0 || n % 1 !== 0) {
      throw new TypeError("칸 수는 양의 정수여야 한다: " + String(n));
    }
    if (typeof k !== "number" || !isFinite(k) || k < 0 || k % 1 !== 0) {
      throw new TypeError("꺼진 칸 수는 0 이상의 정수여야 한다: " + String(k));
    }
    if (k > n) {
      throw new TypeError("꺼진 칸 " + k + " 이 전체 칸 " + n + " 보다 많다");
    }
    var PHI = 0.6180339887498949;
    var used = {}, out = [];
    for (var i = 0; out.length < k; i += 1) {
      var idx = Math.floor((((i + 0.5) * PHI) % 1) * n) % n;
      while (used[idx]) idx = (idx + 1) % n;   // 선형 탐사
      used[idx] = true;
      out.push(idx);
    }
    return out.sort(function (a, b) { return a - b; });
  }

  // ── 권역 하나의 모델 ────────────────────────────────────────────────────
  /**
   * out/market.json · out/underwriting.json 에서 단면 한 장에 필요한 값만 뽑는다.
   *
   * 자본 지층은 여기서 엔진을 부른다 — 화면에 그릴 숫자를 화면이 따로 계산하면
   * `out/*.json` 과 어긋날 수 있으니, 부르는 함수는 파이썬과 패리티가 잡힌
   * `max_loan` 하나여야 한다.
   */
  function regionModel(market, underwriting, name) {
    if (!market || !market.regions) {
      throw new TypeError("market 에 regions 가 없다");
    }
    var reg = market.regions[name];
    if (!reg) {
      throw new TypeError(
        "모르는 권역이다: " + String(name) + " — 있는 권역은 " +
        Object.keys(market.regions).join("·"));
    }
    var a = (underwriting && underwriting.assumptions) || {};
    var byRegion = (underwriting && underwriting.summary &&
                    underwriting.summary.by_region) || {};
    var cap = reg.cap.cap_income_based;
    var rates = market.rates || {};
    var t10 = (rates.treasury10y && rates.treasury10y.latest) || {};

    // 가치 100 을 기준으로 삼는다. 단위가 원이든 억이든 지층의 비율은 같고,
    // 대장이 열리기 전이라 동별 가치가 없으므로 기준을 100 으로 두는 편이 정직하다.
    var loan = engine.max_loan(cap * 100, 100, a.ltv_max, a.dscr_min,
                               a.debt_yield_min, a.loan_rate, true);
    var ltvCap = a.ltv_max * 100;
    var senior = loan.loan_won;
    var stack = {
      total: 100,
      senior: senior,
      mezzRoom: ltvCap - senior,
      equity: 100 - ltvCap,
      ltvCap: ltvCap,
      binding: loan.binding,
      by: loan.by,
      waterline: senior
    };

    var cells = FLOORS * CELLS_PER_FLOOR;
    var dark = Math.round(reg.vacancy * cells);
    var meta = reg.rent_free_meta || {};

    return {
      name: name,
      buildings: (byRegion[name] && byRegion[name].n) || 0,
      quarter: reg.latest_quarter,
      rent: {
        nominal: reg.nominal_rent_won_m2_mo,
        effective: reg.effective_rent_won_m2_mo,
        rentFreeMo: reg.rent_free_mo,
        source: meta.source || "",
        caveat: meta.caveat || ""
      },
      vacancy: reg.vacancy,
      vacancyPct: reg.vacancy_pct,
      cap: cap,
      capQuarters: reg.cap.quarters_used || [],
      spreadBp: reg.spread_vs_treasury10y_bp,
      spreadBelowTreasury: reg.spread_vs_treasury10y_bp < 0,
      treasury: { ym: t10.ym, pct: t10.value_pct },
      tower: {
        floors: FLOORS,
        perFloor: CELLS_PER_FLOOR,
        cells: cells,
        dark: dark,
        darkCells: pickDarkCells(cells, dark),
        submergedFloors: r4(FLOORS * senior / 100)
      },
      stack: stack,
      assumptions: {
        ltvMax: a.ltv_max,
        dscrMin: a.dscr_min,
        debtYieldMin: a.debt_yield_min,
        loanRate: a.loan_rate
      },
      trend: (reg.trend_quarters || []).map(function (q) {
        return {
          yq: q.yq,
          effective: q.effective_rent_won_m2_mo,
          vacancyPct: q.vacancy_pct
        };
      })
    };
  }

  // ── 판형 ────────────────────────────────────────────────────────────────
  // minLabel 은 이 판형에서 **가장 작은** 라벨의 선언 크기다(hero.css 와 짝).
  // wide 는 .lab-sub 9.5px, compact 는 한 크기로 맞춘 12px 이다.
  var LAYOUT = {
    wide: {
      w: 880, h: 512, topY: 78, groundY: 456,
      tower: { x: 84, width: 272, wall: 7, winPad: 7, winTop: 4 },
      spine: { x: 442, floorTicks: [0, 5, 10, 15, 20], valueTicks: [0, 25, 50, 75, 100] },
      column: { x: 566, width: 118 },
      labelX: 698, waterLabelX: 74, ground: { x0: 40, x1: 856, depth: 17 },
      annotY: 494, headY: 60, verbose: true, font: 1, minLabel: 9.5, kMax: 1.6
    },
    compact: {
      w: 430, h: 430, topY: 58, groundY: 372,
      tower: { x: 26, width: 148, wall: 5, winPad: 4, winTop: 3 },
      spine: { x: 214, floorTicks: [0, 10, 20], valueTicks: [0, 50, 100] },
      column: { x: 268, width: 64 },
      labelX: 342, waterLabelX: 0, ground: { x0: 14, x1: 416, depth: 12 },
      annotY: 0, headY: 42, verbose: false, font: 1, minLabel: 12, kMax: 1.15
    }
  };

  function layoutOf(opts) {
    return (opts && opts.compact) ? LAYOUT.compact : LAYOUT.wide;
  }

  function viewBoxWidth(opts) {
    return layoutOf(opts).w;
  }

  // ── 라벨은 판형이 아니라 화면에서 읽힌다 ────────────────────────────────
  /**
   * viewBox 안의 글자 크기는 **선언값이 아니라 배율의 결과**다.
   *
   * `width:100%` 로 놓인 도면은 실폭 ÷ viewBox 폭 만큼 통째로 커지거나 작아진다.
   * 880 폭 판형이 662px(768 뷰포트)에 들어가면 배율이 0.752 라 9.5px 로 선언한
   * 부속 라벨이 화면에서는 7.1px 로 찍힌다 — 판형은 멀쩡한데 글자만 못 읽는다.
   * 판형을 셋으로 늘리는 대신 **배율의 역수를 글자에 되돌려준다**: 실렌더가
   * 9px 아래로 내려가지 않을 만큼만 선언값을 키우는 계수 하나(`--fig-k`)를
   * CSS 로 넘기고, 모든 라벨의 font-size 가 그 계수를 곱한다(hero.css).
   *
   * 줄이지는 않는다(k ≥ 1). 넓은 화면에서 도면이 커지면 글자도 함께 커지는
   * 것이 원래 조형이고, 그쪽은 읽기에 문제가 없다.
   *
   * 계수에는 천장이 있다. 글자를 키우면 라벨이 판형 밖으로 밀려 **잘리기**
   * 때문이다 — 작은 글자보다 잘린 글자가 나쁘다. 좁은 판형에서 가장 긴 라벨
   * ("메자닌 자리 4.4")은 실측 74.2 단위이고 자리는 430 − 342 = 88 단위라
   * 1.186 에서 잘리기 시작한다. 그래서 천장을 1.15 로 둔다(활자 대체 폭이
   * 조금 달라져도 견딜 3% 여유). 그 천장 아래에서 하한 9px 은 폭 362px 까지
   * 지켜지고(390px 화면이 쓰는 계수는 1.0471 이다), 그보다 좁으면 라벨은 더
   * 크지 않는다 — 대신 그 수치들은 그림 밑 판독 글줄이 본문 크기로 싣는다.
   */
  var MIN_LABEL_PX = 9;
  var K_MAX = 1.6;

  function labelScale(renderedWidthPx, viewBoxW, minDeclaredPx, kMax) {
    if (typeof renderedWidthPx !== "number" || !isFinite(renderedWidthPx) ||
        renderedWidthPx <= 0) {
      return 1;   // 아직 레이아웃이 없는 순간(display:none 등)은 손대지 않는다
    }
    var scale = renderedWidthPx / viewBoxW;
    var k = MIN_LABEL_PX / (minDeclaredPx * scale);
    // 자를 때는 올린다 — 내림으로 다듬으면 하한이 8.9997px 이 되어 규칙이 깨진다.
    return Math.min(kMax || K_MAX, Math.max(1, Math.ceil(k * 1e4) / 1e4));
  }

  function plateLabelScale(renderedWidthPx, opts) {
    var L = layoutOf(opts);
    return labelScale(renderedWidthPx, L.w, L.minLabel, L.kMax);
  }

  // ── 해칭·정의 ───────────────────────────────────────────────────────────
  /**
   * 해칭 두 종. 지반은 굵게 성기게, 메자닌 자리는 가늘게 촘촘히.
   *
   * 색을 속성으로 박지 않고 CSS 로 넘긴다(`hero.css` 의 `.hatch-* line`) —
   * 다크 모드에서 다시 그리지 않아도 색이 따라온다.
   */
  function defs() {
    function hatch(id, size, cls) {
      return tag("pattern", {
        id: id, width: size, height: size,
        patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"
      }, tag("line", { x1: 0, y1: 0, x2: 0, y2: size, class: cls }));
    }
    return tag("defs", {},
      hatch("cw-hatch-ground", 6, "hatch-ground") +
      hatch("cw-hatch-mezz", 4, "hatch-mezz"));
  }

  // ── 타워 단면 ───────────────────────────────────────────────────────────
  function towerPart(m, L) {
    var T = L.tower;
    var H = L.groundY - L.topY;
    var floorH = H / m.tower.floors;
    var x1 = T.x + T.width;
    var inner0 = T.x + T.wall;
    var innerW = T.width - T.wall * 2;
    var colW = innerW / m.tower.perFloor;
    var winW = colW - T.winPad * 2;
    var winH = Math.max(4, floorH - T.winTop * 2 - 1);
    var dark = {};
    m.tower.darkCells.forEach(function (i) { dark[i] = true; });

    var body = "";
    // 벽체 단면 두 줄 + 몸통
    body += tag("rect", {
      x: T.x, y: L.topY, width: T.width, height: H, class: "tower-body"
    });
    // 파라펫 — 지붕은 층이 아니다
    body += tag("rect", {
      x: T.x - 4, y: L.topY - 7, width: T.width + 8, height: 7, class: "tower-cap"
    });
    // 슬래브 — 층이 쌓인 자리
    for (var f = 0; f <= m.tower.floors; f += 1) {
      var sy = r4(L.groundY - f * floorH);
      body += tag("line", {
        x1: T.x, x2: x1, y1: sy, y2: sy,
        class: "slab" + (f % 5 === 0 ? " slab-major" : "")
      });
    }
    // 창 — 아래층부터 위로 센다(칸 번호 0 이 1층 왼쪽 끝)
    for (var i = 0; i < m.tower.cells; i += 1) {
      var fl = Math.floor(i / m.tower.perFloor);
      var cl = i % m.tower.perFloor;
      body += tag("rect", {
        x: r4(inner0 + colW * cl + T.winPad),
        y: r4(L.groundY - (fl + 1) * floorH + T.winTop),
        width: r4(winW), height: r4(winH),
        class: dark[i] ? "win off" : "win"
      });
    }
    // 벽체 — 창 위에 덮어 단면선을 살린다
    body += tag("rect", {
      x: T.x, y: L.topY, width: T.wall, height: H, class: "tower-wall"
    });
    body += tag("rect", {
      x: r4(x1 - T.wall), y: L.topY, width: T.wall, height: H, class: "tower-wall"
    });
    return tag("g", { class: "tower", "data-part": "tower" }, body);
  }

  // ── 가운데 눈금자 — 같은 높이를 두 단위로 읽는다 ────────────────────────
  function spinePart(m, L) {
    var S = L.spine;
    var H = L.groundY - L.topY;
    var body = tag("line", {
      x1: S.x, x2: S.x, y1: L.topY - 6, y2: L.groundY, class: "spine"
    });
    S.floorTicks.forEach(function (f) {
      var y = r4(L.groundY - (f / m.tower.floors) * H);
      body += tag("line", { x1: S.x - 7, x2: S.x, y1: y, y2: y, class: "tick" });
      body += text(S.x - 11, y + 3.5, String(f),
                   { class: "lab lab-num", "text-anchor": "end" });
    });
    S.valueTicks.forEach(function (v) {
      var y = r4(L.groundY - (v / 100) * H);
      body += tag("line", { x1: S.x, x2: S.x + 7, y1: y, y2: y, class: "tick" });
      body += text(S.x + 11, y + 3.5, String(v), { class: "lab lab-num" });
    });
    body += text(S.x - 11, L.topY - 14, "층", { class: "lab lab-unit", "text-anchor": "end" });
    body += text(S.x + 11, L.topY - 14, "가치", { class: "lab lab-unit" });
    return tag("g", { class: "spine-g" }, body);
  }

  // ── 자본 지층 ───────────────────────────────────────────────────────────
  function strataBands(m) {
    var s = m.stack;
    return [
      { key: "senior", label: "선순위", value: s.senior, className: "stratum-senior" },
      { key: "mezz", label: "메자닌 자리", value: s.mezzRoom, className: "stratum-mezz" },
      { key: "equity", label: "지분", value: s.equity, className: "stratum-equity" }
    ];
  }

  function columnBox(m, L) {
    return {
      x: L.column.x, y: L.topY,
      width: L.column.width, height: L.groundY - L.topY, total: m.stack.total
    };
  }

  function strataPart(m, L) {
    var box = columnBox(m, L);
    var laid = charts.strataLayout(strataBands(m), box);
    var body = charts.strataColumn(strataBands(m), box);
    // 메자닌 자리는 계산이 아니라 가정이다 — 채운 색 위에 해칭을 덮어 구분한다.
    var mezz = laid[1];
    if (mezz && mezz.height > 0.5) {
      body += tag("rect", {
        x: mezz.x, y: mezz.y, width: mezz.width, height: mezz.height,
        fill: "url(#cw-hatch-mezz)", class: "mezz-hatch"
      });
    }
    body += tag("rect", {
      x: box.x, y: box.y, width: box.width, height: box.height, class: "column-frame"
    });
    // LTV 한도 — 물이 닿을 수 있는 천장
    var ltvY = r4(box.y + box.height * (1 - m.stack.ltvCap / 100));
    body += tag("line", {
      x1: box.x - 8, x2: box.x + box.width + 8, y1: ltvY, y2: ltvY, class: "ltv-cap"
    });
    return tag("g", { class: "column-g" }, body);
  }

  function strataLabels(m, L) {
    var laid = charts.strataLayout(strataBands(m), columnBox(m, L));
    var right = L.column.x + L.column.width;
    var subs = {
      senior: "묶는 제약 " + BINDING_LABEL[m.stack.binding],
      mezz: "LTV 한도까지 남은 자리 · 가정",
      equity: "100 − LTV 한도 " + fx(m.stack.ltvCap)
    };
    var vals = { senior: m.stack.senior, mezz: m.stack.mezzRoom, equity: m.stack.equity };
    return laid.map(function (b) {
      var cy = r4(b.y + b.height / 2);
      // 지시선이 색을 맡는다. 라벨 글자를 계열색으로 칠하면 지분(주황)이 종이
      // 위에서 대비 3:1 을 못 넘겨 읽히지 않는다 — 색은 선에, 글자는 먹에.
      var out = tag("line", {
        x1: r4(right + 2), x2: r4(L.labelX - 6), y1: cy, y2: cy,
        class: "leader leader-" + b.key
      });
      out += text(L.labelX, cy - (L.verbose ? 1 : -3.5),
                  b.label + " " + fx(vals[b.key]),
                  { class: "lab lab-stratum" });
      if (L.verbose) out += text(L.labelX, cy + 13, subs[b.key], { class: "lab lab-sub" });
      return out;
    }).join("");
  }

  // ── 지반 ────────────────────────────────────────────────────────────────
  function groundPart(L) {
    var G = L.ground;
    return tag("g", { class: "ground-g" },
      tag("rect", { x: G.x0, y: L.groundY, width: G.x1 - G.x0, height: G.depth,
                    fill: "url(#cw-hatch-ground)", class: "ground-hatch" }) +
      tag("line", { x1: G.x0, x2: G.x1, y1: L.groundY, y2: L.groundY, class: "ground" }));
  }

  // ── 한 장 ───────────────────────────────────────────────────────────────
  // 메자닌이 가정이라는 사실을 그림은 해칭으로 말한다. 해칭은 낭독기에 들리지
  // 않고 좁은 판형에서는 부속 라벨도 덜어 내므로, 그 한 문장은 **폭과 무관하게**
  // 남는 두 곳 — 낭독용 aria 와 그림 밑 판독 글줄 — 에 글자로 박아 둔다.
  var MEZZ_CAVEAT =
    "메자닌 자리는 관측이 아니라 LTV 한도까지 남은 자리라는 가정이다.";

  function ariaOf(m) {
    return m.name + " 권역 단면 — " + m.tower.cells + "칸 중 " + m.tower.dark +
      "칸이 꺼져 있고(공실률 " + pctp(m.vacancyPct) + "), 가치 100 위에 선순위 " +
      fx(m.stack.senior) + " · 메자닌 자리(가정) " + fx(m.stack.mezzRoom) +
      " · 지분 " + fx(m.stack.equity) + " 가 쌓여 부채의 수면이 " +
      fx(m.stack.waterline) + " 에 그어진다. " + MEZZ_CAVEAT;
  }

  function render(m, opts) {
    var L = layoutOf(opts);
    var box = columnBox(m, L);
    var water = charts.waterlineGeom(m.stack.waterline, box);
    var inner = defs();

    inner += groundPart(L);
    inner += towerPart(m, L);
    inner += spinePart(m, L);
    inner += strataPart(m, L);

    // 수면은 두 층위를 함께 가로지른다 — 이 한 선이 서장의 문장이다.
    inner += charts.waterline(m.stack.waterline, {
      x0: L.tower.x, x1: L.column.x + L.column.width + 6,
      y: box.y, height: box.height, total: box.total,
      waves: L.verbose ? 14 : 8
    });

    inner += strataLabels(m, L);
    inner += text(L.tower.x, L.headY, "물리 층위 · " + m.tower.floors + "층 × " +
                  m.tower.perFloor + "칸", { class: "lab lab-head" });
    inner += text(L.column.x, L.headY, "자본 층위 · 가치 100",
                  { class: "lab lab-head" });

    if (L.verbose) {
      inner += text(L.waterLabelX, r4(water.y) - 5, "부채의 수면",
                    { class: "lab lab-water", "text-anchor": "end" });
      inner += text(L.waterLabelX, r4(water.y) + 9, fx(m.stack.waterline),
                    { class: "lab lab-num lab-water", "text-anchor": "end" });
      inner += text(L.tower.x, L.annotY,
                    "꺼진 창 " + m.tower.dark + "칸 / " + m.tower.cells +
                    "칸 · 공실률 " + pctp(m.vacancyPct),
                    { class: "lab lab-foot" });
      inner += text(L.column.x, L.annotY,
                    "수면 " + fx(m.stack.waterline) + " = " +
                    fx(m.tower.submergedFloors) + "층 높이",
                    { class: "lab lab-foot" });
    }

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h,
      role: "img",
      "aria-label": ariaOf(m),
      class: "plate-svg" + (L.verbose ? "" : " is-compact"),
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  // ── 그림을 글로 ─────────────────────────────────────────────────────────
  /** 낭독기는 rect 를 읽지 못한다. 그림이 말하는 것을 글도 말해야 한다. */
  function readingLines(m) {
    var s = m.stack;
    return [
      m.name + " · " + m.buildings + "동 — " + m.tower.floors + "층 × " +
        m.tower.perFloor + "칸 = " + m.tower.cells + "칸 가운데 " + m.tower.dark +
        "칸이 꺼져 있다. 공실률 " + pctp(m.vacancyPct) + " (R-ONE " + m.quarter + ").",
      "가치 100 기준 — 선순위 " + fx(s.senior) + " · 메자닌 자리 " +
        fx(s.mezzRoom) + "(가정) · 지분 " + fx(s.equity) + ". " + MEZZ_CAVEAT,
      "부채의 수면은 " + fx(s.waterline) + " — " + m.tower.floors + "층 중 " +
        fx(m.tower.submergedFloors) + "층 높이다.",
      "묶는 제약은 " + BINDING_LABEL[s.binding] + " " +
        pct(m.assumptions.debtYieldMin, 1) + " — 대출은 LTV 한도 " +
        fx(s.ltvCap) + " 에 닿지 못하고 " + fx(s.senior) + " 에서 멈춘다."
    ];
  }

  // ── 계기판 ──────────────────────────────────────────────────────────────
  function rateSeries(market) {
    var rates = (market && market.rates) || {};
    return RATE_SERIES.map(function (spec) {
      var r = rates[spec.key] || {};
      var months = (r.trend_months || []).slice(-RATE_MONTHS);
      return {
        key: spec.key,
        short: spec.short,
        name: r.name || spec.short,
        className: spec.className,
        unit: r.unit || "연%",
        latest: (r.latest || {}),
        points: months.map(function (p) {
          return { label: ymDot(p.ym), y: p.value_pct };
        })
      };
    });
  }

  /** 권역 카드 하나. 수치는 전부 글자로도 존재한다(차트는 형태만 보탠다). */
  function gaugeCard(m) {
    var rows = [
      { k: "유효임대료", v: won(m.rent.effective), u: "원/㎡·월", est: true },
      { k: "공실률", v: pctp(m.vacancyPct), u: "" },
      { k: "소득수익률 cap", v: pct(m.cap), u: "" },
      { k: "국고채 10년 대비", v: bp(m.spreadBp), u: "", alert: m.spreadBelowTreasury }
    ];
    var body = "";
    rows.forEach(function (row) {
      body += '<div class="g-row' + (row.alert ? " is-alert" : "") + '">' +
        '<dt>' + esc(row.k) +
        (row.est ? '<span class="chip" title="' + esc(m.rent.caveat) + '">추정</span>' : "") +
        "</dt>" +
        '<dd><b class="num">' + esc(row.v) + "</b>" +
        (row.u ? '<span class="unit">' + esc(row.u) + "</span>" : "") + "</dd></div>";
    });
    var spark = charts.spark(m.trend.map(function (q) { return q.effective; }), {
      width: 168, height: 34, stretch: true,
      aria: m.name + " 유효임대료 " + m.trend.length + "분기 추이 — " +
        (m.trend.length ? m.trend[0].yq + " " + won(m.trend[0].effective) + "원에서 " +
          m.quarter + " " + won(m.rent.effective) + "원으로" : "자료 없음")
    });
    return '<article class="g-card">' +
      '<header class="g-head"><h3>' + esc(m.name) + "</h3>" +
      '<span class="g-n">' + m.buildings + "동 · R-ONE " + esc(m.quarter) + "</span></header>" +
      '<dl class="g-rows">' + body + "</dl>" +
      '<div class="g-spark">' + spark +
      '<span class="cap-note">유효임대료 ' + esc(m.trend.length) + "분기</span></div>" +
      '<p class="g-note">명목 ' + won(m.rent.nominal) + "원에서 렌트프리 " +
      fx(m.rent.rentFreeMo) + "개월/년을 환산 차감한 <b>추정</b>값이다. 가정의 출처: " +
      esc(m.rent.source) + "</p>" +
      "</article>";
  }

  // 좁은 판형은 축소가 아니라 **다시 그린 판**이다. 880 폭 도면을 390px 에
  // 욱여넣으면 11px 글자가 5px 이 된다.
  var RATE_PLATE = {
    wide: { width: 840, height: 300, margin: { t: 18, r: 126, b: 28, l: 44 } },
    compact: { width: 380, height: 300, margin: { t: 16, r: 74, b: 24, l: 34 } }
  };
  // 금리 도면에서 가장 작은 라벨은 기준선 이름(.chart .lab-rule 10px)이다.
  var RATE_MIN_LABEL = 10;

  function ratesLabelScale(renderedWidthPx, compact) {
    var plate = compact ? RATE_PLATE.compact : RATE_PLATE.wide;
    return labelScale(renderedWidthPx, plate.width, RATE_MIN_LABEL);
  }

  function ratesPanel(market, models, compact) {
    var series = rateSeries(market);
    var plate = compact ? RATE_PLATE.compact : RATE_PLATE.wide;
    var rules = models.map(function (m) {
      return {
        value: m.cap * 100,
        label: m.name + (compact ? " " : " cap ") + pct(m.cap),
        className: "rule-cap"
      };
    });
    var chart = charts.line(series.map(function (s) {
      return {
        key: s.key,
        label: compact ? s.short.split(" ")[0] : s.short,
        className: s.className,
        points: s.points
      };
    }), {
      width: plate.width, height: plate.height, margin: plate.margin,
      compact: compact, rules: rules, ticks: 5,
      yFmt: function (v) { return fx(v, 1); },
      aria: "금리 3계열 12개월과 권역 cap 세 선 — " + series.map(function (s) {
        return s.short + " " + fx(s.latest.value_pct, 3) + "%";
      }).join(", ") + ". 권역 cap 은 " + models.map(function (m) {
        return m.name + " " + pct(m.cap);
      }).join(", ") + "."
    });
    var legend = series.map(function (s) {
      return '<li class="' + s.className + '"><span class="swatch"></span>' +
        esc(s.name) + ' <b class="num">' + fx(s.latest.value_pct, 3) + "%</b>" +
        '<span class="unit">' + esc(ymDot(s.latest.ym)) + "</span></li>";
    }).join("");
    return '<figure class="rates">' +
      '<figcaption class="rates-cap">금리 3계열 열두 달과 권역 cap — ' +
      '파선은 흐르지 않는다(R-ONE 한 분기 값이다).</figcaption>' +
      '<div class="rates-plot">' + chart + "</div>" +
      '<ul class="rates-legend">' + legend + "</ul></figure>";
  }

  function renderGauge(market, underwriting, manifest, models, compact) {
    var t10 = (market.rates.treasury10y && market.rates.treasury10y.latest) || {};
    var allBelow = models.every(function (m) { return m.spreadBelowTreasury; });
    var head = '<p class="lede-alert' + (allBelow ? " is-alert" : "") + '">' +
      (allBelow
        ? "세 권역 모두 스프레드가 음수다 — <b>임대수익이 국고채 10년을 밑돈다</b>. " +
          "권역 소득수익률 " + models.map(function (m) {
            return pct(m.cap);
          }).join(" · ") + " 에 대해 국고채 10년은 " + fx(t10.value_pct, 3) +
          "% (" + esc(ymDot(t10.ym)) + ") 다."
        : "권역별 스프레드의 부호가 갈린다.") + "</p>";
    var cards = models.map(gaugeCard).join("");
    return head +
      '<div class="g-grid">' + cards + "</div>" +
      ratesPanel(market, models, compact) +
      '<p class="g-foot">기준월이 하나가 아니다 — 임대료·공실·cap 은 R-ONE ' +
      esc(models[0].quarter) + ", 금리는 한국은행 ECOS " + esc(ymDot(t10.ym)) +
      " 다. 원장의 데이터 기준월은 " + esc(ymDot(manifest.data_cutoff)) +
      " 이고, 관측월과 수집일은 방법론에 따로 적었다.</p>";
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  var WIDE_QUERY = "(min-width: 760px)";

  function mount(doc, data) {
    doc = doc || document;
    data = data || {};
    var plate = doc.getElementById("hero-plate");
    var panel = doc.getElementById("hero-panel");
    var reading = doc.getElementById("hero-reading");
    var tabsEl = doc.getElementById("hero-tabs");
    var gaugeEl = doc.getElementById("gauge");
    if (!plate || !tabsEl) return null;

    var market = data.market, uw = data.underwriting, manifest = data.manifest || {};
    var names = Object.keys((market && market.regions) || {});
    if (!names.length) {
      plate.innerHTML = '<p class="fail">권역 자료를 읽지 못했다 — ' +
        'out/market.json 이 실리지 않았다.</p>';
      return null;
    }
    var models = names.map(function (n) { return regionModel(market, uw, n); });
    var byName = {};
    models.forEach(function (m) { byName[m.name] = m; });
    var active = names[0];
    var wide = typeof matchMedia === "function" ? matchMedia(WIDE_QUERY) : null;

    function paintTabs() {
      tabsEl.innerHTML = names.map(function (n) {
        var on = n === active;
        return '<button type="button" role="tab" id="tab-' + esc(n) + '"' +
          ' data-region="' + esc(n) + '"' +
          ' aria-selected="' + (on ? "true" : "false") + '"' +
          ' aria-controls="hero-panel" tabindex="' + (on ? "0" : "-1") + '"' +
          ' class="r-tab' + (on ? " on" : "") + '">' + esc(n) + "</button>";
      }).join("");
    }

    function isCompact() {
      return !(wide && wide.matches);
    }

    // 그려 놓고 나서 실폭을 재어 라벨 계수를 돌려준다 — 화면에서 9px 아래로
    // 내려가는 글자가 없도록. 폭을 읽는 곳은 여기 한 곳뿐이다.
    function fitLabels() {
      var svg = plate.querySelector("svg.plate-svg");
      if (svg) {
        svg.style.setProperty("--fig-k", String(plateLabelScale(
          svg.getBoundingClientRect().width, { compact: isCompact() })));
      }
      var chart = gaugeEl && gaugeEl.querySelector(".rates-plot .chart");
      if (chart) {
        chart.style.setProperty("--fig-k", String(ratesLabelScale(
          chart.getBoundingClientRect().width, isCompact())));
      }
    }

    function paintPlate() {
      var m = byName[active];
      plate.innerHTML = render(m, { compact: isCompact() });
      if (panel) panel.setAttribute("aria-labelledby", "tab-" + active);
      if (reading) {
        reading.innerHTML = readingLines(m).map(function (s) {
          return "<li>" + esc(s) + "</li>";
        }).join("");
      }
      fitLabels();
    }

    function paintGauge() {
      if (!gaugeEl) return;
      gaugeEl.innerHTML = renderGauge(market, uw, manifest, models, isCompact());
      fitLabels();
    }

    function select(name) {
      if (!byName[name] || name === active) return;
      active = name;
      paintTabs();
      paintPlate();
      var btn = tabsEl.querySelector('[aria-selected="true"]');
      if (btn) btn.focus();
    }

    tabsEl.addEventListener("click", function (ev) {
      // 버튼의 정체는 글자가 아니라 data-region 이다 — 라벨을 손보는 순간
      // textContent 로 고르던 코드는 조용히 아무 권역도 못 찾는다.
      var btn = ev.target.closest ? ev.target.closest("button[role=tab]") : null;
      if (btn) select(btn.getAttribute("data-region"));
    });
    tabsEl.addEventListener("keydown", function (ev) {
      var step = ev.key === "ArrowRight" ? 1 : (ev.key === "ArrowLeft" ? -1 : 0);
      if (!step) return;
      ev.preventDefault();
      var i = names.indexOf(active);
      select(names[(i + step + names.length) % names.length]);
    });
    if (wide && wide.addEventListener) {
      // 판형이 바뀌면 라벨 밀도가 달라진다 — 줄여서 읽히지 않게 다시 그린다.
      wide.addEventListener("change", function () { paintPlate(); paintGauge(); });
    }
    if (typeof window !== "undefined" && window.addEventListener) {
      // 폭이 달라지면 배율이 달라진다. 다시 그리지는 않는다 — 계수만 고쳐 준다.
      var pending = false;
      window.addEventListener("resize", function () {
        if (pending) return;
        pending = true;
        var raf = window.requestAnimationFrame ||
          function (fn) { return setTimeout(fn, 16); };
        raf(function () { pending = false; fitLabels(); });
      });
    }

    paintTabs();
    paintPlate();
    paintGauge();
    return { select: select, models: models };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var plate = document.getElementById("hero-plate");
    if (!plate) return;
    try {
      mount(document, {
        market: window.__DATA_MARKET,
        underwriting: window.__DATA_UNDERWRITING,
        manifest: window.__DATA_MANIFEST
      });
    } catch (err) {
      // 조용히 빈 화면을 내보내지 않는다 — 무엇이 없어서 못 그렸는지 적는다.
      plate.innerHTML = '<p class="fail">서장을 그리지 못했다 — ' +
        esc(err && err.message ? err.message : String(err)) + "</p>";
    }
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }

  return {
    FLOORS: FLOORS,
    CELLS_PER_FLOOR: CELLS_PER_FLOOR,
    pickDarkCells: pickDarkCells,
    regionModel: regionModel,
    render: render,
    readingLines: readingLines,
    rateSeries: rateSeries,
    gaugeCard: gaugeCard,
    renderGauge: renderGauge,
    viewBoxWidth: viewBoxWidth,
    layoutOf: layoutOf,
    labelScale: labelScale,
    plateLabelScale: plateLabelScale,
    ratesLabelScale: ratesLabelScale,
    MIN_LABEL_PX: MIN_LABEL_PX,
    K_MAX: K_MAX,
    mount: mount,
    LAYOUT: LAYOUT
  };
});
