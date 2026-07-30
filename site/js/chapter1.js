/**
 * Ⅰ장 공간의 층위 — 원장 55동과 거래의 사다리.
 *
 * 이 장의 조형은 하나의 문장을 세 번 다르게 말한다: **아직 대장이 열리지 않았다.**
 *
 *   ① 카드 55장이 전부 같은 스탬프를 달고 있다. 반복 자체가 논증이다 — 한 장에
 *      "대장 대기"라고 적는 것과 쉰다섯 장이 같은 도장을 찍고 늘어선 것은 다른
 *      크기의 사실이다. 카드는 도면 시트의 **표제란 한 칸**을 그대로 축소한
 *      모양이라 서장과 같은 종이 위에 있다.
 *   ② 거래 산점은 21년치 권역 중위값 위에 **건물에 붙일 수 있는 점 55개**를
 *      얹는다. 그 점들이 오른쪽 끝 3년, 네 동에만 몰려 있는 그림이 곧 매칭의
 *      한계다. 색이 아니라 **형태**로 가른다 — 계열은 실선, 귀속된 거래는 속
 *      빈 원. 서장의 "실선은 계산, 해칭은 가정"과 같은 규칙의 연장이다.
 *   ③ 배타 사다리는 서장의 **자본 지층 기둥과 같은 프리미티브**로 그린다. 같은
 *      기둥이 두 번째 뜻을 얻는 것이다: 저기서는 가치 위에 쌓인 부채였고,
 *      여기서는 매칭된 4,523행 위에 쌓인 확신의 등급이다. 맨 위 83.8%는 채운
 *      색이 아니라 **역방향 해칭**으로 그린다 — 귀속할 수 없는 자리라서.
 *
 * ── 행 변종 세 가지를 지금 다 그린다 ──
 * `underwriting.buildings[]` 는 pending·승격·실패 세 모양이고, 지금 실데이터는
 * 55동 전부 pending 이다. 승격 UI 를 대장이 열린 뒤에 만들면 그날 처음으로 화면이
 * 깨진다. 그래서 세 갈래를 다 그려 두고 합성 데이터로 검사한다
 * (`tests/test_chapters.py`). 변종 판정은 **`underwriting` 키의 유무**로 한다 —
 * 실패 행도 `pending_ledger` 가 false 라 그 플래그만 보면 승격으로 읽힌다.
 *
 * ── 도면 활자 높이는 하나다 ──
 * 이 장의 인-피겨 라벨은 크기가 한 종류다(넓은 판 11px · 좁은 판 12px). 제도
 * 규범(ISO 3098)이 한 도면에 한 활자 높이를 쓰는 것과 같은 이유이고, 실무적으로는
 * `--fig-k` 의 하한 계산이 **정확해진다** — 최소 선언값이 유일하기 때문이다.
 * 위계는 크기가 아니라 색과 자간이 맡는다.
 *
 * 의존은 charts.js · hero.js(판형 부속·서식) 두 개다. 로드 순서가 계약이다.
 */

