import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiBudget } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { AiUsage } from "./AiUsage";

function aBudget(overrides: Partial<AiBudget> = {}): AiBudget {
  return { console_url: "https://console.anthropic.com/", credits_usd: "50.00",
           credits_as_of: "2026-09-20", spent_since_credits: "6.25",
           estimated_balance: "43.75", monthly_budget_usd: "20.00", month_spend: "8.10",
           month_start: "2026-09-01", next_import: null, warnings: [], ...overrides };
}

function show(budget = aBudget(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/ai-budget/": budget,
    "GET /api/ai-usage/summary/": { by_purpose: [], total: { cost: "8.10", calls: 40 } },
    "GET /api/ai-usage/": [],
    "GET /api/ai-key/": { source: "tenant", last4: "abcd", verified_at: null,
                          rotated_at: null, model: "claude-opus-5" },
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<AiUsage />);
  return fetchMock;
}

/** Owner, 2026-09-28 — credits, a budget, and a balance that says it is a guess. */
describe("AI credits and budget", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("links to the Anthropic console", async () => {
    show();
    expect(await screen.findByRole("link", { name: /Manage your Anthropic account/ }))
      .toHaveAttribute("href", "https://console.anthropic.com/");
  });

  it("shows the balance and says every time that it is an estimate", async () => {
    show();
    expect(await screen.findByText("$43.75")).toBeInTheDocument();
    expect(screen.getByText(/An estimate: the \$50\.00 you entered on 2026-09-20/))
      .toBeInTheDocument();
    expect(screen.getByText(/of a \$20\.00 monthly budget/)).toBeInTheDocument();
  });

  it("shows the warnings the server raises", async () => {
    show(aBudget({ warnings: [{ kind: "budget",
      message: "AI spend this month is $16.40 — 82% of the $20.00 monthly budget." }] }));
    expect(await screen.findByText(/82% of the \$20\.00 monthly budget/)).toBeInTheDocument();
  });

  it("saves a top-up as an amount and a date", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aBudget(), { "POST /api/ai-budget/": aBudget() });
    await user.type(await screen.findByLabelText("Credits on account"), "100");
    await user.clear(screen.getByLabelText("Topped up on"));
    await user.type(screen.getByLabelText("Topped up on"), "2026-09-28");
    await user.click(screen.getByRole("button", { name: "Save credits" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ credits_usd: "100", credits_as_of: "2026-09-28" }));
  });

  it("clears the budget when the box is emptied", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aBudget(), { "POST /api/ai-budget/": aBudget() });
    await user.clear(await screen.findByLabelText("Monthly budget"));
    await user.click(screen.getByRole("button", { name: "Save budget" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ monthly_budget_usd: null }));
  });
});
