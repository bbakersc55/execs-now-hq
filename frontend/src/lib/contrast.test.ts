import { describe, expect, it } from "vitest";

import { check, ratio, textOn } from "./contrast";
import reference from "./contrast-reference.json";

describe("contrast — the same answers as apps/tenancy/contrast.py", () => {
  it.each(reference.ratios)("ratio $a / $b", ({ a, b, ratio: expected }) => {
    expect(Math.round(ratio(a, b) * 100) / 100).toBe(expected);
  });
  it.each(reference.text_on)("text on $fill", ({ fill, text }) => {
    expect(textOn(fill)).toBe(text);
  });
  it.each(reference.verdicts)("verdict $primary / $accent", ({ primary, accent, blocked, warned }) => {
    const checks = check(primary, accent);
    expect(checks.filter((c) => c.blocks && !c.ok).map((c) => c.rule)).toEqual(blocked);
    expect(checks.filter((c) => !c.blocks && !c.ok).map((c) => c.rule)).toEqual(warned);
  });
});
