import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Forecast, ForecastReview } from "../lib/api";
import { FINANCE_DISCLAIMER } from "../lib/finance";
import { aMe } from "../test/fixtures";
import { AI, aForecast, line, weeks } from "../test/forecast";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";

/** P6 M2, the second stop: planned lines, the what-if, the owner's changes,
 *  how good it has been, and the two buttons that ask Claude. */

const F = "/api/finance-forecast/";

function show(data: Forecast = aForecast(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/finance-forecast/explain/": AI,
    ...extra, "GET /api/me": aMe({ modules: ["bookkeeping", "forecast"] }),
    "GET /api/finance-forecast/": data, ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance tab="forecast" />);
  return fetchMock;
}

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string, method = "POST") =>
  fetchMock.calls.filter((c) => c.method === method && c.url.endsWith(suffix))
    .map((c) => c.body);

/** Every list on the screen is folded away until asked for. */
async function unfold(title: RegExp) {
  const heading = await screen.findByRole("heading", { name: title });
  const card = heading.closest("section") as HTMLElement;
  const summary = card.querySelector("summary");
  if (summary) await userEvent.click(summary);
  return card;
}

const planned = (more: object = {}) => ({
  id: "p1", description: "Operations analyst", direction: "out" as const,
  amount_cents: 650000, on_date: "2026-12-01", repeat: "monthly" as const, until: null,
  is_what_if: false, source: "" as const, state: "planned" as const,
  next_on: "2026-12-01", ...more });

beforeEach(() => { vi.unstubAllGlobals(); });

describe("planned lines", () => {
  it("adds one: what it is, in or out, an amount, a date, and how often", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/planned/": () => ({
        status: 201, body: aForecast({ planned: [planned()] }) }) });
    await userEvent.click(await screen.findByRole("button", { name: "Add a planned line" }));
    const form = screen.getByRole("group", { name: "The new planned line" });
    const add = within(form).getByRole("button", { name: "Add it" });
    expect(add).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("The new planned line: what it is"),
                         "Operations analyst");
    await userEvent.type(within(form).getByLabelText("The new planned line: amount"),
                         "6,500");
    const when = within(form).getByLabelText("The new planned line: date");
    await userEvent.clear(when);
    await userEvent.type(when, "2026-12-01");
    // "Until" is offered only for one that repeats.
    expect(within(form).queryByLabelText("The new planned line: until")).toBeNull();
    await userEvent.selectOptions(
      within(form).getByLabelText("The new planned line: how often"), "monthly");
    expect(within(form).getByLabelText("The new planned line: until")).toBeInTheDocument();
    await userEvent.click(add);
    await waitFor(() => expect(sent(fetchMock, "planned/")).toEqual([{
      description: "Operations analyst", direction: "out", amount_cents: 650000,
      on_date: "2026-12-01", repeat: "monthly", until: null, is_what_if: false }]));
    const table = await screen.findByRole("table", { name: "Planned lines" });
    expect(table).toHaveTextContent("December 1, 2026every monthOperations analyst");
    expect(table).toHaveTextContent("out $6,500.00");
    expect(screen.getByText(/It never becomes an entry in your books/)).toBeInTheDocument();
  });

  it("says a planned line happened, or removes it; and asks about one that lapsed",
    async () => {
      const data = aForecast({ planned: [
        planned(), planned({ id: "p2", description: "New laptops", repeat: "",
                             state: "lapsed", next_on: null, source: "review" }),
        planned({ id: "p3", description: "Old deposit", state: "happened" })] });
      const fetchMock = show(data, {
        "POST /api/finance-forecast/planned/p1/happened/": () => ({ body: data }),
        "DELETE /api/finance-forecast/planned/p2/": () => ({ body: data }) });
      const table = await screen.findByRole("table", { name: "Planned lines" });
      const lapsed = within(table).getByText("New laptops").closest("tr")!;
      expect(lapsed).toHaveTextContent("did not happen?");
      expect(lapsed).toHaveTextContent("from a review");
      // One that happened has nothing left to do to it.
      const happened = within(table).getByText("Old deposit").closest("tr")!;
      expect(within(happened).queryByRole("button")).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "Operations analyst happened" }));
      await userEvent.click(screen.getByRole("button", { name: "Remove New laptops" }));
      await waitFor(() => expect(sent(fetchMock, "planned/p2/", "DELETE")).toHaveLength(1));
      expect(sent(fetchMock, "planned/p1/happened/")).toHaveLength(1);
    });
});

