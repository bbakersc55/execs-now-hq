import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Board, Point, Tile } from "../lib/scorecard";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Scorecard } from "./Scorecard";
import { ScorecardCompanies } from "./ScorecardCompanies";

/** After the demo checks (Bryan, 2026-10-22). */
describe("the practice's Scorecard menu", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  it("lists each client: Open for one with a scorecard, Start one for one without", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/companies/": [
      { id: "c1", name: "Alpine Stay Co.", kpis: 6, has_scorecard: true },
      { id: "c2", name: "Acme Tools", kpis: 0, has_scorecard: false }] }));
    renderRoute(<ScorecardCompanies />);
    const table = await screen.findByRole("table", { name: "Clients" });
    expect(within(table).getByRole("link", { name: "Open Alpine Stay Co.'s scorecard" }))
      .toHaveAttribute("href", "/companies/c1/scorecard");
    expect(within(table).getByText("6 KPIs")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Start one for Acme Tools" }))
      .toHaveAttribute("href", "/companies/c2#scorecard-setup");
    expect(within(table).getByText("No scorecard yet")).toBeInTheDocument();
  });

  it("is in the left menu for practice owners and associates, and opens the picker",
    async () => {
      const { App } = await import("../App");
      for (const role of ["FF", "CF"] as const) {
        vi.stubGlobal("fetch", mockApi({
          "GET /api/me": aMe({ role }),
          "GET /api/branding": { display_name: "Executives Now", logo_url: "", palette: null },
          "GET /api/scorecard/companies/": [
            { id: "c1", name: "Alpine Stay Co.", kpis: 6, has_scorecard: true }],
          "GET /api/": [],
        }));
        const { unmount } = renderRoute(<App />, { path: "*", route: "/scorecard" });
        const nav = await screen.findByRole("navigation");
        await waitFor(() => expect(within(nav).getByRole("link", { name: /Scorecard/ }))
          .toHaveAttribute("href", "/scorecard"));
        expect(await screen.findByRole("table", { name: "Clients" })).toBeInTheDocument();
        unmount();
        vi.unstubAllGlobals();
      }
    });

  it("is not in an assistant's menu", async () => {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me": aMe({ role: "VA" }),
      "GET /api/branding": { display_name: "Executives Now", logo_url: "", palette: null },
      "GET /api/": [],
    }));
    renderRoute(<App />, { path: "*", route: "/tasks" });
    const nav = await screen.findByRole("navigation");
    await waitFor(() => expect(within(nav).getAllByRole("link").length).toBeGreaterThan(3));
    expect(within(nav).queryByRole("link", { name: /Scorecard/ })).toBeNull();
  });
});

const point = (start: string, label: string, value: number | null): Point => ({
  period_start: start, label, value, target: 10, status: value === null ? null : "on_track",
  missing: false, edited: false, reading: null, entered_by: "", entered_at: null, source: "",
});

describe("the grid follows the window", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("draws the window's periods and its roll-up, the tile's value", async () => {
    const user = userEvent.setup();
    const history = [point("2026-10-05", "Oct 5", 12), point("2026-10-12", "Oct 12", 9),
                     point("2026-10-19", "Oct 19", null)];
    const tile = {
      id: "k1", name: "Calls", kind: "count", direction: "higher", cadence: "weekly",
      rollup: "sum", tile: "number_trend", unit: "", duration_unit: "", rating_scale: null,
      note: "", component: "", per_person: false, leaderboard: false, page: "p1",
      range_low: null, range_high: null, fixed_target: 10, band: 10, owner: "", owner_id: null,
      may_enter: false, computed: "", shape: "number_trend",
      summary: { value: 21, target: 30, status: "off_track", stale: false, missing: null,
                 periods: 3, periods_in: 2, full_target: 30, days_left: 70, elapsed: 0.2 },
      delta: null, spark: history, history, rows: [], total: true, history_is_window: true,
    } as Tile;
    const board: Board = {
      exists: true, company: { id: "c1", name: "Alpine Stay Co." }, week_start: "monday",
      window: { key: "this_quarter", label: "This quarter", first: "2026-10-01",
                last: "2026-12-31", text: "October to December 2026" },
      pages: [{ id: "p1", name: "Weekly", audience: "everyone" }], page: "p1",
      may_set_up: false, may_enter: false, counts: { in: 1, of: 1, on_track: 0, behind: 0,
      off_track: 1 }, notices: [], kpis: [tile] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": board }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Calls" });
    await user.click(screen.getByRole("button", { name: "Grid" }));
    expect(screen.getAllByRole("columnheader").map((c) => c.textContent)).toEqual(
      ["KPI", "Target", "Oct 5", "Oct 12", "Oct 19", "This quarter", "Owner"]);
    expect(screen.getByLabelText("Calls, This quarter: 21, Off track"))
      .toHaveClass("sc-cell-off_track", "sc-cell-window");
  });
});
