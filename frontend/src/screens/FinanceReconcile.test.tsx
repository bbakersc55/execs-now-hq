import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  FinanceAccount, MonthDetail, ReconcileGrid, ReconcileLine, Reconciliation,
} from "../lib/api";
import { FINANCE_DISCLAIMER, GUIDE_STEPS } from "../lib/finance";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";
import { FinanceSettings } from "./FinanceSettings";

/** P6 M1, the second stop: reconciling an account, closing a month, guided
 *  mode with "Explain this step", and the lock leaving the finance settings. */

const RC = "/api/finance-reconcile/";

const GRID: ReconcileGrid = {
  months: [
    { month: "2026-08", label: "August 2026", state: "closed",
      closed_at: "2026-09-07T23:30:00Z", closed_by: "John Carter" },
    { month: "2026-09", label: "September 2026", state: "open", closed_at: null,
      closed_by: "" },
    { month: "2026-10", label: "October 2026", state: "open", closed_at: null,
      closed_by: "" }],
  accounts: [
    { id: "bank", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4417",
      reconciled_monthly: true, opening_on: "2025-01-01", opening_balance_cents: 1850000,
      next_month: "2026-10",
      bank_said: { on: "2026-10-09", cents: 2412000 },
      cells: { "2026-08": { state: "finished", id: "r-aug", statement_on: "2026-08-31",
                            finished_at: "2026-09-06T22:30:00Z" },
               "2026-09": { state: "open", id: "r-sep", statement_on: "2026-09-30",
                            difference_cents: -30000 },
               "2026-10": { state: "not_started" } } },
    { id: "card", name: "Business Visa", kind: "card", kind_label: "Credit card",
      last4: "0932", reconciled_monthly: true, opening_on: "2025-01-01",
      opening_balance_cents: 124000, next_month: null,
      cells: { "2026-08": { state: "not_started" }, "2026-09": { state: "not_started" },
               "2026-10": { state: "not_started" } } }],
  locked_through: "2026-08-31",
  locked_by: { month: "August 2026", by: "John Carter", at: "2026-09-07T23:30:00Z" },
  next_to_close: "2026-09", guided: false, today: "2026-10-10",
};

const line = (id: string, more: Partial<ReconcileLine>): ReconcileLine => ({
  id, on_date: "2026-09-10", amount_cents: 30000, way: "out", description: "Flight to Tucson",
  counterparty: "United Airlines", kind: "expense", kind_label: "Expense", cleared: false,
  carried: false, from_bank: false, ...more });

const REC: Reconciliation = {
  id: "r-sep",
  account: { id: "bank", name: "Checking", kind: "bank", kind_label: "Bank account" },
  month: "2026-09", month_label: "September 2026", statement_on: "2026-09-30",
  statement_balance_cents: 1170000, state: "open", state_label: "In progress",
  finished_at: null, finished_by: "", reopened_at: null, reopened_by: "", reopen_reason: "",
  starting_balance_cents: 1000000, cleared_in_cents: 200000, cleared_out_cents: 0,
  expected_cents: 1200000, difference_cents: -30000, first: false,
  period_start: "2026-09-01",
  lines: [
    line("fee", { way: "in", amount_cents: 200000, description: "Invoice SOP-0142",
                  counterparty: "Acme Fasteners", kind: "income", kind_label: "Income",
                  cleared: true, from_bank: true, on_date: "2026-09-05" }),
    line("flight", {}),
    line("check", { amount_cents: 75000, description: "Quarterly sponsorship",
                    counterparty: "Denver Metro Chamber", carried: true,
                    on_date: "2026-08-12" })],
  hints: [{ kind: "untick", entry: "flight",
            text: "An unticked entry is for exactly the difference." },
          { kind: "missing", entry: null,
            text: "Something on the statement may not be in the books yet." }],
  unplaced: [{ id: "loose", on_date: "2026-09-28", amount_cents: 680000,
               description: "Invoice SOP-0150", counterparty: "Globex Logistics" }],
  cannot_reopen: "", can_discard: true,
};

const FINISHED: Reconciliation = {
  ...REC, id: "r-aug", month: "2026-08", month_label: "August 2026",
  statement_on: "2026-08-31", state: "finished", finished_at: "2026-09-06T22:30:00Z",
  finished_by: "John Carter", difference_cents: 0, hints: [], unplaced: [],
  can_discard: false };