;(function (root, factory) {
  "use strict";
  var isNode = typeof module !== "undefined" && module.exports;
  var scope = typeof window !== "undefined" ? window : (root || {});
  var charts = isNode ? require("./charts.js") : scope.CheungwiCharts;
  var hero = isNode ? require("./hero.js") : scope.CheungwiHero;
  var api = factory(charts, hero);
  if (isNode) module.exports = api;
  if (typeof window !== "undefined") window.CheungwiChapter1 = api;
  else if (root) root.CheungwiChapter1 = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, hero) {
  "use strict";

  var tag = charts.tag, text = charts.text, esc = charts.esc, r4 = charts.r4;
  var F = hero.fmt;

  var STAMP = { pending: "대장 개통 대기", failed: "계산 정지" };

  /** 막힌 함수 이름을 사람의 말로. 없는 이름이 오면 원문을 그대로 보인다. */
  var BLOCKED_LABEL = {
    building_adjust: "건물 특성 보정",
    noi: "NOI",
    value: "추정가치",
    max_loan: "대출가능액",
    hold_model: "보유 모델",
    refi_test: "차환 판정",
    breakeven_vacancy: "손익분기 공실률"
  };

  var KIND_LABEL = {
    RuntimeError: "물리 게이트 — 단위를 의심하라",
    ValueError: "입력 오류",
    NotImplementedError: "계산 불가"
  };

  var REGION_SERIES = [
    { name: "도심", className: "reg-cbd" },
    { name: "강남", className: "reg-gbd" },
    { name: "여의도마포", className: "reg-ybd" }
  ];

  var PYEONG_M2 = 400 / 121;   // 1평 — trades_analysis.units 와 같은 상수

  // ── 서식 ────────────────────────────────────────────────────────────────
  /** 원 → 억원. 원 단위로 적으면 자릿수가 카드를 넘어가고 아무도 읽지 못한다. */
  function eok(won, digits) {
    return F.group(Number(won / 1e8).toFixed(digits === undefined ? 0 : digits));
  }

  /** 원/평 → 만원/평. 산점의 눈금 단위다. */
  function manwon(won) {
    return F.group(Math.round(won / 1e4).toFixed(0));
  }

  function yearOf(ymd) {
    return Number(String(ymd).slice(0, 4));
  }

  /** "2024-04-30" → 2024.33. 같은 해의 점들이 한 세로줄에 겹치지 않게 편다. */
  function yearFrac(ymd) {
    var y = yearOf(ymd);
    var m = Number(String(ymd).slice(5, 7)) || 1;
    return y + (m - 0.5) / 12;
  }

  // ── 행 변종 ─────────────────────────────────────────────────────────────
  /**
   * pending · underwritten · failed 중 하나.
   *
   * **`pending_ledger` 만 보고 가르면 안 된다** — 계산 중 예외로 멈춘 행도 그
   * 플래그가 false 라 승격으로 읽히고, `row.underwriting.noi` 를 짚는 순간 터진다.
   */
  function variantOf(row) {
    if (!row || typeof row !== "object") {
      throw new TypeError("원장의 행이 아니다: " + String(row));
    }
    if (row.underwriting) return "underwritten";
    if (row.pending_ledger === true) return "pending";
    return "failed";
  }

  /** 카드 한 장이 아는 것 전부. 그리는 일은 `card` 가 한다. */
  function cardModel(row, index) {
    var variant = variantOf(row);
    var land = row.land || {};
    var m = {
      index: index === undefined || index === null ? null : index + 1,
      id: row.id,
      name: row.name,
      region: row.region,
      umd: row.umd,
      jibun: row.jibun,
      address: row.address_road,
      landPriceWonM2: land.land_price_won_m2,
      landPriceYear: land.land_price_year,
      zone: (land.zones && land.zones[0]) || null,
      flags: row.ledger_flags || [],
      variant: variant,
      stamp: STAMP[variant] || null,
      blocked: null,
      pendingReason: null,
      rows: [],
      ltv: null,
      binding: null,
      error: null
    };

    if (variant === "pending") {
      m.pendingReason = row.pending_reason || "";
      m.blocked = (row.blocked || []).map(function (k) {
        return BLOCKED_LABEL[k] || k;
      });
      return m;
    }
    if (variant === "failed") {
      var err = row.underwriting_error || {};
      m.error = {
        kind: err.kind || "알 수 없음",
        kindLabel: KIND_LABEL[err.kind] || "",
        reason: err.reason || "사유가 기록되지 않았다"
      };
      return m;
    }

    // 승격 — 대장이 열린 뒤의 모양. 지금은 합성 데이터로만 도달한다.
    var uw = row.underwriting;
    var led = row.ledger || {};
    var grnd = led.grndFlrCnt || 0;
    var ugrnd = led.ugrndFlrCnt || 0;
    m.ltv = uw.loan.loan_won / uw.value_won;
    m.binding = uw.loan.binding;
    m.rows = [
      { k: "연면적", v: F.group(Number(uw.gfa_m2).toFixed(0)), u: "㎡" },
      { k: "층수", v: "지상 " + grnd + " · 지하 " + ugrnd, u: "층" },
      { k: "NOI", v: eok(uw.noi.noi_won_y), u: "억원/년" },
      { k: "추정가치", v: eok(uw.value_won), u: "억원" }
    ];
    m.approvedOn = led.useAprDay || null;
    return m;
  }

  function card(m) {
    var head = '<header class="card-head">' +
      (m.index === null ? "" : '<span class="card-no">' +
        (m.index < 10 ? "0" : "") + m.index + "</span>") +
      "<h4>" + esc(m.name) + "</h4>" +
      '<p class="card-where">' + esc(m.region) + " · " + esc(m.umd) +
      (m.jibun ? " " + esc(m.jibun) : "") + "</p></header>";

    var sheet = '<dl class="card-sheet">' +
      '<div><dt>공시지가</dt><dd><b class="num">' +
      (m.landPriceWonM2 ? F.group(Number(m.landPriceWonM2 / 1e4).toFixed(0)) : "―") +
      '</b><span class="unit">만원/㎡ · ' + esc(m.landPriceYear || "―") +
      "</span></dd></div>" +
      "<div><dt>용도지역</dt><dd>" + esc(m.zone || "―") + "</dd></div></dl>";

    var body = "", stamp = "";
    if (m.variant === "pending") {
      // 일곱 이름을 55장에 되풀이하면 도장이 묻힌다 — 카드에는 수만 두고 이름은
      // 손끝(title)과 아래 판독 글줄이 받는다. 사라지는 정보는 없다.
      body = '<p class="card-blocked" title="' + esc(m.blocked.join(" · ")) +
        '">막힌 계산 <b>' + m.blocked.length + "</b>건 — NOI 이하 전부</p>";
      stamp = '<span class="stamp-mark" title="' + esc(m.pendingReason) + '">' +
        esc(m.stamp) + "</span>";
    } else if (m.variant === "failed") {
      body = '<p class="card-error"><b>' + esc(m.error.kind) + "</b>" +
        (m.error.kindLabel ? " · " + esc(m.error.kindLabel) : "") + "<br>" +
        esc(m.error.reason) + "</p>";
      stamp = '<span class="stamp-mark is-fail">' + esc(m.stamp) + "</span>";
    } else {
      var rows = m.rows.map(function (r) {
        return '<div class="card-row"><dt>' + esc(r.k) + '</dt><dd><b class="num">' +
          esc(r.v) + '</b><span class="unit">' + esc(r.u) + "</span></dd></div>";
      }).join("");
      // 카드 한 장에 실린 작은 단면 — 가치를 가로로 눕히고 대출만큼 물을 채운다.
      var pct = Math.max(0, Math.min(100, m.ltv * 100));
      body = '<dl class="card-rows">' + rows + "</dl>" +
        '<div class="card-water" style="--ltv:' + r4(pct) + '%"' +
        ' role="img" aria-label="가치 대비 대출 ' + F.fx(pct) + '퍼센트">' +
        '<span class="card-water-fill"></span></div>' +
        '<p class="card-ltv">LTV <b class="num">' + F.fx(pct) +
        '%</b><span class="unit">묶는 제약 ' + esc(m.binding) + "</span></p>";
    }

    var flags = m.flags.length
      ? '<p class="card-flags" title="' + esc(m.flags.join(" / ")) + '">주의 ' +
        m.flags.length + "건</p>"
      : "<span></span>";
    return '<article class="b-card is-' + m.variant + '">' +
      head + sheet + body +
      '<div class="card-foot">' + flags + stamp + "</div></article>";
  }

  // ── 원장 전체 ───────────────────────────────────────────────────────────
  function ledgerModel(underwriting) {
    var rows = (underwriting && underwriting.buildings) || [];
    if (!rows.length) {
      throw new TypeError("원장에 건물이 없다 — out/underwriting.json 이 실리지 않았다");
    }
    var counts = { pending: 0, underwritten: 0, failed: 0 };
    var byRegion = [], seen = {};
    var cards = rows.map(function (row, i) {
      var m = cardModel(row, i);
      counts[m.variant] += 1;
      if (!seen[m.region]) {
        seen[m.region] = { name: m.region, n: 0, pending: 0, underwritten: 0, failed: 0 };
        byRegion.push(seen[m.region]);
      }
      seen[m.region].n += 1;
      seen[m.region][m.variant] += 1;
      return m;
    });
    var summary = (underwriting && underwriting.summary) || {};
    // 카드에는 막힌 계산의 **수**만 적는다(일곱 이름을 55장에 되풀이하면 도장이
    // 묻힌다). 그러니 이름은 판독 글줄이 본문 크기로 한 번 받아야 한다 — 손끝에
    // 닿아야만 보이는 정보로 남겨 두지 않는다.
    var blocked = [];
    cards.forEach(function (c) {
      if (c.blocked && c.blocked.length > blocked.length) blocked = c.blocked;
    });
    return {
      n: rows.length,
      pending: counts.pending,
      underwritten: counts.underwritten,
      failed: counts.failed,
      blocked: blocked,
      byRegion: byRegion,
      cards: cards,
      ledgerStatus: summary.ledger_status || "",
      // 원장이 열리지 않은 이유는 숫자가 아니라 문장으로만 남는다 — 지우지 않는다.
      pendingReason: (rows[0] && rows[0].pending_reason) || ""
    };
  }

  function ledgerLines(m) {
    var out = [
      "원장 " + m.n + "동 — 대장 개통 대기 " + m.pending + "동 · 언더라이팅 완료 " +
        m.underwritten + "동 · 계산 정지 " + m.failed + "동.",
      m.byRegion.map(function (r) {
        return r.name + " " + r.n + "동";
      }).join(" · ") + ". 권역 구분은 R-ONE 기준이고 시드 매핑은 근사다."
    ];
    if (m.pending) {
      out.push("연면적·사용승인일이 없어 " + m.blocked.length + "개 계산이 막혀 " +
        "있다: " + m.blocked.join(" · ") + ". 빈 자리를 권역 평균으로 메우지 " +
        "않았다 — 추정과 부재를 같은 색으로 칠하면 대장이 없다는 사실이 " +
        "산출물에서 사라진다.");
    }
    if (m.ledgerStatus) out.push("대장 상태: " + m.ledgerStatus);
    return out;
  }

  // ── 거래 ────────────────────────────────────────────────────────────────
  var AMBIGUOUS_CAVEAT =
    "모호 3,789건은 마스킹된 지번이 여러 시드에 동시에 걸려 **건물 귀속 불가**다 — " +
    "후보 중 첫 동을 고르면 수천 행이 엉뚱한 한 동에 몰리므로 건물 단위 집계에서 " +
    "통째로 뺐다(권역·연도 집계에는 시군구만 쓰므로 그대로 남는다).";

  function tradesModel(trades) {
    if (!trades || !trades.matching || !trades.by_region) {
      throw new TypeError("거래 분석이 없다 — out/trades_analysis.json 이 실리지 않았다");
    }
    var ladderSrc = trades.matching.ladder_exclusive;
    if (!ladderSrc) {
      throw new TypeError(
        "배타 사다리(ladder_exclusive)가 없다 — exact ⊆ resolved 라 세 수를 " +
        "그대로 더하면 matched 를 넘는다. 겹치는 수로 사다리를 그리지 않는다");
    }
    var regions = REGION_SERIES.map(function (spec) {
      var src = trades.by_region[spec.name] || { by_year: [] };
      return {
        name: spec.name,
        className: spec.className,
        n: src.n || 0,
        points: (src.by_year || []).map(function (y) {
          return {
            label: String(y.year),
            x: y.year,
            y: y.median_won_per_pyeong / 1e4,
            n: y.n
          };
        })
      };
    });
    var dots = (trades.exact_cases || []).map(function (c) {
      return {
        key: c.building_id,
        ymd: c.deal_ymd,
        x: yearFrac(c.deal_ymd),
        y: c.per_pyeong_won / 1e4,
        amountWon: c.amount_won,
        areaM2: c.building_ar_m2
      };
    });
    var buildings = [];
    dots.forEach(function (d) {
      if (buildings.indexOf(d.key) < 0) buildings.push(d.key);
    });
    var years = dots.map(function (d) { return yearOf(d.ymd); });
    var xs = [];
    regions.forEach(function (s) {
      s.points.forEach(function (p) { xs.push(p.x); });
    });

    return {
      unit: "만원/평",
      pyeongM2: PYEONG_M2,
      regions: regions,
      dots: dots,
      span: [Math.min.apply(null, xs), Math.max.apply(null, xs)],
      exact: {
        n: trades.matching.exact.n,
        live: trades.matching.exact.n_live,
        canceled: trades.matching.exact.n_canceled_excluded,
        buildings: buildings,
        years: years.length
          ? [Math.min.apply(null, years), Math.max.apply(null, years)]
          : null
      },
      ladder: {
        total: ladderSrc.sum,
        matched: ladderSrc.n_matched,
        exact: ladderSrc.exact,
        resolvedOnly: ladderSrc.resolved_only,
        ambiguous: ladderSrc.ambiguous,
        bands: [
          { key: "exact", label: "필지 확정", value: ladderSrc.exact,
            className: "rung-exact" },
          { key: "resolved", label: "동 확정(후보 유일)", value: ladderSrc.resolved_only,
            className: "rung-resolved" },
          { key: "ambiguous", label: "귀속 불가", value: ladderSrc.ambiguous,
            className: "rung-ambiguous" }
        ]
      },
      rowsUsed: (trades.filters || {}).rows_used,
      canceled: (trades.filters || {}).canceled_excluded,
      caveat: AMBIGUOUS_CAVEAT
    };
  }

  // ── 산점 판형 ───────────────────────────────────────────────────────────
  var PLOT = {
    wide: { w: 880, h: 384, m: { t: 40, r: 122, b: 38, l: 68 }, dot: 3, ticks: 5 },
    compact: { w: 430, h: 340, m: { t: 34, r: 16, b: 34, l: 54 }, dot: 2.6, ticks: 4 }
  };

  function plotOf(opts) {
    return (opts && opts.compact) ? PLOT.compact : PLOT.wide;
  }

  /**
   * 좌표만 낸다. 그림은 이 값의 결과일 뿐이라, 점이 판형 밖으로 나가는지는
   * 눈이 아니라 여기서 잡는다.
   */
  function tradesGeom(m, opts) {
    var P = plotOf(opts);
    var ys = [];
    m.regions.forEach(function (s) {
      s.points.forEach(function (p) { ys.push(p.y); });
    });
    m.dots.forEach(function (d) { ys.push(d.y); });
    var ye = charts.extent(ys);
    var pad = (ye[1] - ye[0]) * 0.08;
    var y0 = Math.max(0, ye[0] - pad), y1 = ye[1] + pad;
    var x0 = m.span[0] - 0.5, x1 = m.span[1] + 0.5;
    var sx = charts.scaleLinear(x0, x1, P.m.l, P.w - P.m.r);
    var sy = charts.scaleLinear(y0, y1, P.h - P.m.b, P.m.t);

    var exactYears = m.exact.years;
    return {
      width: P.w, height: P.h, margin: P.m, dotR: P.dot,
      xDomain: [x0, x1], yDomain: [y0, y1],
      yTicks: charts.niceTicks(y0, y1, P.ticks).map(function (v) {
        return { v: v, y: r4(sy(v)) };
      }),
      xTicks: [m.span[0], Math.round((m.span[0] + m.span[1]) / 2), m.span[1]]
        .map(function (v) { return { v: v, x: r4(sx(v)) }; }),
      series: m.regions.map(function (s) {
        return {
          name: s.name, className: s.className,
          points: s.points.map(function (p) {
            return { x: r4(sx(p.x)), y: r4(sy(p.y)), label: p.label };
          })
        };
      }),
      dots: m.dots.map(function (d) {
        return { x: r4(sx(d.x)), y: r4(sy(d.y)), key: d.key };
      }),
      exactBand: exactYears
        ? { x0: r4(sx(exactYears[0] - 0.5)), x1: r4(sx(exactYears[1] + 0.5)) }
        : null
    };
  }

  function tradesAria(m) {
    return "권역별 연도 중위 평당가 " + m.span[0] + "~" + m.span[1] +
      "년과 건물에 귀속된 거래 " + m.dots.length + "점. " +
      m.regions.map(function (s) {
        var last = s.points[s.points.length - 1];
        return s.name + " " + m.span[1] + "년 " + manwon(last.y * 1e4) + "만원/평";
      }).join(", ") + ". 귀속된 점은 " +
      (m.exact.years ? m.exact.years[0] + "~" + m.exact.years[1] + "년" : "없음") +
      ", " + m.exact.buildings.length + "동에만 있다.";
  }

  function tradesPlot(m, opts) {
    var g = tradesGeom(m, opts);
    var compact = !!(opts && opts.compact);
    var inner = "";

    // 귀속 가능 구간 — 점이 있는 자리에만 옅은 바탕을 깔아 "여기뿐"을 보인다.
    if (g.exactBand) {
      inner += tag("rect", {
        x: g.exactBand.x0, y: g.margin.t,
        width: r4(g.exactBand.x1 - g.exactBand.x0),
        height: r4(g.height - g.margin.b - g.margin.t),
        class: "exact-band"
      });
    }
    g.yTicks.forEach(function (t) {
      inner += tag("line", {
        x1: g.margin.l, x2: g.width - g.margin.r, y1: t.y, y2: t.y, class: "grid"
      });
      inner += text(g.margin.l - 8, t.y + 4, manwon(t.v * 1e4),
                    { class: "lab lab-num", "text-anchor": "end" });
    });
    g.xTicks.forEach(function (t, i) {
      inner += text(t.x, g.height - 12, String(t.v), {
        class: "lab lab-num",
        "text-anchor": i === 0 ? "start" : (i === g.xTicks.length - 1 ? "end" : "middle")
      });
    });

    var ends = [];
    g.series.forEach(function (s) {
      var d = "";
      s.points.forEach(function (p, i) {
        d += (i ? " L" : "M") + p.x + " " + p.y;
      });
      inner += tag("path", { d: d, class: "series " + s.className, "data-key": s.name });
      var last = s.points[s.points.length - 1];
      ends.push({ x: last.x, y: last.y, name: s.name, cls: s.className });
    });
    g.dots.forEach(function (d) {
      inner += tag("circle", {
        cx: d.x, cy: d.y, r: g.dotR, class: "dot-exact", "data-key": d.key
      });
    });

    if (!compact) {
      // 직접 라벨. 끝값이 가까우면 글자만 아래로 비킨다(값은 그대로).
      ends.sort(function (a, b) { return a.y - b.y; });
      for (var i = 1; i < ends.length; i += 1) {
        if (ends[i].y - ends[i - 1].y < 16) ends[i].y = r4(ends[i - 1].y + 16);
      }
      ends.forEach(function (e) {
        inner += text(e.x + 8, e.y + 4, e.name, { class: "lab lab-series " + e.cls });
      });
    }

    inner += text(g.margin.l - 8, 20, "중위 평당가 · 만원/평",
                  { class: "lab", "text-anchor": "start" });
    if (g.exactBand) {
      inner += text(r4(g.exactBand.x0 + 6), r4(g.margin.t - 10),
                    compact
                      ? "귀속 " + m.dots.length + "점"
                      : "건물에 귀속된 " + m.dots.length + "점은 이 구간 " +
                        m.exact.buildings.length + "동뿐이다",
                    { class: "lab lab-band", "text-anchor": compact ? "middle" : "end" });
    }

    return tag("svg", {
      viewBox: "0 0 " + g.width + " " + g.height,
      role: "img", "aria-label": tradesAria(m),
      class: "ch-fig plot" + (compact ? " is-compact" : ""),
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  function tradesLines(m) {
    return [
      "연도별 중위 평당가는 " + m.span[0] + "~" + m.span[1] + "년 업무용 매매 " +
        F.group(String(m.rowsUsed)) + "행에서 냈다(해제 " + m.canceled +
        "건 제외). 대형 통매각은 건수가 적어 중위값이 소형 구분소유 거래에 끌린다.",
      "거래면적은 집합건물의 계약·분양면적이라 건물 연면적이 아니다 — 평당가를 " +
        "연면적 기준 단가와 직접 비교하면 안 된다.",
      "속 빈 원 " + m.dots.length + "점만이 건물에 붙는다(필지 확정 " + m.exact.n +
        "행 중 해제 " + m.exact.canceled + "건 제외). " +
        (m.exact.years
          ? m.exact.years[0] + "~" + m.exact.years[1] + "년 " +
            m.exact.buildings.length + "동에 몰려 있다."
          : "")
    ];
  }

  // ── 배타 사다리 ─────────────────────────────────────────────────────────
  // 사다리는 좁은 칸에 선다(넓은 화면에서도 300px 남짓). 판형을 그 칸에 맞춰야
  // 배율이 1 근처가 되고 글자가 제 크기로 찍힌다 — 880 판을 300px 에 넣으면
  // 계수로도 못 살린다.
  var LADDER = {
    wide: { w: 300, h: 452, topY: 34, botY: 392,
            col: { x: 16, width: 54 }, labelX: 84, gap: 32 },
    compact: { w: 430, h: 448, topY: 30, botY: 372,
               col: { x: 20, width: 62 }, labelX: 98, gap: 36 }
  };

  function ladderOf(opts) {
    return (opts && opts.compact) ? LADDER.compact : LADDER.wide;
  }

  function ladderAria(m) {
    var L = m.ladder;
    return "매칭된 거래 " + F.group(String(L.total)) + "행의 배타 사다리 — 필지 확정 " +
      L.exact + "행, 동 확정 " + F.group(String(L.resolvedOnly)) + "행, 귀속 불가 " +
      F.group(String(L.ambiguous)) + "행. 셋은 겹치지 않고 합이 매칭 수와 같다.";
  }

  function ladderPlate(m, opts) {
    var L = ladderOf(opts);
    var lad = m.ladder;
    var box = {
      x: L.col.x, y: L.topY, width: L.col.width,
      height: L.botY - L.topY, total: lad.total
    };
    var laid = charts.strataLayout(lad.bands, box);
    var inner = tag("defs", {}, tag("pattern", {
      id: "cw-hatch-void", width: 5, height: 5,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(-45)"
    }, tag("line", { x1: 0, y1: 0, x2: 0, y2: 5, class: "hatch-void" })));

    inner += charts.strataColumn(lad.bands, box);
    // 귀속 불가는 채운 색이 아니라 **역방향 해칭**이다 — 서장에서 해칭이 "가정"을
    // 뜻했듯, 여기서는 "이 자리는 어느 건물에도 못 붙는다"를 형태가 말한다.
    var amb = laid[2];
    if (amb) {
      inner += tag("rect", {
        x: amb.x, y: amb.y, width: amb.width, height: amb.height,
        fill: "url(#cw-hatch-void)", class: "void-hatch"
      });
    }
    inner += tag("rect", {
      x: box.x, y: box.y, width: box.width, height: box.height, class: "column-frame"
    });

    // 지시선. 57 은 전체의 1.3% 라 3.8px 이다 — 높이로는 못 읽으니 선이 받는다.
    var right = box.x + box.width;
    // **위에서 아래로** 한 번만 훑으며 최소 간격을 지킨다. 아무 순서로 훑으면서
    // "가까우면 아래로"를 반복하면 세 라벨이 서로를 밀어 판형 밖으로 나간다.
    // 그렇게 해도 밑변을 넘으면 묶음째 위로 올린다 — 잘린 글자보다 나은 것이 없다.
    var order = laid.slice().sort(function (a, b) {
      return (a.y + a.height / 2) - (b.y + b.height / 2);
    });
    var lys = [], cursor = -Infinity;
    order.forEach(function (b) {
      cursor = Math.max(r4(b.y + b.height / 2), cursor + L.gap);
      lys.push(cursor);
    });
    var over = lys[lys.length - 1] - (L.botY - 6);
    if (over > 0) {
      var lift = Math.min(over, lys[0] - (L.topY + 8));
      if (lift > 0) lys = lys.map(function (v) { return v - lift; });
    }
    order.forEach(function (b, i) {
      var cy = r4(b.y + b.height / 2);
      var ly = r4(lys[i]);
      inner += tag("line", {
        x1: r4(right + 2), x2: r4(L.labelX - 6), y1: cy, y2: ly,
        class: "leader leader-" + b.key
      });
      inner += text(L.labelX, ly - 3, b.label, { class: "lab lab-rung" });
      inner += text(L.labelX, ly + 14,
                    F.group(String(b.value)) + "행 · " + F.fx(b.share * 100) + "%",
                    { class: "lab lab-num" });
    });

    inner += text(L.col.x, 20, "매칭 " + F.group(String(lad.total)) + "행",
                  { class: "lab" });
    inner += text(L.col.x, r4(L.botY + 40),
                  "모호 " + F.group(String(lad.ambiguous)) + "건은 건물 귀속 불가",
                  { class: "lab lab-void" });

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h,
      role: "img", "aria-label": ladderAria(m),
      class: "ch-fig ladder-svg" + ((opts && opts.compact) ? " is-compact" : ""),
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  function ladderLines(m) {
    var L = m.ladder;
    return [
      "매칭된 " + F.group(String(L.total)) + "행을 겹치지 않는 세 칸으로 나눈다 — " +
        "필지 확정 " + L.exact + " · 동 확정 " + F.group(String(L.resolvedOnly)) +
        " · 귀속 불가 " + F.group(String(L.ambiguous)) + ". exact 는 resolved 의 " +
        "부분집합이라 원래 수를 그대로 더하면 매칭 수를 넘는다.",
      "모호 " + F.group(String(L.ambiguous)) + "건은 건물에 귀속할 수 없다. " +
        "마스킹된 지번이 여러 시드에 동시에 걸려 동을 특정하지 못한 행이고, 후보 " +
        "중 첫 동을 고르면 수천 행이 엉뚱한 한 동에 몰리므로 건물 단위 집계에서 " +
        "통째로 뺐다.",
      "필지까지 확정된 " + L.exact + "행이 전체의 " +
        F.fx(L.exact / L.total * 100, 1) + "% 다 — 추정가치와 실거래의 오차 분포는 " +
        "대장 승격 뒤에야 이 " + L.exact + "행과 짝을 지어 낼 수 있다."
    ];
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  var ALL = "전체";

  function mount(doc, data) {
    doc = doc || document;
    data = data || {};
    var tabsEl = doc.getElementById("ch1-filter");
    var gridEl = doc.getElementById("ch1-cards");
    var readEl = doc.getElementById("ch1-ledger-reading");
    var plotEl = doc.getElementById("ch1-trades-plot");
    var plotRead = doc.getElementById("ch1-trades-reading");
    var ladderEl = doc.getElementById("ch1-ladder-plate");
    var ladderRead = doc.getElementById("ch1-ladder-reading");
    var countEl = doc.getElementById("ch1-count");
    if (!gridEl) return null;

    var ledger = ledgerModel(data.underwriting);
    var trades = data.trades ? tradesModel(data.trades) : null;
    var names = [ALL].concat(ledger.byRegion.map(function (r) { return r.name; }));
    var active = ALL;
    var wide = typeof matchMedia === "function"
      ? matchMedia(hero.WIDE_QUERY) : null;

    function isCompact() { return !(wide && wide.matches); }

    function countOf(name) {
      if (name === ALL) return ledger.n;
      var hit = ledger.byRegion.filter(function (r) { return r.name === name; })[0];
      return hit ? hit.n : 0;
    }

    function paintTabs() {
      if (!tabsEl) return;
      tabsEl.innerHTML = names.map(function (n) {
        var on = n === active;
        return '<button type="button" role="tab" id="ch1-tab-' + esc(n) + '"' +
          ' data-region="' + esc(n) + '" aria-selected="' + (on ? "true" : "false") +
          '" aria-controls="ch1-cards" tabindex="' + (on ? "0" : "-1") +
          '" class="r-tab' + (on ? " on" : "") + '">' + esc(n) +
          ' <span class="r-n">' + countOf(n) + "</span></button>";
      }).join("");
    }

    function paintCards() {
      var shown = ledger.cards.filter(function (c) {
        return active === ALL || c.region === active;
      });
      gridEl.innerHTML = shown.map(card).join("");
      gridEl.setAttribute("aria-labelledby", "ch1-tab-" + active);
      if (countEl) {
        countEl.textContent = active === ALL
          ? ledger.n + "동 전부"
          : active + " " + shown.length + "동";
      }
    }

    function fitFigures() {
      [[plotEl, "plot"], [ladderEl, "ladder"]].forEach(function (pair) {
        var host = pair[0];
        if (!host) return;
        var svg = host.querySelector("svg.ch-fig");
        if (!svg) return;
        var vb = pair[1] === "plot" ? plotOf({ compact: isCompact() }).w
                                    : ladderOf({ compact: isCompact() }).w;
        svg.style.setProperty("--fig-k", String(hero.labelScale(
          svg.getBoundingClientRect().width, vb,
          isCompact() ? 12 : 11, isCompact() ? 1.15 : 1.6)));
      });
    }

    function paintFigures() {
      if (!trades) return;
      var opts = { compact: isCompact() };
      if (plotEl) plotEl.innerHTML = tradesPlot(trades, opts);
      if (ladderEl) ladderEl.innerHTML = ladderPlate(trades, opts);
      if (plotRead) plotRead.innerHTML = tradesLines(trades).map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("");
      if (ladderRead) ladderRead.innerHTML = ladderLines(trades).map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("");
      fitFigures();
    }

    function select(name) {
      if (name === active || names.indexOf(name) < 0) return;
      active = name;
      paintTabs();
      paintCards();
      var btn = tabsEl && tabsEl.querySelector('[aria-selected="true"]');
      if (btn) btn.focus();
    }

    if (tabsEl) {
      tabsEl.addEventListener("click", function (ev) {
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
    }
    if (wide && wide.addEventListener) {
      wide.addEventListener("change", paintFigures);
    }
    if (typeof window !== "undefined" && window.addEventListener) {
      var pending = false;
      window.addEventListener("resize", function () {
        if (pending) return;
        pending = true;
        var raf = window.requestAnimationFrame ||
          function (fn) { return setTimeout(fn, 16); };
        raf(function () { pending = false; fitFigures(); });
      });
    }

    paintTabs();
    paintCards();
    if (readEl) {
      readEl.innerHTML = ledgerLines(ledger).map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("");
    }
    paintFigures();
    return { select: select, ledger: ledger, trades: trades };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var grid = document.getElementById("ch1-cards");
    if (!grid) return;
    try {
      mount(document, {
        underwriting: window.__DATA_UNDERWRITING,
        trades: window.__DATA_TRADES
      });
    } catch (err) {
      grid.innerHTML = '<p class="fail">Ⅰ장을 그리지 못했다 — ' +
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
    STAMP: STAMP,
    AMBIGUOUS_CAVEAT: AMBIGUOUS_CAVEAT,
    variantOf: variantOf,
    cardModel: cardModel,
    card: card,
    ledgerModel: ledgerModel,
    ledgerLines: ledgerLines,
    tradesModel: tradesModel,
    tradesGeom: tradesGeom,
    tradesPlot: tradesPlot,
    tradesLines: tradesLines,
    ladderPlate: ladderPlate,
    ladderLines: ladderLines,
    PLOT: PLOT,
    LADDER: LADDER,
    mount: mount
  };
});
