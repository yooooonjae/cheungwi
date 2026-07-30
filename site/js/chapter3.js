/**
 * Ⅲ장 시간의 층위 — 지층이 눕는다.
 *
 * 서장에서 지층은 **한 시점의 자본 스택**이었다(가치 100 위에 선순위·메자닌·지분).
 * 여기서는 같은 기둥이 마흔두 개 늘어서서 **시간**이 된다. 달마다 토지·공사·
 * 간접비·금융비용이 퇴적되고, 그 위로 부채의 수면이 차오른다. 서장의 문법을 한
 * 축 돌린 것이지 새로 그린 그림이 아니다 — 좌표는 같은 프리미티브
 * (`charts.strataLayout`)가 낸다.
 *
 * ── 이 그림이 말하는 네 가지 ──
 *   ① 자기자본은 첫 달에 전액 들어간다(D3). 그 뒤 들어오는 돈은 전부 빚이다.
 *      다만 수면 위의 마른 두께가 **자기자본과 같아지는 달은 준공 달 하나뿐**이다
 *      — 그 전에는 미자본화 이자만큼, 그 뒤에는 임대기간 순현금만큼 더 두껍다.
 *   ② 발생이자는 준공 달에 한 번에 원금으로 얹힌다(D5). 그때까지 수면 위에
 *      부풀어 있던 두께가 그 달에 꺼진다 — 아직 자본화되지 않은 이자다.
 *   ③ 준공은 퇴적이 멈추는 자리다. 지질 단면의 **부정합면**처럼, 그 위로는
 *      다른 종류의 시간(임대·매각)이 온다.
 *   ④ 매각가와 총사업비 사이의 얇은 층이 개발이익이다. 그 층만 **해칭**인 것은
 *      exit cap 이 관측이 아니라 가정이기 때문이다(서장의 규칙 그대로).
 *
 * ── LLCR 은 두 값이다 ──
 * 원장이 "하나만 인용하지 말 것"을 D8 에 적어 두었다. 화면이 하나만 실으면 그
 * 계약이 화면에서만 깨진다 — 그래서 표를 짓는 함수가 두 값과 원문 주석을 함께
 * 낸다(`llcrPair`). 검사가 그것을 붙든다.
 *
 * 순수 함수(`depositModel`·`depositGeom`·`stressModel`·`ladderModel`·`landModel`)와
 * DOM(`mount`)을 나눈 이유는 앞 장들과 같다.
 */

