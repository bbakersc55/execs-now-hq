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

  it("offers the practice the starter KPIs on an empty scorecard, made only by Save on the company page",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
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
      // Off to the company page's form (no route for it here), and nothing made.
      await waitFor(() => expect(screen.queryByRole("heading", { name: "Start the scorecard" })).toBeNull());
      expect(fetchMock.calls.filter((c) => c.method !== "GET")).toEqual([]);
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

/** Two faults from production (Bryan, 2026-10-22): a KPI was made before
 *  Save, and the scorecard view offered the practice no Edit or Archive. */
describe("a KPI is made only by Save, and managed from both places", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const STARTERS = [{ discipline: "operations", name: "Operations", kpis: [
    { key: "on_time_delivery", name: "On-time delivery", kind: "percent", direction: "higher",
      cadence: "weekly", rollup: "average", target_value: 95, tile: "gauge" }] }];
  const EMPTY = { ...SETUP, exists: false, pages: [], kpis: [], starters: STARTERS };

  it("a starter fills the form in and makes nothing until Save; Cancel and Enter make nothing",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "POST /api/scorecard/kpis/": () => ({ status: 201, body: { id: "k9" } }),
        "GET /api/scorecard/setup/": EMPTY,
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
        company={aCompany({ id: "c1", is_client_company: true })} />);
      await user.click(await screen.findByRole("button", { name: "+ On-time delivery" }));
      const form = screen.getByRole("form", { name: "New KPI" });
      expect(within(form).getByLabelText("Name")).toHaveValue("On-time delivery");
      // Enter in a field doesn't save it.
      await user.type(within(form).getByLabelText("Name"), " rate{Enter}");
      // Leaving the form doesn't either.
      await user.click(within(form).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("form", { name: "New KPI" })).toBeNull();
      expect(fetchMock.calls.filter((c) => c.method !== "GET")).toEqual([]);
      // Only Save does.
      await user.click(screen.getByRole("button", { name: "+ On-time delivery" }));
      await user.click(screen.getByRole("button", { name: "Add the KPI" }));
      await waitFor(() => {
        const made = fetchMock.calls.filter((c) => c.method === "POST");
        expect(made.map((c) => c.url)).toEqual(["/api/scorecard/kpis/"]);
        expect(made[0].body).toMatchObject({ company: "c1", name: "On-time delivery",
          kind: "percent", target_value: 95, tile: "gauge" });
      });
    });

  it("the scorecard view's starter link opens the form here, filled in, with nothing made",
    async () => {
      const fetchMock = mockApi({ "GET /api/scorecard/setup/": EMPTY });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
        company={aCompany({ id: "c1", is_client_company: true })} />,
      { path: "/companies/:id", route: "/companies/c1?starter=on_time_delivery#scorecard-setup" });
      const form = await screen.findByRole("form", { name: "New KPI" });
      expect(within(form).getByLabelText("Name")).toHaveValue("On-time delivery");
      expect(fetchMock.calls.filter((c) => c.method !== "GET")).toEqual([]);
    });

  it("the company page's card offers Edit and Archive on every KPI", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/scorecard/kpis/k2/archive/": { ok: true },
      "GET /api/scorecard/setup/": SETUP });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "CF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    for (const name of ["Occupancy", "Bookings"]) {
      expect(await screen.findByRole("button", { name: `Edit ${name}` })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: `Archive ${name}` })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: "Archive Bookings" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url === "/api/scorecard/kpis/k2/archive/")).toBe(true));
  });

  it("the scorecard view's tile: Details → Edit opens the form, and Archive asks first",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "PATCH /api/scorecard/kpis/k1/": { id: "k1" },
        "POST /api/scorecard/kpis/k1/archive/": { ok: true },
        "GET /api/scorecard/setup/": SETUP,
        "GET /api/scorecard/": { ...BOARD, may_set_up: true },
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
        route: "/companies/c1/scorecard" });
      const tile = await screen.findByRole("region", { name: "Occupancy" });
      await user.click(within(tile).getByRole("button", { name: "Back of Occupancy" }));
      await user.click(within(tile).getByRole("button", { name: "Edit Occupancy" }));
      const dialog = await screen.findByRole("dialog", { name: "Edit Occupancy" });
      const name = await within(dialog).findByLabelText("Name");
      await user.clear(name);
      await user.type(name, "Occupancy rate");
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
        .toMatchObject({ name: "Occupancy rate" }));
      expect(await screen.findByText("Occupancy rate is saved.")).toBeInTheDocument();
      await user.click(within(tile).getByRole("button", { name: "Archive Occupancy" }));
      expect(fetchMock.calls.some((c) => c.url.endsWith("/archive/"))).toBe(false);
      await user.click(within(tile).getByRole("button", { name: "Archive" }));
      await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST"
        && c.url === "/api/scorecard/kpis/k1/archive/")).toBe(true));
    });

  it("a client's tile offers Feed from HubSpot, which opens the HubSpot picker", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/scorecard/hubspot/feed/": { kpi: { id: "k1", name: "Occupancy", kind: "percent",
        per_person: false }, connected: false, feed: null },
      "GET /api/scorecard/setup/": SETUP,
      "GET /api/scorecard/": { ...BOARD, may_set_up: true },
    }));
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    const tile = await screen.findByRole("region", { name: "Occupancy" });
    await user.click(within(tile).getByRole("button", { name: "Back of Occupancy" }));
    await user.click(within(tile).getByRole("button", { name: "HubSpot measure for Occupancy" }));
    const dialog = await screen.findByRole("dialog", { name: "Feed Occupancy from HubSpot" });
    expect(await within(dialog).findByText(/no HubSpot connection yet/)).toBeInTheDocument();
  });

  it("no Edit or Archive on a tile for anyone who doesn't set the scorecard up", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, may_set_up: false } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const tile = await screen.findByRole("region", { name: "Occupancy" });
    await user.click(within(tile).getByRole("button", { name: "Back of Occupancy" }));
    expect(within(tile).queryByRole("button", { name: "Edit Occupancy" })).toBeNull();
    expect(within(tile).queryByRole("button", { name: "Archive Occupancy" })).toBeNull();
  });
});

