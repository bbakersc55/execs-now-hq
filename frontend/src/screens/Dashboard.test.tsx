import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard as Board } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Dashboard } from "./Dashboard";

const DAY = 24 * 60 * 60 * 1000;
/** A time `days` ago, so "this week" and "last week" do not drift with the calendar. */
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

const PIPELINES = [
  { id: "p-sales", name: "Sales", kind: "sales", position: 0, stages: [], contact_count: 3 },
  { id: "p-ref", name: "Referral partners", kind: "referral", position: 1, stages: [],
    contact_count: 2 },
];

function aBoard(overrides: Partial<Board> = {}): Board {
  return {
    window_days: 7,
    tiles: { tasks_due: 7, tasks_overdue: 2, digests_pending: 3,
             pipeline_moves: 4, goals_open: 5 },
    due_by_day: [
      { date: null, label: "Overdue", count: 2, overdue: true },
      { date: "2026-09-22", label: "Today", count: 3, overdue: false },
      { date: "2026-09-23", label: "Tomorrow", count: 0, overdue: false },
      { date: "2026-09-24", label: "Thu 24 Sep", count: 2, overdue: false },
    ],
    digests: [{ id: "d1", contact: "Dana Reyes", cadence: "weekly",
                period_end: "2026-09-25T08:00:00Z", ai_prose: true, stale: false }],
    pipeline: [
      { id: "s1", contact: "c1", name: "Mike Eller", pipeline: "Sales",
        from: "Lead", to: "Qualified lead", at: ago(1) },
      { id: "s2", contact: "c1", name: "Mike Eller", pipeline: "Sales",
        from: "", to: "Lead", at: ago(2) },
      { id: "s3", contact: "c2", name: "Ana Ortiz", pipeline: "Sales",
        from: "", to: "Contact", at: ago(9) },
      { id: "s4", contact: "c3", name: "Pat Quinn", pipeline: "Referral partners",
        from: "", to: "Introduced", at: ago(3) },
    ],
    clients: [
      { id: "co1", name: "Acme Facilities", open_tasks: 4, overdue: 2, open_goals: 1 },
      { id: "co2", name: "Northwind", open_tasks: 1, overdue: 0, open_goals: 2 },
    ],
    ...overrides,
  };
}

function show(board = aBoard(), me = aMe()) {
  const fetchMock = mockApi({ "GET /api/dashboard/": board, "GET /api/pipelines/": PIPELINES });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Dashboard me={me} />, { path: "/", route: "/" });
  return fetchMock;
}

/**
 * The landing page. **One question: what needs me today** — so the tests are
 * about whether it answers that, and whether every answer leads somewhere.
 */
