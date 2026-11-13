import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlanColumn, PlanItemRow, PlanPayload, WeekPayload } from "../lib/plans";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PlanScreen, ThisWeekScreen } from "./Plan";
import { WordingSection } from "./Wording";

function item(over: Partial<PlanItemRow>): PlanItemRow {
  return {
    id: "i1", horizon: "quarter", period_start: "2026-10-01", period_label: "October to December 2026",
    title: "Sign four new wholesale accounts", done_means: "Four signed agreements",
    status: "on_track", status_label: "On track", owner: { id: "u1", name: "Bryan Baker" },
    serves: null, served_by: [], goal: null, project: null, client_team: null, target_value: null,
    tasks: [], kpis: [], state: "accepted", source: "hand", source_label: "Added by hand",
    drew_on: [], from_ai_app: false, from_ai: false, proposed_by: "", may_edit: true, ...over,
  };
}

function col(key: PlanColumn["key"], name: string, over: Partial<PlanColumn> = {}): PlanColumn {
  return { key, name, period_start: "2026-11-09", period_label: name, is_current: true,
    previous: "2026-11-02", next: "2026-11-16", items: [], proposals: [], closed: null,
    last_close: null, close_offer: null, ...over };
}

const STAFF_ACCESS = { horizons: ["picture", "year", "quarter", "month", "week"] as PlanColumn["key"][],
  edits: true, may_close: true, may_draft: true, sees_tray: true,
  may_add: ["picture", "year", "quarter", "month", "week"] as PlanColumn["key"][], may_propose: [] };

function staffPlan(): PlanPayload {
  return {
    company: { id: "c1", name: "Acme Fasteners", is_practice: false, fiscal_year_start: 1,
      week_start: "monday" },
    today: "2026-11-13", access: STAFF_ACCESS,
    choices: { people: [], goals: [], projects: [], tasks: [], kpis: [], teams: [] },
    horizons: [
      col("picture", "Three-year picture"),
      col("year", "This year's goals", { items: [item({ id: "y1", horizon: "year",
        title: "The 90-day operations reset", goal: { id: "g1", title: "The 90-day operations reset" },
        served_by: [{ id: "i1", title: "Sign four new wholesale accounts", horizon: "quarter",
          status: "on_track", status_label: "On track", period_label: "Q4" }] })] }),
      col("quarter", "This quarter's priorities", {
        items: [item({ serves: { id: "y1", title: "The 90-day operations reset", horizon: "year" },
          kpis: [{ id: "k1", name: "Scrap rate", value_text: "3.4%", target_text: "keep under 3%",
            status: "behind", status_label: "Behind", period: "Week of November 2" }] })],
        proposals: [item({ id: "p1", title: "Map the quoting process", state: "proposed",
          from_ai: true, drew_on: ["Strategy session, October 2, 2026"] })] }),
      col("month", "This month's plan"),
      col("week", "This week's sprint", {
        items: [item({ id: "w1", horizon: "week", title: "Every order picked right",
          tasks: [{ id: "t1", title: "Count the bins", status: "done", status_label: "Done",
            done: true, due_date: null, owner: "", client_owner: "", team: "", team_id: null,
            project: "" }] })],
        last_close: { summary: "Week of November 2: “Clean the floor”. 3 of 4 tasks done.",
          period_label: "Week of November 2", closed_at: "2026-11-09T10:00:00Z" },
        close_offer: { period_start: "2026-11-09", label: "Week of November 9", late: false } }),
    ],
  };
}

const route = { path: "/companies/:id/plan", route: "/companies/c1/plan" };

