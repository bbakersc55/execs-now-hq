import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoalBlock, ValueReport } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Report } from "./Report";

const COMPANY = "11111111-1111-4111-8111-111111111111";
const GOAL = "22222222-2222-4222-8222-222222222222";

function aBlock(overrides: Partial<GoalBlock> = {}): GoalBlock {
  return {
    id: GOAL,
    title: "Decisions stall waiting on the founder",
    outcome_statement: "The founder stops being the bottleneck on day-to-day calls.",
    headline: { kind: "measure", text: "Decisions escalated per week" },
    measure: {
      kind: "numeric", kind_is_undecided: false,
      measurable: "Decisions escalated per week", unit: "per week",
      how_we_will_know: "", direction: "down_is_good",
      baseline: { value: "14.0000", at: "2026-07-01" },
      current: { value: "6.0000", at: "2026-09-18", note: "" },
      target: "4.0000", movement: "better", reading_count: 3, show_chart: true,
      series: [
        { at: "2026-07-01", value: "14.0000", is_baseline: true, note: "" },
        { at: "2026-08-15", value: "9.0000", is_baseline: false, note: "" },
        { at: "2026-09-18", value: "6.0000", is_baseline: false, note: "" },
      ],
    },
    completion: { done: 1, of: 3, percent: 33 },
    status: "in_progress", target_date: null, horizon_days: 60,
    client_owner_contact: "", is_historical: false,
    resolution: null, resolutions: [], milestones: [],
    narrative: null, source_map_row: null,
    ...overrides,
  };
}

function aReport(overrides: Partial<ValueReport> = {}): ValueReport {
  return {
    company: { id: COMPANY, name: "Acme Facilities" },
    timeline: {
      from: "2026-07-01", to: "2026-09-21", today: "2026-09-21",
      spans: [{ goal: GOAL, title: "Decisions stall waiting on the founder",
                start: "2026-07-01", end: "2026-09-21", is_historical: false }],
      marks: [
        { goal: GOAL, goal_title: "Decisions stall waiting on the founder",
          kind: "start", at: "2026-07-01", label: "", detail: "" },
        { goal: GOAL, goal_title: "Decisions stall waiting on the founder",
          kind: "milestone", at: "2026-08-02", label: "Ladder published",
          detail: "hit" },
        { goal: GOAL, goal_title: "Decisions stall waiting on the founder",
          kind: "resolution", at: "2026-09-10", label: "Changed course",
          detail: "The second branch mattered more." },
      ],
    },
    current: [aBlock()],
    historical: [],
    generated_at: "2026-09-21T12:00:00Z",
    ...overrides,
  };
}

function show(report = aReport(), me = aMe(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/value-report-exports/": [],
    "GET /api/value-report/": report,
    "GET /api/companies/": [{ id: COMPANY, name: "Acme Facilities",
                              is_client_company: true }],
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Report me={me} />, { path: "/report", route: "/report" });
  return fetchMock;
}

