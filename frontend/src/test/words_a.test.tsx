import { screen, within } from "@testing-library/react";
import { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientStatus } from "../components/ClientStatus";
import { ClientTeamsCard } from "../components/ClientTeams";
import { Sheet } from "../components/shell";
import { StakeholdersPanel } from "../components/StakeholdersPanel";
import { Dashboard as Board, GoalBlock, ValueReport } from "../lib/api";
import { WordsProvider } from "../lib/words";
import { Dashboard } from "../screens/Dashboard";
import { Report } from "../screens/Report";
import { Work } from "../screens/Work";
import { WorkParentDetail } from "../screens/WorkParentDetail";
import { COMPANY_ID, aCompany, aMe, aTask, aWorkParent } from "./fixtures";
import { mockApi, renderRoute } from "./render";

/**
 * The practice's own words (2026-10-15) on Work, a goal's or project's page,
 * the value report, the dashboard and the company cards. Each case draws with
 * custom words and checks that they show and the default words do not, in the
 * places the hierarchy is named.
 */
const PAIRS = {
  goal: { singular: "objective", plural: "objectives" },
  project: { singular: "initiative", plural: "initiatives" },
  task: { singular: "action", plural: "actions" },
  step: { singular: "checkpoint", plural: "checkpoints" },
};
const custom = (node: ReactNode) => <WordsProvider pairs={PAIRS}>{node}</WordsProvider>;
const DEFAULT = /\b(goals?|projects?|tasks?)\b/i;

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const acme = { client_company: COMPANY_ID, client_company_name: "Acme Facilities" };

describe("Work, in the practice's words", () => {
  it("names the three lists and an empty goal in the practice's words", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/goals/": [aWorkParent({ id: "g1", kind: "goal", title: "Calm Mondays", ...acme })],
      "/api/projects/": [aWorkParent({ id: "p1", kind: "project", title: "Loose one", ...acme,
                                       goal: null })],
      "/api/tasks/?unfiled=1": [],
      "/api/tasks/": [],
      "/api/client-activity/": [],
      "/api/companies/": [aCompany({ id: COMPANY_ID, name: "Acme Facilities" })],
      "/api/goal-order/": [],
      "/api/goal-proposals/": [],
      "/api/": [],
    }));
    renderRoute(custom(<Work me={aMe({ role: "FF" })} />));

    expect(await screen.findByText("Calm Mondays")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Objectives" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Initiatives with no objective" }))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Actions filed under nothing" }))
      .toBeInTheDocument();
    expect(screen.getByText(
      "Nothing under this objective yet — add an initiative or an action to start it moving."))
      .toBeInTheDocument();
    expect(screen.getByText(/An objective's status is derived/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Goals" })).toBeNull();
    expect(screen.queryByText(/Nothing under this goal/)).toBeNull();
  });

  it("composes the portal's sentence from the terms", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/goals/": [], "/api/projects/": [], "/api/tasks/?unfiled=1": [], "/api/tasks/": [],
      "/api/": [],
    }));
    renderRoute(custom(<Work me={aMe({ role: "ECC", client_company: COMPANY_ID })} />));
    expect(await screen.findByText(
      "Objectives hold initiatives, initiatives hold actions — and an action can stand on its own."))
      .toBeInTheDocument();
  });
});

describe("a goal's own page, in the practice's words", () => {
  it("names its parts, its box and its delete in the practice's words", async () => {
    const goal = aWorkParent();
    vi.stubGlobal("fetch", mockApi({
      [`/api/goals/${goal.id}/children/`]: { projects: [], tasks: [] },
      [`/api/goals/${goal.id}/`]: goal,
      "/api/stakeholders/": [],
      "/api/comments/": [],
    }));
    renderRoute(custom(<WorkParentDetail me={aMe()} kind="goal" />), {
      path: "/work/goals/:id", route: `/work/goals/${goal.id}`,
    });

    expect(await screen.findByText("No initiatives yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Actions filed straight on this objective" }))
      .toBeInTheDocument();
    expect(screen.getByText("No actions yet.")).toBeInTheDocument();
    expect(screen.getByLabelText("New action title")).toBeInTheDocument();
    expect(screen.getByText("Add an action here")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add action" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete this objective" })).toBeInTheDocument();
    expect(screen.getByText(/Deleting an objective does not delete its work: the initiatives and actions/))
      .toBeInTheDocument();
    expect(screen.getByText(/^Objective ·/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).toBeNull();
  });
});

const GOAL_ID = "22222222-2222-4222-8222-222222222222";
const block = (over: Partial<GoalBlock> = {}): GoalBlock => ({
  id: GOAL_ID, title: "Decisions stall", client_company: COMPANY_ID,
  outcome_statement: "", headline: { kind: "none", text: "" },
  measure: {
    kind: "sentence", kind_is_undecided: false, measurable: "", unit: "",
    how_we_will_know: "", direction: "up_is_good", baseline: { value: null, at: null },
    current: null, target: null, movement: "", reading_count: 0, show_chart: false, series: [],
  },
  completion: { done: 0, of: 0, percent: 0 },
  status: "in_progress", target_date: null, horizon_days: 60,
  client_owner_contact: "", is_historical: false,
  resolution: null, resolutions: [], milestones: [],
  narrative: null, source_map_row: null,
  ...over,
} as GoalBlock);

