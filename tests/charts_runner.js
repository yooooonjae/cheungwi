/**
 * 조형 러너 — stdin 의 케이스 배열을 `site/js/charts.js`·`site/js/hero.js` 로
 * 돌려 stdout 에 낸다. `tests/parity_runner.js` 와 같은 왕복 규약이다.
 *
 * 입력: `[{"mod": "charts", "fn": "strataLayout", "args": [...]}, ...]`
 * 출력: `[{"ok": true, "value": ...} | {"ok": false, "error": 종류, "message": "..."}]`
 *
 * 두 파일의 **순수 함수**만 검사한다 — 좌표를 내는 계산과 문자열을 짓는 계산은
 * DOM 없이도 전부 확인할 수 있고, 그 둘이 이 조형의 실체이기 때문이다. DOM 을
 * 만지는 `mount` 는 여기서 부르지 않는다(브라우저 검사는 반응형 스크립트 몫).
 *
 * 오류 종류는 엔진 러너와 같은 갈래를 쓴다.
 *   TypeError  → input   (입력이 틀렸다)
 *   RangeError → gate    (물리 게이트 — 좌표계가 성립하지 않는다)
 */

"use strict";

const fs = require("fs");
const path = require("path");

const MODULES = {
  // 엔진도 여기서 부를 수 있어야 한다 — 장이 내놓은 판독값을 엔진 원본과 **직접**
  // 대조하려면 같은 프로세스에서 두 쪽을 다 불러야 하기 때문이다(IRR 의 기준처럼
  // 장이 인자를 고쳐 넣는 자리는 대조 없이는 조용히 어긋난다).
  engine: require(path.join(__dirname, "..", "site", "js", "engine.js")),
  charts: require(path.join(__dirname, "..", "site", "js", "charts.js")),
  hero: require(path.join(__dirname, "..", "site", "js", "hero.js")),
  chapter1: require(path.join(__dirname, "..", "site", "js", "chapter1.js")),
  chapter2: require(path.join(__dirname, "..", "site", "js", "chapter2.js")),
  chapter3: require(path.join(__dirname, "..", "site", "js", "chapter3.js")),
  lab: require(path.join(__dirname, "..", "site", "js", "lab.js")),
};

function kindOf(err) {
  // 좁은 유형부터 — 뒤집으면 세 갈래가 한 갈래로 뭉개진다.
  if (err instanceof RangeError) return "gate";
  if (err instanceof TypeError) return "input";
  return "other";
}

function runCase(spec) {
  const mod = MODULES[spec.mod];
  if (!mod) throw new Error("모르는 모듈이다: " + spec.mod);
  const fn = mod[spec.fn];
  if (typeof fn !== "function") {
    throw new Error("함수가 아니다: " + spec.mod + "." + spec.fn);
  }
  try {
    return { ok: true, value: fn.apply(null, spec.args || []) };
  } catch (err) {
    return {
      ok: false,
      error: kindOf(err),
      message: err && err.message ? String(err.message) : "",
    };
  }
}

function main() {
  const cases = JSON.parse(fs.readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify(cases.map(runCase)));
}

main();
