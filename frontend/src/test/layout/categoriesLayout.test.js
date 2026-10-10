// @vitest-environment node
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * The category rows' action buttons, in a real browser (owner, 2026-10-10:
 * "the Combine label spills out of its button"). As `builderLayout.test.js`:
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
let layout;

describe.skipIf(!CHROME && !required)("the category actions' layout, in a browser", () => {
  beforeAll(async () => {
    expect(CHROME, "LAYOUT_CHECK=required, and no Chrome was found").toBeTruthy();
    server = await createServer({
      root: fileURLToPath(new URL("../../..", import.meta.url)), configFile: false, plugins: [react()],
      logLevel: "silent", server: { port: 5232, strictPort: false, host: "127.0.0.1" },
    });
    await server.listen();
    const port = server.httpServer.address().port;
    const { stdout } = await run(CHROME, [
      "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
      "--window-size=1280,2400", "--virtual-time-budget=15000", "--dump-dom",
      `http://127.0.0.1:${port}/src/test/layout/categories.html`,
    ], { maxBuffer: 64 * 1024 * 1024, timeout: 90_000 });
    const found = /<pre id="layout"[^>]*>([\s\S]*?)<\/pre>/.exec(stdout);
    expect(found?.[1], "the page measured nothing").toBeTruthy();
    layout = JSON.parse(found[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">").replace(/&amp;/g, "&"));
    expect(layout.error).toBeUndefined();
  }, 120_000);

  afterAll(async () => { await server?.close(); });

  const buttons = () => layout.rows.flatMap((row) => row.cells.filter((cell) => cell.button)
    .map((cell) => ({ row: row.name, ...cell.button, cell })));

  it("rendered every action there is", () => {
    expect(layout.rows.length).toBe(9);
    expect(new Set(buttons().map((b) => b.label))).toEqual(
      new Set(["Combine", "Split", "Archive", "Restore", "Remove"]));
  });

  it("keeps every label inside its button", () => {
    const spilled = buttons().filter((b) => b.textLeft < b.x || b.textRight > b.right
      || b.scrollWidth > b.clientWidth)
      .map((b) => `${b.label} on ${b.row}: text ${b.textLeft}–${b.textRight}, `
        + `button ${b.x}–${b.right}`);
    expect(spilled).toEqual([]);
  });

  it("makes Combine, Split, Archive and Remove the same width, and 36 pixels high", () => {
    const sizes = new Set(buttons().map((b) => `${b.w}x${b.h}`));
    expect(sizes.size, [...sizes].join(" | ")).toBe(1);
    expect(buttons()[0].h).toBe(36);
    // Each button fills its column, and the three columns are one width.
    for (const b of buttons()) expect(b).toMatchObject({ x: b.cell.x, w: b.cell.w });
    const columns = new Set(layout.rows.flatMap((row) => row.cells.map((cell) => cell.w)));
    expect(columns.size, [...columns].join(" | ")).toBe(1);
  });

  it("puts each action at the same x on every top-level row", () => {
    const top = layout.rows.filter((row) => !/Airfare|Lodging/.test(row.name));
    for (const index of [0, 1, 2]) {
      const places = new Set(top.map((row) => row.cells[index].x));
      expect(places.size, `column ${index}: ${[...places].join(" | ")}`).toBe(1);
    }
  });
});
