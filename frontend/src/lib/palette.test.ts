// @ts-expect-error — the app has no Node types; the test runner is Node.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { ratio } from "./contrast";
import { applyPortalTokens, mix, portalTokens } from "./palette";

describe("the product's own orange buttons (2026-11-09)", () => {
  const css: string = readFileSync("src/theme.css", "utf8");
  const token = (name: string) => css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6});`))![1];

  it("carry navy text that passes AA on the orange and on its hover", () => {
    expect(token("--on-orange").toLowerCase()).toBe(token("--navy").toLowerCase());
    expect(ratio(token("--orange"), token("--on-orange"))).toBeGreaterThanOrEqual(4.5);
    expect(ratio(token("--orange-hover"), token("--on-orange"))).toBeGreaterThanOrEqual(4.5);
  });

  it("put no hard-coded white on an orange fill", () => {
    expect(css).not.toMatch(/background:\s*var\(--orange\);\s*color:\s*#fff/);
  });
});

describe("the portal's color tokens (P1: the portal stylesheet bug)", () => {
  it("derives the whole family the stylesheet reads, not just --blue", () => {
    const tokens = portalTokens("#2E7D32", "#F9A825");
    expect(tokens["--navy"]).toBe("#2E7D32");
    expect(tokens["--orange"]).toBe("#F9A825");
    for (const name of ["--navy-700", "--navy-300", "--orange-600", "--orange-050"]) {
      expect(tokens[name]).toMatch(/^#[0-9a-f]{6}$/);
    }
    expect(tokens["--focus"]).toBe("0 0 0 3px rgba(46, 125, 50, .20)");
  });

  it("puts dark text on a light accent and white on a dark one", () => {
    expect(portalTokens("#0A3A65", "#F58220")["--on-orange"]).toBe("#1F2933");
    expect(portalTokens("#0A3A65", "#0B6E4F")["--on-orange"]).toBe("#FFFFFF");
  });

  it("keeps the text readable on an accent under the pointer, light or dark", () => {
    for (const accent of ["#F58220", "#E87722", "#F9A825", "#0B6E4F", "#7A1F3D"]) {
      const t = portalTokens("#0A3A65", accent);
      expect(ratio(t["--orange-hover"], t["--on-orange"])).toBeGreaterThanOrEqual(
        ratio(accent, t["--on-orange"]));
    }
  });

  it("mixes toward white and black", () => {
    expect(mix("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mix("#0a3a65", "#ffffff", 0)).toBe("#0a3a65");
  });

  it("applies for a client and removes every token for staff", () => {
    const root = document.createElement("div");
    applyPortalTokens(root, { primary: "#2E7D32", accent: "#F9A825" });
    expect(root.style.getPropertyValue("--navy")).toBe("#2E7D32");
    applyPortalTokens(root, null);
    expect(root.style.getPropertyValue("--navy")).toBe("");
    expect(root.style.getPropertyValue("--on-orange")).toBe("");
  });
});
