import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinanceAccount, FinanceCategory, Pnl } from "../lib/api";
import { FINANCE_DISCLAIMER, categoryOptions, inTreeOrder } from "../lib/finance";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Finance } from "./Finance";
import { FinanceSettings } from "./FinanceSettings";
import { PracticeRow, Practices } from "./Practices";

/** P6 M1, the first stop: the two-level chart and its tools, the Bookkeeping
 *  switch, and the line every Finance screen carries. */

const ACCOUNTS: FinanceAccount[] = [
  { id: "a1", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4421",
    opening_balance_cents: 1000000, opening_on: "2026-01-01", closed: false }];
const cat = (id: string, name: string, type: FinanceCategory["type"],
             more: Partial<FinanceCategory> = {}): FinanceCategory => ({
  id, name, type, type_label: type, cpa_code: "", position: 0, archived: false,
  system: false, used: false, parent: null, merged_into: null, ...more });
const CATEGORIES = [
  cat("fees", "Client fees", "income", { system: true, used: true }),
  cat("retainers", "Retainers", "income", { parent: "fees" }),
  cat("travel", "Travel", "expense", { position: 0, used: true }),
  cat("air", "Airfare", "expense", { parent: "travel", position: 0, used: true }),
  cat("lodging", "Lodging", "expense", { parent: "travel", position: 1 }),
  cat("meals", "Meals", "expense", { position: 1, used: true }),
  cat("vehicle", "Vehicle", "expense", { position: 2 }),
  cat("old", "Entertainment", "expense", { position: 3, archived: true, merged_into: "meals" }),
  cat("draw", "Owner draw", "owner"),
  cat("tax", "Sales tax collected", "held", { system: true })];

const sent = (fetchMock: ReturnType<typeof mockApi>, method: string, suffix: string) =>
  fetchMock.calls.filter((c) => c.method === method && c.url.endsWith(suffix))
    .map((c) => c.body);

function showSettings(extra: Record<string, unknown> = {}, modules = ["bookkeeping"]) {
  const fetchMock = mockApi({
    // First, so the more specific address is matched before the list's; a
    // test's own answer for it replaces this one.
    "GET /api/finance-categories/changes/": [],
    ...extra, "GET /api/me": aMe({ modules }),
    "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-rules/": [],
    "GET /api/finance-categories/": CATEGORIES,
    "GET /api/finance-settings/": { locked_through: null, invoice_income_category: "fees" } });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<FinanceSettings />);
  return fetchMock;
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("the line every Finance screen carries", () => {
  const stubs = {
    "GET /api/me": aMe({ modules: ["bookkeeping"] }),
    "GET /api/finance-categories/changes/": [],
    "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-categories/": CATEGORIES,
    "GET /api/finance-rules/": [], "GET /api/finance-imports/": [],
    "GET /api/finance-settings/": { locked_through: null, invoice_income_category: "fees" },
    "GET /api/finance-payees/": { year: 2026, threshold_cents: 200000,
                                  default_threshold_cents: 200000, over: 0, payees: [] },
    "GET /api/finance-entries/": { entries: [], count: 0,
                                   totals: { income_cents: 0, expenses_cents: 0, net_cents: 0 } },
    "GET /api/finance-reports/pnl/": {
      year: 2026, by: "month", periods: [], income: { rows: [], totals: [], total: 0 },
      expenses: { rows: [], totals: [], total: 0 }, net: [], net_total: 0,
      uncategorized: { count: 0, amount_cents: 0 }, years: [2026] },
    "GET /api/finance-reports/balance/": {
      as_of: "2026-10-08", cash: [], cards: [], cash_total_cents: 0, tax_held_cents: 0,
      owed_total_cents: 0, unplaced: { count: 0, amount_cents: 0 },
      owed_to_you_cents: 0 },
  };

  it("is the owner's words", () => {
    expect(FINANCE_DISCLAIMER).toBe("Bookkeeping and projections only, not tax, legal or "
      + "financial advice. Confirm with your CPA.");
  });

  // Every Finance route in App.tsx: the six tabs, and Settings → Finance.
  it.each(["entries", "import", "payees", "pnl", "balance", "export"] as const)(
    "is on the %s tab", async (tab) => {
      vi.stubGlobal("fetch", mockApi(stubs));
      renderRoute(<Finance tab={tab} />);
      expect(await screen.findByRole("note", { name: "Disclaimer" }))
        .toHaveTextContent(FINANCE_DISCLAIMER);
    });

  it("is on the finance settings", async () => {
    vi.stubGlobal("fetch", mockApi(stubs));
    renderRoute(<FinanceSettings />);
    expect(await screen.findByRole("note", { name: "Disclaimer" }))
      .toHaveTextContent(FINANCE_DISCLAIMER);
  });

  it("covers every finance route the app has", async () => {
    const source = (await import("../App.tsx?raw")).default as string;
    // The screen a route shows: the last component named in its element.
    const routes = [...source.matchAll(
      /path="(\/(?:settings\/)?finance[^"]*)"\s+element=\{(?:<Settings me=\{me\}>)?<(\w+)/g)];
    expect(routes.map((r) => r[1]).sort()).toEqual([
      "/finance", "/finance/1099", "/finance/balance", "/finance/export", "/finance/import",
      "/finance/pnl", "/settings/finance"]);
    // Each is one of the two screens tested above; a new one has to be added there.
    expect(new Set(routes.map((r) => r[2]))).toEqual(new Set(["Finance", "FinanceSettings"]));
  });
});