describe("the plan (P11)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("five horizons side by side; each item says what it serves and what serves it", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/plans/c1/": staffPlan() }));
    renderRoute(<PlanScreen me={aMe({ role: "FF" })} />, route);
    for (const name of ["Three-year picture", "This year's goals", "This quarter's priorities",
      "This month's plan", "This week's sprint"]) {
      expect(await screen.findByRole("region", { name })).toBeInTheDocument();
    }
    const quarter = screen.getByRole("region", { name: "This quarter's priorities" });
    const priority = within(quarter).getByRole("article", { name: "Sign four new wholesale accounts" });
    expect(priority).toHaveTextContent("Serves: The 90-day operations reset");
    expect(within(priority).getByText("Behind")).toBeInTheDocument();
    const year = screen.getByRole("region", { name: "This year's goals" });
    expect(year).toHaveTextContent("Served by");
    expect(within(year).getByRole("link", { name: "The 90-day operations reset" }))
      .toHaveAttribute("href", "/work/goals/g1");
    const week = screen.getByRole("region", { name: "This week's sprint" });
    expect(week).toHaveTextContent("Last week: Week of November 2");
    expect(within(week).getByRole("button", { name: "Close the week" })).toBeInTheDocument();
    expect(screen.getByLabelText("Fiscal year starts in")).toHaveValue("1");
  });

  it("the tray: a proposal names what it drew on, and Accept puts it on the plan", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/plans/c1/": staffPlan(),
      "POST /api/plan-items/p1/accept/": item({ id: "p1" }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PlanScreen me={aMe({ role: "FF" })} />, route);
    const tray = await screen.findByLabelText("Proposed for This quarter's priorities");
    expect(tray).toHaveTextContent("Drafted by Claude · drew on Strategy session, October 2, 2026");
    await user.click(within(tray).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url.endsWith("/api/plan-items/p1/accept/"))).toBe(true));
  });

  it("Draft from sources says its price first and sends the chosen sources", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/plans/c1/sources/": { sources: [
      { type: "session", id: "s1", label: "Strategy session, October 2, 2026", detail: "5 map rows" },
      { type: "scorecard", id: "scorecard", label: "The scorecard", detail: "KPIs behind first" }],
      ai: { estimate_usd: "0.1234", used_today: 2, cap: 20, refused: "" } },
      "POST /api/plans/c1/draft/": () => ({ status: 201, body: { proposals: [item({ state: "proposed" })],
        cost_usd: "0.11", used_today: 3, cap: 20 } }),
      "GET /api/plans/c1/": staffPlan() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PlanScreen me={aMe({ role: "FF" })} />, route);
    const month = await screen.findByRole("region", { name: "This month's plan" });
    await user.click(within(month).getByRole("button", { name: "Draft from sources" }));
    const press = await screen.findByRole("button", { name: "Draft with Claude (about $0.12)" });
    expect(press).toBeDisabled();
    await user.click(screen.getByLabelText(/The scorecard/));
    await user.type(screen.getByLabelText(/Pasted text/), "Night shift misses scans");
    await user.click(press);
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "POST" && c.url.endsWith("/draft/"));
      expect(call?.body).toMatchObject({ horizon: "month",
        sources: [{ type: "scorecard", id: "scorecard" }], pasted: "Night shift misses scans" });
    });
    expect(await screen.findByText(/1 proposed into the tray/)).toBeInTheDocument();
  });

  it("Close the week: suggested outcomes, carry over only when chosen", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/plans/c1/close/": { horizon: "week",
      period_start: "2026-11-09", period_label: "Week of November 9", sprint: "Every order picked right",
      rows: [{ kind: "task", id: "t1", title: "Count the bins", status: "done", suggested: "done" },
        { kind: "task", id: "t2", title: "Retrain the night shift", status: "in_progress",
          suggested: "not_done" }],
      next: { period_start: "2026-11-16", period_label: "Week of November 16" } },
      "POST /api/plans/c1/close/": () => ({ status: 201, body: { summary: "Week of November 9: “Every order picked right”. 1 of 2 tasks done; 1 carried over to next week.",
        outcomes: [], next: { horizon: "week", period_start: "2026-11-16",
          period_label: "Week of November 16" }, offer_draft: false } }),
      "GET /api/plans/c1/": staffPlan() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PlanScreen me={aMe({ role: "FF" })} />, route);
    await user.click(await screen.findByRole("button", { name: "Close the week" }));
    expect(await screen.findByLabelText("Count the bins: done")).toBeChecked();
    expect(screen.getByLabelText("Retrain the night shift: not done")).toBeChecked();
    expect(screen.getByLabelText("Retrain the night shift: carry over")).not.toBeChecked();
    await user.click(screen.getByLabelText("Retrain the night shift: carry over"));
    await user.click(screen.getByRole("button", { name: "Close Week of November 9" }));
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "POST" && c.url.endsWith("/close/"));
      expect(call?.body).toEqual({ horizon: "week", period_start: "2026-11-09",
        outcomes: { t2: "carried" } });
    });
    expect(await screen.findByText(/1 carried over to next week/)).toBeInTheDocument();
  });

  it("a client member sees the month and week only, with no drafting or closing", async () => {
    const plan = staffPlan();
    const member: PlanPayload = { ...plan, choices: null,
      access: { horizons: ["month", "week"], edits: false, may_close: false, may_draft: false,
        sees_tray: false, may_add: ["month", "week"], may_propose: [] },
      horizons: plan.horizons.filter((c) => c.key === "month" || c.key === "week")
        .map((c) => ({ ...c, close_offer: null, items: c.items.map((i) => ({ ...i, may_edit: false })) })) };
    vi.stubGlobal("fetch", mockApi({ "GET /api/plans/mine/": member }));
    renderRoute(<PlanScreen me={aMe({ role: "ECC", client_company: "c1" })} />,
      { path: "/plan", route: "/plan" });
    expect(await screen.findByRole("region", { name: "This week's sprint" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "This year's goals" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Draft from sources" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Close/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("the client owner proposes at the quarter rather than adding", async () => {
    const user = userEvent.setup();
    const plan = staffPlan();
    const owner: PlanPayload = { ...plan, access: { ...STAFF_ACCESS, edits: false, may_close: false,
      may_draft: false, sees_tray: false, may_add: ["month", "week"], may_propose: ["year", "quarter"] } };
    const fetchMock = mockApi({ "GET /api/plans/mine/": owner,
      "POST /api/plan-items/": () => ({ status: 201, body: item({ state: "proposed" }) }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PlanScreen me={aMe({ role: "FCC", client_company: "c1" })} />,
      { path: "/plan", route: "/plan" });
    const quarter = await screen.findByRole("region", { name: "This quarter's priorities" });
    await user.click(within(quarter).getByRole("button", { name: "Propose" }));
    expect(screen.getByText("The practice approves it before it goes on the plan.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Title"), "Open a second warehouse");
    await user.click(screen.getByRole("button", { name: "Propose it" }));
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "POST");
      expect(call?.body).toMatchObject({ company: "mine", horizon: "quarter",
        title: "Open a second warehouse" });
    });
  });

  it("This week: the sprint goal, my tasks, my team's, and what it serves", async () => {
    const week: WeekPayload = { company: { id: "c1", name: "Acme Fasteners" },
      name: "This week's sprint", period_start: "2026-11-09", period_label: "Week of November 9",
      sprint: { id: "w1", title: "Every order picked right", done_means: "", status: "on_track",
        status_label: "On track", owner: null, may_edit: false },
      mine: [{ id: "t1", title: "Count the bins", status: "in_progress", status_label: "In progress",
        done: false, due_date: "2026-11-13", owner: "", client_owner: "Marvin Martian", team: "",
        team_id: null, project: "" }],
      team: [], others: [],
      serves: [{ id: "m1", title: "Fix the top two bottlenecks", horizon: "month",
        name: "This month's plan", status_label: "On track" }],
      done: 2, total: 5, access: STAFF_ACCESS };
    vi.stubGlobal("fetch", mockApi({ "GET /api/plans/mine/week/": week }));
    renderRoute(<ThisWeekScreen />, { path: "/plan/week", route: "/plan/week" });
    const goal = await screen.findByRole("region", { name: "The sprint goal" });
    expect(goal).toHaveTextContent("Every order picked right");
    expect(goal).toHaveTextContent("2 of 5 tasks done");
    expect(screen.getByRole("region", { name: "Your tasks" })).toHaveTextContent("Count the bins");
    expect(screen.getByRole("region", { name: "What the week serves" }))
      .toHaveTextContent("Fix the top two bottlenecks");
  });

  it("This week for a team member: the team line and teammates' tasks, read only", async () => {
    const week: WeekPayload = { company: { id: "c1", name: "Acme Fasteners" },
      name: "This week's sprint", period_start: "2026-11-09", period_label: "Week of November 9",
      sprint: { id: "w1", title: "Every order picked right", done_means: "", status: "on_track",
        status_label: "On track", owner: null, may_edit: false },
      mine: [{ id: "t1", title: "Count the bins", status: "in_progress", status_label: "In progress",
        done: false, due_date: null, owner: "", client_owner: "Marvin Martian", team: "",
        team_id: null, project: "" }],
      team: [{ title: "Run second shift's changeover", owner: "Elmer Fudd", status: "done",
        status_label: "Done", done: true, read_only: true }],
      team_lines: [{ team: "Everyone", done: 7, total: 12 }], teammates: true,
      others: [], serves: [], done: 1, total: 1, access: STAFF_ACCESS };
    vi.stubGlobal("fetch", mockApi({ "GET /api/plans/mine/week/": week }));
    renderRoute(<ThisWeekScreen />, { path: "/plan/week", route: "/plan/week" });
    const team = await screen.findByRole("region", { name: "Your team's tasks" });
    expect(team).toHaveTextContent("Team: 7 of 12 done");
    expect(team).toHaveTextContent("Run second shift's changeover · Done · Elmer Fudd");
    // Read only: nothing in it to open.
    expect(within(team).queryAllByRole("link")).toHaveLength(0);
  });

  it("This week with the switch off: the team line, and a word on why no tasks", async () => {
    const week: WeekPayload = { company: { id: "c1", name: "Acme Fasteners" },
      name: "This week's sprint", period_start: "2026-11-09", period_label: "Week of November 9",
      sprint: { id: "w1", title: "Every order picked right", done_means: "", status: "on_track",
        status_label: "On track", owner: null, may_edit: false },
      mine: [], team: [], team_lines: [{ team: "Everyone", done: 3, total: 9 }], teammates: false,
      others: [], serves: [], done: 0, total: 0, access: STAFF_ACCESS };
    vi.stubGlobal("fetch", mockApi({ "GET /api/plans/mine/week/": week }));
    renderRoute(<ThisWeekScreen />, { path: "/plan/week", route: "/plan/week" });
    const team = await screen.findByRole("region", { name: "Your team's tasks" });
    expect(team).toHaveTextContent("Team: 3 of 9 done");
    expect(team).toHaveTextContent("Your teammates' tasks aren't shown here.");
  });

  it("the practice switches teammates' sprint tasks per client", async () => {
    const user = userEvent.setup();
    const plan = staffPlan();
    const fetchMock = mockApi({ "GET /api/plans/c1/": plan,
      "PATCH /api/plans/c1/": () => ({ status: 200, body: plan }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PlanScreen me={aMe({ role: "FF" })} />, route);
    const box = await screen.findByLabelText("Team members see teammates' sprint tasks");
    expect(box).toBeChecked();
    await user.click(box);
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(call?.body).toEqual({ sprint_team_tasks: false });
    });
  });

  it("Settings → Wording names the five horizons, saved with the words", async () => {
    const user = userEvent.setup();
    const defaults = { goal: { singular: "goal", plural: "goals" },
      project: { singular: "project", plural: "projects" }, task: { singular: "task", plural: "tasks" },
      step: { singular: "step", plural: "steps" }, kpi: { singular: "KPI", plural: "KPIs" },
      scorecard: { singular: "scorecard", plural: "scorecards" } };
    const fetchMock = mockApi({ "GET /api/settings/words": { words: defaults, defaults,
      horizons: { picture: "Three-year picture", year: "This year's goals",
        quarter: "This quarter's priorities", month: "This month's plan", week: "This week's sprint" } },
      "PUT /api/settings/words": (body: unknown) => ({ body: { words: defaults, defaults,
        horizons: (body as { horizons: unknown }).horizons } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<WordingSection />);
    const quarter = await screen.findByLabelText("Name for This quarter's priorities");
    await user.clear(quarter);
    await user.type(quarter, "The quarter's three");
    await user.click(screen.getByRole("button", { name: "Save the wording" }));
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "PUT");
      expect((call?.body as { horizons: Record<string, string> }).horizons.quarter)
        .toBe("The quarter's three");
    });
  });
});
