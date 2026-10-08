import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandMark } from "../App";

/**
 * The portal sidebar on a laptop showed a broken image and the alt text
 * "Executives Now" (2026-10-08). The address was right; the laptop's copy of
 * production has the logo's row and not its file. Whenever the image is not
 * there, the practice's name is drawn as the styled heading instead.
 */
describe("the sidebar's brand", () => {
  it("draws the logo when there is one", () => {
    render(<BrandMark logo="/api/branding/logo" name="Executives Now" />);
    expect(screen.getByRole("img", { name: "Executives Now" }))
      .toHaveAttribute("src", "/api/branding/logo");
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("shows the name as styled text when the logo file fails to load", () => {
    render(<BrandMark logo="/api/branding/logo" name="Executives Now" />);
    fireEvent.error(screen.getByRole("img"));

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    const name = screen.getByRole("heading", { name: "Executives Now" });
    expect(name).toHaveClass("wordmark");
  });

  it("shows the name as the same styled text when the practice has no logo", () => {
    render(<BrandMark logo="" name="Executives Now" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Executives Now" })).toHaveClass("wordmark");
  });

  it("tries again when the logo changes, rather than staying on text for good", () => {
    const { rerender } = render(<BrandMark logo="/api/branding/logo" name="Executives Now" />);
    fireEvent.error(screen.getByRole("img"));
    rerender(<BrandMark logo="/api/branding/logo?v=2" name="Executives Now" />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/branding/logo?v=2");
  });
});
