import { describe, expect, it } from "vitest";

import { NAV } from "../App";
import { Me } from "../lib/api";
import { aMe } from "../test/fixtures";

/** What the sidebar shows this person: the app's own filter. */
function labels(me: Me) {
  return NAV.filter((n) => (!n.roles || (me.role && n.roles.includes(me.role)))
    && (!n.when || n.when(me))).map((n) => (typeof n.label === "string" ? n.label : "")).filter(Boolean);
}

describe("SOPs in the navigation (P10)", () => {
  it("the practice gets SOPs right after Tools while a Command Center is on", () => {
    const shown = labels(aMe({ role: "VA", has_plan: true }));
    expect(shown.indexOf("SOPs")).toBe(shown.indexOf("Tools") + 1);
    expect(labels(aMe({ role: "FF", has_plan: false }))).not.toContain("SOPs");
  });

  it("a client user gets SOPs after Plan only when one is published to them", () => {
    const shown = labels(aMe({ role: "ECC", has_plan: true, has_sops: true }));
    expect(shown.indexOf("SOPs")).toBe(shown.indexOf("Plan") + 1);
    expect(labels(aMe({ role: "FCC", has_plan: true, has_sops: false }))).not.toContain("SOPs");
  });
});
