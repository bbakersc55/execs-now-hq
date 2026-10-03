import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SignedOut } from "./SignedOut";

describe("the signed-out screen (2026-09-30)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); document.cookie = "csrftoken=tok123"; });

  function respond(status: number, body: object) {
    const fetchMock = vi.fn(async () => ({
      ok: status < 400, status, json: async () => body,
    }) as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("lets a client ask for a sign-in link, and says the same thing either way", async () => {
    const user = userEvent.setup();
    const fetchMock = respond(200, { detail: "If that address has access, we've sent a link." });
    render(<SignedOut practice="Executives Now" />);
    await user.type(screen.getByRole("textbox", { name: "Your email address" }),
      "bbakersc1@gmail.com");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByText(/If that address has access/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/auth/magic/request");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok123");
    expect((init.body as FormData).get("email")).toBe("bbakersc1@gmail.com");
  });

  it("keeps Google sign-in for staff, email first (P2: the address picks the client)", () => {
    respond(200, {});
    render(<SignedOut practice="" />);
    const button = screen.getByRole("button", { name: "Sign in with Google" });
    const form = button.closest("form")!;
    expect(form).toHaveAttribute("action", "/accounts/google/start");
    expect(form).toHaveAttribute("method", "get");
    expect(screen.getByLabelText("Your work email")).toHaveAttribute("name", "email");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("says so when rate-limited", async () => {
    const user = userEvent.setup();
    respond(429, { detail: "x" });
    render(<SignedOut practice="" />);
    await user.type(screen.getByRole("textbox", { name: "Your email address" }), "a@b.co");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    await waitFor(() => expect(screen.getByText(/Too many requests/)).toBeInTheDocument());
  });
});
