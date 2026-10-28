import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SheetFeedModal } from "./ScorecardFeed";
import { FeedState } from "../lib/scorecard";
import { mockApi } from "../test/render";

const STATE: FeedState = {
  google: { ready: true, account: "bryan@practice.example", connected: true, reconnect: false, refusal: "" },
  kpi: { id: "k1", name: "Revenue", per_person: false, cadence: "weekly", cadence_noun: "week", people: [] },
  feed: null,
};

const GRID = {
  spreadsheet_id: "1AbC", title: "Weekly numbers", tab: "Data", account: "bryan@practice.example",
  tabs: [{ title: "Data", id: 0 }, { title: "Dash", id: 1 }],
  rows: [["Northwind weekly numbers"], [], ["Week of", "Occupancy", "Revenue"],
    ["10/5/2026", "81%", "$12,400"], ["Total", "", "$12,400"]],
  more_rows: 0, header_row: 2,
};

const PREVIEW = {
  header_row: 2, more: 0, skipped: [{ row: 5, why: '"Total" isn\'t a date.' }], skipped_more: 0,
  unmatched: [], counts: { new: 1, update: 0, same: 0, kept: 0, open: 0 },
  periods: [{ start: "2026-10-05", label: "the week of October 5 to 11, 2026", person: "", value: 12400,
    had: null, what: "new", says: "New reading", rows: [4] }],
};

function show(routes: Record<string, unknown>) {
  const fetchMock = mockApi(routes as never);
  vi.stubGlobal("fetch", fetchMock);
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SheetFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { fetchMock, onSaved };
}

