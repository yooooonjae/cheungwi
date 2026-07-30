#!/usr/bin/env node
/*
 * responsive_check.js — 다섯 뷰포트에서 지면을 실제로 재는 검사.
 *
 * pytest 는 문자열과 좌표를 붙들지만, **폭이 만드는 결함**은 브라우저가 그려
 * 봐야만 보인다. 겹치는 눈금 라벨, 판형을 넘는 도면 글자, 8px 로 찍히는 라벨,
 * 화면 밖으로 삐져나온 표 — 넷 다 소스만 읽어서는 통과한다.
 *
 * 재는 것 넷:
 *   ① 가로 오버플로 0        document.scrollWidth ≤ clientWidth (+1px 여유)
 *   ② 터치 타깃 ≥ 44px       보이는 조작 요소 전부
 *   ③ 도면 활자              실렌더 ≥ 9px 이고 viewBox 안에 있다
 *   ④ 눈금 라벨 겹침 0       「기준」 글자가 최소·최대 라벨 위에 올라타지 않는다
 * 그리고 뷰포트마다 **다크 모드 스크린샷**을 남긴다(사람이 볼 몫).
 *
 * ── ⑤ 생존 신호(위 넷보다 먼저 봐야 하는 것) ──
 * 위의 넷은 전부 **위반을 세는** 검사다. 그래서 지면이 통째로 비면 — 스크립트가
 * 전부 던져 아무것도 그려지지 않으면 — 잴 요소가 없어 위반도 0 이고, 검사는
 * 5/5 초록으로 통과한다. 빈 지면이 가장 반응형인 지면이 되는 것이다.
 * 그래서 뷰포트마다 **살아 있다는 증거**를 함께 단언한다.
 *
 *   · 도면(viewBox 를 가진 svg)이 하한 이상 그려졌는가
 *   · 원장 표(#method-manifest tbody)에 행이 있는가
 *   · 눈금(.knob-scale)이 셋 이상인가
 *   · `Runtime.exceptionThrown` 이 0 건인가 (스크립트가 조용히 죽지 않았는가)
 *   · `.fail` 요소가 0 개인가 (지면이 스스로 "그리지 못했다"고 적지 않았는가)
 *
 * 하나라도 무너지면 그 뷰포트는 실패다. 폭 문제가 아니라 지면 문제지만, 폭
 * 문제만 보는 검사는 지면이 사라진 것을 끝내 못 본다.
 *
 * ── 헤드리스 함정 셋(앞선 태스크가 남긴 것) ──
 *   · `--window-size=390` 은 500px 로 클램프된다. 그래서 창 크기가 아니라
 *     CDP `Emulation.setDeviceMetricsOverride` 로 뷰포트를 만든다 — iframe
 *     우회가 필요 없어진다.
 *   · macOS 에 `timeout` 이 없다. 여기서는 프로세스를 직접 죽인다.
 *   · Chrome 을 두 대 동시에 띄우면 둘 다 멎는다. 이 스크립트는 한 대만 띄우고,
 *     다른 헤드리스 잡과 겹쳐 돌리지 말 것.
 *
 * 실행: node tests/responsive_check.js   (make responsive)
 *   RESP_TARGET  검사할 파일(기본 web/index.html)
 *   RESP_SHOTS   스크린샷 디렉터리(기본 <tmp>/cheungwi-responsive)
 *   RESP_NO_SHOT 1 이면 스크린샷을 건너뛴다
 */
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { pathToFileURL } = require("node:url");

const ROOT = path.resolve(__dirname, "..");
const TARGET = process.env.RESP_TARGET
  ? path.resolve(process.env.RESP_TARGET)
  : path.join(ROOT, "web", "index.html");
const SHOTS = process.env.RESP_SHOTS
  ? path.resolve(process.env.RESP_SHOTS)
  : path.join(os.tmpdir(), "cheungwi-responsive");

// 계획서가 정한 다섯 폭. 390 은 손, 768 은 접힌 판, 1024~1440 은 책상이다.
const VIEWPORTS = [
  { w: 390, h: 844 }, { w: 768, h: 1024 }, { w: 1024, h: 768 },
  { w: 1280, h: 900 }, { w: 1440, h: 900 },
];

// 손이 닿는 것은 전부 44px 이어야 한다 — 폭에 관계없이(마우스도 44px 을 싫어하지 않는다).
const TOUCH = [".brand", ".tabs a", ".theme-toggle", ".r-tab", ".rig-reset",
               ".exp-reset", ".exp-num", ".knob-range"];
