import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  PersonalCategory, PersonalImport, PersonalImportRow, PersonalLine, PersonalReconciliation,
} from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";

/** P6 M4 stop 1: the personal side of Finance — the switch, Entries with To
 *  sort, Accounts, and the chart's Tax-deductible marks. */

const cat = (id: string, name: string, more: Partial<PersonalCategory> = {}): PersonalCategory =>
  ({ id, name, type: "expense", parent: null, position: 0, system: false, tax_group: "",
     tax_group_label: "", archived: false, ...more });
const CHART = {
  categories: [cat("c1", "Groceries"), cat("c2", "Health"),
               cat("c3", "Prescriptions", { parent: "c2", tax_group: "medical",
                                            tax_group_label: "Medical and dental" }),
               cat("c4", "Everything else", { system: true })],
  tax_groups: [{ code: "medical", label: "Medical and dental" },
               { code: "charitable", label: "Charitable contributions" }],
};
const line = (id: string, description: string, more: Partial<PersonalLine> = {}): PersonalLine =>
  ({ id, kind: "line", on_date: "2026-10-02", amount_cents: 500, direction: "out", description,
     category: { id: "c4", name: "Everything else" },
     account: { id: "a1", name: "Business card" }, from_books: true, source: "books",
     to_sort: false, ...more });
const LINES = {
  lines: [line("e1", "COSTCO WHOLESALE", { kind: "entry", amount_cents: 31240, category: null,
                                            to_sort: true }),
          line("l1", "COFFEE BAR")],
  to_sort: 1, threshold_cents: 2500,
};
const WITH_PERSONAL = aMe({ modules: ["bookkeeping", "personal"] });

function show(tab: "overview" | "goals" | "entries" | "import" | "accounts" | "categories",
              me = WITH_PERSONAL,
              extra: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    "GET /api/me": me,
    "GET /api/personal/categories": CHART, "GET /api/personal/lines": LINES,
    "GET /api/personal/ledger": { to_sort_threshold_cents: 2500 },
    "GET /api/personal/accounts": [
      { id: "p1", name: "Joint checking", kind: "bank", kind_label: "Bank account",
        last4: "9911", closed: false, side: "personal", in_books: false,
        balance_cents: 412345, reconciled_through: null },
      { id: "a1", name: "Business card", kind: "card", kind_label: "Credit card",
        last4: "", closed: false, side: "mixed", in_books: true }],
    "GET /api/finance-categories/": [
      { id: "b1", name: "Supplies", type: "expense", type_label: "Expense", cpa_code: "",
        position: 0, archived: false, system: false, parent: null }],
    "PATCH /api/personal/lines/l1": () => ({ body: line("l1", "COFFEE BAR") }),
    "POST /api/personal/sort": () => ({ body: { id: "e1", side: "personal", kind: "owner" } }),
    "PATCH /api/personal/categories/c1": () => ({ body: CHART.categories[0] }),
  };
  // A test's own routes win, and are matched first.
  for (const key of Object.keys(extra)) delete defaults[key];
  const fetchMock = mockApi({ ...extra, ...defaults });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Finance personalTab={tab} />);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  try { localStorage.clear(); } catch { /* not needed */ }
});

