import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScorecardSetup } from "../components/ScorecardSetup";
import { Board, EntryForm, Point, SetupState, Tile } from "../lib/scorecard";
import { WordsProvider } from "../lib/words";
import { aCompany, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Scorecard } from "./Scorecard";
import { ScorecardEntry } from "./ScorecardEntry";

const point = (i: number, value: number | null, status: Point["status"] = "on_track"): Point => ({
  period_start: `2026-07-${String(i + 1).padStart(2, "0")}`, label: `Wk ${i + 1}`, value,
  target: 82, status: value === null ? null : status, missing: value === null, edited: false,
  reading: value === null ? null : `r${i}`, entered_by: "Elena Brooks",
  entered_at: "2026-10-19T09:00:00Z", source: "hand",
});

function tile(over: Partial<Tile>): Tile {
  const history = Array.from({ length: 13 }, (_, i) => point(i, 70 + i));
  return {
    id: "k1", name: "Occupancy", kind: "percent", direction: "higher", cadence: "weekly",
    rollup: "average", tile: "number_trend", unit: "", duration_unit: "", rating_scale: null,
    note: "Booked nights ÷ available nights", component: "", per_person: false,
    leaderboard: false, page: "p1", range_low: null, range_high: null, fixed_target: 82,
    band: 10, owner: "Elena Brooks", owner_id: "u1", may_enter: true, computed: "",
    shape: "number_trend",
    summary: { value: 78, target: 82, status: "behind", stale: false, missing: null,
      periods: 1, periods_in: 1, full_target: 82, days_left: 4, elapsed: 0.4 },
    delta: { change: -3, better: false }, spark: history, history, rows: [], total: true,
    ...over,
  };
}

const BOARD: Board = {
  exists: true, company: { id: "c1", name: "Alpine Stay Co." }, week_start: "monday",
  window: { key: "this_week", label: "This week", first: "2026-10-19", last: "2026-10-25",
    text: "The week of October 19 to 25, 2026" },
  pages: [{ id: "p1", name: "Weekly scorecard", audience: "everyone" },
    { id: "p2", name: "Guest services", audience: "team" }],
  page: "p1", may_set_up: false, may_enter: true,
  counts: { in: 2, of: 3, on_track: 1, behind: 1, off_track: 1 },
  notices: [],
  kpis: [
    tile({}),
    tile({ id: "k2", name: "Overtime hours", kind: "duration", duration_unit: "hours",
      direction: "lower", shape: "status", tile: "status",
      summary: { value: 36, target: 40, status: "on_track", stale: false, missing: null,
        periods: 1, periods_in: 1, full_target: 40, days_left: 4, elapsed: 0.4 } }),
    tile({ id: "k3", name: "Response time", kind: "duration", duration_unit: "minutes",
      direction: "lower", per_person: true, shape: "my_row", total: false,
      rows: [{ membership: "m1", name: "Maya Ortiz", you: true, value: 11, target: 15,
        status: "on_track", stale: false, summary: {} as never, delta: null, spark: [],
        history: [] }],
      summary: { value: 11, target: 15, status: "on_track", stale: false, missing: null,
        periods: 1, periods_in: 1, full_target: 15, days_left: 4, elapsed: 0.4 } }),
  ],
};

