// @vitest-environment node
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * A layout check in a real browser (owner, 2026-10-08): the builder, with
 * every kind of section, is opened in headless Chrome, and what is asserted
 * is where things are. The other tests run in jsdom, which lays nothing out,
 * so "the Remove buttons line up down the page" cannot be tested there.
 *
 * Plain JavaScript, so the app's build needs no Node type definitions for it.
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

describe.skipIf(!CHROME && !required)("the builder's layout, in a browser", () => {
  beforeAll(async () => {
    expect(CHROME, "LAYOUT_CHECK=required, and no Chrome was found").toBeTruthy();
    server = await createServer({
      root: fileURLToPath(new URL("../../..", import.meta.url)), configFile: false, plugins: [react()],
      logLevel: "silent", server: { port: 5231, strictPort: false, host: "127.0.0.1" },
    });
    await server.listen();
    const port = server.httpServer.address().port;
    const { stdout } = await run(CHROME, [
      "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
      "--window-size=1280,2400", "--virtual-time-budget=15000", "--dump-dom",
      `http://127.0.0.1:${port}/src/test/layout/harness.html`,
    ], { maxBuffer: 64 * 1024 * 1024, timeout: 90_000 });
    const found = /<pre id="layout"[^>]*>([\s\S]*?)<\/pre>/.exec(stdout);
    expect(found?.[1], "the page measured nothing").toBeTruthy();
    layout = JSON.parse(found[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">").replace(/&amp;/g, "&"));
    expect(layout.error).toBeUndefined();
  }, 120_000);

  afterAll(async () => { await server?.close(); });

  it("rendered every kind of section", () => {
    expect(layout.sections).toEqual(expect.arrayContaining([
      "Before the call", "Ratings", "Diagnostic", "Leadership bench",
      "The mirror and where they want to go", "Strategy Map", "What they value",
      "Two paths", "Scope", "Removed section", "Add a section", "Wording for Claude"]));
    // Every section that holds questions has rows of actions to compare.
    expect(new Set(layout.rows.map((row) => row.section))).toEqual(new Set([
      "Before the call", "Ratings", "Diagnostic", "Leadership bench",
      "The mirror and where they want to go", "What they value", "Two paths", "Scope"]));
    // And the rows differ in how many flags they carry, which is the point.
    expect(new Set(layout.rows.map((row) => row.flags)).size).toBeGreaterThan(2);
  });

  it("puts move up, move down and Remove at the same x in every section", () => {
    for (const column of ["up", "down", "remove"]) {
      const places = layout.rows.map((row) => `${row[column].x} +${row[column].w}`);
      expect(new Set(places), `${column}: ${places.join(" | ")}`).toEqual(new Set([places[0]]));
    }
    // The three columns, left to right, and not on top of each other.
    const [row] = layout.rows;
    expect(row.up.x + row.up.w).toBeLessThanOrEqual(row.down.x);
    expect(row.down.x + row.down.w).toBeLessThanOrEqual(row.remove.x);
  });

  it("fills each column with its button, so the buttons line up as the columns do", () => {
    const withButtons = layout.rows.filter((row) => row.removeButton);
    expect(withButtons.length).toBeGreaterThan(8);
    for (const row of withButtons) {
      expect(row.upButton).toMatchObject({ x: row.up.x, w: row.up.w });
      expect(row.downButton).toMatchObject({ x: row.down.x, w: row.down.w });
      expect(row.removeButton).toMatchObject({ x: row.remove.x, w: row.remove.w });
    }
    // The two paths have no such buttons, and keep the columns all the same.
    const paths = layout.rows.filter((row) => row.section === "Two paths");
    expect(paths).toHaveLength(2);
    expect(paths.every((row) => !row.removeButton && !row.upButton)).toBe(true);
  });

  it("makes every button, input and select 36 pixels high", () => {
    expect(layout.controls.length).toBeGreaterThan(60);
    const off = layout.controls.filter((control) => control.h !== 36)
      .map((control) => `${control.what} is ${control.h}`);
    expect(off).toEqual([]);
  });

  it("aligns the template's name with the buttons beside it, top and height", () => {
    const { name, beside } = layout.nameRow;
    expect(beside.map((b) => b.what)).toEqual([
      "Make this the practice default", "Start a session from this template"]);
    for (const button of beside) {
      expect(button, button.what).toMatchObject({ y: name.y, h: name.h });
    }
  });
});
