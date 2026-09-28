import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { Unsubscribe } from "./Unsubscribe";

const state = (marketing: boolean, updates: boolean) => ({
  practice: "Executives Now", category: "marketing",
  categories: [
    { category: "marketing", label: "marketing emails", unsubscribed: marketing },
    { category: "updates", label: "progress updates", unsubscribed: updates },
  ],
});

function show(responses: unknown[]) {
  let n = 0;
  const fetchMock = mockApi({ "POST /api/unsubscribe/tok": () =>
    ({ status: 200, body: responses[Math.min(n++, responses.length - 1)] }) });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Unsubscribe />, { path: "/unsubscribe/:token", route: "/unsubscribe/tok" });
  return fetchMock;
}

/** Owner, 2026-09-28 — one category, a confirmation, the other offered, an undo. */
describe("the unsubscribe page", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("unsubscribes from the email's category on landing and says so", async () => {
    const fetchMock = show([state(true, false)]);
    expect(await screen.findByText(/You are unsubscribed from marketing emails/))
      .toBeInTheDocument();
    expect(screen.getByText(/sign-in links, or documents you asked for — are\s+not affected/))
      .toBeInTheDocument();
    expect(fetchMock.calls.map((c) => c.body)).toEqual([{}]);
  });

  it("offers the other category, and an undo", async () => {
    const user = userEvent.setup();
    const fetchMock = show([state(true, false), state(true, true), state(false, true)]);
    await user.click(await screen.findByRole("button",
      { name: "Unsubscribe from progress updates too" }));
    await user.click(await screen.findByRole("button",
      { name: "Undo — keep sending me marketing emails" }));

    await waitFor(() => expect(fetchMock.calls.map((c) => c.body)).toEqual([
      {}, { category: "updates" }, { category: "marketing", action: "resubscribe" }]));
    expect(await screen.findByText("You are receiving marketing emails again."))
      .toBeInTheDocument();
  });
});
