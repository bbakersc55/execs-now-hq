import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiBudget, AiGuard } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { AiUsage } from "./AiUsage";

function aBudget(overrides: Partial<AiBudget> = {}): AiBudget {
  return { console_url: "https://console.anthropic.com/", credits_usd: "50.00",
           credits_as_of: "2026-09-20", spent_since_credits: "6.25",
           estimated_balance: "43.75", monthly_budget_usd: "20.00", month_spend: "8.10",
           month_start: "2026-09-01", next_import: null, warnings: [], ...overrides };
}

function aGuard(overrides: Partial<AiGuard> = {}): AiGuard {
  return { paused: false, resumes_at: null, skipped_today: 0, stopped_after_two_failures: 0,
           cap_usd: "5.00", spent_today_usd: "1.20", skipped: [], ...overrides };
}

function show(budget = aBudget(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/ai-guard/": aGuard(),
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

describe("the daily limit on automatic AI (owner, 2026-09-29)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows today against the limit, and saves a new one", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aBudget(), {
      "POST /api/ai-guard/": aGuard({ cap_usd: "2.50" }),
    });
    expect(await screen.findByText("Daily limit on automatic AI")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: /Daily limit on automatic AI/ });
    expect(input).toHaveValue("5.00");
    await user.clear(input);
    await user.type(input, "2.50");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.method === "POST" && c.url.endsWith("/ai-guard/"));
      expect(post?.body).toEqual({ daily_cap_usd: "2.50" });
    });
  });

  it("says when the worker is paused, and what it held back", async () => {
    show(aBudget(), { "GET /api/ai-guard/": aGuard({
      paused: true, resumes_at: "2026-09-30T06:00:00Z", skipped_today: 3,
      spent_today_usd: "5.08",
      skipped: [{ reason: "daily_cap", purpose: "meeting_parse", job: "meetings.poll_drive",
                  target_type: "meeting_source_file", target_id: "f1",
                  at: "2026-09-29T20:00:00Z" }] }) });
    expect(await screen.findByText(/Automatic AI work is paused for the rest of today/))
      .toHaveTextContent("3 items wait until tomorrow");
    expect(screen.getByText("paused until midnight")).toBeInTheDocument();
    expect(screen.getByText(/Reading meeting notes · meeting_source_file · waits for tomorrow/))
      .toBeInTheDocument();
  });
});
