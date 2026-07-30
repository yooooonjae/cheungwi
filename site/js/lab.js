/**
 * 실험실 — 여섯 개의 자유 파라미터를 손에 쥔다.
 *
 * 앞의 세 장은 이 데이터로 무엇을 말할 수 있는지를 보였다. 여기서는 데이터를
 * 치우고 **엔진만 남긴다**. 가격·NOI·LTV·DSCR·금리·매각 cap 을 직접 적으면
 * `max_loan → hold_model → refi_test` 체인이 브라우저에서 그대로 돌아간다.
 * 서버도 없고 요청도 없다 — 파이썬 원본과 패리티로 묶인 같은 계산이다.
 *
 * ── 이 실험실의 주제는 단위다 ──
 * 이 엔진이 가장 많이 막는 사고는 틀린 모델이 아니라 **틀린 단위**다. 4.5% 를
 * `4.5` 로 넣으면 감정가가 100분의 1 이 되고, `0.045` 로 넣으면 10배가 되는데
 * 둘 다 정상 금액처럼 생겨서 대출과 IRR 까지 조용히 흘러간다. 그래서 여기서는
 *   ① 칸마다 단위를 적고,
 *   ② 적은 수가 엔진에 어떤 수로 들어가는지를 그 자리에서 원 단위로 보이고,
 *   ③ 물리 게이트에 걸리면 "단위를 의심하라"를 **가장 먼저** 말한다.
 *
 * ── 오류의 세 갈래 ──
 * 자바스크립트에서 RangeError·TypeError 는 둘 다 Error 의 하위형이다. `Error` 를
 * 먼저 잡으면 세 갈래가 한 갈래로 뭉개지므로, 언제나 **RangeError → TypeError →
 * 그 밖** 순서다(`kindOf`). 그리고 단계마다 따로 잡는다 — 보유 모델이 거절한다고
 * 대출·차환 판독까지 사라지면 화면은 "안 된다"만 말하고 무엇이 왜 안 되는지는
 * 말하지 못한다.
 *
 * `implausible` 은 게이트가 아니라 **신호**다. 예외를 던지지 않고 판정도 바꾸지
 * 않는다. 그래서 여기서도 계산을 멈추지 않고 사유 원문을 배너로만 올린다.
 */

