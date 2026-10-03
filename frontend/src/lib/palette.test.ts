import { describe, expect, it } from "vitest";

import { applyPortalTokens, mix, portalTokens } from "./palette";

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