describe("the personal side", () => {
  it("is titled Personal, carries its own disclaimer and the switch back", async () => {
    show("entries");
    expect(await screen.findByRole("heading", { name: "Personal finance" })).toBeInTheDocument();
    const sides = screen.getByRole("group", { name: "Business or personal" });
    expect(within(sides).getByRole("button", { name: "Personal" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("note")).toHaveTextContent(
      "Budgeting, forecasting and tax estimates only, not tax, legal or financial advice. "
      + "Confirm with your CPA.");
  });

  it("opens on its Overview, and Overview and Goals carry the disclaimer (stop 2)",
    async () => {
      const BUDGET = { has_budget: false, month: null, goals: [], coming_up: [],
        questions_waiting: 0, proposal: { ready: false, least_months: 3, months: [],
                                          envelopes: [] },
        cash_flow: { months: [], labels: [], so_far: "", rows: [], in_cents: [],
                     out_cents: [], net_cents: [] } };
      for (const tab of ["overview", "goals"] as const) {
        const { unmount } = { unmount: () => document.body.replaceChildren() };
        show(tab, WITH_PERSONAL, { "GET /api/personal/budget": BUDGET });
        const nav = await screen.findByRole("navigation", { name: "Personal finance" });
        expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(
          ["Overview", "Forecast", "Goals", "Debts", "Retirement", "Household", "Entries",
           "Import", "Accounts", "Categories"]);
        expect(screen.getByRole("note")).toHaveTextContent("Confirm with your CPA.");
        unmount();
      }
    });

  it("is not there for a practice without the module", async () => {
    show("entries", aMe({ modules: ["bookkeeping"] }));
    expect(await screen.findByText(/Personal finance is its own module/)).toBeInTheDocument();
  });

  it("sorts a Mixed account's waiting line to a side, and remembers it", async () => {
    const user = userEvent.setup();
    const fetchMock = show("entries");
    await user.selectOptions(await screen.findByLabelText("Side of COSTCO WHOLESALE"),
                             "personal");
    await user.selectOptions(screen.getByLabelText("Personal category for COSTCO WHOLESALE"),
                             "c1");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ entry: "e1", side: "personal", category: null, personal_category: "c1",
                 remember: "COSTCO WHOLESALE" }));
  });

  it("moves a ledger line to another category", async () => {
    const user = userEvent.setup();
    const fetchMock = show("entries");
    await user.selectOptions(await screen.findByLabelText("Category for COFFEE BAR"), "c1");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ category: "c1", remember: "COFFEE BAR" }));
  });

  it("lists the household's accounts beside the practice's Mixed ones", async () => {
    show("accounts");
    expect(await screen.findByText("Joint checking")).toBeInTheDocument();
    expect(screen.getByText("Mixed, in the practice's books")).toBeInTheDocument();
  });

  it("marks a category with one of the CPA's groups", async () => {
    const user = userEvent.setup();
    const fetchMock = show("categories");
    expect(await screen.findByLabelText("Tax-deductible group for Prescriptions"))
      .toHaveValue("medical");
    await user.selectOptions(screen.getByLabelText("Tax-deductible group for Groceries"),
                             "charitable");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ tax_group: "charitable" }));
    expect(screen.queryByRole("button", { name: "Archive Everything else" })).toBeNull();
  });
});