describe("the scorecard (M5 part 1)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("draws each tile with its value, target and status in words, and Enter readings",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
      renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
      const occupancy = await screen.findByRole("region", { name: "Occupancy" });
      expect(within(occupancy).getByText("78%")).toBeInTheDocument();
      expect(within(occupancy).getByText("target 82%")).toBeInTheDocument();
      expect(within(occupancy).getByText("Behind")).toBeInTheDocument();
      expect(within(occupancy).getByText("▼ 3 pts")).toHaveClass("sc-bad");
      const overtime = screen.getByRole("region", { name: "Overtime hours" });
      expect(within(overtime).getByText("keep under 40 h")).toBeInTheDocument();
      // A member's per-person KPI is their own row, titled so.
      expect(screen.getByRole("region", { name: "Response time, yours" })).toBeInTheDocument();
      expect(screen.getByText(/2 of 3 readings in · 1 behind, 1 off track/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Enter readings" }))
        .toHaveAttribute("href", "/scorecard/enter");
      expect(screen.getAllByRole("tab").map((t) => t.textContent))
        .toEqual(["Weekly scorecard", "Guest services"]);
    });

  it("offers no Enter readings to someone who may enter nothing", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, may_enter: false } }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Occupancy" });
    expect(screen.queryByRole("link", { name: "Enter readings" })).toBeNull();
  });

  it("asks for the window chosen, and custom dates only once both are given", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/scorecard/": BOARD });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    await screen.findByRole("region", { name: "Occupancy" });
    await user.selectOptions(screen.getByLabelText("Window"), "this_quarter");
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.url.includes("window=this_quarter") && c.url.includes("company=c1"))).toBe(true));
    await user.selectOptions(screen.getByLabelText("Window"), "custom");
    const show = screen.getByRole("button", { name: "Show" });
    expect(show).toBeDisabled();
    await user.type(screen.getByLabelText("First day"), "2026-07-01");
    await user.type(screen.getByLabelText("Last day"), "2026-09-30");
    await user.click(show);
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.url.includes("from=2026-07-01") && c.url.includes("to=2026-09-30"))).toBe(true));
  });

  it("turns a tile over: how it is measured, the last readings, who entered them", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/scorecard/readings/r12/history/": { kpi: "Occupancy",
        period: "the week of October 12 to 18, 2026",
        changes: [{ value: 76, previous: null, by: "Elena Brooks", at: "2026-10-19T09:00:00Z" },
          { value: 82, previous: 76, by: "Sam Whitfield", at: "2026-10-19T12:00:00Z" }] },
      "GET /api/scorecard/": BOARD,
    }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const occupancy = await screen.findByRole("region", { name: "Occupancy" });
    await user.click(within(occupancy).getByRole("button", { name: "Back of Occupancy" }));
    expect(within(occupancy).getByText(/Booked nights ÷ available nights/)).toBeInTheDocument();
    expect(within(occupancy).getByText(/Latest entered by Elena Brooks/)).toBeInTheDocument();
    await user.click(within(occupancy).getByRole("button", { name: "History of Wk 13" }));
    const history = await screen.findByRole("region", {
      name: "History of the week of October 12 to 18, 2026" });
    expect(within(history).getAllByRole("listitem")[1]).toHaveTextContent(
      /^82% \(was 76%\) by Sam Whitfield/);
  });

  it("shows the grid, KPIs down and periods across, each cell by status", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Occupancy" });
    await user.click(screen.getByRole("button", { name: "Grid" }));
    const cell = screen.getByRole("button", { name: "Occupancy, Wk 13: 82%, On track" });
    expect(cell).toHaveClass("sc-cell-on_track", "sc-cell-now");
    expect(screen.getAllByRole("columnheader").map((c) => c.textContent)).toContain("Wk 1");
    await user.click(cell);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Occupancy, Wk 13: 82%, entered by Elena Brooks");
    expect(screen.getByText("Behind, within 10%")).toBeInTheDocument();
  });

  it("opens the meeting view full screen and leaves it", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Occupancy" });
    await user.click(screen.getByRole("button", { name: "Meeting" }));
    const meeting = screen.getByRole("dialog", { name: "Scorecard, meeting view" });
    expect(within(meeting).getAllByRole("region").length).toBe(3);
    expect(within(meeting).getByLabelText("Cycle pages")).toBeInTheDocument();
    await user.click(within(meeting).getByRole("button", { name: "Exit" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says a missing reading instead of drawing a zero", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [tile({
      summary: { value: 74, target: 82, status: "behind", stale: true,
        stale_from: "the week of October 5 to 11, 2026",
        missing: "No reading for the week of October 12 to 18, 2026", periods: 1, periods_in: 0,
        full_target: 82, days_left: 4, elapsed: 0.4 } })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const occupancy = await screen.findByRole("region", { name: "Occupancy" });
    expect(within(occupancy).getByText("74%")).toHaveClass("sc-stale");
    expect(within(occupancy).getByText(/No reading for the week of October 12 to 18, 2026; showing/))
      .toBeInTheDocument();
  });

  it("offers the practice the starter KPIs on an empty scorecard, one click each", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/starters/": () => ({ status: 201, body: { id: "k9" } }),
      "GET /api/scorecard/setup/": { starters: [
        { discipline: "operations", name: "Operations", kpis: [
          { key: "on_time_delivery", name: "On-time delivery", kind: "percent" }] },
        { discipline: "service", name: "Service", kpis: [
          { key: "response_time", name: "Response time", kind: "duration" }] }] },
      "GET /api/scorecard/": { ...BOARD, exists: false, pages: [], kpis: [], may_set_up: true },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    expect(await screen.findByRole("heading", { name: "Start the scorecard" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "+ On-time delivery" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ company: "c1", key: "on_time_delivery" }));
  });

  it("uses the practice's own words for the scorecard", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(
      <WordsProvider pairs={{ scorecard: { singular: "dashboard", plural: "dashboards" } }}>
        <Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />
      </WordsProvider>);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

const FORM: EntryForm = {
  period: { day: "2026-10-12", week_start: "monday", label: "the week of October 12 to 18, 2026",
    closes: "2026-10-18", open: false },
  choices: [{ day: "2026-10-19", label: "the week of October 19 to 25, 2026" },
    { day: "2026-10-12", label: "the week of October 12 to 18, 2026" }],
  kpis: [
    { ...tile({ id: "k1", name: "Guest rating", kind: "rating", rating_scale: 5 }),
      page_name: "Weekly scorecard", period_start: "2026-10-12",
      period_label: "the week of October 12 to 18, 2026", target: 4.6,
      fields: [{ membership: null, name: "", you: false, value: null, reading: null,
        edited: false, last: 4.7 }] },
    { ...tile({ id: "k2", name: "Five-star reviews", kind: "count", per_person: true }),
      page_name: "Guest services", period_start: "2026-10-12",
      period_label: "the week of October 12 to 18, 2026", target: 10,
      fields: [
        { membership: "m1", name: "Maya Ortiz", you: true, value: 12, reading: "r1",
          edited: false, last: 12 },
        { membership: "m2", name: "Dev Patel", you: false, value: null, reading: null,
          edited: false, last: 11 }] },
  ],
  progress: [{ id: "k9", name: "Occupancy", state: "in", owner: "Elena Brooks" },
    { id: "k1", name: "Guest rating", state: "yours", owner: "Maya Ortiz" }],
  notices: [],
};

describe("entering readings (M5 part 1)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists what the person enters, last period beside each, and saves only what changed",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "POST /api/scorecard/readings/": () => ({ status: 200,
          body: { saved: 2, changed: 0, errors: {} } }),
        "GET /api/scorecard/entry/": FORM,
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
      const rating = await screen.findByLabelText(/Guest rating/);
      expect(screen.getByText("last week 4.7")).toBeInTheDocument();
      expect(screen.getByRole("rowheader", { name: "Maya Ortiz (you)" })).toBeInTheDocument();
      expect(screen.getByLabelText("Maya Ortiz Five-star reviews")).toHaveValue("12");
      await user.type(rating, "4.8");
      await user.type(screen.getByLabelText("Dev Patel Five-star reviews"), "14");
      await user.click(screen.getByRole("button", { name: "Save readings" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({
        company: "c1", readings: [
          { kpi: "k1", period_start: "2026-10-12", membership: null, value: "4.8" },
          // Maya's 12 is already in: an unchanged field is not sent.
          { kpi: "k2", period_start: "2026-10-12", membership: "m2", value: "14" }] }));
      expect(await screen.findByRole("status")).toHaveTextContent("Saved 2 readings.");
      expect(screen.getByText("Yours, above")).toBeInTheDocument();
    });

  it("shows the server's reason beside the field it refused, and saves nothing", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "POST /api/scorecard/readings/": () => ({ status: 400, body: { saved: 0, changed: 0,
        errors: { "k1|2026-10-12|": "A rating is from 0 to 5." } } }),
      "GET /api/scorecard/entry/": FORM,
    }));
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.type(await screen.findByLabelText(/Guest rating/), "7");
    await user.click(screen.getByRole("button", { name: "Save readings" }));
    expect(await screen.findByText("A rating is from 0 to 5.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing was saved/)).toBeInTheDocument();
  });
});

