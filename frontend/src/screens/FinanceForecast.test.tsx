import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Forecast } from "../lib/api";
import { FINANCE_DISCLAIMER } from "../lib/finance";
import { aMe } from "../test/fixtures";
import { AI, aForecast } from "../test/forecast";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";

/** P6 M2, the first stop: the cash forecast from known and regular lines,
 *  the card, the floor, and the Cash forecast module's tab. */

function show(data: Forecast = aForecast(), extra: Record<string, unknown> = {},
              modules = ["bookkeeping", "forecast"]) {
  const fetchMock = mockApi({
    // Before the forecast's own address, which it begins with.
    "GET /api/finance-forecast/explain/": AI,
    ...extra, "GET /api/me": aMe({ modules }),
    "GET /api/finance-forecast/": data, ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance tab="forecast" />);
  return fetchMock;
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("the Forecast tab", () => {
  it("is after Reconcile for a practice with the module, and absent without it",
    async () => {
      show();
      await screen.findByRole("link", { name: "Forecast" });
      const tabs = screen.getAllByRole("link")
        .filter((a) => a.getAttribute("href")?.startsWith("/finance"))
        .map((a) => a.textContent);
      expect(tabs.slice(0, 3)).toEqual(["Entries", "Reconcile", "Forecast"]);
      vi.unstubAllGlobals();
      vi.stubGlobal("fetch", mockApi({
        "GET /api/me": aMe({ modules: ["bookkeeping"] }),
        "GET /api/finance-reconcile/explain/": {},
        "GET /api/finance-reconcile/": { months: [], accounts: [], locked_through: null,
                                         locked_by: null, next_to_close: null,
                                         guided: false, today: "2026-10-11" } }));
      const { container } = renderRoute(<Finance tab="reconcile" />);
      await within(container).findByRole("link", { name: "Reconcile" });
      expect(within(container).queryByRole("link", { name: "Forecast" }))
        .not.toBeInTheDocument();
    });

  it("carries the line every Finance screen carries", async () => {
    show();
    expect(await screen.findByRole("note", { name: "Disclaimer" }))
      .toHaveTextContent(FINANCE_DISCLAIMER);
  });
});

describe("the forecast", () => {
  it("says what it is, where it starts, the low point and the floor", async () => {
    show();
    expect(await screen.findByText(/It is\s+arithmetic on your own books, not a prediction/))
      .toBeInTheDocument();
    const three = screen.getByLabelText("The forecast in three figures");
    expect(three).toHaveTextContent("Cash today$12,000.00");
    // 90 days is what opens: 13 weeks, whose low point is the seventh week.
    expect(three).toHaveTextContent(
      "Lowest in the next 90 days-$4,018.00 · the week of November 22, 2026");
    expect(three).toHaveTextContent("Your floor$10,000.00");
    expect(screen.getByLabelText("Where cash today comes from")).toHaveTextContent(
      "Front Range Bank checking: $12,000.00, reconciled through September 30, 2026, "
      + "entries through October 9, 2026");
  });

  it("marks below zero always, and under the floor when there is one", async () => {
    show();
    expect(await screen.findByText("Below zero.")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "The cash forecast as a table" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(13);
    expect(rows[0]).toHaveTextContent(
      "October 11, 2026$12,000.00—$695.00$11,305.001 line");
    expect(rows[1]).toHaveTextContent("under your floor");
    expect(rows[6]).toHaveTextContent("below zero");
    expect(rows[6]).not.toHaveTextContent("under your floor");
  });

  it("marks below zero just the same with no floor set at all", async () => {
    show(aForecast({}, null));
    expect(await screen.findByText("Below zero.")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument();
    expect(screen.queryByText(/under your floor/i)).not.toBeInTheDocument();
    const table = screen.getByRole("table", { name: "The cash forecast as a table" });
    expect(within(table).getAllByRole("row")[7]).toHaveTextContent("below zero");
  });

  it("switches between 30, 90 and 180 days and 12 months", async () => {
    show();
    const table = await screen.findByRole("table", { name: "The cash forecast as a table" });
    const count = () => within(table).getAllByRole("row").length - 1;
    const far = screen.getByRole("group", { name: "How far ahead" });
    expect(within(far).getByRole("button", { name: "90 days" }))
      .toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(far).getByRole("button", { name: "30 days" }));
    expect(count()).toBe(5);
    // Thirty days ends before the week the cash runs out.
    expect(screen.queryByText("Below zero.")).not.toBeInTheDocument();
    expect(screen.getByText("Under your floor.")).toBeInTheDocument();
    await userEvent.click(within(far).getByRole("button", { name: "180 days" }));
    expect(count()).toBe(26);
    await userEvent.click(within(far).getByRole("button", { name: "12 months" }));
    expect(count()).toBe(2);
    expect(within(table).getAllByRole("row")[2]).toHaveTextContent("November 2026");
    expect(screen.getByLabelText("The forecast in three figures"))
      .toHaveTextContent("Lowest in the next 12 months-$4,018.00 · November 2026");
  });

  it("opens the lines a week is made of, each linked to its source", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", {
      name: "Show the 2 lines of October 18, 2026" }));
    const table = screen.getByRole("table", { name: "The cash forecast as a table" });
    expect(within(table).getByRole("link", { name: "Acme Fasteners: Invoice SOP-0188" }))
      .toHaveAttribute("href", "/invoices/i1");
    expect(within(table).getByRole("link", { name: "Business Visa payment" }))
      .toHaveAttribute("href", "/finance/balance");
    await userEvent.click(screen.getByRole("button", {
      name: "Hide the 2 lines of October 18, 2026" }));
    expect(within(table).queryByRole("link", { name: "Business Visa payment" }))
      .not.toBeInTheDocument();
  });

  it("lists what is known and what is regular, each saying where it comes from",
    async () => {
      show();
      // Within the 90 days shown: one known line; rent, the card and a card charge.
      expect(await screen.findByRole("heading", { name: "Known (1)" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Regular (3)" })).toBeInTheDocument();
      const regular = screen.getByRole("table", { name: "Regular lines", hidden: true });
      const rent = within(regular).getByRole("link", { name: "Larimer Square Cowork",
                                                       hidden: true }).closest("tr")!;
      expect(rent).toHaveTextContent("Office expense: Coworking and meeting rooms");
      expect(rent).toHaveTextContent("monthly");
      expect(rent).toHaveTextContent(
        "$695.00 on the 1st, monthly: the same amount of 3 of the last 3 closed months.");
      // A charge on a card is listed and marked: it is cash when the card is paid.
      expect(within(regular).getByRole("link", { name: "Zoom", hidden: true }).closest("tr"))
        .toHaveTextContent("on a card");
      expect(within(regular).queryByText("Far away")).not.toBeInTheDocument();
    });

  it("sets, changes and removes the floor", async () => {
    const fetchMock = show(aForecast({}, null), {
      "POST /api/finance-forecast/floor/": (body: { floor_cents: number | null }) => ({
        body: aForecast({}, body.floor_cents) }) });
    await userEvent.click(await screen.findByRole("button", { name: "Set a floor" }));
    await userEvent.type(screen.getByLabelText("The least cash you want in the bank"),
                         "15,000");
    await userEvent.click(screen.getByRole("button", { name: "Save the floor" }));
    const posted = () => fetchMock.calls.filter((c) => c.method === "POST")
      .map((c) => c.body);
    await waitFor(() => expect(posted()).toEqual([{ floor_cents: 1500000 }]));
    expect(await screen.findByText("$15,000.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    await userEvent.click(screen.getByRole("button", { name: "No floor" }));
    await waitFor(() => expect(posted()).toEqual([{ floor_cents: 1500000 },
                                                  { floor_cents: null }]));
  });

  it("says so when it is invoices only, and when an account is stale", async () => {
    show(aForecast({
      ready: false, closed_months: 1,
      note: "Close two months and your regular costs will be forecast from them. Until "
        + "then this is only your invoices.",
      accounts: [{ id: "a1", name: "Front Range Bank checking", kind: "bank",
                   amount_cents: 1200000, last_entry_on: "2026-09-12",
                   reconciled_through: null, stale: true }] }));
    expect((await screen.findAllByText(/Close two months and your regular costs/)).length)
      .toBeGreaterThan(0);
    expect(screen.getByText(/has no entry in the last 14 days/)).toHaveTextContent(
      "Front Range Bank checking has no entry in the last 14 days.");
    expect(screen.getByLabelText("Where cash today comes from"))
      .toHaveTextContent("not reconciled yet");
  });

  it("lists what is not counted, and what is likely annual and not in it", async () => {
    show(aForecast({
      left_out: [{ id: "i9", group: "invoice:i9", adjustment: "",
                   why: "more than 60 days overdue",
                   label: "Globex Logistics: Invoice SOP-0101",
                   amount_cents: 850000, due_date: "2026-07-16", days_overdue: 87,
                   link: "/invoices/i9" }],
      likely_annual: [{ id: "x", group: "pattern:adobe", label: "Adobe annual plan",
                        direction: "out",
                        category: "Dues and subscriptions: Software and apps",
                        amount_cents: 119900, last_on: "2025-10-08",
                        likely_on: "2026-10-08", detail: "" }] }));
    const overdue = await screen.findByRole("table", { name: "Not counted" });
    expect(overdue).toHaveTextContent("Globex Logistics: Invoice SOP-0101");
    expect(overdue).toHaveTextContent(
      "more than 60 days overdue; due July 16, 2026, 87 days ago$8,500.00");
    expect(within(overdue).getByRole("link")).toHaveAttribute("href", "/invoices/i9");
    expect(screen.getByText(/hoping is not forecasting/)).toBeInTheDocument();
    const annual = screen.getByRole("table", { name: "Likely annual, to confirm" });
    expect(annual).toHaveTextContent("Adobe annual plan");
    expect(annual).toHaveTextContent(
      "last on October 8, 2025; likely again about October 8, 2026$1,199.00");
    expect(screen.getByText(/Seen once, about a year ago, and not since/))
      .toHaveTextContent("They are not in the forecast until you confirm them");
  });

  it("draws the cash line with the same figures as the table, read by pointer or keys",
    async () => {
      show();
      const chart = await screen.findByRole("img", { name: /Cash at the end of each week/ });
      expect(chart).toHaveAccessibleName(
        "Cash at the end of each week, from $11,305.00 to -$4,018.00. The table below has "
        + "every figure.");
      // One series: a single line, with zero and the floor as named reference
      // lines, and so no legend.
      expect(chart.querySelectorAll("path")).toHaveLength(1);
      expect(screen.queryByRole("list", { name: "What the lines are" }))
        .not.toBeInTheDocument();
      expect(chart).toHaveTextContent("zero");
      expect(chart).toHaveTextContent("your floor, $10k");
      const readout = screen.getByRole("status", { name: "The point on the chart" });
      expect(readout).toHaveTextContent("Point at the line, or use the arrow keys");
      chart.focus();
      await userEvent.keyboard("{ArrowRight}{ArrowRight}");
      expect(readout).toHaveTextContent(
        "$8,982.00 at the end of the week of October 18, 2026 · under your floor");
      const table = screen.getByRole("table", { name: "The cash forecast as a table" });
      expect(within(table).getAllByRole("row")[2]).toHaveTextContent("$8,982.00");
    });

  it("offers the download", async () => {
    show();
    expect(await screen.findByRole("link", { name: "Download the forecast" }))
      .toHaveAttribute("href", "/api/finance-forecast/export/");
  });
});