describe("the dashboard", () => {
  beforeEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  it("leads with four tiles, each linking to the screen behind it", async () => {
    show();

    expect(await screen.findByRole("link", { name: /Tasks due/ }))
      .toHaveAttribute("href", "/tasks");
    expect(screen.getByRole("link", { name: /Digests waiting/ }))
      .toHaveAttribute("href", "/digests");
    expect(screen.getByRole("link", { name: /Pipeline moves/ }))
      .toHaveAttribute("href", "/pipeline");
    expect(screen.getByRole("link", { name: /Open goals/ }))
      .toHaveAttribute("href", "/work");
  });

  it("names how much of the total is already late", async () => {
    show();

    // Folded into the total and said out loud: a number that hides how much of
    // it is overdue is a number you stop reading.
    const tile = await screen.findByRole("link", { name: /Tasks due/ });
    expect(tile).toHaveTextContent("7");
    expect(tile).toHaveTextContent("2 overdue");
  });

  it("says so rather than hiding the tile when nothing is late", async () => {
    show(aBoard({ tiles: { tasks_due: 3, tasks_overdue: 0, digests_pending: 0,
                           pipeline_moves: 0, goals_open: 2 } }));

    expect(await screen.findByText("none overdue")).toBeInTheDocument();
  });

  it("shows every day of the week, including the quiet ones", async () => {
    show();

    // A list that skips quiet days makes a light week look like a missing one.
    expect(await screen.findByText("Tomorrow")).toBeInTheDocument();
    expect(screen.getByText("Overdue")).toBeInTheDocument();
    expect(screen.getByText("Thu 24 Sep")).toBeInTheDocument();
  });

  it("lists waiting digests and sends you to the screen that shows them", async () => {
    show();

    /* FR-3.29 — approving something you have not read is the failure the
       approval screen exists to prevent, and this panel cannot show the
       rendered digest. So it lists and links; it does not approve. */
    expect(await screen.findByRole("link", { name: "Dana Reyes" }))
      .toHaveAttribute("href", "/digests");
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("splits the pipeline into prospects and partners, names grouped by week", async () => {
    show();

    const prospects = (await screen.findByRole("heading", { name: "New prospects" }))
      .parentElement!;
    const partners = screen.getByRole("heading", { name: "New partners" }).parentElement!;

    // Two moves by one contact are one name, at the latest move.
    expect(within(prospects).getAllByRole("link", { name: "Mike Eller" })).toHaveLength(1);
    expect(within(prospects).getByText("This week")).toBeInTheDocument();
    expect(within(prospects).getByText("Last week")).toBeInTheDocument();
    expect(within(prospects).getByRole("link", { name: "Ana Ortiz" })).toBeInTheDocument();
    expect(within(partners).getByRole("link", { name: "Pat Quinn" }))
      .toHaveAttribute("href", "/contacts/c3");
    expect(within(partners).queryByText("Mike Eller")).not.toBeInTheDocument();
  });

  it("puts the stage and time on hover, not in a line under every name", async () => {
    show();

    const mike = await screen.findByRole("link", { name: "Mike Eller" });
    expect(mike).toHaveAttribute("href", "/contacts/c1");
    expect(mike.getAttribute("title")).toMatch(/^Lead → Qualified lead · /);
    expect(screen.queryByText(/Lead →/)).not.toBeInTheDocument();
  });

  it("keeps a place for practice finances, with no figures in it", async () => {
    show();

    expect(await screen.findByRole("heading", { name: "Practice finances" }))
      .toBeInTheDocument();
    expect(screen.getByText(/appear here once the finance module lands/))
      .toBeInTheDocument();
  });

  it("does not show a VA even the empty finances slot", async () => {
    show(aBoard(), aMe({ role: "VA" }));

    await screen.findByRole("heading", { name: "Pipeline" });
    expect(screen.queryByRole("heading", { name: "Practice finances" }))
      .not.toBeInTheDocument();
  });

  it("gives one card per client, marked when something is overdue", async () => {
    show();

    const acme = await screen.findByRole("link", { name: /Acme Facilities/ });
    expect(acme).toHaveAttribute("href", "/companies/co1");
    expect(acme).toHaveTextContent("2 overdue");
    expect(screen.getByRole("link", { name: /Northwind/ }))
      .not.toHaveTextContent("overdue");
  });

  it("says plainly when a panel has nothing in it", async () => {
    show(aBoard({
      due_by_day: [{ date: "2026-09-22", label: "Today", count: 0, overdue: false }],
      digests: [], pipeline: [], clients: [],
    }));

    expect(await screen.findByText("Nothing due this week.")).toBeInTheDocument();
    expect(screen.getByText(/No stage changes in the last week/)).toBeInTheDocument();
    expect(screen.getByText("No client companies yet.")).toBeInTheDocument();
  });
});

/** The order is the person's own, remembered in this browser. */
describe("arranging the dashboard", () => {
  beforeEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  const panelOrder = () => screen.getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);

  it("moves a panel with the arrows and remembers it for this user", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Arrange" }));
    fireEvent.click(screen.getByRole("button", { name: "Move Pipeline earlier" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(panelOrder().slice(0, 3))
      .toEqual(["Due by day", "Pipeline", "Waiting for approval"]);
    const saved = JSON.parse(
      localStorage.getItem("dashboard-layout:bryan.baker@getexecutivesnow.com")!);
    expect(saved.panels.slice(0, 3)).toEqual(["due", "pipeline", "approval"]);
  });

  it("moves a tile by dragging it onto another", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Arrange" }));

    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: "", dropEffect: "" };
    fireEvent.dragStart(screen.getByTestId("slot-goals"), { dataTransfer });
    fireEvent.dragOver(screen.getByTestId("slot-tasks"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("slot-tasks"), { dataTransfer });

    const tiles = screen.getAllByTestId(/^slot-(tasks|digests|pipeline|goals)$/)
      .filter((slot) => slot.parentElement!.classList.contains("tiles"));
    expect(tiles.map((slot) => slot.dataset.testid))
      .toEqual(["slot-goals", "slot-tasks", "slot-digests", "slot-pipeline"]);
  });

  it("does not follow a tile's link while arranging", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Arrange" }));

    // The arrows are the keyboard's way; the grid itself is marked as arranging,
    // which the stylesheet uses to make the links inert.
    expect(screen.getByTestId("slot-tasks").parentElement).toHaveClass("arranging");
  });

  it("restores a saved order, and Reset layout puts it back", async () => {
    localStorage.setItem("dashboard-layout:bryan.baker@getexecutivesnow.com",
      JSON.stringify({ tiles: ["goals", "tasks", "digests", "pipeline"],
                       panels: ["clients", "due", "approval", "pipeline", "finances"] }));
    show();

    await screen.findByRole("heading", { name: "Clients" });
    expect(panelOrder()[0]).toBe("Clients");

    fireEvent.click(screen.getByRole("button", { name: "Arrange" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset layout" }));
    expect(panelOrder()[0]).toBe("Due by day");
  });

  it("adds a panel the saved order has never heard of, rather than hiding it", async () => {
    // Saved before the finances slot existed, and with one name since retired.
    localStorage.setItem("dashboard-layout:bryan.baker@getexecutivesnow.com",
      JSON.stringify({ tiles: ["tasks"], panels: ["pipeline", "retired", "due"] }));
    show();

    await screen.findByRole("heading", { name: "Practice finances" });
    expect(panelOrder()[0]).toBe("Pipeline");
    expect(screen.getByRole("link", { name: /Open goals/ })).toBeInTheDocument();
  });

  it("keeps each person's order to themselves", async () => {
    localStorage.setItem("dashboard-layout:someone.else@example.com",
      JSON.stringify({ panels: ["clients"] }));
    show();

    await screen.findByRole("heading", { name: "Clients" });
    expect(panelOrder()[0]).toBe("Due by day");
  });
});
