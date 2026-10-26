import { describe, expect, it } from "vitest";

import { figure, unitAfter } from "./figures";

describe("a goal's figures (owner, 2026-10-26)", () => {
  it("drops stored decimals and groups thousands", () => {
    expect(figure("54.0000")).toBe("54");
    expect(figure("1234.5000", "sites")).toBe("1,234.5");
    expect(figure("0.3333")).toBe("0.33");
    expect(figure(null)).toBe("");
  });
  it("puts a percent on the number and money before it, and says the unit once", () => {
    expect(figure("54.0000", "%")).toBe("54%");
    expect(figure("90", "$")).toBe("$90");
    expect(figure("-3.25", "USD")).toBe("-$3.25");
    expect(unitAfter("%")).toBe("");
    expect(unitAfter("sites")).toBe("sites");
  });
});
