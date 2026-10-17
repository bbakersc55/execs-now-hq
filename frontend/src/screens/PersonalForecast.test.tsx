import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForecastRow, PersonalForecast, PersonalForecastLine } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { PersonalForecastPage } from "./PersonalForecast";

function row(start: string, end: number, lines: string[] = []): ForecastRow {
  return { start, end: start, label: start, start_cents: end, in_cents: 0, out_cents: 0,
           end_cents: end, lines, below_floor: false, below_zero: false };
}

function line(over: Partial<PersonalForecastLine>): PersonalForecastLine {
  return { id: "l1", group: "pattern:out|c1|a1|mountain market", kind: "regular",
           direction: "out", amount_cents: 9_707, on_date: "2026-10-21",
           label: "MOUNTAIN MARKET #118", detail: "$97.07 on the 21st, monthly.",
           category: "Groceries", cadence: "monthly", link: "/finance/personal/entries",
           counted: true, what_if: false, adjusted: "", adjustment: "", ...over };
}

const SUMMARY = { low_cents: 14_176_573, low_start: "2026-10-17", low_label: "October 2026",
                  end_cents: 20_116_828, first_below_floor: null, first_below_zero: null };

const LINES = [
  line({}),
  line({ id: "pay:1", group: "pay", kind: "known", direction: "in", amount_cents: 2_200_000,
         on_date: "2026-10-29", label: "Pay from the practice",
         category: "Pay from the practice", detail: "$22,000.00 once a month." }),
  line({ id: "planned:p1:2026-12-01", group: "planned:p1", kind: "planned",
         amount_cents: 180_000, on_date: "2026-12-01", label: "Christmas", category: "",
         cadence: "", detail: "A goal's target, spent on its date." }),
  line({ id: "planned:p2:2027-02-14", group: "planned:p2", kind: "planned",
         amount_cents: 1_450_000, on_date: "2027-02-14", label: "New roof", category: "",
         cadence: "", counted: false, what_if: true, detail: "A what-if." }),
];

const FORECAST: PersonalForecast = {
  as_of: "2026-10-17", ready: true, complete_months: 6, note: "",
  cash_today_cents: 14_269_183,
  accounts: [{ id: "a1", name: "Joint checking", kind: "bank", amount_cents: 8_154_371,
               last_entry_on: "2026-10-17", reconciled_through: null, stale: false },
             { id: "a2", name: "Joint savings", kind: "bank", amount_cents: 6_114_812,
               last_entry_on: "2026-09-30", reconciled_through: "2026-09-30", stale: true }],
  floor_cents: 800_000,
  weeks: Array.from({ length: 26 }, (_v, i) => row(`2026-${10 + Math.floor(i / 5)}-0${
    1 + (i % 5)}`, 14_000_000 + i * 100_000, i === 0 ? ["l1"] : [])),
  months: Array.from({ length: 12 }, (_v, i) => row(`m${i}`, 15_000_000 + i * 1_000_000)),
  views: { "30": SUMMARY, "90": SUMMARY, "180": SUMMARY, months: SUMMARY },
  lines: LINES,
  planned: [
    { id: "p1", description: "Christmas", direction: "out", amount_cents: 180_000,
      on_date: "2026-12-01", repeat: "", is_what_if: false, state: "planned", goal: "g1",
      next_on: "2026-12-01" },
    { id: "p2", description: "New roof", direction: "out", amount_cents: 1_450_000,
      on_date: "2027-02-14", repeat: "", is_what_if: true, state: "what_if", goal: null,
      next_on: "2027-02-14" }],
  goals_not_drawn: [{ id: "g3", name: "Emergency fund", monthly_cents: 97_000,
                      account: "Joint savings" }],
  adjustments: [], history: [], what_if: null,
  disclaimer: "Budgeting, forecasting and tax estimates only. Confirm with your CPA.",
};

const ASK = { estimate_usd: "0.0200", review_estimate_usd: "0.0400", used_today: 1, cap: 20,
              resets_at: "", refused: "", disclaimer: "", include_client_names: false };