;(function (root, factory) {
  "use strict";
  var isNode = typeof module !== "undefined" && module.exports;
  var scope = typeof window !== "undefined" ? window : (root || {});
  var charts = isNode ? require("./charts.js") : scope.CheungwiCharts;
  var engine = isNode ? require("./engine.js") : scope.CheungwiEngine;
  var hero = isNode ? require("./hero.js") : scope.CheungwiHero;
  var api = factory(charts, engine, hero);
  if (isNode) module.exports = api;
  if (typeof window !== "undefined") window.CheungwiChapter3 = api;
  else if (root) root.CheungwiChapter3 = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, engine, hero) {
  "use strict";

  var tag = charts.tag, text = charts.text, esc = charts.esc, r4 = charts.r4;
  var F = hero.fmt;

  // ── 서식 ────────────────────────────────────────────────────────────────
  function eok(won, digits) {
    return F.group(Number(won / 1e8).toFixed(digits === undefined ? 1 : digits));
  }

  /** 원장의 문장에는 마크다운 강조가 섞여 있다. 지면은 그것을 해석하지 않는다. */
  function plain(s) {
    return String(s == null ? "" : s).replace(/\*\*/g, "");
  }

  /** 값이 없으면 0 이 아니라 줄표다 — 없는 것과 0 은 다른 사실이다. */
  var DASH = "―";

  function pctOrDash(v, d) {
    return (typeof v === "number" && isFinite(v)) ? F.pct(v, d) : DASH;
  }

  function deltaOrDash(v) {
    if (typeof v !== "number" || !isFinite(v)) return DASH;
    return (v > 0 ? "+" : "") + F.fx(v * 100, 2) + "%p";
  }

  // ── 퇴적의 다섯 층 ──────────────────────────────────────────────────────
  // 순서가 계약이다 — 배열의 첫 원소가 바닥(가장 먼저 놓인 것)이다.
  var DEPOSIT_BANDS = [
    { key: "land", label: "토지", className: "dep-land",
      of: "첫 달에 전액. 이 사업의 기반암이다(D1)." },
    { key: "hard", label: "공사비", className: "dep-hard",
      of: "공사기간에 균등 분산. 실제 기성은 S자에 가깝다(D1)." },
    { key: "soft", label: "간접비", className: "dep-soft",
      of: "기본비용의 12%. 취득세·예비비·TI/LC 는 여기 없다." },
    { key: "fin", label: "금융비용", className: "dep-fin",
      of: "취급수수료 + 건설기간 이자. 준공 달에 원금으로 얹힌다(D5)." },
    { key: "op", label: "임대기간 순현금", className: "dep-op",
      of: "이자가 NOI 를 넘는 달들. 자기자본이 메운다고 본다." }
  ];

  /**
   * 월별 현금흐름 → 퇴적 모델.
   *
   * 원장의 `monthly` 는 그 달의 **유량**이고 지층은 **저량**이다. 여기서 한 번
   * 누적으로 바꾸고, 그 뒤로는 아무도 다시 더하지 않는다.
   */
  function depositModel(pf) {
    if (!pf || !pf.model || !Array.isArray(pf.model.monthly)) {
      throw new TypeError("pf_case 의 월별 현금흐름이 없다");
    }
    var M = pf.model, A = M.assumptions;
    var monthly = M.monthly;
    var buildMonths = A.months_build;
    var hardPerMo = A.hard_cost_won / buildMonths;
    var softPerMo = A.soft_cost_won / buildMonths;

    var cols = [];
    var interestCum = 0;
    var opCum = 0;
    for (var i = 0; i < monthly.length; i += 1) {
      var row = monthly[i];
      var built = Math.min(i + 1, buildMonths);
      if (row.phase === "construction") interestCum += row.interest_won;
      // 임대기간의 순현금은 음수다 — 그 **누적 순유출**이 다섯 번째 층이다.
      // 달마다의 손실을 더하지 않고 순액을 누적하는 이유는, 언젠가 NOI 가
      // 이자를 넘는 달이 오면 그 층도 다시 얇아져야 하기 때문이다. 0 에서
      // 멈추는 것은 지층의 두께가 음수일 수 없어서다(그 아래는 이익이지 층이 아니다).
      if (row.phase !== "construction") {
        opCum = Math.max(0, opCum - row.operating_cash_won);
      }
      var parts = {
        land: A.land_won,
        hard: hardPerMo * built,
        soft: softPerMo * built,
        fin: M.fee_won + interestCum,
        op: opCum
      };
      var cum = parts.land + parts.hard + parts.soft + parts.fin + parts.op;
      cols.push({
        month: row.month,
        phase: row.phase,
        parts: parts,
        cum: cum,
        loan: row.loan_balance_won,
        dry: cum - row.loan_balance_won,
        noi: row.noi_won,
        opCash: row.operating_cash_won,
        exitCash: row.exit_cash_won
      });
    }

    return {
      bands: DEPOSIT_BANDS,
      cols: cols,
      months: cols.length,
      buildMonths: buildMonths,
      leaseMonths: A.lease_up_months,
      equity: A.equity_won,
      totalCost: M.total_cost,
      loanWon: M.loan_won,
      ltc: M.ltc,
      exitValue: M.exit_value,
      profit: M.profit,
      margin: M.margin,
      interestWon: M.interest_won,
      feeWon: M.fee_won,
      opLoss: opCum,
      caseName: (pf.case && pf.case.name) || "가상 사업지",
      hypothetical: !!(pf.case && pf.case.hypothetical),
      decisions: (A.decisions || []).slice(),
      caveats: (A.caveats || []).slice()
    };
  }

  // ── 판형 ────────────────────────────────────────────────────────────────
  // 넓은 판은 서장·Ⅱ장과 같은 880 폭이다. 좁은 판은 축소가 아니라 다른 판형이고,
  // 덜어 낸 라벨은 그림 밑 판독 글줄이 본문 크기로 그대로 받는다.
  var DEPOSIT = {
    wide: {
      w: 880, h: 500, topY: 58, groundY: 424, x0: 78, x1: 838,
      ground: { x0: 40, x1: 856, depth: 16 },
      ruleLabelX: 834, headY: 34, annotY: 466,
      verbose: true, minLabel: 11, kMax: 1.6
    },
    compact: {
      w: 430, h: 400, topY: 46, groundY: 334, x0: 52, x1: 416,
      ground: { x0: 20, x1: 424, depth: 12 },
      ruleLabelX: 414, headY: 28, annotY: 372,
      verbose: false, minLabel: 12, kMax: 1.15
    }
  };
  var LADDER = {
    wide: {
      w: 620, h: 320, topY: 56, groundY: 246, x0: 98, x1: 600, gap: 24,
      ground: { x0: 24, x1: 608, depth: 13 },
      headY: 30, verbose: true, minLabel: 11, kMax: 1.4
    },
    compact: {
      w: 430, h: 300, topY: 44, groundY: 228, x0: 40, x1: 418, gap: 14,
      ground: { x0: 16, x1: 424, depth: 11 },
      headY: 26, verbose: false, minLabel: 12, kMax: 1.15
    }
  };
  // 손익분기와 시드 최저는 축 위에서 0.8백만원밖에 떨어져 있지 않다 — 라벨을
  // 같은 높이에 두면 서로를 지운다. 그래서 표식마다 **층과 방향**을 정해 둔다:
  // 왼쪽 이웃은 왼쪽으로 뻗고 오른쪽 이웃은 오른쪽으로 뻗어 서로를 비켜 간다.
  var LAND_LANES = {
    assumed: { dy: -34, anchor: "end" },
    breakeven: { dy: -64, anchor: "end" },
    seedMin: { dy: -34, anchor: "start" },
    median: { dy: -92, anchor: "end" },
    max: { dy: -120, anchor: "end" }
  };
  var LAND = {
    wide: {
      w: 880, h: 206, x0: 84, x1: 772, axisY: 154,
      verbose: true, minLabel: 11, kMax: 1.6
    },
    compact: {
      w: 430, h: 210, x0: 34, x1: 366, axisY: 156,
      verbose: false, minLabel: 12, kMax: 1.15
    }
  };

  function pick(table, opts) {
    return (opts && opts.compact) ? table.compact : table.wide;
  }

  /** 도면마다 배율이 다르다 — 계수는 판형의 선언값에서 나온다(서장 규약). */
  function figScale(widthPx, L) {
    return hero.labelScale(widthPx, L.w, L.minLabel, L.kMax);
  }

  // ── 퇴적의 좌표 ─────────────────────────────────────────────────────────
  /**
   * 천장(`ceiling`)은 매각가 위에 조금의 하늘을 남긴 값이다. 퇴적이 천장을 넘으면
   * `strataLayout` 이 멈춘다 — 기둥 밖으로 삐져나갈 값을 조용히 자르지 않는다.
   */
  function depositGeom(pf, opts) {
    var m = depositModel(pf);
    var L = pick(DEPOSIT, opts);
    var ceiling = (opts && opts.ceiling) || m.exitValue * 1.06;
    var H = L.groundY - L.topY;
    var n = m.cols.length;

    function y(v) {
      return L.groundY - (v / ceiling) * H;
    }

    // 열의 경계를 먼저 잡는다 — 폭을 각자 반올림하면 열 사이에 틈이 생긴다.
    var edges = [];
    for (var e = 0; e <= n; e += 1) {
      edges.push(r4(L.x0 + (L.x1 - L.x0) * (e / n)));
    }

    var yOf = [];
    var cols = m.cols.map(function (col, i) {
      var bands = m.bands.map(function (b) {
        return { key: b.key, label: b.label, className: b.className,
                 value: col.parts[b.key] };
      });
      var laid = charts.strataLayout(bands, {
        x: edges[i], y: L.topY, width: edges[i + 1] - edges[i],
        height: H, total: ceiling
      });
      yOf.push({ month: col.month, cumY: r4(y(col.cum)), loanY: r4(y(col.loan)) });
      return {
        month: col.month, phase: col.phase,
        x: edges[i], width: r4(edges[i + 1] - edges[i]),
        loanY: r4(y(col.loan)),
        rects: laid
      };
    });

    return {
      model: m, ceiling: ceiling,
      x0: edges[0], x1: edges[n], topY: L.topY, groundY: L.groundY,
      cols: cols, yOf: yOf,
      jointX: edges[m.buildMonths],
      costY: y(m.totalCost),
      exitY: y(m.exitValue),
      ticks: charts.niceTicks(0, ceiling, 4).map(function (v) {
        return { value: v, y: r4(y(v)), label: F.group(Number(v / 1e8).toFixed(0)) };
      })
    };
  }

  function depositLines(m) {
    var done = m.cols[m.buildMonths - 1].parts;
    var out = [
      m.caseName + (m.hypothetical ? " · 가상 사업지" : "") + " — " +
        m.buildMonths + "개월 공사와 " + m.leaseMonths + "개월 임대안정화, 모두 " +
        m.months + "달이 왼쪽에서 오른쪽으로 퇴적된다. 총사업비 " +
        eok(m.totalCost) + "억원은 토지 " + eok(done.land) + " · 공사 " +
        eok(done.hard) + " · 간접 " + eok(done.soft) + " · 금융 " +
        eok(done.fin) + "억원으로 쌓인다.",
      "자기자본 " + eok(m.equity) + "억원은 첫 달에 전액 들어간다(D3) — 그 뒤 " +
        "들어오는 돈은 전부 대출이다. 수면 위의 마른 두께가 정확히 그 자기자본이 " +
        "되는 달은 발생이자가 원금으로 얹히는 준공 달 하나뿐이고, 그 전에는 아직 " +
        "자본화되지 않은 이자만큼 더 두껍다. 준공 시점 LTC 는 " +
        F.fx(m.ltc * 100) + "%다.",
      "건설기간 이자 " + eok(m.interestWon) + "억원은 달마다 발생하지만 원금에 " +
        "얹히는 것은 준공 달 한 번이다(D5 · 단리 자본화). 그 전까지 수면 위에 " +
        "부풀어 있는 두께가 아직 자본화되지 않은 이자이고, 준공 달에 그것이 " +
        "꺼지면서 수면이 " + eok(m.loanWon) + "억원으로 뛴다.",
      "준공에서 퇴적이 멈춘다 — 지질 단면의 부정합면이다. 그 위로는 다른 시간이 " +
        "온다: 임대안정화 " + m.leaseMonths + "개월 동안 이자가 NOI 를 넘어 순현금 " +
        eok(m.opLoss) + "억원이 더 들어가고(자기자본이 메운다), 마지막 달에 " +
        eok(m.exitValue) + "억원에 판다.",
      "매각가와 총사업비 사이의 얇은 층이 개발이익 " + eok(m.profit) + "억원 · " +
        "이익률 " + F.fx(m.margin * 100) + "%다(D9 — 총사업비 대비). 그 층만 " +
        "해칭인 것은 매각가가 exit cap 가정 위에 서 있기 때문이다. 임대기간 " +
        "순현금 " + eok(m.opLoss) + "억원은 이 이익에 들어 있지 않다 — 두 지표의 " +
        "범위가 다르다."
    ];
    return out;
  }

  function depositAria(m) {
    return "개발 PF 월별 퇴적 단면 — " + depositLines(m).join(" ");
  }

  function profitHatch() {
    return tag("defs", {}, tag("pattern", {
      id: "ch3-hatch-profit", width: 5, height: 5,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"
    }, tag("line", { x1: 0, y1: 0, x2: 0, y2: 5, class: "hatch-profit" })));
  }

  /**
   * 수면은 계단이다. 월별 잔액을 매끈한 곡선으로 이으면 준공 달의 자본화가
   * 완만한 상승처럼 보인다 — 그 한 번의 도약이 이 그림의 사건이다.
   */
  function waterPath(g) {
    var d = "M" + g.cols[0].x + " " + g.cols[0].loanY;
    g.cols.forEach(function (c) {
      d += " L" + c.x + " " + c.loanY + " L" + r4(c.x + c.width) + " " + c.loanY;
    });
    return d;
  }

  function renderDeposit(pf, opts) {
    var g = depositGeom(pf, opts);
    var m = g.model;
    var L = pick(DEPOSIT, opts);
    var inner = hero.defs("ch3-") + profitHatch();
    inner += hero.groundPart(L, "ch3-");

    // ① 눈금 — 왼쪽은 금액(억원), 아래는 달.
    g.ticks.forEach(function (t) {
      inner += tag("line", { x1: g.x0, x2: g.x1, y1: t.y, y2: t.y, class: "grid" });
      inner += text(g.x0 - 7, t.y + 3.5, t.label,
                    { class: "lab lab-num", "text-anchor": "end" });
    });
    inner += text(g.x0 - 7, r4(L.topY - 12), "억원",
                  { class: "lab", "text-anchor": "end" });

    // ② 퇴적 — 마흔두 개의 지층 기둥. 서장의 프리미티브 그대로다.
    var strata = "";
    g.cols.forEach(function (c) {
      c.rects.forEach(function (b) {
        if (b.height <= 0) return;
        strata += tag("rect", {
          x: b.x, y: b.y, width: b.width, height: b.height,
          "data-key": b.key, class: "stratum " + b.className
        });
      });
    });
    inner += tag("g", { class: "strata deposit", "data-part": "deposit" }, strata);

    // ③ 개발이익 — 매각가와 총사업비 사이. 해칭인 것은 가정이기 때문이다.
    inner += tag("rect", {
      x: g.jointX, y: r4(g.exitY), width: r4(g.x1 - g.jointX),
      height: r4(g.costY - g.exitY),
      fill: "url(#ch3-hatch-profit)", class: "profit-band"
    });
    inner += tag("line", {
      x1: g.x0, x2: g.x1, y1: r4(g.exitY), y2: r4(g.exitY), class: "exit-rule"
    });
    inner += tag("line", {
      x1: g.x0, x2: g.x1, y1: r4(g.costY), y2: r4(g.costY), class: "base-rule"
    });

    // ④ 부채의 수면 — 시간축에서는 잔물결이 아니라 계단이다.
    var wd = waterPath(g);
    inner += tag("g", { class: "water", "data-part": "water" },
      tag("path", {
        d: wd + " L" + g.x1 + " " + g.groundY + " L" + g.x0 + " " + g.groundY + " Z",
        class: "water-body"
      }) + tag("path", { d: wd, class: "water-line" }));

    // ⑤ 부정합면 — 퇴적이 멈추는 자리. 지질 도면은 이 경계를 물결선으로 긋는다.
    var wave = "M" + g.jointX + " " + r4(L.topY - 6);
    for (var s = 0; s < 12; s += 1) {
      var seg = (g.groundY - L.topY + 6) / 12;
      wave += " q" + r4(s % 2 === 0 ? 3.4 : -3.4) + " " + r4(seg / 2) +
        " 0 " + r4(seg);
    }
    inner += tag("path", { d: wave, class: "unconformity" });
    // 좁은 판에서는 이 라벨이 오른쪽으로 뻗으면 판형을 넘는다 — 방향을 뒤집고
    // 짧게 적는다. 잘린 글자보다 작은 글자가 낫고, 덜어 낸 말은 글줄이 받는다.
    inner += L.verbose
      ? text(r4(g.jointX + 5), r4(L.topY - 10),
             "준공 " + m.buildMonths + "개월 · 퇴적이 멈춘다",
             { class: "lab lab-joint" })
      : text(r4(g.jointX - 5), r4(L.topY - 10), "준공 " + m.buildMonths + "개월",
             { class: "lab lab-joint", "text-anchor": "end" });

    // ⑥ 라벨 — 좁은 판은 셋만 남기고 나머지는 판독 글줄이 받는다.
    inner += text(L.ruleLabelX, r4(g.exitY - 6),
                  "매각가 " + eok(m.exitValue) + "억 · 가정",
                  { class: "lab lab-exit", "text-anchor": "end" });
    // 총사업비 선의 이름은 **왼쪽**에 붙인다. 오른쪽 끝은 임대기간 순현금이
    // 그 선 위로 올라선 자리라 라벨이 지층에 묻힌다.
    inner += text(r4(g.x0 + 6), r4(g.costY - 6),
                  "총사업비 " + eok(m.totalCost) + "억", { class: "lab lab-cost" });
    if (L.verbose) {
      inner += text(r4(g.jointX + 8), r4((g.exitY + g.costY) / 2 + 4),
                    "개발이익 " + eok(m.profit) + "억 · " +
                    F.fx(m.margin * 100) + "%", { class: "lab lab-profit" });
      // 두 지시선은 각자의 사실을 짚는다 — 라벨을 지층 위에 얹으면 읽히지 않고,
      // 빼면 그림이 스스로 설명하지 못한다.
      //
      // 마른 두께가 **자기자본과 같아지는 달은 준공 달 하나뿐이다.** 그 전에는
      // 아직 자본화되지 않은 발생이자만큼 더 두껍고(공사 마지막 전달까지 계속
      // 부푼다), 그 뒤로는 임대기간 순현금이 얹혀 다시 두꺼워진다. 그래서 짚는
      // 달을 준공(마지막 공사 달)으로 못박고, 지시선 자체가 그 달의 마른
      // 두께(퇴적 꼭대기 ↔ 수면)를 재는 치수선이 된다.
      var iDry = Math.max(0, Math.min(m.buildMonths - 1, g.cols.length - 1));
      var iWet = Math.min(20, g.cols.length - 1);
      var dryX = r4(g.cols[iDry].x + g.cols[iDry].width / 2);
      var dryTop = r4(g.yOf[iDry].cumY);
      var dryBot = r4(g.yOf[iDry].loanY);
      var callout = r4(g.costY + 22);
      inner += tag("line", {
        x1: dryX, x2: dryX, y1: dryTop, y2: dryBot, class: "callout"
      });
      // 치수선의 양 끝 — 어디부터 어디까지를 잰 것인지 선이 스스로 말한다.
      [dryTop, dryBot].forEach(function (yy) {
        inner += tag("line", {
          x1: r4(dryX - 4), x2: r4(dryX + 4), y1: yy, y2: yy, class: "callout"
        });
      });
      inner += text(dryX, r4(dryTop - 7),
                    "준공 시점의 마른 두께 = 자기자본 " + eok(m.equity) + "억",
                    { class: "lab lab-dry", "text-anchor": "end" });
      var wpt = g.cols[iWet];
      inner += tag("line", {
        x1: r4(wpt.x + wpt.width / 2), x2: r4(wpt.x + wpt.width / 2),
        y1: r4(callout + 22), y2: r4(g.yOf[iWet].loanY), class: "callout is-water"
      });
      inner += text(r4(wpt.x + wpt.width / 2), r4(callout + 18),
                    "수면 = 대출잔액",
                    { class: "lab lab-water", "text-anchor": "middle" });
      // 각주는 그림이 말하지 못하는 것만 적는다. 한때 여기에 "위가 자기자본이다"가
      // 있었는데, 그것은 준공 달 하나에서만 참이라 바로 위의 치수선과 부딪혔다 —
      // 공사 중에는 아직 원금으로 얹히지 않은 발생이자만큼, 준공 뒤에는 임대기간의
      // 누적 순유출만큼 더 두껍다. 두 줄로 나눈 것은 한 줄로 적으면 좁은 판형에서
      // 계수가 커진 글자가 판형을 넘기 때문이다.
      inner += text(g.x0, L.annotY,
                    "가로축 한 칸 = 한 달 · 세로축 = 누적 투입액(억원)",
                    { class: "lab" });
      inner += text(g.x0, r4(L.annotY + 15),
                    "수면 아래 = 대출잔액 · 위 = 자기자본 + 아직 자본화되지 않은 " +
                    "이자(준공 뒤에는 운영 순유출)", { class: "lab" });
    }
    [[0, "착공"], [m.buildMonths, "준공"], [m.months - 1, "매각"]]
      .forEach(function (pair) {
        var idx = Math.min(pair[0], g.cols.length - 1);
        inner += text(r4(g.cols[idx].x), r4(g.groundY + 26), pair[1],
                      { class: "lab lab-when",
                        "text-anchor": pair[0] === 0 ? "start" : "middle" });
      });
    inner += text(g.x0, L.headY,
                  "시간의 층위 · " + m.months + "개월", { class: "lab lab-head2" });

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h, role: "img",
      "aria-label": depositAria(m),
      class: "plate-svg ch-fig dep-plate" + (L.verbose ? "" : " is-compact"),
      "data-fig-w": L.w, "data-fig-min": L.minLabel, "data-fig-kmax": L.kMax,
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  // ── 스트레스 15행 ───────────────────────────────────────────────────────
  var STRESS_GROUPS = [
    { prefix: "공사비", key: "cost", label: "공사비" },
    { prefix: "준공지연", key: "delay", label: "일정" },
    { prefix: "금리", key: "rate", label: "금리" },
    { prefix: "임대개시", key: "leaseup", label: "일정" },
    { prefix: "안정화 NOI", key: "noi", label: "수익" },
    { prefix: "exit cap", key: "exit", label: "매각" },
    { prefix: "매각가", key: "exit", label: "매각" },
    { prefix: "자기자본", key: "equity", label: "제도 사다리" }
  ];

  function groupOf(name) {
    for (var i = 0; i < STRESS_GROUPS.length; i += 1) {
      if (String(name).indexOf(STRESS_GROUPS[i].prefix) === 0) {
        return STRESS_GROUPS[i];
      }
    }
    return { key: "other", label: "기타" };
  }

  function stressModel(pf) {
    if (!pf || !pf.stress || !Array.isArray(pf.stress.rows)) {
      throw new TypeError("pf_case 의 스트레스 표가 없다");
    }
    var M = pf.model;
    var rows = pf.stress.rows.map(function (r) {
      var g = groupOf(r.name);
      return {
        name: r.name, shock: r.shock, group: g.key, groupLabel: g.label,
        irr: (typeof r.equity_irr === "number") ? r.equity_irr : null,
        delta: (typeof r.delta === "number") ? r.delta : null,
        ltc: r.ltc, llcr: r.llcr
      };
    });
    var scored = rows.filter(function (r) { return r.irr !== null; });
    var worst = null, best = null;
    scored.forEach(function (r) {
      if (!worst || r.irr < worst.irr) worst = r;
      if (!best || r.irr > best.irr) best = r;
    });
    return {
      n: pf.stress.n,
      rows: rows,
      base: {
        name: "기준 시나리오", shock: "―", group: "base",
        irr: M.equity_irr, delta: null, ltc: M.ltc,
        llcr: M.llcr, llcrNoiOnly: M.llcr_noi_only
      },
      worst: worst, best: best,
      negatives: scored.filter(function (r) { return r.irr < 0; }).length,
      llcrNote: pf.stress.llcr_note,
      modelLlcrNote: M.llcr_note,
      stressNote: pf.stress.note
    };
  }

  /**
   * LLCR 두 값을 한 문자열로. **하나만 인용하지 말 것**이 원장의 계약이라,
   * 화면의 어느 자리에서든 두 값이 함께 나가야 한다.
   */
  function llcrPair(m) {
    return "LLCR " + F.fx(m.base.llcr, 4) + "(매각대금 포함) · " +
      F.fx(m.base.llcrNoiOnly, 4) + "(잔여 NOI 만) — " + plain(m.modelLlcrNote);
  }

  function stressTableHtml(m) {
    var head = ["시나리오", "충격", "지분 IRR", "Δ IRR", "LTC", "LLCR"];
    var out = '<table class="stress-table">';
    out += "<caption>" + esc(
      "기준 시나리오 한 줄과 충격 " + m.n + "행. LLCR 은 기준 행만 두 값을 함께 " +
      "낸다 — 행 사이 비교는 같은 정의끼리만 하라.") + "</caption>";
    out += "<thead><tr>" + head.map(function (h, i) {
      return '<th scope="col"' + (i >= 2 ? ' class="col-num"' : "") + ">" +
        esc(h) + "</th>";
    }).join("") + "</tr></thead><tbody>";

    out += '<tr class="is-base"><th scope="row">' + esc(m.base.name) + "</th>" +
      "<td>" + DASH + "</td>" +
      '<td class="num">' + esc(pctOrDash(m.base.irr)) + "</td>" +
      '<td class="num">' + DASH + "</td>" +
      '<td class="num">' + esc(F.fx(m.base.ltc * 100) + "%") + "</td>" +
      '<td class="num llcr-two">' + esc(F.fx(m.base.llcr, 4)) +
      '<span class="llcr-alt">' + esc(F.fx(m.base.llcrNoiOnly, 4)) +
      "</span></td></tr>";

    m.rows.forEach(function (r) {
      var alert = r.irr !== null && r.irr < 0;
      out += '<tr class="g-' + esc(r.group) + (alert ? " is-alert" : "") +
        (m.worst && r.name === m.worst.name ? " is-worst" : "") + '">' +
        '<th scope="row">' + esc(r.name) +
        '<span class="row-group">' + esc(r.groupLabel) + "</span></th>" +
        "<td>" + esc(r.shock) + "</td>" +
        '<td class="num">' + esc(pctOrDash(r.irr)) + "</td>" +
        '<td class="num">' + esc(deltaOrDash(r.delta)) + "</td>" +
        '<td class="num">' + esc(F.fx(r.ltc * 100) + "%") + "</td>" +
        '<td class="num">' + esc(F.fx(r.llcr, 4)) + "</td></tr>";
    });
    out += "</tbody><tfoot><tr><td colspan=\"6\">" +
      esc(plain(m.llcrNote)) + " " + esc(plain(m.stressNote)) +
      "</td></tr></tfoot></table>";
    return out;
  }

  function stressLines(m) {
    // 모든 행의 IRR 이 없으면 최악·최선을 말할 수 없다. 지어내지 않고 그렇게 적는다.
    if (!m.worst || !m.best) {
      return ["열다섯 행 가운데 지분 IRR 이 구해진 행이 없다 — 부호 변화가 " +
              "없거나 근이 탐색 범위 밖이라는 뜻이지 '0%' 가 아니다.",
              llcrPair(m), plain(m.stressNote)];
    }
    return [
      "열다섯 개의 충격 가운데 지분 IRR 이 음수로 돌아서는 것이 " + m.negatives +
        "개다. 가장 나쁜 것은 " + m.worst.name + "(" + F.pct(m.worst.irr) +
        " · 기준 대비 " + deltaOrDash(m.worst.delta) + ")이고, 가장 좋은 것은 " +
        m.best.name + "(" + F.pct(m.best.irr) + ")이다.",
      llcrPair(m),
      plain(m.stressNote)
    ];
  }

  // ── 자기자본 제도 사다리 ────────────────────────────────────────────────
  /**
   * 같은 사업이 제도 한 칸에 두 얼굴을 보인다 — 자기자본을 올리면 지분 IRR 은
   * 깎이고 대주 커버리지(LLCR)는 좋아진다. 두 값을 나란히 싣는 이유다.
   */
  function ladderModel(pf) {
    var s = stressModel(pf);
    var rungs = s.rows.filter(function (r) { return r.group === "equity"; })
      .map(function (r) {
        var share = 1 - r.ltc;
        return {
          name: r.name, equityShare: share, ltc: r.ltc,
          irr: r.irr, delta: r.delta, llcr: r.llcr,
          bands: [
            { key: "senior", label: "대출", className: "stratum-senior",
              value: r.ltc * 100 },
            { key: "equity", label: "자기자본", className: "stratum-equity",
              value: share * 100 }
          ]
        };
      });
    if (!rungs.length) {
      throw new TypeError(
        "제도 사다리 행이 없다 — 스트레스 표에 '자기자본' 시나리오가 실리지 " +
        "않았다. 사다리를 빈 그림으로 그리면 제도가 없는 것처럼 읽힌다");
    }
    var base = {
      name: "이 사업의 가정", equityShare: 1 - pf.model.ltc, ltc: pf.model.ltc,
      irr: pf.model.equity_irr, delta: null, llcr: pf.model.llcr,
      bands: [
        { key: "senior", label: "대출", className: "stratum-senior",
          value: pf.model.ltc * 100 },
        { key: "equity", label: "자기자본", className: "stratum-equity",
          value: (1 - pf.model.ltc) * 100 }
      ]
    };
    return {
      rungs: rungs, base: base, cols: [base].concat(rungs),
      note: "자기자본 비율은 **그 시나리오 자신의 총사업비** 대비다. 사다리의 " +
        "네 칸은 제도가 요구하는 최소 자기자본(5~20%)을 그대로 옮긴 것이고, " +
        "맨 왼쪽 칸은 이 사업이 실제로 가정한 자기자본이다."
    };
  }

  function ladderGeom(pf, opts) {
    var m = ladderModel(pf);
    var L = pick(LADDER, opts);
    var H = L.groundY - L.topY;
    var n = m.cols.length;
    var slot = (L.x1 - L.x0) / n;
    var width = slot - L.gap;
    if (!(width > 0)) throw new TypeError("사다리 칸이 너무 좁다");

    var cols = m.cols.map(function (c, i) {
      var x = r4(L.x0 + slot * i + L.gap / 2);
      return {
        key: c.name, equityShare: c.equityShare, irr: c.irr, llcr: c.llcr,
        x: x, width: r4(width),
        rects: charts.strataLayout(c.bands, {
          x: x, y: L.topY, width: width, height: H, total: 100
        })
      };
    });
    return { model: m, cols: cols, topY: L.topY, groundY: L.groundY,
             x0: L.x0, x1: L.x1 };
  }

  function ladderLines(m) {
    var lo = m.rungs[0], hi = m.rungs[m.rungs.length - 1];
    return [
      "제도가 요구하는 자기자본을 " + F.fx(lo.equityShare * 100, 0) + "% 에서 " +
        F.fx(hi.equityShare * 100, 0) + "% 로 올리면 지분 IRR 은 " +
        F.pct(lo.irr) + " 에서 " + F.pct(hi.irr) + " 로 깎이고, 대주 커버리지 " +
        "LLCR 은 " + F.fx(lo.llcr, 4) + " 에서 " + F.fx(hi.llcr, 4) +
        " 로 좋아진다. 같은 사업이 제도 한 칸에 두 얼굴을 보인다.",
      "레버리지가 지분 수익을 만든다는 말은 이 표에서 숫자가 된다 — " +
        "자기자본을 절반으로 줄이면(10% → 5%) IRR 이 " +
        deltaOrDash(m.rungs[0].irr - m.rungs[1].irr) + " 움직인다. 그 대가는 " +
        "대주가 진다.",
      "이 사업이 가정한 자기자본은 총사업비의 " +
        F.fx(m.base.equityShare * 100) + "%(기본비용의 25%)로 사다리의 " +
        "맨 위 칸보다도 두껍다 — 사다리와 나란히 놓아 그 거리를 보인다.",
      plain(m.note)
    ];
  }

  function renderLadder(pf, opts) {
    var g = ladderGeom(pf, opts);
    var L = pick(LADDER, opts);
    var inner = hero.defs("ch3l-");
    inner += hero.groundPart(L, "ch3l-");

    g.cols.forEach(function (c, i) {
      var body = "";
      c.rects.forEach(function (b) {
        if (b.height <= 0) return;
        body += tag("rect", {
          x: b.x, y: b.y, width: b.width, height: b.height,
          "data-key": b.key, class: "stratum " + b.className
        });
      });
      inner += tag("g", { class: "strata rung" + (i === 0 ? " is-case" : "") }, body);
      var cx = r4(c.x + c.width / 2);
      inner += text(cx, r4(L.groundY + 18),
                    F.fx(c.equityShare * 100, i === 0 ? 1 : 0) + "%",
                    { class: "lab lab-num", "text-anchor": "middle" });
      inner += text(cx, r4(L.groundY + 33),
                    i === 0 ? "이 사업" : "제도",
                    { class: "lab lab-when", "text-anchor": "middle" });
      inner += text(cx, r4(L.topY - 18), F.pct(c.irr),
                    { class: "lab lab-irr", "text-anchor": "middle" });
      if (L.verbose) {
        inner += text(cx, r4(L.topY - 4), "LLCR " + F.fx(c.llcr, 3),
                      { class: "lab lab-llcr", "text-anchor": "middle" });
      }
    });
    // 행의 이름은 왼쪽 여백에 한 번만 적는다 — 칸마다 붙이면 숫자가 묻힌다.
    if (L.verbose) {
      inner += text(r4(L.x0 - 12), r4(L.topY - 18), "지분 IRR",
                    { class: "lab lab-head2", "text-anchor": "end" });
      inner += text(r4(L.x0 - 12), r4(L.topY - 4), "LLCR",
                    { class: "lab lab-head2", "text-anchor": "end" });
      inner += text(r4(L.x0 - 12), r4(L.groundY + 18), "자기자본",
                    { class: "lab lab-head2", "text-anchor": "end" });
    }

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h, role: "img",
      "aria-label": "자기자본 제도 사다리 — " + ladderLines(g.model).join(" "),
      class: "plate-svg ch-fig ladder-plate" + (L.verbose ? "" : " is-compact"),
      "data-fig-w": L.w, "data-fig-min": L.minLabel, "data-fig-kmax": L.kMax,
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  // ── 손익분기 토지단가 ───────────────────────────────────────────────────
  /**
   * 프라임 필지에서는 이 사업이 서지 않는다 — 그 판정은 문장이 아니라 계산이다.
   * 시드의 공시지가가 손익분기 아래로 내려가면 판정도 뒤집힌다.
   */
  function landModel(pf) {
    var ctx = pf && pf.land_price_context;
    if (!ctx || !ctx.seed_land_price_won_m2) {
      throw new TypeError("pf_case 의 토지단가 맥락이 없다");
    }
    var seed = ctx.seed_land_price_won_m2;
    var breakeven = ctx.breakeven_land_price_won_m2;
    var assumed = ctx.assumed_land_price_won_m2;
    // 축은 "판정이 갈리는 구간"까지만 연다. 중위·최대는 그 밖이라 파단 표기로 남는다.
    var axisMax = Math.ceil(Math.max(assumed, breakeven, seed.min) * 1.12 / 1e6) * 1e6;

    function mark(key, label, won, kind) {
      return {
        key: key, label: label, won: won, kind: kind,
        clipped: won > axisMax
      };
    }
    return {
      assumed: assumed, breakeven: breakeven,
      seedMin: seed.min, seedMedian: seed.median, seedMax: seed.max,
      n: seed.n, source: seed.source,
      axisMax: axisMax,
      stands: seed.min <= breakeven,
      gapToMin: seed.min / breakeven - 1,
      gapToMedian: seed.median / breakeven,
      marks: [
        mark("assumed", "가정 토지단가", assumed, "가정"),
        mark("breakeven", "손익분기", breakeven, "계산"),
        mark("seedMin", "시드 최저", seed.min, "실측"),
        mark("median", "시드 중위", seed.median, "실측"),
        mark("max", "시드 최고", seed.max, "실측")
      ],
      note: plain(ctx.note)
    };
  }

  function landGeom(pf, opts) {
    var m = landModel(pf);
    var L = pick(LAND, opts);
    var scale = charts.scaleLinear(0, m.axisMax, L.x0, L.x1);
    return {
      model: m, x0: L.x0, x1: L.x1, axisY: L.axisY,
      ticks: charts.niceTicks(0, m.axisMax, 4).map(function (v) {
        return { value: v, x: r4(scale(v)), label: F.fx(v / 1e6, 0) };
      }),
      marks: m.marks.map(function (p, i) {
        return {
          key: p.key, label: p.label, kind: p.kind, won: p.won,
          clipped: p.clipped,
          x: r4(p.clipped ? L.x1 : scale(p.won)),
          lane: i
        };
      })
    };
  }

  function landLines(m) {
    return [
      "이 사업이 서려면 토지를 ㎡당 " + F.group(Math.round(m.breakeven).toFixed(0)) +
        "원 아래로 사야 한다(손익분기 토지단가). 시드 " + m.n +
        "필지의 개별공시지가는 최저가 " +
        F.group(m.seedMin.toFixed(0)) + "원, 중위가 " +
        F.group(m.seedMedian.toFixed(0)) + "원이다 — " +
        (m.stands
          ? "최저 필지라면 사업이 선다."
          : "가장 싼 필지조차 손익분기를 " + F.fx(m.gapToMin * 100) +
            "% 넘는다. 프라임 필지에서는 이 사업이 서지 않는다."),
      "중위 필지로 사면 토지비만 손익분기의 " + F.fx(m.gapToMedian, 1) +
        "배다 — 완성된 자산의 가치가 토지 원가를 덮지 못한다.",
      "이 사업이 쓴 토지단가 ㎡당 " + F.group(m.assumed.toFixed(0)) +
        "원은 실측이 아니라 **가정**이다(강남권 이면부 중형 개발부지). " +
        "시드는 3대 권역의 프라임 대로변 표본이라 그 공시지가를 신규 개발부지의 " +
        "매입 원가로 쓸 수 없다 — 두 수를 한 축에 올린 것은 비교가 아니라 거리를 " +
        "보이기 위해서다.",
      m.note + " 출처: " + m.source + "."
    ].map(plain);
  }

  function renderLand(pf, opts) {
    var g = landGeom(pf, opts);
    var m = g.model;
    var L = pick(LAND, opts);
    var inner = "";
    inner += tag("line", {
      x1: g.x0, x2: g.x1, y1: L.axisY, y2: L.axisY, class: "land-axis"
    });
    g.ticks.forEach(function (t) {
      inner += tag("line", {
        x1: t.x, x2: t.x, y1: L.axisY, y2: r4(L.axisY + 6), class: "tick"
      });
      inner += text(t.x, r4(L.axisY + 20), t.label,
                    { class: "lab lab-num", "text-anchor": "middle" });
    });
    inner += text(g.x1, r4(L.axisY + 20), "백만원/㎡",
                  { class: "lab", "text-anchor": "start" });

    // 손익분기 왼쪽이 "사업이 서는 구간"이다 — 그 자리에만 옅은 바탕을 깐다.
    var bx = g.marks[1].x;
    inner += tag("rect", {
      x: g.x0, y: r4(L.axisY - 15), width: r4(bx - g.x0), height: 15,
      class: "land-ok"
    });
    inner += text(r4(g.x0 + 8), r4(L.axisY - 4), "이 구간이면 사업이 선다",
                  { class: "lab lab-ok" });

    g.marks.forEach(function (p) {
      var lane = LAND_LANES[p.key];
      var y = r4(L.axisY + lane.dy);
      inner += tag("line", {
        x1: p.x, x2: p.x, y1: r4(L.axisY), y2: y, class: "land-stem is-" + p.key
      });
      inner += tag("circle", { cx: p.x, cy: y, r: 3.2, class: "land-dot is-" + p.key });
      var tx = p.clipped
        ? r4(p.x - 8)
        : (lane.anchor === "end" ? r4(p.x - 7) : r4(p.x + 7));
      inner += text(tx, r4(y + 4),
                    p.label + " " + F.fx(p.won / 1e6, 2) + (p.clipped ? " ▸" : ""),
                    { class: "lab lab-land is-" + p.key,
                      "text-anchor": lane.anchor });
      if (p.clipped) {
        // 파단선 — 값이 축 밖으로 나갔다는 도면의 표기다. 수는 라벨이 그대로 싣는다.
        inner += tag("path", {
          d: "M" + r4(p.x - 5) + " " + r4(y + 12) + " l4 4 l4 -8 l4 8 l4 -4",
          class: "break-mark"
        });
      }
    });
    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h, role: "img",
      "aria-label": "손익분기 토지단가와 시드 공시지가 — " + landLines(m).join(" "),
      class: "plate-svg ch-fig land-plate" + (L.verbose ? "" : " is-compact"),
      "data-fig-w": L.w, "data-fig-min": L.minLabel, "data-fig-kmax": L.kMax,
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  // ── 도면 활자 맞추기 ────────────────────────────────────────────────────
  /**
   * viewBox 안의 px 는 화면 px 이 아니다. 그려 놓고 실폭을 재어 계수를 되돌린다.
   *
   * 판마다 따로 재던 것을 한 함수로 모았다 — 도면이 늘 때마다 mount 가 제 몫의
   * 측정 코드를 복사하면, 어느 판 하나가 조용히 빠진다. 판형의 선언값은 SVG 가
   * `data-fig-*` 로 스스로 들고 있다.
   */
  function fitFigures(rootEl) {
    if (!rootEl || !rootEl.querySelectorAll) return 0;
    var svgs = rootEl.querySelectorAll("svg[data-fig-w]");
    for (var i = 0; i < svgs.length; i += 1) {
      var el = svgs[i];
      el.style.setProperty("--fig-k", String(hero.labelScale(
        el.getBoundingClientRect().width,
        Number(el.getAttribute("data-fig-w")),
        Number(el.getAttribute("data-fig-min")),
        Number(el.getAttribute("data-fig-kmax")))));
    }
    return svgs.length;
  }

  /**
   * 판정 한 줄. 문장은 하나지만 그 안의 수와 방향은 전부 계산에서 온다 —
   * 시드가 손익분기 밑으로 내려가면 이 문장도 반대로 뒤집힌다.
   */
  function verdictHtml(m) {
    if (!m.stands) {
      return "<b>프라임 필지에서는 이 사업이 서지 않는다.</b> 손익분기 토지단가는 ㎡당 " +
        esc(F.group(Math.round(m.breakeven).toFixed(0))) + "원인데, 시드 " + m.n +
        "필지 가운데 가장 싼 필지의 개별공시지가가 " +
        esc(F.group(m.seedMin.toFixed(0))) + "원으로 그것을 " +
        esc(F.fx(m.gapToMin * 100)) + "% 넘는다. 중위 필지라면 " +
        esc(F.fx(m.gapToMedian, 1)) + "배다.";
    }
    return "<b>가장 싼 필지라면 이 사업이 선다.</b> 손익분기 토지단가 ㎡당 " +
      esc(F.group(Math.round(m.breakeven).toFixed(0))) + "원이 시드 최저 " +
      esc(F.group(m.seedMin.toFixed(0))) + "원 위에 있다 — 다만 중위 필지는 " +
      esc(F.fx(m.gapToMedian, 1)) + "배라 여전히 대부분의 필지에서는 서지 않는다.";
  }

  function legendHtml(m) {
    return '<ul class="strata-legend">' + m.bands.map(function (b) {
      return '<li class="' + esc(b.className) + '"><span class="swatch"></span>' +
        "<b>" + esc(b.label) + "</b>" +
        '<span class="of">' + esc(b.of) + "</span></li>";
    }).join("") + "</ul>";
  }

  function ul(lines) {
    return lines.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  function mount(doc, data) {
    doc = doc || document;
    var pf = (data && data.pf) || null;
    var depEl = doc.getElementById("ch3-deposit");
    if (!depEl) return null;
    if (!pf) {
      depEl.innerHTML = '<p class="fail">Ⅲ장을 그리지 못했다 — ' +
        "out/pf_case.json 이 실리지 않았다.</p>";
      return null;
    }
    var legEl = doc.getElementById("ch3-legend");
    var depReadEl = doc.getElementById("ch3-deposit-reading");
    var stressEl = doc.getElementById("ch3-stress");
    var stressReadEl = doc.getElementById("ch3-stress-reading");
    var ladEl = doc.getElementById("ch3-ladder");
    var ladReadEl = doc.getElementById("ch3-ladder-reading");
    var landEl = doc.getElementById("ch3-land");
    var landReadEl = doc.getElementById("ch3-land-reading");
    var verdictEl = doc.getElementById("ch3-land-verdict");
    var specEl = doc.getElementById("ch3-spec");

    var wide = typeof matchMedia === "function" ? matchMedia(hero.WIDE_QUERY) : null;
    function isCompact() { return !(wide && wide.matches); }

    function paint() {
      var opts = { compact: isCompact() };
      var dm = depositModel(pf);
      depEl.innerHTML = renderDeposit(pf, opts);
      if (legEl) legEl.innerHTML = legendHtml(dm);
      if (depReadEl) depReadEl.innerHTML = ul(depositLines(dm));
      var sm = stressModel(pf);
      if (stressEl) stressEl.innerHTML = stressTableHtml(sm);
      if (stressReadEl) stressReadEl.innerHTML = ul(stressLines(sm));
      if (ladEl) ladEl.innerHTML = renderLadder(pf, opts);
      if (ladReadEl) ladReadEl.innerHTML = ul(ladderLines(ladderModel(pf)));
      if (landEl) landEl.innerHTML = renderLand(pf, opts);
      var lm = landModel(pf);
      if (landReadEl) landReadEl.innerHTML = ul(landLines(lm));
      if (verdictEl) verdictEl.innerHTML = verdictHtml(lm);
      if (specEl) {
        specEl.innerHTML =
          "<div><dt>사업</dt><dd>" + esc(dm.caseName) + "</dd></div>" +
          "<div><dt>기간</dt><dd>공사 " + dm.buildMonths + "개월 · 임대 " +
          dm.leaseMonths + "개월</dd></div>" +
          "<div><dt>총사업비</dt><dd>" + eok(dm.totalCost) + "억원 · LTC " +
          F.fx(dm.ltc * 100) + "%</dd></div>" +
          "<div><dt>지분 IRR</dt><dd>" + F.pct(pf.model.equity_irr) +
          " · 세전</dd></div>";
      }
      fitFigures(doc.getElementById("ch3") || doc.body || doc);
    }

    if (wide && wide.addEventListener) {
      wide.addEventListener("change", paint);
    }
    if (typeof window !== "undefined" && window.addEventListener) {
      var pending = false;
      window.addEventListener("resize", function () {
        if (pending) return;
        pending = true;
        var raf = window.requestAnimationFrame ||
          function (fn) { return setTimeout(fn, 16); };
        raf(function () {
          pending = false;
          fitFigures(doc.getElementById("ch3") || doc.body || doc);
        });
      });
    }
    paint();
    return { paint: paint };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var host = document.getElementById("ch3-deposit");
    if (!host) return;
    try {
      mount(document, { pf: window.__DATA_PF });
    } catch (err) {
      host.innerHTML = '<p class="fail">Ⅲ장을 그리지 못했다 — ' +
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
    DEPOSIT_BANDS: DEPOSIT_BANDS,
    DEPOSIT: DEPOSIT, LADDER: LADDER, LAND: LAND,
    plain: plain,
    depositModel: depositModel,
    depositGeom: depositGeom,
    depositLines: depositLines,
    depositAria: depositAria,
    renderDeposit: renderDeposit,
    legendHtml: legendHtml,
    stressModel: stressModel,
    llcrPair: llcrPair,
    stressTableHtml: stressTableHtml,
    stressLines: stressLines,
    ladderModel: ladderModel,
    ladderGeom: ladderGeom,
    ladderLines: ladderLines,
    renderLadder: renderLadder,
    landModel: landModel,
    landGeom: landGeom,
    landLines: landLines,
    renderLand: renderLand,
    verdictHtml: verdictHtml,
    figScale: figScale,
    fitFigures: fitFigures,
    mount: mount
  };
});