describe("categories in two levels", () => {
  it("shows each sub-category under its category, with the note about the CPA",
    async () => {
      showSettings();
      const travel = await screen.findByRole("group", { name: "Travel" });
      expect(within(travel).getByLabelText("Name of Airfare")).toBeInTheDocument();
      expect(within(travel).getByLabelText("Name of Lodging")).toBeInTheDocument();
      expect(within(travel).queryByLabelText("Name of Meals")).not.toBeInTheDocument();
      expect(screen.getByText(/Ask your CPA what they want to see, then add, remove or combine/))
        .toBeInTheDocument();
      expect(screen.getByText("combined into Meals")).toBeInTheDocument();
    });

  it("adds a sub-category, and moves a category under another or back to the top",
    async () => {
      const fetchMock = showSettings({
        "POST /api/finance-categories/": () => ({ status: 201, body: CATEGORIES[3] }),
        "PATCH /api/finance-categories/": () => ({ body: CATEGORIES[5] }) });
      await userEvent.type(await screen.findByLabelText("New sub-category of Travel"),
                           "Ground transport");
      await userEvent.click(screen.getByRole("button",
                                             { name: "Add: New sub-category of Travel" }));
      await waitFor(() => expect(sent(fetchMock, "POST", "/api/finance-categories/"))
        .toEqual([{ name: "Ground transport", parent: "travel" }]));

      const where = screen.getByLabelText("Where Meals sits");
      expect(within(where).getByText("Under Travel")).toBeInTheDocument();
      expect(within(where).queryByText("Under Airfare")).not.toBeInTheDocument();
      expect(within(where).queryByText("Under Client fees")).not.toBeInTheDocument();
      await userEvent.selectOptions(where, "travel");
      await userEvent.selectOptions(screen.getByLabelText("Where Airfare sits"), "");
      await waitFor(() => expect(sent(fetchMock, "PATCH", "/")).toEqual([
        { parent: "travel" }, { parent: null }]));
      // One with sub-categories of its own, or one the books rely on, stays put.
      expect(screen.queryByLabelText("Where Travel sits")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Where Client fees sits")).not.toBeInTheDocument();
    });

  it("removes a category nothing has used, and archives one that has entries",
    async () => {
      const fetchMock = showSettings({
        "DELETE /api/finance-categories/vehicle/": () => ({ status: 204, body: null }) });
      await userEvent.click(await screen.findByRole("button", { name: "Remove Vehicle" }));
      await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "DELETE"
        && c.url === "/api/finance-categories/vehicle/")).toBe(true));
      expect(screen.getByRole("button", { name: "Archive Meals" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Remove Meals" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Remove Travel" })).not.toBeInTheDocument();
    });

  it("combines one into another only after saying how many entries move", async () => {
    const count = { entries: 214, first_on: "2025-01-03", last_on: "2026-10-01", rules: 2,
                    sub_categories: 0, from: "Meals", to: "Travel" };
    const fetchMock = showSettings({
      "POST /api/finance-categories/meals/merge/": (body: { preview?: boolean }) =>
        ({ body: body.preview ? count : CATEGORIES }) });
    await userEvent.click(await screen.findByRole("button",
                                                  { name: "Combine Meals into another" }));
    const panel = screen.getByRole("group", { name: "Combine Meals" });
    const into = within(panel).getByLabelText("Combine Meals into");
    // Its own type only, sub-categories named with what they are under.
    expect(within(into).getByText("Travel: Airfare")).toBeInTheDocument();
    expect(within(into).queryByText("Client fees")).not.toBeInTheDocument();
    expect(within(into).queryByText("Entertainment")).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: /^Combine into/ }))
      .not.toBeInTheDocument();

    await userEvent.selectOptions(into, "travel");
    expect(await within(panel).findByRole("status")).toHaveTextContent(
      "214 entries from January 3, 2025 to October 1, 2026 move from Meals to Travel, "
      + "with 2 import rules. No total, balance or net changes. Closed months are included.");
    expect(sent(fetchMock, "POST", "/merge/")).toEqual([{ into: "travel", preview: true }]);

    await userEvent.click(within(panel).getByRole("button", { name: "Combine into Travel" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/merge/")).toEqual([
      { into: "travel", preview: true }, { into: "travel" }]));
    await waitFor(() => expect(screen.queryByRole("group", { name: "Combine Meals" }))
      .not.toBeInTheDocument());
    // One the books rely on is not combined away.
    expect(screen.queryByRole("button", { name: "Combine Client fees into another" }))
      .not.toBeInTheDocument();
  });

  it("splits a category by the text its entries contain, counted first", async () => {
    const count = { entries: 2, first_on: "2026-03-04", last_on: "2026-03-04",
                    from: "Travel", to: "Rideshare", new: true, under: "Travel",
                    contains: "uber", left: 9 };
    const fetchMock = showSettings({
      "POST /api/finance-categories/travel/split/": (body: { preview?: boolean }) =>
        ({ body: body.preview ? count : CATEGORIES }) });
    await userEvent.click(await screen.findByRole("button", { name: "Split Travel" }));
    const panel = screen.getByRole("group", { name: "Split Travel" });
    const countThem = within(panel).getByRole("button", { name: "Count them" });
    expect(countThem).toBeDisabled();
    await userEvent.type(within(panel).getByLabelText("Name of the new category"), "Rideshare");
    await userEvent.type(within(panel).getByLabelText("Entries containing"), "uber");
    await userEvent.click(countThem);
    expect(await within(panel).findByRole("status")).toHaveTextContent(
      "2 entries dated March 4, 2026 move from Travel to Rideshare (new, under Travel); "
      + "9 stay. No total, balance or net changes. Closed months are included.");
    await userEvent.click(within(panel).getByRole("button", { name: "Move them to Rideshare" }));
    const body = { name: "Rideshare", as: "sub", contains: "uber" };
    await waitFor(() => expect(sent(fetchMock, "POST", "/split/")).toEqual([
      { ...body, preview: true }, body]));
    // A category nothing has used has nothing to split.
    expect(screen.queryByRole("button", { name: "Split Vehicle" })).not.toBeInTheDocument();
  });

  it("a split from a sub-category makes the new one beside it, or uses one you have",
    async () => {
      const fetchMock = showSettings({
        "POST /api/finance-categories/air/split/": () => ({
          body: { entries: 1, first_on: "2026-03-04", last_on: "2026-03-04", from: "Airfare",
                  to: "Lodging", new: false, under: "Travel", contains: "hotel", left: 3 } }) });
      await userEvent.click(await screen.findByRole("button", { name: "Split Airfare" }));
      const panel = screen.getByRole("group", { name: "Split Airfare" });
      const where = within(panel).getByLabelText("Where the entries go");
      expect(within(where).queryByText(/new sub-category/)).not.toBeInTheDocument();
      await userEvent.selectOptions(where, "existing");
      await userEvent.selectOptions(within(panel).getByLabelText("The category they go to"),
                                    "lodging");
      await userEvent.type(within(panel).getByLabelText("Entries containing"), "hotel");
      await userEvent.click(within(panel).getByRole("button", { name: "Count them" }));
      expect(await within(panel).findByRole("status")).toHaveTextContent(
        "1 entry dated March 4, 2026 moves from Airfare to Lodging; 3 stay.");
      expect(sent(fetchMock, "POST", "/split/")).toEqual([
        { to: "lodging", contains: "hotel", preview: true }]);
    });

  it("adds the starting chart only after showing what it would add", async () => {
    const plan = { note: "", skipped: [{ name: "Health", why: "“Insurance” is archived" }],
                   add: [{ name: "Payroll", type: "expense", parent: null },
                         { name: "Wages", type: "expense", parent: "Payroll" },
                         { name: "Ground transport", type: "expense", parent: "Travel" }] };
    const fetchMock = showSettings({
      "GET /api/finance-categories/starting-chart/": plan,
      "POST /api/finance-categories/starting-chart/": () => ({ body: { ...plan, added: 3 } }) });
    await userEvent.click(await screen.findByRole("button", { name: "Add the starting chart" }));
    const panel = await screen.findByRole("group", { name: "Add the starting chart" });
    expect(panel).toHaveTextContent("This would add 3 categories. Nothing you have is "
      + "renamed, moved, archived or removed, and no entry moves.");
    expect(panel).toHaveTextContent("Categories: Payroll");
    expect(panel).toHaveTextContent("Sub-categories: Payroll: Wages · Travel: Ground transport");
    expect(panel).toHaveTextContent("Left out: Health (“Insurance” is archived).");
    expect(sent(fetchMock, "POST", "/starting-chart/")).toEqual([]);
    await userEvent.click(within(panel).getByRole("button", { name: "Add these 3" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/starting-chart/")).toEqual([{}]));
    expect(await screen.findByText("Added 3 categories.")).toBeInTheDocument();
  });

  it("says so when there is nothing in the starting chart to add", async () => {
    showSettings({ "GET /api/finance-categories/starting-chart/":
      { add: [], skipped: [], note: "" } });
    await userEvent.click(await screen.findByRole("button", { name: "Add the starting chart" }));
    expect(await screen.findByText(/You already have every category in the\s+starting chart/))
      .toBeInTheDocument();
  });

  it("lists what was combined and split", async () => {
    showSettings({ "GET /api/finance-categories/changes/": [
      { id: "x1", kind: "merge", kind_label: "Combined", from: "Entertainment", to: "Meals",
        entries_moved: 12, first_on: "2025-02-01", last_on: "2026-05-01", contains: "",
        at: "2026-10-08T15:00:00+00:00", by: "John Carter" }] });
    await userEvent.click(await screen.findByText("Combined and split: 1"));
    const table = await screen.findByRole("table", { name: "Combined and split" });
    expect(table).toHaveTextContent("Entertainment combined into Meals");
    expect(table).toHaveTextContent("12, February 1, 2025 to May 1, 2026");
  });

  it("a practice without Bookkeeping sees its chart and none of the tools", async () => {
    const fetchMock = showSettings({}, []);
    expect(await screen.findByLabelText("Name of Airfare")).toBeInTheDocument();
    await screen.findByText("paid invoices go here");
    for (const name of [/^Combine /, /^Split /, "Add the starting chart"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByLabelText("New sub-category of Travel")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Where Meals sits")).not.toBeInTheDocument();
    expect(screen.getByLabelText("New expense category")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.includes("changes")
      || c.url.includes("starting-chart"))).toBe(false);
  });
});

describe("categories wherever one is picked", () => {
  it("lists a category and then its sub-categories, each named with what it is under", () => {
    expect(inTreeOrder(CATEGORIES.filter((c) => c.type === "expense")).map((c) => c.name))
      .toEqual(["Travel", "Airfare", "Lodging", "Meals", "Vehicle", "Entertainment"]);
    expect(categoryOptions(CATEGORIES.filter((c) => c.type === "expense" && !c.archived))
      .map(([, label]) => label)).toEqual([
      "Travel", "Travel: Airfare", "Travel: Lodging", "Meals", "Vehicle"]);
    // A sub-category whose parent is filtered out still names it.
    expect(categoryOptions([CATEGORIES[3]], CATEGORIES)).toEqual([["air", "Travel: Airfare"]]);
  });
});

describe("the profit and loss in two levels", () => {
  const PNL: Pnl = {
    year: 2026, by: "quarter", periods: ["Q1", "Q2", "Q3", "Q4"],
    income: { rows: [{ id: "fees", name: "Client fees", cpa_code: "", total: 500000,
                       amounts: [500000, 0, 0, 0], children: [] }],
              totals: [500000, 0, 0, 0], total: 500000 },
    expenses: { rows: [
      { id: "travel", name: "Travel", cpa_code: "", total: 70000, amounts: [65000, 5000, 0, 0],
        children: [
          { id: "air", name: "Airfare", cpa_code: "", total: 40000, amounts: [40000, 0, 0, 0] },
          { id: "lodging", name: "Lodging", cpa_code: "", total: 25000,
            amounts: [25000, 0, 0, 0] },
          { id: "travel", name: "Travel, not broken down", cpa_code: "", total: 5000,
            amounts: [0, 5000, 0, 0], direct: true }] },
      { id: "meals", name: "Meals", cpa_code: "", total: 1200, amounts: [0, 1200, 0, 0],
        children: [] }],
                totals: [65000, 6200, 0, 0], total: 71200 },
    net: [435000, -6200, 0, 0], net_total: 428800,
    uncategorized: { count: 0, amount_cents: 0 }, years: [2026] };

  function showPnl() {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/finance-accounts/": ACCOUNTS, "GET /api/finance-categories/": CATEGORIES,
      "GET /api/finance-reports/pnl/": PNL }));
    renderRoute(<Finance tab="pnl" />, { route: "/?by=quarter" });
  }

  it("shows each sub-category under its category, and folds them away", async () => {
    showPnl();
    const toggle = await screen.findByRole("button",
                                           { name: "Hide the sub-categories of Travel" });
    const row = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;
    expect(toggle.closest("tr")).toHaveTextContent("$700.00");
    expect(row("Airfare")).toHaveTextContent("$400.00");
    expect(row("Travel, not broken down")).toHaveTextContent("$50.00");
    await userEvent.click(toggle);
    expect(screen.queryByText("Airfare")).not.toBeInTheDocument();
    expect(screen.queryByText("Travel, not broken down")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button",
                                           { name: "Show the sub-categories of Travel" }));
    expect(screen.getByText("Airfare")).toBeInTheDocument();
  });

  it("a category's figure opens its entries and its sub-categories'; a line's, its own",
    async () => {
      showPnl();
      expect(await screen.findByRole("link", { name: "Travel, Q1: $650.00" })).toHaveAttribute(
        "href", "/finance?category=travel&subs=1&from=2026-01-01&to=2026-03-31");
      expect(screen.getByRole("link", { name: "Airfare, Q1: $400.00" })).toHaveAttribute(
        "href", "/finance?category=air&from=2026-01-01&to=2026-03-31");
      expect(screen.getByRole("link", { name: "Travel, not broken down, Q2: $50.00" }))
        .toHaveAttribute("href", "/finance?category=travel&from=2026-04-01&to=2026-06-30");
      expect(screen.getByRole("link", { name: "Meals, Q2: $12.00" })).toHaveAttribute(
        "href", "/finance?category=meals&from=2026-04-01&to=2026-06-30");
    });
});

describe("the Bookkeeping switch in the Practices area", () => {
  const ROW: PracticeRow = {
    id: "p1", display_name: "Blue Sky Business Consulting", legal_name: "Blue Sky LLC",
    domain: "bluesky.example", status: "active", created_at: "2026-10-01T00:00:00Z",
    archived_at: null, oauth_client: "external", staff_count: 1, client_count: 0,
    ai_spend_this_month_usd: "0.00", last_activity_at: null,
    modules: [{ code: "bookkeeping", name: "Bookkeeping", enabled: false }] };

  it("switches a module on for a practice, and says so", async () => {
    const fetchMock = mockApi({
      "POST /api/platform/practices/p1/modules": () => ({ body: {
        ...ROW, modules: [{ code: "bookkeeping", name: "Bookkeeping", enabled: true }] } }),
      "GET /api/platform/practices": [ROW] });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Practices />);
    const box = await screen.findByLabelText("Bookkeeping for Blue Sky Business Consulting");
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(sent(fetchMock, "POST", "/modules")).toEqual([
      { module: "bookkeeping", enabled: true }]));
    expect(await screen.findByText("Blue Sky Business Consulting now has Bookkeeping."))
      .toBeInTheDocument();
  });
});