const MIN_TOUCH = 44;
// 도면 인-피겨 라벨의 하한. 이보다 작으면 종이에서 읽히지 않는다.
const MIN_LABEL = 9;
/**
 * 생존 하한. 뷰포트마다 **적어도 이만큼은 그려져 있어야** 나머지 측정이 뜻을 갖는다.
 *
 * 도면 8 은 좁은 판형에서도 남는 수다(서장 계기판·Ⅰ장 산점과 사다리·Ⅱ장 계측기·
 * Ⅲ장 단면과 스트레스·방법론 사다리…). 넉넉히 잡되 "한 장도 없다"와 "반이
 * 사라졌다"를 둘 다 잡을 만큼은 높게 둔다. 눈금 셋은 Ⅱ장과 실험실의 조작부다.
 */
const ALIVE_MIN = { figs: 8, manifestRows: 1, knobs: 3 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findChrome() {
  const cands = [
    process.env.CHROME, process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
  ].filter(Boolean);
  for (const c of cands) { try { if (fs.existsSync(c)) return c; } catch { /* 없으면 다음 */ } }
  for (const bin of ["google-chrome", "chromium", "chrome"]) {
    const r = spawnSync(process.platform === "win32" ? "where" : "which", [bin],
                        { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim()) return r.stdout.trim().split("\n")[0];
  }
  return null;
}

/** 의존성 없는 최소 CDP 클라이언트(Node 내장 WebSocket). */
class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0; this.pending = new Map(); this.waiters = new Map();
    // 페이지가 조용히 던진 예외를 여기 모은다 — 콘솔은 헤드리스에서 아무도 안 본다.
    this.thrown = [];
    this.ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) rej(new Error(m.error.message)); else res(m.result);
        return;
      }
      if (m.method === "Runtime.exceptionThrown") {
        const d = (m.params && m.params.exceptionDetails) || {};
        const one = (d.exception && (d.exception.description || d.exception.value)) ||
          d.text || "알 수 없는 예외";
        this.thrown.push(String(one).split("\n")[0].slice(0, 120));
      }
      if (m.method && this.waiters.has(m.method)) {
        const w = this.waiters.get(m.method); this.waiters.delete(m.method); w();
      }
    });
  }
  ready() {
    return new Promise((res, rej) => {
      this.ws.addEventListener("open", () => res());
      this.ws.addEventListener("error", () => rej(new Error("WebSocket 오류")));
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  wait(method) { return new Promise((res) => this.waiters.set(method, res)); }
  close() { try { this.ws.close(); } catch { /* 이미 닫혔다 */ } }
}

async function waitReady(port) {
  for (let i = 0; i < 150; i += 1) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (r.ok) return;
    } catch { /* 아직 안 떴다 */ }
    await sleep(100);
  }
  throw new Error("Chrome DevTools 엔드포인트가 응답하지 않는다");
}

async function pageWsUrl(port) {
  const r = await fetch(`http://127.0.0.1:${port}/json`);
  const list = await r.json();
  const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
  if (!page) throw new Error("page 타깃이 없다");
  return page.webSocketDebuggerUrl;
}

/**
 * 페이지 안에서 도는 측정기. 여기서 나오는 수가 이 검사의 전부다.
 *
 * SVG 안의 `font-size` 는 화면 px 이 아니다 — 도면은 viewBox 를 실폭에 맞춰
 * 통째로 늘이거나 줄이므로, 실렌더 크기는 선언값 × (실폭 ÷ viewBox 폭)이다.
 */
