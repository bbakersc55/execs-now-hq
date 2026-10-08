import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BankImportBatch, BankImportRow, FinanceAccount, FinanceCategory, FinanceRule, ImportDetected,
  PayeeReport,
} from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";
import { FinanceSettings } from "./FinanceSettings";

/** P5, the second stop — the import, rules and 1099 payees: the screens. */

const ACCOUNTS: FinanceAccount[] = [
  { id: "a1", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4421",
    opening_balance_cents: 1000000, opening_on: "2026-01-01", closed: false },
  { id: "a2", name: "Business card", kind: "card", kind_label: "Credit card", last4: "",
    opening_balance_cents: 0, opening_on: "2026-01-01", closed: false }];
const cat = (id: string, name: string, type: FinanceCategory["type"]): FinanceCategory => ({
  id, name, type, type_label: type, cpa_code: "", position: 0, archived: false, system: false });
const CATEGORIES = [cat("c1", "Client fees", "income"), cat("c2", "Travel", "expense"),
                    cat("c3", "Meals", "expense"), cat("c4", "Owner draw", "owner")];
const PAYEES: PayeeReport = {
  year: 2026, threshold_cents: 200000, default_threshold_cents: 200000, over: 1,
  payees: [
    { contact: "p1", name: "Casey Contractor", company: "", is_payee: true,
      total_cents: 210000, by_card_cents: 0, reportable_cents: 210000, over_threshold: true },
    { contact: "p2", name: "Lee Designer", company: "Studio Lee", is_payee: true,
      total_cents: 300000, by_card_cents: 250000, reportable_cents: 50000,
      over_threshold: false },
    { contact: "p3", name: "Sam Smallwork", company: "", is_payee: false,
      total_cents: 30000, by_card_cents: 0, reportable_cents: 30000, over_threshold: false }] };

const DETECTED: ImportDetected = {
  header: ["Date", "Description", "Amount"], lines: 4, from_saved: false,
  sample: [{ Date: "10/01/2026", Description: "ADOBE", Amount: "-59.99" }],
  mapping: { date: "Date", date_format: "%m/%d/%Y", description: "Description",
             amount: "Amount", sign: "negative_is_out", debit: "", credit: "", balance: "",
             reference: "", bank_id: "" },
  date_formats: [{ value: "%m/%d/%Y", label: "MM/DD/YYYY" },
                 { value: "%Y-%m-%d", label: "YYYY-MM-DD" }] };

function row(more: Partial<BankImportRow>): BankImportRow {
  return { id: "r1", row_number: 2, on_date: "2026-10-01", amount_cents: 5999,
           direction: "out", description: "ADOBE CREATIVE CLOUD", outcome: "new",
           outcome_label: "New entry", category: null, other_account: null, payee_contact: "",
           matched: null, rule: null, error: "", raw: null, ...more };
}
const BATCH: BankImportBatch = {
  id: "b1", account: { id: "a1", name: "Checking" }, filename: "checking.csv",
  status: "dry_run", status_label: "Dry run", created_at: "2026-10-08T12:00:00Z",
  committed_at: null, last_balance_cents: null, last_balance_on: null,
  counts: { new: 2, needs_category: 1, duplicate: 1, invoice_payment: 1, transfer_match: 0,
            transfer: 0, ignore: 0, error: 1, total: 5 },
  rows: [
    row({}),
    row({ id: "r2", row_number: 3, description: "COFFEE BAR", amount_cents: 500,
          category: { id: "c3", name: "Meals" }, rule: { id: "u1", contains: "coffee bar" } }),
    row({ id: "r3", row_number: 4, description: "DEPOSIT ACME", amount_cents: 680000,
          direction: "in", outcome: "invoice_payment",
          matched: { id: "e9", on_date: "2026-10-01", description: "Invoice INV-0007",
                     counterparty: "Acme Facilities", amount_cents: 680000 } }),
    row({ id: "r4", row_number: 5, description: "OLD LINE", outcome: "duplicate" }),
    row({ id: "r5", row_number: 6, on_date: null, amount_cents: null, direction: "",
          description: "", outcome: "error", error: "“soon” is not a date this import reads.",
          raw: { Date: "soon", Description: "BROKEN", Amount: "-1" } })],
};

const posts = (fetchMock: ReturnType<typeof mockApi>, part: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.includes(part));

