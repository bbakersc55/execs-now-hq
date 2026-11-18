import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/render";
import { SheetProposal, SheetSetup } from "./ScorecardSheetSetup";

/** 2026-11-17: "Set up KPIs from a sheet". */

const column = (column: string, header: string, more = {}) => ({
  column, header, name: header.replace(/ \(\$\)| %/, ""), kind: "number" as const,
  cadence: "weekly", direction: "higher", rollup: "sum", numbers: 12, blanks: 0,
  not_numbers: 0, sample: ["1530000"], skip: false, why_skip: "", ...more });

const proposal: SheetProposal = {
  header_row: 0, date_column: "A", date_header: "Week ending", date_is: "end",
  cadence: "weekly", dates: { count: 12, first: "2026-08-30", last: "2026-11-15" },
  columns: [column("C", "Revenue ($)", { kind: "money" }),
            column("D", "Gross margin %", { kind: "percent", rollup: "average" }),
            column("E", "Leads")],
  skipped: [{ column: "B", reason: "No header, so it is skipped." }], already: [],
  pages: [{ id: "page1", name: "Overview", audience: "everyone",
            audience_label: "Everyone at the company" }],
};

function show(routes: Record<string, unknown>) {
  const fetchMock = mockApi(routes);
  vi.stubGlobal("fetch", fetchMock);
  const onMade = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}>
    <SheetSetup companyId="co1" onClose={() => {}} onMade={onMade} /></QueryClientProvider>);
  return { fetchMock, onMade };
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("set up KPIs from a sheet", () => {
  it("proposes each column, takes changes, and makes them all at once", async () => {
    const summary = { created: [{ id: "k1", name: "Net revenue", page: "Money" },
                                { id: "k2", name: "Gross margin", page: "Overview" }],
                      readings: 23, blank_cells: 1,
                      cells_skipped: [{ why: '"n/a" isn\'t a number.', count: 2 }],
                      columns_skipped: [{ column: "B", reason: "No header, so it is skipped." },
                                        { column: "E", reason: "Skipped by you." }],
                      already: [], failed: [] };
    const { fetchMock, onMade } = show({
      "POST /api/scorecard/sheet-setup/open/": () => ({ body: {
        spreadsheet_id: "abc", title: "Weekly numbers", tabs: [{ title: "Weekly", id: 0 }],
        tab: "Weekly", account: "bryan@practice.example",
        rows: [["Week ending", "", "Revenue ($)", "Gross margin %", "Leads"]],
        proposal, problem: "" } }),
      "POST /api/scorecard/sheet-setup/": () => ({ status: 201, body: summary }),
    });
    await userEvent.type(screen.getByLabelText("The sheet's address"),
                         "https://docs.google.com/spreadsheets/d/abc/edit");
    await userEvent.click(screen.getByRole("button", { name: "Open the sheet" }));
    const table = await screen.findByRole("table", { name: "Columns proposed as KPIs" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByText("Column B: No header, so it is skipped.")).toBeInTheDocument();
    expect(screen.getByLabelText("Its dates are")).toHaveValue("end");
    await userEvent.clear(screen.getByLabelText("Name for Revenue ($)"));
    await userEvent.type(screen.getByLabelText("Name for Revenue ($)"), "Net revenue");
    await userEvent.click(screen.getByLabelText("Make Leads"));
    await userEvent.type(screen.getByLabelText("New page name"), "Money");
    await userEvent.selectOptions(screen.getByLabelText("New page audience"), "leadership");
    await userEvent.click(screen.getByRole("button", { name: "Add the page" }));
    await userEvent.selectOptions(screen.getByLabelText("Page for Revenue ($)"), "new:p1");
    await userEvent.click(screen.getByRole("button", { name: "Make 2 KPIs" }));
    const sent = fetchMock.calls.find((c) => c.url === "/api/scorecard/sheet-setup/")?.body as {
      columns: Record<string, unknown>[]; new_pages: unknown[]; date_is: string };
    expect(sent.date_is).toBe("end");
    expect(sent.new_pages).toEqual([{ key: "p1", name: "Money", audience: "leadership" }]);
    expect(sent.columns[0]).toMatchObject({ column: "C", name: "Net revenue", kind: "money",
                                            new_page: "p1", skip: false });
    expect(sent.columns[1]).toMatchObject({ column: "D", page: "page1", rollup: "average" });
    expect(sent.columns[2]).toMatchObject({ column: "E", skip: true });
    const done = await screen.findByRole("status", { name: "What was set up" });
    expect(done).toHaveTextContent("2 KPIs made, 23 readings loaded.");
    expect(done).toHaveTextContent("1 blank cell: no reading for those periods, never zero.");
    expect(within(done).getByRole("list", { name: "Columns skipped" }))
      .toHaveTextContent("Column E: Skipped by you.");
    expect(onMade).toHaveBeenCalled();
  });

  it("keeps the tabs when a tab can't be proposed, to choose another", async () => {
    show({ "POST /api/scorecard/sheet-setup/open/": () => ({ body: {
      spreadsheet_id: "abc", title: "Weekly numbers",
      tabs: [{ title: "Notes", id: 0 }, { title: "Weekly", id: 1 }], tab: "Notes",
      account: "bryan@practice.example", rows: [["Nothing here"]], proposal: null,
      problem: "This tab has no row of headers: put a header over each column, then open it "
        + "again." } }) });
    await userEvent.type(screen.getByLabelText("The sheet's address"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Open the sheet" }));
    expect(await screen.findByText(/This tab has no row of headers/)).toBeInTheDocument();
    expect(screen.getByLabelText("Tab")).toHaveValue("Notes");
    expect(screen.queryByRole("table")).toBeNull();
  });
});
