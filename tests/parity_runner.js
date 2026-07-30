/**
 * 패리티 러너 — stdin 의 케이스 배열을 `site/js/engine.js` 로 돌려 stdout 에 낸다.
 *
 * 입력: `[{"fn": "noi", "args": [...]}, ...]` (JSON 배열, stdin)
 * 출력: `[{"ok": true, "value": ...} | {"ok": false, "error": 종류, "message": "..."}, ...]`
 *
 * `tests/test_parity.py` 가 이 프로세스를 한 번만 띄워 전 케이스를 왕복시킨다.
 * 케이스마다 node 를 새로 띄우면 200조에 200번 프로세스가 뜬다.
 *
 * 오류 종류는 파이썬 예외에 1:1 로 대응한다.
 *
 *   RangeError            → gate            (파이썬 RuntimeError — 물리 게이트)
 *   TypeError             → input           (파이썬 ValueError   — 입력 오류)
 *   Error("미구현 …")     → not_implemented (파이썬 NotImplementedError)
 *
 * **분기 순서가 파이썬과 반대다.** 파이썬에서는 NotImplementedError 가
 * RuntimeError 의 하위형이라 좁은 쪽을 먼저 잡아야 하지만, 자바스크립트에서는
 * RangeError·TypeError 가 Error 의 하위형이라 **좁은 쪽(RangeError·TypeError)을
 * 먼저** 보고 밋밋한 Error 를 나중에 봐야 한다. 뒤집으면 세 갈래가 한 갈래로
 * 뭉개진다.
 */

"use strict";

const fs = require("fs");
const path = require("path");

const engine = require(path.join(__dirname, "..", "site", "js", "engine.js"));

const FUNCTIONS = [
  "effective_rent",
  "building_adjust",
  "noi",
  "appraise",
  "implied",
  "max_loan",
  "hold_model",
  "refi_test",
  "breakeven_vacancy",
];

function kindOf(err) {
  // 좁은 유형부터 — 순서를 뒤집으면 전부 not_implemented 로 뭉개진다.
  if (err instanceof RangeError) return "gate";
  if (err instanceof TypeError) return "input";
  if (err instanceof Error && String(err.message).indexOf("미구현") !== -1) {
    return "not_implemented";
  }
  return "other";
}

/**
 * NaN·±무한대는 JSON 이 실어 나르지 못한다(파이썬 `json` 은 `NaN` 을 쓰고
 * `JSON.parse` 는 그것을 거절한다). 유한성 가드는 엔진의 방어선 하나라 검증을
 * 포기하지 않고, 대신 세 표식을 정해 양쪽에서 같은 값으로 되돌린다.
 */
const SENTINELS = { __nan__: NaN, __inf__: Infinity, "__-inf__": -Infinity };

function decode(arg) {
  if (typeof arg === "string" && Object.prototype.hasOwnProperty.call(SENTINELS, arg)) {
    return SENTINELS[arg];
  }
  return arg;
}

function runCase(spec) {
  const name = spec.fn;
  if (FUNCTIONS.indexOf(name) === -1) {
    throw new Error("패리티 대상이 아닌 함수다: " + name);
  }
  try {
    return { ok: true, value: engine[name].apply(null, spec.args.map(decode)) };
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
