import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoalBlock, ValueReport } from "../lib/api";
import { useLocation } from "react-router-dom";

import { aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Report, layAxis } from "./Report";

const COMPANY = "11111111-1111-4111-8111-111111111111";
const GOAL = "22222222-2222-4222-8222-222222222222";

function aBlock(overrides: Partial<GoalBlock> = {}): GoalBlock {
  return {
    id: GOAL,
    title: "Decisions stall waiting on the founder",
    client_company: COMPANY,
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

const TREE = {
  projects: [{
    ...aWorkParent({ id: "pr1", kind: "project", title: "Decision ladder",
                     status: "in_progress" }),
    tasks: [aTask({ id: "t1", title: "Publish the ladder", status: "done" }),
            aTask({ id: "t2", title: "Train the leads", status: "blocked" })],
  }],
  tasks: [aTask({ id: "t3", title: "Count this week's escalations", status: "not_started" })],
};

/** Where the app is, read from inside it: the report moves between `/report`
 *  and `/report/<goal>` without leaving the page. */
function Address() {
  return <output aria-label="address">{useLocation().pathname}</output>;
}

/** The report, with the goal in `aReport()` already open unless `route` says
 *  otherwise: most of what these tests read is inside an open goal. */
function show(report = aReport(), me = aMe(), extra: Record<string, unknown> = {},
              route = `/report/${GOAL}`) {
  const fetchMock = mockApi({
    // First: the stub takes the first route a URL starts with.
    ...extra,
    "GET /api/value-report-exports/": [],
    "GET /api/value-report/": report,
    "GET /api/companies/": [{ id: COMPANY, name: "Acme Facilities",
                              is_client_company: true }],
    "GET /api/goals/": TREE,
    "GET /api/comments/": [],
    // Again, so that a route named in both keeps the test's answer.
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<><Report me={me} /><Address /></>, { path: "/report/:id?", route });
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

  it("never prints two labels on top of each other", async () => {
    // Findings, round 1: three marks in the same week stacked their labels
    // into an unreadable pile at the right-hand end.
    const crowded = aReport({
      timeline: {
        from: "2026-07-01", to: "2026-09-21", today: "2026-09-21",
        spans: [],
        marks: ["2026-09-18", "2026-09-19", "2026-09-20", "2026-09-21"].map((at, i) => ({
          goal: GOAL, goal_title: "Decisions stall waiting on the founder",
          kind: "milestone" as const, at,
          label: `A milestone with a long name ${i}`, detail: "hit",
        })),
      },
    });
    show(crowded, aMe({ role: "FCC" }));
    const axis = await screen.findByRole("img", { name: /marks between/ });

    // Every mark is still on the axis, as its own dot...
    expect(axis.querySelectorAll(".mark")).toHaveLength(4);
    // ...and four days this close are one stack of numbers, with no word on
    // it to print over another.
    const stack = axis.querySelector(".pile")!;
    expect([...stack.querySelectorAll(".lbl.n")].map((el) => el.textContent))
      .toEqual(["1", "2", "3", "4"]);
    expect([...axis.querySelectorAll(".lbl")].filter((el) => !el.classList.contains("n")))
      .toHaveLength(0);

    // And the list underneath numbers them, so a dropped label is findable.
    expect(screen.getAllByText("1").length).toBeGreaterThan(0);
  });

  describe("marks that share a day (2026-10-07: four goals started 2026-10-06)", () => {
    const TITLES = ["Cash conversion", "Hiring bench", "Founder hours", "Vendor terms"];
    const starts = TITLES.map((title, i) => ({
      goal: `goal-${i}`, goal_title: title, kind: "start" as const,
      at: "2026-10-06", label: "", detail: "",
    }));
    const later = {
      goal: "goal-0", goal_title: "Cash conversion", kind: "milestone" as const,
      at: "2026-11-20", label: "Invoices out in 2 days", detail: "hit",
    };
    const timeline = (marks: ValueReport["timeline"]["marks"], to = "2026-11-20") => ({
      from: "2026-10-06", to, today: to, spans: [], marks,
    });

    it("stacks their numbers on the axis and keeps their labels for the list", async () => {
      const user = userEvent.setup();
      show(aReport({ timeline: timeline([...starts, later]) }), aMe({ role: "FCC" }));
      const axis = await screen.findByRole("img", { name: /5 marks between/ });

      const stacks = axis.querySelectorAll(".pile");
      expect(stacks).toHaveLength(1);
      expect([...stacks[0].querySelectorAll(".lbl.n")].map((el) => el.textContent))
        .toEqual(["1", "2", "3", "4"]);
      // None of the four titles is printed on the axis...
      for (const title of TITLES) expect(within(axis).queryByText(title)).not.toBeInTheDocument();
      // ...and the mark with a day to itself keeps its words.
      expect(within(axis).getByText("Invoices out in 2 days")).toBeInTheDocument();
      // The four dots sit on one spot, which is the truth about them.
      const lefts = [...axis.querySelectorAll<HTMLElement>(".mark")].map((el) => el.style.left);
      expect(new Set(lefts.slice(0, 4)).size).toBe(1);

      await user.click(screen.getByText("Every mark, in words"));
      const rows = [...document.querySelectorAll(".timeline-row")];
      expect(rows.map((row) => row.querySelector(".which")!.textContent)).toEqual(
        [...TITLES, "Cash conversion"]);
      expect(rows.map((row) => row.querySelector(".mark-n")!.textContent))
        .toEqual(["1", "2", "3", "4", "5"]);
    });

    it("shows the list instead of an axis when every mark is on the same day", async () => {
      show(aReport({ timeline: timeline(starts, "2026-10-06") }), aMe({ role: "FCC" }));
      const card = (await screen.findByText("The engagement, in order")).closest("section")!;

      expect(within(card).queryByRole("img")).not.toBeInTheDocument();
      expect(card.querySelector(".axis")).toBeNull();
      // Open, not behind "Every mark, in words": it is all there is.
      expect(card.querySelector("details")).toBeNull();
      for (const title of TITLES) expect(within(card).getByText(title)).toBeVisible();
      expect(card.querySelectorAll(".timeline-row")).toHaveLength(4);
    });

    it("keeps each date on one line beside its number", async () => {
      show(aReport({ timeline: timeline(starts, "2026-10-06") }), aMe({ role: "FCC" }));
      const date = (await screen.findAllByText(/2026-10-06/))[0].closest(".at")!;
      expect(date.textContent).toBe("1 2026-10-06");
      // jsdom lays nothing out; what stops the wrap is this rule.
      // @ts-expect-error — the app has no Node types; the test runner is Node.
      const { readFileSync } = await import("node:fs");
      const css: string = readFileSync("src/theme.css", "utf8");
      const rule = css.slice(css.indexOf(".timeline-row .at {"));
      expect(rule.slice(0, rule.indexOf("}"))).toMatch(/white-space: nowrap/);
    });

    it("lists a goal's same-day milestones under its own axis, by number", async () => {
      const stone = (id: string, title: string, at: string) => ({
        id, title, due_date: at, occurred_at: at, state: "hit" as const, state_label: "hit",
      });
      const block = aBlock({ milestones: [
        stone("s1", "Ladder drafted", "2026-08-01"),
        stone("s2", "Ladder published", "2026-08-01"),
        stone("s3", "First week without an escalation", "2026-09-15"),
      ] as GoalBlock["milestones"] });
      show(aReport({ current: [block] }), aMe({ role: "FCC" }));
      const axis = await screen.findByRole("img", { name: /3 marks between 2026-08-01/ });

      expect(within(axis).queryByText("Ladder drafted")).not.toBeInTheDocument();
      const legend = axis.parentElement!.querySelector(".axis-legend")!;
      expect([...legend.querySelectorAll("li")].map((li) => li.textContent)).toEqual([
        "1 Ladder drafted · hit · 2026-08-01",
        "2 Ladder published · hit · 2026-08-01",
      ]);
    });
  });

  describe("where the axis puts things (jsdom has no layout, so by position)", () => {
    const mark = (at: string, label = "A label long enough to collide") =>
      ({ at, label, detail: label, tone: "hit" as const });
    /** Half-widths, in percent of the axis: a label is 132px of roughly 900. */
    const HALF = { label: 7.5, numbers: 1.5 };

    function overlaps(from: string, to: string, ats: string[]) {
      const groups = layAxis(from, to, ats.map((at) => mark(at)));
      const clashes: string[] = [];
      for (const lane of ["above", "below"] as const) {
        const row = groups.filter((g) => g.lane === lane).sort((a, b) => a.left - b.left);
        for (let i = 1; i < row.length; i += 1) {
          const [a, b] = [row[i - 1], row[i]];
          const room = (a.showLabel ? HALF.label : HALF.numbers)
            + (b.showLabel ? HALF.label : HALF.numbers);
          if (b.left - a.left < room) clashes.push(`${lane}: ${a.left} and ${b.left}`);
        }
      }
      return clashes;
    }

    it.each([
      ["four on one day, then one", ["2026-10-06", "2026-10-06", "2026-10-06", "2026-10-06",
                                     "2026-11-20"]],
      ["a week of consecutive days", ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
                                      "2026-10-10", "2026-10-11", "2026-10-12"]],
      ["two busy days a fortnight apart", ["2026-10-06", "2026-10-06", "2026-10-20",
                                           "2026-10-20", "2026-10-20"]],
      ["evenly spread", ["2026-10-06", "2026-10-20", "2026-11-03", "2026-11-17", "2026-12-01",
                         "2026-12-15", "2026-12-29"]],
      ["a pile at each end", ["2026-10-06", "2026-10-07", "2026-12-28", "2026-12-29",
                              "2026-12-29"]],
    ])("nothing lands on its neighbour: %s", (_name, ats) => {
      expect(overlaps("2026-10-06", "2026-12-29", ats)).toEqual([]);
    });

    it("gives a same-day pair no label and a lone mark its label", () => {
      const groups = layAxis("2026-10-06", "2026-12-29",
        [mark("2026-10-06"), mark("2026-10-06"), mark("2026-12-01")]);
      expect(groups.map((g) => [g.members.map((m) => m.n), g.showLabel]))
        .toEqual([[[1, 2], false], [[3], true]]);
    });
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

describe("a goal opens in place on the report (2026-10-07)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const TITLE = "Decisions stall waiting on the founder";
  const OTHER = "33333333-3333-4333-8333-333333333333";
  const stone = (id: string, title: string, at: string) => ({
    id, title, due_date: at, occurred_at: at, state: "hit", state_label: "hit",
    is_derived: false, source_task: null,
  });
  const full = () => aBlock({
    narrative: { body: "The leads now decide routing on their own." },
    milestones: [stone("s1", "Ladder published", "2026-08-02"),
                 stone("s2", "First week without an escalation", "2026-09-15")],
    resolutions: [{ id: "r1", resolution: "changed_course", label: "Changed course",
                    reason: "The second branch mattered more.", at: "2026-09-10T12:00:00Z",
                    by: "Bryan Baker" }],
  } as Partial<GoalBlock>);
  const two = () => aReport({ current: [
    full(),
    aBlock({ id: OTHER, title: "Close the books in five days",
             headline: { kind: "outcome", text: "Month-end stops being a scramble." },
             narrative: { body: "Reconciliations are weekly now." } }),
  ] });
  const toggle = (title = TITLE) => screen.getByRole("button", { name: title });
  const address = () => screen.getByLabelText("address").textContent;

  it("is closed until it is clicked: the headline and the work done, nothing else", async () => {
    const fetchMock = show(two(), aMe({ role: "FCC" }), {}, "/report");
    expect(await screen.findByText("Decisions escalated per week")).toBeInTheDocument();

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    const bar = screen.getAllByRole("progressbar", { name: "Work completed" })[0];
    expect(bar).toHaveAttribute("aria-valuetext", "1 of 3");
    expect(screen.getAllByText(/Work completed: 1 of 3/).length).toBe(2);

    expect(screen.queryByText("The leads now decide routing on their own.")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /3 readings/ })).not.toBeInTheDocument();
    expect(screen.queryByText("The work under this goal")).not.toBeInTheDocument();
    expect(screen.queryByText("Comments")).not.toBeInTheDocument();
    // And nothing was asked for that only an open goal needs.
    expect(fetchMock.calls.some((c) => c.url.includes("/tree/"))).toBe(false);
    expect(fetchMock.calls.some((c) => c.url.startsWith("/api/comments/"))).toBe(false);
  });

  it("opens on the same page, with everything about the goal", async () => {
    const user = userEvent.setup();
    show(two(), aMe({ role: "FCC" }), {}, "/report");
    await screen.findByText("Decisions escalated per week");

    await user.click(toggle());

    // Still the report: its heading and its timeline have not gone anywhere.
    expect(screen.getByRole("heading", { name: "Where we are" })).toBeInTheDocument();
    expect(screen.getByText("The engagement, in order")).toBeInTheDocument();
    expect(address()).toBe(`/report/${GOAL}`);
    expect(toggle()).toHaveAttribute("aria-expanded", "true");

    const goal = document.getElementById(`goal-${GOAL}`)!;
    // The measurable headline and the measure...
    expect(within(goal).getByText("Decisions escalated per week")).toBeInTheDocument();
    expect(within(goal).getByRole("img", { name: /3 readings/ })).toBeInTheDocument();
    // ...the progress bar...
    expect(within(goal).getByRole("progressbar", { name: "Work completed" })).toBeInTheDocument();
    // ...the milestones timeline...
    const stones = within(goal).getByRole("img", { name: /2 marks between 2026-08-02/ });
    expect(within(stones).getByText("Ladder published")).toBeInTheDocument();
    // ...the accepted narrative...
    expect(within(goal).getByText("The leads now decide routing on their own."))
      .toBeInTheDocument();
    // ...the resolution history, reason included...
    expect(within(goal).getByText("Changed course")).toBeInTheDocument();
    expect(within(goal).getByText(/The second branch mattered more\./)).toBeInTheDocument();
    // ...and the projects and tasks beneath it, each with its status.
    const work = await within(goal).findByRole("region", { name: `Work under ${TITLE}` });
    const line = (text: string) =>
      within(work).getByRole("link", { name: text }).closest("li, p") as HTMLElement;
    expect(within(line("Decision ladder")).getByText(/In progress/)).toBeInTheDocument();
    expect(within(line("Publish the ladder")).getByText("Done")).toBeInTheDocument();
    expect(within(line("Train the leads")).getByText("Blocked")).toBeInTheDocument();
    expect(within(line("Count this week's escalations")).getByText("Not started"))
      .toBeInTheDocument();

    // The other goal stayed shut.
    expect(toggle("Close the books in five days")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Reconciliations are weekly now.")).not.toBeInTheDocument();
  });

  it("closes again on a second click, and opening another closes the first", async () => {
    const user = userEvent.setup();
    show(two(), aMe({ role: "FCC" }), {}, "/report");
    await screen.findByText("Decisions escalated per week");

    await user.click(toggle());
    await user.click(toggle("Close the books in five days"));
    expect(address()).toBe(`/report/${OTHER}`);
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Reconciliations are weekly now.")).toBeInTheDocument();

    await user.click(toggle("Close the books in five days"));
    expect(address()).toBe("/report");
    expect(screen.queryByText("Reconciliations are weekly now.")).not.toBeInTheDocument();
  });

  it("the single-goal address opens the whole report with that goal open", async () => {
    show(two(), aMe({ role: "FCC" }), {}, `/report/${OTHER}`);

    expect(await screen.findByText("Reconciliations are weekly now.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Where we are" })).toBeInTheDocument();
    expect(screen.getByText("The engagement, in order")).toBeInTheDocument();
    expect(toggle("Close the books in five days")).toHaveAttribute("aria-expanded", "true");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("says so when the address names a goal that is not on the report", async () => {
    show(two(), aMe({ role: "FCC" }), {}, "/report/44444444-4444-4444-8444-444444444444");
    expect(await screen.findByText(/That goal is not on this report/)).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("lets a client add a task on the goal, or under one of its projects", async () => {
    const user = userEvent.setup();
    const fetchMock = show(two(), aMe({ role: "FCC" }), {
      "POST /api/tasks/": () => ({ status: 201, body: aTask({ id: "t9" }) }),
    });
    const box = await screen.findByLabelText(`New task under ${TITLE}`);
    const posted = () => fetchMock.calls.filter(
      (c) => c.method === "POST" && c.url === "/api/tasks/").map((c) => c.body);

    await user.type(box, "Ask the leads what still comes to me");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    // Their company is the server's to set; they send none.
    await waitFor(() => expect(posted()).toEqual(
      [{ title: "Ask the leads what still comes to me", goal: GOAL }]));

    await waitFor(() => expect(box).toHaveValue(""));
    await user.type(box, "Shadow one decision");
    await user.selectOptions(await screen.findByLabelText("File the task under"), "pr1");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(posted()[1]).toEqual(
      { title: "Shadow one decision", project: "pr1" }));
  });

  it("lets a client comment on the goal", async () => {
    const user = userEvent.setup();
    const fetchMock = show(two(), aMe({ role: "FCC" }), {
      "POST /api/comments/": () => ({ status: 201, body: { id: "c1" } }),
    });
    await screen.findByText("Comments");
    const goal = document.getElementById(`goal-${GOAL}`)!;

    await user.type(within(goal).getByLabelText("Add a comment"),
                    "This is the one that matters most to us.");
    await user.click(within(goal).getByRole("button", { name: "Post comment" }));

    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.method === "POST" && c.url === "/api/comments/")?.body)
      .toEqual({ goal: GOAL, body: "This is the one that matters most to us." }));
  });

  it("keeps readings and resolutions the practice's, open or not", async () => {
    show(two(), aMe({ role: "FCC" }));
    await screen.findByText("The work under this goal");

    expect(screen.queryByLabelText(`Reading for ${TITLE}`)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record it" })).not.toBeInTheDocument();
    expect(screen.queryByText("Resolve this goal")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Draft the narrative/ })).not.toBeInTheDocument();
  });

  it("lets a client add a project under the goal", async () => {
    const user = userEvent.setup();
    const fetchMock = show(two(), aMe({ role: "FCC" }), {
      "POST /api/projects/": () => ({ status: 201, body: aWorkParent({ id: "pr9" }) }),
    });

    await user.type(await screen.findByLabelText(`New project under ${TITLE}`),
                    "Our own follow-ups");
    await user.click(screen.getByRole("button", { name: "Add project" }));

    // Under this goal, and no company: the server sets a client's own.
    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.method === "POST" && c.url === "/api/projects/")?.body)
      .toEqual({ title: "Our own follow-ups", goal: GOAL }));
    // The tree is asked for again, so the new project shows.
    await waitFor(() => expect(fetchMock.calls.filter(
      (c) => c.url.includes("/tree/")).length).toBeGreaterThan(1));
  });

  it("shows the server's refusal when an add is refused", async () => {
    const user = userEvent.setup();
    show(two(), aMe({ role: "FCC" }), {
      "POST /api/projects/": () => ({
        status: 400, body: { goal: ["That goal is not available to you."] } }),
    });
    await user.type(await screen.findByLabelText(`New project under ${TITLE}`), "Nope");
    await user.click(screen.getByRole("button", { name: "Add project" }));
    expect(await screen.findByText(/That goal is not available to you/)).toBeInTheDocument();
  });

  it("is the same expansion on the practice's Value report, with its controls", async () => {
    const user = userEvent.setup();
    const fetchMock = show(two(), aMe(), {
      "POST /api/tasks/": () => ({ status: 201, body: aTask({ id: "t9" }) }),
      "POST /api/projects/": () => ({ status: 201, body: aWorkParent({ id: "pr9" }) }),
    }, "/report");
    await screen.findByText("Decisions escalated per week");
    expect(screen.queryByLabelText(`Reading for ${TITLE}`)).not.toBeInTheDocument();

    await user.click(toggle());
    expect(await screen.findByText("The work under this goal")).toBeInTheDocument();
    expect(screen.getByLabelText(`Reading for ${TITLE}`)).toBeInTheDocument();
    expect(screen.getByText("Resolve this goal")).toBeInTheDocument();

    // The practice names the company; a client's is implied.
    await user.type(screen.getByLabelText(`New task under ${TITLE}`), "Review the ladder");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.method === "POST" && c.url === "/api/tasks/")?.body)
      .toEqual({ title: "Review the ladder", goal: GOAL, client_company: COMPANY }));

    await user.type(screen.getByLabelText(`New project under ${TITLE}`), "Second branch");
    await user.click(screen.getByRole("button", { name: "Add project" }));
    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.method === "POST" && c.url === "/api/projects/")?.body)
      .toEqual({ title: "Second branch", goal: GOAL, client_company: COMPANY }));
  });

  it("opens the right company's report for the practice from a link to one goal", async () => {
    const RIDGE = "55555555-5555-4555-8555-555555555555";
    const fetchMock = show(two(), aMe(), {
      [`GET /api/value-report/${GOAL}/`]: aBlock({ client_company: RIDGE }),
      "GET /api/companies/": [
        { id: COMPANY, name: "Acme Facilities", is_client_company: true },
        { id: RIDGE, name: "Ridgeline Freight", is_client_company: true },
      ],
    });
    await screen.findByText("The work under this goal");

    const asked = fetchMock.calls.map((c) => c.url)
      .filter((url) => url.startsWith("/api/value-report/?"));
    // Ridgeline's, which the goal named, and never Acme's, the first in the list.
    expect(asked).toEqual([`/api/value-report/?client_company=${RIDGE}`]);
    expect(screen.getByLabelText("Client company")).toHaveValue(RIDGE);
  });
});
