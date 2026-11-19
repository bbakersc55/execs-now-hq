import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScorecardSetup } from "../components/ScorecardSetup";
import { Board, Point, Priority, SetupState, Tile } from "../lib/scorecard";
import { aCompany, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Scorecard } from "./Scorecard";

/** Bryan, 2026-11-18: a page in priority order, and a KPI's connector set in
 *  the setup's own form. */
const point = (i: number): Point => ({
  period_start: `2026-07-${String(i + 1).padStart(2, "0")}`, label: `Wk ${i + 1}`, value: 10 + i,
  target: 12, status: "on_track", missing: false, edited: false, reading: `r${i}`,
  entered_by: "Elena Brooks", entered_at: "2026-10-19T09:00:00Z", source: "hand",
});

function tile(id: string, name: string, priority: Priority): Tile {
  const history = Array.from({ length: 4 }, (_, i) => point(i));
  return {
    id, name, priority, kind: "count", direction: "higher", cadence: "weekly", rollup: "sum",
    tile: "number_trend", unit: "", duration_unit: "", rating_scale: null, note: "",
    component: "", per_person: false, leaderboard: false, page: "p1", range_low: null,
    range_high: null, fixed_target: 12, band: 10, owner: "", owner_id: null, may_enter: false,
    computed: "", shape: "number_trend",
    summary: { value: 13, target: 12, status: "on_track", stale: false, missing: null,
      periods: 1, periods_in: 1, full_target: 12, days_left: 4, elapsed: 0.4 },
    delta: null, spark: history, history, rows: [], total: true,
  };
}

// As the server sends them: Top, then Medium, then Low.
const BOARD: Board = {
  exists: true, company: { id: "c1", name: "SkyRun Park City" }, week_start: "monday",
  window: { key: "this_week", label: "This week", first: "2026-10-19", last: "2026-10-25",
    text: "The week of October 19 to 25, 2026" },
  pages: [{ id: "p1", name: "Marketing: Ads", audience: "everyone" }], page: "p1",
  may_set_up: false, may_enter: false,
  counts: { in: 5, of: 5, on_track: 5, behind: 0, off_track: 0 }, notices: [],
  kpis: [tile("k3", "Cost per owner lead", "top"), tile("k5", "Google Ads spend", "top"),
    tile("k1", "Meta spend", "medium"), tile("k2", "Google Ads clicks", "medium"),
    tile("k4", "Google Ads impressions", "low")],
};

const headings = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const tilesIn = (group: string) => within(screen.getByRole("region", { name: group }))
  .getAllByRole("region").map((r) => r.getAttribute("aria-label"));

describe("a scorecard page in priority order (2026-11-18)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("opens on the Top KPIs, then Medium, then Low, under light headings, in the app", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    await screen.findByRole("region", { name: "Top priority" });
    expect(headings()).toEqual(expect.arrayContaining(["Top priority", "Medium", "Low"]));
    expect(headings().filter((h) => ["Top priority", "Medium", "Low"].includes(h ?? "")))
      .toEqual(["Top priority", "Medium", "Low"]);
    expect(tilesIn("Top priority")).toEqual(["Cost per owner lead", "Google Ads spend"]);
    expect(tilesIn("Medium")).toEqual(["Meta spend", "Google Ads clicks"]);
    expect(tilesIn("Low")).toEqual(["Google Ads impressions"]);
  });

  it("shows the portal the same order", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Top priority" });
    expect(tilesIn("Top priority")).toEqual(["Cost per owner lead", "Google Ads spend"]);
    expect(tilesIn("Low")).toEqual(["Google Ads impressions"]);
  });

  it("reads as before, with no heading, when every KPI shares one priority", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": {
      ...BOARD, kpis: BOARD.kpis.map((t) => ({ ...t, priority: "medium" })) } }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Meta spend" });
    expect(screen.queryByRole("region", { name: "Medium" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Top priority" })).toBeNull();
  });
});

const SETUP: SetupState = {
  company: { id: "c1", name: "SkyRun Park City" }, exists: true, week_start: "monday",
  pages: [{ id: "p1", name: "Marketing: Ads", audience: "everyone", team: null,
    archived: false, position: 1 }],
  kpis: [{ ...tile("k1", "Meta spend", "medium"), position: 1, archived: false,
    audience: "page", audience_team: null, person_total: "sum", target_value: null,
    behind_band_pct: 10, reading_owner: null, strategy_component: "", month_targets: {},
    people: [], formula: "", source_a: null, source_b: null,
    feed: { kind: "sheet", text: "From SkyRun Marketing KPIs, Weekly, column D", error: "" } }],
  teams: [{ id: "t1", name: "Everyone", is_default: true }], owners: [], people: [],
  starters: [],
};

describe("a KPI's connector in the setup (2026-11-18)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows each KPI's current source in the setup list", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/setup/": SETUP }));
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    expect(await screen.findByText(/from Google Sheet/)).toBeInTheDocument();
  });

  it("makes a KPI with its priority and connects it in one pass", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/scorecard/setup/": SETUP,
      "POST /api/scorecard/kpis/": () => ({ status: 201, body: {
        ...SETUP.kpis[0], id: "k9", name: "Owner leads", priority: "top", feed: null } }),
      "GET /api/scorecard/track/feed/": { connected: false,
        kpi: { id: "k9", name: "Owner leads", kind: "count", per_person: false }, feed: null },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Add a KPI" }));
    const form = screen.getByRole("form", { name: "New KPI" });
    await user.type(within(form).getByPlaceholderText("Occupancy"), "Owner leads");
    await user.selectOptions(within(form).getByLabelText("Priority"), "top");
    await user.selectOptions(within(form).getByLabelText("The number comes from"), "track");
    await user.click(within(form).getByRole("button", { name: "Add the KPI, then connect it" }));
    await waitFor(() => {
      const body = fetchMock.calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
      expect(body.priority).toBe("top");
      expect(body.name).toBe("Owner leads");
    });
    // In the same place: the Track settings the tile's details open.
    const connect = await screen.findByLabelText("Connect Owner leads");
    expect(within(connect).getByText(/Owner leads is added/)).toBeInTheDocument();
    expect(await within(connect).findByText(/This company has no Track connection yet/))
      .toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.startsWith(
      "/api/scorecard/track/feed/?company=c1&kpi=k9"))).toBe(true);
  });
});
