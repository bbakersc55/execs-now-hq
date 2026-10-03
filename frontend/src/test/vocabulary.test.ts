/// <reference types="vite/client" />
/**
 * P1 vocabulary (owner, 2026-10-02): roles have names and a tenant is a
 * Practice, wherever a person reads it. This scans every screen's source for
 * text a person could read (JSX text and string literals that are sentences,
 * not bare codes) and fails on a role code, "tenant" or "founder fractional".
 */
import { describe, expect, it } from "vitest";

import { ROLE_LABEL, roleLabel } from "../lib/roles";

const sources = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

const FORBIDDEN = /\b(FF|CF|VA|FCC|ECC)\b|tenant|founder fractional/i;

function readable(source: string): string[] {
  const code = source
    .replace(/\/\*[\s\S]*?\*\//g, "")          // block and JSX comments
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");    // line comments, not URLs
  const texts: string[] = [];
  for (const m of code.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)) {
    texts.push(m[1] ?? m[2] ?? m[3] ?? "");
  }
  // JSX text, but not the code between a generic's ">" and the next "<".
  for (const m of code.matchAll(/>([^<>{}]+)</g)) {
    if (!/;|=|&&|\bconst\b|\breturn\b/.test(m[1])) texts.push(m[1]);
  }
  // A bare code or identifier ("FF", "tenant") is logic; a sentence is not.
  return texts.filter((t) => /\s/.test(t.trim()) && /[a-z]/i.test(t));
}

describe("vocabulary", () => {
  it("no screen shows a role code, 'tenant' or 'founder fractional'", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    const found = Object.entries(sources).flatMap(([file, source]) =>
      readable(source).filter((t) => FORBIDDEN.test(t)).map((t) => `${file}: ${t.trim().slice(0, 80)}`));
    expect(found).toEqual([]);
  });

  it("names every role and never prints a code", () => {
    expect(Object.keys(ROLE_LABEL).sort()).toEqual(["CF", "ECC", "FCC", "FF", "VA"]);
    expect(roleLabel("VA")).toBe("Assistant");
    expect(roleLabel("ZZ")).toBe("Team member");
    expect(roleLabel(null)).toBe("Team member");
  });
});
