/**
 * 층위 언더라이팅 엔진의 자바스크립트 미러 — `src/analysis/*` 의 아홉 함수.
 *
 * 대시보드 Ⅱ장(자본의 층위)과 실험실은 슬라이더를 움직일 때마다 같은 계산을
 * 브라우저에서 다시 돌린다. 서버가 없으니 계산도 여기 있어야 하고, 여기 있는
 * 계산이 파이썬과 다르면 화면의 숫자와 `out/*.json` 의 숫자가 어긋난다.
 *
 * **파이썬이 원본이다.** 이 파일은 옮긴 것이지 다시 쓴 것이 아니다. 값이
 * 어긋나면 고칠 쪽은 언제나 이쪽이고, 그 대조를 `tests/test_parity.py` 가
 * 무작위 207조 + 골든 5종으로 매 실행 고정한다(rel 1e-9 / abs 1e-6).
 *
 * ── 미러한 아홉 함수 ──
 *   effective_rent      렌트프리 차감 유효임대료
 *   building_adjust     연식·규모·역세권 보정
 *   noi                 전용률·공실·opex → 순영업소득
 *   appraise            NOI ÷ cap (소득접근 감정가)
 *   implied             실거래 역산 cap
 *   max_loan            삼중 제약 대출가능액
 *   hold_model          보유기간 분기 현금흐름과 지분 IRR
 *   refi_test           만기 차환 판정
 *   breakeven_vacancy   손익분기 공실률
 * 내부 의존인 `irr_annual`·`require_finite` 도 함께 내보낸다(파이썬 `fin_core`).
 * `caprate.benchmark`·`value.error_dist`·`pf.pf_model` 은 슬라이더 대상이
 * 아니라 옮기지 않았다.
 *
 * ── 오류 유형 매핑 ──
 * 파이썬의 세 갈래를 자바스크립트 관례로 옮긴다.
 *
 *   ValueError          (입력이 틀렸다)        → **TypeError**
 *   RuntimeError        (단위를 의심하라)      → **RangeError**
 *   NotImplementedError (계산하지 않는다)      → **Error**, 문구가 "미구현"으로 시작
 *
 * **잡는 순서가 파이썬과 반대다.** 파이썬에서는 NotImplementedError 가
 * RuntimeError 의 하위형이라 좁은 쪽을 먼저 잡아야 하지만, 여기서는
 * RangeError·TypeError 가 Error 의 하위형이다. 그러니 부르는 쪽은
 *
 *     catch (e) {
 *       if (e instanceof RangeError) { … }   // 물리 게이트 — 단위를 의심하라
 *       else if (e instanceof TypeError) { … } // 입력 오류
 *       else { … }                            // 미구현·그 밖
 *     }
 *
 * 순서로, **RangeError·TypeError 를 Error 보다 먼저** 보아야 한다. 뒤집으면
 * 세 갈래가 한 갈래로 뭉개진다.
 *
 * ── 물리 게이트(단일 출처) ──
 * 임대료 10,000~60,000원/㎡·월 · cap 0.02~0.12 · DSCR 0~5. 파이썬은 이 상수를
 * 모듈 하나에 두고 나머지가 임포트해 쓴다. 여기서도 파일 맨 위에 한 번만 적고
 * 전부 그 이름을 부른다 — 두 벌이 되는 순간 한 벌이 어긋난다.
 *
 * ── 문구 안의 수치 표기 ──
 * `notes`·`assumptions` 는 인자를 문구에 그대로 박아 넣는다. 파이썬 `str(float)`
 * 은 정수값도 "5.0" 으로 쓰고 `f"{x:,.0f}"` 는 천단위 쉼표를 넣는다. 자바스크립트
 * 기본 표기는 둘 다 다르므로 `_repr`·`_fixed` 로 파이썬 규칙을 옮겼다. 다만
 * 파이썬 **int** 는 `str(5)` 가 "5" 라 흉내낼 수 없다 — JSON 을 건너오면 int 와
 * float 의 구분이 사라지기 때문이다. 문구에 그대로 박히는 인자(전용률·공실률·
 * 금리·성장률 따위)는 파이썬 쪽에서도 float 로 넘겨야 두 판이 같아진다.
 * 같은 한계가 `hold_model` 의 `hold_years` 에도 있다(파이썬은 `5.0` 을 거절하고
 * 여기서는 `5` 와 구분할 수 없다). 소수 연수(`5.5`)는 양쪽 다 거절한다.
 *
 * 수치가 아닌 값(`null`·문자열)은 파이썬도 여기도 TypeError 다. 다만 파이썬에서
 * 그것은 `require_finite` 가 아니라 `math.isnan` 이 내는 것이라 "입력 오류"
 * (ValueError) 갈래에 들어가지 않는다 — 유형 검사가 필요한 진입점은 이 가드를
 * 부르기 전에 스스로 유형을 확인해야 한다는 원본의 규약이 여기에도 그대로 산다.
 *
 * 외부 의존은 없다. 브라우저에서는 `window.CheungwiEngine`, node 에서는
 * `require(".../engine.js")` 로 같은 객체를 얻는다.
 */

