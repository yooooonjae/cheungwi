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
    this.ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) rej(new Error(m.error.message)); else res(m.result);
      } else if (m.method && this.waiters.has(m.method)) {
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
  const out = { sw: de.scrollWidth, cw: de.clientWidth, touch: [], labels: [], overlap: [] };

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
      await ws.send("Page.navigate", { url });
      await Promise.race([loaded, sleep(9000)]);
      await sleep(700);   // defer 스크립트가 그림을 그리고 계수를 잴 시간

      const res = await ws.send("Runtime.evaluate", {
        expression: PROBE, returnByValue: true,
      });
      if (res.exceptionDetails) {
        throw new Error("측정 중 예외: " +
          (res.result && res.result.description) || "알 수 없음");
      }
      const r = JSON.parse(res.result.value);
      r.vp = `${vp.w}×${vp.h}`;
      r.overflow = r.sw > r.cw + 1;
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
    console.log("  뷰포트        scrollW  clientW  가로넘침  터치<44px  도면활자  눈금겹침");
    console.log("  " + "-".repeat(76));
    let failed = 0;
    for (const r of rows) {
      const bad = r.overflow || r.touch.length || r.labels.length || r.overlap.length;
      if (bad) failed += 1;
      console.log("  " + r.vp.padEnd(12) +
        String(r.sw).padStart(6) + "  " + String(r.cw).padStart(7) + "  " +
        (r.overflow ? "✗ 있음" : "✓ 없음").padEnd(9) + "  " +
        (r.touch.length ? "✗ " + r.touch.length : "✓ 0").padEnd(9) + "  " +
        (r.labels.length ? "✗ " + r.labels.length : "✓ 0").padEnd(8) + "  " +
        (r.overlap.length ? "✗ " + r.overlap.length : "✓ 0"));
      for (const line of [...r.touch, ...r.labels, ...r.overlap]) {
        console.log("      · " + line);
      }
    }
    if (!noShot) console.log(`\n  다크 스크린샷: ${SHOTS}`);
    if (failed) {
      console.error(`\n✗ 반응형 검사 실패 — ${failed}/${rows.length} 뷰포트`);
      exitCode = 1;
    } else {
      console.log(`\n✓ 반응형 검사 통과 — ${rows.length} 뷰포트 · 가로 오버플로 0 · ` +
        `터치 ≥ ${MIN_TOUCH}px · 도면 활자 ≥ ${MIN_LABEL}px · 눈금 겹침 0`);
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
