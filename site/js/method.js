/**
 * 방법론 — 잘 맞는 척하지 않는다.
 *
 * 앞의 네 장이 도면이었다면 여기는 **표제란이 지면 전체로 커진 자리**다. 도면
 * 시트의 오른쪽 아래 작은 칸에 적히던 것 — 무엇을 그렸고, 어떤 축척이며, 무엇을
 * 기준으로 했고, 어디까지가 확인된 것인가 — 를 여섯 개의 필드로 펼친다.
 *
 * ── 이 장이 스스로 지키는 세 규약 ──
 *   ① **인용한다.** 원장(`DATA_MANIFEST`)의 관측월·수집일·단위·캐시 정책,
 *      엔진이 스스로 적어 둔 주석(`errors_note`·`implausible_refi_note`),
 *      게이트가 남긴 사유는 전부 **원문 그대로** 온다. 요약하면 그 순간
 *      요약한 사람의 판단이 데이터인 척하기 시작한다.
 *   ② **다시 계산한다.** 유효임대료 사다리의 마지막 칸은 지면이 직접 곱해서
 *      낸 수이고, 그 수가 `out/market.json` 과 다르면 그림을 그리지 않고
 *      멈춘다(`RangeError`). 지면이 제 숫자를 따로 들고 있으면 언젠가
 *      데이터와 갈라지는데, 그 어긋남은 아무도 못 본 채로 오래 산다.
 *   ③ **빈칸에는 사선을 긋는다.** 제도 도면은 의도된 공백에 사선을 그어
 *      미기입과 구분한다. 0건인 점검 항목이 그렇다 — 사선과 함께
 *      "현재 0건 — 검증됨으로 읽지 말 것"이 반드시 따라붙는다. 이 문장은 이
 *      작품이 지어낸 것이 아니라 엔진이 `implausible_refi_note` 에 먼저
 *      적어 둔 말이다.
 *
 * 매칭 한계는 새 그림을 그리지 않는다. Ⅰ장의 배타 사다리를 **같은 함수로**
 * 다시 부른다 — 두 장이 서로 다른 그림으로 같은 사실을 말하기 시작하면 그중
 * 하나는 반드시 틀린다.
 *
 * 의존은 charts·hero(서식)·chapter1(사다리)·engine(물리 게이트 경계) 넷이고 로드
 * 순서가 계약이다. 엔진은 계산하러 부르는 것이 아니라 **게이트 범위를 인용하러**
 * 부른다 — 범위를 지면에 글자로 박아 두면 엔진이 경계를 옮기는 날 지면만 옛
 * 범위를 말한다.
 */

