import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard as Board } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Dashboard } from "./Dashboard";

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
    pipeline: [{ id: "s1", contact: "c1", name: "Mike Eller",
                 pipeline: "Sales", from: "Lead", to: "Qualified lead",
                 at: "2026-09-21T10:00:00Z" }],
    clients: [
      { id: "co1", name: "Acme Facilities", open_tasks: 4, overdue: 2, open_goals: 1 },
      { id: "co2", name: "Northwind", open_tasks: 1, overdue: 0, open_goals: 2 },
    ],
    ...overrides,
  };
}

function show(board = aBoard(), me = aMe()) {
  const fetchMock = mockApi({ "GET /api/dashboard/": board });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Dashboard me={me} />, { path: "/", route: "/" });
  return fetchMock;
}

/**
 * The landing page. **One question: what needs me today** — so the tests are
 * about whether it answers that, and whether every answer leads somewhere.
 */
describe("the dashboard", () => {
  beforeEach(() => vi.unstubAllGlobals());

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

  it("shows pipeline movement with where each contact came from", async () => {
    show();

    expect(await screen.findByRole("link", { name: "Mike Eller" }))
      .toHaveAttribute("href", "/contacts/c1");
    expect(screen.getByText(/Lead →/)).toBeInTheDocument();
    expect(screen.getByText(/Qualified lead/)).toBeInTheDocument();
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
