/**
 * 층위의 조형 프리미티브 — 인라인 SVG 문자열을 짓는 순수 함수들.
 *
 * 수지(~/개발)의 차트 엔진에서 **좌표계 다루는 법**만 가져왔다(정의역 확장,
 * 눈금 고르기, 결측 구간에서 선 끊기). 코드는 옮기지 않았다. 그쪽은 DOM 노드를
 * 만들어 붙이고 상호작용까지 품는 라이브러리이고, 여기 필요한 것은 **문자열을
 * 내는 순수 함수**이기 때문이다.
 *
 * 문자열이어야 하는 이유가 둘 있다.
 *   ① DOM 없이 검사할 수 있다 — 지층의 좌표가 비율과 맞는지, 층 사이에 틈이
 *      없는지를 node 에서 그대로 본다(`tests/test_charts.py`). 그림은 좌표의
 *      결과일 뿐이라, 눈으로는 2px 어긋난 지층을 잡을 수 없다.
 *   ② 한 번에 갈아 끼운다 — 권역 탭을 바꿀 때 노드를 하나씩 고치지 않고
 *      innerHTML 을 통째로 바꾸므로 반쪽만 갱신된 화면이 나오지 않는다.
 *
 * ── 색은 여기서 정하지 않는다 ──
 * 모든 도형은 `class` 만 달고 나간다. 색은 CSS 변수(토큰)가 준다. 다크 모드
 * 전환에 다시 그릴 필요가 없고, 팔레트의 단일 출처가 tokens.css 하나로 남는다.
 *
 * ── 반환 규약 ──
 *   `line`·`spark`·`scatter`·`bar`  — 혼자 서는 `<svg>` 한 장(문자열)
 *   `strataColumn`·`waterline`      — 남의 `<svg>` 안에 들어가는 `<g>` 조각
 *   `strataLayout`·`waterlineGeom`  — 그리지 않고 좌표만 내는 계산
 *
 * ── 오류 ──
 * 좌표가 성립하지 않는 입력은 `TypeError` 다(엔진의 "입력 오류"와 같은 갈래).
 * 조용히 0 으로 두거나 잘라 내지 않는다 — 넓이 0 인 기둥, 합이 전체를 넘는 지층,
 * 숫자가 아닌 값은 전부 그리는 쪽이 아니라 부르는 쪽의 잘못이다.
 *
 * 외부 의존은 없다. 브라우저에서는 `window.CheungwiCharts`, node 에서는
 * `require(".../charts.js")` 로 같은 객체를 얻는다.
 */

