import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BalanceView, FinanceAccount, FinanceCategory, FinanceEntry, FinanceEntryList, Pnl,
} from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";
import { FinanceSettings } from "./FinanceSettings";

/** P5, the first stop — the books: the practice owner's screens. */

const ACCOUNTS: FinanceAccount[] = [
  { id: "a1", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4421",
    opening_balance_cents: 1000000, opening_on: "2026-01-01", closed: false },
  { id: "a2", name: "Business card", kind: "card", kind_label: "Credit card", last4: "",
    opening_balance_cents: 50000, opening_on: "2026-01-01", closed: false }];
const cat = (id: string, name: string, type: FinanceCategory["type"],
             more: Partial<FinanceCategory> = {}): FinanceCategory => ({
  id, name, type, type_label: type, cpa_code: "", position: 0, archived: false,
  system: false, used: false, ...more });
const CATEGORIES = [cat("c1", "Client fees", "income", { system: true }),
                    cat("c2", "Travel", "expense", { cpa_code: "24a", used: true }),
                    cat("c3", "Meals", "expense"), cat("c4", "Owner draw", "owner"),
                    cat("c5", "Sales tax collected", "held", { system: true }),
                    cat("c6", "Old one", "expense", { archived: true })];

function entry(more: Partial<FinanceEntry> = {}): FinanceEntry {
  return { id: "e1", kind: "expense", kind_label: "Expense", direction: "out",
           on_date: "2026-10-01", amount_cents: 12500,
           category: { id: "c2", name: "Travel" }, account: { id: "a1", name: "Checking" },
           to_account: null, description: "Flight to Denver", counterparty: "United",
           client_company: null, reference: "", source: "manual", source_label: "Typed in",
           invoice: null, removed: false, remove_reason: "", ...more };
}
const LIST: FinanceEntryList = {
  entries: [
    entry(),
    entry({ id: "e2", kind: "income", kind_label: "Income", direction: "in",
            amount_cents: 680000, category: { id: "c1", name: "Client fees" }, account: null,
            description: "Invoice INV-0007", counterparty: "Acme", source: "invoice",
            source_label: "From an invoice payment",
            invoice: { id: "i1", number: "INV-0007" } }),
    entry({ id: "e3", kind: "transfer", kind_label: "Transfer", category: null,
            to_account: { id: "a2", name: "Business card" }, description: "Card payment",
            counterparty: "", amount_cents: 50000 }),
    entry({ id: "e4", category: null, description: "Unknown charge", amount_cents: 999 })],
  count: 4, totals: { income_cents: 680000, expenses_cents: 13499, net_cents: 666501 },
};

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