describe("the value report, in the practice's words", () => {
  it("names an open goal's work and its boxes in the practice's words", async () => {
    const report: ValueReport = {
      company: { id: COMPANY_ID, name: "Acme Facilities" },
      timeline: { from: "2026-07-01", to: "2026-09-21", today: "2026-09-21", spans: [], marks: [] },
      current: [block()], historical: [], generated_at: "2026-09-21T12:00:00Z",
    } as ValueReport;
    vi.stubGlobal("fetch", mockApi({
      "GET /api/value-report-exports/": [],
      "GET /api/value-report/": report,
      "GET /api/companies/": [{ id: COMPANY_ID, name: "Acme Facilities", is_client_company: true }],
      "GET /api/goals/": {
        projects: [{ ...aWorkParent({ id: "pr1", kind: "project", title: "Ladder" }), tasks: [] }],
        tasks: [aTask({ id: "t3", title: "Count escalations" })],
      },
      "GET /api/comments/": [],
      "GET /api/goal-order/": { company: COMPANY_ID, order: [], may_reorder: false,
                                may_propose: false, proposal: null, last_decided: null },
      "GET /api/goal-proposals/": { company: COMPANY_ID, may_propose: false, may_decide: false,
                                    proposals: [] },
      "GET /api/branding": { display_name: "Executives Now" },
    }));
    renderRoute(custom(<Report me={aMe()} />), { path: "/report/:id?", route: `/report/${GOAL_ID}` });

    expect(await screen.findByRole("heading", { name: "The work under this objective" }))
      .toBeInTheDocument();
    expect(await screen.findByText("No actions yet.")).toBeInTheDocument();
    expect(screen.getByText("Filed straight on the objective")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add an action")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add an initiative")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add action" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add initiative" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "On the objective itself" })).toBeInTheDocument();
    expect(screen.getByText("Resolve this objective")).toBeInTheDocument();
    expect(screen.getByText(/kept on the objective and the company/)).toBeInTheDocument();
    expect(screen.getByText(/^Per objective:/)).toBeInTheDocument();
    const work = screen.getByRole("region", { name: "Work under Decisions stall" });
    expect(within(work).queryByText(DEFAULT)).toBeNull();
  });
});

describe("the dashboard, in the practice's words", () => {
  it("names its tiles and the client cards in the practice's words", async () => {
    const board = {
      window_days: 7,
      tiles: { tasks_due: 7, tasks_overdue: 0, digests_pending: 0, pipeline_moves: 0,
               goals_open: 5 },
      due_by_day: [], digests: [], pipeline: [],
      clients: [{ id: "co1", name: "Acme Facilities", open_tasks: 4, overdue: 0, open_goals: 2 }],
    } as unknown as Board;
    vi.stubGlobal("fetch", mockApi({ "GET /api/dashboard/": board, "GET /api/pipelines/": [] }));
    renderRoute(custom(<Dashboard me={aMe()} />));

    expect(await screen.findByText("Actions due")).toBeInTheDocument();
    expect(screen.getByText("Open objectives")).toBeInTheDocument();
    expect(screen.getByText("4 open · 2 objectives")).toBeInTheDocument();
    expect(screen.queryByText("Tasks due")).toBeNull();
    expect(screen.queryByText("Open goals")).toBeNull();
  });
});

describe("the company cards, in the practice's words", () => {
  it("says what a client company can be chosen for", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/companies/co1/client-status/": { id: "co1", is_client_company: true,
                                                 undo_blockers: [] },
    }));
    renderRoute(custom(<ClientStatus me={aMe({ role: "VA" })}
      company={aCompany({ id: "co1", is_client_company: true })} />));
    const card = (await screen.findByRole("heading", { name: "Client company" }))
      .closest("section")!;
    expect(card).toHaveTextContent(/chosen for objectives, initiatives and actions/);
    expect(card).not.toHaveTextContent(DEFAULT);
  });

  it("counts what a team holds and what a person may create", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/client-teams/": {
      company: COMPANY_ID, may_manage: true,
      teams: [{ id: "t0", name: "Everyone", is_default: true, projects: 1, open_tasks: 2,
                people: [] },
              { id: "t1", name: "Ops", is_default: false, projects: 0, open_tasks: 1,
                people: [] }],
      people: [{ id: "m2", name: "Ben Orji", email: "ben@x.invalid", role: "ECC",
                 may_create: "projects", leads_all_teams: false, teams: [] }],
    } }));
    renderRoute(custom(<ClientTeamsCard me={aMe()} company={aCompany()} />));
    const teams = await screen.findByRole("table", { name: "Teams" });
    expect(teams).toHaveTextContent("1 initiative, 2 open actions");
    expect(teams).toHaveTextContent("0 initiatives, 1 open action");
    expect(screen.getByText(/senior leadership edits objectives too/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Initiatives and actions" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Objectives too" })).toBeInTheDocument();
    expect(teams).not.toHaveTextContent(DEFAULT);
  });

  it("says where a stakeholder is attached in the practice's words", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/stakeholders/": [
      { id: "s1", contact: { id: "c1", name: "Dana Reyes" }, cadence: "weekly",
        is_muted: false, level: "project", attached_to: "p1", effective: true,
        last_notified_at: null },
    ] }));
    renderRoute(custom(<StakeholdersPanel me={aMe({ role: "ECC" })} target="task" id="t1" />));
    expect(await screen.findByText(/initiative/)).toHaveTextContent("initiative (inherited)");
  });

  it("names a sheet after the practice's task unless told otherwise", () => {
    renderRoute(custom(<Sheet title="x" onClose={() => {}}>body</Sheet>));
    expect(screen.getByRole("dialog", { name: "Action" })).toBeInTheDocument();
  });
});
