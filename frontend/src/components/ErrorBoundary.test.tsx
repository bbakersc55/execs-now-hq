import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("Cannot read properties of undefined (reading 'length')");
}

describe("ErrorBoundary", () => {
  it("shows the error instead of a blank page", () => {
    // React logs the caught error; silence it so the run stays readable.
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(<ErrorBoundary><Boom /></ErrorBoundary>);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/This screen failed to render/)).toBeInTheDocument();
    // The message is ON SCREEN — the whole point. A blank page hid it in the
    // console, which is exactly what made this class of bug hard to report.
    expect(
      screen.getByText(/Cannot read properties of undefined/),
    ).toBeInTheDocument();
  });

  it("renders children when nothing throws", () => {
    render(<ErrorBoundary><p>All good</p></ErrorBoundary>);
    expect(screen.getByText("All good")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