describe("the personal forecast (P6 M4 stop 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows cash today, the low point and the floor, and every kind of line", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/personal/forecast/ask": ASK, "GET /api/personal/forecast": FORECAST }));
    renderRoute(<PersonalForecastPage />);
    const figures = await screen.findByLabelText("The personal forecast in three figures");
    expect(within(figures).getByText("$142,691.83")).toBeInTheDocument();
    expect(within(figures).getByText("$141,765.73")).toBeInTheDocument();
    expect(within(figures).getByText("$8,000.00")).toBeInTheDocument();
    // A stale account says so; a card is said not to be cash.
    expect(screen.getByText(/Joint savings\s+has no line in the last 14 days/))
      .toBeInTheDocument();
    expect(screen.getByText(/A card is not cash/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Known (1)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Regular (1)" })).toBeInTheDocument();
    // The goal is on the forecast; the emergency fund, with no date, is said.
    const planned = screen.getByRole("table", { name: "Planned lines" });
    expect(within(planned).getByText("Christmas")).toBeInTheDocument();
    expect(within(planned).getByText("a goal")).toBeInTheDocument();
    expect(screen.getByText(/Emergency fund\s+has no date/)).toBeInTheDocument();
  });

  it("tries a what-if by asking the server, and saves nothing", async () => {
    const user = userEvent.setup();
    const tried = { ...FORECAST, what_if: {
      weeks: FORECAST.weeks, months: FORECAST.months,
      views: { ...FORECAST.views, "90": { ...SUMMARY, low_cents: 12_726_573,
                                         end_cents: 18_666_828 } },
      difference_at_low: { "30": 0, "90": -1_450_000, "180": -1_450_000, months: -1_450_000 },
      off: [], on: ["p2"], amounts: {} } };
    const fetchMock = mockApi({
      "GET /api/personal/forecast/ask": ASK, "POST /api/personal/forecast/what-if": tried,
      "GET /api/personal/forecast": FORECAST });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalForecastPage />);
    await user.click(await screen.findByRole("button", { name: "Try New roof" }));
    const status = await screen.findByRole("status", { name: "The what-if" });
    expect(status).toHaveTextContent("with New roof");
    await waitFor(() => expect(status).toHaveTextContent("$14,500.00 lower than it stands"));
    expect(fetchMock.calls.find((c) => c.url.endsWith("/what-if"))?.body)
      .toEqual({ off: [], on: ["p2"], amounts: {} });
    expect(fetchMock.calls.filter((c) => c.method !== "GET" && !c.url.endsWith("/what-if")))
      .toEqual([]);
  });

  it("says a regular line is not regular, and prices Claude before anything is sent",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/personal/forecast/ask": ASK,
        "POST /api/personal/forecast/adjustments": FORECAST,
        "POST /api/personal/forecast/ask/explain": { text: "Pay carries it.",
                                                     cost_usd: "0.0141", disclaimer: "D",
                                                     used_today: 2, cap: 20 },
        "GET /api/personal/forecast": FORECAST });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<PersonalForecastPage />);
      const regular = (await screen.findByRole("heading", { name: "Regular (1)" }))
        .closest("section.card") as HTMLElement;
      await user.click(within(regular).getByText("Show it"));
      await user.click(screen.getByRole("button", { name: "MOUNTAIN MARKET #118 is not regular" }));
      await waitFor(() => expect(fetchMock.calls.find(
        (c) => c.url === "/api/personal/forecast/adjustments")?.body)
        .toEqual({ group: "pattern:out|c1|a1|mountain market", kind: "not_regular" }));
      const explain = await screen.findByRole("button",
                                              { name: "Explain this forecast (about $0.02)" });
      expect(fetchMock.calls.some((c) => c.url.endsWith("/ask/explain"))).toBe(false);
      expect(screen.getByText(/never a merchant's name/)).toBeInTheDocument();
      await user.click(explain);
      expect(await screen.findByRole("note", { name: "Explanation" }))
        .toHaveTextContent("Pay carries it.");
      expect(fetchMock.calls.find((c) => c.url.endsWith("/ask/explain"))?.body)
        .toEqual({ view: "90" });
    });
});