function show(tab: "import" | "payees", extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/finance-imports/": [], "GET /api/finance-payees/": PAYEES,
    "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-categories/": CATEGORIES,
    ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance tab={tab} />);
  return fetchMock;
}

async function toTheDryRun(extra: Record<string, unknown> = {}) {
  const fetchMock = show("import", {
    "POST /api/finance-imports/detect/": () => ({ body: DETECTED }),
    "POST /api/finance-imports/dry-run/": () => ({ status: 201, body: BATCH }), ...extra });
  await userEvent.selectOptions(await screen.findByLabelText("Account to import into"), "a1");
  await userEvent.upload(screen.getByLabelText("The CSV file"),
                         new File(["Date,Description,Amount\n"], "checking.csv",
                                  { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "Read the file" }));
  await userEvent.click(await screen.findByRole("button", { name: "Show me what would happen" }));
  await screen.findByLabelText("What the import would do");
  return fetchMock;
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("importing a bank or card file", () => {
  it("reads the file, shows the guess at the columns, and lets it be corrected", async () => {
    const fetchMock = show("import", {
      "POST /api/finance-imports/detect/": () => ({ body: DETECTED }) });
    const read = await screen.findByRole("button", { name: "Read the file" });
    expect(read).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Account to import into"), "a2");
    await userEvent.upload(screen.getByLabelText("The CSV file"),
                           new File(["x"], "card.csv", { type: "text/csv" }));
    await userEvent.click(read);
    expect(await screen.findByText(/This is a first guess from the column names/))
      .toBeInTheDocument();
    expect(screen.getByLabelText("Column for: Date")).toHaveValue("Date");
    expect(screen.getByLabelText("Column for: Amount (one column)")).toHaveValue("Amount");
    const sign = screen.getByLabelText("Sign of the amount");
    await userEvent.selectOptions(sign, "positive_is_out");
    expect(sign).toHaveValue("positive_is_out");
    expect(within(screen.getByLabelText("The first lines of the file"))
      .getByText("ADOBE")).toBeInTheDocument();
    expect(posts(fetchMock, "detect/")).toHaveLength(1);
    expect(posts(fetchMock, "dry-run/")).toHaveLength(0);
  });

  it("says a saved mapping is being used", async () => {
    show("import", { "POST /api/finance-imports/detect/":
      () => ({ body: { ...DETECTED, from_saved: true } }) });
    await userEvent.selectOptions(await screen.findByLabelText("Account to import into"), "a1");
    await userEvent.upload(screen.getByLabelText("The CSV file"),
                           new File(["x"], "c.csv", { type: "text/csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Read the file" }));
    expect(await screen.findByText(/Using the columns you chose last time/)).toBeInTheDocument();
  });

  it("shows the dry run: what each line would do, with nothing written yet", async () => {
    await toTheDryRun();
    expect(screen.getByText(/Nothing has been written to the books/)).toBeInTheDocument();
    const summary = screen.getByLabelText("What the import would do");
    expect(summary).toHaveTextContent("2 new entries (1 with no category yet)");
    expect(summary).toHaveTextContent("1 already in the books");
    expect(summary).toHaveTextContent("1 matched to an invoice payment");
    expect(summary).toHaveTextContent("1 that cannot be read");
    // A line a rule decided says which rule.
    expect(screen.getByText("your rule: contains “coffee bar”")).toBeInTheDocument();
    expect(screen.getByLabelText("What is line 3")).toHaveValue("category:c3");
    // A proposed match shows the other side.
    const match = screen.getByText("DEPOSIT ACME").closest("tr") as HTMLElement;
    expect(match).toHaveTextContent("Invoice INV-0007, Acme Facilities, October 1, 2026");
    expect(match).toHaveTextContent("No new entry is made");
    expect(screen.getByText("already in the books")).toBeInTheDocument();
    expect(screen.getByText(/“soon” is not a date/)).toBeInTheDocument();
    expect(screen.getByText("soon · BROKEN · -1")).toBeInTheDocument();
  });

  it("gives a line a category and remembers it when asked", async () => {
    const fetchMock = await toTheDryRun({
      "POST /api/finance-imports/b1/rows/r1/": () => ({ body: BATCH }) });
    await userEvent.click(screen.getByLabelText("Remember for line 2"));
    const text = screen.getByLabelText("Text to remember for line 2");
    expect(text).toHaveValue("ADOBE CREATIVE");
    await userEvent.clear(text);
    await userEvent.type(text, "ADOBE");
    await userEvent.selectOptions(screen.getByLabelText("What is line 2"), "category:c2");
    await waitFor(() => expect(posts(fetchMock, "rows/r1/")).toHaveLength(1));
    expect(posts(fetchMock, "rows/r1/")[0].body).toEqual({
      decision: "entry", category: "c2", payee_contact: null, remember: "ADOBE" });
  });

  it("marks a line as a transfer, an ignore, a payee, or not a match", async () => {
    const fetchMock = await toTheDryRun({
      "POST /api/finance-imports/b1/rows/": () => ({ body: BATCH }) });
    const what = screen.getByLabelText("What is line 2");
    expect(within(what).getByText("Business card")).toBeInTheDocument();
    expect(within(what).queryByText("Checking")).not.toBeInTheDocument();
    await userEvent.selectOptions(what, "transfer:a2");
    await userEvent.selectOptions(what, "ignore");
    await userEvent.selectOptions(screen.getByLabelText("1099 payee for line 2"), "p1");
    await userEvent.click(screen.getByLabelText("Not a match: line 4"));
    await waitFor(() => expect(posts(fetchMock, "rows/")).toHaveLength(4));
    expect(posts(fetchMock, "rows/").map((c) => c.body)).toEqual([
      { decision: "transfer", other_account: "a2" }, { decision: "ignore" },
      { decision: "entry", category: null, payee_contact: "p1" },
      { decision: "not_a_match" }]);
    // Only flagged payees are offered, and only on money going out.
    const payee = screen.getByLabelText("1099 payee for line 2");
    expect(within(payee).queryByText("Sam Smallwork")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("1099 payee for line 4")).not.toBeInTheDocument();
  });

  it("writes to the books only on the third step, and says so when it is refused",
    async () => {
      let refuse = true;
      const fetchMock = await toTheDryRun({
        "POST /api/finance-imports/b1/commit/": () => refuse
          ? { status: 409, body: { detail: "The books have changed since this import was "
              + "shown. Run the dry run again, so what is written is what you saw." } }
          : { body: { ...BATCH, status: "committed", rows: undefined } } });
      const write = screen.getByRole("button", { name: "3. Write 2 entries to the books" });
      await userEvent.click(write);
      expect(await screen.findByText(/Run the dry run again/)).toBeInTheDocument();
      expect(screen.getByLabelText("What the import would do")).toBeInTheDocument();
      refuse = false;
      await userEvent.click(write);
      expect(await screen.findByText("Imported checking.csv into Checking."))
        .toBeInTheDocument();
      expect(posts(fetchMock, "commit/")).toHaveLength(2);
      expect(screen.queryByLabelText("What the import would do")).not.toBeInTheDocument();
    });

  it("lists earlier imports and rolls one back after a confirmation, naming what was kept",
    async () => {
      const done: BankImportBatch = { ...BATCH, status: "committed", rows: undefined,
                                      committed_at: "2026-10-08T12:05:00Z" };
      const confirmed = vi.spyOn(window, "confirm").mockReturnValue(false);
      const fetchMock = show("import", {
        "POST /api/finance-imports/b1/rollback/": () => ({ body: {
          ...done, status: "rolled_back", rolled_back: { removed: 4, unmatched: 1, kept: [
            { on_date: "2026-10-01", amount_cents: 5999, description: "Adobe licence" }] } } }),
        "GET /api/finance-imports/": [done, { ...BATCH, id: "b0" }] });
      const button = await screen.findByRole("button", {
        name: "Roll back the import of checking.csv" });
      // A dry run that was never committed is not an earlier import.
      expect(screen.getAllByText("checking.csv")).toHaveLength(1);
      await userEvent.click(button);
      expect(posts(fetchMock, "rollback/")).toHaveLength(0);
      confirmed.mockReturnValue(true);
      await userEvent.click(button);
      expect(await screen.findByText(/4 entries removed, 1 invoice payments unplaced again/))
        .toBeInTheDocument();
      expect(screen.getByText(/1 you had edited since was kept: Adobe licence \(\$59\.99\)/))
        .toBeInTheDocument();
    });
});

describe("1099 payees", () => {
  it("totals each payee for the year, marks who is over, and sets apart card payments",
    async () => {
      show("payees");
      const table = await screen.findByLabelText("1099 payees for 2026");
      const casey = within(table).getByText("Casey Contractor").closest("tr") as HTMLElement;
      expect(casey).toHaveTextContent("$2,100.00");
      expect(casey).toHaveTextContent("at or over the threshold");
      const lee = within(table).getByText("Lee Designer").closest("tr") as HTMLElement;
      expect(lee).toHaveTextContent("$3,000.00$2,500.00$500.00");
      expect(lee).not.toHaveTextContent("at or over the threshold");
      expect(within(table).getByText("no longer flagged")).toBeInTheDocument();
      expect(screen.getByText("One payee is at or over $2,000.00 for 2026."))
        .toBeInTheDocument();
      expect(screen.getByText(/Confirm the threshold and the card rule with your CPA/))
        .toBeInTheDocument();
      expect(screen.getByText(/\$600 through 2025, \$2,000 from 2026/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Download as CSV" })).toHaveAttribute(
        "href", "/api/finance-payees/export/?year=2026");
    });

  it("flags a contact found by name, and unflags one", async () => {
    const fetchMock = show("payees", {
      "POST /api/finance-payees/": () => ({ body: PAYEES }),
      "GET /api/contacts/search/": { contacts: [
        { id: "p9", first_name: "Robin", last_name: "Newhire" },
        { id: "p1", first_name: "Casey", last_name: "Contractor" }] } });
    await userEvent.type(
      await screen.findByLabelText("Find a contact to flag as a 1099 payee"), "ro");
    await userEvent.click(await screen.findByRole("button", {
      name: "Flag Robin Newhire as a 1099 payee" }));
    // Someone already a payee is not offered again.
    expect(screen.queryByRole("button", { name: "Flag Casey Contractor as a 1099 payee" }))
      .not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", {
      name: "Remove the 1099 flag from Lee Designer" }));
    await waitFor(() => expect(posts(fetchMock, "/api/finance-payees/")).toHaveLength(2));
    expect(posts(fetchMock, "/api/finance-payees/").map((c) => c.body)).toEqual([
      { contact: "p9", is_payee: true }, { contact: "p2", is_payee: false }]);
  });

  it("asks again with another threshold when one is typed", async () => {
    const fetchMock = show("payees");
    const box = await screen.findByLabelText("Threshold");
    await waitFor(() => expect(box).toHaveValue("2000.00"));
    await userEvent.clear(box);
    await userEvent.type(box, "600");
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url === "/api/finance-payees/?year=2026&threshold_cents=60000")).toBe(true));
  });
});