describe("the client value report", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("leads with the measure the server chose, and never with a percentage", async () => {
    show(aReport(), aMe({ role: "FCC" }));
    expect(await screen.findByText("Decisions escalated per week")).toBeInTheDocument();
    // The count is present and subordinate: it is not in the headline, and the
    // percentage never appears as a figure of its own.
    expect(screen.getByText(/Work completed: 1 of 3/)).toBeInTheDocument();
    expect(screen.queryByText(/33%/)).not.toBeInTheDocument();
  });

  it("leads with the outcome statement when there is no number", async () => {
    const block = aBlock({
      headline: { kind: "outcome", text: "The founder stops being the bottleneck." },
      measure: { ...aBlock().measure, kind: "none", current: null, show_chart: false,
                 how_we_will_know: "Nobody waits on a sign-off." },
      completion: { done: 4, of: 5, percent: 80 },
    });
    show(aReport({ current: [block] }), aMe({ role: "FCC" }));
    expect(await screen.findByText("The founder stops being the bottleneck."))
      .toBeInTheDocument();
    // 80% done and still not the headline.
    expect(screen.getByText(/Work completed: 4 of 5/)).toBeInTheDocument();
    expect(screen.queryByText(/80%/)).not.toBeInTheDocument();
  });

  it("shows figures instead of a chart below three readings", async () => {
    const block = aBlock();
    block.measure = { ...block.measure, reading_count: 2, show_chart: false,
                      series: block.measure.series.slice(0, 2) };
    show(aReport({ current: [block] }), aMe({ role: "FCC" }));
    expect(await screen.findByText(/2 of 3 readings/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Decisions escalated/ }))
      .not.toBeInTheDocument();
  });

  it("draws the chart at three, with the baseline as one of the points", async () => {
    show(aReport(), aMe({ role: "FCC" }));
    const chart = await screen.findByRole("img", { name: /3 readings/ });
    expect(chart.querySelectorAll("circle")).toHaveLength(3);
  });

  it("opens with the engagement timeline across every goal", async () => {
    const user = userEvent.setup();
    show(aReport(), aMe({ role: "FCC" }));
    const timeline = (await screen.findByText("The engagement, in order"))
      .closest("section")!;

    // One horizontal axis, with every mark on it (design brief, Tier 1).
    const axis = within(timeline).getByRole("img", { name: /marks between/ });
    expect(axis.querySelectorAll(".mark")).toHaveLength(3);
    expect(within(axis).getByTitle(/Ladder published/)).toBeInTheDocument();

    // And the words underneath, for reading rather than scanning.
    await user.click(within(timeline).getByText("Every mark, in words"));
    expect(within(timeline).getAllByText("Changed course").length).toBeGreaterThan(0);
    // Ruling G — the client reads the reason.
    expect(within(timeline).getByText(/The second branch mattered more./))
      .toBeInTheDocument();
  });

  it("keeps the timeline off a single goal's page", async () => {
    const fetchMock = mockApi({ "GET /api/value-report/": aBlock() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Report me={aMe({ role: "FCC" })} />,
                { path: "/report/:id", route: `/report/${GOAL}` });
    expect(await screen.findByText("Decisions escalated per week")).toBeInTheDocument();
    expect(screen.queryByText("The engagement, in order")).not.toBeInTheDocument();
  });

  it("gives a client no controls, no nudge and no draft", async () => {
    const block = aBlock({
      measure: { ...aBlock().measure, kind_is_undecided: true },
      // A client's payload never carries the draft at all; this asserts the
      // screen does not invent one from an accepted narrative either.
      narrative: { body: "The routes are moving." },
    });
    show(aReport({ current: [block] }), aMe({ role: "FCC" }));
    expect(await screen.findByText("The routes are moving.")).toBeInTheDocument();
    expect(screen.queryByText(/Nobody has said how we will know/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Draft the narrative/ }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("The quarterly PDF")).not.toBeInTheDocument();
  });

  it("nudges the practice when nobody has chosen a kind", async () => {
    const block = aBlock({ measure: { ...aBlock().measure, kind_is_undecided: true } });
    show(aReport({ current: [block] }), aMe());
    expect(await screen.findByText(/Nobody has said how we will know this worked/))
      .toBeInTheDocument();
  });

  it("records a reading and asks the server for the goal it belongs to", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aReport(), aMe(), {
      "POST /api/goal-measurements/": { id: "m1" },
    });
    const box = await screen.findByLabelText(
      "Reading for Decisions stall waiting on the founder");
    await user.type(box, "5");
    await user.click(screen.getByRole("button", { name: "Record it" }));
    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url === "/api/goal-measurements/");
      expect(posted?.body).toEqual({ goal: GOAL, value: "5" });
    });
  });

  it("will not resolve a goal without a reason", async () => {
    const user = userEvent.setup();
    show(aReport(), aMe());
    await user.click(await screen.findByText("Resolve this goal"));
    const record = screen.getByRole("button", { name: "Record the resolution" });
    expect(record).toBeDisabled();
    await user.type(screen.getByLabelText(
      "Reason for Decisions stall waiting on the founder"), "It regressed.");
    expect(record).toBeEnabled();
  });

  it("shows a VA the draft and not the button that publishes it", async () => {
    const block = aBlock({
      narrative: { body: "", proposed_body: "Claude's account.", state: "proposed" },
    });
    show(aReport({ current: [block] }), aMe({ role: "VA" }));
    expect(await screen.findByText("Claude's account.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Draft the narrative/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Publish it to the client/ }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("Resolve this goal")).not.toBeInTheDocument();
  });
});