describe("the what-if", () => {
  const other = () => {
    const rows = weeks(1000000).map((row, index) => (index < 6 ? row
      : { ...row, start_cents: row.start_cents + 680000, end_cents: row.end_cents + 680000,
          below_zero: row.end_cents + 680000 < 0 }));
    const low = rows.reduce((a, b) => (b.end_cents < a.end_cents ? b : a));
    const view = { low_cents: low.end_cents, low_start: low.start, low_label: "",
                   end_cents: rows[25].end_cents, first_below_floor: null,
                   first_below_zero: null };
    return { weeks: rows, months: aForecast().months,
             views: { "30": view, "90": view, "180": view, months: view },
             difference_at_low: { "30": 0, "90": 680000, "180": 680000, months: 0 },
             off: [], on: [], amounts: {} };
  };

  it("tries the forecast without a line, beside it as it stands, and saves nothing",
    async () => {
      const fetchMock = show(aForecast(), {
        "POST /api/finance-forecast/what-if/": () => ({
          body: aForecast({ what_if: other() }) }) });
      const regular = await unfold(/^Regular \(/);
      await userEvent.click(within(regular).getByRole("button", {
        name: "Try without Larimer Square Cowork" }));
      await waitFor(() => expect(sent(fetchMock, "what-if/")).toEqual([
        { off: ["pattern:rent"], on: [], amounts: {} }]));
      const says = await screen.findByRole("status", { name: "The what-if" });
      expect(says).toHaveTextContent("What if: without Larimer Square Cowork.");
      await waitFor(() => expect(says).toHaveTextContent(
        "The lowest point would be $2,782.00, $6,800.00 higher than it stands."));
      // The table gains a column, and the chart a second line, a legend, and
      // each line's name at its end.
      const table = screen.getByRole("table", { name: "The cash forecast as a table" });
      expect(within(table).getByRole("columnheader", { name: "What if" })).toBeInTheDocument();
      const chart = screen.getByRole("img", { name: /Cash at the end of each week/ });
      expect(chart.querySelectorAll("path")).toHaveLength(2);
      expect(chart.querySelector('path[data-series="what-if"]'))
        .toHaveAttribute("stroke-dasharray", "5 3");
      expect(chart).toHaveTextContent("as it stands");
      expect(chart).toHaveTextContent("what if");
      expect(within(screen.getByRole("list", { name: "What the lines are" }))
        .getAllByRole("listitem").map((li) => li.textContent?.trim()))
        .toEqual(["As it stands", "What if"]);
      expect(within(regular).getByRole("link", { name: "Larimer Square Cowork" })
        .closest("tr")).toHaveTextContent("tried without");
      // Cleared, it is gone, and nothing but the look was ever sent.
      await userEvent.click(screen.getByRole("button", { name: "Clear the what-if" }));
      expect(screen.queryByRole("status", { name: "The what-if" })).toBeNull();
      expect(chart.querySelectorAll("path")).toHaveLength(1);
      expect(fetchMock.calls.filter((c) => c.method !== "GET").map((c) => c.url))
        .toEqual([`${F}what-if/`]);
    });

  it("tries it without a client, with a what-if line, and with another amount",
    async () => {
      const fetchMock = show(aForecast({ planned: [planned({
        id: "p9", description: "A second associate", is_what_if: true,
        state: "what_if" })] }), {
        "POST /api/finance-forecast/what-if/": () => ({
          body: aForecast({ what_if: other() }) }) });
      await userEvent.selectOptions(
        await screen.findByLabelText("A client to try the forecast without"), "co1");
      await userEvent.click(screen.getByRole("button", { name: "Try it" }));
      await userEvent.click(screen.getByRole("button", { name: "Try A second associate" }));
      const regular = await unfold(/^Regular \(/);
      await userEvent.click(within(regular).getByRole("button", {
        name: "Change Larimer Square Cowork" }));
      const change = within(regular).getByRole("group", {
        name: "Change Larimer Square Cowork" });
      const amount = within(change).getByLabelText(
        "The new amount of Larimer Square Cowork");
      await userEvent.clear(amount);
      await userEvent.type(amount, "750");
      await userEvent.click(within(change).getByRole("button",
                                                     { name: "Only try this amount" }));
      await waitFor(() => expect(sent(fetchMock, "what-if/").at(-1)).toEqual({
        off: ["client:co1"], on: ["p9"], amounts: { "pattern:rent": 75000 } }));
      expect(await screen.findByRole("status", { name: "The what-if" })).toHaveTextContent(
        "What if: without Acme Fasteners (every invoice); with A second associate; "
        + "Larimer Square Cowork at $750.00.");
      // Trying an amount is a look: nothing was saved as a change.
      expect(sent(fetchMock, "adjust/")).toEqual([]);
    });

  it("saves a what-if line as planned when the owner decides to", async () => {
    const fetchMock = show(aForecast({ planned: [planned({
      id: "p9", description: "A second associate", is_what_if: true, state: "what_if" })] }), {
      "PATCH /api/finance-forecast/planned/p9/": () => ({ body: aForecast() }) });
    expect(await screen.findByText("what-if")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Plan A second associate" }));
    await waitFor(() => expect(sent(fetchMock, "planned/p9/", "PATCH"))
      .toEqual([{ is_what_if: false }]));
  });
});

describe("the owner's changes to a line", () => {
  it("changes a regular line's amount from a date, and each other way", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/adjust/": () => ({ status: 201, body: aForecast() }) });
    const regular = await unfold(/^Regular \(/);
    const open = () => userEvent.click(within(regular).getByRole("button", {
      name: "Change Larimer Square Cowork" }));
    await open();
    const group = () => within(regular).getByRole("group",
                                                  { name: "Change Larimer Square Cowork" });
    const amount = within(group()).getByLabelText("The new amount of Larimer Square Cowork");
    await userEvent.clear(amount);
    await userEvent.type(amount, "750");
    const from = within(group()).getByLabelText("From when Larimer Square Cowork changes");
    await userEvent.clear(from);
    await userEvent.type(from, "2027-01-01");
    await userEvent.click(within(group()).getByRole("button", { name: "Save the change" }));
    await open();
    await userEvent.selectOptions(
      within(group()).getByLabelText("How Larimer Square Cowork changes"), "pause");
    const until = within(group()).getByLabelText("Until when Larimer Square Cowork is paused");
    await userEvent.type(until, "2026-12-31");
    await userEvent.click(within(group()).getByRole("button", { name: "Save the change" }));
    await open();
    await userEvent.selectOptions(
      within(group()).getByLabelText("How Larimer Square Cowork changes"), "not_regular");
    expect(within(group()).queryByLabelText("From when Larimer Square Cowork changes"))
      .toBeNull();
    await userEvent.click(within(group()).getByRole("button", { name: "Save the change" }));
    const today = new Date().toISOString().slice(0, 10);
    await waitFor(() => expect(sent(fetchMock, "adjust/")).toEqual([
      { line: "pattern:rent", kind: "amount", amount_cents: 75000, from_date: "2027-01-01" },
      { line: "pattern:rent", kind: "pause", from_date: today, until_date: "2026-12-31" },
      { line: "pattern:rent", kind: "not_regular" }]));
    // A card's payment is worked out, not changed: it can only be tried without.
    expect(within(regular).queryByRole("button", { name: "Change Business Visa payment" }))
      .toBeNull();
  });

  it("shows each change beside its line and in its own list, and undoes one", async () => {
    const fetchMock = show(aForecast({
      lines: [line("rent", { adjusted: "You set it to $750.00 from January 1, 2027.",
                             adjustment: "j1", amount_cents: 75000 })],
      adjustments: [{ id: "j1", group: "pattern:rent", label: "Larimer Square Cowork",
                      kind: "amount", text: "You set it to $750.00 from January 1, 2027.",
                      source: "review", at: "2026-10-10T15:00:00Z", by: "John Carter" }] }), {
      "POST /api/finance-forecast/adjust/j1/undo/": () => ({ body: aForecast() }) });
    const regular = await unfold(/^Regular \(/);
    expect(within(regular).getByRole("link", { name: "Larimer Square Cowork" })
      .closest("tr")).toHaveTextContent("You set it to $750.00 from January 1, 2027.");
    const changed = screen.getByRole("table", { name: "What you have changed" });
    expect(changed).toHaveTextContent(
      "Larimer Square Cowork from a reviewYou set it to $750.00 from January 1, 2027."
      + "October 10, 2026, John Carter");
    await userEvent.click(screen.getByRole("button", {
      name: "Undo the change to Larimer Square Cowork" }));
    await waitFor(() => expect(sent(fetchMock, "adjust/j1/undo/")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("table", { name: "What you have changed" }))
      .toBeNull());
  });

  it("moves an invoice to the day the client said, or leaves it out", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/adjust/": () => ({ status: 201, body: aForecast() }) });
    const known = await unfold(/^Known \(/);
    const name = "Acme Fasteners: Invoice SOP-0188";
    await userEvent.click(within(known).getByRole("button", { name: `Change ${name}` }));
    const when = within(known).getByLabelText(`When you expect ${name}`);
    expect(when).toHaveValue("2026-10-20");
    await userEvent.clear(when);
    await userEvent.type(when, "2026-10-25");
    await userEvent.click(within(known).getByRole("button", { name: "Move it" }));
    await userEvent.click(within(known).getByRole("button", { name: `Change ${name}` }));
    await userEvent.click(within(known).getByRole("button", { name: "Leave it out" }));
    await waitFor(() => expect(sent(fetchMock, "adjust/")).toEqual([
      { line: "invoice:i1", kind: "expected", expected_on: "2026-10-25" },
      { line: "invoice:i1", kind: "leave_out" }]));
  });

  it("puts back an invoice that is not counted: with a date, or by undoing",
    async () => {
      const data = aForecast({ left_out: [
        { id: "i9", group: "invoice:i9", adjustment: "", why: "more than 60 days overdue",
          label: "Globex: Invoice SOP-0101", amount_cents: 850000, due_date: "2026-07-16",
          days_overdue: 87, link: "/invoices/i9" },
        { id: "i8", group: "invoice:i8", adjustment: "j8", why: "left out by you",
          label: "Hooli: Invoice SOP-0177", amount_cents: 420000, due_date: "2026-10-30",
          days_overdue: 0, link: "/invoices/i8" }] });
      const fetchMock = show(data, {
        "POST /api/finance-forecast/adjust/j8/undo/": () => ({ body: data }),
        "POST /api/finance-forecast/adjust/": () => ({ status: 201, body: data }) });
      const table = await screen.findByRole("table", { name: "Not counted" });
      const old = within(table).getByText("Globex: Invoice SOP-0101").closest("tr")!;
      const back = within(old).getByRole("button",
                                         { name: "Put back Globex: Invoice SOP-0101" });
      expect(back).toBeDisabled();
      await userEvent.type(within(old).getByLabelText(
        "When you expect Globex: Invoice SOP-0101"), "2026-11-15");
      await userEvent.click(back);
      expect(within(table).getByText("Hooli: Invoice SOP-0177").closest("tr"))
        .toHaveTextContent("left out by you; due October 30, 2026");
      await userEvent.click(screen.getByRole("button",
                                             { name: "Put back Hooli: Invoice SOP-0177" }));
      await waitFor(() => expect(sent(fetchMock, "adjust/j8/undo/")).toHaveLength(1));
      expect(sent(fetchMock, "adjust/")).toEqual([
        { line: "invoice:i9", kind: "expected", expected_on: "2026-11-15" }]);
    });

  it("confirms a likely annual item as a planned line, with the owner's own figures",
    async () => {
      const data = aForecast({ likely_annual: [{
        id: "x", group: "pattern:adobe", label: "Adobe annual plan", direction: "out",
        category: "Dues and subscriptions: Software and apps", amount_cents: 119900,
        last_on: "2025-10-08", likely_on: "2027-10-08", detail: "" }] });
      const fetchMock = show(data, {
        "POST /api/finance-forecast/planned/": () => ({ status: 201, body: data }),
        "POST /api/finance-forecast/adjust/": () => ({ status: 201, body: data }) });
      await userEvent.click(await screen.findByRole("button",
                                                    { name: "Confirm Adobe annual plan" }));
      const form = screen.getByRole("group", { name: "Confirming Adobe annual plan" });
      // Last year's figures to start from; the owner's to change.
      const amount = within(form).getByLabelText("Confirming Adobe annual plan: amount");
      expect(amount).toHaveValue("1199.00");
      await userEvent.clear(amount);
      await userEvent.type(amount, "1,319");
      await userEvent.click(within(form).getByRole("button", { name: "Confirm it" }));
      await waitFor(() => expect(sent(fetchMock, "planned/")).toEqual([{
        description: "Adobe annual plan", direction: "out", amount_cents: 131900,
        on_date: "2027-10-08", repeat: "", until: null, is_what_if: false,
        source: "annual", line: "pattern:adobe" }]));
      await userEvent.click(screen.getByRole("button",
                                             { name: "Adobe annual plan is not regular" }));
      await waitFor(() => expect(sent(fetchMock, "adjust/")).toEqual([
        { line: "pattern:adobe", kind: "not_regular" }]));
    });
});

describe("how good it has been", () => {
  it("sets each closed month's forecast beside what happened, with no score", async () => {
    show(aForecast({ history: [
      { month: "2026-09", label: "September 2026", taken_on: "2026-09-01",
        forecast: { in_cents: 4000000, out_cents: 3100000, end_cents: 5200000 },
        actual: { in_cents: 3600000, out_cents: 3244000, end_cents: 4656000 },
        largest: [
          { name: "Client invoices", forecast_cents: 4000000, actual_cents: 3600000,
            difference_cents: -400000 },
          { name: "Travel: airfare, rental car, hotel: Airfare", forecast_cents: -90000,
            actual_cents: -234000, difference_cents: -144000 }] },
      { month: "2026-08", label: "August 2026", taken_on: "2026-08-04",
        forecast: { in_cents: 100, out_cents: 100, end_cents: 100 },
        actual: { in_cents: 100, out_cents: 100, end_cents: 100 }, largest: [] }] }));
    const table = await screen.findByRole("table", { name: "How good it has been" });
    const [september, august] = within(table).getAllByRole("row").slice(1);
    expect(september).toHaveTextContent(
      "September 2026$52,000.00$46,560.00−$5,440.00$36,000.00forecast $40,000.00"
      + "$32,440.00forecast $31,000.00");
    expect(september).toHaveTextContent(
      "Client invoices: forecast $40,000.00, was $36,000.00; Travel: airfare, rental car, "
      + "hotel: Airfare: forecast -$900.00, was -$2,340.00");
    // One not taken on the 1st says which day it stood on.
    expect(august).toHaveTextContent("as it stood on August 4, 2026");
    expect(august).toHaveTextContent("None.");
    expect(screen.getByText(/There is no score/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/accuracy|% right/i);
  });

  it("is not there until a closed month has a forecast to set beside it", async () => {
    show();
    await screen.findByRole("heading", { name: /^Known \(/ });
    expect(screen.queryByRole("table", { name: "How good it has been" })).toBeNull();
  });
});

describe("the buttons that ask Claude", () => {
  it("asks nothing until pressed, says the price before and the cost after", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/explain/": () => ({ body: {
        text: "The low point is the week the card is paid.", cost_usd: "0.021400",
        disclaimer: FINANCE_DISCLAIMER, used_today: 3, cap: 20 } }) });
    const ask = await screen.findByRole("button",
                                        { name: "Explain this forecast (about $0.02)" });
    expect(screen.getByRole("button", { name: "Review with Claude (about $0.06)" }))
      .toBeEnabled();
    expect(screen.getByText("2 of 20 used today.")).toBeInTheDocument();
    expect(sent(fetchMock, "explain/")).toEqual([]);
    await userEvent.click(ask);
    // The view shown is the one explained.
    await waitFor(() => expect(sent(fetchMock, "explain/")).toEqual([{ view: "90" }]));
    const answer = await screen.findByRole("note", { name: "Explanation" });
    expect(answer).toHaveTextContent("The low point is the week the card is paid.");
    expect(answer).toHaveTextContent("This cost $0.0214. 3 of 20 used today.");
    expect(answer).toHaveTextContent(FINANCE_DISCLAIMER);
  });

  it("says how clients are sent, and lets the owner include their names", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/client-names/": () => ({
        body: aForecast({ include_client_names: true }) }) });
    const box = await screen.findByLabelText("Include client names in AI explanations");
    expect(box).not.toBeChecked();
    expect(screen.getByText(/Clients are sent as “Client A”, “Client B”, never by name/))
      .toHaveTextContent("The payees and categories of your expenses are sent by name.");
    await userEvent.click(box);
    await waitFor(() => expect(sent(fetchMock, "client-names/")).toEqual([{ include: true }]));
    expect(await screen.findByText(/Clients are sent by name/)).toHaveTextContent(
      "Invoice numbers and contact details never are.");
  });

  it("says why they cannot be pressed: no key, the day's limit, or no closed months",
    async () => {
      show(aForecast(), { "GET /api/finance-forecast/explain/": {
        ...AI, refused: "No Anthropic API key is set. The practice owner adds one under "
          + "AI usage." } });
      expect(await screen.findByText(/No Anthropic API key is set/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Explain this forecast/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /Review with Claude/ })).toBeNull();
      vi.unstubAllGlobals();
    });

  it("keeps Review for a practice with two closed months", async () => {
    show(aForecast({ ready: false, note: "Close two months and your regular costs will "
      + "be forecast from them. Until then this is only your invoices." }));
    expect(await screen.findByRole("button", { name: /Review with Claude/ })).toBeDisabled();
    expect(screen.getByText(/A review reads your closed\s+months, so it needs two of them/))
      .toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /Explain this forecast/ }))
      .toBeEnabled());
    expect(screen.getByRole("button", { name: /Review with Claude/ })).toBeDisabled();
  });

  const REVIEW: ForecastReview = {
    one_offs: [{ group: "pattern:bank", who: "Front Range Bank", direction: "out",
                 category: "Bank charges: Bank fees", why: "Seen twice only.",
                 months: [{ month: "2026-07", amount_cents: 4500 },
                          { month: "2026-09", amount_cents: 4500 }],
                 last_on: "2026-09-15", last_amount_cents: 4500, cadence: "monthly",
                 amount_cents: 4500 }],
    missed: [{ group: "pattern:quill", who: "Ledger & Quill", direction: "out",
               category: "Accounting: Tax preparation", why: "Looks like a yearly return.",
               months: [{ month: "2026-03", amount_cents: 185000 }],
               last_on: "2026-03-18", last_amount_cents: 185000 }],
    questions: [{ topic: "hire", question: "Are you taking anyone on before spring?" }],
    cost_usd: "0.058000", disclaimer: FINANCE_DISCLAIMER, used_today: 3, cap: 20 };

  it("reviews as a form: each answer is the owner's, sent only when confirmed",
    async () => {
      const fetchMock = show(aForecast(), {
        "POST /api/finance-forecast/review/": () => ({ body: REVIEW }),
        "POST /api/finance-forecast/adjust/": () => ({ status: 201, body: aForecast() }),
        "POST /api/finance-forecast/planned/": () => ({ status: 201, body: aForecast() }) });
      await userEvent.click(await screen.findByRole("button", { name: /Review with Claude/ }));
      const review = await screen.findByRole("region", { name: "The review" });
      expect(review).toHaveTextContent("Closing this changes nothing.");
      expect(review).toHaveTextContent("This cost $0.0580. 3 of 20 used today.");
      expect(within(review).getByRole("note", { name: "Review disclaimer" }))
        .toHaveTextContent(FINANCE_DISCLAIMER);
      // Reviewing sent the one call and changed nothing.
      expect(fetchMock.calls.filter((c) => c.method !== "GET").map((c) => c.url))
        .toEqual([`${F}review/`]);

      // 1. A regular line that looks like a one-off, with what the books show.
      const bank = within(review).getByRole("group", { name: "Review of Front Range Bank" });
      expect(bank).toHaveTextContent("Front Range Bank · Bank charges: Bank fees: Seen "
        + "twice only. In your books: 2026-07 $45.00, 2026-09 $45.00.");
      await userEvent.click(within(bank).getByRole("button", { name: "It is a one-off" }));
      expect(await within(bank).findByText("Taken out of the forecast.")).toBeInTheDocument();
      // 2. Looks recurring: added with an amount the owner sets, or not at all.
      const quill = within(review).getByRole("group", { name: "Review of Ledger & Quill" });
      const amount = within(quill).getByLabelText("Adding Ledger & Quill: amount");
      expect(amount).toHaveValue("1850.00");          // the books' own figure, to start from
      await userEvent.clear(amount);
      await userEvent.type(amount, "1,950");
      await userEvent.selectOptions(
        within(quill).getByLabelText("Adding Ledger & Quill: how often"), "");
      const when = within(quill).getByLabelText("Adding Ledger & Quill: date");
      await userEvent.clear(when);
      await userEvent.type(when, "2027-03-18");
      await userEvent.click(within(quill).getByRole("button", { name: "Add it" }));
      expect(await within(quill).findByText("Added as a planned line.")).toBeInTheDocument();
      // 3. A question about what the books cannot know: answered with nothing.
      const question = within(review).getByRole("group", { name: "Question 1" });
      expect(question).toHaveTextContent("Are you taking anyone on before spring?");
      await userEvent.click(within(question).getByRole("button", { name: "Nothing planned" }));
      expect(within(question).getByText("Nothing planned.")).toBeInTheDocument();

      await waitFor(() => expect(sent(fetchMock, "planned/")).toHaveLength(1));
      expect(sent(fetchMock, "adjust/")).toEqual([
        { line: "pattern:bank", kind: "not_regular", source: "review" }]);
      expect(sent(fetchMock, "planned/")).toEqual([{
        description: "Ledger & Quill", direction: "out", amount_cents: 195000,
        on_date: "2027-03-18", repeat: "", until: null, is_what_if: false,
        source: "review" }]);
      await userEvent.click(within(review).getByRole("button", { name: "Close the review" }));
      expect(screen.queryByRole("region", { name: "The review" })).toBeNull();
    });

  it("closing a review unanswered sends nothing", async () => {
    const fetchMock = show(aForecast(), {
      "POST /api/finance-forecast/review/": () => ({ body: REVIEW }) });
    await userEvent.click(await screen.findByRole("button", { name: /Review with Claude/ }));
    const review = await screen.findByRole("region", { name: "The review" });
    await userEvent.click(within(review).getByRole("button", { name: "Close the review" }));
    expect(fetchMock.calls.filter((c) => c.method !== "GET").map((c) => c.url))
      .toEqual([`${F}review/`]);
  });

  it("says so when the review finds nothing", async () => {
    show(aForecast(), { "POST /api/finance-forecast/review/": () => ({
      body: { ...REVIEW, one_offs: [], missed: [], questions: [] } }) });
    await userEvent.click(await screen.findByRole("button", { name: /Review with Claude/ }));
    expect(await screen.findByText("It found nothing to question.")).toBeInTheDocument();
  });
});
