import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BankImportBatch, BankImportRow, FinanceAccount, FinanceCategory, FinanceRule, ImportDetected,
  PayeeReport,
} from "../lib/api";
import { aMe } from "../test/fixtures";
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
  await userEvent.upload(screen.getByLabelText("The file from your bank"),
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
    await userEvent.upload(screen.getByLabelText("The file from your bank"),
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

  it("takes a bank's own OFX, QFX or QBO file, with no columns to choose", async () => {
    // Owner, 2026-10-14. The format says which value is which.
    const fetchMock = show("import", {
      "POST /api/finance-imports/dry-run/": () => ({ status: 201, body: BATCH }),
      "POST /api/finance-imports/detect/": () => ({ body: {
        ...DETECTED, kind: "ofx", fixed: true,
        header: ["Date", "Description", "Amount", "Transaction ID", "Check number"],
        sample: [{ Date: "2026-10-01", Description: "ADOBE", Amount: "-59.99",
                   "Transaction ID": "2026100101", "Check number": "" }] } }) });
    const file = await screen.findByLabelText("The file from your bank");
    for (const kind of [".csv", ".ofx", ".qfx", ".qbo"]) {
      expect(file.getAttribute("accept")).toContain(kind);
    }
    expect(screen.getByText(/a CSV, or the bank's own OFX, QFX \(Quicken\) or QBO/))
      .toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Account to import into"), "a1");
    await userEvent.upload(file, new File(["<OFX>"], "export.qfx", { type: "" }),
                           { applyAccept: false });
    await userEvent.click(screen.getByRole("button", { name: "Read the file" }));
    expect(await screen.findByText(/your bank's own file format, which says which value is/))
      .toBeInTheDocument();
    expect(screen.queryByLabelText("Column for: Date")).toBeNull();
    expect(screen.queryByLabelText("Sign of the amount")).toBeNull();
    expect(within(screen.getByLabelText("The first lines of the file"))
      .getByText("2026100101")).toBeInTheDocument();
    // The dry run is the next step, as for a CSV.
    await userEvent.click(screen.getByRole("button", { name: "Show me what would happen" }));
    await waitFor(() => expect(posts(fetchMock, "dry-run/")).toHaveLength(1));
  });

  describe("a PDF statement", () => {
    // Owner, 2026-10-14. Claude reads it; priced before, costed after.
    const PDF = { ...DETECTED, kind: "pdf" as const, fixed: true, header: [], sample: [],
                  lines: 0, pages: 3, estimate_usd: "0.1730", refused: "" };
    const FACTS = { pdf: "/api/finance-imports/b1/statement/", period_start: "2026-10-01",
                    period_end: "2026-10-31", opening_balance_cents: 1000000,
                    closing_balance_cents: 1623501, cost_usd: "0.164200",
                    adds_up: { in_cents: 680000, out_cents: 56499, expected_cents: 1623501,
                               difference_cents: 0 } };

    async function choose(detected: object, batch: object = { ...BATCH, source: "pdf",
                                                              statement: FACTS }) {
      const fetchMock = show("import", {
        "POST /api/finance-imports/dry-run/": () => ({ status: 201, body: batch }),
        "POST /api/finance-imports/detect/": () => ({ body: detected }) });
      const file = await screen.findByLabelText("The file from your bank");
      expect(file.getAttribute("accept")).toContain(".pdf");
      await userEvent.selectOptions(screen.getByLabelText("Account to import into"), "a1");
      await userEvent.upload(file, new File(["%PDF"], "october.pdf",
                                            { type: "application/pdf" }));
      await userEvent.click(screen.getByRole("button", { name: "Read the file" }));
      return fetchMock;
    }

    it("says how long it is and about what it costs before Claude reads it", async () => {
      const fetchMock = await choose(PDF);
      const card = await screen.findByRole("group", { name: "The PDF statement" });
      expect(card).toHaveTextContent("A PDF statement, 3 pages.");
      expect(card).toHaveTextContent("for about $0.17 of your AI budget");
      expect(card).toHaveTextContent("never the account number, a name or an address");
      expect(card).toHaveTextContent("sent to Anthropic as it is");
      // No columns to choose, and nothing read until the button is pressed.
      expect(screen.queryByLabelText("Column for: Date")).toBeNull();
      expect(posts(fetchMock, "dry-run/")).toHaveLength(0);
      await userEvent.click(within(card).getByRole("button", {
        name: "Read it with Claude, about $0.17" }));
      await waitFor(() => expect(posts(fetchMock, "dry-run/")).toHaveLength(1));

      // The ordinary dry run, with what was read set against itself.
      const read = await screen.findByRole("group", {
        name: "What was read from the statement" });
      expect(read).toHaveTextContent("Read from the PDF by Claude for $0.1642.");
      expect(read).toHaveTextContent(
        "The statement runs October 1, 2026 to October 31, 2026.");
      expect(read).toHaveTextContent(
        "Beginning balance $10,000.00. Ending balance $16,235.01.");
      expect(read).toHaveTextContent(
        "The lines read add up to the statement's ending balance.");
      expect(within(read).getByRole("link", { name: "Open the statement" }))
        .toHaveAttribute("href", "/api/finance-imports/b1/statement/");
      expect(screen.getByText("Nothing has been written to the books. This is the dry run."))
        .toBeInTheDocument();
    });

    it("says by how much the lines miss the ending balance, before anything is written",
      async () => {
        await choose(PDF, { ...BATCH, source: "pdf", statement: { ...FACTS, adds_up: {
          in_cents: 680000, out_cents: 56499, expected_cents: 1623501,
          difference_cents: -23501 } } });
        await userEvent.click(await screen.findByRole("button", {
          name: /Read it with Claude/ }));
        expect(await screen.findByText(
          /The lines read come to \$16,235.01, which is\s+\$235.01\s+more than the statement's ending balance/))
          .toBeInTheDocument();
      });

    it("says why it cannot be read, and offers no button that would fail", async () => {
      const fetchMock = await choose({ ...PDF, refused:
        "This month's AI budget is spent, and a PDF statement is read by Claude." });
      expect(await screen.findByText(/This month's AI budget is spent/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Read it with Claude/ })).toBeDisabled();
      expect(posts(fetchMock, "dry-run/")).toHaveLength(0);
    });
  });

  it("says a saved mapping is being used", async () => {
    show("import", { "POST /api/finance-imports/detect/":
      () => ({ body: { ...DETECTED, from_saved: true } }) });
    await userEvent.selectOptions(await screen.findByLabelText("Account to import into"), "a1");
    await userEvent.upload(screen.getByLabelText("The file from your bank"),
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
            { on_date: "2026-10-01", amount_cents: 5999, description: "Adobe license" }] } } }),
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
      expect(screen.getByText(/1 you had edited since was kept: Adobe license \(\$59\.99\)/))
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

describe("rules by hand (P6 M4 stop 1)", () => {
  const PERSONAL = {
    categories: [{ id: "p1", name: "Phone and internet", type: "expense", parent: null,
                   position: 0, system: false, tax_group: "", tax_group_label: "",
                   archived: false }],
    tax_groups: [] };
  const RULE: FinanceRule = {
    id: "u1", contains: "VERIZON", treat_as: "category", category: { id: "c3", name: "Meals" },
    other_account: null, account: null, is_active: true, side: "split", split_percent: 60,
    personal_category: { id: "p1", name: "Phone and internet" } };

  function settings(modules: string[]) {
    const fetchMock = mockApi({
      "POST /api/finance-rules/": () => ({ status: 201, body: RULE }),
      "PATCH /api/finance-rules/u1/": () => ({ body: RULE }),
      "GET /api/finance-rules/": [RULE], "GET /api/finance-accounts/": ACCOUNTS,
      "GET /api/finance-categories/": CATEGORIES, "GET /api/me": aMe({ modules }),
      "GET /api/personal/categories": PERSONAL,
      "GET /api/finance-settings/": { locked_through: null, invoice_income_category: "c1" } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<FinanceSettings />);
    return fetchMock;
  }

  it("adds a rule with its side: split, with the percent that is business", async () => {
    const fetchMock = settings(["personal"]);
    const shown = (await screen.findByText("“VERIZON”")).closest("tr") as HTMLElement;
    expect(shown).toHaveTextContent("60% Meals, the rest personal (Phone and internet)");
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    await userEvent.type(screen.getByLabelText("Text of the new rule"), "COMCAST");
    await userEvent.selectOptions(screen.getByLabelText("Side of the new rule"), "split");
    await userEvent.selectOptions(screen.getByLabelText("Category of the new rule"), "c3");
    await userEvent.clear(screen.getByLabelText("Percent business of the new rule"));
    await userEvent.type(screen.getByLabelText("Percent business of the new rule"), "40");
    await waitFor(() => expect(screen.getByLabelText("Personal category of the new rule"))
      .toHaveTextContent("Phone and internet"));
    await userEvent.selectOptions(screen.getByLabelText("Personal category of the new rule"),
                                  "p1");
    await userEvent.click(screen.getByRole("button", { name: "Add the rule" }));
    await waitFor(() => expect(posts(fetchMock, "/api/finance-rules/")[0].body).toEqual({
      contains: "COMCAST", treat_as: "category", category: "c3", side: "split",
      personal_category: "p1", split_percent: 40 }));
  });

  it("edits one, and without Personal finance a rule has no side", async () => {
    const fetchMock = settings([]);
    await userEvent.click(await screen.findByRole("button",
                                                  { name: "Edit the rule for VERIZON" }));
    expect(screen.queryByLabelText("Side of the rule for VERIZON")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Category of the rule for VERIZON"),
                                  "c2");
    await userEvent.click(screen.getByRole("button", { name: "Save the rule" }));
    await waitFor(() => expect(posts(fetchMock, "/api/finance-rules/u1/")[0].body).toEqual({
      contains: "VERIZON", treat_as: "category", category: "c2" }));
  });
});

describe("sides in the dry run (P6 M4 decision 2)", () => {
  const MIXED: BankImportBatch = {
    ...BATCH, counts: { ...BATCH.counts, personal: 2, to_sort: 1 },
    rows: [
      row({ id: "m1", description: "NETFLIX.COM", side: "personal",
            personal_category: { id: "p2", name: "Entertainment and subscriptions" },
            rule: { id: "u2", contains: "NETFLIX" } }),
      row({ id: "m2", row_number: 3, description: "COSTCO WHOLESALE", amount_cents: 31240,
            side: "to_sort" }),
      row({ id: "m3", row_number: 4, description: "VERIZON WIRELESS", amount_cents: 10000,
            side: "split", split_business_cents: 6000, category: { id: "c3", name: "Meals" },
            personal_category: { id: "p3", name: "Phone and internet" } }),
      row({ id: "m4", row_number: 5, description: "ADOBE CREATIVE CLOUD" })],
  };
  const PERSONAL = {
    categories: [{ id: "p1", name: "Groceries", type: "expense", parent: null, position: 0,
                   system: false, tax_group: "", tax_group_label: "", archived: false }],
    tax_groups: [] };

  it("shows each line's side beside its category, and puts one on another side", async () => {
    const fetchMock = await toTheDryRun({
      "POST /api/finance-imports/dry-run/": () => ({ status: 201, body: MIXED }),
      "GET /api/me": aMe({ modules: ["personal"] }),
      "GET /api/personal/categories": PERSONAL,
      "POST /api/finance-imports/b1/rows/m2/": () => ({ body: MIXED }) });
    expect(screen.getByLabelText("What the import would do")).toHaveTextContent(
      "2 personal (an owner draw in the books, the spend in your personal ledger) · 1 to sort");
    expect(screen.getByLabelText("Side of line 2")).toHaveValue("personal");
    expect(screen.getByText("your rule: contains “NETFLIX”")).toBeInTheDocument();
    expect(screen.getByLabelText("Side of line 3")).toHaveValue("to_sort");
    expect(screen.getByText("waits in Personal → To sort")).toBeInTheDocument();
    expect(screen.getByText(/\$60\.00 business, \$40\.00 personal \(Phone and internet\)/))
      .toBeInTheDocument();
    expect(screen.getByLabelText("Side of line 5")).toHaveValue("business");
    await userEvent.selectOptions(screen.getByLabelText("Side of line 3"), "personal");
    await waitFor(() => expect(posts(fetchMock, "/rows/m2/")[0].body)
      .toEqual({ decision: "entry", side: "personal", category: null }));
  });

  it("splits a line by hand, in dollars, and remembers it", async () => {
    const fetchMock = await toTheDryRun({
      "POST /api/finance-imports/dry-run/": () => ({ status: 201, body: MIXED }),
      "GET /api/me": aMe({ modules: ["personal"] }),
      "GET /api/personal/categories": PERSONAL,
      "POST /api/finance-imports/b1/rows/m2/": () => ({ body: MIXED }) });
    await userEvent.selectOptions(screen.getByLabelText("Side of line 3"), "split");
    const editor = screen.getByRole("group", { name: "Split line 3" });
    await userEvent.clear(within(editor).getByLabelText("Business part of line 3, in dollars"));
    await userEvent.type(within(editor).getByLabelText("Business part of line 3, in dollars"),
                         "100");
    await userEvent.selectOptions(
      within(editor).getByLabelText("Business category for the split of line 3"), "c2");
    await userEvent.selectOptions(
      within(editor).getByLabelText("Personal category for the split of line 3"), "p1");
    expect(editor).toHaveTextContent("$212.40 personal");
    await userEvent.click(screen.getByLabelText("Remember the side of line 3"));
    await userEvent.click(within(editor).getByRole("button", { name: "Split it" }));
    await waitFor(() => expect(posts(fetchMock, "/rows/m2/")[0].body).toEqual({
      decision: "entry", side: "split", category: "c2", split_business_cents: 10000,
      personal_category: "p1", remember: "COSTCO WHOLESALE" }));
  });

  it("offers no side to a practice without Personal finance", async () => {
    await toTheDryRun({ "GET /api/me": aMe({ modules: [] }) });
    expect(screen.queryByLabelText("Side of line 2")).toBeNull();
  });
});