describe("the Google Sheet feed (M5 part 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("maps by clicking columns, shows what it would make, and saves only after the preview", async () => {
    const user = userEvent.setup();
    const { fetchMock, onSaved } = show({
      "GET /api/scorecard/feeds/": STATE, "POST /api/scorecard/feeds/open/": GRID,
      "POST /api/scorecard/feeds/preview/": PREVIEW,
      "PUT /api/scorecard/feeds/": { feed: {}, run: { ok: true, new: 1, update: 0 } },
    });
    await user.type(await screen.findByLabelText("The spreadsheet's address"),
      "https://docs.google.com/spreadsheets/d/1AbC/edit");
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByLabelText("Headings in row")).toHaveValue("2");
    await user.click(screen.getByRole("button", { name: "Column A for dates" }));
    await user.click(screen.getByRole("button", { name: "Column C for numbers" }));
    expect(screen.getByRole("button", { name: /Numbers: C \(Revenue\)/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save the feed" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Show what it would make" }));
    const preview = await screen.findByRole("region", { name: "What it would make" });
    expect(within(preview).getByRole("status")).toHaveTextContent("1 new reading");
    expect(within(preview).getByText("New reading")).toBeInTheDocument();
    expect(within(preview).getByText(/1 row left out/)).toBeInTheDocument();
    const asked = fetchMock.calls.find((c) => c.url.includes("/preview/"))!.body as Record<string, unknown>;
    expect(asked).toMatchObject({ date_column: "A", date_header: "Week of", value_column: "C",
      value_header: "Revenue", header_row: 2, mode: "column" });
    await user.click(screen.getByRole("button", { name: "Save the feed" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Revenue now reads from the sheet: 1 new reading."));
  });

  it("cell mode: a click on the cell, and the preview says when it is kept", async () => {
    const user = userEvent.setup();
    show({
      "GET /api/scorecard/feeds/": STATE, "POST /api/scorecard/feeds/open/": GRID,
      "POST /api/scorecard/feeds/preview/": { ...PREVIEW, periods: [], skipped: [],
        cell: { ref: "C4", value: 12400, period: "the week of October 19 to 25, 2026", closes: "2026-10-25" } },
    });
    await user.type(await screen.findByLabelText("The spreadsheet's address"), "1AbC");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByLabelText(/From one cell/));
    await user.click(screen.getByRole("button", { name: "Cell C4" }));
    await user.click(screen.getByRole("button", { name: "Show what it would make" }));
    expect(await screen.findByText(/C4 reads 12400 now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save the feed" })).toBeEnabled();
  });

  it("a grant from before the Sheets permission offers Reconnect Google", async () => {
    show({ "GET /api/scorecard/feeds/": { ...STATE, google: { ...STATE.google, ready: false, reconnect: true } } });
    expect(await screen.findByRole("button", { name: "Reconnect Google" })).toBeInTheDocument();
    expect(screen.getByText(/made before the scorecard could read spreadsheets/)).toBeInTheDocument();
  });

  it("the demo says it never reads Google", async () => {
    show({ "GET /api/scorecard/feeds/": { ...STATE, google: { ...STATE.google, ready: false,
      refusal: "This is the demo. It never reads a Google account." } } });
    expect(await screen.findByText("This is the demo. It never reads a Google account.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Google/ })).toBeNull();
  });
});

describe("the Google Sheet feed by row (a column per period)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("clicks the row of months and the row of numbers, previews, then saves", async () => {
    const user = userEvent.setup();
    const pl = {
      ...GRID, tab: "P&L", tabs: [{ title: "P&L", id: 0 }], header_row: null,
      rows: [["Northwind Foods"], [], [], [], [], [],
        ["", "Account", "Oct 2024", "Nov 2024", "Total"],
        ["", "Revenue", "$8,800,000", "$7,900,000", "$16,700,000"],
        ["", "Net Income", "$1,101,321", "(48,210)", "$1,053,111"]],
    };
    const { fetchMock, onSaved } = show({
      "GET /api/scorecard/feeds/": { ...STATE, kpi: { ...STATE.kpi, name: "Net income", cadence: "monthly",
        cadence_noun: "month", kind: "money" } },
      "POST /api/scorecard/feeds/open/": pl,
      "POST /api/scorecard/feeds/preview/": { ...PREVIEW, header_row: 6,
        skipped: [{ row: "column E", where: "column E", why: '"Total" isn\'t a period.' }],
        counts: { new: 2, update: 0, same: 0, kept: 0, open: 0 },
        periods: [
          { start: "2024-10-01", label: "October 2024", person: "", value: 1101321, had: null, what: "new",
            says: "New reading", rows: ["C"] },
          { start: "2024-11-01", label: "November 2024", person: "", value: -48210, had: null, what: "new",
            says: "New reading", rows: ["D"] }] },
      "PUT /api/scorecard/feeds/": { feed: {}, run: { ok: true, new: 2, update: 0 } },
    });
    await user.type(await screen.findByLabelText("The spreadsheet's address"), "1AbC");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByLabelText("By row (a column per period)"));
    await user.click(screen.getByRole("button", { name: "Row 7 for dates" }));
    await user.click(screen.getByRole("button", { name: "Row 9 for numbers" }));
    expect(screen.getByRole("button", { name: /Numbers: row 9 \(Net Income\)/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show what it would make" }));
    const preview = await screen.findByRole("region", { name: "What it would make" });
    expect(within(preview).getByText("From columns")).toBeInTheDocument();
    expect(within(preview).getByText("$1,101,321")).toBeInTheDocument();
    expect(within(preview).getByText("-$48,210")).toBeInTheDocument();
    expect(within(preview).getByText(/1 column left out/)).toBeInTheDocument();
    expect(within(preview).getByText(/column E: "Total" isn't a period/)).toBeInTheDocument();
    const asked = fetchMock.calls.find((c) => c.url.includes("/preview/"))!.body as Record<string, unknown>;
    expect(asked).toMatchObject({ mode: "row", date_row: 6, value_row: 8, value_label: "Net Income" });
    await user.click(screen.getByRole("button", { name: "Save the feed" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Net income now reads from the sheet: 2 new readings."));
  });
});