;(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.CheungwiCharts = api;
  } else if (root) {
    root.CheungwiCharts = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // 좌표 정밀도. 소수 넷째 자리면 1000px 판형에서 1e-4px 라 눈에 보이지 않고,
  // 부동소수의 꼬리(19.999999999999996)가 SVG 속성에 그대로 실리는 것을 막는다.
  var PRECISION = 1e4;

  function r4(v) {
    return Math.round(v * PRECISION) / PRECISION;
  }

  /** 숫자가 아닌 값은 여기서 멈춘다 — NaN 좌표는 도형을 조용히 지운다. */
  function fin(v, what) {
    if (typeof v !== "number" || !isFinite(v)) {
      throw new TypeError(what + " 은(는) 유한한 수여야 한다: " + String(v));
    }
    return v;
  }

  function positive(v, what) {
    fin(v, what);
    if (!(v > 0)) throw new TypeError(what + " 은(는) 양수여야 한다: " + String(v));
    return v;
  }

  /** 라벨은 사람이 쓴 문자열이다 — 태그를 닫고 나가지 못하게 막는다. */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** {k: v} → ' k="v"'. null·undefined 인 속성은 아예 쓰지 않는다. */
  function attrs(o) {
    var out = "";
    for (var k in o) {
      if (!Object.prototype.hasOwnProperty.call(o, k)) continue;
      var v = o[k];
      if (v === null || v === undefined || v === "") continue;
      out += " " + k + '="' + (typeof v === "number" ? r4(v) : esc(v)) + '"';
    }
    return out;
  }

  function tag(name, o, inner) {
    return inner === undefined || inner === null
      ? "<" + name + attrs(o) + "/>"
      : "<" + name + attrs(o) + ">" + inner + "</" + name + ">";
  }

  function text(x, y, s, o) {
    return tag("text", Object.assign({ x: x, y: y }, o || {}), esc(s));
  }

  // ── 좌표계 ──────────────────────────────────────────────────────────────
  /** 유한한 값들의 최소·최대. 전부 결측이면 [0,1], 한 점뿐이면 위아래로 벌린다. */
  function extent(values) {
    var lo = Infinity, hi = -Infinity;
    for (var i = 0; i < values.length; i += 1) {
      var v = values[i];
      if (typeof v !== "number" || !isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (lo === Infinity) return [0, 1];
    if (lo === hi) return [lo - 1, hi + 1];
    return [lo, hi];
  }

  /** 1·2·2.5·5 배수로 떨어지는 눈금. 사람이 읽는 수는 이 다섯 뿐이다. */
  function niceTicks(lo, hi, n) {
    var span = hi - lo;
    if (!(span > 0)) return [lo];
    var step0 = span / Math.max(1, n);
    var mag = Math.pow(10, Math.floor(Math.log10(step0)));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; })
      .find(function (s) { return span / s <= n; }) || mag * 10;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      out.push(r4(v));
    }
    return out;
  }

  function scaleLinear(d0, d1, r0, r1) {
    var span = d1 - d0;
    return function (v) {
      return span === 0 ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * (r1 - r0);
    };
  }

  // ── 지층 기둥 ───────────────────────────────────────────────────────────
  /**
   * 지층의 좌표를 낸다. 이 조형의 심장이다.
   *
   * 지층은 **아래에서 위로** 쌓인다 — 배열의 첫 원소가 바닥이다(자본 스택이면
   * 선순위). SVG 의 y 는 위에서 재므로 그 뒤집기를 여기서 한 번만 한다.
   *
   * 층의 높이를 각자 반올림하면 층과 층 사이에 0.01px 짜리 틈이 생겨 배경색이
   * 실선처럼 비친다. 그래서 **경계를 먼저 반올림하고 높이는 그 차이로 잡는다**
   * — 아랫층의 윗면과 윗층의 아랫면이 같은 수가 되는 유일한 방법이다.
   *
   * @param bands [{key, label, value, className}] — 아래부터
   * @param opts  {x, y, width, height, total} — y 는 기둥의 **천장**
   * @returns [{key, label, value, share, x, y, width, height}]
   */
  function strataLayout(bands, opts) {
    opts = opts || {};
    if (!Array.isArray(bands)) throw new TypeError("지층은 배열이어야 한다");
    var x = opts.x === undefined ? 0 : fin(opts.x, "기둥의 x");
    var y = opts.y === undefined ? 0 : fin(opts.y, "기둥의 y");
    var width = positive(opts.width, "기둥의 너비");
    var height = positive(opts.height, "기둥의 높이");
    if (!bands.length) return [];

    var sum = 0;
    for (var i = 0; i < bands.length; i += 1) {
      var v = fin(bands[i].value, "지층 '" + (bands[i].key || i) + "' 의 값");
      if (v < 0) {
        throw new TypeError(
          "지층의 두께는 음수일 수 없다: " + (bands[i].key || i) + " = " + v);
      }
      sum += v;
    }
    var total = opts.total === undefined || opts.total === null
      ? sum : positive(opts.total, "지층의 전체");
    if (sum > total + 1e-9) {
      throw new TypeError(
        "지층의 합 " + r4(sum) + " 이 전체 " + r4(total) +
        " 을 넘는다 — 기둥 밖으로 삐져나갈 값을 조용히 자르지 않는다");
    }

    var edges = [r4(y + height)];   // 바닥부터
    var cum = 0;
    for (var j = 0; j < bands.length; j += 1) {
      cum += bands[j].value;
      edges.push(r4(y + height * (1 - cum / total)));
    }
    return bands.map(function (b, k) {
      return {
        key: b.key,
        label: b.label,
        className: b.className,
        value: b.value,
        share: r4(b.value / total),
        x: r4(x),
        y: edges[k + 1],
        width: r4(width),
        height: r4(edges[k] - edges[k + 1])
      };
    });
  }

  /** 지층 기둥을 `<g>` 조각으로. 색은 band.className 이 CSS 에서 받는다. */
  function strataColumn(bands, opts) {
    opts = opts || {};
    var laid = strataLayout(bands, opts);
    var body = laid.map(function (b) {
      return tag("rect", {
        x: b.x, y: b.y, width: b.width, height: b.height,
        "data-key": b.key,
        class: "stratum" + (b.className ? " " + b.className : "")
      });
    }).join("");
    if (opts.labels) {
      var lx = r4(opts.x + opts.width + (opts.labelGap || 12));
      body += laid.map(function (b) {
        if (b.height < (opts.labelMinHeight || 14)) return "";
        return text(lx, r4(b.y + b.height / 2 + 4), b.label || b.key,
                    { class: "lab lab-stratum" });
      }).join("");
    }
    return tag("g", { class: "strata", "data-part": "strata" }, body);
  }

  // ── 수면 ────────────────────────────────────────────────────────────────
  /**
   * 부채의 수면이 놓일 자리.
   *
   * 물이 기둥을 넘거나(부채가 가치를 넘는다) 바닥 아래로 내려가면 좌표는 잘라
   * 두되 `overflow`·`underflow` 표식을 남긴다 — 잘린 사실이 값에서 사라지면
   * 화면은 "가득 찼다"와 "넘쳤다"를 같은 그림으로 그린다.
   */
  function waterlineGeom(level, opts) {
    opts = opts || {};
    fin(level, "수면의 높이");
    var y = opts.y === undefined ? 0 : fin(opts.y, "기둥의 y");
    var height = positive(opts.height, "기둥의 높이");
    var total = positive(opts.total, "기둥의 전체");
    var raw = level / total;
    var share = Math.min(1, Math.max(0, raw));
    return {
      level: level,
      share: r4(share),
      y: r4(y + height * (1 - share)),
      depth: r4(height * share),
      overflow: raw > 1,
      underflow: raw < 0
    };
  }

  /**
   * 수면 조각 — 물이 찬 면, 잔물결이 이는 선, 그리고 표식.
   *
   * 선을 매끈한 직선으로 그으면 그것은 눈금이지 물이 아니다. 얕은 사인 곡선
   * 하나가 "차오른다"는 말을 그림으로 옮긴다.
   */
  function waterline(level, opts) {
    opts = opts || {};
    var g = waterlineGeom(level, opts);
    var x0 = fin(opts.x0, "수면의 왼쪽"), x1 = fin(opts.x1, "수면의 오른쪽");
    // y 의 기본값은 `waterlineGeom` 과 같은 0 이다. 여기서만 엄격하면 같은 opts 로
    // 좌표는 나오는데 그림은 NaN path 가 되어 물이 조용히 사라진다.
    var boxY = opts.y === undefined ? 0 : opts.y;
    var bottom = r4(boxY + opts.height);
    var amp = opts.amplitude === undefined ? 2.2 : opts.amplitude;
    var waves = Math.max(2, opts.waves || 8);
    var step = (x1 - x0) / waves;

    var d = "M" + r4(x0) + " " + g.y;
    for (var i = 0; i < waves; i += 1) {
      var half = step / 2;
      var up = i % 2 === 0 ? -amp : amp;
      d += " q" + r4(half) + " " + r4(up) + " " + r4(step) + " 0";
    }
    var surface = tag("path", { d: d, class: "water-line" });
    var body = tag("path", {
      d: d + " L" + r4(x1) + " " + bottom + " L" + r4(x0) + " " + bottom + " Z",
      class: "water-body"
    });
    return tag("g", { class: "water", "data-part": "water" }, body + surface);
  }

  // ── 혼자 서는 그림 ──────────────────────────────────────────────────────
  function svgWrap(w, h, aria, cls, inner, par) {
    return tag("svg", {
      viewBox: "0 0 " + r4(w) + " " + r4(h),
      role: "img",
      "aria-label": aria || "",
      class: cls,
      preserveAspectRatio: par || "xMidYMid meet"
    }, inner);
  }

  /** 스파크라인 — 축도 눈금도 없다. 모양만 남긴 12개월. */
  function spark(values, opts) {
    opts = opts || {};
    var w = opts.width || 120, h = opts.height || 28, pad = opts.pad || 2.5;
    var nums = values.filter(function (v) {
      return typeof v === "number" && isFinite(v);
    });
    if (!nums.length) return svgWrap(w, h, opts.aria || "", "spark", "");
    var ex = opts.domain || extent(nums);
    var x = scaleLinear(0, Math.max(1, values.length - 1), pad, w - pad);
    var y = scaleLinear(ex[0], ex[1], h - pad, pad);

    var d = "", pen = false, lastX = 0, lastY = 0;
    for (var i = 0; i < values.length; i += 1) {
      var v = values[i];
      if (typeof v !== "number" || !isFinite(v)) { pen = false; continue; }
      lastX = r4(x(i)); lastY = r4(y(v));
      d += (pen ? " L" : (d ? " M" : "M")) + lastX + " " + lastY;
      pen = true;
    }
    var inner = tag("path", { d: d, class: "spark-line" });
    if (opts.dot !== false) {
      inner += tag("circle", { cx: lastX, cy: lastY, r: 2, class: "spark-dot" });
    }
    // stretch: 상자를 꽉 채운다. 스파크는 값을 재는 그림이 아니라 모양이라
    // 가로로 늘어나도 읽는 데 지장이 없고, 비율을 지키면 좌우에 빈자리가 남는다.
    // 선 굵기는 CSS 의 non-scaling-stroke 가 지킨다.
    return svgWrap(w, h, opts.aria || "", "spark", inner,
                   opts.stretch ? "none" : null);
  }

  /**
   * 다계열 선 그래프. x 는 라벨의 순번이고, 계열은 라벨을 공유해야 한다.
   *
   * `opts.rules` 로 수평 기준선을 얹는다 — 시계열이 아닌 한 시점의 값(권역 cap
   * 같은)을 시계열 위에 놓을 때 쓰고, 파선으로 그려 "이것은 흐르지 않는다"를
   * 형태로 밝힌다.
   */
  function line(series, opts) {
    opts = opts || {};
    var w = opts.width || 640, h = opts.height || 220;
    var m = Object.assign({ t: 14, r: 96, b: 26, l: 44 }, opts.margin || {});
    series = (series || []).filter(function (s) {
      return s && s.points && s.points.length;
    });
    if (!series.length) return svgWrap(w, h, opts.aria || "", "chart", "");

    var n = Math.max.apply(null, series.map(function (s) {
      return s.points.length;
    }));
    var ys = [];
    series.forEach(function (s) {
      s.points.forEach(function (p) { ys.push(p.y); });
    });
    (opts.rules || []).forEach(function (r) { ys.push(r.value); });
    var ex = opts.yDomain || extent(ys);
    var padY = (ex[1] - ex[0]) * (opts.yPad === undefined ? 0.12 : opts.yPad);
    var y = scaleLinear(ex[0] - padY, ex[1] + padY, h - m.b, m.t);
    var x = scaleLinear(0, Math.max(1, n - 1), m.l, w - m.r);

    var inner = "";
    niceTicks(ex[0] - padY, ex[1] + padY, opts.ticks || 4).forEach(function (tv) {
      inner += tag("line", {
        x1: m.l, x2: w - m.r, y1: r4(y(tv)), y2: r4(y(tv)), class: "grid"
      });
      inner += text(m.l - 8, r4(y(tv)) + 4,
                    opts.yFmt ? opts.yFmt(tv) : String(r4(tv)),
                    { class: "lab lab-num", "text-anchor": "end" });
    });

    var labels = series[0].points;
    var marks = n <= 2 ? [0, n - 1] : [0, Math.floor((n - 1) / 2), n - 1];
    marks.filter(function (v, i, a) { return a.indexOf(v) === i; })
      .forEach(function (i) {
        if (!labels[i]) return;
        inner += text(r4(x(i)), h - 7, labels[i].label, {
          class: "lab",
          "text-anchor": i === 0 ? "start" : (i === n - 1 ? "end" : "middle")
        });
      });

    // 기준선의 라벨은 오른쪽이 아니라 선 위 왼쪽에 붙인다 — 오른쪽 여백은
    // 계열 직접 라벨의 자리이고, 둘이 겹치면 값이 서로를 지운다.
    (opts.rules || []).forEach(function (rule) {
      var ry = r4(y(rule.value));
      inner += tag("line", {
        x1: m.l, x2: w - m.r, y1: ry, y2: ry,
        class: "rule" + (rule.className ? " " + rule.className : "")
      });
      if (rule.label) {
        inner += text(m.l + 5, ry - 5, rule.label, { class: "lab lab-rule" });
      }
    });

    // 계열 직접 라벨은 끝점 높이에 붙지만, 두 계열의 끝값이 가까우면 글자가
    // 겹친다. 위에서부터 최소 간격만큼 밀어 낸다(값은 그대로, 글자만 비킨다).
    var ends = [];
    series.forEach(function (s) {
      var d = "", pen = false, endX = 0, endY = 0;
      s.points.forEach(function (p, i) {
        if (typeof p.y !== "number" || !isFinite(p.y)) { pen = false; return; }
        endX = r4(x(i)); endY = r4(y(p.y));
        d += (pen ? " L" : (d ? " M" : "M")) + endX + " " + endY;
        pen = true;
      });
      if (!d) return;
      var cls = s.className ? " " + s.className : "";
      inner += tag("path", { d: d, class: "series" + cls, "data-key": s.key });
      inner += tag("circle", { cx: endX, cy: endY, r: 2.6, class: "series-end" + cls });
      if (s.label) ends.push({ x: endX, y: endY, label: s.label, cls: cls });
    });
    ends.sort(function (a, b) { return a.y - b.y; });
    var gap = opts.labelGap || 14;
    for (var e = 1; e < ends.length; e += 1) {
      if (ends[e].y - ends[e - 1].y < gap) ends[e].y = r4(ends[e - 1].y + gap);
    }
    ends.forEach(function (p) {
      inner += text(p.x + 7, p.y + 3.5, p.label, { class: "lab lab-series" + p.cls });
    });
    return svgWrap(w, h, opts.aria || "", "chart" + (opts.compact ? " is-compact" : ""),
                   inner);
  }

  /** 산점 — Ⅰ장의 실거래·추정가치 대조가 쓴다. */
  function scatter(points, opts) {
    opts = opts || {};
    var w = opts.width || 480, h = opts.height || 320;
    var m = Object.assign({ t: 12, r: 16, b: 28, l: 48 }, opts.margin || {});
    var xs = points.map(function (p) { return p.x; });
    var ys = points.map(function (p) { return p.y; });
    var xe = opts.xDomain || extent(xs), ye = opts.yDomain || extent(ys);
    var x = scaleLinear(xe[0], xe[1], m.l, w - m.r);
    var y = scaleLinear(ye[0], ye[1], h - m.b, m.t);

    var inner = "";
    niceTicks(ye[0], ye[1], 4).forEach(function (tv) {
      inner += tag("line", {
        x1: m.l, x2: w - m.r, y1: r4(y(tv)), y2: r4(y(tv)), class: "grid"
      });
    });
    points.forEach(function (p) {
      if (typeof p.x !== "number" || typeof p.y !== "number") return;
      inner += tag("circle", {
        cx: r4(x(p.x)), cy: r4(y(p.y)), r: p.r || 3.2,
        class: "dot" + (p.className ? " " + p.className : ""),
        "data-key": p.key
      });
    });
    return svgWrap(w, h, opts.aria || "", "chart", inner);
  }

  /** 막대 — 세로. 지층과 헷갈리지 않게 항상 바닥에서 자란다. */
  function bar(items, opts) {
    opts = opts || {};
    var w = opts.width || 320, h = opts.height || 160;
    var m = Object.assign({ t: 12, r: 8, b: 22, l: 8 }, opts.margin || {});
    var vals = items.map(function (d) { return d.value; });
    var hi = opts.max === undefined ? Math.max.apply(null, vals.concat([0])) : opts.max;
    var base = h - m.b;
    var slot = (w - m.l - m.r) / Math.max(1, items.length);
    var bw = slot * (opts.fill === undefined ? 0.62 : opts.fill);

    var inner = "";
    items.forEach(function (d, i) {
      var bh = hi > 0 ? ((d.value || 0) / hi) * (base - m.t) : 0;
      var bx = m.l + slot * i + (slot - bw) / 2;
      inner += tag("rect", {
        x: r4(bx), y: r4(base - bh), width: r4(bw), height: r4(Math.max(0, bh)),
        class: "bar" + (d.className ? " " + d.className : ""), "data-key": d.key
      });
      if (d.label) {
        inner += text(r4(bx + bw / 2), h - 6, d.label,
                      { class: "lab", "text-anchor": "middle" });
      }
    });
    return svgWrap(w, h, opts.aria || "", "chart", inner);
  }

  return {
    esc: esc, attrs: attrs, tag: tag, text: text,
    extent: extent, niceTicks: niceTicks, scaleLinear: scaleLinear, r4: r4,
    strataLayout: strataLayout, strataColumn: strataColumn,
    waterlineGeom: waterlineGeom, waterline: waterline,
    line: line, spark: spark, scatter: scatter, bar: bar
  };
});