describe("catching up on any past period (Bryan, 2026-10-23)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the catch-up table has a From picker that asks for the period chosen", async () => {
    const user = userEvent.setup();
    const sheet = { cadence: "weekly", lines: [{ ...tile({ id: "k1", name: "Guest rating" }),
      membership: null, person: "", cells: [{ period_start: "2025-01-06", value: 4.5 }] }],
      periods: [{ start: "2025-01-06", label: "Jan 6" }], from: "2025-01-06",
      earliest: "2024-10-21",
      choices: [{ start: "2026-10-19", label: "the week of October 19 to 25, 2026" },
        { start: "2025-01-06", label: "the week of January 6 to 12, 2025" }] };
    const fetchMock = mockApi({ "GET /api/scorecard/bulk/": sheet,
      "GET /api/scorecard/entry/": FORM });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("button", { name: "Catch up on several weeks" }));
    const picker = await screen.findByLabelText("From");
    expect(within(picker).getByRole("option", { name: "The latest periods" })).toBeInTheDocument();
    await user.selectOptions(picker, "2025-01-06");
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.includes("/api/scorecard/bulk/")
      && c.url.includes("from=2025-01-06"))).toBe(true));
  });

  it("a daily catch-up table takes a date", async () => {
    const user = userEvent.setup();
    const sheet = { cadence: "daily", lines: [], periods: [], from: null, earliest: "2024-10-22",
      choices: [] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bulk/": sheet,
      "GET /api/scorecard/entry/": FORM }));
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("button", { name: "Catch up on several weeks" }));
    await user.selectOptions(await screen.findByLabelText("Cadence"), "daily");
    const picker = await screen.findByLabelText("From");
    expect(picker).toHaveAttribute("type", "date");
    await waitFor(() => expect(picker).toHaveAttribute("min", "2024-10-22"));
  });

  it("Earlier steps the table back a width at a time", async () => {
    const user = userEvent.setup();
    const sheet = { cadence: "monthly", lines: [], periods: [{ start: "2026-05-01", label: "May 2026" }],
      from: "2026-05-01", earliest: "2024-11-01", earlier: "2025-11-01", later: null, choices: [] };
    const fetchMock = mockApi({ "GET /api/scorecard/bulk/": sheet, "GET /api/scorecard/entry/": FORM });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("button", { name: "Catch up on several weeks" }));
    expect(await screen.findByRole("button", { name: "Later →" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "← Earlier" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.includes("from=2025-11-01"))).toBe(true));
  });

  it("the cadence menu offers only the cadences there is something to enter in", async () => {
    // Bryan, 2026-10-24: monthly and quarterly showed blank on a scorecard
    // with only weekly KPIs; they aren't offered there now.
    const user = userEvent.setup();
    const weekly = { cadence: "weekly", cadences: ["weekly", "monthly"], from: null,
      earliest: "2024-10-21", choices: [], periods: [{ start: "2026-10-12", label: "Oct 12" }],
      lines: [{ ...tile({ id: "k1", name: "Guest rating" }), membership: null, person: "",
        cells: [{ period_start: "2026-10-12", value: null }] }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bulk/": weekly, "GET /api/scorecard/entry/": FORM }));
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("button", { name: "Catch up on several weeks" }));
    const menu = await screen.findByLabelText("Cadence");
    await waitFor(() => expect(within(menu).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Weekly", "Monthly"]));
  });

  it("rows pasted from a spreadsheet fill the table, by KPI name and by period heading", async () => {
    const user = userEvent.setup();
    const sheet = { cadence: "weekly", from: null, earliest: "2024-10-21", choices: [],
      periods: [{ start: "2026-10-05", label: "Oct 5" }, { start: "2026-10-12", label: "Oct 12" }],
      lines: [
        { ...tile({ id: "k1", name: "Guest rating" }), membership: null, person: "",
          cells: [{ period_start: "2026-10-05", value: null }, { period_start: "2026-10-12", value: null }] },
        { ...tile({ id: "k2", name: "Occupancy" }), membership: null, person: "",
          cells: [{ period_start: "2026-10-05", value: null }, { period_start: "2026-10-12", value: null }] }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bulk/": sheet, "GET /api/scorecard/entry/": FORM }));
    renderRoute(<ScorecardEntry me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("button", { name: "Catch up on several weeks" }));
    const first = await screen.findByLabelText("Guest rating, 2026-10-05");
    await user.click(first);
    await user.paste("KPI\tOct 5\tOct 12\nOccupancy\t81%\t84%\nGuest rating\t4.5\t4.7");
    expect(screen.getByLabelText("Occupancy, 2026-10-05")).toHaveValue("81%");
    expect(screen.getByLabelText("Occupancy, 2026-10-12")).toHaveValue("84%");
    expect(screen.getByLabelText("Guest rating, 2026-10-12")).toHaveValue("4.7");
    expect(screen.getByRole("status")).toHaveTextContent("Pasted 4 values");
  });

  it("a CSV paste with no names fills right and down from the cell", async () => {
    const { pasteInto } = await import("./ScorecardEntry");
    const sheet = { cadence: "weekly", lines: [
      { ...tile({ id: "k1", name: "A" }), membership: null, person: "", cells: [] },
      { ...tile({ id: "k2", name: "B" }), membership: null, person: "", cells: [] }],
      periods: [{ start: "p1", label: "P1" }, { start: "p2", label: "P2" }, { start: "p3", label: "P3" }] };
    const got = pasteInto(sheet as never, { line: 0, period: 1 }, '"1,200",3\n4,"5"\n');
    expect(got.values).toEqual({ "k1|p2|": "1,200", "k1|p3|": "3", "k2|p2|": "4", "k2|p3|": "5" });
  });
});


describe("the scorecard's ties into the rest of the app (M5)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  const OFF = tile({ id: "k9", name: "Delivery rate", off_track_run: 3, may_make_task: true,
    offer_task: true, open_task: null, component: "process",
    task_draft: { title: "Delivery rate: Off track 3 weeks running", description: "From the scorecard." } });

  it("three periods Off track offer a task unprompted, and Make a task references the KPI", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/tasks/": () => ({ status: 201, body: { id: "t1", title: "Delivery rate: Off track 3 weeks running" } }),
      "GET /api/scorecard/": { ...BOARD, kpis: [OFF, tile({ id: "k1", may_make_task: true })] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const offered = await screen.findByRole("region", { name: "Delivery rate" });
    expect(within(offered).getByText(/Off track 3 weeks running/)).toBeInTheDocument();
    // A KPI that isn't three periods Off track offers nothing on its front.
    const quiet = screen.getByRole("region", { name: "Occupancy" });
    expect(within(quiet).queryByRole("button", { name: /Make a task/ })).toBeNull();
    await user.click(within(offered).getByRole("button", { name: "Make a task for Delivery rate" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toMatchObject({
      title: "Delivery rate: Off track 3 weeks running", kpi: "k9" }));
    expect(await screen.findByText(/made: Delivery rate: Off track 3 weeks running/)).toBeInTheDocument();
  });

  it("an open task made from the KPI is shown instead of the offer", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [
      { ...OFF, offer_task: false, open_task: { id: "t1", title: "Chase deliveries" } }] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const t = await screen.findByRole("region", { name: "Delivery rate" });
    expect(within(t).getByRole("link", { name: "Chase deliveries" })).toHaveAttribute("href", "/tasks/t1");
    expect(within(t).queryByRole("button", { name: /Make a task/ })).toBeNull();
  });

  it("groups the tiles by strategy component when asked, and remembers it", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [
      OFF, tile({ id: "k1", component: "traction" }), tile({ id: "k3", name: "Untagged", component: "" })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await user.click(await screen.findByLabelText("Group by component"));
    const groups = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(groups).toEqual(["Process", "Traction", "No component"]);
    expect(within(screen.getByRole("region", { name: "Process" }))
      .getByRole("region", { name: "Delivery rate" })).toBeInTheDocument();
    expect(localStorage.getItem("sc-group-by-component")).toBe("true");
  });

  it("explains the scorecard and drafts the weekly note, priced as estimates, for the practice", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/ai/": { text: "Deliveries slipped; the notes suggest a short-staffed week." },
      "GET /api/scorecard/ai/": { explain_estimate_usd: "0.0312", note_estimate_usd: "0.0420",
        used_today: 2, cap: 20, refused: "" },
      "GET /api/scorecard/setup/": { exists: true, pages: [], kpis: [] },
      "GET /api/scorecard/": { ...BOARD, may_set_up: true },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    const explain = await screen.findByRole("button", { name: "Explain this scorecard (about $0.03)" });
    expect(screen.getByRole("button", { name: "Draft the weekly note (about $0.04)" })).toBeInTheDocument();
    expect(screen.getByText("2 of 20 used today.")).toBeInTheDocument();
    expect(screen.getByText(/nothing about bonuses are sent/)).toBeInTheDocument();
    await user.click(explain);
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ company: "c1", purpose: "explain" }));
    expect(await screen.findByRole("note", { name: "Explanation" })).toHaveTextContent("Deliveries slipped");
  });

  it("says why it can't be pressed, and shows no buttons to a client", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/scorecard/ai/": { explain_estimate_usd: "0.03", note_estimate_usd: "0.04",
        used_today: 20, cap: 20, refused: "That is today's 20 for the scorecard." },
      "GET /api/scorecard/setup/": { exists: true, pages: [], kpis: [] },
      "GET /api/scorecard/": { ...BOARD, may_set_up: true },
    }));
    const view = renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    expect(await screen.findByText("That is today's 20 for the scorecard.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Explain this scorecard/ })).toBeNull();
    view.unmount();
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": BOARD }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Occupancy" });
    expect(screen.queryByText("Ask Claude")).toBeNull();
  });
});