describe("the rest of stop 1", () => {
  const OWN = line("j1", "CANYON HARDWARE", { amount_cents: 14200, category: null,
                                              to_sort: true, from_books: false,
                                              source: "import",
                                              account: { id: "p1", name: "Joint checking" } });
  const PAID = line("j2", "CANVA PRO", { amount_cents: 1499, from_books: false,
                                         category: { id: "c9", name: "Paid for the practice" },
                                         paid_for: { entry: "e9", category: "Software" },
                                         account: { id: "p1", name: "Joint checking" } });
  const WAITING = { lines: [LINES.lines[0], OWN, PAID], to_sort: 2, threshold_cents: 2500 };

  it("sorts a personal account's line to the practice's side, paid personally", async () => {
    const user = userEvent.setup();
    const fetchMock = show("entries", WITH_PERSONAL, {
      "GET /api/personal/lines": WAITING,
      "POST /api/personal/sort": () => ({ body: OWN }) });
    expect(await screen.findByText("the practice's: Software, paid personally"))
      .toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Side of CANYON HARDWARE"), "business");
    await user.selectOptions(screen.getByLabelText("Business category for CANYON HARDWARE"),
                             "b1");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ line: "j1", side: "business", category: "b1", personal_category: null,
                 remember: "CANYON HARDWARE" }));
  });

  it("sorts with Claude: priced first, says what is sent, and accepts as rules", async () => {
    const user = userEvent.setup();
    const fetchMock = show("entries", WITH_PERSONAL, {
      "GET /api/personal/lines": WAITING,
      "GET /api/personal/sort-with-claude": {
        estimate_usd: "0.0312", used_today: 3, cap: 20, resets_at: "", refused: "",
        disclaimer: "x", lines: 2, most: 80 },
      "POST /api/personal/sort-with-claude": () => ({ body: {
        cost_usd: "0.028100", used_today: 4, cap: 20, disclaimer: "Not advice.",
        proposals: [
          { kind: "entry", id: "e1", description: "COSTCO WHOLESALE", amount_cents: 31240,
            direction: "out", side: "personal", category: { id: "c1", name: "Groceries" },
            match: "COSTCO", why: "A warehouse store." },
          { kind: "line", id: "j1", description: "CANYON HARDWARE", amount_cents: 14200,
            direction: "out", side: "business", category: { id: "b1", name: "Supplies" },
            match: "CANYON", why: "Hardware." }] } }),
      "POST /api/personal/sort": () => ({ body: OWN }) });
    await user.click(await screen.findByRole("button", { name: "To sort (2)" }));
    const box = await screen.findByRole("group", { name: "Sort these with Claude" });
    expect(box).toHaveTextContent("about $0.03 of your AI budget");
    expect(box).toHaveTextContent("the merchant's name");
    expect(box).toHaveTextContent("Never an account's name or number");
    expect(box).toHaveTextContent("Today: 3 of 20 Finance AI presses.");
    await user.click(within(box).getByRole("button", {
      name: "Sort these with Claude, about $0.03" }));
    expect(await within(box).findByText("A warehouse store.")).toBeInTheDocument();
    // The owner changes one before accepting.
    await user.selectOptions(within(box).getByLabelText("Side proposed for CANYON HARDWARE"),
                             "personal");
    await user.selectOptions(
      within(box).getByLabelText("Category proposed for CANYON HARDWARE"), "c1");
    await user.click(within(box).getByRole("button", { name: "Accept all" }));
    await waitFor(() => expect(fetchMock.calls.filter(
      (c) => c.method === "POST" && c.url === "/api/personal/sort").map((c) => c.body))
      .toEqual([
        { entry: "e1", side: "personal", personal_category: "c1", remember: "COSTCO" },
        { line: "j1", side: "personal", personal_category: "c1", remember: "CANYON" }]));
    expect(await screen.findByText("2 lines sorted, each remembered as a rule."))
      .toBeInTheDocument();
  });

  const prow = (id: string, description: string,
                more: Partial<PersonalImportRow> = {}): PersonalImportRow => ({
    id, row_number: 2, on_date: "2026-10-03", amount_cents: 31240, direction: "out",
    description, outcome: "new", outcome_label: "New line", side: "to_sort", category: null,
    business_category: null, split_business_cents: null, matched: null, rule: null,
    error: "", raw: null, ...more });
  const BATCH: PersonalImport = {
    id: "i1", account: { id: "p1", name: "Joint checking" }, filename: "joint.csv",
    status: "dry_run", status_label: "Dry run", created_at: "2026-10-08T12:00:00Z",
    committed_at: null, source: "csv", statement: null,
    counts: { new: 3, personal: 1, business: 1, split: 0, to_sort: 1, transfer_match: 1,
              duplicate: 0, ignore: 0, error: 0 },
    rows: [prow("r1", "COSTCO WHSE"),
           prow("r2", "ADOBE", { row_number: 3, side: "business", amount_cents: 5999,
                                 business_category: { id: "b1", name: "Supplies" },
                                 rule: { id: "u1", contains: "ADOBE" } }),
           prow("r3", "TRANSFER FROM CHECKING", {
             row_number: 4, outcome: "transfer_match", direction: "in", side: "personal",
             matched: { id: "l9", on_date: "2026-10-02", description: "TRANSFER TO SAVINGS",
                        account: "Joint checking" } })] };

  it("imports a personal account's statement through the same dry run", async () => {
    const user = userEvent.setup();
    const fetchMock = show("import", WITH_PERSONAL, {
      "GET /api/personal/imports": [],
      "POST /api/personal/imports/detect": () => ({ body: {
        header: ["Date", "Description", "Amount"], lines: 3, from_saved: false,
        sample: [], kind: "csv", fixed: false,
        mapping: { date: "Date", date_format: "%m/%d/%Y", description: "Description",
                   amount: "Amount", sign: "negative_is_out", debit: "", credit: "",
                   balance: "", reference: "", bank_id: "" },
        date_formats: [{ value: "%m/%d/%Y", label: "MM/DD/YYYY" }] } }),
      "POST /api/personal/imports/dry-run": () => ({ status: 201, body: BATCH }),
      "POST /api/personal/imports/i1/rows/r1": () => ({ body: BATCH }),
      "POST /api/personal/imports/i1/commit": () => ({ body: { ...BATCH,
                                                               status: "committed" } }) });
    expect(await screen.findByRole("heading", { name: "Personal: import a statement" }))
      .toBeInTheDocument();
    // Only the household's own accounts: the Mixed card is imported on the business side.
    const accounts = await screen.findByLabelText("Account to import into");
    expect(within(accounts).queryByText("Business card")).toBeNull();
    await user.selectOptions(accounts, "p1");
    await user.upload(screen.getByLabelText("The file from your bank"),
                      new File(["Date,Description,Amount\n"], "joint.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Read the file" }));
    await user.click(await screen.findByRole("button", { name: "Show me what would happen" }));
    expect(await screen.findByLabelText("What the import would do")).toHaveTextContent(
      "4 new lines · 1 personal · 1 the practice's, paid personally · 1 to sort"
      + " · 1 the other side of a transfer");
    expect(screen.getByText("in the books as paid personally")).toBeInTheDocument();
    expect(screen.getByText(/TRANSFER TO SAVINGS, Joint checking/)).toBeInTheDocument();
    // The practice's: it waits for its category, then goes.
    await user.selectOptions(screen.getByLabelText("Side of line 2"), "business");
    expect(fetchMock.calls.filter((c) => c.url.includes("/rows/"))).toHaveLength(0);
    await user.selectOptions(screen.getByLabelText("The practice's category for line 2"), "b1");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.includes("/rows/r1"))?.body)
      .toEqual({ decision: "line", side: "business", business_category: "b1" }));
    await user.click(screen.getByRole("button", { name: "Write 4 lines" }));
    expect(await screen.findByText("Imported joint.csv into Joint checking."))
      .toBeInTheDocument();
  });

  it("shows a personal account's balance, and reconciles it with no close", async () => {
    const user = userEvent.setup();
    const REC: PersonalReconciliation = {
      id: "z1", account: { id: "p1", name: "Joint checking", kind: "bank" },
      statement_on: "2026-09-30", statement_balance_cents: 412345, state: "open",
      finished_at: null, starting_balance_cents: 400000, cleared_in_cents: 0,
      cleared_out_cents: 0, difference_cents: 12345,
      lines: [{ id: "l1", on_date: "2026-09-12", amount_cents: 12345, direction: "in",
                description: "INTEREST", cleared: false }] };
    let started = false;
    const fetchMock = show("accounts", WITH_PERSONAL, {
      "POST /api/personal/accounts/p1/reconciliations": () => {
        started = true;
        return { status: 201, body: REC };
      },
      "GET /api/personal/accounts/p1/reconciliations": () => ({
        body: started ? [REC] : [] }),
      "GET /api/personal/reconciliations/z1": REC,
      "POST /api/personal/reconciliations/z1/tick": () => ({ body: REC }) });
    const row = (await screen.findByText("Joint checking")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("$4,123.45");
    expect(row).toHaveTextContent("not yet");
    await user.click(within(row).getByRole("button", { name: "Reconcile Joint checking" }));
    expect(await screen.findByText(/no month close on the personal side/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Statement ending date"), "2026-09-30");
    await user.type(screen.getByLabelText("Statement ending balance"), "4123.45");
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.url.endsWith("/reconciliations") && c.method === "POST")?.body)
      .toEqual({ statement_on: "2026-09-30", statement_balance_cents: 412345 }));
  });
});