function show(tab: "entries" | "pnl" | "balance" | "export",
              extra: Record<string, unknown> = {}, route = "/") {
  const fetchMock = mockApi({
    // Before the list's own address, which it begins with.
    "GET /api/finance-entries/bulk/": [],
    ...extra, "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-categories/": CATEGORIES,
    "GET /api/finance-payees/": { year: 2026, threshold_cents: 200000,
                                  default_threshold_cents: 200000, over: 0, payees: [] },
    "GET /api/finance-entries/": LIST,
    // Again, so a test's own answer replaces the one above and keeps its place.
    ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance tab={tab} />, { route });
  return fetchMock;
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("the entries", () => {
  it("lists what happened, with what still needs attention marked", async () => {
    show("entries");
    const totals = await screen.findByLabelText("Totals for what is listed");
    expect(totals).toHaveTextContent("Income $6,800.00 · expenses $134.99 · net $6,665.01");
    const flight = screen.getByText("Flight to Denver").closest("tr") as HTMLElement;
    expect(flight).toHaveTextContent("−$125.00");
    expect(flight).toHaveTextContent("Travel");
    // A payment on an invoice: linked, not yet placed, and not removable here.
    const paid = screen.getByRole("link", { name: "invoice INV-0007" }).closest("tr") as HTMLElement;
    expect(paid).toHaveTextContent("not placed yet");
    expect(within(paid).queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
    expect(screen.getByText("no category yet")).toBeInTheDocument();
    const move = screen.getByText("Card payment").closest("tr") as HTMLElement;
    expect(move).toHaveTextContent("Checking → Business card");
    // A transfer can be chosen: it cannot change category, and can be removed.
    expect(within(move).getByRole("checkbox")).toBeInTheDocument();
  });

  it("adds an expense in cents, to an account, with only fitting categories offered",
    async () => {
      const fetchMock = show("entries", {
        "POST /api/finance-entries/": () => ({ status: 201, body: entry() }) });
      const add = await screen.findByRole("button", { name: "Add the entry" });
      expect(add).toBeDisabled();
      const category = screen.getByLabelText("Category of the new entry");
      await waitFor(() => expect(within(category).getByText("Travel")).toBeInTheDocument());
      expect(within(category).queryByText("Client fees")).not.toBeInTheDocument();
      expect(within(category).queryByText("Old one")).not.toBeInTheDocument();
      await userEvent.type(screen.getByLabelText("Amount of the new entry"), "45.50");
      await userEvent.selectOptions(category, "c3");
      await userEvent.selectOptions(screen.getByLabelText("Account of the new entry"), "a2");
      await userEvent.type(screen.getByLabelText("Description of the new entry"), "Lunch");
      await userEvent.click(add);
      await waitFor(() => expect(sent(fetchMock, "/api/finance-entries/")).toHaveLength(1));
      expect(sent(fetchMock, "/api/finance-entries/")[0]).toMatchObject({
        kind: "expense", amount_cents: 4550, category: "c3", account: "a2",
        to_account: null, description: "Lunch" });
    });

  it("asks for two accounts and no category for a transfer", async () => {
    const fetchMock = show("entries", {
      "POST /api/finance-entries/": () => ({ status: 201, body: entry() }) });
    await userEvent.selectOptions(
      await screen.findByLabelText("Kind of the new entry"), "transfer");
    expect(screen.queryByLabelText("Category of the new entry")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Amount of the new entry"), "500");
    await userEvent.selectOptions(screen.getByLabelText("Account of the new entry"), "a1");
    const to = screen.getByLabelText("Account the new entry goes to");
    expect(within(to).queryByText("Checking")).not.toBeInTheDocument();
    await userEvent.selectOptions(to, "a2");
    await userEvent.click(screen.getByRole("button", { name: "Add the entry" }));
    await waitFor(() => expect(sent(fetchMock, "/api/finance-entries/")[0]).toMatchObject({
      kind: "transfer", amount_cents: 50000, category: null, account: "a1",
      to_account: "a2" }));
  });

  it("keeps a refused entry in the form, with the reason", async () => {
    show("entries", { "POST /api/finance-entries/": () => ({ status: 409, body: {
      detail: "The books are locked through September 30, 2026." } }) });
    await userEvent.type(await screen.findByLabelText("Amount of the new entry"), "10");
    await userEvent.selectOptions(screen.getByLabelText("Account of the new entry"), "a1");
    await userEvent.click(screen.getByRole("button", { name: "Add the entry" }));
    expect(await screen.findByText(/locked through September 30, 2026/)).toBeInTheDocument();
    expect(screen.getByLabelText("Amount of the new entry")).toHaveValue("10");
  });

  it("lets an invoice payment be placed and renamed, and nothing else", async () => {
    const fetchMock = show("entries", {
      "PATCH /api/finance-entries/e2/": () => ({ body: entry() }) });
    await userEvent.click(await screen.findByRole("button", {
      name: "Edit the entry of October 1, 2026, $6,800.00" }));
    expect(await screen.findByText(/Its amount and date are\s+changed on the invoice/))
      .toBeInTheDocument();
    expect(screen.queryByLabelText("Amount of this entry")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Date of this entry")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Account of this entry"), "a1");
    await userEvent.click(screen.getByRole("button", { name: "Save the entry" }));
    await waitFor(() => expect(sent(fetchMock, "/api/finance-entries/e2/")).toEqual([
      { category: "c1", account: "a1", description: "Invoice INV-0007" }]));
  });

  it("removes an entry only with a reason", async () => {
    const fetchMock = show("entries", {
      "POST /api/finance-entries/e1/remove/": () => ({ body: entry({ removed: true }) }) });
    const ask = vi.spyOn(window, "prompt").mockReturnValue("");
    const remove = await screen.findByRole("button", {
      name: "Remove the entry of October 1, 2026, $125.00" });
    await userEvent.click(remove);
    expect(sent(fetchMock, "remove/")).toEqual([]);
    ask.mockReturnValue("Entered twice");
    await userEvent.click(remove);
    await waitFor(() => expect(sent(fetchMock, "remove/")).toEqual([
      { reason: "Entered twice" }]));
  });

  const PLAN = { action: "recategorize", chosen: 4, count: 2, to: "Meals",
                 first_on: "2026-10-01", last_on: "2026-10-01",
                 left_out: [{ why: "transfer", label: "a transfer, which has no category",
                              count: 1 },
                            { why: "type", label: "of a kind that category cannot take",
                              count: 1 }] };
  const bulkBodies = (fetchMock: ReturnType<typeof mockApi>) =>
    fetchMock.calls.filter((c) => c.method === "POST" && c.url.endsWith("/bulk/"))
      .map((c) => c.body);

  it("selects all that the filter shows, and clears the selection", async () => {
    show("entries");
    const all = await screen.findByRole("button", { name: "Select all 4 shown" });
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
    await userEvent.click(all);
    const bar = screen.getByRole("group", { name: "The selection" });
    expect(bar).toHaveTextContent("4 chosen");
    expect(all).toBeDisabled();
    // Every row is chosen, the transfer too: it can be removed, if not moved.
    for (const box of screen.getAllByRole("checkbox", { name: /^Choose the entry of/ })) {
      expect(box).toBeChecked();
    }
    expect(screen.getAllByRole("checkbox", { name: /^Choose the entry of/ })).toHaveLength(4);
    await userEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
    expect(within(bar).queryByText("4 chosen")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select all 4 shown" })).toBeEnabled();
  });

  it("changes the category of the selection, showing the count before it acts",
    async () => {
      const fetchMock = show("entries", {
        "POST /api/finance-entries/bulk/": () => ({ body: PLAN }) });
      await userEvent.click(await screen.findByRole("button", { name: "Select all 4 shown" }));
      const change = screen.getByRole("button", { name: "Change category" });
      expect(change).toBeDisabled();
      await userEvent.selectOptions(
        screen.getByLabelText("Category for the chosen entries"), "c3");
      await userEvent.click(change);
      const body = { action: "recategorize", entries: ["e1", "e2", "e3", "e4"],
                     category: "c3" };
      // Counted, and nothing moved yet.
      const before = await screen.findByRole("group", { name: "Before it acts" });
      expect(within(before).getByRole("status")).toHaveTextContent(
        "2 of 4 entries will move to Meals, dated October 1, 2026. Left as they are: 1 a "
        + "transfer, which has no category; 1 of a kind that category cannot take.");
      expect(bulkBodies(fetchMock)).toEqual([{ ...body, preview: true }]);
      await userEvent.click(within(before).getByRole("button", { name: "Move 2 to Meals" }));
      await waitFor(() => expect(bulkBodies(fetchMock)).toEqual([
        { ...body, preview: true }, body]));
      await waitFor(() => expect(screen.queryByRole("group", { name: "Before it acts" }))
        .not.toBeInTheDocument());
    });

  it("deletes the selection only after the count, and only with a reason", async () => {
    const plan = { ...PLAN, action: "remove", count: 1, to: "", chosen: 2,
                   left_out: [{ why: "locked", label: "in a closed or locked month",
                                count: 1 }] };
    const fetchMock = show("entries", {
      "POST /api/finance-entries/bulk/": () => ({ body: plan }) });
    await userEvent.click(await screen.findByLabelText(
      "Choose the entry of October 1, 2026, $125.00"));
    await userEvent.click(screen.getByLabelText("Choose the entry of October 1, 2026, $9.99"));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const before = await screen.findByRole("group", { name: "Before it acts" });
    expect(within(before).getByRole("status")).toHaveTextContent(
      "1 of 2 entries will be removed, dated October 1, 2026. Left as they are: 1 in a "
      + "closed or locked month. A removed entry is kept in the history and leaves every "
      + "figure.");
    const remove = within(before).getByRole("button", { name: "Remove 1" });
    expect(remove).toBeDisabled();
    await userEvent.type(within(before).getByLabelText("Why the entries are being removed"),
                         "Entered twice");
    await userEvent.click(remove);
    const body = { action: "remove", entries: ["e1", "e4"] };
    await waitFor(() => expect(bulkBodies(fetchMock)).toEqual([
      { ...body, preview: true }, { ...body, reason: "Entered twice" }]));
  });

  it("acts on nothing when the count is zero, and forgets the count if the choice changes",
    async () => {
      show("entries", { "POST /api/finance-entries/bulk/": () => ({
        body: { ...PLAN, action: "remove", count: 0, chosen: 1, to: "", first_on: null,
                last_on: null, left_out: [{ why: "invoice", count: 1,
                                            label: "an invoice payment, removed on its invoice" }] } }) });
      await userEvent.click(await screen.findByLabelText(
        "Choose the entry of October 1, 2026, $6,800.00"));
      await userEvent.click(screen.getByRole("button", { name: "Delete" }));
      const before = await screen.findByRole("group", { name: "Before it acts" });
      expect(within(before).getByRole("status")).toHaveTextContent(
        "0 of 1 entry will be removed. Left as they are: 1 an invoice payment, removed on "
        + "its invoice.");
      expect(within(before).getByRole("button", { name: "Remove 0" })).toBeDisabled();
      await userEvent.click(screen.getByLabelText(
        "Choose the entry of October 1, 2026, $125.00"));
      expect(screen.queryByRole("group", { name: "Before it acts" })).not.toBeInTheDocument();
    });

  it("lists the bulk changes made, as combines are listed", async () => {
    show("entries", { "GET /api/finance-entries/bulk/": [
      { id: "b1", at: "2026-10-10T15:00:00Z", action: "recategorize", count: 14,
        to: "Meals", first_on: "2026-01-04", last_on: "2026-09-28", reason: "",
        by: "John Carter" },
      { id: "b2", at: "2026-10-09T15:00:00Z", action: "remove", count: 2, to: "",
        first_on: "2026-10-01", last_on: "2026-10-02", reason: "Entered twice",
        by: "John Carter" }] });
    await userEvent.click(await screen.findByText("Changed several at once: 2"));
    const rows = within(screen.getByRole("table", { name: "Changed several at once" }))
      .getAllByRole("row").slice(1).map((row) => row.textContent);
    expect(rows).toEqual([
      "October 10, 2026Moved to Meals14, January 4, 2026 to September 28, 2026John Carter",
      "October 9, 2026Removed: Entered twice2, October 1, 2026 to October 2, 2026John Carter"]);
  });

  it("filters from the address, as a figure on the P&L links to it", async () => {
    const fetchMock = show("entries", {}, "/?category=c2&from=2026-10-01&to=2026-10-31");
    await screen.findByLabelText("Totals for what is listed");
    expect(fetchMock.calls.some((c) => c.url
      === "/api/finance-entries/?from=2026-10-01&to=2026-10-31&category=c2")).toBe(true);
    expect(screen.getByLabelText("From")).toHaveValue("2026-10-01");
  });

  it("asks for an account before anything else when there is none", async () => {
    const fetchMock = mockApi({ "GET /api/finance-payees/": { payees: [] },
                                "GET /api/finance-accounts/": [],
                                "GET /api/finance-categories/": CATEGORIES,
                                "GET /api/finance-entries/": { ...LIST, entries: [], count: 0 } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Finance tab="entries" />);
    expect(await screen.findByText(/Add the bank account or card your money moves through/))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add the entry" })).not.toBeInTheDocument();
    expect(screen.getByText("No entries yet.")).toBeInTheDocument();
  });
});

describe("the profit and loss", () => {
  const PNL: Pnl = {
    year: 2026, by: "quarter", periods: ["Q1", "Q2", "Q3", "Q4"],
    income: { rows: [{ id: "c1", name: "Client fees", cpa_code: "", total: 2050000,
                       amounts: [1250000, 0, 800000, 0] }],
              totals: [1250000, 0, 800000, 0], total: 2050000 },
    expenses: { rows: [{ id: "c2", name: "Travel", cpa_code: "24a", total: 12500,
                         amounts: [12500, 0, 0, 0] }],
                totals: [12500, 0, 0, 0], total: 12500 },
    net: [1237500, 0, 800000, 0], net_total: 2037500,
    uncategorized: { count: 2, amount_cents: 236044 }, years: [2026, 2025] };

  it("shows income, expenses and net, and says what is left out", async () => {
    show("pnl", { "GET /api/finance-reports/pnl/": PNL }, "/?by=quarter");
    expect(await screen.findByText("Profit and loss, 2026")).toBeInTheDocument();
    expect(screen.getByLabelText("Net")).toHaveTextContent("$12,375.00");
    expect(screen.getByLabelText("Net")).toHaveTextContent("$20,375.00");
    expect(screen.getByText(/2 entries, \$2,360.44, have\s+no category and are not in these/))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Give them one" })).toHaveAttribute(
      "href", "/finance?category=none");
    expect(screen.getByText(/Transfers, your own money in or out and\s+tax held/))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download as CSV" })).toHaveAttribute(
      "href", "/api/finance-reports/pnl/?year=2026&by=quarter&download=1");
  });

  it("opens the entries behind a figure: that category, in that quarter", async () => {
    show("pnl", { "GET /api/finance-reports/pnl/": PNL }, "/?by=quarter");
    expect(await screen.findByRole("link", { name: "Client fees, Q3: $8,000.00" }))
      .toHaveAttribute("href", "/finance?category=c1&from=2026-07-01&to=2026-09-30");
    expect(screen.getByRole("link", { name: "Travel, Q1: $125.00" }))
      .toHaveAttribute("href", "/finance?category=c2&from=2026-01-01&to=2026-03-31");
  });

  it("asks for another year or the months", async () => {
    const fetchMock = show("pnl", { "GET /api/finance-reports/pnl/": PNL });
    await userEvent.selectOptions(await screen.findByLabelText("Year"), "2025");
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url === "/api/finance-reports/pnl/?year=2025&by=month")).toBe(true));
  });
});