describe("the open period so far, the window menu and a source's cadence", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the open period's reading on the front marked so far, the closed ones below it in Details",
    async () => {
      const user = userEvent.setup();
      const history = Array.from({ length: 13 }, (_, i) => ({
        ...point(i, 70 + i), source: "sheet", so_far: i === 12 }));
      const board = { ...BOARD, kpis: [tile({ history, spark: history,
        summary: { value: 82, target: 82, status: "on_track", stale: false, missing: null,
          periods: 1, periods_in: 1, full_target: 82, days_left: 4, elapsed: 0.4, so_far: true } })] };
      vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": board }));
      renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
      const occupancy = await screen.findByRole("region", { name: "Occupancy" });
      expect(within(occupancy).getByText("82%")).toBeInTheDocument();
      expect(within(occupancy).getByText("so far")).toBeInTheDocument();
      await user.click(within(occupancy).getByRole("button", { name: "Back of Occupancy" }));
      const rows = within(occupancy).getAllByRole("row").slice(1);
      expect(rows[0]).toHaveTextContent(/^Wk 13.*so far/);
      expect(rows.slice(1).every((r) => !/so far/.test(r.textContent ?? ""))).toBe(true);
      expect(rows[1]).toHaveTextContent(/^Wk 12/);
    });

  it("marks a so-far cell in the grid", async () => {
    const user = userEvent.setup();
    const history = Array.from({ length: 13 }, (_, i) => ({ ...point(i, 70 + i), so_far: i === 12 }));
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": {
      ...BOARD, kpis: [tile({ history, spark: history })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    await screen.findByRole("region", { name: "Occupancy" });
    await user.click(screen.getByRole("button", { name: "Grid" }));
    expect(await screen.findByRole("button", { name: /Occupancy, Wk 13: 82% so far/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Occupancy, Wk 12: 81%, On track/ })).toBeInTheDocument();
  });

  it("offers every window whatever the page's cadences", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [
      tile({ cadence: "quarterly" }), tile({ id: "k2", name: "Cash", cadence: "monthly" })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    await screen.findByRole("region", { name: "Cash" });
    expect(within(screen.getByLabelText("Window")).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["This week", "This month", "This quarter", "Year to date", "Last year", "Custom dates…"]);
  });

  it("lists computed sources on the cadence chosen in the form, and drops one that no longer fits", async () => {
    const user = userEvent.setup();
    const setup = { ...SETUP, kpis: [...SETUP.kpis,
      { ...SETUP.kpis[1], id: "k3", name: "Revenue", cadence: "monthly" as const }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/setup/": setup }));
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Add a KPI" }));
    await user.click(screen.getByLabelText(/Computed: worked out/));
    const names = () => within(screen.getByLabelText("First KPI")).getAllByRole("option")
      .map((o) => o.textContent);
    expect(names()).toEqual(["Choose…", "Occupancy", "Bookings"]);
    await user.selectOptions(screen.getByLabelText("First KPI"), "k1");
    await user.selectOptions(screen.getByLabelText("Entered"), "monthly");
    expect(names()).toEqual(["Choose…", "Revenue"]);
    expect(screen.getByLabelText("First KPI")).toHaveValue("");
  });

  it("changing a source's cadence offers to change its computed KPIs with it in one save", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/scorecard/kpis/k1/": (body: unknown) => (body as { with_computed?: boolean }).with_computed
        ? { status: 200, body: SETUP.kpis[0] }
        : { status: 400, body: { detail: "Occupancy per booking is worked out from Occupancy. "
            + "Change it to monthly with it?", field: "with_computed",
            computed: ["Occupancy per booking"] } },
      "GET /api/scorecard/setup/": SETUP,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Edit Occupancy" }));
    await user.selectOptions(screen.getByLabelText("Entered"), "monthly");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Change it to monthly with it\?/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change them together and save" }));
    expect(await screen.findByText("Occupancy is saved.")).toBeInTheDocument();
    const patches = fetchMock.calls.filter((c) => c.method === "PATCH")
      .map((c) => (c.body as { with_computed: boolean; cadence: string }));
    expect(patches.map((b) => [b.cadence, b.with_computed])).toEqual([["monthly", false], ["monthly", true]]);
  });
});