const MONTH: MonthDetail = {
  month: "2026-09", label: "September 2026", state: "open",
  checklist: [
    { code: "reconciled", label: "Every account reconciled", blocks: true, ok: false,
      count: 2, detail: "Still to reconcile: Checking, Business Visa.",
      link: "/finance/reconcile" },
    { code: "categorized", label: "Nothing uncategorized", blocks: true, ok: true, count: 0,
      detail: "", link: "/finance?category=none&from=2026-09-01&to=2026-09-30" },
    { code: "placed", label: "Invoice payments placed", blocks: true, ok: true, count: 0,
      detail: "", link: "/finance?account=none&from=2026-09-01&to=2026-09-30" },
    { code: "payees", label: "1099 payees named", blocks: false, ok: false, count: 1,
      detail: "1 paid to contractors with nobody named. This is a warning: the month can "
        + "close with it showing.", link: "/finance/1099" }],
  cannot_close: "Still on the checklist: every account reconciled.",
  history: [], reopen_note: "",
};

const PRICE = { estimate_usd: "0.0165", used_today: 3, cap: 20,
                resets_at: "2026-10-11T06:00:00Z", refused: "", disclaimer: FINANCE_DISCLAIMER };

function show(extra: Record<string, unknown> = {}, grid: Partial<ReconcileGrid> = {}) {
  const fetchMock = mockApi({
    // First, so it is matched before a test's own answer for the
    // reconciliation it is the report of.
    "GET /api/finance-reconcile/r-aug/report/": {
      ...FINISHED, practice: "Summit Operations Partners",
      cleared: [REC.lines[0]], outstanding: [REC.lines[2]], outstanding_in_cents: 0,
      outstanding_out_cents: 75000, disclaimer: FINANCE_DISCLAIMER },
    ...extra,
    "GET /api/me": aMe({ modules: ["bookkeeping"] }),
    "GET /api/finance-reconcile/explain/": PRICE,
    "GET /api/finance-reconcile/r-sep/": REC,
    "GET /api/finance-reconcile/r-aug/": FINISHED,
    "GET /api/finance-reconcile/": { ...GRID, ...grid },
    "GET /api/finance-months/2026-09/": MONTH,
    "GET /api/finance-categories/": [],
    // Again, so a test's own answer replaces the one above while keeping its
    // place in front of the less specific addresses.
    ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance tab="reconcile" />);
  return fetchMock;
}

const posts = (fetchMock: ReturnType<typeof mockApi>, suffix: string, method = "POST") =>
  fetchMock.calls.filter((c) => c.method === method && c.url.endsWith(suffix))
    .map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

describe("the Reconcile tab", () => {
  it("is beside Entries for a practice with Bookkeeping, and absent without it", async () => {
    show();
    expect(await screen.findByRole("link", { name: "Reconcile" }))
      .toHaveAttribute("href", "/finance/reconcile");
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me": aMe({ modules: [] }), "GET /api/finance-accounts/": [],
      "GET /api/finance-categories/": [], "GET /api/finance-payees/": { payees: [] },
      "GET /api/finance-entries/": { entries: [], count: 0, totals: {
        income_cents: 0, expenses_cents: 0, net_cents: 0 } } }));
    const { container } = renderRoute(<Finance tab="entries" />);
    await within(container).findByRole("link", { name: "Import" });
    expect(within(container).queryByRole("link", { name: "Reconcile" }))
      .not.toBeInTheDocument();
  });

  it("shows accounts down and months across, each cell's state, and what set the lock",
    async () => {
      show();
      const grid = await screen.findByRole("table",
                                           { name: "Reconciliations by account and month" });
      expect(within(grid).getByRole("button", { name: "Checking, August 2026: Reconciled" }))
        .toHaveTextContent("Reconciled September 6, 2026");
      expect(within(grid).getByRole("button",
                                    { name: "Checking, September 2026: In progress" }))
        .toHaveTextContent("In progress, -$300.00 off");
      // The next month can be started; an account's first may be any month.
      expect(within(grid).getByRole("button", { name: "Checking, October 2026: start" }))
        .toBeInTheDocument();
      expect(within(grid).getByRole("button", { name: "Business Visa, August 2026: start" }))
        .toBeInTheDocument();
      expect(within(grid).getByRole("button", { name: "August 2026: Closed" }))
        .toBeInTheDocument();
      expect(within(grid).getByRole("button", { name: "September 2026: Open" }))
        .toHaveTextContent("Close…");
      expect(screen.getByText(/The books are locked through/)).toHaveTextContent(
        "The books are locked through August 31, 2026, set by closing August 2026 "
        + "(John Carter).");
    });

  it("says so when the lock was typed before month close began", async () => {
    show({}, { locked_by: null });
    expect(await screen.findByText(/The books are locked through/))
      .toHaveTextContent("a date typed before month close began");
  });
});