describe("import rules in the settings", () => {
  const RULES: FinanceRule[] = [
    { id: "u1", contains: "coffee bar", treat_as: "category",
      category: { id: "c3", name: "Meals" }, other_account: null, account: null,
      is_active: true },
    { id: "u2", contains: "PAYMENT TO CARD", treat_as: "transfer", category: null,
      other_account: { id: "a2", name: "Business card" },
      account: { id: "a1", name: "Checking" }, is_active: false }];

  it("lists them in plain words, and turns one off or deletes it", async () => {
    const fetchMock = mockApi({
      "PATCH /api/finance-rules/u1/": () => ({ body: RULES[0] }),
      "DELETE /api/finance-rules/u2/": () => ({ status: 204, body: null }),
      "GET /api/finance-rules/": RULES, "GET /api/finance-accounts/": ACCOUNTS,
      "GET /api/finance-categories/": CATEGORIES,
      "GET /api/finance-settings/": { locked_through: null, invoice_income_category: "c1" } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<FinanceSettings />);
    const first = (await screen.findByText("“coffee bar”")).closest("tr") as HTMLElement;
    expect(first).toHaveTextContent("Meals");
    expect(first).toHaveTextContent("any account");
    const second = screen.getByText(/“PAYMENT TO CARD”/).closest("tr") as HTMLElement;
    expect(second).toHaveTextContent("a transfer, Business card");
    expect(second).toHaveTextContent("off");
    expect(screen.getByText(/Nothing here is\s+decided by AI/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", {
      name: "Turn off the rule for coffee bar" }));
    await userEvent.click(screen.getByRole("button", {
      name: "Delete the rule for PAYMENT TO CARD" }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "DELETE"))
      .toHaveLength(1));
    expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      is_active: false });
  });
});
