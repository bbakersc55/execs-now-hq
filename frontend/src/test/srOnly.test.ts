/** Words for screen readers only (owner, 2026-11-25): the class had no rule,
 *  so the tax number's "ending 4321" showed on screen beside "Show full
 *  number". jsdom lays nothing out, so this reads the stylesheet itself. */
// @ts-expect-error — the app has no Node types; the test runner is Node.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe(".sr-only", () => {
  const css: string = readFileSync("src/theme.css", "utf8");

  it("is defined in the app's stylesheet, out of sight but not removed", () => {
    const rule = css.match(/\n\.sr-only\s*\{([^}]*)\}/);
    expect(rule, ".sr-only has no rule in theme.css").not.toBeNull();
    const body = rule![1];
    expect(body).toMatch(/position:\s*absolute/);
    expect(body).toMatch(/width:\s*1px/);
    expect(body).toMatch(/overflow:\s*hidden/);
    expect(body).toMatch(/clip(-path)?:/);
    // Never display:none or visibility:hidden: a screen reader skips those.
    expect(body).not.toMatch(/display:\s*none|visibility:\s*hidden/);
  });
});