describe("reconciling an account", () => {
  it("starts one from the statement's date and balance, offering the bank's own figure",
    async () => {
      const fetchMock = show({ "POST /api/finance-reconcile/": () => ({
        status: 201, body: REC }) });
      await userEvent.click(await screen.findByRole("button",
                                                    { name: "Checking, October 2026: start" }));
      expect(screen.getByLabelText("Statement ending date")).toHaveValue("2026-10-09");
      expect(screen.getByText(/Your bank's file ended at \$24,120.00 on October 9, 2026/))
        .toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Start reconciling" }));
      await waitFor(() => expect(posts(fetchMock, RC)).toEqual([
        { account: "bank", statement_on: "2026-10-09", statement_balance_cents: 2412000 }]));
    });

  it("lets an account's first reconciliation begin later, with its own starting balance",
    async () => {
      const fetchMock = show({ "POST /api/finance-reconcile/": () => ({
        status: 201, body: REC }) });
      await userEvent.click(await screen.findByRole(
        "button", { name: "Business Visa, September 2026: start" }));
      expect(screen.getByText(/starts from the opening balance of \$1,240.00/))
        .toBeInTheDocument();
      await userEvent.type(screen.getByLabelText("Statement ending balance"), "310.25");
      await userEvent.click(screen.getByLabelText("Begin reconciling with this statement"));
      await userEvent.type(screen.getByLabelText("Statement starting balance"), "1,100");
      await userEvent.click(screen.getByRole("button", { name: "Start reconciling" }));
      await waitFor(() => expect(posts(fetchMock, RC)).toEqual([
        { account: "card", statement_on: "2026-09-30", statement_balance_cents: 31025,
          starting_balance_cents: 110000, starting_on: "2026-09-01" }]));
    });

  it("shows the difference as its sum, always, and finishes only at zero", async () => {
    // The server's copy: what a tick changes is what the next read returns.
    let now: Reconciliation = REC;
    const fetchMock = show({
      "POST /api/finance-reconcile/r-sep/tick/": () => {
        now = { ...REC, difference_cents: 0, cleared_out_cents: 30000, hints: [],
                lines: REC.lines.map((l) => (l.id === "flight" ? { ...l, cleared: true } : l)) };
        return { body: now };
      },
      "POST /api/finance-reconcile/r-sep/finish/": () => ({ body: now }),
      "GET /api/finance-reconcile/r-sep/": () => ({ body: now }) });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, September 2026: In progress" }));
    const sum = await screen.findByRole("status", { name: "The difference" });
    expect(sum).toHaveTextContent(
      "Statement balance $11,700.00 − (starting balance $10,000.00 + cleared money in "
      + "$2,000.00 − cleared money out $0.00) = difference -$300.00");
    expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();

    // Money in and money out are two columns; what an earlier statement left is above.
    const earlier = screen.getByRole("table", { name: "From earlier statements" });
    expect(within(earlier).getByText(/Quarterly sponsorship/)).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Money out" }))
      .getByText(/Flight to Tucson/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Money in" })).not.toBeInTheDocument();
    // Ticked lines are in the "Cleared" list, marked where the bank brought them in.
    const cleared = screen.getByRole("table", { name: "Cleared" });
    expect(within(cleared).getByText(/Invoice SOP-0142/).closest("tr"))
      .toHaveTextContent("from the bank");

    // The first of the usual causes offers to tick the entry it found.
    expect(screen.getByText(/An unticked entry is for exactly the difference/))
      .toHaveTextContent("Flight to Tucson, $300.00, September 10, 2026");
    await userEvent.click(screen.getByRole("button", { name: "Tick this one?" }));
    await waitFor(() => expect(posts(fetchMock, "r-sep/tick/")).toEqual([
      { entries: ["flight"], cleared: true }]));
    await waitFor(() => expect(screen.getByRole("status", { name: "The difference" }))
      .toHaveTextContent("= difference $0.00"));
    expect(screen.queryByText("What it usually is")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    await waitFor(() => expect(posts(fetchMock, "r-sep/finish/")).toHaveLength(1));
  });

  it("ticks one line, ticks all, and unticks all", async () => {
    const fetchMock = show({ "POST /api/finance-reconcile/r-sep/tick/": () => ({ body: REC }) });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, September 2026: In progress" }));
    await userEvent.click(await screen.findByLabelText("Tick Quarterly sponsorship, $750.00"));
    // Each says how many before it acts.
    await userEvent.click(screen.getByRole("button",
                                           { name: "Tick all 2 through the statement date" }));
    await userEvent.click(screen.getByRole("button", { name: "Untick all 1" }));
    await waitFor(() => expect(posts(fetchMock, "r-sep/tick/")).toEqual([
      { entries: ["check"], cleared: true }, { all: true, cleared: true },
      { all: true, cleared: false }]));
  });

  it("ticks all that one list shows, or unticks them, with the count on the button",
    async () => {
      const more: Reconciliation = { ...REC, lines: [
        ...REC.lines, line("hotel", { description: "Hotel, Tucson", amount_cents: 41000 }),
        line("fee2", { way: "in", amount_cents: 90000, description: "Invoice SOP-0143",
                       kind: "income", kind_label: "Income", cleared: true })] };
      const fetchMock = show({
        "GET /api/finance-reconcile/r-sep/": more,
        "POST /api/finance-reconcile/r-sep/tick/": () => ({ body: more }) });
      await userEvent.click(await screen.findByRole(
        "button", { name: "Checking, September 2026: In progress" }));
      // Money out shows two unticked lines; the list of one has no such button.
      await userEvent.click(await screen.findByRole(
        "button", { name: "Tick all 2 shown in Money out" }));
      expect(screen.queryByRole("button", { name: /shown in From earlier statements/ }))
        .not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button",
                                             { name: "Untick all 2 shown in Cleared" }));
      await waitFor(() => expect(posts(fetchMock, "r-sep/tick/")).toEqual([
        { entries: ["flight", "hotel"], cleared: true },
        { entries: ["fee", "fee2"], cleared: false }]));
    });

  it("lists a payment received and not yet placed, and places it from here", async () => {
    let now: Reconciliation = REC;
    const fetchMock = show({
      "POST /api/finance-reconcile/r-sep/place/": () => {
        now = { ...REC, unplaced: [] };
        return { body: now };
      },
      "GET /api/finance-reconcile/r-sep/": () => ({ body: now }) });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, September 2026: In progress" }));
    const loose = await screen.findByRole("table", { name: "Received, not yet placed" });
    expect(loose).toHaveTextContent("Invoice SOP-0150 · Globex Logistics$6,800.00");
    await userEvent.click(screen.getByRole("button", { name: "Place Invoice SOP-0150 here" }));
    await waitFor(() => expect(posts(fetchMock, "r-sep/place/")).toEqual([{ entry: "loose" }]));
    await waitFor(() => expect(screen.queryByText("Received, not yet placed"))
      .not.toBeInTheDocument());
  });

  it("adds an entry without leaving the statement", async () => {
    const fetchMock = show({
      "POST /api/finance-entries/": () => ({ status: 201, body: {} }),
      "GET /api/finance-categories/": [
        { id: "fees", name: "Bank and merchant fees", type: "expense", type_label: "Expense",
          cpa_code: "", position: 0, archived: false, system: false, parent: null }] });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, September 2026: In progress" }));
    // Offered among the usual causes, and always in the row of actions.
    await userEvent.click((await screen.findAllByRole("button", { name: "Add an entry" }))[0]);
    await userEvent.type(screen.getByLabelText("Amount of the new entry"), "12");
    await userEvent.selectOptions(await screen.findByLabelText("Category of the new entry"),
                                  "fees");
    await userEvent.type(screen.getByLabelText("Description of the new entry"), "Wire fee");
    await userEvent.click(screen.getByRole("button", { name: "Add it" }));
    await waitFor(() => expect(posts(fetchMock, "/api/finance-entries/")).toEqual([
      { kind: "expense", on_date: "2026-09-30", amount_cents: 1200, account: "bank",
        category: "fees", description: "Wire fee" }]));
  });

  it("calls a card's two sides charges and payments, and its balance what is owed",
    async () => {
      show({ "GET /api/finance-reconcile/r-sep/": {
        ...REC, account: { id: "card", name: "Business Visa", kind: "card",
                           kind_label: "Credit card" },
        statement_balance_cents: 154000, starting_balance_cents: 124000,
        cleared_in_cents: 0, cleared_out_cents: 30000, expected_cents: 154000,
        difference_cents: 0, hints: [], unplaced: [],
        lines: [line("flight", { cleared: true }), line("pay", { way: "in" })] } });
      await userEvent.click(await screen.findByRole(
        "button", { name: "Checking, September 2026: In progress" }));
      expect(await screen.findByRole("status", { name: "The difference" })).toHaveTextContent(
        "Statement balance $1,540.00 − (owed at the start $1,240.00 + cleared charges "
        + "$300.00 − cleared payments and credits $0.00) = difference $0.00");
      expect(screen.getByRole("table", { name: "Payments and credits" })).toBeInTheDocument();
      expect(screen.getByText("Balance owed on the statement")).toBeInTheDocument();
    });

  it("shows a finished one as its report, and reopens it only with a reason", async () => {
    const fetchMock = show({
      "POST /api/finance-reconcile/r-aug/reopen/": () => ({ body: { ...FINISHED,
                                                                    state: "open" } }) });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, August 2026: Reconciled" }));
    const report = await screen.findByRole("region", { name: "Reconciliation report" });
    expect(report).toHaveTextContent("Summit Operations Partners · Checking · statement "
      + "ending August 31, 2026. Finished by John Carter on September 6, 2026.");
    expect(within(report).getByRole("table", { name: "Still outstanding" }))
      .toHaveTextContent("Quarterly sponsorship");
    expect(within(report).getByRole("note", { name: "Report disclaimer" }))
      .toHaveTextContent(FINANCE_DISCLAIMER);
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reopen…" }));
    expect(screen.getByRole("button", { name: "Reopen it" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Why the reconciliation is being reopened"),
                         "The amount was wrong.");
    await userEvent.click(screen.getByRole("button", { name: "Reopen it" }));
    await waitFor(() => expect(posts(fetchMock, "r-aug/reopen/")).toEqual([
      { reason: "The amount was wrong." }]));
  });

  it("says why a finished one cannot be reopened, where it cannot", async () => {
    show({ "GET /api/finance-reconcile/r-aug/": {
      ...FINISHED, cannot_reopen: "August 2026 is closed. Reopen the month first." } });
    await userEvent.click(await screen.findByRole(
      "button", { name: "Checking, August 2026: Reconciled" }));
    expect(await screen.findByText("August 2026 is closed. Reopen the month first."))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen…" })).not.toBeInTheDocument();
  });
});

describe("closing a month", () => {
  const open = async (name = "September 2026: Open") =>
    userEvent.click(await screen.findByRole("button", { name }));

  it("shows the checklist ticking itself, with a way to each list, and what blocks",
    async () => {
      show();
      await open();
      const list = await screen.findByRole("table",
                                           { name: "Close checklist for September 2026" });
      const rows = within(list).getAllByRole("row");
      expect(rows.map((row) => row.textContent)).toEqual([
        "To doEvery account reconciledStill to reconcile: Checking, Business Visa.Show me",
        "DoneNothing uncategorized", "DoneInvoice payments placed",
        expect.stringMatching(/^Warning1099 payees named1 paid to contractors.*Show me$/)]);
      expect(within(rows[3]).getByRole("link", { name: "Show me" }))
        .toHaveAttribute("href", "/finance/1099");
      expect(screen.getByRole("button", { name: "Close September 2026" })).toBeDisabled();
      expect(screen.getByText("Still on the checklist: every account reconciled."))
        .toBeInTheDocument();
    });

  it("closes a month whose checklist is done, and says what closing does", async () => {
    const ready = { ...MONTH, cannot_close: "",
                    checklist: MONTH.checklist.map((l) => ({ ...l, ok: true, detail: "" })) };
    let now: MonthDetail = ready;
    const fetchMock = show({
      "GET /api/finance-months/2026-09/": () => ({ body: now }),
      "POST /api/finance-months/2026-09/close/": () => {
        now = { ...ready, state: "closed", history: [{
          closed_at: "2026-10-10T15:00:00Z", closed_by: "John Carter", warnings: [],
          reopened_at: null, reopened_by: "", reopen_reason: "" }] };
        return { body: now };
      } });
    await open();
    expect(await screen.findByText(/Closing locks the books through the last day of/))
      .toHaveTextContent("nothing dated on or before it can be added, changed, removed");
    await userEvent.click(screen.getByRole("button", { name: "Close September 2026" }));
    await waitFor(() => expect(posts(fetchMock, "2026-09/close/")).toHaveLength(1));
    expect(await screen.findByText(/Closed by John Carter on October 10, 2026/))
      .toBeInTheDocument();
  });

  it("says first what reopening is not for, names the later months, and needs a reason",
    async () => {
      const closed: MonthDetail = {
        ...MONTH, month: "2026-08", label: "August 2026", state: "closed", cannot_close: "",
        history: [
          { closed_at: "2026-09-07T23:30:00Z", closed_by: "John Carter", warnings: [
            { code: "payees", label: "1099 payees named", count: 2 }],
            reopened_at: "2026-09-09T16:15:00Z", reopened_by: "John Carter",
            reopen_reason: "Adobe's refund was never entered." },
          { closed_at: "2026-09-09T16:20:00Z", closed_by: "John Carter", warnings: [],
            reopened_at: null, reopened_by: "", reopen_reason: "" }] };
      const fetchMock = show({
        "GET /api/finance-months/2026-08/": closed,
        "POST /api/finance-months/2026-08/reopen/": (body: unknown) => ({
          body: (body as { preview?: boolean }).preview
            ? { month: "2026-08", label: "August 2026", also: ["September 2026"],
                locked_through_after: "2026-07-31",
                note: "If a later statement showed a mistake in this month, add a "
                  + "correcting entry in the open month instead. Reopen only if the month "
                  + "should not have been closed." }
            : { ...closed, state: "open", reopened: ["2026-08", "2026-09"] } }) });
      await open("August 2026: Closed");
      // Closed, reopened and closed again: all three, with who and why.
      const history = (await screen.findByText("What happened to this month"))
        .nextElementSibling as HTMLElement;
      expect(within(history).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        "Closed by John Carter on September 7, 2026 with a warning showing: 1099 payees "
        + "named (2). Reopened by John Carter on September 9, 2026: Adobe's refund was "
        + "never entered.",
        "Closed by John Carter on September 9, 2026."]);

      await userEvent.click(screen.getByRole("button", { name: "Reopen…" }));
      expect(await screen.findByText(/If a later statement showed a mistake in this month/))
        .toHaveTextContent("add a correcting entry in the open month instead");
      expect(screen.getByText(/also reopens/)).toHaveTextContent(
        "Reopening August 2026 also reopens September 2026. Their reconciliations stay "
        + "finished.");
      expect(screen.getByRole("button", { name: "Reopen August 2026" })).toBeDisabled();
      await userEvent.type(screen.getByLabelText("Why the month is being reopened"),
                           "Closed by mistake.");
      await userEvent.click(screen.getByRole("button", { name: "Reopen August 2026" }));
      await waitFor(() => expect(posts(fetchMock, "2026-08/reopen/")).toEqual([
        { preview: true }, { reason: "Closed by mistake." }]));
    });

  it("names a month locked by a typed date for what it is", async () => {
    show({ "GET /api/finance-months/2026-08/": {
      ...MONTH, month: "2026-08", label: "August 2026", state: "locked_before",
      cannot_close: "" } }, {
      months: [{ ...GRID.months[0], state: "locked_before" }, ...GRID.months.slice(1)] });
    await open("August 2026: Locked before month close began");
    expect(await screen.findByText(/It is locked, not reconciled/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close August 2026" }))
      .not.toBeInTheDocument();
  });
});

describe("walk me through it", () => {
  it("is a switch, remembered by the server for this person", async () => {
    const fetchMock = show({ "POST /api/finance-reconcile/guided/": () => ({
      body: { guided: true } }) });
    const box = await screen.findByLabelText("Walk me through it");
    expect(box).not.toBeChecked();
    expect(screen.queryByRole("list", { name: "The steps" })).not.toBeInTheDocument();
    await userEvent.click(box);
    await waitFor(() => expect(posts(fetchMock, "guided/")).toEqual([{ on: true }]));
  });

  it("shows the eight written steps, one open at a time, and asks Claude nothing",
    async () => {
      const fetchMock = show({}, { guided: true });
      const steps = await screen.findByRole("list", { name: "The steps" });
      expect(within(steps).getAllByRole("listitem").map(
        (li) => within(li).getAllByRole("button")[0].textContent)).toEqual(
        GUIDE_STEPS.map(([title]) => title));
      expect(GUIDE_STEPS).toHaveLength(8);
      expect(within(steps).getByText(GUIDE_STEPS[0][1])).toBeInTheDocument();
      expect(within(steps).queryByText(GUIDE_STEPS[7][1])).not.toBeInTheDocument();
      await userEvent.click(within(steps).getByRole("button", { name: "Close the month" }));
      // The owner's addition: a correcting entry, not reopening.
      expect(within(steps).getByText(GUIDE_STEPS[7][1])).toHaveTextContent(
        "If a later statement shows this month was wrong, do not reopen it. Add a "
        + "correcting entry in the open month that says what it corrects. Your CPA will "
        + "thank you.");
      expect(within(steps).queryByText(GUIDE_STEPS[0][1])).not.toBeInTheDocument();
      // Opening a statement moves to the step it is at.
      await userEvent.click(screen.getByRole(
        "button", { name: "Checking, September 2026: In progress" }));
      expect(await within(steps).findByText(GUIDE_STEPS[2][1])).toBeInTheDocument();
      expect(posts(fetchMock, "explain/")).toEqual([]);
    });

  it("explains a step only when pressed, says the price before and the cost after",
    async () => {
      const fetchMock = show({ "POST /api/finance-reconcile/explain/": () => ({ body: {
        text: "The difference is the flight: tick it.", cost_usd: "0.014300",
        disclaimer: FINANCE_DISCLAIMER, used_today: 4, cap: 20 } }) }, { guided: true });
      await userEvent.click(await screen.findByRole(
        "button", { name: "Checking, September 2026: In progress" }));
      await screen.findByRole("status", { name: "The difference" });
      const steps = screen.getByRole("list", { name: "The steps" });
      await userEvent.click(within(steps).getByRole("button",
                                                    { name: "Get the difference to zero" }));
      const ask = within(steps).getByRole("button",
                                          { name: "Explain this step (about $0.02)" });
      expect(posts(fetchMock, "explain/")).toEqual([]);
      await userEvent.click(ask);
      await waitFor(() => expect(posts(fetchMock, "explain/")).toEqual([
        { step: 5, reconciliation: "r-sep" }]));
      const answer = await within(steps).findByRole("note", { name: "Explanation" });
      expect(answer).toHaveTextContent("The difference is the flight: tick it.");
      expect(answer).toHaveTextContent("This cost $0.0143. 4 of 20 used today.");
      expect(answer).toHaveTextContent(FINANCE_DISCLAIMER);
      // The same step with the same numbers is not asked twice.
      expect(within(steps).getByRole("button", { name: "Explained below" })).toBeDisabled();
      await userEvent.click(within(steps).getByRole("button", { name: "Look at what is left" }));
      await userEvent.click(within(steps).getByRole("button",
                                                    { name: "Get the difference to zero" }));
      expect(within(steps).getByRole("note", { name: "Explanation" }))
        .toHaveTextContent("The difference is the flight: tick it.");
      expect(posts(fetchMock, "explain/")).toHaveLength(1);
    });

  it("says why the button cannot be pressed: no key, or the day's limit", async () => {
    show({ "GET /api/finance-reconcile/explain/": {
      ...PRICE, refused: "No Anthropic API key is set. The practice owner adds one under "
        + "AI usage." } }, { guided: true });
    const steps = await screen.findByRole("list", { name: "The steps" });
    expect(await within(steps).findByText(/No Anthropic API key is set/)).toBeInTheDocument();
    expect(within(steps).queryByRole("button", { name: /Explain this step/ }))
      .not.toBeInTheDocument();
  });
});

describe("the lock leaves the finance settings", () => {
  const ACCOUNTS: FinanceAccount[] = [
    { id: "bank", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4417",
      opening_balance_cents: 1850000, opening_on: "2025-01-01", closed: false,
      reconciled_monthly: true },
    { id: "cash", name: "Petty cash", kind: "cash", kind_label: "Cash", last4: "",
      opening_balance_cents: 20000, opening_on: "2025-01-01", closed: false,
      reconciled_monthly: false }];

  function settings(modules: string[], extra: Record<string, unknown> = {}) {
    const fetchMock = mockApi({
      ...extra, "GET /api/finance-categories/changes/": [],
      "GET /api/me": aMe({ modules }), "GET /api/finance-accounts/": ACCOUNTS,
      "GET /api/finance-rules/": [], "GET /api/finance-categories/": [],
      "GET /api/finance-settings/": { locked_through: "2026-09-30",
                                      invoice_income_category: "" } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<FinanceSettings />);
    return fetchMock;
  }

  it("is not typed by a practice that closes months, which is pointed to Reconcile",
    async () => {
      settings(["bookkeeping"]);
      expect(await screen.findByText(/The lock is set by closing a month/)).toHaveTextContent(
        "The books are locked through September 30, 2026. The lock is set by closing a "
        + "month and moved back by reopening one, under Finance, Reconcile.");
      expect(screen.getByRole("link", { name: "Finance, Reconcile" }))
        .toHaveAttribute("href", "/finance/reconcile");
      expect(screen.queryByLabelText("Lock the books through")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Unlock" })).not.toBeInTheDocument();
    });

  it("stays for a practice without Bookkeeping, which has no other way to lock",
    async () => {
      settings([]);
      expect(await screen.findByLabelText("Lock the books through")).toBeInTheDocument();
      expect(screen.queryByText(/The lock is set by closing a month/))
        .not.toBeInTheDocument();
      expect(screen.queryByLabelText("Reconcile Checking each month"))
        .not.toBeInTheDocument();
    });

  it("keeps the year-end facts the worksheet asks for, per year", async () => {
    const year = new Date().getFullYear();
    const saved = { year, total_miles: 14820, business_miles: null,
                    home_square_feet: 2400, office_square_feet: 180 };
    const fetchMock = settings(["bookkeeping"], {
      "GET /api/finance-settings/year-facts/": { ...saved, total_miles: null },
      "POST /api/finance-settings/year-facts/": () => ({ body: saved }) });
    const home = await screen.findByLabelText("Home square footage");
    await waitFor(() => expect(home).toHaveValue("2400"));
    expect(screen.getByLabelText("Business miles")).toHaveValue("");
    await userEvent.type(screen.getByLabelText("Total miles driven"), "14820");
    const card = home.closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    // A blank is "not said", sent as null and not as zero.
    await waitFor(() => expect(posts(fetchMock, "/year-facts/")).toEqual([
      { year, total_miles: 14820, business_miles: null, home_square_feet: 2400,
        office_square_feet: 180 }]));
    expect(await within(card).findByText(`Saved for ${year}.`)).toBeInTheDocument();
    // Whole numbers only.
    await userEvent.type(screen.getByLabelText("Business miles"), "6,310");
    expect(within(card).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(card).getByText("Whole numbers only.")).toBeInTheDocument();
  });

  it("switches whether an account is reconciled each month", async () => {
    const fetchMock = settings(["bookkeeping"], {
      "PATCH /api/finance-accounts/cash/": () => ({ body: ACCOUNTS[1] }) });
    expect(await screen.findByLabelText("Reconcile Checking each month")).toBeChecked();
    const cash = screen.getByLabelText("Reconcile Petty cash each month");
    expect(cash).not.toBeChecked();
    await userEvent.click(cash);
    await waitFor(() => expect(posts(fetchMock, "/api/finance-accounts/cash/", "PATCH"))
      .toEqual([{ reconciled_monthly: true }]));
  });
});
