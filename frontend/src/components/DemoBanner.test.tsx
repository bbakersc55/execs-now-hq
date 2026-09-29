import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { aMe } from "../test/fixtures";
import { DemoBanner } from "./DemoBanner";

describe("the demo banner (owner, 2026-09-29)", () => {
  it.each(["FF", "CF", "VA"] as const)("tells a %s it is the demo", (role) => {
    render(<DemoBanner me={aMe({ role, environment: "demo" })} />);
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });

  it("is not shown to a client user, or anywhere but the demo", () => {
    const { container, rerender } = render(
      <DemoBanner me={aMe({ role: "ECC", environment: "demo" })} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<DemoBanner me={aMe({ role: "FF", environment: "production" })} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<DemoBanner me={aMe({ role: "FF", environment: "local" })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
