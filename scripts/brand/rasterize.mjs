// Headless Chrome renders for scripts/brand/build_brand.py.
//
//   node scripts/brand/rasterize.mjs <jobs.json> <scratch dir>
//
// Each job is either { svg, out, width, height, pad, bg } (the SVG drawn
// `pad` px in from every edge of a width x height PNG, on `bg` or on
// transparent when it is null) or { page, out, width } (a whole HTML page,
// captured at its full height).
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const [jobsFile, scratch] = process.argv.slice(2);
const jobs = JSON.parse(readFileSync(jobsFile, "utf8"));
const port = 9400 + Math.floor(Math.random() * 400);
const chrome = spawn("google-chrome", ["--headless=new", `--remote-debugging-port=${port}`,
  `--user-data-dir=${scratch}/chrome`, "--no-first-run", "--hide-scrollbars",
  "--force-color-profile=srgb", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 100 && !target; i++) {
  try {
    target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json())
      .find((t) => t.type === "page");
  } catch { await sleep(100); }
}
if (!target) { chrome.kill(); throw new Error("Chrome did not start."); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const waiting = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const n = ++id;
  waiting.set(n, (m) => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
  ws.send(JSON.stringify({ id: n, method, params }));
});
const { frameTree } = await send("Page.getFrameTree");
await send("Page.enable");
await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });

async function show(html, width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await send("Page.setDocumentContent", { frameId: frameTree.frame.id, html });
  await send("Runtime.evaluate", {
    expression: "Promise.all([...document.images].map((i) => i.decode().catch(() => null))).then(() => document.fonts.ready).then(() => 1)",
    awaitPromise: true,
  });
}

for (const job of jobs) {
  if (job.page) {
    await show(job.page, job.width, 1000);
    const { result } = await send("Runtime.evaluate", {
      expression: "Math.ceil(document.documentElement.scrollHeight)", returnByValue: true });
    const height = result.value;
    await send("Emulation.setDeviceMetricsOverride", { width: job.width, height, deviceScaleFactor: 1, mobile: false });
    const shot = await send("Page.captureScreenshot", { format: "png",
      clip: { x: 0, y: 0, width: job.width, height, scale: 1 }, captureBeyondViewport: true });
    writeFileSync(job.out, Buffer.from(shot.data, "base64"));
    continue;
  }
  const src = `data:image/svg+xml;base64,${Buffer.from(job.svg).toString("base64")}`;
  const inner = { w: job.width - 2 * job.pad, h: job.height - 2 * job.pad };
  const html = `<!doctype html><html><body style="margin:0;background:${job.bg || "transparent"};` +
    `width:${job.width}px;height:${job.height}px;overflow:hidden">` +
    `<img src="${src}" style="position:absolute;left:${job.pad}px;top:${job.pad}px;` +
    `width:${inner.w}px;height:${inner.h}px"></body></html>`;
  await show(html, job.width, job.height);
  const shot = await send("Page.captureScreenshot", { format: "png",
    clip: { x: 0, y: 0, width: job.width, height: job.height, scale: 1 } });
  writeFileSync(job.out, Buffer.from(shot.data, "base64"));
}
ws.close();
chrome.kill();