describe("the balance view", () => {
  const VIEW: BalanceView = {
    as_of: "2026-10-08",
    cash: [{ id: "a1", name: "Checking", kind: "bank", last4: "4421",
             amount_cents: 1207500, closed: false }],
    unplaced_cents: 200000, unplaced_count: 1, cash_total_cents: 1407500,
    cards: [{ id: "a2", name: "Business card", kind: "card", last4: "", amount_cents: 54500,
              closed: false }],
    tax_held_cents: 33333, owed_total_cents: 87833, net_cents: 1319667,
    owed_to_you_cents: 480000 };

  it("adds up cash less what is owed, and says what it is not", async () => {
    show("balance", { "GET /api/finance-reports/balance/": VIEW });
    const table = await screen.findByLabelText("Balance view");
    expect(table).toHaveTextContent("Checking ·· 4421$12,075.00");
    expect(table).toHaveTextContent("not yet placed in an account (1)$2,000.00");
    expect(table).toHaveTextContent("Cash$14,075.00");
    expect(table).toHaveTextContent("Business card, owed$545.00");
    expect(table).toHaveTextContent("Sales tax collected, not yet paid over$333.33");
    expect(table).toHaveTextContent("Net$13,196.67");
    expect(screen.getByText(/It is not a balance\s+sheet/)).toBeInTheDocument();
    expect(screen.getByText(/Beside it, not in it/)).toHaveTextContent("$4,800.00");
  });
});

