import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PersonalCategory, PersonalLine } from "../lib/api";
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

function show(tab: "entries" | "accounts" | "categories", me = WITH_PERSONAL,
              extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/me": me,
    "GET /api/personal/categories": CHART, "GET /api/personal/lines": LINES,
    "GET /api/personal/ledger": { to_sort_threshold_cents: 2500 },
    "GET /api/personal/accounts": [
      { id: "p1", name: "Joint checking", kind: "bank", kind_label: "Bank account",
        last4: "9911", closed: false, side: "personal", in_books: false },
      { id: "a1", name: "Business card", kind: "card", kind_label: "Credit card",
        last4: "", closed: false, side: "mixed", in_books: true }],
    "GET /api/finance-categories/": [
      { id: "b1", name: "Supplies", type: "expense", type_label: "Expense", cpa_code: "",
        position: 0, archived: false, system: false, parent: null }],
    "PATCH /api/personal/lines/l1": () => ({ body: line("l1", "COFFEE BAR") }),
    "POST /api/personal/sort": () => ({ body: { id: "e1", side: "personal", kind: "owner" } }),
    "PATCH /api/personal/categories/c1": () => ({ body: CHART.categories[0] }),
  });
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