const SETUP: SetupState = {
  company: { id: "c1", name: "Alpine Stay Co." }, exists: true, week_start: "monday",
  pages: [{ id: "p1", name: "Weekly scorecard", audience: "everyone", team: null,
    archived: false, position: 1 }],
  kpis: [{ ...tile({ id: "k1", name: "Occupancy" }), position: 1, archived: false,
    audience: "page", audience_team: null, person_total: "sum", target_value: 82,
    behind_band_pct: 10, reading_owner: null, strategy_component: "", month_targets: {},
    people: [], formula: "", source_a: null, source_b: null },
    { ...tile({ id: "k2", name: "Bookings", kind: "count" }), position: 2, archived: false,
      audience: "page", audience_team: null, person_total: "sum", target_value: 95,
      behind_band_pct: 10, reading_owner: null, strategy_component: "", month_targets: {},
      people: [], formula: "", source_a: null, source_b: null }],
  teams: [{ id: "t1", name: "Everyone", is_default: true }],
  owners: [{ id: "u1", name: "Elena Brooks", side: "client" }],
  people: [], starters: [],
};

describe("setting a scorecard up (M5 part 1)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is the practice owner's and associates', never an assistant's", () => {
    const fetchMock = mockApi({ "GET /api/scorecard/setup/": SETUP });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "VA" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    expect(screen.queryByRole("heading", { name: "Scorecard" })).toBeNull();
    expect(fetchMock.calls).toEqual([]);
  });

  it("gives a KPI a target per month, the seasonal way", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/scorecard/kpis/k1/": () => ({ status: 200, body: SETUP.kpis[0] }),
      "GET /api/scorecard/setup/": SETUP,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Edit Occupancy" }));
    await user.click(screen.getByLabelText("A target per month (seasonal)"));
    await user.type(screen.getByLabelText("Target for Jul"), "90");
    await user.selectOptions(screen.getByLabelText("Reading owner"), "u1");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = fetchMock.calls.find((c) => c.method === "PATCH")?.body as Record<string, unknown>;
      expect(body.month_targets).toEqual({ 7: "90" });
      expect(body.reading_owner).toBe("u1");
      expect(body.company).toBe("c1");
    });
    expect(await screen.findByText("Occupancy is saved.")).toBeInTheDocument();
  });
});