describe("the CPA's worksheet and an estimated tax payment", () => {
  it("downloads the worksheet for a year", async () => {
    show("export");
    const year = new Date().getFullYear();
    const link = await screen.findByRole("link", { name: "Download the worksheet" });
    expect(link).toHaveAttribute("href", `/api/finance-reports/export-worksheet/?year=${year}`);
    await userEvent.selectOptions(screen.getByLabelText("Worksheet year"), String(year - 1));
    expect(link).toHaveAttribute(
      "href", `/api/finance-reports/export-worksheet/?year=${year - 1}`);
    expect(screen.getByText(/laid out as the Business Income & Expense\s+Worksheet/))
      .toHaveTextContent("your estimated tax payments by date, federal and state");
  });

  it("marks an owner draw as an estimated tax payment, federal or state", async () => {
    const fetchMock = show("entries", {
      "POST /api/finance-entries/": () => ({ status: 201, body: entry() }) });
    await screen.findByLabelText("Totals for what is listed");
    // Not offered on an expense: it is the owner's own money going out.
    expect(screen.queryByLabelText("Estimated tax payment, for the new entry"))
      .not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Kind of the new entry"), "owner");
    const mark = screen.getByLabelText("Estimated tax payment, for the new entry");
    expect(within(mark).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["No", "Federal", "State"]);
    await userEvent.selectOptions(mark, "federal");
    await userEvent.type(screen.getByLabelText("Amount of the new entry"), "4500");
    await userEvent.selectOptions(screen.getByLabelText("Category of the new entry"), "c4");
    await userEvent.selectOptions(screen.getByLabelText("Account of the new entry"), "a1");
    await userEvent.click(screen.getByRole("button", { name: "Add the entry" }));
    await waitFor(() => expect(sent(fetchMock, "/api/finance-entries/")).toHaveLength(1));
    expect(sent(fetchMock, "/api/finance-entries/")[0]).toMatchObject({
      kind: "owner", direction: "out", amount_cents: 450000, estimated_tax: "federal" });
    // Money coming in from the owner is not one, so the mark goes with the choice.
    await userEvent.selectOptions(screen.getByLabelText("Kind of the new entry"), "owner");
    await userEvent.selectOptions(screen.getByLabelText("Direction of the new entry"), "in");
    expect(screen.queryByLabelText("Estimated tax payment, for the new entry"))
      .not.toBeInTheDocument();
  });

  it("shows the mark as a chip on the entry, and filters the owner draws on it",
    async () => {
      const fetchMock = show("entries", { "GET /api/finance-entries/": { ...LIST, entries: [
        entry({ id: "e9", kind: "owner", kind_label: "Owner", amount_cents: 450000,
                category: { id: "c4", name: "Owner draw" }, description: "Q2 estimate",
                estimated_tax: "federal" }),
        entry({ id: "e10", kind: "owner", kind_label: "Owner", amount_cents: 80000,
                category: { id: "c4", name: "Owner draw" }, description: "Q2 state",
                estimated_tax: "state" })], count: 2 } }, "/?kind=owner");
      const row = (await screen.findByText(/Q2 estimate/)).closest("tr") as HTMLElement;
      expect(within(row).getByText("Estimated tax: Federal")).toHaveClass("pill");
      expect(within(screen.getByText(/Q2 state/).closest("tr") as HTMLElement)
        .getByText("Estimated tax: State")).toHaveClass("pill");
      // Among the owner's entries, the filter is offered; it asks the server.
      const filter = screen.getByLabelText("Estimated tax payments");
      expect(within(filter).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "Every owner entry", "Estimated tax payments", "Estimated tax, federal",
        "Estimated tax, state"]);
      await userEvent.selectOptions(filter, "federal");
      await waitFor(() => expect(fetchMock.calls.some((c) => c.url
        === "/api/finance-entries/?kind=owner&estimated_tax=federal")).toBe(true));
    });

  it("does not offer the estimated tax filter among other kinds of entry", async () => {
    show("entries");
    await screen.findByLabelText("Totals for what is listed");
    expect(screen.queryByLabelText("Estimated tax payments")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "owner");
    expect(await screen.findByLabelText("Estimated tax payments")).toBeInTheDocument();
  });
});

