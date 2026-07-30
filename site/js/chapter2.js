/**
 * Ⅱ장 자본의 층위 — 서장의 단면이 계측기가 된다.
 *
 * 같은 판, 같은 타워, 같은 수면이다. 달라진 것은 **읽는 사람이 손잡이를 쥔다**는
 * 것 하나다. 공실 손잡이를 당기면 창이 꺼지고 → NOI 가 내려가고 → 가치가 내려가고
 * → 고정된 대출 위로 수면이 상대적으로 차오르고 → 지분 지층이 얇아진다. 한 번의
 * 동작에 인과의 사슬 전체가 보이는 것, 그것이 이 장의 전부다.
 *
 * ── 대출은 왜 고정인가 ──
 * 슬라이더마다 `max_loan` 을 다시 부르면 대출이 늘 조건에 맞춰 줄어들어 LTV 가
 * 한도 아래에 붙박이고, **지분은 영영 잠기지 않는다**. 현실의 순서는 반대다 —
 * 대출은 취득 시점에 한 번 정해지고 그 뒤에 세상이 변한다. 그래서 수면(대출)은
 * 기준 조건에서 한 번 긋고 움직이지 않으며, 움직이는 것은 자산 쪽이다.
 * "지금 조건이라면 얼마나 빌릴 수 있는가"는 판독값 한 줄로 따로 싣는다.
 *
 * ── 눈금은 지어낸 수다 ──
 * 대장이 없어 동별 연면적을 모른다. 계측기가 원 단위 금액을 말하려면 규격이
 * 있어야 하므로 **기준 규격 연면적 50,000㎡** 하나를 눈금으로 세우고 표제란에
 * 적는다(`SPEC`). 관측이 아니라 자의 눈금이라는 사실을 숨기지 않는 대신, 대장이
 * 열려 승격 행이 생기면 `buildingBase` 가 그 동의 실측 연면적으로 갈아 끼운다 —
 * 그 경로는 지금 합성 데이터로 검사되고 있다.
 *
 * ── 오류를 잡는 순서 ──
 * 엔진은 파이썬의 세 갈래를 자바스크립트 관례로 옮겼다(게이트 → RangeError,
 * 입력 → TypeError, 미구현 → Error). 자바스크립트에서는 앞의 둘이 Error 의
 * **하위형**이라, `Error` 를 먼저 잡으면 세 갈래가 한 갈래로 뭉개진다. 여기서는
 * 언제나 **RangeError → TypeError → 그 밖** 순서다(`kindOf`). 그리고 단계마다
 * 따로 잡는다 — 보유 모델이 거절한다고 해서 DSCR·차환 판독까지 함께 사라지면,
 * 화면은 "계산이 안 된다"만 말하고 무엇이 왜 안 되는지는 말하지 못한다.
 *
 * 순수 함수(`regionBase`·`evaluate`·`render`·`readings`·`lines`)와 DOM(`mount`)을
 * 나눈 이유는 서장과 같다 — 슬라이더가 만든 좌표를 브라우저 없이 붙들기 위해서다.
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
  if (typeof window !== "undefined") window.CheungwiChapter2 = api;
  else if (root) root.CheungwiChapter2 = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, engine, hero) {
  "use strict";

  var tag = charts.tag, text = charts.text, esc = charts.esc, r4 = charts.r4;
  var F = hero.fmt;

  /** 기준 규격 — 관측이 아니라 계측기의 눈금이다. 표제란에 그대로 적는다. */
  var SPEC = {
    gfaM2: 50000.0,
    note: "권역 대표 단면의 연면적은 관측이 아니라 계측기의 눈금이다 — " +
      "건축물대장이 열리기 전이라 동별 연면적을 모른다. 5만㎡ 는 서울 프라임 " +
      "오피스의 흔한 규모대에서 고른 한 값이고, 규모 계수가 기준(1.0)이 되는 " +
      "구간이라 보정이 눈금에 끼어들지 않는다. 대장 승격 뒤에는 동별 실측 " +
      "연면적으로 갈아 끼운다."
  };

  /** 기둥의 눈금 — 기준 가치를 100 으로 두고 그 위에 30 만큼의 하늘을 남긴다. */
  var COLUMN_TOTAL = 130;
  var BASE_INDEX = 100;

  var KNOBS = [
    {
      key: "rate", label: "금리", kind: "delta",
      min: -0.02, max: 0.02, step: 0.0005, scale: 100, digits: 2, unit: "%p",
      of: "대출 이자와 차환 시장금리",
      note: "빌린 금액은 그대로 두고 이자만 움직인다 — 변동금리이거나 만기에 " +
        "다시 빌리는 상황이다."
    },
    {
      key: "vacancy", label: "공실", kind: "absolute",
      min: 0, max: 0.30, step: 0.005, scale: 100, digits: 1, unit: "%",
      of: "타워의 꺼진 창과 NOI",
      note: "기준값은 R-ONE 권역 공실률이다. 손잡이를 당기면 창이 꺼지고 " +
        "NOI·가치가 함께 내려간다."
    },
    {
      key: "exitCap", label: "Exit Cap", kind: "delta",
      min: -0.01, max: 0.01, step: 0.00025, scale: 100, digits: 2, unit: "%p",
      of: "매각가와 지분 IRR",
      note: "진입 cap 과 같게 두면 자본이득이 NOI 성장만큼만 생기고, 벌리면 " +
        "매각가가 급격히 무너진다. 매각 cap 은 관측이 아니라 가정이다."
    }
  ];
  var KNOB_BY_KEY = {};
  KNOBS.forEach(function (s) { KNOB_BY_KEY[s.key] = s; });

  var BINDING_LABEL = {
    ltv: "LTV 한도", dscr: "요구 DSCR", debt_yield: "Debt Yield 하한"
  };

  // ── 수치 다듬기 ─────────────────────────────────────────────────────────
  /**
   * 문구에 그대로 박히는 인자는 소수 여섯째 자리에서 끊는다.
   *
   * 엔진의 `notes` 는 인자를 파이썬 `str(float)` 표기로 문장에 넣는다. 슬라이더
   * 산술이 낳은 `0.043400000000000005` 를 그대로 넘기면 화면의 문장이 그 꼬리를
   * 달고 나온다 — 계산에는 아무 영향이 없고 **읽는 사람만 잃는** 종류의 결함이다.
   */
  function round6(x) {
    return Math.round(x * 1e6) / 1e6;
  }

  function eok(won, digits) {
    return F.group(Number(won / 1e8).toFixed(digits === undefined ? 0 : digits));
  }

  /** 엔진의 세 갈래. **좁은 유형부터** — 뒤집으면 게이트가 '그 밖'으로 뭉개진다. */
  function kindOf(err) {
    if (err instanceof RangeError) return "gate";
    if (err instanceof TypeError) return "input";
    return "other";
  }

  /** 한 단계를 격리해 부른다. 실패는 그 단계에만 머문다. */
  function stage(fn) {
    try {
      return { ok: true, value: fn() };
    } catch (err) {
      return {
        ok: false,
        kind: kindOf(err),
        message: err && err.message ? String(err.message) : String(err)
      };
    }
  }

  var KIND_HEAD = {
    gate: "물리 게이트 — 단위를 의심하라",
    input: "입력 오류",
    other: "계산하지 않는다"
  };

  // ── 계측 대상 ───────────────────────────────────────────────────────────
  function regionBase(market, underwriting, name) {
    if (!market || !market.regions || !market.regions[name]) {
      throw new TypeError("모르는 권역이다: " + String(name));
    }
    var reg = market.regions[name];
    var a = (underwriting && underwriting.assumptions) || {};
    return {
      kind: "region",
      key: "region:" + name,
      name: name + " 권역 대표",
      region: name,
      quarter: reg.latest_quarter,
      effRent: reg.effective_rent_won_m2_mo,
      adjusted: false,
      gfa: SPEC.gfaM2,
      gfaIsSpec: true,
      vacancy0: reg.vacancy,
      cap: reg.cap.cap_income_based,
      loanRate: round6(a.loan_rate),
      marketRate: round6(a.market_rate),
      ltvMax: a.ltv_max,
      dscrMin: a.dscr_min,
      dyMin: a.debt_yield_min,
      refiLtvMax: a.refi_ltv_max,
      efficiency: a.efficiency,
      opexRatio: a.opex_ratio,
      noiGrowth: a.noi_growth_y,
      holdYears: a.hold_years,
      costRate: a.cost_rate
    };
  }

  /**
   * 승격 행 하나를 계측 대상으로. 지금은 합성 데이터로만 도달하는 경로다.
   *
   * 임대료는 **이미 보정된 값**(`building_adjust.value`)을 쓴다 — 연식·규모·역세권
   * 계수는 슬라이더가 건드리는 값이 아니라 그 동의 성질이기 때문이다.
   */
  function buildingBase(row) {
    if (!row || !row.underwriting) {
      throw new TypeError(
        "승격된 행이 아니다 — `underwriting` 이 없다. pending·실패 행은 " +
        "계측 대상이 될 수 없다(계산이 막혀 있다)");
    }
    var uw = row.underwriting;
    var la = uw.loan.assumptions;
    var ha = uw.hold.assumptions;
    var ra = uw.refi.assumptions;
    return {
      kind: "building",
      key: "building:" + row.id,
      name: row.name,
      region: row.region,
      quarter: (row.region_figures || {}).latest_quarter,
      effRent: uw.building_adjust.value,
      adjusted: true,
      gfa: uw.gfa_m2,
      gfaIsSpec: false,
      vacancy0: uw.noi.assumptions.vacancy,
      cap: uw.cap_used,
      loanRate: round6(la.loan_rate),
      marketRate: round6(ra.market_rate),
      ltvMax: la.ltv_max,
      dscrMin: la.dscr_min,
      dyMin: la.debt_yield_min,
      refiLtvMax: ra.ltv_max,
      efficiency: uw.noi.assumptions.efficiency,
      opexRatio: uw.noi.assumptions.opex_ratio,
      noiGrowth: ha.noi_growth_y,
      holdYears: ha.hold_years,
      costRate: ha.cost_rate
    };
  }

  // ── 손잡이 ──────────────────────────────────────────────────────────────
  function defaultKnobs(base) {
    return { rate: 0, vacancy: base.vacancy0, exitCap: 0 };
  }

  /**
   * 선언된 범위 안으로 접는다. `evaluate` 는 접지 **않는다** — 범위 밖 값을
   * 조용히 고쳐 그리면 게이트가 무엇을 막았는지가 화면에서 사라지기 때문이다.
   */
  function clampKnobs(knobs, base) {
    var d = defaultKnobs(base);
    var out = {};
    KNOBS.forEach(function (s) {
      var v = knobs && typeof knobs[s.key] === "number" && isFinite(knobs[s.key])
        ? knobs[s.key] : d[s.key];
      out[s.key] = Math.min(s.max, Math.max(s.min, v));
    });
    return out;
  }

  function knobDisplay(spec, v, base) {
    if (spec.kind === "absolute") {
      return F.fx(v * spec.scale, spec.digits) + spec.unit;
    }
    return (v > 0 ? "+" : "") + F.fx(v * spec.scale, spec.digits) + spec.unit;
  }

  /** 손잡이가 만든 **결과**. 큰 숫자가 "+0.00%p" 이면 아무것도 말하지 않는다. */
  function knobResult(spec, v, base) {
    if (spec.key === "vacancy") return F.fx(v * 100, 1) + "%";
    if (spec.key === "rate") return F.pct(round6(base.loanRate + v));
    return F.pct(round6(base.cap + v));
  }

  function ariaValueText(spec, v, base) {
    if (spec.key === "vacancy") {
      return "공실률 " + F.fx(v * 100, 1) + "%, 기준 " +
        F.fx(base.vacancy0 * 100, 1) + "% 대비 " +
        (v >= base.vacancy0 ? "+" : "") + F.fx((v - base.vacancy0) * 100, 1) + "%p";
    }
    if (spec.key === "rate") {
      return "금리 " + knobDisplay(spec, v, base) + ", 기준 " +
        F.pct(base.loanRate) + " 에서 " + F.pct(round6(base.loanRate + v)) + " 로";
    }
    return "매각 cap " + knobDisplay(spec, v, base) + ", 기준 " +
      F.pct(base.cap) + " 에서 " + F.pct(round6(base.cap + v)) + " 로";
  }

  /** 기준값이 눈금의 어디쯤인가 — 트랙 아래 삼각으로 찍을 자리(0~100%). */
  function restFraction(spec, base) {
    var d = defaultKnobs(base)[spec.key];
    return r4(((d - spec.min) / (spec.max - spec.min)) * 100);
  }

  function sliderRow(spec, v, base) {
    var id = "ch2-knob-" + spec.key;
    return '<div class="knob" data-knob="' + esc(spec.key) + '">' +
      '<label class="knob-label" for="' + id + '">' + esc(spec.label) +
      '<span class="knob-of">' + esc(spec.of) + "</span></label>" +
      '<output class="knob-out num" for="' + id + '">' +
      esc(knobResult(spec, v, base)) +
      (spec.kind === "delta"
        ? '<span class="knob-delta">' + esc(knobDisplay(spec, v, base)) + "</span>"
        : "") + "</output>" +
      '<input type="range" id="' + id + '" class="knob-range"' +
      ' min="' + spec.min + '" max="' + spec.max + '" step="' + spec.step + '"' +
      ' value="' + v + '"' +
      ' aria-valuetext="' + esc(ariaValueText(spec, v, base)) + '">' +
      '<p class="knob-scale" style="--rest:' + restFraction(spec, base) + '%">' +
      "<span>" + esc(knobDisplay(spec, spec.min, base)) + "</span>" +
      '<span class="knob-rest">기준 ' +
      esc(knobResult(spec, defaultKnobs(base)[spec.key], base)) + "</span>" +
      "<span>" + esc(knobDisplay(spec, spec.max, base)) + "</span></p>" +
      "</div>";
  }

  // ── 계측 ────────────────────────────────────────────────────────────────
  /**
   * 손잡이 셋 → 엔진 → 그릴 수 있는 모델 하나. 이 함수가 이 장의 심장이다.
   */
  function evaluate(base, knobs) {
    if (!base || typeof base !== "object") {
      throw new TypeError("계측 대상이 없다: " + String(base));
    }
    var k = {
      rate: (knobs && typeof knobs.rate === "number") ? knobs.rate : 0,
      vacancy: (knobs && typeof knobs.vacancy === "number")
        ? knobs.vacancy : base.vacancy0,
      exitCap: (knobs && typeof knobs.exitCap === "number") ? knobs.exitCap : 0
    };
    var loanRate = round6(base.loanRate + k.rate);
    var marketRate = round6(base.marketRate + k.rate);
    var exitCap = round6(base.cap + k.exitCap);

    // ① 기준 상태 — 대출은 여기서 한 번 정해지고 그 뒤로 움직이지 않는다.
    var baseNoi = stage(function () {
      return engine.noi(base.effRent, base.gfa, base.efficiency,
                        base.vacancy0, base.opexRatio).noi_won_y;
    });
    var baseValue = baseNoi.ok ? stage(function () {
      return engine.appraise(baseNoi.value, base.cap);
    }) : baseNoi;
    var loanRes = baseValue.ok ? stage(function () {
      return engine.max_loan(baseNoi.value, baseValue.value, base.ltvMax,
                             base.dscrMin, base.dyMin, base.loanRate);
    }) : baseValue;

    // ② 손잡이를 반영한 지금.
    var noiRes = stage(function () {
      return engine.noi(base.effRent, base.gfa, base.efficiency,
                        k.vacancy, base.opexRatio).noi_won_y;
    });
    var valueRes = noiRes.ok ? stage(function () {
      return engine.appraise(noiRes.value, base.cap);
    }) : noiRes;

    var model = {
      base: base,
      knobs: k,
      loanRate: loanRate,
      marketRate: marketRate,
      exitCap: exitCap,
      columnTotal: COLUMN_TOTAL,
      banners: [],
      ok: baseNoi.ok && baseValue.ok && loanRes.ok && noiRes.ok && valueRes.ok
    };

    model.noi = noiRes.ok
      ? { ok: true, won: noiRes.value, baseWon: baseNoi.ok ? baseNoi.value : null }
      : noiRes;
    model.value = valueRes.ok
      ? { ok: true, won: valueRes.value, baseWon: baseValue.ok ? baseValue.value : null }
      : valueRes;
    model.loan = loanRes.ok
      ? {
        ok: true, won: loanRes.value.loan_won, binding: loanRes.value.binding,
        by: loanRes.value.by, notes: loanRes.value.assumptions.notes
      }
      : loanRes;

    if (!model.ok) {
      // 기둥을 그릴 좌표가 없다. 무엇이 왜 없는지만 남기고 멈춘다.
      [["기준 NOI", baseNoi], ["기준 가치", baseValue], ["대출", loanRes],
       ["NOI", noiRes], ["가치", valueRes]].forEach(function (pair) {
        if (!pair[1].ok) {
          model.banners.push({
            kind: pair[1].kind,
            head: KIND_HEAD[pair[1].kind],
            text: pair[0] + " 를 계산하지 못했다 — " + pair[1].message
          });
        }
      });
      model.bands = [];
      model.tower = towerOf(k.vacancy);
      return model;
    }

    var loanWon = model.loan.won;
    var valueWon = model.value.won;
    var baseValueWon = model.value.baseWon;
    var idx = BASE_INDEX / baseValueWon;

    model.ltv = loanWon / valueWon;
    model.dscr = loanWon > 0 && loanRate > 0
      ? model.noi.won / (loanWon * loanRate) : null;
    model.debtYield = loanWon > 0 ? model.noi.won / loanWon : null;
    model.equity = {
      won: valueWon - loanWon,
      submerged: valueWon < loanWon,
      share: (valueWon - loanWon) / baseValueWon
    };
    model.index = idx;
    model.water = {
      level: r4(loanWon * idx),
      total: COLUMN_TOTAL,
      valueTop: r4(valueWon * idx)
    };
    model.bands = [
      { key: "senior", label: "대출(고정)", className: "stratum-senior",
        value: r4(Math.min(loanWon, valueWon) * idx) },
      { key: "equity", label: "지분", className: "stratum-equity",
        value: r4(Math.max(0, valueWon - loanWon) * idx) }
    ];
    model.tower = towerOf(k.vacancy);

    // ③ 지금 조건이라면 얼마나 빌릴 수 있는가 — 고정된 대출과 나란히 놓는다.
    var loanNow = stage(function () {
      return engine.max_loan(model.noi.won, valueWon, base.ltvMax, base.dscrMin,
                             base.dyMin, loanRate);
    });
    model.loanNow = loanNow.ok
      ? { ok: true, won: loanNow.value.loan_won, binding: loanNow.value.binding }
      : loanNow;

    // ④ 차환 — 금리 관문과 LTV 관문 둘 다.
    var refiRes = stage(function () {
      return engine.refi_test(model.noi.won, loanWon, valueWon, base.dscrMin,
                              base.refiLtvMax, marketRate);
    });
    model.refi = refiRes.ok
      ? {
        ok: true,
        pass: refiRes.value.pass,
        maxRate: refiRes.value.max_rate,
        headroomBp: refiRes.value.headroom_bp,
        ratePass: refiRes.value.assumptions.rate_pass,
        ltvPass: refiRes.value.assumptions.ltv_pass,
        ltvAtRefi: refiRes.value.assumptions.ltv_at_refi,
        // 자산이 이 아래로 내려가면 LTV 관문에서 떨어진다 — 기둥에 그을 수 있는
        // 유일한 차환 한계선이다(금리 관문은 값의 축이 아니라 이율의 축에 있다).
        ltvLimitWon: loanWon / base.refiLtvMax,
        implausible: refiRes.value.implausible,
        reasons: refiRes.value.implausible_reasons
      }
      : refiRes;

    // ⑤ 보유·매각. 대출이 가치를 넘으면 이 모델은 거절한다 — 그 거절도 판독이다.
    var holdRes = stage(function () {
      return engine.hold_model(valueWon, loanWon, loanRate, model.noi.won,
                               base.noiGrowth, exitCap, base.holdYears,
                               base.costRate);
    });
    model.hold = holdRes.ok
      ? {
        ok: true,
        irr: holdRes.value.equity_irr,
        exitValueWon: holdRes.value.exit_value,
        notes: holdRes.value.assumptions.notes
      }
      : holdRes;

    var bevRes = stage(function () {
      return engine.breakeven_vacancy(base.effRent, base.gfa, base.efficiency,
                                      base.opexRatio, loanWon, loanRate,
                                      base.dscrMin);
    });
    model.bev = bevRes.ok ? { ok: true, vacancy: bevRes.value } : bevRes;

    // ⑥ 지분이 완전히 잠기는 공실률. 손잡이 밖이면 밖이라고 적는다.
    var vSpec = KNOB_BY_KEY.vacancy;
    var drownV = 1 - (loanWon / baseValueWon) * (1 - base.vacancy0);
    model.drown = {
      vacancy: drownV,
      reachable: drownV >= vSpec.min && drownV <= vSpec.max
    };

    // ⑦ 배너 — 사유 없이 색만 바꾸지 않는다.
    [["차환", refiRes], ["보유 모델", holdRes], ["손익분기 공실률", bevRes],
     ["현 조건 대출가능액", loanNow]].forEach(function (pair) {
      if (!pair[1].ok) {
        model.banners.push({
          kind: pair[1].kind,
          head: KIND_HEAD[pair[1].kind],
          text: pair[0] + " 를 계산하지 못했다 — " + pair[1].message
        });
      }
    });
    if (model.refi.ok && model.refi.implausible) {
      model.banners.push({
        kind: "implausible",
        head: "실무에 없는 조합이다",
        text: model.refi.reasons.join(" / ")
      });
    }
    if (model.equity.submerged) {
      model.banners.push({
        kind: "alert",
        head: "지분이 잠겼다",
        text: "부채 " + eok(loanWon) + "억원이 가치 " + eok(valueWon) +
          "억원을 " + eok(loanWon - valueWon) + "억원만큼 넘었다 — 수면이 자산의 " +
          "천장 위에 있다."
      });
    } else {
      model.banners.push({
        kind: "note",
        head: model.drown.reachable ? "완전 침수까지" : "이 손잡이로는 잠기지 않는다",
        text: model.drown.reachable
          ? "공실률 " + F.fx(drownV * 100, 1) + "% 에서 가치가 대출과 같아져 " +
            "지분이 완전히 잠긴다."
          : "지분이 완전히 잠기려면 공실률이 " + F.fx(drownV * 100, 1) +
            "% 여야 한다 — 손잡이의 상한 " + F.fx(vSpec.max * 100, 0) +
            "% 밖이다. 그 사실 자체가 판독값이다."
      });
    }
    return model;
  }

  function towerOf(vacancy) {
    var cells = hero.FLOORS * hero.CELLS_PER_FLOOR;
    var dark = Math.round(Math.max(0, Math.min(1, vacancy)) * cells);
    return {
      floors: hero.FLOORS, perFloor: hero.CELLS_PER_FLOOR, cells: cells,
      dark: dark, darkCells: hero.pickDarkCells(cells, dark)
    };
  }

  // ── 판독값 ──────────────────────────────────────────────────────────────
  // 결속 제약은 **정확히** 하한에 앉는다(대출이 그 제약으로 정해졌으니). 부동소수
  // 꼬리 하나로 "하한 미달"이 켜지면 기준 상태의 화면이 붉게 물든다 — 거짓 경보다.
  var EPS = 1e-9;

  function readings(m) {
    if (!m.ok) {
      return [{ k: "판독 불가", v: "―", u: "", alert: true,
                note: m.banners.length ? m.banners[0].text : "" }];
    }
    var rows = [
      { k: "NOI", v: eok(m.noi.won), u: "억원/년",
        note: "유효임대료 × 임대면적 × 12 에서 공실과 opex 를 뺀 값" },
      { k: "가치", v: eok(m.value.won), u: "억원",
        note: "NOI ÷ 진입 cap " + F.pct(m.base.cap) + " (직접환원법)" },
      { k: "대출(고정)", v: eok(m.loan.won), u: "억원",
        note: "취득 시점 삼중 제약 · 묶는 제약 " + BINDING_LABEL[m.loan.binding] },
      { k: "LTV", v: F.fx(m.ltv * 100) + "%", u: "",
        alert: m.ltv > m.base.refiLtvMax + EPS,
        note: "차환 LTV 한도 " + F.fx(m.base.refiLtvMax * 100) + "%" },
      { k: "지분", v: eok(m.equity.won), u: "억원", alert: m.equity.submerged,
        note: m.equity.submerged ? "수면 아래다" : "가치 − 대출" },
      { k: "DSCR", v: m.dscr === null ? "―" : F.fx(m.dscr, 2), u: "배",
        alert: m.dscr !== null && m.dscr < m.base.dscrMin - EPS,
        note: "NOI ÷ 이자 · 요구 " + F.fx(m.base.dscrMin, 2) + "배(IO 가정)" },
      { k: "Debt Yield", v: m.debtYield === null ? "―" : F.pct(m.debtYield), u: "",
        alert: m.debtYield !== null && m.debtYield < m.base.dyMin - EPS,
        note: "NOI ÷ 대출 · 하한 " + F.pct(m.base.dyMin) }
    ];
    if (m.refi.ok) {
      rows.push({
        k: "차환 여유", v: F.bp(m.refi.headroomBp), u: "",
        alert: !m.refi.pass,
        note: "견딜 수 있는 최대금리 " + F.pct(m.refi.maxRate) + " − 시장금리 " +
          F.pct(m.marketRate) + " · 금리 관문 " + (m.refi.ratePass ? "통과" : "탈락") +
          " · LTV 관문 " + (m.refi.ltvPass ? "통과" : "탈락")
      });
      rows.push({
        k: "차환 한계선", v: eok(m.refi.ltvLimitWon), u: "억원",
        alert: !m.refi.ltvPass,
        note: "자산이 이 아래로 내려가면 LTV 관문에서 떨어진다(대출 ÷ " +
          F.fx(m.base.refiLtvMax * 100) + "%)"
      });
    }
    if (m.bev.ok) {
      rows.push({
        k: "손익분기 공실률", v: F.fx(m.bev.vacancy * 100) + "%", u: "",
        alert: m.bev.vacancy <= m.knobs.vacancy + EPS,
        note: "이 공실률을 넘으면 이자를 요구 DSCR 로 덮지 못한다"
      });
    }
    if (m.hold.ok) {
      rows.push({
        k: "매각가", v: eok(m.hold.exitValueWon), u: "억원",
        note: m.base.holdYears + "년 뒤 NOI ÷ 매각 cap " + F.pct(m.exitCap) + " · 가정"
      });
      rows.push({
        k: "지분 IRR", v: m.hold.irr === null ? "―" : F.pct(m.hold.irr), u: "",
        alert: m.hold.irr !== null && m.hold.irr < 0,
        note: m.hold.irr === null
          ? "부호 변화가 없거나 근이 탐색 범위 밖이다 — 값을 지어내지 않는다"
          : "세전·CapEx 전·매각비용 전"
      });
    } else {
      rows.push({
        k: "지분 IRR", v: "―", u: "", alert: true,
        note: KIND_HEAD[m.hold.kind] + " · " + m.hold.message
      });
    }
    if (m.loanNow && m.loanNow.ok) {
      rows.push({
        k: "지금 조건의 대출가능액", v: eok(m.loanNow.won), u: "억원",
        note: "묶는 제약 " + BINDING_LABEL[m.loanNow.binding] +
          " · 고정된 대출과의 차이가 차환에서 갚아야 할 금액이다"
      });
    }
    return rows;
  }

  function lines(m) {
    if (!m.ok) {
      return m.banners.map(function (b) { return b.head + " — " + b.text; });
    }
    var out = [
      m.base.name + " · 공실 " + F.fx(m.knobs.vacancy * 100, 1) + "% · 금리 " +
        F.pct(m.loanRate) + " · 매각 cap " + F.pct(m.exitCap) + " — 타워 " +
        m.tower.cells + "칸 중 " + m.tower.dark + "칸이 꺼져 있다.",
      "가치 " + eok(m.value.won) + "억원 위에 대출 " + eok(m.loan.won) +
        "억원의 수면이 그어진다. 지분은 " + eok(m.equity.won) + "억원 · LTV " +
        F.fx(m.ltv * 100) + "%" +
        (m.equity.submerged ? " — 수면이 자산의 천장을 넘었다." : "."),
      "대출은 취득 시점에 정해진 뒤 움직이지 않는다 — 손잡이가 움직이는 것은 " +
        "자산 쪽이고, 그래서 수면이 상대적으로 차오른다."
    ];
    if (m.refi.ok) {
      out.push("차환 여유 " + F.bp(m.refi.headroomBp) + " — 견딜 수 있는 최대금리 " +
        F.pct(m.refi.maxRate) + " 대 시장금리 " + F.pct(m.marketRate) + ". 판정은 " +
        (m.refi.pass ? "통과" : "부결") + "(금리·LTV 두 관문의 AND).");
    }
    m.banners.forEach(function (b) {
      if (b.kind === "note" || b.kind === "alert") out.push(b.head + " — " + b.text);
    });
    return out;
  }

  function liveText(m) {
    if (!m.ok) return "판독 불가 — " + (m.banners[0] ? m.banners[0].text : "");
    return "공실 " + F.fx(m.knobs.vacancy * 100, 1) + "%, 금리 " + F.pct(m.loanRate) +
      ", 매각 cap " + F.pct(m.exitCap) + ". 가치 " + eok(m.value.won) +
      "억원, 수면(대출) " + eok(m.loan.won) + "억원, 지분 " + eok(m.equity.won) +
      "억원, LTV " + F.fx(m.ltv * 100) + "%, DSCR " +
      (m.dscr === null ? "―" : F.fx(m.dscr, 2)) + "배, 차환 여유 " +
      (m.refi.ok ? F.bp(m.refi.headroomBp) : "―") + ".";
  }

  // ── 판형 ────────────────────────────────────────────────────────────────
  // 기둥의 눈금은 기준 가치 100 이고 천장은 130 이다. 타워의 지붕은 값 100 에
  // 맞춰 서고, 그 위 30 은 매각가가 올라설 수 있는 하늘이다.
  var LAYOUT = {
    wide: {
      w: 880, h: 552, topY: 52, groundY: 492,
      tower: { x: 84, width: 272, wall: 7, winPad: 7, winTop: 4 },
      spine: { x: 442, floorTicks: [0, 5, 10, 15, 20], valueTicks: [0, 50, 100] },
      column: { x: 566, width: 118 },
      labelX: 698, ruleLabelX: 556, ground: { x0: 40, x1: 856, depth: 17 },
      headY: 32, annotY: 528, verbose: true, minLabel: 11, kMax: 1.6
    },
    compact: {
      w: 430, h: 470, topY: 44, groundY: 410,
      tower: { x: 26, width: 148, wall: 5, winPad: 4, winTop: 3 },
      spine: { x: 214, floorTicks: [0, 10, 20], valueTicks: [0, 100] },
      column: { x: 268, width: 64 },
      labelX: 340, ruleLabelX: 0, ground: { x0: 14, x1: 416, depth: 12 },
      headY: 28, annotY: 0, verbose: false, minLabel: 12, kMax: 1.15
    }
  };

  function layoutOf(opts) {
    return (opts && opts.compact) ? LAYOUT.compact : LAYOUT.wide;
  }

  function plateLabelScale(renderedWidthPx, opts) {
    var L = layoutOf(opts);
    return hero.labelScale(renderedWidthPx, L.w, L.minLabel, L.kMax);
  }

  /** 값(0~130) → y. 기둥 전체가 눈금이고 기준 가치 100 이 타워의 지붕이다. */
  function scaleOf(L) {
    var H = L.groundY - L.topY;
    return function (v) {
      return r4(L.groundY - (v / COLUMN_TOTAL) * H);
    };
  }

  function roofYOf(L) {
    return scaleOf(L)(BASE_INDEX);
  }

  function spinePart(m, L) {
    var S = L.spine;
    var y = scaleOf(L);
    var roofY = roofYOf(L);
    var floorSpan = L.groundY - roofY;
    var body = tag("line", {
      x1: S.x, x2: S.x, y1: L.topY, y2: L.groundY, class: "spine"
    });
    S.floorTicks.forEach(function (f) {
      var fy = r4(L.groundY - (f / m.tower.floors) * floorSpan);
      body += tag("line", { x1: S.x - 7, x2: S.x, y1: fy, y2: fy, class: "tick" });
      body += text(S.x - 11, fy + 3.5, String(f),
                   { class: "lab lab-num", "text-anchor": "end" });
    });
    S.valueTicks.forEach(function (v) {
      var vy = y(v);
      body += tag("line", { x1: S.x, x2: S.x + 7, y1: vy, y2: vy, class: "tick" });
      body += text(S.x + 11, vy + 3.5, String(v), { class: "lab lab-num" });
    });
    body += text(S.x - 11, r4(L.topY - 12), "층",
                 { class: "lab", "text-anchor": "end" });
    body += text(S.x + 11, r4(L.topY - 12), "가치", { class: "lab" });
    return tag("g", { class: "spine-g" }, body);
  }

  function rulePart(m, L, y) {
    var box = L.column;
    var x0 = box.x - 10, x1 = box.x + box.width + 10;
    var body = "";

    function rule(v, cls, label, broken) {
      var ry = y(Math.min(v, COLUMN_TOTAL - 3));
      body += tag("line", {
        x1: x0, x2: x1, y1: ry, y2: ry, class: cls
      });
      if (broken) {
        // 파단선 — 값이 판형을 넘었다는 도면의 표기다. 숫자는 라벨이 그대로 싣는다.
        body += tag("path", {
          d: "M" + r4(x1 - 26) + " " + r4(ry - 5) + " l6 -4 l6 8 l6 -8 l6 4",
          class: "break-mark"
        });
      }
      if (L.verbose && label) {
        body += text(L.ruleLabelX, ry - 4, label,
                     { class: "lab lab-rule2", "text-anchor": "end" });
      }
    }

    if (m.refi.ok) {
      var limitIdx = m.refi.ltvLimitWon * m.index;
      rule(limitIdx, "refi-limit" + (m.refi.ltvPass ? "" : " is-alert"),
           "차환 한계선 " + F.fx(limitIdx), limitIdx > COLUMN_TOTAL - 3);
    }
    if (m.hold.ok) {
      var exitIdx = m.hold.exitValueWon * m.index;
      rule(exitIdx, "exit-rule",
           m.base.holdYears + "년 뒤 매각가 " + F.fx(exitIdx) + " · 가정",
           exitIdx > COLUMN_TOTAL - 3);
    }
    return tag("g", { class: "rules-g" }, body);
  }

  function columnPart(m, L, y) {
    var box = {
      x: L.column.x, y: L.topY, width: L.column.width,
      height: L.groundY - L.topY, total: COLUMN_TOTAL
    };
    var body = charts.strataColumn(m.bands, box);
    // 자산이 부채보다 낮으면 그 차이만큼을 따로 그린다 — 물이 덮은 빈자리다.
    if (m.equity.submerged) {
      var topY = y(m.water.level), botY = y(m.water.valueTop);
      body += tag("rect", {
        x: box.x, y: topY, width: box.width, height: r4(botY - topY),
        class: "over-debt"
      });
    }
    // 테두리는 **기준 가치까지만** 두른다. 130 까지 두르면 자산 위의 빈 상자가
    // 또 하나의 지층처럼 읽힌다 — 그 위는 눈금일 뿐 자산이 들어설 자리가 아니다.
    var refY = y(BASE_INDEX);
    body += tag("rect", {
      x: box.x, y: refY, width: box.width, height: r4(L.groundY - refY),
      class: "column-frame"
    });
    body += tag("line", {
      x1: box.x - 10, x2: box.x + box.width + 10, y1: refY, y2: refY,
      class: "base-rule"
    });
    return tag("g", { class: "column-g" }, body);
  }

  function columnLabels(m, L, y) {
    var right = L.column.x + L.column.width;
    var laid = charts.strataLayout(m.bands, {
      x: L.column.x, y: L.topY, width: L.column.width,
      height: L.groundY - L.topY, total: COLUMN_TOTAL
    });
    var vals = { senior: m.loan.won, equity: m.equity.won };
    var out = "";
    var last = -Infinity;
    laid.filter(function (b) {
      return !(b.height < 0.5 && b.key === "equity");   // 잠긴 지분은 라벨이 없다
    }).sort(function (a, b) {
      return (a.y + a.height / 2) - (b.y + b.height / 2);
    }).forEach(function (b) {
      var cy = r4(b.y + b.height / 2);
      var ly = r4(Math.max(cy, last + 30));
      last = ly;
      out += tag("line", {
        x1: r4(right + 2), x2: r4(L.labelX - 6), y1: cy, y2: ly,
        class: "leader leader-" + b.key
      });
      out += text(L.labelX, ly - 1, b.label, { class: "lab" });
      out += text(L.labelX, ly + 15, eok(vals[b.key]) + "억원",
                  { class: "lab lab-num" });
    });
    if (m.equity.submerged) {
      var wy = y(m.water.level);
      out += text(L.labelX, r4(wy - 6), "부채 초과 " + eok(m.loan.won - m.value.won) +
                  "억원", { class: "lab lab-over" });
    }
    return out;
  }

  function ariaOf(m) {
    return m.base.name + " 계측기 — " + lines(m).join(" ");
  }

  function render(m, opts) {
    var L = layoutOf(opts);
    var y = scaleOf(L);
    var inner = hero.defs("ch2-");
    inner += hero.groundPart(L, "ch2-");

    if (!m.ok || !m.bands.length) {
      inner += text(L.tower.x, r4(L.groundY / 2), "판독 불가 — 아래 사유를 보라",
                    { class: "lab lab-over" });
      return tag("svg", {
        viewBox: "0 0 " + L.w + " " + L.h, role: "img",
        "aria-label": ariaOf(m), class: "plate-svg ch-fig gauge-plate",
        preserveAspectRatio: "xMidYMid meet"
      }, inner);
    }

    // 타워의 지붕은 값 100 에 선다 — 서장과 같은 등가(20층 = 기준 가치)다.
    inner += hero.towerPart(m, {
      topY: roofYOf(L), groundY: L.groundY, tower: L.tower
    });
    inner += spinePart(m, L);
    inner += columnPart(m, L, y);
    inner += rulePart(m, L, y);

    // 하나의 수면이 두 층위를 가로지른다 — 서장의 그 선이 여기서 움직인다.
    inner += charts.waterline(m.water.level, {
      x0: L.tower.x, x1: L.column.x + L.column.width + 6,
      y: L.topY, height: L.groundY - L.topY, total: COLUMN_TOTAL,
      waves: L.verbose ? 14 : 8
    });

    inner += columnLabels(m, L, y);
    inner += text(L.tower.x, L.headY,
                  "물리 층위 · 꺼진 창 " + m.tower.dark + " / " + m.tower.cells,
                  { class: "lab" });
    inner += text(L.column.x, L.headY, "자본 층위 · 기준 가치 100",
                  { class: "lab" });
    if (L.verbose) {
      inner += text(L.tower.x, L.annotY,
                    "공실률 " + F.fx(m.knobs.vacancy * 100, 1) + "% · 금리 " +
                    F.pct(m.loanRate) + " · 매각 cap " + F.pct(m.exitCap),
                    { class: "lab" });
      inner += text(L.column.x, L.annotY,
                    "수면 " + F.fx(m.water.level) + " · 자산 " +
                    F.fx(m.water.valueTop) + " · LTV " + F.fx(m.ltv * 100) + "%",
                    { class: "lab" });
    }

    return tag("svg", {
      viewBox: "0 0 " + L.w + " " + L.h,
      role: "img", "aria-label": ariaOf(m),
      class: "plate-svg ch-fig gauge-plate" + (L.verbose ? "" : " is-compact") +
        (m.equity.submerged ? " is-drowned" : ""),
      preserveAspectRatio: "xMidYMid meet"
    }, inner);
  }

  function bannerHtml(m) {
    return m.banners.map(function (b) {
      return '<p class="rig-banner is-' + esc(b.kind) + '"><b>' + esc(b.head) +
        "</b> " + esc(b.text) + "</p>";
    }).join("");
  }

  function readingsHtml(m) {
    return '<dl class="g-rows rig-rows">' + readings(m).map(function (r) {
      return '<div class="g-row' + (r.alert ? " is-alert" : "") + '">' +
        "<dt>" + esc(r.k) + '<span class="row-note">' + esc(r.note || "") +
        "</span></dt>" +
        '<dd><b class="num">' + esc(r.v) + "</b>" +
        (r.u ? '<span class="unit">' + esc(r.u) + "</span>" : "") + "</dd></div>";
    }).join("") + "</dl>";
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  function mount(doc, data) {
    doc = doc || document;
    data = data || {};
    var plateEl = doc.getElementById("ch2-plate");
    var knobsEl = doc.getElementById("ch2-knobs");
    var readEl = doc.getElementById("ch2-readings");
    var bannerEl = doc.getElementById("ch2-banners");
    var lineEl = doc.getElementById("ch2-reading");
    var liveEl = doc.getElementById("ch2-live");
    var subjEl = doc.getElementById("ch2-subject");
    var specEl = doc.getElementById("ch2-spec");
    if (!plateEl || !knobsEl) return null;

    var market = data.market, uw = data.underwriting;
    var subjects = [];
    Object.keys((market && market.regions) || {}).forEach(function (n) {
      subjects.push(regionBase(market, uw, n));
    });
    // 승격된 동이 있으면 계측 대상 목록에 함께 오른다 — 지금은 비어 있지만
    // 대장이 열리는 날 이 목록이 저절로 길어진다(재빌드만으로).
    ((uw && uw.buildings) || []).forEach(function (row) {
      if (row.underwriting) subjects.push(buildingBase(row));
    });
    if (!subjects.length) {
      plateEl.innerHTML = '<p class="fail">계측 대상을 만들지 못했다 — ' +
        'out/market.json 이 실리지 않았다.</p>';
      return null;
    }

    var base = subjects[0];
    var knobs = defaultKnobs(base);
    var wide = typeof matchMedia === "function"
      ? matchMedia(hero.WIDE_QUERY) : null;
    var liveTimer = null;

    function isCompact() { return !(wide && wide.matches); }

    function paintSubjects() {
      if (!subjEl) return;
      subjEl.innerHTML = subjects.map(function (s) {
        var on = s.key === base.key;
        return '<button type="button" role="tab" id="ch2-tab-' + esc(s.key) + '"' +
          ' data-subject="' + esc(s.key) + '" aria-selected="' + (on ? "true" : "false") +
          '" aria-controls="ch2-plate" tabindex="' + (on ? "0" : "-1") +
          '" class="r-tab' + (on ? " on" : "") + '">' + esc(s.name) + "</button>";
      }).join("");
    }

    function paintKnobs() {
      knobsEl.innerHTML = KNOBS.map(function (s) {
        return sliderRow(s, knobs[s.key], base);
      }).join("");
    }

    function fitLabels() {
      var svg = plateEl.querySelector("svg.gauge-plate");
      if (!svg) return;
      svg.style.setProperty("--fig-k", String(plateLabelScale(
        svg.getBoundingClientRect().width, { compact: isCompact() })));
    }

    function paint(announce) {
      var m = evaluate(base, knobs);
      plateEl.innerHTML = render(m, { compact: isCompact() });
      if (readEl) readEl.innerHTML = readingsHtml(m);
      if (bannerEl) bannerEl.innerHTML = bannerHtml(m);
      if (lineEl) {
        lineEl.innerHTML = lines(m).map(function (s) {
          return "<li>" + esc(s) + "</li>";
        }).join("");
      }
      fitLabels();
      if (liveEl && announce) {
        // 낭독기에 매 프레임을 읽히지 않는다 — 손을 멈춘 뒤 한 번만 말한다.
        if (liveTimer) clearTimeout(liveTimer);
        liveTimer = setTimeout(function () { liveEl.textContent = liveText(m); }, 450);
      }
      return m;
    }

    function paintSpec() {
      if (!specEl) return;
      specEl.innerHTML =
        "<div><dt>계측 대상</dt><dd>" + esc(base.name) + "</dd></div>" +
        "<div><dt>연면적</dt><dd>" + F.group(base.gfa.toFixed(0)) + "㎡" +
        (base.gfaIsSpec ? " · 눈금" : " · 대장 실측") + "</dd></div>" +
        "<div><dt>진입 cap</dt><dd>" + F.pct(base.cap) + " · R-ONE " +
        esc(base.quarter || "―") + "</dd></div>" +
        "<div><dt>기준 금리</dt><dd>" + F.pct(base.loanRate) + " · ECOS</dd></div>";
    }

    knobsEl.addEventListener("input", function (ev) {
      var el = ev.target;
      if (!el || el.type !== "range") return;
      var host = el.closest ? el.closest("[data-knob]") : null;
      var key = host && host.getAttribute("data-knob");
      var spec = KNOB_BY_KEY[key];
      if (!spec) return;
      knobs[key] = Number(el.value);
      knobs = clampKnobs(knobs, base);
      el.setAttribute("aria-valuetext", ariaValueText(spec, knobs[key], base));
      var out = host.querySelector("output");
      if (out) {
        out.innerHTML = esc(knobResult(spec, knobs[key], base)) +
          (spec.kind === "delta"
            ? '<span class="knob-delta">' + esc(knobDisplay(spec, knobs[key], base)) +
              "</span>"
            : "");
      }
      paint(true);
    });

    if (subjEl) {
      subjEl.addEventListener("click", function (ev) {
        var btn = ev.target.closest ? ev.target.closest("button[role=tab]") : null;
        if (!btn) return;
        var key = btn.getAttribute("data-subject");
        var next = subjects.filter(function (s) { return s.key === key; })[0];
        if (!next || next.key === base.key) return;
        base = next;
        knobs = defaultKnobs(base);
        paintSubjects();
        paintKnobs();
        paintSpec();
        paint(true);
        var on = subjEl.querySelector('[aria-selected="true"]');
        if (on) on.focus();
      });
    }
    var resetBtn = doc.getElementById("ch2-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        knobs = defaultKnobs(base);
        paintKnobs();
        paint(true);
      });
    }
    if (wide && wide.addEventListener) {
      wide.addEventListener("change", function () { paint(false); });
    }
    if (typeof window !== "undefined" && window.addEventListener) {
      var pending = false;
      window.addEventListener("resize", function () {
        if (pending) return;
        pending = true;
        var raf = window.requestAnimationFrame ||
          function (fn) { return setTimeout(fn, 16); };
        raf(function () { pending = false; fitLabels(); });
      });
    }

    paintSubjects();
    paintKnobs();
    paintSpec();
    paint(false);
    return { evaluate: function () { return evaluate(base, knobs); }, subjects: subjects };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var plate = document.getElementById("ch2-plate");
    if (!plate) return;
    try {
      mount(document, {
        market: window.__DATA_MARKET,
        underwriting: window.__DATA_UNDERWRITING
      });
    } catch (err) {
      plate.innerHTML = '<p class="fail">Ⅱ장을 그리지 못했다 — ' +
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
    SPEC: SPEC,
    KNOBS: KNOBS,
    // 러너는 함수만 부를 수 있다 — 상수도 문 하나를 통해 나간다.
    knobSpecs: function () { return KNOBS; },
    spec: function () { return SPEC; },
    COLUMN_TOTAL: COLUMN_TOTAL,
    LAYOUT: LAYOUT,
    round6: round6,
    regionBase: regionBase,
    buildingBase: buildingBase,
    defaultKnobs: defaultKnobs,
    clampKnobs: clampKnobs,
    knobDisplay: knobDisplay,
    knobResult: knobResult,
    ariaValueText: ariaValueText,
    restFraction: restFraction,
    sliderRow: sliderRow,
    evaluate: evaluate,
    readings: readings,
    lines: lines,
    liveText: liveText,
    render: render,
    plateLabelScale: plateLabelScale,
    mount: mount
  };
});