;(function (root, factory) {
  "use strict";
  var isNode = typeof module !== "undefined" && module.exports;
  var scope = typeof window !== "undefined" ? window : (root || {});
  var charts = isNode ? require("./charts.js") : scope.CheungwiCharts;
  var engine = isNode ? require("./engine.js") : scope.CheungwiEngine;
  var hero = isNode ? require("./hero.js") : scope.CheungwiHero;
  var ch3 = isNode ? require("./chapter3.js") : scope.CheungwiChapter3;
  var api = factory(charts, engine, hero, ch3);
  if (isNode) module.exports = api;
  if (typeof window !== "undefined") window.CheungwiLab = api;
  else if (root) root.CheungwiLab = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, engine, hero, ch3) {
  "use strict";

  var tag = charts.tag, text = charts.text, esc = charts.esc, r4 = charts.r4;
  var F = hero.fmt;

  /** 계측기의 눈금 — Ⅱ장과 같은 규격 연면적에서 나온 도심 대표치를 기본으로 둔다. */
  var SPEC_GFA_M2 = 50000.0;

  /**
   * 여섯 칸. `scale` 은 화면의 수 × scale = 엔진의 수다 — 환산은 한 곳에서
   * 한 번만 일어난다(`toEngine`). 두 곳에서 나누면 반드시 한 곳이 틀린다.
   */
  var FIELDS = [
    { key: "price", label: "가격", unit: "억원", scale: 1e8, step: 10,
      of: "취득가이자 차환 시점의 가치다",
      hint: "1,540 은 1,540억원이다. 원 단위로 적으면 열 자리가 남는다." },
    { key: "noi", label: "NOI", unit: "억원/년", scale: 1e8, step: 1,
      of: "정상화 한 해의 순영업소득",
      hint: "임대수입에서 공실과 운영경비를 뺀 값. 이자·세금 전이다." },
    { key: "ltv", label: "LTV 한도", unit: "%", scale: 0.01, step: 1,
      of: "대출가능액의 첫 번째 제약",
      hint: "55 는 55% 다. 0.55 를 적으면 0.55% 가 되어 대출이 100분의 1 이 된다." },
    { key: "dscr", label: "요구 DSCR", unit: "배", scale: 1, step: 0.05,
      of: "이자를 몇 배로 덮어야 하는가",
      hint: "1.3 은 1.3배다. 130 을 적으면 물리 게이트가 잡는다(0~5)." },
    { key: "rate", label: "금리", unit: "%", scale: 0.01, step: 0.05,
      of: "대출금리이자 차환 시장금리",
      hint: "4.27 은 연 4.27% 다." },
    { key: "exitCap", label: "매각 cap", unit: "%", scale: 0.01, step: 0.05,
      of: "매각가 = 매각 시점 NOI ÷ 이 값",
      hint: "4.05 는 4.05% 다. 0.04 를 적으면 0.04% 가 되어 매각가가 100배가 된다." }
  ];
  var FIELD_BY_KEY = {};
  FIELDS.forEach(function (f) { FIELD_BY_KEY[f.key] = f; });

  /** 손잡이가 없는 가정들. 화면에 적지 않으면 결과가 어디서 왔는지 알 수 없다. */
  var FIXED_NOTES = [
    ["Debt Yield 하한", "NOI ÷ 대출의 하한 — 삼중 제약의 셋째"],
    ["NOI 성장률", "연 단위 계단 성장(한 해 안의 네 분기는 같다)"],
    ["보유 기간", "분기 현금흐름의 길이. IRR 은 연율이다"],
    ["취득부대비용률", "취득세·중개·실사·자문 — 전액 자기자본으로 본다"],
    ["차환 LTV 한도", "만기에 다시 빌릴 때의 관문"],
    ["차환 시장금리", "위의 금리 칸을 그대로 쓴다"],
    ["차환 시점 가치", "위의 가격 칸을 그대로 쓴다"]
  ];

  function defaultFixed(underwriting) {
    var a = (underwriting && underwriting.assumptions) || {};
    return {
      debtYieldMin: a.debt_yield_min === undefined ? 0.08 : a.debt_yield_min,
      noiGrowth: a.noi_growth_y === undefined ? 0.02 : a.noi_growth_y,
      holdYears: a.hold_years === undefined ? 5 : a.hold_years,
      costRate: a.cost_rate === undefined ? 0.05 : a.cost_rate,
      refiLtvMax: a.refi_ltv_max === undefined ? 0.6 : a.refi_ltv_max
    };
  }

  /**
   * 기본값은 Ⅱ장 도심 대표치다 — 실험실이 빈 종이에서 시작하면 무엇이 정상인지
   * 모른 채 숫자를 흔들게 된다. 규격 연면적 5만㎡ 는 Ⅱ장과 같은 눈금이다.
   */
  function defaults(market, underwriting) {
    var reg = market && market.regions && market.regions["도심"];
    if (!reg) throw new TypeError("도심 권역이 없다 — out/market.json 을 확인하라");
    var a = (underwriting && underwriting.assumptions) || {};
    var noiWon = engine.noi(reg.effective_rent_won_m2_mo, SPEC_GFA_M2,
                            a.efficiency, reg.vacancy, a.opex_ratio).noi_won_y;
    var cap = reg.cap.cap_income_based;
    var priceWon = engine.appraise(noiWon, cap);
    return {
      price: priceWon / 1e8,
      noi: noiWon / 1e8,
      ltv: a.ltv_max * 100,
      dscr: a.dscr_min,
      rate: a.loan_rate * 100,
      exitCap: cap * 100
    };
  }

  /** 화면의 수 → 엔진의 수. 환산이 일어나는 유일한 자리다. */
  function toEngine(inputs) {
    var out = {};
    FIELDS.forEach(function (f) {
      var v = inputs ? inputs[f.key] : undefined;
      out[f.key] = (typeof v === "number" && isFinite(v)) ? v * f.scale : v;
    });
    return out;
  }

  /**
   * 세 갈래. **좁은 유형부터** — 뒤집으면 게이트가 '그 밖'으로 뭉개진다.
   * 문자열 인자는 검사가 갈래 순서를 직접 붙들기 위한 문이다.
   */
  function kindOf(err) {
    if (err === "range") err = new RangeError("검사용");
    if (err === "type") err = new TypeError("검사용");
    if (err === "plain") err = new Error("검사용");
    if (err instanceof RangeError) return "gate";
    if (err instanceof TypeError) return "input";
    return "other";
  }

  var KIND_HEAD = {
    gate: "물리 게이트 — 단위를 의심하라",
    input: "입력 오류",
    other: "계산하지 않는다",
    implausible: "실무에 없는 조합이다"
  };

  function stage(fn) {
    try {
      return { ok: true, value: fn() };
    } catch (err) {
      return {
        ok: false, kind: kindOf(err),
        message: err && err.message ? String(err.message) : String(err)
      };
    }
  }

  function eok(won, digits) {
    return F.group(Number(won / 1e8).toFixed(digits === undefined ? 1 : digits));
  }

  // ── 체인 ────────────────────────────────────────────────────────────────
  /**
   * `max_loan → hold_model → refi_test`. 대출은 한 번만 계산되어 뒤의 두 단계에
   * 같은 값으로 들어간다 — 단계마다 다시 부르면 화면 안에서 서로 다른 대출이
   * 돌아다닌다.
   */
  function run(inputs, fixedOverride) {
    // 기본값은 한 곳에서만 나온다 — `defaultFixed(null)` 이 그 한 곳이다.
    var fixed = fixedOverride || defaultFixed(null);
    var res = { inputs: inputs, fixed: fixed, banners: [], ok: false };

    // ① 칸 자체가 수가 아닌 경우. 엔진에 넘기기 전에 여기서 갈린다.
    var bad = FIELDS.filter(function (f) {
      var v = inputs ? inputs[f.key] : undefined;
      return typeof v !== "number" || !isFinite(v);
    });
    if (bad.length) {
      res.engine = null;
      res.banners.push({
        kind: "input", head: KIND_HEAD.input,
        text: bad.map(function (f) { return f.label; }).join(" · ") +
          " 칸이 수가 아니다 — 빈 칸이거나 숫자로 읽히지 않는 글자다."
      });
      res.loan = { ok: false, kind: "input", message: "입력이 수가 아니다" };
      res.hold = res.loan;
      res.refi = res.loan;
      return res;
    }

    var e = toEngine(inputs);
    res.engine = e;

    // ② 대출가능액 — 삼중 제약의 최솟값.
    var loanRes = stage(function () {
      return engine.max_loan(e.noi, e.price, e.ltv, e.dscr, fixed.debtYieldMin,
                             e.rate);
    });
    res.loan = loanRes.ok
      ? {
        ok: true, won: loanRes.value.loan_won, binding: loanRes.value.binding,
        by: loanRes.value.by, ltv: loanRes.value.assumptions.ltv_at_max_loan,
        dscr: loanRes.value.assumptions.dscr_at_max_loan,
        debtYield: loanRes.value.assumptions.debt_yield_at_max_loan
      }
      : loanRes;

    // ③ 보유·매각 — 대출이 정해져야 지분이 정해진다.
    res.hold = loanRes.ok
      ? (function () {
        var r = stage(function () {
          return engine.hold_model(e.price, loanRes.value.loan_won, e.rate, e.noi,
                                   fixed.noiGrowth, e.exitCap, fixed.holdYears,
                                   fixed.costRate);
        });
        return r.ok
          ? {
            ok: true, irr: r.value.equity_irr, exitValueWon: r.value.exit_value,
            equityWon: r.value.assumptions.equity_won,
            exitNoiWon: r.value.assumptions.exit_noi_won_y,
            ltvAtEntry: r.value.assumptions.ltv_at_entry
          }
          : r;
      })()
      : { ok: false, kind: loanRes.kind, propagated: true,
          message: "대출가능액이 없어 보유 모델을 세울 수 없다" };

    // ④ 차환 — 금리 관문과 LTV 관문의 AND.
    res.refi = loanRes.ok
      ? (function () {
        var r = stage(function () {
          return engine.refi_test(e.noi, loanRes.value.loan_won, e.price, e.dscr,
                                  fixed.refiLtvMax, e.rate);
        });
        return r.ok
          ? {
            ok: true, pass: r.value.pass, maxRate: r.value.max_rate,
            headroomBp: r.value.headroom_bp,
            ratePass: r.value.assumptions.rate_pass,
            ltvPass: r.value.assumptions.ltv_pass,
            ltvAtRefi: r.value.assumptions.ltv_at_refi,
            implausible: r.value.implausible,
            reasons: r.value.implausible_reasons
          }
          : r;
      })()
      : { ok: false, kind: loanRes.kind, propagated: true,
          message: "대출가능액이 없어 차환을 판정할 수 없다" };

    // ⑤ 배너 — 사유 없이 색만 바꾸지 않는다. 게이트가 먼저 온다.
    //
    // 앞 단계가 막혀서 못 돈 단계는 배너를 따로 올리지 않는다(`propagated`).
    // 원인 하나에 배너가 셋이면 읽는 사람은 잘못이 셋이라고 읽는다 — 판독값에는
    // 그대로 남으므로 어느 단계가 못 돌았는지는 사라지지 않는다.
    [["대출가능액", res.loan], ["보유·매각 모델", res.hold], ["차환 판정", res.refi]]
      .forEach(function (pair) {
        if (!pair[1].ok && !pair[1].propagated) {
          res.banners.push({
            kind: pair[1].kind, head: KIND_HEAD[pair[1].kind] || KIND_HEAD.other,
            text: pair[0] + " 를 계산하지 못했다 — " + pair[1].message
          });
        }
      });
    res.banners.sort(function (a, b) {
      var order = { gate: 0, input: 1, other: 2, implausible: 3 };
      return (order[a.kind] === undefined ? 9 : order[a.kind]) -
        (order[b.kind] === undefined ? 9 : order[b.kind]);
    });
    if (res.refi.ok && res.refi.implausible) {
      res.banners.push({
        kind: "implausible", head: KIND_HEAD.implausible,
        text: res.refi.reasons.join(" / ")
      });
    }
    res.ok = res.loan.ok && res.hold.ok && res.refi.ok;
    return res;
  }

  // ── 판독값 ──────────────────────────────────────────────────────────────
  var EPS = 1e-9;
  var BINDING_LABEL = {
    ltv: "LTV 한도", dscr: "요구 DSCR", debt_yield: "Debt Yield 하한"
  };

  function readings(res) {
    var rows = [];
    if (res.loan.ok) {
      rows.push({
        k: "대출가능액", v: eok(res.loan.won), u: "억원",
        note: "삼중 제약의 최솟값 · 묶는 제약 " + BINDING_LABEL[res.loan.binding] +
          " · LTV " + F.fx(res.loan.ltv * 100) + "% · DY " +
          F.pct(res.loan.debtYield)
      });
      rows.push({
        k: "자기자본", v: eok(res.engine.price - res.loan.won +
                              res.engine.price * res.fixed.costRate), u: "억원",
        note: "가격 − 대출 + 취득부대비용(" +
          F.fx(res.fixed.costRate * 100, 0) + "%)"
      });
    } else {
      rows.push({ k: "대출가능액", v: "―", u: "", alert: true,
                  note: (KIND_HEAD[res.loan.kind] || "") + " · " + res.loan.message });
    }
    if (res.hold.ok) {
      rows.push({
        k: "매각가", v: eok(res.hold.exitValueWon), u: "억원",
        note: res.fixed.holdYears + "년 뒤 NOI " + eok(res.hold.exitNoiWon) +
          "억원 ÷ 매각 cap · 가정"
      });
      rows.push({
        k: "지분 IRR",
        v: res.hold.irr === null ? "―" : F.pct(res.hold.irr), u: "",
        alert: res.hold.irr !== null && res.hold.irr < 0,
        note: res.hold.irr === null
          ? "부호 변화가 없거나 근이 탐색 범위 밖이다 — 값을 지어내지 않는다"
          : "취득 시점 IRR · 진입 지분 " + eok(res.hold.equityWon) +
            "억원 · 세전·CapEx 전·매각비용 전"
      });
    } else {
      rows.push({ k: "지분 IRR", v: "―", u: "", alert: true,
                  note: (KIND_HEAD[res.hold.kind] || "") + " · " + res.hold.message });
    }
    if (res.refi.ok) {
      rows.push({
        k: "차환 여유", v: F.bp(res.refi.headroomBp), u: "",
        alert: !res.refi.pass,
        note: "견딜 수 있는 최대금리 " + F.pct(res.refi.maxRate) +
          " · 금리 관문 " + (res.refi.ratePass ? "통과" : "탈락") +
          " · LTV 관문 " + (res.refi.ltvPass ? "통과" : "탈락") +
          "(차환 LTV " + F.fx(res.refi.ltvAtRefi * 100) + "%, 한도 " +
          F.fx(res.fixed.refiLtvMax * 100) + "%)"
      });
    } else {
      rows.push({ k: "차환 여유", v: "―", u: "", alert: true,
                  note: (KIND_HEAD[res.refi.kind] || "") + " · " + res.refi.message });
    }
    if (res.loan.ok && res.engine) {
      var dscrNow = res.loan.dscr;
      rows.push({
        k: "DSCR", v: dscrNow === null ? "―" : F.fx(dscrNow, 2), u: "배",
        alert: dscrNow !== null && dscrNow < res.engine.dscr - EPS,
        note: "NOI ÷ 이자 · 요구 " + F.fx(res.engine.dscr, 2) + "배(IO 가정)"
      });
    }
    return rows;
  }

  function lines(res) {
    if (!res.loan.ok) {
      return res.banners.map(function (b) { return b.head + " — " + b.text; });
    }
    var out = [
      "가격 " + eok(res.engine.price) + "억원 · NOI " + eok(res.engine.noi) +
        "억원/년에서 대출가능액은 " + eok(res.loan.won) + "억원이다(묶는 제약 " +
        BINDING_LABEL[res.loan.binding] + "). 셋 중 가장 작은 제약 하나가 " +
        "대출의 크기를 정한다 — 나머지 둘은 여유로 남는다."
    ];
    if (res.hold.ok) {
      out.push("자기자본 " + eok(res.hold.equityWon) + "억원으로 " +
        res.fixed.holdYears + "년 보유하면 지분 IRR 은 " +
        (res.hold.irr === null ? "구할 수 없다(근이 없다)" : F.pct(res.hold.irr)) +
        "다. 매각가 " + eok(res.hold.exitValueWon) + "억원은 매각 cap 가정 " +
        "하나에 통째로 매달려 있다.");
    }
    if (res.refi.ok) {
      out.push("차환은 " + (res.refi.pass ? "통과" : "부결") + "다 — 견딜 수 있는 " +
        "최대금리 " + F.pct(res.refi.maxRate) + " 대 시장금리 " +
        F.pct(res.engine.rate) + ", 여유 " + F.bp(res.refi.headroomBp) + ".");
    }
    res.banners.forEach(function (b) { out.push(b.head + " — " + b.text); });
    return out;
  }

  function liveText(res) {
    if (!res.loan.ok) {
      return "계산하지 못했다 — " +
        (res.banners[0] ? res.banners[0].head + ". " + res.banners[0].text : "");
    }
    return "대출가능액 " + eok(res.loan.won) + "억원, 지분 IRR " +
      (res.hold.ok && res.hold.irr !== null ? F.pct(res.hold.irr) : "―") +
      ", 차환 여유 " + (res.refi.ok ? F.bp(res.refi.headroomBp) : "―") + "." +
      (res.banners.length ? " " + res.banners[0].head + "." : "");
  }

  // ── 작은 판 ─────────────────────────────────────────────────────────────
  // 실험실도 도면이다. 가격을 100 으로 눕히고 대출만큼 물을 채운 뒤, 매각가를
  // 파선으로 얹는다 — 서장의 기둥이 여기서 가장 작은 크기로 한 번 더 선다.
  var LAB_PLATE = {
    w: 300, h: 330, topY: 52, groundY: 282,
    column: { x: 96, width: 92 }, total: 128,
    ground: { x0: 16, x1: 284, depth: 12 },
    minLabel: 11, kMax: 1.3
  };

  function plateGeom(res) {
    var L = LAB_PLATE;
    var H = L.groundY - L.topY;
    var idx = 100 / res.engine.price;
    var bands = [
      { key: "senior", label: "대출", className: "stratum-senior",
        value: r4(res.loan.won * idx) },
      { key: "equity", label: "지분", className: "stratum-equity",
        value: r4((res.engine.price - res.loan.won) * idx) }
    ];
    return {
      L: L, idx: idx, bands: bands,
      y: function (v) { return r4(L.groundY - (v / L.total) * H); },
      laid: charts.strataLayout(bands, {
        x: L.column.x, y: L.topY, width: L.column.width, height: H,
        total: L.total
      })
    };
  }

  function render(res) {
    var L = LAB_PLATE;
    var inner = hero.defs("lab-") + hero.groundPart(L, "lab-");
    if (!res.loan.ok) {
      inner += text(r4(L.w / 2), r4(L.groundY / 2), "판독 불가",
                    { class: "lab lab-over", "text-anchor": "middle" });
      inner += text(r4(L.w / 2), r4(L.groundY / 2 + 20), "아래 사유를 보라",
                    { class: "lab", "text-anchor": "middle" });
      return tag("svg", {
        viewBox: "0 0 " + L.w + " " + L.h, role: "img",
        "aria-label": "실험실 단면 — " + liveText(res),
        class: "plate-svg ch-fig lab-plate is-void",
        "data-fig-w": L.w, "data-fig-min": L.minLabel, "data-fig-kmax": L.kMax,
        preserveAspectRatio: "xMidYMid meet"
      }, inner);
    }

    var g = plateGeom(res);
    var body = "";
    g.laid.forEach(function (b) {
      if (b.height <= 0) return;
      body += tag("rect", {
        x: b.x, y: b.y, width: b.width, height: b.height,
        "data-key": b.key, class: "stratum " + b.className
      });
    });
    inner += tag("g", { class: "strata" }, body);
    var refY = g.y(100);
    inner += tag("rect", {
      x: L.column.x, y: refY, width: L.column.width,
      height: r4(L.groundY - refY), class: "column-frame"
    });
    inner += charts.waterline(r4(res.loan.won * g.idx), {
      x0: r4(L.column.x - 14), x1: r4(L.column.x + L.column.width + 14),
      y: L.topY, height: L.groundY - L.topY, total: L.total, waves: 8
    });
    if (res.hold.ok) {
      var exitIdx = res.hold.exitValueWon * g.idx;
      var clipped = exitIdx > L.total - 4;
      var ey = g.y(Math.min(exitIdx, L.total - 4));
      inner += tag("line", {
        x1: r4(L.column.x - 14), x2: r4(L.column.x + L.column.width + 14),
        y1: ey, y2: ey, class: "exit-rule"
      });
      if (clipped) {
        // 파단선 — 값이 판형을 넘었다는 도면의 표기다(Ⅱ장의 규약 그대로).
        // 자리는 잃어도 수는 라벨이 그대로 싣는다.
        inner += tag("path", {
          d: "M" + r4(L.column.x + 8) + " " + r4(ey - 5) +
             " l6 -4 l6 8 l6 -8 l6 4", class: "break-mark"
        });
      }
      inner += text(r4(L.column.x + L.column.width + 16), r4(ey - 4),
                    "매각가 " + eok(res.hold.exitValueWon) + "억",
                    { class: "lab lab-exit" });
    }
    inner += text(r4(L.column.x + L.column.width + 16),
                  r4(g.y(res.loan.won * g.idx / 2)), "대출 " + eok(res.loan.won) + "억",
                  { class: "lab" });
    inner += text(L.column.x, r4(L.topY - 14), "가격 100 기준", { class: "lab" });
    inner += text(L.column.x, r4(L.groundY + 22),
                  "LTV " + F.fx(res.loan.ltv * 100) + "%", { class: "lab lab-num" });

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h, role: "img",
      "aria-label": "실험실 단면 — " + liveText(res),
      class: "plate-svg ch-fig lab-plate",
      "data-fig-w": L.w, "data-fig-min": L.minLabel, "data-fig-kmax": L.kMax,
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  // ── 칸 ──────────────────────────────────────────────────────────────────
  /**
   * 라벨은 `for` 로 칸에 묶이고, 환산값 `<output>` 은 **스스로 말하지 않는다**.
   * 기본값이 `aria-live="polite"` 인 `<output>` 을 여러 개 두면 손을 한 번 움직일
   * 때마다 낭독기가 같은 이야기를 여러 번 읽는다 — 말하는 자리는 결과 리전 하나뿐이다.
   */
  function fieldRow(spec, v) {
    var id = "lab-f-" + spec.key;
    var num = (typeof v === "number" && isFinite(v)) ? v : "";
    return '<div class="exp-field" data-field="' + esc(spec.key) + '">' +
      '<label class="exp-label" for="' + id + '">' + esc(spec.label) +
      '<span class="exp-of">' + esc(spec.of) + "</span></label>" +
      '<span class="exp-input"><input type="number" id="' + id + '"' +
      ' class="exp-num" inputmode="decimal" step="' + spec.step + '"' +
      ' value="' + esc(String(num)) + '"' +
      ' aria-describedby="' + id + '-h">' +
      '<span class="exp-unit">' + esc(spec.unit) + "</span></span>" +
      '<output class="exp-out num" for="' + id + '" aria-live="off">' +
      esc(engineEcho(spec, v)) + "</output>" +
      '<p class="exp-hint" id="' + id + '-h">' + esc(spec.hint) + "</p>" +
      "</div>";
  }

  /** 적은 수가 엔진에 어떤 수로 들어가는지 — 이 실험실의 주제가 이 한 줄이다. */
  function engineEcho(spec, v) {
    if (typeof v !== "number" || !isFinite(v)) return "―";
    var e = v * spec.scale;
    if (spec.scale === 1e8) return "→ " + F.group(Math.round(e).toFixed(0)) + "원";
    if (spec.scale === 0.01) return "→ " + F.fx(e, 6) + " (소수)";
    // 배수는 환산이 없다 — "그대로"라고 적는 편이 화살표만 두는 것보다 정직하다.
    return "→ " + F.fx(e, 4) + " (그대로)";
  }

  function bannerHtml(res) {
    return res.banners.map(function (b) {
      return '<p class="rig-banner is-' + esc(b.kind) + '"><b>' + esc(b.head) +
        "</b> " + esc(b.text) + "</p>";
    }).join("");
  }

  function readingsHtml(res) {
    return '<dl class="g-rows rig-rows">' + readings(res).map(function (r) {
      return '<div class="g-row' + (r.alert ? " is-alert" : "") + '">' +
        "<dt>" + esc(r.k) + '<span class="row-note">' + esc(r.note || "") +
        "</span></dt><dd><b class=\"num\">" + esc(r.v) + "</b>" +
        (r.u ? '<span class="unit">' + esc(r.u) + "</span>" : "") +
        "</dd></div>";
    }).join("") + "</dl>";
  }

  function fixedHtml(fixed) {
    var v = {
      "Debt Yield 하한": F.pct(fixed.debtYieldMin),
      "NOI 성장률": F.pct(fixed.noiGrowth),
      "보유 기간": fixed.holdYears + "년",
      "취득부대비용률": F.pct(fixed.costRate, 0),
      "차환 LTV 한도": F.pct(fixed.refiLtvMax, 0),
      "차환 시장금리": "= 금리 칸",
      "차환 시점 가치": "= 가격 칸"
    };
    return FIXED_NOTES.map(function (pair) {
      return "<div><dt>" + esc(pair[0]) + "</dt><dd>" + esc(v[pair[0]]) +
        '<span class="fx-of">' + esc(pair[1]) + "</span></dd></div>";
    }).join("");
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  function mount(doc, data) {
    doc = doc || document;
    data = data || {};
    var formEl = doc.getElementById("lab-fields");
    var plateEl = doc.getElementById("lab-plate");
    if (!formEl || !plateEl) return null;
    var readEl = doc.getElementById("lab-readings");
    var bannerEl = doc.getElementById("lab-banners");
    var lineEl = doc.getElementById("lab-reading");
    var liveEl = doc.getElementById("lab-live");
    var fixedEl = doc.getElementById("lab-fixed");
    var resetEl = doc.getElementById("lab-reset");

    var fixed = defaultFixed(data.underwriting);
    var base = defaults(data.market, data.underwriting);
    var inputs = {};
    Object.keys(base).forEach(function (k) { inputs[k] = round4(base[k]); });
    var liveTimer = null;

    function paintFields() {
      formEl.innerHTML = FIELDS.map(function (f) {
        return fieldRow(f, inputs[f.key]);
      }).join("");
    }

    function paint(announce) {
      var res = run(inputs, fixed);
      plateEl.innerHTML = render(res);
      if (readEl) readEl.innerHTML = readingsHtml(res);
      if (bannerEl) bannerEl.innerHTML = bannerHtml(res);
      if (lineEl) {
        lineEl.innerHTML = lines(res).map(function (s) {
          return "<li>" + esc(s) + "</li>";
        }).join("");
      }
      if (ch3 && ch3.fitFigures) ch3.fitFigures(plateEl);
      if (liveEl && announce) {
        // 손을 멈춘 뒤 한 번만 말한다 — 타자마다 읽으면 아무것도 들리지 않는다.
        if (liveTimer) clearTimeout(liveTimer);
        liveTimer = setTimeout(function () {
          liveEl.textContent = liveText(res);
        }, 600);
      }
      return res;
    }

    function round4(v) { return Math.round(v * 1e4) / 1e4; }

    formEl.addEventListener("input", function (ev) {
      var el = ev.target;
      if (!el || el.tagName !== "INPUT") return;
      var host = el.closest ? el.closest("[data-field]") : null;
      var key = host && host.getAttribute("data-field");
      var spec = FIELD_BY_KEY[key];
      if (!spec) return;
      // 빈 칸은 0 이 아니다 — 그 사실이 '입력 오류' 갈래로 가야 한다.
      inputs[key] = el.value === "" ? null : Number(el.value);
      if (inputs[key] !== null && !isFinite(inputs[key])) inputs[key] = null;
      var out = host.querySelector("output");
      if (out) out.textContent = engineEcho(spec, inputs[key]);
      paint(true);
    });

    if (resetEl) {
      resetEl.addEventListener("click", function () {
        Object.keys(base).forEach(function (k) { inputs[k] = round4(base[k]); });
        paintFields();
        paint(true);
      });
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
          if (ch3 && ch3.fitFigures) ch3.fitFigures(plateEl);
        });
      });
    }

    if (fixedEl) fixedEl.innerHTML = fixedHtml(fixed);
    paintFields();
    paint(false);
    return { run: function () { return run(inputs, fixed); }, inputs: inputs };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var host = document.getElementById("lab-fields");
    if (!host) return;
    try {
      mount(document, {
        market: window.__DATA_MARKET,
        underwriting: window.__DATA_UNDERWRITING
      });
    } catch (err) {
      host.innerHTML = '<p class="fail">실험실을 세우지 못했다 — ' +
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
    SPEC_GFA_M2: SPEC_GFA_M2,
    FIELDS: FIELDS,
    fields: function () { return FIELDS; },
    FIXED_NOTES: FIXED_NOTES,
    defaultFixed: defaultFixed,
    defaults: defaults,
    toEngine: toEngine,
    kindOf: kindOf,
    run: run,
    readings: readings,
    lines: lines,
    liveText: liveText,
    render: render,
    plateGeom: plateGeom,
    fieldRow: fieldRow,
    engineEcho: engineEcho,
    readingsHtml: readingsHtml,
    bannerHtml: bannerHtml,
    fixedHtml: fixedHtml,
    mount: mount
  };
});