describe("live targets, operands and helpers", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("a Progress tile with a live target reads “102 of 108 · 94%”, and Details names the source", async () => {
    const user = userEvent.setup();
    const live = tile({ name: "Contacts Completed", kind: "count", shape: "progress", tile: "progress",
      rollup: "last", target_live: { text: "the sheet's Total Homeowners column", value: 108 },
      summary: { value: 102, target: 108, status: "behind", stale: false, missing: null,
        periods: 1, periods_in: 1, full_target: 108, days_left: 4, elapsed: 0.4 } });
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [live] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const region = await screen.findByRole("region", { name: "Contacts Completed" });
    expect(within(region).getByText("102")).toBeInTheDocument();
    expect(within(region).getByText("of 108 · 94%")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Back of Contacts Completed" }));
    expect(within(region).getByText("Target 108, live from the sheet's Total Homeowners column."))
      .toBeInTheDocument();
  });

  it("a typed target's Progress tile keeps “of” alone", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, kpis: [tile({
      name: "Revenue", kind: "count", shape: "progress", tile: "progress",
      summary: { value: 50, target: 100, status: "off_track", stale: false, missing: null,
        periods: 1, periods_in: 1, full_target: 100, days_left: 4, elapsed: 0.4 } })] } }));
    renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
    const region = await screen.findByRole("region", { name: "Revenue" });
    expect(within(region).getByText("of 100")).toBeInTheDocument();
  });

  it("sets a live target from the sheet's column, an operand from a KPI's target, and a helper", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/kpis/": () => ({ status: 201, body: SETUP.kpis[0] }),
      "PATCH /api/scorecard/kpis/k1/": () => ({ status: 200, body: SETUP.kpis[0] }),
      "GET /api/scorecard/setup/": { ...SETUP, fields: { track: [], hubspot: [] } },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ScorecardSetup me={aMe({ role: "FF" })}
      company={aCompany({ id: "c1", is_client_company: true })} />);
    await user.click(await screen.findByRole("button", { name: "Edit Occupancy" }));
    await user.selectOptions(screen.getByLabelText("Target from"), "sheet_column");
    expect(screen.queryByLabelText("Target")).toBeNull();
    await user.type(screen.getByLabelText("Column heading or letter"), "Total Homeowners");
    await user.click(screen.getByLabelText(/Helper: not shown as a tile/));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = fetchMock.calls.find((c) => c.method === "PATCH")?.body as Record<string, unknown>;
      expect(body.target_live).toEqual({ kind: "sheet_column", header: "Total Homeowners", column: "" });
      expect(body.helper).toBe(true);
    });
    await user.click(await screen.findByRole("button", { name: "Add a KPI" }));
    await user.type(screen.getByLabelText("Name"), "Reached");
    await user.click(screen.getByLabelText(/Computed: worked out/));
    await user.selectOptions(screen.getByLabelText("First KPI"), "k1");
    await user.selectOptions(screen.getByLabelText("Second KPI"), "k1");
    await user.selectOptions(screen.getByLabelText("Of the second, use"), "target");
    await user.click(screen.getByRole("button", { name: "Add the KPI" }));
    await waitFor(() => {
      const body = fetchMock.calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
      expect([body.source_a, body.source_b, body.operand_a, body.operand_b])
        .toEqual(["k1", "k1", null, { kind: "target" }]);
    });
  });
});
