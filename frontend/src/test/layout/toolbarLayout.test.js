// @vitest-environment node
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * The strategy session's agenda rail and the portal's Tasks toolbar, in a real
 * browser at 1366 and 390 wide (owner, 2026-10-29). As `builderLayout.test.js`:
 * headless Chrome, and what is asserted is where things are.
 *
 * It needs Chrome on the machine. Where there is none it is skipped, and says
 * so; set `LAYOUT_CHECK=required` to make that a failure instead.
 */

const CHROME = [process.env.CHROME_BIN, "/usr/bin/google-chrome", "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
  .find((candidate) => candidate && existsSync(candidate));
const required = process.env.LAYOUT_CHECK === "required";
const run = promisify(execFile);

let server;
const layouts = {};

async function measureAt(port, width) {
  const { stdout } = await run(CHROME, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    "--window-size=1366,1700", "--virtual-time-budget=15000", "--dump-dom",
    `http://127.0.0.1:${port}/src/test/layout/toolbar.html?w=${width}`,
  ], { maxBuffer: 64 * 1024 * 1024, timeout: 90_000 });
  const found = /<pre id="layout"[^>]*>([\s\S]*?)<\/pre>/.exec(stdout);
  expect(found?.[1], "the page measured nothing").toBeTruthy();
  return JSON.parse(found[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&amp;/g, "&"));
}

describe.skipIf(!CHROME && !required)("the agenda rail and the Tasks toolbar, in a browser", () => {
  beforeAll(async () => {
    expect(CHROME, "LAYOUT_CHECK=required, and no Chrome was found").toBeTruthy();
    server = await createServer({
      root: fileURLToPath(new URL("../../..", import.meta.url)), configFile: false, plugins: [react()],
      logLevel: "silent", server: { port: 5233, strictPort: false, host: "127.0.0.1" },
    });
    await server.listen();
    const port = server.httpServer.address().port;
    for (const width of [1366, 390]) {
      layouts[width] = await measureAt(port, width);
      expect(layouts[width].error).toBeUndefined();
    }
  }, 240_000);

  afterAll(async () => { await server?.close(); });

  for (const width of [1366, 390]) {
    describe(`at ${width}`, () => {
      it("scrolls nothing sideways", () => {
        const l = layouts[width];
        expect(l.width).toBe(width);
        expect(l.scrollWidth).toBeLessThanOrEqual(width);
      });

      it("wraps a long step label under itself, the minutes right-aligned on its first line", () => {
        const l = layouts[width];
        for (const step of l.rail) {
          // Inside its button, left of its minutes, never under them.
          expect(step.text.right, step.label).toBeLessThanOrEqual(step.mins.x + 0.5);
          expect(step.mins.right, step.label).toBeLessThanOrEqual(step.button.right);
          expect(Math.abs(step.mins.y - step.text.y), step.label).toBeLessThanOrEqual(2);
          expect(step.mins.h, step.label).toBeLessThan(step.lineHeight * 1.5);
          expect(step.button.right, step.label).toBeLessThanOrEqual(width);
        }
        // The rail keeps its own column at 1366, the panel untouched beside it.
        if (width === 1366) {
          const mirror = l.rail.find((s) => s.label.startsWith("The mirror"));
          expect(mirror.text.h).toBeGreaterThan(mirror.lineHeight * 1.5);
          expect(l.nav.w).toBe(232);
          for (const step of l.rail) expect(step.button.right).toBeLessThanOrEqual(l.panel.x);
          // Every step's minutes end at one x: right-aligned.
          expect(new Set(l.rail.map((s) => s.mins.right)).size).toBe(1);
        }
      });

      it("joins Mine / My team / Everyone and Board / List, each at its natural width", () => {
        const l = layouts[width];
        for (const group of [l.whose, l.view]) {
          expect(group.buttons.length).toBeGreaterThan(1);
          // One line, the same height, each touching the next.
          expect(new Set(group.buttons.map((b) => b.y)).size).toBe(1);
          for (let i = 1; i < group.buttons.length; i += 1) {
            expect(group.buttons[i].x).toBeCloseTo(group.buttons[i - 1].right - 1, 0);
          }
          // Not stretched: no wider than its buttons.
          expect(group.box.w).toBeLessThanOrEqual(
            group.buttons.reduce((sum, b) => sum + b.w, 0));
        }
        expect(l.whose.buttons.length).toBe(3);
      });

      it("lays the toolbar out in two rows: search, whose, view; then the five dropdowns", () => {
        const l = layouts[width];
        expect(l.rows).toHaveLength(2);
        expect(l.firstRow).toEqual(["search", "seg", "seg"]);
        expect(l.selects.map((s) => s.label)).toEqual([
          "Filter by project", "Filter by assignee", "Filter by status",
          "Filter by priority", "Sort by"]);
        // Left-aligned, below row one.
        expect(l.selects[0].x).toBe(l.rows[1].x);
        for (const s of l.selects) expect(s.y).toBeGreaterThanOrEqual(l.rows[0].bottom);
        if (width === 1366) {
          // Row one on one line, the search growing to fill what is left.
          expect(l.whose.box.y).toBeCloseTo(l.search.y + (l.search.h - l.whose.box.h) / 2, 0);
          expect(l.view.box.right).toBeCloseTo(l.rows[0].right, 0);
          expect(l.search.w).toBeGreaterThan(700);
          // The five fit on one line.
          expect(new Set(l.selects.map((s) => s.y)).size).toBe(1);
        }
      });
    });
  }
});