;(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.CheungwiEngine = api;
  } else if (root) {
    root.CheungwiEngine = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ── 물리 게이트 경계(단일 출처) ────────────────────────────────────────
  var RENT_MIN_WON_M2_MO = 10000.0;   // effective_rent
  var RENT_MAX_WON_M2_MO = 60000.0;
  var CAP_MIN = 0.02;                 // caprate
  var CAP_MAX = 0.12;
  var DSCR_GATE_MIN = 0.0;            // acquisition(전역 제약)
  var DSCR_GATE_MAX = 5.0;

  // ── 조정 가능한 가정의 기본값(골든 상수가 아니다) ──────────────────────
  var DEFAULT_EFFICIENCY = 0.5;
  var DEFAULT_OPEX_RATIO = 0.15;

  // ── 그 밖의 상수 ───────────────────────────────────────────────────────
  var BP_PER_UNIT = 10000.0;              // 소수 이율 1 = 10,000bp
  var IMPLAUSIBLE_MAX_RATE_OVER = 1.0;    // 이자만으로 연 100% 초과를 견딘다
  var IMPLAUSIBLE_LTV_UNDER = 0.01;       // 대출이 가치의 1% 도 안 된다
  var BINDING_PRIORITY = ["ltv", "dscr", "debt_yield"];
  var MONTHS_PER_YEAR = 12;
  var QUARTERS_PER_YEAR = 4;
  var IRR_LO = -0.5;                      // 분기이율 탐색 구간
  var IRR_HI = 1.0;
  var IRR_ITERATIONS = 200;               // 고정 반복 — 입력에 좌우되지 않는다

  var AGE_FACTORS = [
    [10.0, 1.06],       // 0~10년: 신축 프리미엄 +6%
    [20.0, 1.0],        // 10~20년: 기준
    [30.0, 0.94],       // 20~30년: −6%
    [Infinity, 0.88]    // 30년+: −12%
  ];
  var SCALE_FACTORS = [
    [30000.0, 0.96],    // 3만㎡ 미만: −4%
    [50000.0, 1.0],     // 3만~5만㎡: 기준
    [100000.0, 1.04],   // 5만~10만㎡: +4%
    [Infinity, 1.08]    // 10만㎡+: +8%
  ];
  var SUBWAY_RADIUS_M = 400.0;
  var SUBWAY_FACTOR = 1.03;

  // ── 오류 ───────────────────────────────────────────────────────────────
  function inputError(message) {
    return new TypeError(message);          // 파이썬 ValueError
  }

  function gateError(message) {
    return new RangeError(message);         // 파이썬 RuntimeError
  }

  function notImplemented(message) {
    return new Error("미구현 — " + message); // 파이썬 NotImplementedError
  }

  // ── 파이썬 수치 표기 ───────────────────────────────────────────────────
  /**
   * 파이썬 `str(float)` 을 옮긴다.
   *
   * 파이썬은 최단 왕복 표기를 쓰되 소수점을 반드시 남기고(`1.0`), 십진 지수가
   * −4 이하이거나 16 을 넘으면 지수 표기로 바꾼다(`1e-05`·`1e+17`). 자바스크립트
   * `String()` 은 소수점을 떼고(`1`) 지수 전환 경계도 다르다(−7·21). 그대로 두면
   * `factors.age` 가 파이썬에서는 "1.0", 여기서는 "1" 로 나가 문구가 어긋난다.
   */
  function _repr(x) {
    if (typeof x !== "number") return String(x);
    if (Number.isNaN(x)) return "nan";
    if (x === Infinity) return "inf";
    if (x === -Infinity) return "-inf";
    var negative = x < 0 || (x === 0 && 1 / x < 0);
    var abs = Math.abs(x);
    if (abs === 0) return negative ? "-0.0" : "0.0";

    // 인자 없는 toExponential 은 값을 유일하게 특정하는 최단 자릿수를 준다.
    var parts = /^(\d)(?:\.(\d+))?e([+-]\d+)$/.exec(abs.toExponential());
    var digits = parts[1] + (parts[2] || "");
    var exponent = parseInt(parts[3], 10);
    var decpt = exponent + 1;               // 값 = 0.d1d2… × 10^decpt
    var out;

    if (decpt <= -4 || decpt > 16) {
      var mantissa = digits.length > 1 ? digits[0] + "." + digits.slice(1) : digits;
      var sign = exponent < 0 ? "-" : "+";
      var magnitude = String(Math.abs(exponent));
      if (magnitude.length < 2) magnitude = "0" + magnitude;
      out = mantissa + "e" + sign + magnitude;
    } else if (decpt <= 0) {
      out = "0." + "0".repeat(-decpt) + digits;
    } else if (decpt >= digits.length) {
      out = digits + "0".repeat(decpt - digits.length) + ".0";
    } else {
      out = digits.slice(0, decpt) + "." + digits.slice(decpt);
    }
    return negative ? "-" + out : out;
  }

  /** 문구 안의 불리언은 파이썬 표기를 따른다(`True`·`False`). */
  function _bool(x) {
    return x ? "True" : "False";
  }

  /** 십진 문자열의 마지막 자리에 1 을 올린다(자리올림 포함). */
  function _bump(s) {
    var out = s.split("");
    for (var i = out.length - 1; i >= 0; i -= 1) {
      if (out[i] === ".") continue;
      if (out[i] === "9") { out[i] = "0"; continue; }
      out[i] = String(Number(out[i]) + 1);
      return out.join("");
    }
    return "1" + out.join("");
  }

  /**
   * 파이썬 `f"{x:.Nf}"`(group=false) · `f"{x:,.Nf}"`(group=true) 를 옮긴다.
   *
   * `toFixed` 와 파이썬 서식은 **정확히 반이 되는 값에서 갈린다** — 파이썬은
   * 짝수 쪽으로 붙이고(round-half-even) `toFixed` 는 절대값이 큰 쪽으로 붙인다.
   * 그래서 `f"{1000.5:,.0f}"` 는 "1,000" 인데 `(1000.5).toFixed(0)` 은 "1001" 이다.
   * 임의의 실수 연산이 십진 반값에 정확히 떨어지는 일은 드물지만 0.5·0.125 처럼
   * 사람이 적는 값에서는 흔하다.
   *
   * 반값 판정은 어림이 아니라 정확하다. 배정밀도 실수는 m/2^e 꼴이라 십진 전개가
   * 정확히 e 자리에서 끝나므로, 소수 `decimals` 자리에서 반이 되는 것은
   * `x · 2^(decimals+1)` 이 **홀수**일 때뿐이다. 2 의 거듭제곱 곱셈은 오차가
   * 없으니 이 판정 자체에 반올림이 끼지 않는다.
   */
  function _fixed(x, decimals, group) {
    if (Number.isNaN(x)) return "nan";
    if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
    var sign = (x < 0 || (x === 0 && 1 / x < 0)) ? "-" : "";
    var abs = Math.abs(x);
    var body;
    var halved = abs * Math.pow(2, decimals + 1);

    if (Number.isInteger(halved) && halved % 2 === 1) {
      // 정확히 반이다. 이때 `toFixed(decimals + 1)` 은 반올림 없이 정확한 표기라
      // 끝의 "5" 를 떼고 남은 마지막 자리가 홀수일 때만 올리면 된다.
      var exact = abs.toFixed(decimals + 1);
      body = exact.slice(0, -1);
      if (decimals === 0) body = body.slice(0, -1);   // 소수점도 뗀다
      if ((body.charCodeAt(body.length - 1) - 48) % 2 === 1) body = _bump(body);
    } else if (abs >= 1e21) {
      // 이 크기의 실수는 전부 정수라 `toFixed` 가 지수 표기로 새어 나간다.
      // 파이썬은 자릿수를 그대로 펼치므로 정확한 정수 표기를 직접 만든다.
      body = BigInt(abs).toString();
      if (decimals > 0) body += "." + "0".repeat(decimals);
    } else {
      body = abs.toFixed(decimals);
    }

    if (group) {
      var dot = body.indexOf(".");
      var whole = dot < 0 ? body : body.slice(0, dot);
      var fraction = dot < 0 ? "" : body.slice(dot);
      body = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + fraction;
    }
    return sign + body;
  }

  // ── fin_core ───────────────────────────────────────────────────────────
  /**
   * NaN·±무한대를 입력 오류로 잡는다. 분석 계층의 단일 가드다.
   *
   * 둘 다 정상 실수처럼 생겨서, NaN 은 크기 비교가 전부 거짓이라 도메인 검사와
   * 구간표 선택을 조용히 통과하고 ±inf 는 상한 검사가 없는 자리를 그대로 지나
   * cap·대출가능액·IRR 을 오염시킨다. 하류가 잡지 못하므로 여기서 멈춘다.
   */
  function require_finite(x, what) {
    if (typeof x !== "number") {
      throw inputError(what + " 값이 수치가 아니다: " + String(x));
    }
    if (Number.isNaN(x)) {
      throw inputError(what + " 값이 NaN 이다 — 검사를 조용히 통과하므로 막는다");
    }
    if (!Number.isFinite(x)) {
      throw inputError(what + " 값이 무한대다 — 검사를 조용히 통과하므로 막는다");
    }
  }

  /** 분기이율에서의 현재가치 합(IRR 탐색 내부용 — 연율 환산을 하지 않는다). */
  function _npvAt(cashflows, quarterlyRate) {
    var total = 0.0;
    for (var q = 0; q < cashflows.length; q += 1) {
      total += cashflows[q] / Math.pow(1 + quarterlyRate, q);
    }
    return total;
  }

  /**
   * 분기 IRR 을 이분법(구간 [−0.5, 1.0], 200회 고정)으로 구해 연율화한다.
   *
   * 반환은 (1 + irr_q)^4 − 1. 뉴턴법으로 바꾸면 수렴이 입력에 좌우돼 파이썬
   * 산출과 미세하게 어긋나므로 반복 횟수까지 그대로 옮긴다. 부호 변화가 없거나
   * 근이 구간 밖이면 값을 지어내지 않고 `null` 을 돌려준다.
   */
  function irr_annual(cashflows) {
    var nonzero = cashflows.filter(function (c) { return c !== 0; });
    if (nonzero.length === 0) return null;
    var allPositive = nonzero.every(function (c) { return c > 0; });
    var allNegative = nonzero.every(function (c) { return c < 0; });
    if (allPositive || allNegative) return null;   // 부호 변화 없음

    var lo = IRR_LO;
    var hi = IRR_HI;
    var flo = _npvAt(cashflows, lo);
    var fhi = _npvAt(cashflows, hi);
    if (flo === 0) return Math.pow(1 + lo, 4) - 1;
    if (fhi === 0) return Math.pow(1 + hi, 4) - 1;
    if (flo * fhi > 0) return null;                // 범위 내 근 없음

    for (var i = 0; i < IRR_ITERATIONS; i += 1) {
      var mid = (lo + hi) / 2;
      var fmid = _npvAt(cashflows, mid);
      if (flo * fmid <= 0) {
        hi = mid;
      } else {
        lo = mid;
        flo = fmid;
      }
    }
    var irrQuarterly = (lo + hi) / 2;
    return Math.pow(1 + irrQuarterly, 4) - 1;
  }

  // ── effective_rent ─────────────────────────────────────────────────────
  /** 구간표에서 계수를 고른다. 경계는 [하한, 상한) 반열림. */
  function _pick(table, x) {
    for (var i = 0; i < table.length; i += 1) {
      if (x < table[i][0]) return table[i][1];
    }
    return table[table.length - 1][1];
  }

  /** 임대료가 물리 범위 안인지 확인하고 그대로 돌려준다. 밖이면 멈춘다. */
  function _gateRent(rentWonM2Mo, what) {
    if (!(RENT_MIN_WON_M2_MO <= rentWonM2Mo && rentWonM2Mo <= RENT_MAX_WON_M2_MO)) {
      throw gateError(
        what + " " + _fixed(rentWonM2Mo, 1, true) + "원/㎡·월이 물리 범위[" +
        _fixed(RENT_MIN_WON_M2_MO, 0, true) + ", " +
        _fixed(RENT_MAX_WON_M2_MO, 0, true) + "] 밖이다 — " +
        "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라"
      );
    }
    return rentWonM2Mo;
  }

  /**
   * 렌트프리를 차감한 유효임대료 = 명목 × (12 − 렌트프리개월) / 12.
   *
   * 결과는 물리 게이트(10,000~60,000원/㎡·월)를 통과해야 한다. 보증금
   * 운용수익은 넣지 않는다 — 시간 구조가 달라 현금흐름 쪽에서 다룬다.
   */
  function effective_rent(nominal_won_m2_mo, rent_free_months_per_year) {
    require_finite(nominal_won_m2_mo, "명목임대료");
    if (!(0 <= rent_free_months_per_year && rent_free_months_per_year <= 12)) {
      throw inputError(
        "렌트프리는 연 0~12개월이어야 한다: " + _repr(rent_free_months_per_year)
      );
    }
    var effective = nominal_won_m2_mo * (12 - rent_free_months_per_year) / 12;
    return _gateRent(effective, "유효임대료");
  }

  /**
   * 건물 세 특성(연식·규모·역세권)으로 기준임대료를 보정한다.
   *
   * 보정값 = base × 연식계수 × 규모계수 × 역세권계수. 구간 경계는
   * [하한, 상한) 반열림이고, 역까지 거리를 모르면(`null`) 1.0 으로 **보류**한다
   * — 400m 초과와 같은 값이지만 뜻이 달라 `caveats` 에 남긴다.
   */
  function building_adjust(base, age_years, gfa_m2, dist_subway_m) {
    var unknownDistance = dist_subway_m === null || dist_subway_m === undefined;
    require_finite(age_years, "연식");
    if (age_years < 0) {
      throw inputError("연식은 음수일 수 없다: " + _repr(age_years));
    }
    require_finite(gfa_m2, "연면적");
    if (gfa_m2 <= 0) {
      throw inputError("연면적은 양수여야 한다: " + _repr(gfa_m2));
    }
    if (!unknownDistance) {
      require_finite(dist_subway_m, "역까지 거리");
      if (dist_subway_m < 0) {
        throw inputError("역까지 거리는 음수일 수 없다: " + _repr(dist_subway_m));
      }
    }

    var age = _pick(AGE_FACTORS, age_years);
    var scale = _pick(SCALE_FACTORS, gfa_m2);
    var subway;
    if (unknownDistance) {
      subway = 1.0;
    } else {
      subway = dist_subway_m <= SUBWAY_RADIUS_M ? SUBWAY_FACTOR : 1.0;
    }

    var value = _gateRent(base * age * scale * subway, "보정임대료");

    var caveats = [
      "세 계수를 곱으로 겹쳤다 — 특성 간 상관(신축일수록 크고 역세권인 " +
      "경향)을 무시했으므로 셋이 함께 좋은 건물은 프리미엄이 과대평가된다.",
      "계수 폭(±6%·±4%·+3%)은 시장 관행 수준의 가정이며 회귀로 추정한 " +
      "값이 아니다. 리모델링 이력·공용부 효율·임차인 구성은 넣지 않았다."
    ];
    if (unknownDistance) {
      caveats.push(
        "역까지 거리를 몰라 역세권 계수를 1.0 으로 보류했다 — 400m 초과와 " +
        "같은 값이지만 '역세권 아님'이 아니라 '판단 유보'다."
      );
    }

    return {
      value: value,
      factors: { age: age, scale: scale, subway: subway },
      assumptions: [
        "연식 " + _repr(age_years) + "년 → " + _repr(age),
        "연면적 " + _fixed(gfa_m2, 0, true) + "㎡ → " + _repr(scale),
        unknownDistance
          ? "역까지 거리 모름 → 1.0"
          : "역까지 " + _fixed(dist_subway_m, 0, true) + "m → " + _repr(subway),
        "구간 경계는 [하한, 상한) 반열림"
      ],
      caveats: caveats
    };
  }

  // ── noi ────────────────────────────────────────────────────────────────
  /** `noi()` 진입의 임대료 게이트. 문구가 배수로 부푸는 하류를 짚는다. */
  function _gateRentForNoi(rentWonM2Mo) {
    if (!(RENT_MIN_WON_M2_MO <= rentWonM2Mo && rentWonM2Mo <= RENT_MAX_WON_M2_MO)) {
      throw gateError(
        "유효임대료 " + _fixed(rentWonM2Mo, 1, true) + "원/㎡·월이 물리 범위[" +
        _fixed(RENT_MIN_WON_M2_MO, 0, true) + ", " +
        _fixed(RENT_MAX_WON_M2_MO, 0, true) + "] 밖이다 — " +
        "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라. 이대로 두면 NOI 가 " +
        "배수로 부풀어 감정가·대출까지 조용히 어긋난다"
      );
    }
  }

  /**
   * 정상화 순영업소득(원/년)과 그 가정.
   *
   *   임대면적 = GFA × 전용률 · PGI = 유효임대료 × 임대면적 × 12
   *   EGI = PGI × (1 − 공실률) · NOI = EGI × (1 − opex_ratio)
   *
   * 전용률은 GFA 대비 **임대면적** 비율이고, opex_ratio 는 총 운영경비가 아니라
   * 관리비 상계 후 **미회수분**이다. NOI 숫자만 떼어 인용하면 안 된다.
   */
  function noi(eff_rent_won_m2_mo, gfa_m2, efficiency, vacancy, opex_ratio) {
    require_finite(eff_rent_won_m2_mo, "유효임대료");
    if (eff_rent_won_m2_mo <= 0) {
      throw inputError("유효임대료는 양수여야 한다: " + _repr(eff_rent_won_m2_mo));
    }
    _gateRentForNoi(eff_rent_won_m2_mo);
    require_finite(gfa_m2, "연면적");
    if (gfa_m2 <= 0) {
      throw inputError("연면적은 양수여야 한다: " + _repr(gfa_m2));
    }
    require_finite(efficiency, "전용률");
    if (!(0 < efficiency && efficiency <= 1)) {
      throw inputError("전용률은 (0, 1] 이어야 한다: " + _repr(efficiency));
    }
    require_finite(vacancy, "공실률");
    if (!(0 <= vacancy && vacancy <= 1)) {
      throw inputError("공실률은 [0, 1] 이어야 한다: " + _repr(vacancy));
    }
    require_finite(opex_ratio, "운영경비율");
    if (!(0 <= opex_ratio && opex_ratio < 1)) {
      throw inputError("운영경비율은 [0, 1) 이어야 한다: " + _repr(opex_ratio));
    }

    var nla_m2 = gfa_m2 * efficiency;
    var pgi_won_y = eff_rent_won_m2_mo * nla_m2 * MONTHS_PER_YEAR;
    var egi_won_y = pgi_won_y * (1 - vacancy);
    var noi_won_y = egi_won_y * (1 - opex_ratio);

    return {
      noi_won_y: noi_won_y,
      egi_won_y: egi_won_y,
      assumptions: {
        eff_rent_won_m2_mo: eff_rent_won_m2_mo,
        gfa_m2: gfa_m2,
        efficiency: efficiency,
        vacancy: vacancy,
        opex_ratio: opex_ratio,
        nla_m2: nla_m2,
        pgi_won_y: pgi_won_y,
        notes: [
          "임대면적 = GFA " + _fixed(gfa_m2, 0, true) + "㎡ × 전용률 " +
          _repr(efficiency) + " = " + _fixed(nla_m2, 0, true) +
          "㎡ (전유면적이 아니라 공용부 안분을 포함한 " +
          "임대면적/GFA 비율. 관행 근사 " + _repr(DEFAULT_EFFICIENCY) + ")",
          "EGI = 유효임대료 " + _fixed(eff_rent_won_m2_mo, 0, true) +
          "원/㎡·월 × 임대면적 × 12개월 × (1 − 공실 " + _repr(vacancy) + ")",
          "NOI = EGI × (1 − 운영경비율 " + _repr(opex_ratio) + ") — 운영경비율은 총 " +
          "운영경비가 아니라 **관리비 상계 후 미회수분**이다. 임차인이 " +
          "관리비를 별도 부담해 청소·경비·공용 수도광열은 대부분 " +
          "회수되고, 수선충당·보험·공용부 손실·재산세 일부만 남는다는 " +
          "가정(관행 근사 " + _repr(DEFAULT_OPEX_RATIO) + ")."
        ],
        caveats: [
          "전용률·공실률·운영경비율 셋 다 관행 수준의 가정값이며 회귀로 " +
          "추정한 값이 아니다. 셋 중 하나만 흔들려도 NOI 가 두 자릿수 " +
          "퍼센트로 움직인다.",
          "관리비 수입과 지출을 각각 총액으로 세우지 않고 상계 후 비율 " +
          "하나로 뭉갰다. 관리비를 임대인이 부담하는 gross lease 건물은 " +
          "이 가정이 맞지 않아 opex_ratio 를 크게 올려야 한다.",
          "NOI 관행대로 자본적 지출(CapEx)·임대차 수수료(TI/LC)·감가상각·" +
          "이자·법인세는 빼지 않았다. 보증금 운용수익도 넣지 않았다 — " +
          "성격이 달라 현금흐름 쪽에서 따로 다룬다.",
          "공실률을 연중 상수로 봤다. 리스업 기간·임차인 교체 공백의 " +
          "시점 분포는 반영하지 않은 정상화(stabilized) 한 해다."
        ]
      }
    };
  }

  // ── caprate · value ────────────────────────────────────────────────────
  /** cap 이 물리 범위(0.02~0.12) 안인지 확인하고 그대로 돌려준다. */
  function _gateCap(cap, what) {
    if (!(CAP_MIN <= cap && cap <= CAP_MAX)) {
      throw gateError(
        what + " " + _fixed(cap, 6, false) + "(= " + _fixed(cap * 100, 4, false) +
        "%)이 물리 범위[" + _repr(CAP_MIN) + ", " + _repr(CAP_MAX) + "] 밖이다 — " +
        "cap 이 아니라 단위(%↔소수)나 입력 자릿수를 의심하라. 이대로 두면 " +
        "감정가가 배수로 어긋난 채 대출·IRR 까지 조용히 흘러간다"
      );
    }
    return cap;
  }

  /**
   * 실거래가가 함의한 cap = NOI ÷ 가격.
   *
   * NOI 는 원/년, 가격은 원이다. 이 값은 **거래 한 건**이 함의한 cap 이라
   * 표본이 1 이다 — 시장 벤치마크와 나란히 놓고 괴리를 보라.
   */
  function implied(noi_won_y, price_won) {
    require_finite(noi_won_y, "NOI");
    if (noi_won_y < 0) {
      throw inputError("NOI 는 음수일 수 없다: " + _repr(noi_won_y));
    }
    require_finite(price_won, "거래가격");
    if (price_won <= 0) {
      throw inputError("거래가격은 양수여야 한다: " + _repr(price_won));
    }
    return _gateCap(noi_won_y / price_won, "실거래 역산 cap");
  }

  /**
   * 소득접근 감정가(원) = NOI ÷ cap(직접환원법).
   *
   * 임대차 만기 구조·리스업·CapEx 의 시점은 들어 있지 않다. NOI 0 은 가치 0 을
   * 돌려준다 — 소득이 없는 건물의 **소득**접근 가치가 0 이라는 뜻이지 그 건물이
   * 무가치하다는 뜻이 아니다.
   */
  function appraise(noi_won_y, cap) {
    require_finite(noi_won_y, "NOI");
    if (noi_won_y < 0) {
      throw inputError("NOI 는 음수일 수 없다: " + _repr(noi_won_y));
    }
    require_finite(cap, "cap");
    if (!(CAP_MIN <= cap && cap <= CAP_MAX)) {
      throw gateError(
        "cap " + _fixed(cap, 6, false) + "(= " + _fixed(cap * 100, 4, false) +
        "%)이 물리 범위[" + _repr(CAP_MIN) + ", " + _repr(CAP_MAX) + "] 밖이다 — " +
        "cap 이 아니라 단위(%↔소수)를 의심하라. 4.5 를 넣으면 감정가가 " +
        "100분의 1, 0.0045 를 넣으면 10배가 되고, 둘 다 정상 금액처럼 생겨서 " +
        "대출·IRR 까지 그대로 흘러간다"
      );
    }
    return noi_won_y / cap;
  }

  // ── acquisition ────────────────────────────────────────────────────────
  /** 요구 DSCR 이 물리 범위(0~5) 안인지 확인한다. 전역 제약이다. */
  function _gateDscr(dscr_min, tail) {
    if (!(DSCR_GATE_MIN <= dscr_min && dscr_min <= DSCR_GATE_MAX)) {
      throw gateError(
        "요구 DSCR " + _fixed(dscr_min, 4, true) + " 이 물리 범위[" +
        _repr(DSCR_GATE_MIN) + ", " + _repr(DSCR_GATE_MAX) + "] 밖이다 — " +
        "DSCR 이 아니라 단위(배수↔%)를 의심하라. " + tail
      );
    }
  }

  /** 매각 cap 게이트 — `appraise` 와 같은 범위를 매각가에도 건다. */
  function _gateExitCap(cap) {
    if (!(CAP_MIN <= cap && cap <= CAP_MAX)) {
      throw gateError(
        "매각 cap " + _fixed(cap, 6, false) + "(= " + _fixed(cap * 100, 4, false) +
        "%)이 물리 범위[" + _repr(CAP_MIN) + ", " + _repr(CAP_MAX) + "] 밖이다 — " +
        "cap 이 아니라 단위(%↔소수)를 의심하라. 4.5 를 넣으면 매각가가 " +
        "100분의 1, 0.0045 를 넣으면 10배가 되고 둘 다 IRR 까지 조용히 흘러간다"
      );
    }
  }

  /**
   * 삼중 제약(LTV·DSCR·Debt Yield) 중 가장 작은 대출가능액(원).
   *
   *   ltv = 가격 × LTV 한도 · dscr = (NOI ÷ 요구 DSCR) ÷ 금리 · debt_yield = NOI ÷ DY
   *
   * 나누기 두 번은 **IO(이자만 상환)** 가정 때문이다. 원리금균등이면 상한이 더
   * 작아지므로 `io=false` 는 조용히 IO 로 처리하지 않고 계산을 거절한다.
   * `binding` 은 최솟값의 이름 하나이고 동률이면 ltv > dscr > debt_yield 순이다.
   */
  function max_loan(noi_won_y, price_won, ltv_max, dscr_min, debt_yield_min,
                    loan_rate, io) {
    if (io === undefined) io = true;
    if (!io) {
      throw notImplemented(
        "원리금균등(io=false) 대출가능액은 상환 연수가 있어야 계산할 수 " +
        "있는데 시그니처에 없다. 조용히 IO 로 처리하면 상환액을 이자로만 " +
        "봐서 대출가능액이 과대(위험한 방향)로 나온다 — 계산하지 않는다"
      );
    }

    require_finite(noi_won_y, "NOI");
    require_finite(price_won, "가격");
    require_finite(ltv_max, "LTV 한도");
    require_finite(dscr_min, "요구 DSCR");
    require_finite(debt_yield_min, "DY 하한");
    require_finite(loan_rate, "대출금리");

    if (noi_won_y < 0) {
      throw inputError("NOI 는 음수일 수 없다: " + _repr(noi_won_y));
    }
    if (price_won <= 0) {
      throw inputError("가격은 양수여야 한다: " + _repr(price_won));
    }
    if (!(0 < ltv_max && ltv_max <= 1)) {
      throw inputError(
        "LTV 한도는 (0, 1] 인 소수여야 한다(55% = 0.55): " + _repr(ltv_max)
      );
    }
    if (!(0 < debt_yield_min && debt_yield_min <= 1)) {
      throw inputError(
        "DY 하한은 (0, 1] 인 소수여야 한다(8% = 0.08): " + _repr(debt_yield_min)
      );
    }
    if (!(0 < loan_rate && loan_rate <= 1)) {
      throw inputError(
        "대출금리는 (0, 1] 인 소수여야 한다(4.5% = 0.045): " + _repr(loan_rate) +
        ". 0(무이자)이면 DSCR 제약이 무한대가 되어 삼중 제약이 이중 제약으로 " +
        "바뀐다"
      );
    }

    // 게이트를 도메인보다 먼저 건다 — 전역 제약이 음수 DSCR 의 오류 유형을
    // "단위를 의심하라"로 못박고 있어서, 도메인 검사를 앞세우면 유형이 어긋난다.
    _gateDscr(
      dscr_min,
      "1.3 을 130 으로 넣으면 대출가능액이 100분의 1 이 되고, 음수면 제약이 " +
      "뒤집혀 무한대가 된다"
    );
    if (dscr_min <= 0) {
      throw inputError(
        "요구 DSCR 은 양수여야 한다: " + _repr(dscr_min) +
        ". 0 은 '커버리지를 요구하지 않는다'는 뜻이라 DSCR 제약이 무한대가 된다"
      );
    }

    var by = {
      ltv: price_won * ltv_max,
      dscr: (noi_won_y / dscr_min) / loan_rate,
      debt_yield: noi_won_y / debt_yield_min
    };
    // 순회 순서가 곧 동률 우선순위다(파이썬 `min` 이 첫 최솟값을 고르는 것과 같다).
    var binding = BINDING_PRIORITY[0];
    for (var i = 1; i < BINDING_PRIORITY.length; i += 1) {
      if (by[BINDING_PRIORITY[i]] < by[binding]) binding = BINDING_PRIORITY[i];
    }
    var loan_won = by[binding];

    var interest_won_y = loan_won * loan_rate;
    var dscr_at_max_loan = interest_won_y > 0 ? noi_won_y / interest_won_y : null;

    return {
      loan_won: loan_won,
      binding: binding,
      by: by,
      assumptions: {
        noi_won_y: noi_won_y,
        price_won: price_won,
        ltv_max: ltv_max,
        dscr_min: dscr_min,
        debt_yield_min: debt_yield_min,
        loan_rate: loan_rate,
        io: io,
        ltv_at_max_loan: loan_won / price_won,
        interest_won_y: interest_won_y,
        dscr_at_max_loan: dscr_at_max_loan,
        debt_yield_at_max_loan: loan_won > 0 ? noi_won_y / loan_won : null,
        notes: [
          "IO(이자만 상환) 가정이다 — DSCR 제약은 원리금이 아니라 " +
          "이자(대출 × 금리 " + _repr(loan_rate) + ")를 덮는다. 원리금균등이면 " +
          "상환액이 커져 대출가능액이 이보다 작아진다.",
          "결속 조건 " + binding + " — 셋 중 가장 작은 제약이다. 동률이면 " +
          BINDING_PRIORITY.join(" > ") + " 순서로 하나를 고른다.",
          "세 제약의 상한을 `by` 에 모두 실었다. 결속 조건만 인용하면 " +
          "나머지 두 제약까지 얼마나 여유가 있었는지가 사라진다."
        ],
        caveats: [
          "대출 조건(LTV 한도·요구 DSCR·DY 하한·금리)은 시장 관행 수준의 " +
          "가정이며 실제 대주 심사 결과가 아니다. 넷 중 하나만 흔들려도 " +
          "대출가능액이 두 자릿수 퍼센트로 움직인다.",
          "금리를 고정으로 봤다. 변동금리·금리 상한(cap) 비용·수수료·" +
          "약정 수수료는 들어 있지 않다.",
          "선순위 한 트랜치만 본다 — 메자닌·후순위를 얹는 구조는 이 " +
          "삼중 제약으로 설명되지 않는다.",
          "NOI 는 정상화 한 해의 값이다. 임대차 만기 구조·리스업 공백이 " +
          "겹치는 해에는 실제 DSCR 이 이보다 낮아질 수 있다."
        ]
      }
    };
  }

  /**
   * 보유기간 분기 현금흐름과 지분 IRR.
   *
   *   q0 = −(가격 × (1+비용률) − 대출) · q1~ = (t년차 NOI − 대출×금리) ÷ 4
   *   마지막 분기에 (매각가 − 대출)을 더한다.
   *
   * NOI 는 **연 단위 계단**으로 자라고(한 해 안의 네 분기는 같다), 매각가에 쓰는
   * NOI 는 보유 마지막 해가 아니라 **그 다음 해**다. `equity_irr` 은 `null` 일 수
   * 있다 — 부호 변화가 없거나 근이 탐색 범위 밖이면 값을 지어내지 않는다.
   */
  function hold_model(price_won, loan_won, loan_rate, noi_won_y, noi_growth_y,
                      exit_cap, hold_years, cost_rate) {
    if (hold_years === undefined) hold_years = 5;
    if (cost_rate === undefined) cost_rate = 0.05;

    require_finite(price_won, "가격");
    require_finite(loan_won, "대출");
    require_finite(loan_rate, "대출금리");
    require_finite(noi_won_y, "NOI");
    require_finite(noi_growth_y, "NOI 성장률");
    require_finite(exit_cap, "매각 cap");
    require_finite(cost_rate, "취득부대비용률");

    if (price_won <= 0) {
      throw inputError("가격은 양수여야 한다: " + _repr(price_won));
    }
    if (loan_won < 0) {
      throw inputError("대출은 음수일 수 없다: " + _repr(loan_won));
    }
    if (loan_won > price_won) {
      throw inputError(
        "대출 " + _fixed(loan_won, 0, true) + "원이 가격 " +
        _fixed(price_won, 0, true) + "원을 넘는다 — " +
        "LTV 100% 초과 구조는 이 모델에 없다(취득부대비용은 자기자본이다)"
      );
    }
    if (!(0 <= loan_rate && loan_rate <= 1)) {
      throw inputError(
        "대출금리는 [0, 1] 인 소수여야 한다(4% = 0.04): " + _repr(loan_rate)
      );
    }
    if (noi_won_y < 0) {
      throw inputError("NOI 는 음수일 수 없다: " + _repr(noi_won_y));
    }
    if (!(-1 < noi_growth_y && noi_growth_y <= 1)) {
      throw inputError(
        "NOI 성장률은 (−1, 1] 인 소수여야 한다(2% = 0.02): " + _repr(noi_growth_y) +
        ". −1 이하면 NOI 가 0 이하로 무너지고, 1 초과면 연 100% 넘는 성장이라 " +
        "% 를 소수 자리에 넣은 오입력을 의심해야 한다"
      );
    }
    // 파이썬은 bool 이 int 의 하위형이라 `True` 를 따로 막지만, 여기서는
    // 불리언이 애초에 number 가 아니라 유형 검사 하나로 함께 걸린다.
    if (typeof hold_years !== "number" || !Number.isInteger(hold_years)) {
      throw inputError(
        "보유 기간은 정수 연이어야 한다: " + _repr(hold_years) + ". 분기 흐름을 연 " +
        "단위 NOI 성장에 묶어 조립하므로 반년은 규약에 없다"
      );
    }
    if (hold_years < 1) {
      throw inputError("보유 기간은 1년 이상이어야 한다: " + _repr(hold_years));
    }
    if (!(0 <= cost_rate && cost_rate < 1)) {
      throw inputError(
        "취득부대비용률은 [0, 1) 인 소수여야 한다(5% = 0.05): " + _repr(cost_rate)
      );
    }

    _gateExitCap(exit_cap);

    var interest_won_y = loan_won * loan_rate;
    var acquisition_cost_won = price_won * cost_rate;
    var equity_won = price_won * (1 + cost_rate) - loan_won;

    var cashflows_q = [-equity_won];
    var noi_by_year_won = [];
    for (var t = 0; t < hold_years; t += 1) {
      var noi_t = noi_won_y * Math.pow(1 + noi_growth_y, t);
      noi_by_year_won.push(noi_t);
      var quarterly = (noi_t - interest_won_y) / QUARTERS_PER_YEAR;
      for (var q = 0; q < QUARTERS_PER_YEAR; q += 1) cashflows_q.push(quarterly);
    }

    var exit_noi_won_y = noi_won_y * Math.pow(1 + noi_growth_y, hold_years);
    var exit_value = exit_noi_won_y / exit_cap;
    cashflows_q[cashflows_q.length - 1] += exit_value - loan_won;

    var equity_irr = irr_annual(cashflows_q);

    return {
      cashflows_q: cashflows_q,
      equity_irr: equity_irr,
      exit_value: exit_value,
      assumptions: {
        price_won: price_won,
        loan_won: loan_won,
        loan_rate: loan_rate,
        noi_won_y: noi_won_y,
        noi_growth_y: noi_growth_y,
        exit_cap: exit_cap,
        hold_years: hold_years,
        cost_rate: cost_rate,
        equity_won: equity_won,
        acquisition_cost_won: acquisition_cost_won,
        interest_won_y: interest_won_y,
        ltv_at_entry: loan_won / price_won,
        noi_by_year_won: noi_by_year_won,
        exit_noi_won_y: exit_noi_won_y,
        exit_value_won: exit_value,
        cashflow_points: cashflows_q.length,   // q0 포함 = 4 × hold_years + 1
        notes: [
          "IO(이자만 상환) 가정이다 — 보유 중 원금을 갚지 않는다. 매 " +
          "분기 이자는 대출 " + _fixed(loan_won, 0, true) + "원 × 금리 " +
          _repr(loan_rate) + " ÷ 4 로 " +
          "일정하고, 원금은 매각 시점에 한 번에 상계된다(마지막 분기의 " +
          "매각 순유입 = 매각가 − 대출).",
          "q0 = −(가격 × (1 + 비용률 " + _repr(cost_rate) + ") − 대출) = " +
          "−" + _fixed(equity_won, 0, true) + "원. 취득부대비용 " +
          _fixed(acquisition_cost_won, 0, true) + "원" +
          "(취득세·중개·실사·자문)은 전액 자기자본으로 본다.",
          "NOI 는 연 " + _repr(noi_growth_y) + " 로 **연 단위 계단** 성장한다 — 한 해 " +
          "안의 네 분기는 값이 같고 해가 바뀔 때만 오른다.",
          "매각가 = 보유 종료 **다음 해** NOI " + _fixed(exit_noi_won_y, 0, true) +
          "원 ÷ exit cap " + _repr(exit_cap) + " = " + _fixed(exit_value, 0, true) +
          "원. 마지막 해 NOI 가 " + "아니라 다음 해 NOI 다.",
          "현금흐름 원소는 분기이고 IRR 은 연율이다(fin_core 규약). " +
          "equity_irr 은 부호 변화가 없거나 근이 탐색 범위 밖이면 None 이다."
        ],
        caveats: [
          "**매각비용을 반영하지 않았다** — 매각 중개·양도 관련 비용이 " +
          "빠져 있어 IRR 이 그만큼 낙관적이다(취득 쪽 비용만 cost_rate 로 " +
          "넣었다).",
          "법인세·취득세 이연효과·감가상각·CapEx·임대차 수수료(TI/LC)·" +
          "보증금 운용수익이 전부 빠져 있다. 세전·CapEx 전 지분 IRR 이다.",
          "대출 만기와 차환을 모델에 넣지 않았다. 보유 기간 내내 같은 " +
          "금리의 IO 대출이 유지된다고 본다 — 만기가 보유 기간보다 짧으면 " +
          "차환 위험이 이 IRR 에 들어 있지 않다.",
          "exit cap 은 가정이다. 진입 cap 과 같게 두면 자본이득이 NOI " +
          "성장만큼만 생기고, 벌리면(cap expansion) IRR 이 급격히 나빠진다 " +
          "— 민감도를 함께 보지 않은 단일 IRR 은 인용하지 말 것.",
          "공실·임대료는 정상화 한 해의 NOI 에 성장률 하나로 뭉갰다. " +
          "임차인 교체·리스업 공백의 시점 분포는 들어 있지 않다."
        ]
      }
    };
  }

  // ── refi ───────────────────────────────────────────────────────────────
  /**
   * 만기 차환 판정 — 견딜 수 있는 최대금리와 시장금리까지의 여유(bp).
   *
   *   max_rate = NOI ÷ (요구 DSCR × 대출)        (IO — 이자만 덮는다)
   *   pass     = (max_rate > 시장금리) AND (대출 ≤ 가치 × LTV 한도)
   *
   * 등호 처리가 두 관문에서 다르다 — 금리는 **초과**(여유 0 은 여력 없음),
   * LTV 는 **이하**(한도에 붙어도 약정 준수). 대출이 가치를 넘어도 막지 않는다:
   * 그 상황의 판정이 이 함수가 있는 이유다.
   *
   * `implausible` 은 게이트가 아니라 **신호**다. 예외를 던지지도 `pass` 를 바꾸지도
   * 않고, 실무에 없는 조합(최대금리 > 1.0, 차환 LTV < 1%)에서만 켜진다.
   */
  function refi_test(noi_won_y, loan_won, value_won, dscr_min, ltv_max, market_rate) {
    require_finite(noi_won_y, "NOI");
    require_finite(loan_won, "대출");
    require_finite(value_won, "가치");
    require_finite(dscr_min, "요구 DSCR");
    require_finite(ltv_max, "LTV 한도");
    require_finite(market_rate, "시장금리");

    if (noi_won_y < 0) {
      throw inputError("NOI 는 음수일 수 없다: " + _repr(noi_won_y));
    }
    if (loan_won <= 0) {
      throw inputError(
        "차환할 대출은 양수여야 한다: " + _repr(loan_won) + ". 갚을 대출이 없으면 차환 " +
        "판정이 없고, 최대금리가 0 으로 나누어 무한대가 된다"
      );
    }
    if (value_won <= 0) {
      throw inputError("가치는 양수여야 한다: " + _repr(value_won));
    }
    if (!(0 < ltv_max && ltv_max <= 1)) {
      throw inputError(
        "LTV 한도는 (0, 1] 인 소수여야 한다(60% = 0.60): " + _repr(ltv_max)
      );
    }
    if (!(0 <= market_rate && market_rate <= 1)) {
      throw inputError(
        "시장금리는 [0, 1] 인 소수여야 한다(5% = 0.05): " + _repr(market_rate)
      );
    }

    _gateDscr(
      dscr_min,
      "1.3 을 130 으로 넣으면 차환 가능 최대금리가 100분의 1 이 되어 멀쩡한 " +
      "건물이 차환 불가로 나오고, 음수면 제약이 뒤집힌다"
    );
    if (dscr_min <= 0) {
      throw inputError(
        "요구 DSCR 은 양수여야 한다: " + _repr(dscr_min) +
        ". 0 은 '커버리지를 요구하지 않는다'는 뜻이라 견딜 수 있는 금리가 " +
        "무한대가 된다"
      );
    }

    var max_rate = noi_won_y / (dscr_min * loan_won);
    var max_loan_by_ltv = value_won * ltv_max;
    var headroom_bp = (max_rate - market_rate) * BP_PER_UNIT;

    var rate_pass = max_rate > market_rate;
    var ltv_pass = loan_won <= max_loan_by_ltv;
    var ltv_at_refi = loan_won / value_won;

    var implausible_reasons = [];
    if (max_rate > IMPLAUSIBLE_MAX_RATE_OVER) {
      implausible_reasons.push(
        "견딜 수 있는 최대금리가 " + _fixed(max_rate, 2, true) + "(= 연 " +
        _fixed(max_rate * 100, 0, true) + "%)로" +
        " " + _fixed(IMPLAUSIBLE_MAX_RATE_OVER * 100, 0, false) + "% 를 " +
        "넘는다 — 대출 " + _fixed(loan_won, 0, true) +
        "원이 NOI 에 비해 너무 작다. 금액 단위(억↔원)를 의심하라"
      );
    }
    if (ltv_at_refi < IMPLAUSIBLE_LTV_UNDER) {
      implausible_reasons.push(
        "차환 LTV 가 " + _fixed(ltv_at_refi, 6, false) + "(= " +
        _fixed(ltv_at_refi * 100, 4, false) + "%)로 " +
        _fixed(IMPLAUSIBLE_LTV_UNDER * 100, 0, false) + "% 를 밑돈다 — 대출 " +
        _fixed(loan_won, 0, true) + "원과 가치 " + _fixed(value_won, 0, true) +
        "원의 자릿수가 맞지 않는다"
      );
    }

    return {
      pass: rate_pass && ltv_pass,
      max_rate: max_rate,
      max_loan_by_ltv: max_loan_by_ltv,
      headroom_bp: headroom_bp,
      implausible: implausible_reasons.length > 0,
      implausible_reasons: implausible_reasons,
      assumptions: {
        noi_won_y: noi_won_y,
        loan_won: loan_won,
        value_won: value_won,
        dscr_min: dscr_min,
        ltv_max: ltv_max,
        market_rate: market_rate,
        rate_pass: rate_pass,
        ltv_pass: ltv_pass,
        ltv_at_refi: ltv_at_refi,
        interest_at_market_rate_won_y: loan_won * market_rate,
        dscr_at_market_rate:
          market_rate > 0 ? noi_won_y / (loan_won * market_rate) : null,
        notes: [
          "max_rate = NOI ÷ (요구 DSCR " + _repr(dscr_min) + " × 대출 " +
          _fixed(loan_won, 0, true) + "원) = " + _fixed(max_rate, 6, false) +
          " — **IO(이자만 상환)** " +
          "가정이다. 원리금 상환 조건이면 상환액이 커져 견딜 수 있는 " +
          "금리가 이보다 낮아진다.",
          "pass 는 금리(max_rate > 시장금리 " + _repr(market_rate) + ": " +
          _bool(rate_pass) + ")와 " +
          "LTV(대출 ≤ 가치 × 한도 " + _repr(ltv_max) + " = " +
          _fixed(max_loan_by_ltv, 0, true) + "원: " + _bool(ltv_pass) +
          ")의 **AND** 다. 등호는 금리 쪽이 실패(여유 0), " +
          "LTV 쪽이 통과(한도 준수)로 갈린다.",
          "headroom " + _fixed(headroom_bp, 2, true) + "bp 는 부호를 그대로 둔다 — 음수면 " +
          "시장금리가 견딜 수 있는 금리를 그만큼 넘었다는 뜻이고 pass 는 " +
          "False 다.",
          "차환 시점 LTV = 대출 ÷ 가치 = " + _fixed(ltv_at_refi, 4, false) + ". " +
          "1 을 넘는 값도 막지 않는다 — 자산가치가 대출 밑으로 빠진 상황을 " +
          "판정하는 것이 이 함수의 목적이다.",
          implausible_reasons.length > 0
            ? "**implausible 신호가 켜졌다** — 판정보다 입력을 먼저 보라: " +
              implausible_reasons.join(" / ")
            : "implausible 신호는 꺼져 있다 — 최대금리와 차환 LTV 가 " +
              "실무 범위 안이다(신호는 max_rate > " +
              _repr(IMPLAUSIBLE_MAX_RATE_OVER) + " 또는 차환 LTV < " +
              _repr(IMPLAUSIBLE_LTV_UNDER) + " 에서만 켜진다)."
        ],
        caveats: [
          "가치(value_won)가 감정가라면 그 자체가 추정치다 — cap 가정 하나가 " +
          "움직이면 LTV 관문의 판정이 뒤집힌다. 실거래가 아닌 값을 넣었다면 " +
          "cap 가정과 오차 분포를 함께 인용해야 한다.",
          "NOI 는 정상화 한 해의 값이다. 만기 시점에 임대차 만기·리스업 " +
          "공백이 겹쳐 실제 NOI 가 낮으면 max_rate 는 그만큼 과대하다.",
          "시장금리 하나로 봤다 — 대주 스프레드·주선·약정 수수료·금리 상한" +
          "(cap) 비용·중도상환 수수료는 들어 있지 않다. 실제 차환 금리는 " +
          "여기 넣은 시장금리보다 높다.",
          "요구 DSCR·LTV 한도는 시장 관행 수준의 가정이며 실제 대주 심사 " +
          "결과가 아니다. 만기 시점의 대출 시장이 조이면 둘 다 나빠진다.",
          "선순위 한 트랜치만 본다. 메자닌·후순위를 얹거나 자기자본을 더 " +
          "넣어 대출을 줄이는(부분 상환) 대안은 이 판정에 없다 — pass 가 " +
          "False 라도 구조를 바꾸면 차환이 될 수 있다.",
          "대출 금액의 단위 오입력(억↔원)은 물리 게이트가 없는 축이라 " +
          "막지 못한다. 1,485억을 1,485 로 넣으면 max_rate 가 터무니없이 " +
          "커지고 pass 가 True 로 나온다 — 그 조합에서 implausible 신호가 " +
          "켜지지만 예외를 던지지는 않으므로, 부르는 쪽이 신호를 읽어야 한다."
        ]
      }
    };
  }

  /**
   * DSCR 이 정확히 요구치가 되는 공실률(소수). 이미 불가면 0.
   *
   *   1 − (요구 DSCR × 대출 × 금리) ÷ (임대료 × GFA × 전용률 × 12 × (1 − opex))
   *
   * 공실률을 알기 전에는 `noi()` 를 부를 수 없어(그 값이 답이다) 같은 산식을
   * 다시 쓴다 — 그래서 **임대료 물리 게이트를 이 함수가 직접 건다**. 반환값이 0
   * 이면 "만실에서 겨우 맞음"과 "만실이어도 불가"가 겹친 값이고, 대출 0·금리 0
   * 이면 1.0 이다(갚을 이자가 없으면 공실률로 깨질 DSCR 자체가 없다).
   */
  function breakeven_vacancy(eff_rent, gfa, efficiency, opex_ratio, loan_won,
                             loan_rate, dscr_min) {
    require_finite(eff_rent, "유효임대료");
    require_finite(gfa, "연면적");
    require_finite(efficiency, "전용률");
    require_finite(opex_ratio, "운영경비율");
    require_finite(loan_won, "대출");
    require_finite(loan_rate, "대출금리");
    require_finite(dscr_min, "요구 DSCR");

    if (eff_rent <= 0) {
      throw inputError("유효임대료는 양수여야 한다: " + _repr(eff_rent));
    }
    if (gfa <= 0) {
      throw inputError("연면적은 양수여야 한다: " + _repr(gfa));
    }
    if (!(0 < efficiency && efficiency <= 1)) {
      throw inputError("전용률은 (0, 1] 이어야 한다: " + _repr(efficiency));
    }
    if (!(0 <= opex_ratio && opex_ratio < 1)) {
      throw inputError("운영경비율은 [0, 1) 이어야 한다: " + _repr(opex_ratio));
    }
    if (loan_won < 0) {
      throw inputError("대출은 음수일 수 없다: " + _repr(loan_won));
    }
    if (!(0 <= loan_rate && loan_rate <= 1)) {
      throw inputError(
        "대출금리는 [0, 1] 인 소수여야 한다(6% = 0.06): " + _repr(loan_rate)
      );
    }

    if (!(RENT_MIN_WON_M2_MO <= eff_rent && eff_rent <= RENT_MAX_WON_M2_MO)) {
      throw gateError(
        "유효임대료 " + _fixed(eff_rent, 1, true) + "원/㎡·월이 물리 범위[" +
        _fixed(RENT_MIN_WON_M2_MO, 0, true) + ", " +
        _fixed(RENT_MAX_WON_M2_MO, 0, true) + "] 밖이다 — " +
        "임대료가 아니라 단위(평/㎡, 월/연)를 의심하라. 이대로 두면 만실 " +
        "수입이 배수로 어긋나 손익분기 공실률이 조용히 틀린다"
      );
    }
    _gateDscr(
      dscr_min,
      "1.3 을 130 으로 넣으면 차환 가능 최대금리가 100분의 1 이 되어 멀쩡한 " +
      "건물이 차환 불가로 나오고, 음수면 제약이 뒤집힌다"
    );
    if (dscr_min <= 0) {
      throw inputError(
        "요구 DSCR 은 양수여야 한다: " + _repr(dscr_min) +
        ". 0 은 '커버리지를 요구하지 않는다'는 뜻이라 손익분기 공실률이 " +
        "1(어떤 공실에도 안 깨진다)로 나오는데, 안전한 쪽이 아니라 낙관 쪽 " +
        "침묵이다"
      );
    }

    var nla = gfa * efficiency;
    var full_egi_won_y = eff_rent * nla * MONTHS_PER_YEAR;   // 공실 0 의 EGI = PGI
    var required_noi_won_y = dscr_min * loan_won * loan_rate;

    var vacancy = 1 - required_noi_won_y / (full_egi_won_y * (1 - opex_ratio));

    // 음수는 "만실이어도 못 맞춘다"는 뜻이다 — 0 으로 자른다(이미 불가).
    return Math.max(0.0, vacancy);
  }

  return {
    // 아홉 함수
    effective_rent: effective_rent,
    building_adjust: building_adjust,
    noi: noi,
    appraise: appraise,
    implied: implied,
    max_loan: max_loan,
    hold_model: hold_model,
    refi_test: refi_test,
    breakeven_vacancy: breakeven_vacancy,
    // 내부 의존(파이썬 fin_core)
    irr_annual: irr_annual,
    require_finite: require_finite,
    // 물리 게이트 상수 — 화면에 범위를 적을 때 여기서 읽는다
    RENT_MIN_WON_M2_MO: RENT_MIN_WON_M2_MO,
    RENT_MAX_WON_M2_MO: RENT_MAX_WON_M2_MO,
    CAP_MIN: CAP_MIN,
    CAP_MAX: CAP_MAX,
    DSCR_GATE_MIN: DSCR_GATE_MIN,
    DSCR_GATE_MAX: DSCR_GATE_MAX,
    DEFAULT_EFFICIENCY: DEFAULT_EFFICIENCY,
    DEFAULT_OPEX_RATIO: DEFAULT_OPEX_RATIO,
    BINDING_PRIORITY: BINDING_PRIORITY,
    IMPLAUSIBLE_MAX_RATE_OVER: IMPLAUSIBLE_MAX_RATE_OVER,
    IMPLAUSIBLE_LTV_UNDER: IMPLAUSIBLE_LTV_UNDER
  };
});