const PROBE = `(() => {
  const de = document.documentElement;
  const out = { sw: de.scrollWidth, cw: de.clientWidth, touch: [], labels: [],
                overlap: [], figs: 0, manifestRows: 0, knobs: 0, fails: [] };

  // ── 생존 신호 — 이 지면이 실제로 그려져 있는가 ──
  // 아래의 위반 계수기들은 요소가 없으면 전부 0 이 된다. 그러니 "무엇이 있는가"를
  // 먼저 센다. 여기가 무너진 뷰포트에서는 나머지 0 이 통과의 근거가 아니다.
  for (const svg of document.querySelectorAll("svg")) {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    if (!vb || !vb.width) continue;
    if (svg.getBoundingClientRect().width > 0) out.figs += 1;
  }
  const manifest = document.getElementById("method-manifest");
  if (manifest) out.manifestRows = manifest.querySelectorAll("tbody tr").length;
  out.knobs = document.querySelectorAll(".knob-scale").length;
  for (const f of document.querySelectorAll(".fail")) {
    out.fails.push(f.textContent.trim().slice(0, 90));
  }

  const seen = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  for (const sel of ${JSON.stringify(TOUCH)}) {
    for (const el of document.querySelectorAll(sel)) {
      if (!seen(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.height < ${MIN_TOUCH} - 0.5) {
        out.touch.push(sel + " " + r.height.toFixed(1) + "px");
      }
    }
  }

  for (const svg of document.querySelectorAll("svg.ch-fig, svg.plate-svg, .chart")) {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    if (!vb || !vb.width) continue;
    const rect = svg.getBoundingClientRect();
    if (!rect.width) continue;
    const k = rect.width / vb.width;
    for (const t of svg.querySelectorAll("text")) {
      if (!t.textContent.trim()) continue;
      const px = parseFloat(getComputedStyle(t).fontSize) * k;
      if (px < ${MIN_LABEL} - 0.05) {
        out.labels.push("작다 " + px.toFixed(2) + "px «" + t.textContent.slice(0, 14) + "»");
      }
      let bb = null;
      try { bb = t.getBBox(); } catch (e) { bb = null; }
      if (bb && (bb.x < vb.x - 1 || bb.x + bb.width > vb.x + vb.width + 1)) {
        out.labels.push("판형 밖 «" + t.textContent.slice(0, 14) + "»");
      }
    }
  }

  // 눈금의 「기준」 글자가 최소·최대 라벨 위에 올라타면 둘 다 못 읽는다.
  for (const scale of document.querySelectorAll(".knob-scale")) {
    const rest = scale.querySelector(".knob-rest");
    if (!rest || !seen(rest)) continue;
    const a = rest.getBoundingClientRect();
    for (const other of scale.children) {
      if (other === rest || !seen(other)) continue;
      const b = other.getBoundingClientRect();
      const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (dx > 0.5 && dy > 0.5) {
        out.overlap.push("«" + rest.textContent.trim() + "» ↔ «" +
          other.textContent.trim() + "» " + dx.toFixed(1) + "×" + dy.toFixed(1) + "px");
      }
    }
  }
  return JSON.stringify(out);
})()`;

async function shoot(ws, file, vp) {
  const box = await ws.send("Runtime.evaluate", {
    expression: `(() => {
      const el = document.getElementById("method") || document.body;
      const r = el.getBoundingClientRect();
      return JSON.stringify({ y: r.top + scrollY, h: Math.min(r.height, 4200) });
    })()`,
    returnByValue: true,
  });
  const { y, h } = JSON.parse(box.result.value);
  const shot = await ws.send("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: true,
    clip: { x: 0, y: Math.max(0, y), width: vp.w, height: Math.max(200, h), scale: 1 },
  });
  fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
}