describe("the CPA export", () => {
  it("offers the two files for the dates chosen, and refuses them the wrong way round",
    async () => {
      show("export");
      const from = await screen.findByLabelText("Export from");
      await userEvent.clear(from);
      await userEvent.type(from, "2026-01-01");
      const to = screen.getByLabelText("Export to");
      await userEvent.clear(to);
      await userEvent.type(to, "2026-06-30");
      expect(screen.getByRole("link", { name: "Download the entries" })).toHaveAttribute(
        "href", "/api/finance-reports/export-entries/?from=2026-01-01&to=2026-06-30");
      expect(screen.getByRole("link", { name: "Download the summary by category" }))
        .toHaveAttribute("href",
                         "/api/finance-reports/export-summary/?from=2026-01-01&to=2026-06-30");
      await userEvent.clear(to);
      await userEvent.type(to, "2025-12-31");
      expect(await screen.findByText("The last date cannot be before the first."))
        .toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Download the entries" }))
        .not.toBeInTheDocument();
    });
});

describe("accounts, categories and the lock", () => {
  function showSettings(extra: Record<string, unknown> = {}, locked: string | null = null) {
    const fetchMock = mockApi({
      // A practice without the Bookkeeping module: it still types its lock
      // here. One with it closes months instead (FinanceReconcile.test.tsx).
      ...extra, "GET /api/me": aMe({ modules: [] }),
      "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-rules/": [],
      "GET /api/finance-categories/": CATEGORIES,
      "GET /api/finance-settings/": { locked_through: locked, invoice_income_category: "c1" },
      // Again, so a test's own answer replaces the one above.
      ...extra });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<FinanceSettings />);
    return fetchMock;
  }

  it("adds an account with its opening balance in cents", async () => {
    const fetchMock = showSettings({
      "POST /api/finance-accounts/": () => ({ status: 201, body: ACCOUNTS[0] }) });
    await userEvent.type(await screen.findByLabelText("Name of the new account"), "Savings");
    await userEvent.type(screen.getByLabelText("Opening balance of the new account"), "2,500");
    await userEvent.click(screen.getByRole("button", { name: "Add the account" }));
    await waitFor(() => expect(sent(fetchMock, "/api/finance-accounts/")).toHaveLength(1));
    expect(sent(fetchMock, "/api/finance-accounts/")[0]).toMatchObject({
      name: "Savings", kind: "bank", opening_balance_cents: 250000 });
    expect(screen.getByText("Checking").closest("tr")).toHaveTextContent("$10,000.00");
  });

  it("renames a category and sets its CPA code, and archives rather than deletes",
    async () => {
      const fetchMock = showSettings({
        "PATCH /api/finance-categories/c3/": () => ({ body: CATEGORIES[2] }) });
      const name = await screen.findByLabelText("Name of Meals");
      await userEvent.clear(name);
      await userEvent.type(name, "Meals and entertainment");
      await userEvent.type(screen.getByLabelText("CPA code of Meals"), "24b");
      await userEvent.click(screen.getByRole("button", { name: "Save Meals" }));
      await waitFor(() => expect(sent(fetchMock, "/api/finance-categories/c3/")).toEqual([
        { name: "Meals and entertainment", cpa_code: "24b" }]));
      expect(screen.queryByRole("button", { name: /^Delete/ })).not.toBeInTheDocument();
      // The category paid invoices go to, and the one tax is held in, stay.
      expect(screen.getByText("paid invoices go here")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Archive Client fees" }))
        .not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Archive Sales tax collected" }))
        .not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Restore Old one" })).toBeInTheDocument();
    });

  it("sets the practice's payment terms under Paid invoices", async () => {
    // Owner, 2026-10-14: due on receipt, net 15, net 30, or a number of days.
    const settings = { prefix: "INV-", next_value: 1, next_number: "INV-0001",
                       terms_days: 15, terms_label: "Net 15", default_notes: "",
                       default_terms: "", pay_instructions: "", email_subject: "",
                       email_body: "", merge_fields: [] };
    const fetchMock = showSettings({
      "POST /api/invoice-settings/": (body: unknown) => ({
        body: { ...settings, ...(body as object) } }),
      "GET /api/invoice-settings/": settings });
    const terms = await screen.findByLabelText("The practice's payment terms");
    expect(terms).toHaveValue("15");
    expect(screen.getByText(/Changing this changes no invoice\s+already written/))
      .toBeInTheDocument();
    await userEvent.selectOptions(terms, "0");
    await waitFor(() => expect(terms).toHaveValue("0"));
    await userEvent.selectOptions(terms, "other");
    const days = await screen.findByLabelText("The practice's payment terms, in days");
    // Kept as typed until the box is left: emptying it on the way to another
    // number is not "due on receipt", and nothing is saved once a digit.
    await userEvent.clear(days);
    await userEvent.type(days, "60");
    await userEvent.tab();
    await waitFor(() => expect(sent(fetchMock, "/api/invoice-settings/")).toEqual([
      { terms_days: 0 }, { terms_days: 45 }, { terms_days: 60 }]));
    // Nonsense goes back to what it was, and sends nothing.
    await userEvent.clear(days);
    await userEvent.type(days, "900");
    await userEvent.tab();
    expect(days).toHaveValue(60);
    expect(sent(fetchMock, "/api/invoice-settings/")).toHaveLength(3);
  });

  it("sends each kind of paid invoice to its own income category", async () => {
    const fetchMock = showSettings({
      "POST /api/finance-settings/": () => ({ body: {} }),
      "GET /api/finance-settings/": {
        locked_through: null, invoice_income_category: "c1",
        recurring_income_category: "c1", one_off_income_category: "" } });
    const recurring = await screen.findByLabelText("Category for recurring invoices");
    const oneOff = screen.getByLabelText("Category for one-off invoices");
    await waitFor(() => expect(recurring).toHaveValue("c1"));
    // "" is a choice: that kind goes where anything else does.
    expect(oneOff).toHaveValue("");
    expect(within(oneOff).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["As anything else", "Client fees"]);
    expect(screen.getByLabelText("Category for paid invoices")).toHaveValue("c1");
    await userEvent.selectOptions(oneOff, "c1");
    await userEvent.selectOptions(recurring, "");
    await waitFor(() => expect(sent(fetchMock, "/api/finance-settings/")).toEqual([
      { one_off_income_category: "c1" }, { recurring_income_category: "" }]));
  });

  it("locks the books through a date, and unlocks only after a confirmation", async () => {
    const fetchMock = showSettings({
      "POST /api/finance-settings/": () => ({ body: { locked_through: "2026-09-30",
                                                      invoice_income_category: "c1" } }) });
    expect(await screen.findByText("The books are not locked.")).toBeInTheDocument();
    const date = screen.getByLabelText("Lock the books through");
    await userEvent.type(date, "2026-09-30");
    await userEvent.click(screen.getByRole("button", { name: "Lock through this date" }));
    await waitFor(() => expect(sent(fetchMock, "/api/finance-settings/")).toEqual([
      { locked_through: "2026-09-30" }]));
  });

  it("says through when the books are locked", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = showSettings({}, "2026-09-30");
    expect(await screen.findByText("September 30, 2026")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(confirmed).toHaveBeenCalled();
    expect(sent(fetchMock, "/api/finance-settings/")).toEqual([]);
  });
});
