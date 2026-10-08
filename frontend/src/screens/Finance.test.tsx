import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BalanceView, FinanceAccount, FinanceCategory, FinanceEntry, FinanceEntryList, Pnl,
} from "../lib/api";
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
    ...extra, "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-categories/": CATEGORIES,
    "GET /api/finance-payees/": { year: 2026, threshold_cents: 200000,
                                  default_threshold_cents: 200000, over: 0, payees: [] },
    "GET /api/finance-entries/": LIST });
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
    expect(within(move).queryByRole("checkbox")).not.toBeInTheDocument();
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

  it("changes the category of several at once", async () => {
    const fetchMock = show("entries", {
      "POST /api/finance-entries/recategorize/": () => ({ body: { changed: 2 } }) });
    await userEvent.click(await screen.findByLabelText(
      "Choose the entry of October 1, 2026, $125.00"));
    await userEvent.click(screen.getByLabelText("Choose the entry of October 1, 2026, $9.99"));
    await userEvent.selectOptions(
      screen.getByLabelText("Category for the chosen entries"), "c3");
    await userEvent.click(screen.getByRole("button", { name: "Change the category" }));
    await waitFor(() => expect(sent(fetchMock, "recategorize/")).toEqual([
      { entries: ["e1", "e4"], category: "c3" }]));
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
      ...extra, "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-rules/": [],
      "GET /api/finance-categories/": CATEGORIES,
      "GET /api/finance-settings/": { locked_through: locked, invoice_income_category: "c1" } });
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