async function main() {
  if (typeof WebSocket === "undefined") {
    console.error("✗ 이 Node 에는 내장 WebSocket 이 없다 — Node 22+ 로 돌려라");
    process.exit(1);
  }
  if (!fs.existsSync(TARGET)) {
    console.error(`✗ 대상이 없다: ${path.relative(ROOT, TARGET)} — make build 를 먼저 돌려라`);
    process.exit(1);
  }
  const chrome = findChrome();
  if (!chrome) {
    console.error("✗ Chrome/Chromium 을 찾지 못했다 — 반응형 검사를 건너뛰지 않는다");
    process.exit(1);
  }

  const port = 9200 + Math.floor(Math.random() * 700);
  // 프로필은 매번 새로 만든다 — 재사용하면 두 번째 실행이 걸린다.
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), "cheungwi-resp-"));
  const proc = spawn(chrome, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
    "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--hide-scrollbars",
    `--remote-debugging-port=${port}`, `--user-data-dir=${udd}`, "about:blank",
  ], { stdio: "ignore" });

  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    try { proc.kill("SIGKILL"); } catch { /* 이미 죽었다 */ }
    try { fs.rmSync(udd, { recursive: true, force: true }); } catch { /* 지워졌다 */ }
  };
  process.on("exit", cleanup);
  process.on("SIGINT", () => { cleanup(); process.exit(130); });

  const noShot = process.env.RESP_NO_SHOT === "1";
  if (!noShot) fs.mkdirSync(SHOTS, { recursive: true });

  let exitCode = 0;
  try {
    await waitReady(port);
    const ws = new CDP(await pageWsUrl(port));
    await ws.ready();
    await ws.send("Page.enable");
    await ws.send("Runtime.enable");

    const url = pathToFileURL(TARGET).href;
    const rows = [];
    for (const vp of VIEWPORTS) {
      // 창 크기가 아니라 **에뮬레이션**으로 뷰포트를 만든다 — 390 클램프를 지나간다.
      await ws.send("Emulation.setDeviceMetricsOverride", {
        width: vp.w, height: vp.h, deviceScaleFactor: 1, mobile: false,
      });
      const loaded = ws.wait("Page.loadEventFired");
      ws.thrown.length = 0;   // 이 뷰포트가 던진 것만 센다
      await ws.send("Page.navigate", { url });
      await Promise.race([loaded, sleep(9000)]);
      await sleep(700);   // defer 스크립트가 그림을 그리고 계수를 잴 시간

      const res = await ws.send("Runtime.evaluate", {
        expression: PROBE, returnByValue: true,
      });
      if (res.exceptionDetails) {
        throw new Error("측정 중 예외: " +
          ((res.result && res.result.description) || "알 수 없음"));
      }
      const r = JSON.parse(res.result.value);
      r.vp = `${vp.w}×${vp.h}`;
      r.overflow = r.sw > r.cw + 1;
      r.thrown = ws.thrown.slice();
      // 생존 하한을 못 넘긴 신호만 문장으로 남긴다 — 폭이 아니라 지면의 문제다.
      r.dead = [];
      if (r.figs < ALIVE_MIN.figs) {
        r.dead.push(`도면 ${r.figs}장 < 하한 ${ALIVE_MIN.figs}장 — 그려진 그림이 없다`);
      }
      if (r.manifestRows < ALIVE_MIN.manifestRows) {
        r.dead.push(`원장 표 ${r.manifestRows}행 — 방법론이 마운트되지 않았다`);
      }
      if (r.knobs < ALIVE_MIN.knobs) {
        r.dead.push(`눈금 ${r.knobs}개 < 하한 ${ALIVE_MIN.knobs}개 — 조작부가 없다`);
      }
      for (const t of r.thrown) r.dead.push("예외 " + t);
      for (const f of r.fails) r.dead.push("지면이 실패를 적었다: " + f);
      rows.push(r);

      if (!noShot) {
        // 다크는 뷰어의 선택이 시스템 설정을 이기는 경로 그대로 심는다.
        await ws.send("Runtime.evaluate", {
          expression: 'document.documentElement.dataset.theme = "dark";',
        });
        await sleep(200);
        await shoot(ws, path.join(SHOTS, `method-dark-${vp.w}.png`), vp);
      }
    }
    ws.close();

    console.log(`\n반응형 검사 — ${path.relative(ROOT, TARGET)}`);
    console.log("  뷰포트        scrollW  clientW  가로넘침  터치<44px  도면활자  눈금겹침  생존");
    console.log("  " + "-".repeat(84));
    let failed = 0;
    for (const r of rows) {
      const bad = r.overflow || r.touch.length || r.labels.length ||
        r.overlap.length || r.dead.length;
      if (bad) failed += 1;
      console.log("  " + r.vp.padEnd(12) +
        String(r.sw).padStart(6) + "  " + String(r.cw).padStart(7) + "  " +
        (r.overflow ? "✗ 있음" : "✓ 없음").padEnd(9) + "  " +
        (r.touch.length ? "✗ " + r.touch.length : "✓ 0").padEnd(9) + "  " +
        (r.labels.length ? "✗ " + r.labels.length : "✓ 0").padEnd(8) + "  " +
        (r.overlap.length ? "✗ " + r.overlap.length : "✓ 0").padEnd(8) + "  " +
        (r.dead.length ? "✗ " + r.dead.length : "✓ 살아 있다"));
      for (const line of [...r.touch, ...r.labels, ...r.overlap, ...r.dead]) {
        console.log("      · " + line);
      }
    }

    // 무엇이 그려져 있었는지를 통과할 때도 적는다 — 0 이 통과의 근거가 되려면
    // 잴 것이 있었다는 사실이 함께 남아야 한다.
    console.log("\n  생존 신호(도면 · 원장 표 · 눈금 · 예외 · 실패 표시)");
    for (const r of rows) {
      console.log("    " + r.vp.padEnd(12) +
        `도면 ${r.figs}장 · 원장 ${r.manifestRows}행 · 눈금 ${r.knobs}개 · ` +
        `예외 ${r.thrown.length}건 · .fail ${r.fails.length}개`);
    }

    if (!noShot) console.log(`\n  다크 스크린샷: ${SHOTS}`);
    if (failed) {
      console.error(`\n✗ 반응형 검사 실패 — ${failed}/${rows.length} 뷰포트`);
      exitCode = 1;
    } else {
      console.log(`\n✓ 반응형 검사 통과 — ${rows.length} 뷰포트 · 가로 오버플로 0 · ` +
        `터치 ≥ ${MIN_TOUCH}px · 도면 활자 ≥ ${MIN_LABEL}px · 눈금 겹침 0 · ` +
        `도면 ≥ ${ALIVE_MIN.figs}장 · 예외 0`);
    }
  } catch (err) {
    console.error("✗ 반응형 검사 오류:", err.message);
    exitCode = 1;
  } finally {
    cleanup();
  }
  process.exit(exitCode);
}

main();