;(function (root, factory) {
  "use strict";
  var isNode = typeof module !== "undefined" && module.exports;
  var scope = typeof window !== "undefined" ? window : (root || {});
  var charts = isNode ? require("./charts.js") : scope.CheungwiCharts;
  var hero = isNode ? require("./hero.js") : scope.CheungwiHero;
  var ch1 = isNode ? require("./chapter1.js") : scope.CheungwiChapter1;
  var eng = isNode ? require("./engine.js") : scope.CheungwiEngine;
  var api = factory(charts, hero, ch1, eng);
  if (isNode) module.exports = api;
  if (typeof window !== "undefined") window.CheungwiMethod = api;
  else if (root) root.CheungwiMethod = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (charts, hero, ch1, eng) {
  "use strict";

  var esc = charts.esc;
  var F = hero.fmt;

  /**
   * 0건인 목록에 반드시 따라붙는 문장.
   *
   * 지어낸 말이 아니다 — `underwriting.implausible_refi_note` 의 마지막 문장이
   * "이 값이 늘 빈 리스트인 것을 '검증됨'으로 읽지 말 것"이고, 그 요구를 네
   * 목록 전부에 적용한 것이다.
   */
  var BLANK = "현재 0건 — 검증됨으로 읽지 말 것.";

  /**
   * 파킹된 한계. 출처는 `docs/plan2-3-handoff.md` 말미의 두 목록(표기 정정 ·
   * 엔진 최종 리뷰)이고, 여기 옮겨 적은 것은 **읽는 사람이 문서를 열지 않아도
   * 알아야 할 것들**이다. 고쳐지면 그 문서와 이 배열에서 함께 지운다.
   */
  var PARKED_ITEMS = [
    { where: "docs/ledger-unlock-checklist.md · buildings.py",
      what: "필지 공유 시드를 「8동」이라 적은 곳이 남아 있다 — 실제는 7동이다" +
        "(IFC 3 · 파크원 2 · 마제스타 2)." },
    { where: "스펙 §4",
      what: "시드를 「50동」이라 적은 문장이 남아 있다. 실제 시드는 55동이다." },
    { where: "src/analysis/build_out.py",
      what: "수익률 계열이 빈 입력일 때 진단이 TypeError 로 강등된다. 빌드는 " +
        "멈추므로 오답이 나가지는 않지만, 멈춘 이유가 실제 이유와 다르게 적힌다." },
    { where: "market.sub_regions.* · seoul_reference",
      what: "권역 3종에만 건 분기 정렬 단언이 하위 상권·서울 계열에는 없다 — " +
        "임대료·공실·수익률이 서로 다른 분기에서 한 줄에 실릴 수 있다." },
    { where: "src/analysis/pf.py:54",
      what: "D4 대안 금액 3.3495억의 설명이 「마지막 달 인출 23.33억」 으로 " +
        "잘못 귀속돼 있다(실제는 마지막 달 잔액 669.9억의 한 달 이자). 상수 자체는 정확하다." },
    { where: "Ⅱ장 계측기 · 출력 낭독",
      what: "판독값 `<output>` 셋이 낭독기에서 겹쳐 읽힌다. 실험실은 " +
        "aria-live 를 off 로 박아 같은 실수를 피했고, 고칠 때 참고할 형태가 거기 있다." },
    { where: "tests/",
      what: "`open()` 인코딩을 명시하지 않은 자리가 일곱 곳 남아 있다." }
  ];

  // ── ① 원장 — 여섯 원천 ──────────────────────────────────────────────────
  /**
   * 원장의 각 원천을 표 한 줄로.
   *
   * `source_count` 와 실린 수가 어긋나면 다섯 줄만 조용히 그리지 않는다. 원장이
   * 스스로를 잘못 세고 있다는 것은, 이 페이지가 인용할 근거가 무너졌다는 뜻이다.
   */
  function manifestRows(manifest) {
    var sources = manifest && manifest.sources;
    if (!manifest || !Array.isArray(sources) || !sources.length) {
      throw new TypeError(
        "원장을 읽지 못했다 — data/DATA_MANIFEST.json 이 실리지 않았다");
    }
    var declared = manifest.source_count;
    if (typeof declared === "number" && declared !== sources.length) {
      throw new RangeError(
        "원장이 스스로를 잘못 센다: source_count " + declared + " ≠ 실린 원천 " +
        sources.length + "건");
    }
    return sources.map(function (s) {
      var units = s.units === undefined || s.units === null ? "-" : String(s.units);
      return {
        key: s.key,
        dataset: s.dataset,
        institution: s.institution,
        observed: s.observed_through,
        collected: s.collected_at,
        rows: s.rows,
        timeAxis: s.time_axis === true,
        units: units,
        // 단위가 없는 원천(시드)은 빈칸이 아니라 줄표다 — 빈칸은 누락으로 읽힌다.
        unitsText: units === "-" || units === "" ? "―" : units,
        coverage: s.coverage || "",
        cache: s.cache || ""
      };
    });
  }

  function manifestTable(manifest) {
    var rows = manifestRows(manifest);
    var head = ["원천", "기관", "관측월", "수집일", "행", "단위"];
    var thead = "<tr>" + head.map(function (h, i) {
      return '<th scope="col"' + (i === 4 ? ' class="col-num"' : "") + ">" +
        esc(h) + "</th>";
    }).join("") + "</tr>";
    var body = rows.map(function (r) {
      // 캐시 정책은 각주가 아니라 **행의 일부**다. "새 분기를 영원히 못 받는다"는
      // 사실이 접힌 곳에 있으면 그 원천의 한계가 화면에서 사라진다.
      return '<tr class="src-row">' +
        '<th scope="row">' + esc(r.dataset) +
        '<span class="src-key">' + esc(r.key) +
        (r.timeAxis ? " · 시간축" : "") + "</span></th>" +
        "<td>" + esc(r.institution) + "</td>" +
        '<td class="num">' + esc(r.observed) + "</td>" +
        '<td class="num">' + esc(r.collected) + "</td>" +
        '<td class="num">' + esc(F.group(String(r.rows))) + "</td>" +
        '<td class="unit-cell">' + esc(r.unitsText) + "</td></tr>" +
        '<tr class="src-note"><td colspan="6"><b>캐시</b> ' + esc(r.cache) +
        "<span>" + esc(r.coverage) + "</span></td></tr>";
    }).join("");
    return '<div class="table-wrap" role="region" ' +
      'aria-labelledby="method-manifest-h" tabindex="0">' +
      '<table class="src-table"><caption>여섯 원천의 관측월·수집일·단위와 캐시 ' +
      '정책이다. 단위는 원장의 <b>units</b> 가 단일 출처다 — 천원과 백만원이 ' +
      '섞여 있는 것이 이 데이터의 사실이라 "원" 하나로 정리하지 않았다.</caption>' +
      "<thead>" + thead + "</thead><tbody>" + body + "</tbody></table></div>";
  }

  function manifestLines(manifest) {
    var rows = manifestRows(manifest);
    var observed = [];
    rows.forEach(function (r) {
      if (observed.indexOf(r.observed) < 0) observed.push(r.observed);
    });
    observed.sort();
    var stale = rows.filter(function (r) {
      return /무효화가 없다/.test(r.cache);
    }).map(function (r) { return r.key; });
    // 수는 원장에서 온다. 문장에 손으로 박으면 다음 수집에서 조용히 어긋난다.
    var trades = rows.filter(function (r) { return r.key === "trades"; })[0];
    return [
      "원천은 " + rows.length + "종이고 관측월은 하나가 아니다 — " +
        observed.join(" · ") + " 가 한 화면에 함께 있다. 수집일(" +
        rows[0].collected + ")은 관측월이 아니라 내려받은 날이다. " +
        "원장의 데이터 기준월 " + (manifest.data_cutoff || "―") +
        " 은 그 가운데 가장 이른 축을 따른 것이지 전 원천의 공통 기준월이 아니다.",
      "캐시 무효화가 없는 원천이 " + stale.length + "종 있다(" + stale.join(" · ") +
        "). 새 분기가 나와도 다시 받지 않으므로, 여기 실린 분기가 곧 데이터층의 " +
        "한계다 — 갱신하려면 data/raw/ 아래 해당 폴더를 지우고 다시 수집해야 한다.",
      "행 수는 수집한 원시 행이고 분석에 쓴 행이 아니다" +
        (trades ? " — 실거래 " + F.group(String(trades.rows)) + "행 가운데 해제 " +
          "거래는 가격 집계에서 빠졌고, 하위 상권 한 곳은 계열이 짧아 행째 " +
          "제외됐다(아래 점검표)." : ".")
    ];
  }

  // ── ② 추정 — 관측에서 추정까지의 사다리 ─────────────────────────────────
  var KIND_OF = { 관측: "obs", 가정: "assume", 추정: "est" };

  /**
   * 유효임대료 물리 게이트의 범위 문장.
   *
   * 두 경계는 엔진이 단일 출처로 들고 있고(`RENT_MIN_WON_M2_MO`·
   * `RENT_MAX_WON_M2_MO`, 파이썬 `src/analysis/effective_rent.py` 의 미러),
   * 엔진 스스로 "화면에 범위를 적을 때 여기서 읽는다"고 내보내 둔 값이다.
   * 지면이 같은 수를 따로 적으면 경계를 옮기는 날 지면만 옛 범위를 말한다.
   */
  function gateRangeText() {
    var lo = eng.RENT_MIN_WON_M2_MO;
    var hi = eng.RENT_MAX_WON_M2_MO;
    if (!(typeof lo === "number" && typeof hi === "number" && lo < hi)) {
      throw new TypeError(
        "엔진에서 임대료 게이트 경계를 읽지 못했다 — 범위를 지어낼 수 없다");
    }
    return F.won(lo) + "~" + F.won(hi) + "원/㎡·월";
  }

  /**
   * 유효임대료가 만들어지는 네 칸. 마지막 칸까지 **지면이 직접 계산**한다.
   *
   * 계산 결과가 `out/market.json` 의 값과 다르면 그림을 그리지 않고 멈춘다.
   * 여기서 조용히 데이터 쪽 수를 보여 주면, 지면의 산술이 틀렸다는 사실이
   * 화면에서 영영 사라진다.
   */
  function estimationSteps(market, regionName) {
    var reg = market && market.regions && market.regions[regionName];
    if (!reg) {
      throw new TypeError("권역이 없다: " + String(regionName) +
                          " — out/market.json 의 regions 를 확인하라");
    }
    var meta = reg.rent_free_meta || {};
    var computed = reg.nominal_rent_won_m2_mo * (12 - reg.rent_free_mo) / 12;
    var stored = reg.effective_rent_won_m2_mo;
    if (Math.abs(computed - stored) > Math.abs(stored) * 1e-9) {
      throw new RangeError(
        "지면의 산술과 데이터가 어긋난다: 계산 " + computed + " ≠ 산출 " + stored);
    }
    return [
      {
        kind: "관측", label: "명목임대료", value: reg.nominal_rent_won_m2_mo,
        unit: "원/㎡·월", text: F.won(reg.nominal_rent_won_m2_mo) + " 원/㎡·월",
        note: "한국부동산원 R-ONE 상업용부동산 임대동향조사 " +
          reg.latest_quarter + " 의 " + regionName + " 권역 평균이다. " +
          "원값의 단위가 천원/㎡·월이라 1000 을 곱해 원으로 맞췄다.",
        source: "", caveat: ""
      },
      {
        kind: "가정", label: "렌트프리", value: reg.rent_free_mo,
        unit: "개월/년", text: F.fx(reg.rent_free_mo, 1) + " 개월/년",
        note: "권역 대표값 한 숫자로 개별 계약의 렌트프리를 대신했다. 관측치가 " +
          "아니라 조정 가능한 가정이고, 리츠 실적 임대수익 앵커에 맞추는 " +
          "캘리브레이션은 아직 하지 않았다.",
        source: meta.source || "", caveat: meta.caveat || ""
      },
      {
        kind: "추정", label: "유효임대료", value: computed,
        unit: "원/㎡·월", text: F.won(computed) + " 원/㎡·월",
        note: "명목 × (12 − 렌트프리) ÷ 12. 보증금 운용수익은 여기에 넣지 " +
          "않았다 — 임대료와 시간 구조가 달라 현금흐름 쪽에서 따로 다룬다. " +
          "결과는 " + gateRangeText() + " 물리 게이트를 통과해야 한다.",
        source: "", caveat: ""
      },
      {
        kind: "가정", label: "건물 보정", value: null,
        unit: "계수", text: "연식 × 규모 × 역세권",
        note: "건물 한 동의 임대료는 권역 지표에 세 계수를 곱으로 겹쳐 만든다. " +
          "특성 간 상관을 무시했으므로 셋이 함께 좋은 건물은 프리미엄이 " +
          "과대평가된다. 역까지 거리를 담은 데이터층이 없어 역세권 계수 1.0 은 " +
          "'역세권 아님'이 아니라 판단 유보다.",
        source: "", caveat: ""
      }
    ];
  }

  function estimationHtml(market, regionName) {
    var steps = estimationSteps(market, regionName);
    var body = steps.map(function (s, i) {
      return '<li class="rung is-' + KIND_OF[s.kind] + '">' +
        '<span class="rung-kind">' + esc(s.kind) + "</span>" +
        '<div class="rung-body"><h4>' + esc(s.label) +
        '<span class="rung-val num">' + esc(s.text) + "</span></h4>" +
        "<p>" + esc(s.note) + "</p>" +
        (s.source
          ? '<p class="rung-src"><b>가정의 출처</b> ' + esc(s.source) + "</p>"
          : "") +
        (s.caveat ? '<p class="rung-caveat">' + esc(s.caveat) + "</p>" : "") +
        "</div></li>";
    }).join("");
    return '<ol class="rungs" aria-label="' + esc(regionName) +
      ' 유효임대료 추정의 네 칸">' + body + "</ol>";
  }

  // ── ③ 매칭 — 배타 사다리 재게시 ─────────────────────────────────────────
  function matchingModel(trades) {
    var m = trades && trades.matching;
    var lad = m && m.ladder_exclusive;
    if (!lad) {
      throw new TypeError("매칭 사다리가 없다 — out/trades_analysis.json 을 확인하라");
    }
    return {
      exact: lad.exact,
      resolvedOnly: lad.resolved_only,
      ambiguous: lad.ambiguous,
      total: lad.sum,
      matched: lad.n_matched,
      exactLive: m.exact ? m.exact.n_live : null,
      exactCanceled: m.exact ? m.exact.n_canceled_excluded : null,
      nesting: m.nesting || ""
    };
  }

  /** Ⅰ장의 사다리를 **그 함수 그대로** 다시 그린다. 새 그림을 만들지 않는다. */
  function matchingPlate(trades, opts) {
    return ch1.ladderPlate(ch1.tradesModel(trades), opts);
  }

  /**
   * 시드가 몇 동인가. 원장의 `seed_buildings` 행 수가 단일 출처다.
   *
   * 매칭이 후보를 고르는 모집단이 곧 이 시드 목록이라, 이 수가 바뀌면 매칭
   * 문장의 뜻도 바뀐다. 지면에 "55동"을 박아 두면 시드가 늘어난 날 문장만
   * 옛 목록을 가리킨다 — 그때 틀린 것은 데이터가 아니라 설명이다.
   */
  function seedCount(manifest) {
    var seed = manifestRows(manifest).filter(function (r) {
      return r.key === "seed_buildings";
    })[0];
    if (!seed || !(seed.rows > 0)) {
      throw new TypeError(
        "원장에 시드 원천(seed_buildings)이 없다 — 시드 동수를 지어낼 수 없다");
    }
    return seed.rows;
  }

  function matchingLines(trades, manifest) {
    var m = matchingModel(trades);
    var seed = seedCount(manifest);
    return [
      "필지까지 확정된 것은 " + m.exact + "행뿐이다. 나머지 " +
        F.group(String(m.resolvedOnly)) + "행은 '시드 " + seed +
        "동 목록 안에서 후보가 " +
        "유일'할 뿐이고, 마스킹된 지번이라 같은 법정동의 비-시드 건물과 " +
        "구분되지 않는다 — 확정으로 읽으면 안 된다.",
      "exact 는 resolved 의 부분집합이라 원래 수를 그대로 더하면 매칭 " +
        F.group(String(m.matched)) + "행을 넘는다. 그래서 화면에 세우는 것은 " +
        "겹치지 않는 세 칸(" + m.exact + " · " + F.group(String(m.resolvedOnly)) +
        " · " + F.group(String(m.ambiguous)) + ")이고 그 합이 매칭 수와 같다.",
      "사다리의 " + m.exact + "행과 Ⅰ장 산점의 점 " + m.exactLive +
        "개는 다른 수다 — 해제(canceled) 거래 " + m.exactCanceled +
        "건이 사다리에는 남고 가격 집계에서는 빠졌기 때문이다. 해제 거래도 그 " +
        "시점의 호가 정보라 데이터층은 지우지 않고 플래그로 보존한다.",
      "건축물대장이 열리면 이 사다리가 통째로 다시 그려진다. 지금 매칭은 " +
        "지번만으로 붙인 것이라 통매각과 구분소유를 가르지 못한다(kind 가 전부 " +
        "jibun_only 다)."
    ];
  }

  // ── ④ 점검표 — 비어 있는 목록 ───────────────────────────────────────────
  /** 네 목록의 자리와 뜻. 순서는 파이프라인이 그것들을 채우는 순서다. */
  var CHECKS = [
    {
      key: "gate_violations", label: "물리 게이트 위반",
      where: "out/market.json · gate_violations",
      of: "임대료·cap 이 물리 범위를 벗어나 값을 내지 못하고 사유만 남긴 자리",
      pick: function (d) { return (d.market || {}).gate_violations; },
      note: function () {
        return "게이트는 값을 고쳐 통과시키지 않는다 — 그 지점을 null 로 두고 " +
          "사유를 남긴다. 단위를 잘못 넣은 사고가 여기서 걸리므로, 이 목록이 " +
          "길어지면 먼저 의심할 것은 모델이 아니라 단위다.";
      }
    },
    {
      key: "errors", label: "동별 계산 정지",
      where: "out/underwriting.json · errors",
      of: "한 동의 계산이 예외로 멈춘 자리(이름과 사유가 함께 남는다)",
      pick: function (d) { return (d.underwriting || {}).errors; },
      note: function (d) { return (d.underwriting || {}).errors_note || ""; }
    },
    {
      key: "implausible_refi", label: "차환 implausible 신호",
      where: "out/underwriting.json · implausible_refi",
      of: "실무에 없는 조합이라 계산은 되지만 믿을 수 없는 차환 판정",
      pick: function (d) { return (d.underwriting || {}).implausible_refi; },
      note: function (d) { return (d.underwriting || {}).implausible_refi_note || ""; }
    },
    {
      key: "sub_regions_cap_skipped", label: "하위 상권 cap 제외",
      where: "out/market.json · sub_regions_cap_skipped",
      of: "분기 계열이 짧아 연환산 cap 을 낼 수 없어 행째 뺀 상권",
      pick: function (d) { return (d.market || {}).sub_regions_cap_skipped; },
      note: function () {
        return "짧은 계열로 합을 내면 4분의 3 짜리 cap 이 나오는데 그 값도 게이트 " +
          "안(2~12%)이라 조용히 통과한다. 그래서 benchmark 를 부르기 전에 거른다 — " +
          "이 목록은 '없는 값'이 아니라 '내지 않기로 한 값'의 기록이다.";
      }
    }
  ];

  /** 어떤 모양의 행이 와도 머리글과 본문을 만든다(목록마다 키가 다르다). */
  function rowText(row) {
    if (!row || typeof row !== "object") {
      return { head: "―", kind: "", body: String(row) };
    }
    var head = row.where || row.name || row.id || "―";
    var body = row.reason ||
      (Array.isArray(row.reasons) ? row.reasons.join(" / ") : "") ||
      "사유가 기록되지 않았다";
    return { head: String(head), kind: row.kind ? String(row.kind) : "", body: body };
  }

  function checkModel(data) {
    var d = data || {};
    return CHECKS.map(function (c) {
      var list = c.pick(d);
      var rows = Array.isArray(list) ? list : [];
      var empty = rows.length === 0;
      return {
        key: c.key, label: c.label, where: c.where, of: c.of,
        count: rows.length,
        empty: empty,
        // 0건일 때만 따라붙는다. 한 줄이라도 생기면 이 문장은 사라지고 사유가 온다.
        emptyNote: empty
          ? BLANK + " 이 목록이 비어 있는 것은 오늘 데이터의 사실이지 검증의 " +
            "결과가 아니다 — 신호가 켜지는 조건 자체가 이 조립에서 드물거나, " +
            "값이 밖에서 들어오는 순간 켜질 수 있다."
          : "",
        note: c.note(d),
        rows: rows.map(rowText),
        missing: !Array.isArray(list)
      };
    });
  }

  function checkHtml(model) {
    return '<ul class="checks">' + (model || []).map(function (c) {
      // 목록 자체가 없는 것과 목록이 비어 있는 것은 다른 사실이다. 앞의 것을
      // 0건으로 그리면, 파이프라인이 이 자리를 채우지 않았다는 사실이 사라진다.
      var body = c.missing
        ? '<p class="check-missing">이 산출물에는 목록이 아예 없다 — 0건이 ' +
          "아니라 파이프라인이 이 자리를 채우지 않았다는 뜻이다.</p>"
        : c.empty
        ? '<p class="check-blank"><span>' + esc(c.emptyNote) + "</span></p>"
        : '<ul class="check-rows">' + c.rows.map(function (r) {
          return "<li><b>" + esc(r.head) + "</b>" +
            (r.kind ? '<span class="check-kind">' + esc(r.kind) + "</span>" : "") +
            "<span>" + esc(r.body) + "</span></li>";
        }).join("") + "</ul>";
      return '<li class="check' + (c.empty && !c.missing ? " is-blank" : "") +
        (c.missing ? " is-missing" : "") + '">' +
        '<h4>' + esc(c.label) +
        // 없는 목록에 "0건" 배지를 달면 바로 아래 문단("0건이 아니라 채워지지
        // 않은 자리")과 배지가 서로 다른 말을 한다. 셀 수 없는 자리는 줄표다.
        '<span class="check-n num">' + (c.missing ? "―" : c.count + "건") +
        "</span></h4>" +
        '<p class="check-of">' + esc(c.of) +
        '<span class="check-where">' + esc(c.where) + "</span></p>" +
        body +
        (c.note ? '<p class="check-note">' + esc(c.note) + "</p>" : "") +
        "</li>";
    }).join("") + "</ul>";
  }

  // ── ⑤ 대장 — 대기 상태와 승격 경로 ──────────────────────────────────────
  /** 대장이 열린 뒤 무슨 일이 순서대로 일어나는가. `docs/ledger-unlock-checklist.md`. */
  var PROMOTION_PATH = [
    "data.go.kr 활용신청이 승인되면 건축물대장 표제부(BldRgstHubService)가 열린다.",
    "대장 XML 캐시는 무효화가 없다 — data/raw/bldrgst/ 를 지우고 다시 수집해야 " +
      "첫 응답이 스냅샷으로 얼어붙지 않는다.",
    "`python3 src/collect/trades.py --rebuild` 로 실거래 매칭을 승격시킨다. " +
      "네트워크를 쓰지 않고 캐시만으로 kind 가 jibun_only 에서 whole·partial 로 갈린다.",
    "필지를 공유하는 시드 7동(IFC 3 · 파크원 2 · 마제스타 2)의 match_method 와 " +
      "duplicate_ledger 를 눈으로 확인한다 — fallback 이면 연면적으로 고른 것이라 믿을 수 없다.",
    "`make analyze` 가 돌면 pending 행이 승격 행으로 바뀌고 연면적·NOI·추정가치가 " +
      "채워진다. 실패한 동은 사라지지 않고 계산 정지 행으로 남는다.",
    "그때 비로소 추정가치와 실거래의 오차 분포(value.error_dist)를 exact 행과 " +
      "짝지어 낼 수 있다. 지금은 지어내지 않는다."
  ];

  function ledgerModel(underwriting) {
    var rows = underwriting && underwriting.buildings;
    if (!Array.isArray(rows) || !rows.length) {
      throw new TypeError("원장에 건물이 없다 — out/underwriting.json 을 확인하라");
    }
    var counts = { pending: 0, underwritten: 0, failed: 0 };
    rows.forEach(function (row) { counts[ch1.variantOf(row)] += 1; });
    var summary = underwriting.summary || {};
    return {
      n: rows.length,
      pending: counts.pending,
      underwritten: counts.underwritten,
      failed: counts.failed,
      // 막힌 계산의 이름은 카드가 아니라 여기서 본문 크기로 한 번 더 나온다.
      blocked: ch1.blockedUnion(rows),
      status: summary.ledger_status || "",
      reason: (rows[0] && rows[0].pending_reason) || "",
      path: PROMOTION_PATH.slice()
    };
  }

  function ledgerHtml(m) {
    var steps = m.path.map(function (s, i) {
      return "<li><span class=\"step-no num\">" + (i + 1) + "</span>" +
        esc(s) + "</li>";
    }).join("");
    return '<div class="ledger-state">' +
      '<p class="ledger-count-big"><b class="num">' + m.pending + "</b> / " +
      '<span class="num">' + m.n + "</span> 동이 대장 개통 대기다" +
      (m.underwritten ? " · 승격 " + m.underwritten + "동" : "") +
      (m.failed ? " · 계산 정지 " + m.failed + "동" : "") + ".</p>" +
      (m.blocked.length
        ? '<p class="ledger-blocked">연면적과 사용승인일이 없어 막힌 계산 ' +
          m.blocked.length + "개: <b>" + esc(m.blocked.join(" · ")) +
          "</b>. 빈 자리를 권역 평균으로 메우지 않았다 — 추정과 부재를 같은 " +
          "색으로 칠하면 대장이 없다는 사실이 산출물에서 사라진다.</p>"
        : "") +
      (m.status ? '<p class="ledger-http"><b>대장 상태</b> ' + esc(m.status) +
        "</p>" : "") +
      "</div>" +
      '<h4 class="path-h">개통되면 이 순서로 승격한다</h4>' +
      '<ol class="path">' + steps + "</ol>";
  }

  // ── ⑥ 파킹된 한계 ───────────────────────────────────────────────────────
  function parkedHtml() {
    return '<ul class="parked">' + PARKED_ITEMS.map(function (it) {
      return "<li><b>" + esc(it.where) + "</b><span>" + esc(it.what) +
        "</span></li>";
    }).join("") + "</ul>" +
      '<p class="parked-src">출처: docs/plan2-3-handoff.md 말미의 파킹 목록과 ' +
      "각 계획의 최종 리뷰 트리아지. 고쳐지면 그 문서와 이 목록에서 함께 지운다. " +
      "여기 적힌 것은 아직 고쳐지지 않았다는 뜻이지, 영향이 없다는 뜻이 아니다.</p>";
  }

  // ── 표제란 ──────────────────────────────────────────────────────────────
  /**
   * 표제란의 대장 칸. 승격 수는 원장 행에서 세고, 문구는 개통 여부로 갈린다.
   *
   * "0/55 · 활용신청 승인 대기"를 글자로 박아 두면 대장이 열려 승격이 시작된
   * 날에도 표제란만 계속 기다린다 — 그리고 그 어긋남은 아무도 못 본 채로
   * 오래 산다. 한 동이라도 대기에서 벗어나면 개통으로 읽는다.
   */
  function ledgerSpecText(led) {
    var head = led.underwritten + "/" + led.n;
    if (led.pending >= led.n) return head + " · 활용신청 승인 대기";
    var rest = [];
    if (led.pending) rest.push("대기 " + led.pending + "동");
    if (led.failed) rest.push("계산 정지 " + led.failed + "동");
    return head + " 승격" + (rest.length ? " · " + rest.join(" · ") : "");
  }

  function specRows(data) {
    var d = data || {};
    var man = d.manifest || {};
    var rows = manifestRows(man);
    var lad = matchingModel(d.trades);
    var led = ledgerModel(d.underwriting);
    var observed = rows.map(function (r) { return r.observed; }).sort();
    return [
      ["도면", "방법론 · 원장과 한계의 표제란"],
      ["데이터 기준월", String(man.data_cutoff || "―").replace(/-/g, ".")],
      ["원천", rows.length + "종 · 관측월 " + observed[0] + "~" +
        observed[observed.length - 1]],
      ["원장 갱신", String(man.generated_at || "―")],
      ["매칭", "필지 확정 " + lad.exact + " / 매칭 " + F.group(String(lad.matched)) + "행"],
      ["대장", ledgerSpecText(led)],
      ["계보", "수지 → 순환 → 시차 → 층위"]
    ];
  }

  function specHtml(data) {
    return specRows(data).map(function (pair) {
      return "<div><dt>" + esc(pair[0]) + "</dt><dd>" + esc(pair[1]) +
        "</dd></div>";
    }).join("");
  }

  // ── DOM ─────────────────────────────────────────────────────────────────
  function ul(lines) {
    return lines.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
  }

  function mount(doc, data) {
    doc = doc || document;
    data = data || {};
    var host = doc.getElementById("method-manifest");
    if (!host) return null;
    var wide = typeof matchMedia === "function"
      ? matchMedia(hero.WIDE_QUERY) : null;

    function isCompact() { return !(wide && wide.matches); }

    function put(id, html) {
      var el = doc.getElementById(id);
      if (el) el.innerHTML = html;
    }

    function fitLadder() {
      var el = doc.getElementById("method-ladder");
      var svg = el && el.querySelector("svg.ch-fig");
      if (!svg) return;
      var vb = ch1.LADDER[isCompact() ? "compact" : "wide"].w;
      svg.style.setProperty("--fig-k", String(hero.labelScale(
        svg.getBoundingClientRect().width, vb,
        isCompact() ? 12 : 11, isCompact() ? 1.15 : 1.6)));
    }

    function paintLadder() {
      put("method-ladder", matchingPlate(data.trades, { compact: isCompact() }));
      fitLadder();
    }

    put("method-manifest", manifestTable(data.manifest));
    put("method-manifest-lines", ul(manifestLines(data.manifest)));
    put("method-estimate", estimationHtml(data.market, "도심"));
    put("method-matching-reading", ul(matchingLines(data.trades, data.manifest)));
    put("method-checks", checkHtml(checkModel(data)));
    put("method-ledger", ledgerHtml(ledgerModel(data.underwriting)));
    put("method-parked", parkedHtml());
    put("method-spec", specHtml(data));
    paintLadder();

    if (wide && wide.addEventListener) wide.addEventListener("change", paintLadder);
    if (typeof window !== "undefined" && window.addEventListener) {
      var pending = false;
      window.addEventListener("resize", function () {
        if (pending) return;
        pending = true;
        var raf = window.requestAnimationFrame ||
          function (fn) { return setTimeout(fn, 16); };
        raf(function () { pending = false; fitLadder(); });
      });
    }
    return { checks: checkModel(data), ledger: ledgerModel(data.underwriting) };
  }

  function boot() {
    if (typeof document === "undefined") return;
    var host = document.getElementById("method-manifest");
    if (!host) return;
    try {
      mount(document, {
        manifest: window.__DATA_MANIFEST,
        market: window.__DATA_MARKET,
        underwriting: window.__DATA_UNDERWRITING,
        trades: window.__DATA_TRADES
      });
    } catch (err) {
      host.innerHTML = '<p class="fail">방법론을 그리지 못했다 — ' +
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
    EMPTY_NOTE: function () { return BLANK; },
    PARKED: function () { return PARKED_ITEMS.slice(); },
    PROMOTION_PATH: PROMOTION_PATH,
    manifestRows: manifestRows,
    manifestTable: manifestTable,
    manifestLines: manifestLines,
    estimationSteps: estimationSteps,
    estimationHtml: estimationHtml,
    matchingModel: matchingModel,
    matchingPlate: matchingPlate,
    matchingLines: matchingLines,
    checkModel: checkModel,
    checkHtml: checkHtml,
    ledgerModel: ledgerModel,
    ledgerHtml: ledgerHtml,
    parkedHtml: parkedHtml,
    specRows: specRows,
    specHtml: specHtml,
    mount: mount
  };
});