describe("computed KPIs and the leaderboard switch (M5 part 1, after review)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("words the leaderboard switch as the consent it is", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/setup/": SETUP }));
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Edit Occupancy" }));
    await user.click(screen.getByLabelText("Per person: one reading per person"));
    expect(screen.getByLabelText(
      "Show a leaderboard: everyone in the audience sees each other's numbers")).toBeInTheDocument();
  });

  it("makes a KPI computed from two others on its cadence, with nobody to enter it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/kpis/": () => ({ status: 201, body: SETUP.kpis[0] }),
      "GET /api/scorecard/setup/": SETUP,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Add a KPI" }));
    await user.type(screen.getByLabelText("Name"), "Occupancy per booking");
    await user.click(screen.getByLabelText(/Computed: worked out/));
    expect(screen.queryByLabelText("Reading owner")).toBeNull();
    expect(screen.queryByLabelText("Per person: one reading per person")).toBeNull();
    await user.selectOptions(screen.getByLabelText("First KPI"), "k1");
    await user.selectOptions(screen.getByLabelText("Second KPI"), "k2");
    await user.click(screen.getByRole("button", { name: "Add the KPI" }));
    await waitFor(() => {
      const body = fetchMock.calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
      expect([body.formula, body.source_a, body.source_b, body.reading_owner, body.per_person])
        .toEqual(["ratio", "k1", "k2", null, false]);
    });
  });

  it("says on the tile what a computed KPI is worked out from", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [
      tile({ id: "k7", name: "Revenue per booking", kind: "money", computed: "Revenue ÷ Bookings",
        owner: "" })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const t = await screen.findByRole("region", { name: "Revenue per booking" });
    expect(within(t).getByText(/computed: Revenue ÷ Bookings/)).toBeInTheDocument();
  });
});
