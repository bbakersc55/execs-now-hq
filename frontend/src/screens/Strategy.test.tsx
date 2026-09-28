import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreCallForm, StrategySessionRow } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PreCallForm as PreCall } from "./PreCallForm";
import { SessionDetail } from "./SessionDetail";
import { SessionTemplate } from "./SessionTemplate";
import { Sessions } from "./Sessions";

const TOKEN = "a-public-token";
const SESSION_ID = "11111111-2222-4333-8444-555555555555";

const TEMPLATES = [{
  id: "t1", name: "Operations — strategy session", discipline: "operations", version: 1,
  is_default: true, archived_at: null as string | null, sessions: 1,
  sections: [{ code: "diagnostic", title: "Diagnostic", position: 3,
               time_budget_minutes: 25, questions: [
    { key: "s4_done_right", prompt: "How do you know a site was done right?",
      prompt_template: "How do you know a site was done right?", ask_when: "live" as const,
      must_ask: true, area: "Operations & quality",
      response_schema: "diagnostic_triple" as const, is_fractional_observation: false,
      has_fractional_note: true, is_financial: false, position: 0 },
  ]}],
}];

function aForm(overrides: Partial<PreCallForm> = {}): PreCallForm {
  return {
    practice: "Executives Now", company: "Acme Facilities", first_name: "Dana",
    answered: 0, of: 2, complete: false,
    sections: [
      { code: "snapshot", title: "Snapshot: where they are today", scale: "",
        questions: [
          { key: "s1_revenue", prompt: "Revenue — last year / this year",
            response_schema: "free_text", value: null },
        ]},
      { code: "six_key_components", title: "Six Key Components: self-rating",
        scale: "Rate each one from 1 to 10 — 1 means not true today, 10 means "
          + "completely true.",
        questions: [
          { key: "s2_vision", prompt: "Vision — Our 3-year picture is clear, written "
            + "down, and shared by the whole leadership team.",
            response_schema: "rating_1_10", value: null },
        ]},
    ],
    ...overrides,
  };
}

function aSession(overrides: Partial<StrategySessionRow> = {}): StrategySessionRow {
  return {
    id: SESSION_ID, state: "in_call",
    template: { id: "t1", name: "Operations — strategy session" },
    contact: { id: "c1", name: "Dana Reyes" },
    company: { id: "co1", name: "Acme Facilities" },
    visionary: null, integrator: null, owner: "Bryan Baker",
    scheduled_at: null, started_at: "2026-09-18T12:00:00Z", budget_minutes: 70,
    current_section: "", current_section_at: null,
    precall_sent: true, precall_expires_at: "2026-10-18T14:00:00Z",
    precall_questions_sent_at: null,
    prep: null,
    pinned_questions: [],
    fractional_note: "",
    precall_default_intro: "Hi Dana,\n\nAhead of our session, here are a few questions.",
    mirror: { goal: "", unlocks: "" },
    proposed_mirror: { goal: "Two branches by spring.", unlocks: "Supervisor cover." },
    pdf_include_flags: { fractional_notes: false, mechanics: false,
                         diagnostic_observations: false, alignment_observation: false,
                         investment: false },
    has_pdf: false, converted_at: null, created_at: "2026-09-18T12:00:00Z",
    sections: [
      { code: "diagnostic", title: "Diagnostic: where it's breaking", position: 3,
        time_budget_minutes: 25, questions: [
          { key: "s4_done_right", prompt: "How do you know a site was done right?",
            ask_when: "live", must_ask: true, area: "Operations & quality",
            response_schema: "diagnostic_triple", is_fractional_observation: false,
            has_fractional_note: true, is_financial: false, position: 0 },
        ]},
      { code: "six_key_components", title: "Six Key Components: self-rating",
        position: 1, time_budget_minutes: null, questions: [
          { key: "s2_data", prompt: "Data", ask_when: "precall", must_ask: false,
            area: "", response_schema: "rating_1_10", is_fractional_observation: false,
            has_fractional_note: false, is_financial: false, position: 2 },
        ]},
      { code: "mirror", title: "The mirror", position: 4, time_budget_minutes: 5,
        questions: [] },
      { code: "two_paths", title: "Two paths", position: 6, time_budget_minutes: 5,
        questions: [] },
      { code: "strategy_map", title: "Strategy Map", position: 5,
        time_budget_minutes: 15, questions: [] },
    ],
    answers: [
      { question_key: "s2_data", value: { rating: 3, comment: "We rewrote the "
        + "dashboard in March and nobody has opened it since." },
        fractional_note: "", answered_by: "prospect",
        updated_at: "2026-09-19T11:00:00Z" },
    ],
    map_rows: [
      { id: "r1", position: 0, bottleneck: "Supervisor overload", root_cause: "14 sites",
        the_fix: "Area lead per 8", owner_text: "Integrator", horizon: 60,
        measurable: "Inspections per site", mechanics_note: "", state: "proposed",
        converted_to: "", from_ai: true },
    ],
    six_key_components: {
      scores: [
        { key: "s2_vision", rating: 8, comment: "", answered_by: "prospect" },
        { key: "s2_data", rating: 3, comment: "We rewrote the dashboard in March "
          + "and nobody has opened it since.", answered_by: "prospect" },
      ],
      ratings: { s2_vision: 8, s2_data: 3 }, answered: 2, of: 6,
      average: 5.5, complete: false, lowest: null },
    path_notes: [
      { id: "p1", path: "a", kind: "con", text: "It waits behind the day job.",
        position: 0, state: "proposed", from_ai: true },
      { id: "p2", path: "b", kind: "pro", text: "Someone owns the list on Monday.",
        position: 0, state: "accepted", from_ai: true },
    ],
    must_ask: { outstanding: ["s4_done_right"], answered: 0, of: 7 },
    ...overrides,
  };
}

function showSession(session = aSession(), me = aMe(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: [] },
    "GET /api/strategy-sessions/": session,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<SessionDetail me={me} />, { path: "/strategy/:id",
                                           route: `/strategy/${SESSION_ID}` });
  return fetchMock;
}

describe("the pre-call form", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("needs no sign-in and shows only the pre-call questions", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET /api/strategy/precall/${TOKEN}`]: aForm() }));
    renderRoute(<PreCall />, { path: "/strategy/precall/:token",
                               route: `/strategy/precall/${TOKEN}` });
    expect(await screen.findByText(/Revenue — last year/)).toBeInTheDocument();
    expect(screen.getByText(/Executives Now/)).toBeInTheDocument();
    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();
  });

  it("says the scale once, above the six, and leads each with its component", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET /api/strategy/precall/${TOKEN}`]: aForm() }));
    renderRoute(<PreCall />, { path: "/strategy/precall/:token",
                               route: `/strategy/precall/${TOKEN}` });
    expect(await screen.findByText(/1 means not true today, 10 means completely true/))
      .toBeInTheDocument();
    expect(screen.getAllByText(/not true today/)).toHaveLength(1);
    expect(screen.getByRole("combobox", { name: /^Vision — Our 3-year picture is clear/ }))
      .toBeInTheDocument();
  });

  it("saves an answer as soon as the field is left, with no submit", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      [`POST /api/strategy/precall/${TOKEN}`]: {
        saved_at: "2026-09-18T18:00:00Z", answered: 1, of: 2 },
      [`GET /api/strategy/precall/${TOKEN}`]: aForm(),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PreCall />, { path: "/strategy/precall/:token",
                               route: `/strategy/precall/${TOKEN}` });

    const box = await screen.findByLabelText(/Revenue — last year/);
    await user.type(box, "4.2m then 5.1m");
    await user.tab();
    await waitFor(() => expect(screen.getByText("1 of 2 answered")).toBeInTheDocument());
    const posted = fetchMock.calls.find((c) => c.method === "POST");
    expect(posted?.body).toEqual({ question_key: "s1_revenue",
                                   value: { text: "4.2m then 5.1m" } });
    expect(screen.getByText(/Saved at/)).toBeInTheDocument();
  });

  it("comes back with what was already answered", async () => {
    const resumed = aForm({ answered: 1 });
    resumed.sections[0].questions[0].value = { text: "4.2m then 5.1m" };
    vi.stubGlobal("fetch", mockApi({ [`GET /api/strategy/precall/${TOKEN}`]: resumed }));
    renderRoute(<PreCall />, { path: "/strategy/precall/:token",
                               route: `/strategy/precall/${TOKEN}` });
    expect(await screen.findByLabelText(/Revenue — last year/)).toHaveValue("4.2m then 5.1m");
    expect(screen.getByText("1 of 2 answered")).toBeInTheDocument();
  });
});

describe("the live session view", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("counts the must-asks and shows each section's budget", async () => {
    showSession();
    // Exact: the call clock's "N of 70 min" can contain "0 of 7" too.
    expect(await screen.findByText("0 of 7")).toBeInTheDocument();
    expect(screen.getByText("25 min")).toBeInTheDocument();
    expect(screen.getByText("must ask")).toBeInTheDocument();
  });

  it("keeps a drafted row in the tray until someone accepts it", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      "POST /api/strategy-map-rows/r1/accept/": {},
    });
    expect(await screen.findByText(/Tray — 1 proposed rows/)).toBeInTheDocument();
    expect(screen.getByText(/The map — 0 rows/)).toBeInTheDocument();
    // The worked example stands in for an empty map — industry-neutral.
    expect(screen.getByText(/Owner is the bottleneck on approvals/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url.endsWith("/r1/accept/"))).toBe(true));
  });

  it("shows Claude's mirror as a draft, with the saved mirror still empty", async () => {
    showSession();
    expect(await screen.findByText(/Claude's draft, not saved/)).toBeInTheDocument();
    expect(screen.getByText("Two branches by spring.")).toBeInTheDocument();
    expect(screen.getByLabelText("Their goal")).toHaveValue("");
  });

  it("names no lowest score while the six are half answered", async () => {
    showSession();
    expect(await screen.findByText(/2 of 6 rated/)).toBeInTheDocument();
    expect(screen.queryByText("Look here first")).not.toBeInTheDocument();
  });

  it("leaves every PDF switch off and says what turning one on does", async () => {
    showSession();
    const mechanics = await screen.findByLabelText("Notes / mechanics from experience");
    expect(mechanics).not.toBeChecked();
    expect(screen.getByLabelText("§9 — scope and investment")).not.toBeChecked();
    expect(screen.getByText(/Generating is not sending/)).toBeInTheDocument();
  });

  it("matrix §10 — a VA reads the session and cannot run it", async () => {
    showSession(aSession(), aMe({ role: "VA" }));
    expect(await screen.findByText(/Running the call, drafting, sending/))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Draft rows with Claude/ }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("The PDF")).not.toBeInTheDocument();
    expect(screen.queryByText("Convert to work")).not.toBeInTheDocument();
    // It can still send the form — that is matrix 10.3.
    expect(screen.getByRole("button", { name: /Send the form again/ })).toBeInTheDocument();
  });
});

describe("per-section pacing", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("starts a section's clock from its own control, not by navigating", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`PATCH /api/strategy-sessions/${SESSION_ID}/`]: aSession(),
    });
    // The rail navigates and touches nothing — the owner's ruling, so that
    // reading ahead mid-call cannot move the pacing under you.
    const rail = await screen.findByRole("navigation", { name: "Sections" });
    await user.click(within(rail).getByRole("button", { name: /Diagnostic/ }));
    expect(fetchMock.calls.some((c) => c.method === "PATCH")).toBe(false);

    await user.click(screen.getByRole("button", { name: /^Start Diagnostic/ }));
    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(patched?.body).toEqual({ current_section: "diagnostic" });
    });
  });

  it("counts the current section against its own budget", async () => {
    const twelveMinutesAgo = new Date(Date.now() - 12 * 60_000).toISOString();
    showSession(aSession({ current_section: "diagnostic",
                           current_section_at: twelveMinutesAgo }));
    // On the section's own pill, and again on the call clock at the top.
    expect(await screen.findAllByText("12 of 25 min")).toHaveLength(2);
    // The sections not being run show their budget and nothing else.
    expect(screen.getByText("15 min")).toBeInTheDocument();
  });

  it("flags a section that has run over", async () => {
    const longAgo = new Date(Date.now() - 40 * 60_000).toISOString();
    showSession(aSession({ current_section: "diagnostic", current_section_at: longAgo }));
    const [clock, pill] = await screen.findAllByText("40 of 25 min");
    expect(pill).toHaveClass("warn");
    expect(clock).toHaveClass("over");
  });

  it("always shows the call clock, before and during the call", async () => {
    showSession(aSession({ started_at: null }));
    const clock = await screen.findByRole("status", { name: "Call clock" });
    expect(clock).toHaveTextContent(/Call not started · 70 min planned/);
  });

  it("times the call against the template's total once it has started", async () => {
    const tenAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    showSession(aSession({ started_at: tenAgo, current_section: "diagnostic",
                           current_section_at: tenAgo }));
    const clock = await screen.findByRole("status", { name: "Call clock" });
    expect(clock).toHaveTextContent("Call 10 of 70 min");
    expect(clock).toHaveTextContent(/Diagnostic: where it's breaking 10 of 25 min/);
  });

  it("gives a pre-call section no Start control, and every live one a Start", async () => {
    showSession(aSession());
    await screen.findByRole("button", { name: /^Start Diagnostic/ });
    // Six Key Components is all pre-call questions: answered before the call.
    expect(screen.queryByRole("button", { name: /^Start Six Key Components/ }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Start The mirror/ })).toBeInTheDocument();
  });
});

describe("the template editor", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const TEMPLATE = {
    id: "t1", name: "Operations — strategy session", discipline: "operations",
    version: 1, is_default: true,
    sections: [{ code: "diagnostic", title: "Diagnostic", position: 3,
                 time_budget_minutes: 25, questions: [
      { key: "s4_done_right", prompt: "How do you know a site was done right?",
        prompt_template: "How do you know a site was done right?", ask_when: "live",
        must_ask: true, area: "Operations & quality",
        response_schema: "diagnostic_triple", is_fractional_observation: false,
        has_fractional_note: true, is_financial: false, position: 0 },
    ]}],
  };

  it("edits wording, when it is asked, and must-ask — and says what it cannot touch",
     async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/strategy-templates/t1/": { changed: ["s4_done_right"] },
      "GET /api/strategy-templates/": [TEMPLATE],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SessionTemplate me={aMe()} />);

    const box = await screen.findByLabelText("Wording of s4_done_right");
    await user.clear(box);
    await user.type(box, "How do you know last night went well?");
    await user.selectOptions(screen.getByLabelText("When to ask s4_done_right"),
                             "precall");
    await user.click(screen.getByRole("button", { name: /Save 1 change/ }));

    await waitFor(() => expect(screen.getByText(/Sessions already under way are untouched/))
      .toBeInTheDocument());
    const patched = fetchMock.calls.find((c) => c.method === "PATCH");
    expect(patched?.body).toEqual({ questions: [{ key: "s4_done_right",
      prompt: "How do you know last night went well?", ask_when: "precall" }],
      sections: [] });
  });

  it("is the founder fractional's alone", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/strategy-templates/": [TEMPLATE] }));
    renderRoute(<SessionTemplate me={aMe({ role: "CF" })} />);
    expect(await screen.findByText(/founder fractional's to edit/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Wording of s4_done_right")).not.toBeInTheDocument();
  });
});

describe("the emailed link, walked end to end", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // The 2026-09-19 bug. Every test above rendered PreCallForm inside a route
  // that already named `:token`, so `useParams()` always had one — which is
  // exactly the blind spot. This one starts where a prospect starts: the URL
  // out of the email, through the real App, with nothing pre-matched.
  it("opens the URL from the email and asks the server for THAT token", async () => {
    const { App } = await import("../App");
    const token = "plnK7MG8F044F0i8-KblbBQMQEvX5WkvdRhVI01QiKI";
    const fetchMock = mockApi({ [`GET /api/strategy/precall/${token}`]: aForm() });
    vi.stubGlobal("fetch", fetchMock);

    renderRoute(<App />, { path: "*", route: `/strategy/precall/${token}` });

    expect(await screen.findByText(/Revenue — last year/)).toBeInTheDocument();
    const asked = fetchMock.calls.map((c) => c.url);
    expect(asked).toContain(`/api/strategy/precall/${token}`);
    expect(asked.some((url) => url.includes("undefined"))).toBe(false);
    // And no sign-in was attempted on the way: this page has no session.
    expect(asked.some((url) => url.includes("/api/me"))).toBe(false);
  });

  it("does the same for the cadence link, which had the same shape", async () => {
    const { App } = await import("../App");
    const token = "a-stakeholder-token";
    const fetchMock = mockApi({ [`GET /api/cadence/${token}`]: {
      practice: "Executives Now", name: "Dana Reyes", cadence: "weekly",
      is_muted: false, choices: [{ value: "weekly", label: "Weekly" }] } });
    vi.stubGlobal("fetch", fetchMock);

    renderRoute(<App />, { path: "*", route: `/updates/${token}` });

    await waitFor(() => expect(fetchMock.calls.map((c) => c.url))
      .toContain(`/api/cadence/${token}`));
  });
});

describe("answers the prospect already gave", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // The 2026-09-19 dry run: all six self-ratings answered on the form, and the
  // live view showed six empty dropdowns under an otherwise correct summary.
  it("shows a self-rating as answered, not as a blank dropdown", async () => {
    showSession();
    const field = await screen.findByLabelText("Data");
    expect(field).toHaveValue("3");
    expect(screen.getAllByText("from the form").length).toBeGreaterThan(0);
  });

  it("keeps the prospect's comment beside the rating, and on saving it", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/answers/`]: {
        answer: { question_key: "s2_data", value: { rating: 5, comment: "x" },
                  fractional_note: "", answered_by: "fractional",
                  updated_at: "2026-09-19T12:00:00Z" },
        six_key_components: { scores: [], ratings: {}, answered: 0, of: 6,
                              average: null, complete: false, lowest: null },
        drafted: [] },
    });
    expect(await screen.findByLabelText("Data — comment"))
      .toHaveValue("We rewrote the dashboard in March and nobody has opened it since.");

    await user.selectOptions(screen.getByLabelText("Data"), "5");
    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.method === "POST");
      // Changing the number must not delete the sentence that explains it.
      expect(posted?.body).toEqual({ question_key: "s2_data", fractional_note: "",
        value: { rating: 5, comment: "We rewrote the dashboard in March and "
          + "nobody has opened it since." } });
    });
  });

  it("puts each comment beside its rating in the summary", async () => {
    showSession();
    expect(await screen.findByText(/We rewrote the dashboard in March/))
      .toBeInTheDocument();
  });
});

describe("converting a session into work, from the page the owner opens", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // Check 5, 2026-09-21. "Create the work" appeared to do nothing: the server
  // refused every press — nine measurables with no baseline, and "Leave it out"
  // a word it did not know — and drew the refusal in the page banner, three
  // screens above the button. Every test above rendered ConvertCard's screen on
  // a pre-matched route with an empty preview, so none of them ever pressed it.
  const ROWS = [
    { row: "r1", position: 0, title: "Decisions stall waiting on Noble",
      the_fix: "Publish a decision list", root_cause: "No one else may decide",
      owner_text: "Noble Baker",
      client_owner_contact: { id: "c9", name: "Noble Baker" },
      measurable: "Decisions escalated per week", horizon: 30,
      target_date: "2026-10-21", suggested: "goal" as const, needs_baseline: true },
    { row: "r2", position: 1, title: "Recruiting has no owner", the_fix: "Name one",
      root_cause: "Donna does it between jobs", owner_text: "Donna",
      client_owner_contact: null, measurable: "Days to fill an open role",
      horizon: 60, target_date: "2026-11-20", suggested: "goal" as const,
      needs_baseline: true },
    { row: "r3", position: 2, title: "Margin is a blended average",
      the_fix: "Report per site", root_cause: "One ledger", owner_text: "",
      client_owner_contact: null, measurable: "", horizon: 90,
      target_date: "2026-12-20", suggested: "goal" as const, needs_baseline: false },
  ];

  /** The whole app, at the session's own URL, with nothing pre-matched. */
  async function openTheSession(convertRoute: unknown) {
    const { App } = await import("../App");
    const fetchMock = mockApi({
      "GET /api/me": aMe(),
      "GET /api/branding": { display_name: "Executives Now",
                             product_name: "Execs NOW HQ", palette: null },
      [`POST /api/strategy-sessions/${SESSION_ID}/convert/`]: convertRoute,
      [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: ROWS },
      "GET /api/strategy-sessions/": aSession({ state: "complete" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<App />, { path: "*", route: `/strategy/${SESSION_ID}` });
    await screen.findByText("Convert to work");
    // The card draws before its preview lands; the rows are the preview.
    await screen.findByLabelText(`Convert ${ROWS[0].title} as`);
    return fetchMock;
  }

  const theCard = () => screen.getByText("Convert to work").closest("section")!;

  it("chooses per row, takes the baselines, and sends what was chosen", async () => {
    const user = userEvent.setup();
    const fetchMock = await openTheSession({ created: [
      { as: "goal", title: "Decisions stall waiting on Noble" },
      { as: "project", title: "Recruiting has no owner" }] });

    // What the press will do, before it is pressed.
    expect(screen.getByText(/Creates 3 goals and 0 projects/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Baseline for Decisions stall waiting on Noble"),
                    "7");
    await user.type(screen.getByLabelText("Target for Decisions stall waiting on Noble"),
                    "2");
    await user.selectOptions(screen.getByLabelText("Convert Recruiting has no owner as"),
                             "project");
    await user.selectOptions(
      screen.getByLabelText("Convert Margin is a blended average as"), "skip");
    expect(screen.getByText(/Creates 1 goal and 1 project, leaving 1 out/))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create the work" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/convert/"));
      expect(posted?.body).toEqual({ choices: {
        r1: { as: "goal", baseline_value: "7", target_value: "2" },
        r2: { as: "project" },
        r3: { as: "skip" },
      }});
    });
  });

  it("ticks 'not measured yet' instead of a baseline, and says so", async () => {
    const user = userEvent.setup();
    const fetchMock = await openTheSession({ created: [] });

    await user.type(screen.getByLabelText("Baseline for Recruiting has no owner"), "9");
    await user.click(screen.getByLabelText("Not measured yet — Recruiting has no owner"));
    // The reading it replaces goes with it, rather than being sent alongside.
    expect(screen.getByLabelText("Baseline for Recruiting has no owner"))
      .toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Create the work" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/convert/"));
      expect((posted?.body as { choices: Record<string, unknown> }).choices.r2)
        .toEqual({ as: "goal", baseline_unknown: true, baseline_value: "",
                   target_value: "" });
    });
  });

  it("shows the refusal in the card, beside the button that caused it", async () => {
    const user = userEvent.setup();
    await openTheSession(() => ({ status: 400, body: {
      detail: "2 rows are not ready to convert — \"Decisions stall waiting on Noble\", "
        + "\"Recruiting has no owner\". Each one needs a baseline before the "
        + "engagement starts, or an explicit \"not measured yet\".",
      rows: ["r1", "r2"] } }));

    await user.click(screen.getByRole("button", { name: "Create the work" }));

    const card = theCard();
    await waitFor(() => expect(card).toHaveTextContent(/2 rows are not ready to convert/));
    // And the rows it named are marked where they are, not only at the top.
    expect(screen.getAllByText("not ready")).toHaveLength(2);
  });

  it("will not press when every row is left out", async () => {
    const user = userEvent.setup();
    await openTheSession({ created: [] });
    for (const row of ROWS) {
      await user.selectOptions(screen.getByLabelText(`Convert ${row.title} as`), "skip");
    }
    expect(screen.getByRole("button", { name: "Create the work" })).toBeDisabled();
    expect(screen.getByText(/Every row is left out/)).toBeInTheDocument();
  });
});


describe("the decision page's pros and cons", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // Owner, 2026-09-21. The same tray the map rows get, for the same reason:
  // Claude proposes, the fractional disposes, and nothing reaches the
  // prospect's PDF until someone accepts it.
  it("keeps a drafted pro or con in the tray until someone accepts it", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      "POST /api/strategy-path-notes/p1/accept/": {},
    });
    expect(await screen.findByText("It waits behind the day job.")).toBeInTheDocument();
    // The accepted one is already in its column, not in the tray.
    expect(screen.getByText("Someone owns the list on Monday.")).toBeInTheDocument();

    expect(screen.getByText(/Tray — 1 proposed for the two paths/)).toBeInTheDocument();

    await user.click(screen.getByRole(
      "button", { name: 'Accept "It waits behind the day job."' }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url === "/api/strategy-path-notes/p1/accept/")).toBe(true));
  });

  it("asks Claude for them on the button, and says nothing is published", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/draft-paths/`]: { drafted: [] },
    });
    await user.click(await screen.findByRole("button",
                                             { name: /Draft pros and cons with Claude/ }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url.endsWith("/draft-paths/"))).toBe(true));
    expect(screen.getByText(/Nothing reaches the PDF until you accept it/))
      .toBeInTheDocument();
  });

  it("matrix §10 — a VA sees them and cannot accept one", async () => {
    showSession(aSession(), aMe({ role: "VA" }));
    expect(await screen.findByText("It waits behind the day job.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Draft pros and cons/ }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Accept "/ })).not.toBeInTheDocument();
  });
});


describe("the questions by email", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // Owner, 2026-09-21. The path for a prospect who will not click a link.
  it("offers the intro, then sends it from the fractional's own address", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/send-questions/`]:
        { from_address: "bryan@getexecutivesnow.test" },
    });
    await user.click(await screen.findByRole(
      "button", { name: /Or email the questions instead/ }));

    const intro = screen.getByLabelText("Intro to the questions email");
    expect(intro).toHaveValue(
      "Hi Dana,\n\nAhead of our session, here are a few questions.");
    await user.clear(intro);
    await user.type(intro, "Hi Dana, a few questions before Thursday.");
    await user.click(screen.getByRole("button", { name: "Send the questions" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/send-questions/"));
      expect(posted?.body).toEqual({ intro: "Hi Dana, a few questions before Thursday." });
    });
    expect(await screen.findByText(/on their way from bryan@getexecutivesnow.test/))
      .toBeInTheDocument();
  });

  it("marks a pre-call answer typed in after the questions were emailed", async () => {
    showSession(aSession({ precall_questions_sent_at: "2026-09-21T10:00:00Z" }));
    // `s2_data` is a pre-call question whose answer the fixture has as the
    // prospect's: still theirs, still "from the form".
    expect(await screen.findByText("from the form")).toBeInTheDocument();
    expect(screen.getByText(/questions emailed/)).toBeInTheDocument();
  });

  it("matrix 10.3a — a VA may send the link and not the questions", async () => {
    showSession(aSession(), aMe({ role: "VA" }));
    expect(await screen.findByRole("button", { name: /Send the form again/ }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /email the questions/i }))
      .not.toBeInTheDocument();
  });
});


describe("session prep", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const PREP = {
    id: "prep1", state: "ready" as const,
    website_url: "https://acme.invalid", notes: "Donna runs hiring.",
    summary: "Their site says they clean commercial kitchens.",
    bottlenecks: ["Likely dispatch runs through one person"],
    rewordings: [{ key: "s1_revenue", current: "Revenue — last year / this year",
                   suggested: "Revenue last year and this — contract versus one-off",
                   why: "Their site says contracts are the bulk of it." }],
    questions: [
      { id: "q1", text: "Who decides a crew is short on the day?", why: "Likely it.",
        position: 0, is_pinned: false, note: "" },
    ],
    web_searches: 3,
  };

  it("asks for the site and what you know, then keeps the brief", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/prepare/`]: PREP,
    });
    await user.type(await screen.findByLabelText("Their website"), "https://acme.invalid");
    await user.type(screen.getByLabelText("What you already know"), "Donna runs hiring.");
    await user.click(screen.getByRole("button", { name: "Prepare" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/prepare/"));
      expect(posted?.body).toEqual({ website_url: "https://acme.invalid",
                                     notes: "Donna runs hiring." });
    });
    expect(await screen.findByText(/3 searches/)).toBeInTheDocument();
  });

  it("shows a rewording beside today's wording, editable before it is applied", async () => {
    showSession(aSession({ prep: PREP }), aMe());
    expect(await screen.findByText(/Their site says they clean commercial kitchens/))
      .toBeInTheDocument();
    expect(screen.getByText(/Revenue — last year \/ this year/)).toBeInTheDocument();
    // The suggestion is a box, because the fractional simplifies a few first.
    expect(screen.getByLabelText("Suggested wording for s1_revenue"))
      .toHaveValue("Revenue last year and this — contract versus one-off");
    // Nothing is selected, so nothing can be applied yet.
    expect(screen.getByRole("button", { name: /Apply .*selected/ })).toBeDisabled();
  });

  it("applies a selection in one step, carrying the edits", async () => {
    const user = userEvent.setup();
    const two = {
      ...PREP,
      rewordings: [
        PREP.rewordings[0],
        { key: "s1_sites", current: "Active customer sites (or active accounts)",
          suggested: "How many kitchens are you in each week?", why: "" },
      ],
    };
    const fetchMock = showSession(aSession({ prep: two }), aMe(), {
      [`PATCH /api/strategy-sessions/${SESSION_ID}/prep-rewordings/`]: two,
    });

    // Simplify one, tick both, apply once.
    const box = await screen.findByLabelText("Suggested wording for s1_revenue");
    await user.clear(box);
    await user.type(box, "Revenue last year and this");
    await user.click(screen.getByLabelText("Apply the rewording of s1_revenue"));
    await user.click(screen.getByLabelText("Apply the rewording of s1_sites"));
    await user.click(screen.getByRole("button", { name: "Apply 2 selected to the template" }));

    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.url.endsWith("/prep-rewordings/"));
      // The fractional's version travels, not the one Claude wrote.
      expect(patched?.body).toEqual({ rewordings: [
        { key: "s1_revenue", suggested: "Revenue last year and this" },
        { key: "s1_sites", suggested: "How many kitchens are you in each week?" },
      ]});
    });
  });

  it("ticks all, then unticks one, before applying", async () => {
    const user = userEvent.setup();
    const three = { ...PREP, rewordings: [
      PREP.rewordings[0],
      { key: "s1_sites", current: "Sites", suggested: "Kitchens a week", why: "" },
      { key: "s1_team", current: "Team", suggested: "Crew size", why: "" },
    ]};
    const fetchMock = showSession(aSession({ prep: three }), aMe(), {
      [`PATCH /api/strategy-sessions/${SESSION_ID}/prep-rewordings/`]: three,
    });
    await user.click(await screen.findByLabelText("Tick all rewordings"));
    expect(screen.getByRole("button", { name: "Apply 3 selected to the template" }))
      .toBeEnabled();
    await user.click(screen.getByLabelText("Apply the rewording of s1_sites"));
    expect(screen.getByLabelText("Tick all rewordings")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Apply 2 selected to the template" }));
    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.url.endsWith("/prep-rewordings/"));
      expect((patched?.body as { rewordings: { key: string }[] }).rewordings
        .map((r) => r.key)).toEqual(["s1_revenue", "s1_team"]);
    });
    // And unticking all clears it.
    await user.click(screen.getByLabelText("Tick all rewordings"));
    await user.click(screen.getByLabelText("Tick all rewordings"));
    expect(screen.getByRole("button", { name: /Apply .*selected/ })).toBeDisabled();
  });

  it("still copies one on its own", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession({ prep: PREP }), aMe(), {
      [`PATCH /api/strategy-sessions/${SESSION_ID}/prep-rewordings/`]: PREP,
    });
    await user.click(await screen.findByRole("button",
                                             { name: "Copy this one to the editor" }));
    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.url.endsWith("/prep-rewordings/"));
      expect((patched?.body as { rewordings: { key: string }[] }).rewordings)
        .toHaveLength(1);
    });
  });

  it("asks which template when there is more than one, this session's first",
     async () => {
    const user = userEvent.setup();
    const templates = [
      { ...TEMPLATES[0], id: "t-default", name: "Operations — generic", is_default: true },
      { ...TEMPLATES[0], id: "t1", name: "Grime Fighters (Brett Murray)",
        is_default: false },
    ];
    const fetchMock = mockApi({
      [`PATCH /api/strategy-sessions/${SESSION_ID}/prep-rewordings/`]: PREP,
      "GET /api/strategy-templates/": templates,
      [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: [] },
      "GET /api/strategy-sessions/": aSession({ prep: PREP }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Landed() {
      const location = useLocation();
      return <p>landed {location.search}</p>;
    }
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/strategy/${SESSION_ID}`]}>
          <Routes>
            <Route path="/strategy/template" element={<Landed />} />
            <Route path="/strategy/:id" element={<SessionDetail me={aMe()} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const which = await screen.findByLabelText("Apply to which template?");
    // The session was started from t1, so t1 is offered first.
    expect(which).toHaveValue("t1");
    await user.selectOptions(which, "t-default");
    await user.click(screen.getByLabelText("Apply the rewording of s1_revenue"));
    await user.click(screen.getByRole("button", { name: "Apply 1 selected to the template" }));
    expect(await screen.findByText(/landed .*template=t-default/)).toBeInTheDocument();
  });

  it("does not ask when there is only one template", async () => {
    showSession(aSession({ prep: PREP }), aMe(),
                { "GET /api/strategy-templates/": [TEMPLATES[0]] });
    await screen.findByLabelText("Suggested wording for s1_revenue");
    expect(screen.queryByLabelText("Apply to which template?")).not.toBeInTheDocument();
  });

  it("shows a pinned question in the live view with a note of its own", async () => {
    const pinned = { ...PREP.questions[0], is_pinned: true, note: "After the diagnostic." };
    showSession(aSession({ prep: { ...PREP, questions: [pinned] },
                           pinned_questions: [pinned] }), aMe());
    expect(await screen.findByText("Your questions")).toBeInTheDocument();
    expect(screen.getByLabelText(/Your note — Who decides a crew/))
      .toHaveValue("After the diagnostic.");
    expect(screen.getByText(/prompts, not scored answers/)).toBeInTheDocument();
  });

  it("a VA gets no prep panel and no brief", async () => {
    // The server sends a VA no prep at all; the screen offers them nothing either.
    showSession(aSession({ prep: null }), aMe({ role: "VA" }));
    await screen.findByText(/Running the call, drafting, sending/);
    expect(screen.queryByText("Prepare for this session")).not.toBeInTheDocument();
  });
});


describe("nothing sends without the body on the screen", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // The incident of 2026-09-22: the panel showed the opening line and not the
  // questions under it, and six broken questions reached a prospect.
  const PREVIEW = {
    subject: "A few questions before our strategy session",
    to_address: "dana@acme.invalid", from_address: "bryan@getexecutivesnow.test",
    body_text: "Hi Dana,\n\nSNAPSHOT\n1. Revenue — last year / this year\n\n"
      + "SIX KEY COMPONENTS\nRate each one from 1 to 10 — 1 means not true today, "
      + "10 means completely true.\n1. Vision\n2. People",
    body_html: "<p>Hi Dana,</p>",
  };

  it("shows the whole email, and will not send until it has", async () => {
    const user = userEvent.setup();
    let answerPreview = false;
    const fetchMock = showSession(aSession(), aMe(), {
      [`GET /api/strategy-sessions/${SESSION_ID}/send-preview/`]: () =>
        answerPreview ? { status: 200, body: PREVIEW } : { status: 200, body: null },
      [`POST /api/strategy-sessions/${SESSION_ID}/send-questions/`]:
        { from_address: "bryan@getexecutivesnow.test" },
    });

    await user.click(await screen.findByRole(
      "button", { name: /Or email the questions instead/ }));
    // No body yet, so no send.
    expect(screen.getByRole("button", { name: "Send the questions" })).toBeDisabled();

    answerPreview = true;
    await user.type(screen.getByLabelText("Intro to the questions email"), "!");
    const body = await screen.findByLabelText("The email as it will send");
    // The part that was never on the screen before: the questions and the scale.
    expect(body).toHaveTextContent("Rate each one from 1 to 10");
    expect(body).toHaveTextContent("Vision");
    expect(screen.getByText(/dana@acme.invalid/)).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Send the questions" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Send the questions" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url.endsWith("/send-questions/"))).toBe(true));
  });

  it("does the same for the form link", async () => {
    const user = userEvent.setup();
    showSession(aSession({ precall_sent: false }), aMe(), {
      [`GET /api/strategy-sessions/${SESSION_ID}/send-preview/`]: PREVIEW,
    });
    await user.click(await screen.findByRole("button", { name: "Send the form link" }));
    // Scoped to this panel: the map's covering email has one of its own.
    const panel = screen.getByRole("button", { name: "Send the form link" })
      .closest(".card") as HTMLElement;
    expect(await within(panel).findByLabelText("The email as it will send"))
      .toBeInTheDocument();
  });

  it("shows the fractional's note on the session", async () => {
    showSession(aSession({ fractional_note: "Ratings to be taken on the call." }), aMe());
    expect(await screen.findByText("Ratings to be taken on the call."))
      .toBeInTheDocument();
  });

  it("gives a VA no note, because their payload carries none", async () => {
    // The server sends a VA an empty string; the screen draws nothing from it.
    showSession(aSession({ fractional_note: "" }), aMe({ role: "VA" }));
    await screen.findByText(/Running the call, drafting, sending/);
    expect(screen.queryByText("Ratings to be taken on the call.")).not.toBeInTheDocument();
  });
});


describe("more than one template", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const GENERIC = { ...TEMPLATES[0], id: "t2", name: "Operations — generic",
                    is_default: false, sessions: 0 };

  it("opens the practice default, and switches to another", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/strategy-templates/": [GENERIC, TEMPLATES[0]] }));
    renderRoute(<SessionTemplate me={aMe()} />);
    const picker = await screen.findByLabelText("Template");
    expect(picker).toHaveValue("t1");
    await user.selectOptions(picker, "t2");
    expect(screen.getByLabelText("Template name")).toHaveValue("Operations — generic");
  });

  it("renames, duplicates, restores from seed, and sets the default", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/strategy-templates/t1/": { changed: [], template: {
        ...TEMPLATES[0], name: "Grime Fighters (Brett Murray)" } },
      "POST /api/strategy-templates/t1/duplicate/": { ...GENERIC, id: "t3",
                                                      name: "A copy" },
      "POST /api/strategy-templates/restore-from-seed/": GENERIC,
      "POST /api/strategy-templates/t2/set-default/": { ...GENERIC, is_default: true },
      "GET /api/strategy-templates/": [TEMPLATES[0], GENERIC],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SessionTemplate me={aMe()} />);

    const name = await screen.findByLabelText("Template name");
    await user.clear(name);
    await user.type(name, "Grime Fighters (Brett Murray)");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(await screen.findByText(/Renamed to “Grime Fighters \(Brett Murray\)”/))
      .toBeInTheDocument();

    await user.type(screen.getByLabelText("Name for the copy"), "A copy");
    await user.click(screen.getByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/duplicate/"))
      ?.body).toEqual({ name: "A copy" }));

    await user.click(screen.getByRole("button", { name: "Restore from seed" }));
    await waitFor(() => expect(fetchMock.calls.find((c) =>
      c.url.endsWith("/restore-from-seed/"))?.body).toEqual({ name: "Operations — generic",
                                                               variant: "" }));
    // Restoring opens the new one, which is not the default yet.
    await user.click(await screen.findByRole("button",
                                             { name: "Make this the practice default" }));
    expect(await screen.findByText(/is now the practice default/)).toBeInTheDocument();
  });

  it("will not archive the practice default", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/strategy-templates/": [TEMPLATES[0]] }));
    renderRoute(<SessionTemplate me={aMe()} />);
    expect(await screen.findByRole("button", { name: "Archive" })).toBeDisabled();
  });

  it("offers a template on Start a session, defaulting to the practice default",
     async () => {
    const user = userEvent.setup();
    const archived = { ...GENERIC, id: "t9", name: "Old one", archived_at: "2026-09-01" };
    const fetchMock = mockApi({
      "GET /api/strategy-templates/": [GENERIC, archived, TEMPLATES[0]],
      "GET /api/contacts/search/": { contacts: [
        { id: "c1", first_name: "Dana", last_name: "Reyes" }] },
      "POST /api/strategy-sessions/": aSession({ template: { id: "t2",
                                                  name: "Operations — generic" } }),
      "GET /api/strategy-sessions/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Sessions me={aMe()} />);

    const picker = await screen.findByLabelText("Template");
    await waitFor(() => expect(picker).toHaveValue("t1"));
    // Archived ones are not offered.
    expect(within(picker).queryByText(/Old one/)).not.toBeInTheDocument();
    await user.selectOptions(picker, "t2");
    await user.type(screen.getByLabelText("Find a prospect"), "Da");
    await user.click(await screen.findByRole("button", { name: "Dana Reyes" }));
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.method === "POST");
      expect((posted?.body as { template: string }).template).toBe("t2");
    });
    expect(await screen.findByText(/from “Operations — generic”/)).toBeInTheDocument();
  });
});

describe("managing a session", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const DRAFT = { state: "draft" as const, precall_sent: false, reset_refusal: "",
                  may_archive: true, may_delete: true, delete_refusal: "",
                  archived_at: null };
  const TWO = [TEMPLATES[0], { ...TEMPLATES[0], id: "t2", name: "60-minute Operations",
                               is_default: false }];

  const PREVIEW = { source: "60-minute Operations", changed_wording: ["s1_revenue",
    "s1_sites"], added: [], removed: ["s7_value_4", "s7_value_5"], refusal: "" };

  it("reloads a draft from a chosen template, naming it and counting the changes",
     async () => {
    const user = userEvent.setup();
    const asked: string[] = [];
    const fetchMock = showSession(aSession(DRAFT), aMe(), {
      "GET /api/strategy-templates/": TWO,
      [`GET /api/strategy-sessions/${SESSION_ID}/reset-preview/`]: PREVIEW,
      [`POST /api/strategy-sessions/${SESSION_ID}/reset-questions/`]: aSession(DRAFT),
    });
    vi.stubGlobal("confirm", (text: string) => { asked.push(text); return true; });

    await user.selectOptions(await screen.findByLabelText("Reset to the questions of"), "t2");
    await user.click(screen.getByRole("button", { name: "Reload questions from template" }));
    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/reset-questions/"));
      expect(posted?.body).toEqual({ template: "t2" });
    });
    expect(fetchMock.calls.some((c) => c.url.endsWith("reset-preview/?template=t2")))
      .toBe(true);
    expect(asked[0]).toMatch(/Are you sure.*“60-minute Operations”: 2 questions change wording \(2 removed\)/);
    expect(screen.queryByRole("button", { name: /Reset to default questions/ }))
      .not.toBeInTheDocument();
  });

  it("shows the reloaded wording in the live view straight away", async () => {
    const user = userEvent.setup();
    const before = aSession(DRAFT);
    const after = aSession(DRAFT);
    after.sections![0].questions[0] = { ...after.sections![0].questions[0],
                                        prompt: "How do you know the work was right?" };
    let current = before;
    const fetchMock = mockApi({
      "GET /api/strategy-templates/": TWO,
      [`GET /api/strategy-sessions/${SESSION_ID}/reset-preview/`]: {
        ...PREVIEW, changed_wording: ["s4_done_right"], removed: [] },
      [`POST /api/strategy-sessions/${SESSION_ID}/reset-questions/`]: () => {
        current = after; return { body: after }; },
      [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: [] },
      "GET /api/strategy-sessions/": () => ({ body: current }),
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", () => true);
    renderRoute(<SessionDetail me={aMe()} />, { path: "/strategy/:id",
                                                route: `/strategy/${SESSION_ID}` });
    expect(await screen.findByText(/How do you know a site was done right\?/))
      .toBeInTheDocument();
    await user.click(await screen.findByRole("button",
                                             { name: "Reload questions from template" }));
    expect(await screen.findByText("How do you know the work was right?"))
      .toBeInTheDocument();
    expect(screen.queryByText(/How do you know a site was done right\?/))
      .not.toBeInTheDocument();
    expect(screen.getByText(/1 question changed wording/)).toBeInTheDocument();
  });

  it("says there is nothing to reload rather than confirming zero changes", async () => {
    const user = userEvent.setup();
    const asked: string[] = [];
    const fetchMock = showSession(aSession(DRAFT), aMe(), {
      "GET /api/strategy-templates/": TWO,
      [`GET /api/strategy-sessions/${SESSION_ID}/reset-preview/`]: {
        ...PREVIEW, changed_wording: [], removed: [] },
    });
    vi.stubGlobal("confirm", (text: string) => { asked.push(text); return true; });
    await user.click(await screen.findByRole("button",
                                             { name: "Reload questions from template" }));
    expect(await screen.findByText(/Nothing to reload — this draft already has/))
      .toBeInTheDocument();
    expect(asked).toEqual([]);
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("restores the seed's wording, confirmed, as a separate action", async () => {
    const user = userEvent.setup();
    const asked: string[] = [];
    const fetchMock = showSession(aSession(DRAFT), aMe(), {
      "GET /api/strategy-templates/": TWO,
      [`GET /api/strategy-sessions/${SESSION_ID}/reset-preview/`]: {
        ...PREVIEW, source: "Operations — seed wording", changed_wording: ["s1_revenue"],
        removed: [] },
      [`POST /api/strategy-sessions/${SESSION_ID}/restore-seed/`]: aSession(DRAFT),
    });
    vi.stubGlobal("confirm", (text: string) => { asked.push(text); return true; });
    await user.click(await screen.findByRole("button", { name: "Restore seed wording" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/restore-seed/")))
      .toBe(true));
    expect(fetchMock.calls.some((c) => c.url.endsWith("reset-preview/?source=seed")))
      .toBe(true);
    expect(asked[0]).toMatch(/“Operations — seed wording”: 1 question change wording\./);
    expect(fetchMock.calls.some((c) => c.url.endsWith("/reset-questions/"))).toBe(false);
  });

  it("does nothing when either confirm is declined", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(DRAFT), aMe(), {
      "GET /api/strategy-templates/": TWO,
      [`GET /api/strategy-sessions/${SESSION_ID}/reset-preview/`]: PREVIEW,
    });
    vi.stubGlobal("confirm", () => false);
    await user.click(await screen.findByRole("button",
                                             { name: "Reload questions from template" }));
    await user.click(screen.getByRole("button", { name: "Restore seed wording" }));
    await waitFor(() => expect(fetchMock.calls.filter((c) =>
      c.url.includes("reset-preview")).length).toBe(2));
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("lands back from the template editor with the banner and the send card",
     async () => {
    const fetchMock = mockApi({
      [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: [] },
      "GET /api/strategy-sessions/": aSession(DRAFT),
    });
    vi.stubGlobal("fetch", fetchMock);
    const scrolled: string[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) { scrolled.push(this.id); };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[{ pathname: `/strategy/${SESSION_ID}`,
                                         state: { templateUpdated: true } }]}>
          <Routes>
            <Route path="/strategy/:id" element={<SessionDetail me={aMe()} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Template updated\. This draft still holds the old wording — reset it to pick up the changes\./))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send the form/ })).toBeInTheDocument();
    await waitFor(() => expect(scrolled).toContain("precall-card"));
    Element.prototype.scrollIntoView = original;
  });

  it("offers a new session instead, and says why, once someone has been asked",
     async () => {
    showSession(aSession({ ...DRAFT, state: "precall_sent",
      reset_refusal: "The questions on a session are a record of what a real person "
        + "was asked, so they are fixed once it has reached anyone." }), aMe());
    const link = await screen.findByRole("link",
                                         { name: "Start a new session from this template" });
    expect(link.getAttribute("href")).toBe("/strategy?new=1&template=t1&contact=c1");
    expect(screen.getByText(/what a real person was asked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset to default questions" }))
      .not.toBeInTheDocument();
  });

  it("has Start a new session on every session page", async () => {
    showSession(aSession({ state: "complete" }), aMe({ role: "VA" }));
    const link = await screen.findByRole("link", { name: "Start a new session" });
    expect(link.getAttribute("href")).toBe("/strategy?new=1&template=t1");
  });

  it("archives, and deletes only from archived with the refusal shown", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession({ ...DRAFT, state: "complete",
                                             reset_refusal: "fixed" }), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/archive/`]: aSession(),
    });
    expect(screen.queryByRole("button", { name: "Delete permanently" }))
      .not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Archive this session" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/archive/")))
      .toBe(true));
  });

  it("will not offer delete for a converted session, and says why", async () => {
    showSession(aSession({ ...DRAFT, state: "converted", reset_refusal: "fixed",
      archived_at: "2026-09-26T10:00:00Z",
      delete_refusal: "This session was converted to work, and its goals, projects "
        + "and tasks link back to its strategy map." }), aMe());
    expect(await screen.findByRole("button", { name: "Delete permanently" })).toBeDisabled();
    expect(screen.getByText(/link back to its strategy map/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore this session" })).toBeInTheDocument();
  });

  it("tags an ask-if-time question quietly in the live view", async () => {
    const session = aSession();
    session.sections![0].questions[0] = { ...session.sections![0].questions[0],
                                          must_ask: false, ask_if_time: true };
    showSession(session, aMe());
    expect(await screen.findByText("if time")).toHaveClass("muted");
  });
});

describe("the sessions list", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("opens the start form with the template and prospect already chosen", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/strategy-templates/": [TEMPLATES[0], { ...TEMPLATES[0], id: "t2",
        name: "Grime Fighters (Brett Murray)", is_default: false }],
      "GET /api/contacts/c1/": { id: "c1", first_name: "Dana", last_name: "Reyes" },
      "GET /api/strategy-sessions/": [],
    }));
    renderRoute(<Sessions me={aMe()} />, { path: "/strategy",
                                           route: "/strategy?new=1&template=t2&contact=c1" });
    await waitFor(() => expect(screen.getByLabelText("Template")).toHaveValue("t2"));
    await waitFor(() => expect(screen.getByLabelText("Find a prospect"))
      .toHaveValue("Dana Reyes"));
  });

  it("lists archived sessions separately, with restore and a warned delete", async () => {
    const user = userEvent.setup();
    const asked: string[] = [];
    const archived = aSession({ archived_at: "2026-09-26T10:00:00Z", may_archive: true,
                                may_delete: true, delete_refusal: "" });
    const fetchMock = mockApi({
      "GET /api/strategy-sessions/?archived=1": [archived],
      [`DELETE /api/strategy-sessions/${SESSION_ID}/`]: { status: 204, body: null },
      "GET /api/strategy-sessions/": [],
      "GET /api/strategy-templates/": [TEMPLATES[0]],
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", (text: string) => { asked.push(text); return true; });
    renderRoute(<Sessions me={aMe()} />, { path: "/strategy", route: "/strategy" });

    await user.click(await screen.findByRole("button", { name: "Archived" }));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    // The start form is for live work; it is not on the archived list.
    expect(screen.queryByText("Start a session")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "DELETE"))
      .toBe(true));
    expect(asked[0]).toMatch(/permanently.*cannot be undone/);
  });
});

describe("editing a template's questions", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const WITH_TWO = { ...TEMPLATES[0], sections: [{ ...TEMPLATES[0].sections[0],
    questions: [TEMPLATES[0].sections[0].questions[0],
                { ...TEMPLATES[0].sections[0].questions[0], key: "s4_no_show",
                  prompt: "If a frontline worker no-shows tonight?", must_ask: false,
                  position: 1 }] }] };

  it("adds a question with every field the request names", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/strategy-templates/t1/questions/": WITH_TWO,
      "GET /api/strategy-templates/": [WITH_TWO],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SessionTemplate me={aMe()} />);

    await user.click(await screen.findByRole("button", { name: "Add a question to Diagnostic" }));
    await user.type(screen.getByLabelText("Wording of the new question in diagnostic"),
                    "Who signs off a new hire?");
    await user.selectOptions(screen.getByLabelText(
      "Kind of answer (new question in diagnostic)"), "diagnostic_triple");
    await user.type(screen.getByLabelText("Area (new question in diagnostic)"), "People");
    await user.click(screen.getByLabelText("Must ask (new question in diagnostic)"));
    await user.click(screen.getByLabelText("Fractional note (new question in diagnostic)"));
    await user.click(screen.getByRole("button", { name: "Add the question" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/questions/"))
      ?.body).toEqual({
        section: "diagnostic", prompt: "Who signs off a new hire?",
        response_schema: "diagnostic_triple", ask_when: "live", area: "People",
        must_ask: true, is_financial: false, has_fractional_note: true,
        ask_if_time: false }));
  });

  it("keeps a refused new question in the box", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "POST /api/strategy-templates/t1/questions/": () => ({ status: 400, body: {
        detail: "This one is rated 1–10. “What” asks for an explanation." } }),
      "GET /api/strategy-templates/": [WITH_TWO],
    }));
    renderRoute(<SessionTemplate me={aMe()} />);
    await user.click(await screen.findByRole("button", { name: "Add a question to Diagnostic" }));
    await user.type(screen.getByLabelText("Wording of the new question in diagnostic"),
                    "What is it?");
    await user.click(screen.getByRole("button", { name: "Add the question" }));
    expect(await screen.findByText(/asks for an explanation/)).toBeInTheDocument();
    expect(screen.getByLabelText("Wording of the new question in diagnostic"))
      .toHaveValue("What is it?");
  });

  it("removes (after a confirm), reorders, and saves a time budget", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/strategy-templates/t1/remove-question/": WITH_TWO,
      "POST /api/strategy-templates/t1/reorder/": WITH_TWO,
      "PATCH /api/strategy-templates/t1/": { changed: [], template: WITH_TWO },
      "GET /api/strategy-templates/": [WITH_TWO],
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", () => true);
    renderRoute(<SessionTemplate me={aMe()} />);

    await user.click(await screen.findByRole("button", { name: "Move s4_no_show up" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/reorder/"))
      ?.body).toEqual({ section: "diagnostic", keys: ["s4_no_show", "s4_done_right"] }));

    await user.click(screen.getByRole("button", { name: "Remove s4_no_show" }));
    await waitFor(() => expect(fetchMock.calls.find((c) =>
      c.url.endsWith("/remove-question/"))?.body).toEqual({ key: "s4_no_show" }));

    const minutes = screen.getByLabelText("Minutes for Diagnostic");
    await user.clear(minutes);
    await user.type(minutes, "20");
    await user.click(screen.getByLabelText("Ask s4_no_show only if time"));
    await user.click(screen.getByRole("button", { name: /Save 2 changes/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ questions: [{ key: "s4_no_show", ask_if_time: true }],
                 sections: [{ code: "diagnostic", time_budget_minutes: 20 }] }));
  });

  it("restores the 60-minute cut from the seed", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/strategy-templates/restore-from-seed/": { ...TEMPLATES[0], id: "t6",
        name: "60-minute Operations", is_default: false },
      "GET /api/strategy-templates/": [TEMPLATES[0]],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SessionTemplate me={aMe()} />);
    await user.selectOptions(await screen.findByLabelText("Which cut of the seed"), "sixty");
    expect(screen.getByLabelText("Name for the template from the seed"))
      .toHaveValue("60-minute Operations");
    await user.click(screen.getByRole("button", { name: "Restore from seed" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ name: "60-minute Operations", variant: "sixty" }));
  });
});


describe("from prep, through the editor, and back", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("Save returns to the session the prep came from", async () => {
    const user = userEvent.setup();
    const prep = { id: "prep1", state: "ready", website_url: "", notes: "", summary: "",
      bottlenecks: [], questions: [], web_searches: 0,
      rewordings: [{ key: "s4_done_right", current: "How do you know a site was done right?",
                     suggested: "How do you know the kitchen was clean?", why: "" }] };
    const fetchMock = mockApi({
      [`GET /api/strategy-sessions/${SESSION_ID}/`]: aSession({ prep } as never),
      "PATCH /api/strategy-templates/t1/": { changed: ["s4_done_right"],
                                             template: TEMPLATES[0] },
      "GET /api/strategy-templates/": TEMPLATES,
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Landed() {
      const location = useLocation();
      return <p>landed on {location.pathname}
        {(location.state as { templateUpdated?: boolean })?.templateUpdated
          ? " with the banner" : ""}</p>;
    }
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[
          `/strategy/template?session=${SESSION_ID}&prefill=s4_done_right&template=t1`]}>
          <Routes>
            <Route path="/strategy/template" element={<SessionTemplate me={aMe()} />} />
            <Route path="/strategy/:id" element={<Landed />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByLabelText("Wording of s4_done_right"))
      .toHaveValue("How do you know the kitchen was clean?"));
    expect(screen.getByRole("link", { name: "Back to the session" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Save 1 change/ }));
    expect(await screen.findByText(`landed on /strategy/${SESSION_ID} with the banner`))
      .toBeInTheDocument();
  });
});

describe("the map tray, after dry run 2", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const ROW = { id: "r1", position: 0, bottleneck: "Supervisor overload",
    root_cause: "14 sites", the_fix: "Area lead per 8", owner_text: "Integrator",
    horizon: 60, measurable: "Inspections per site", mechanics_note: "",
    converted_to: "" as const, from_ai: true };

  it("consolidates, and shows what a merged row merges", async () => {
    const user = userEvent.setup();
    const merged = { ...ROW, id: "r9", bottleneck: "Supervision does not scale",
      state: "proposed" as const, merged_from: [
        { id: "r1", bottleneck: "Supervisor overload", state: "accepted" },
        { id: "r2", bottleneck: "One supervisor, 14 sites", state: "proposed" }] };
    const fetchMock = showSession(aSession({ map_rows: [
      { ...ROW, state: "accepted" }, { ...ROW, id: "r2", bottleneck: "One supervisor, "
        + "14 sites", state: "proposed" }, merged] }), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/consolidate/`]: { drafted: [] },
    });
    expect(await screen.findByText(
      "Merges 2: Supervisor overload (on the map) · One supervisor, 14 sites"))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Consolidate with Claude" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/consolidate/")))
      .toBe(true));
  });

  it("asks before a Consolidate that would pass the estimated AI balance", async () => {
    const user = userEvent.setup();
    let asked = 0;
    const fetchMock = showSession(aSession({ map_rows: [
      { ...ROW, state: "accepted" }, { ...ROW, id: "r2", state: "proposed" }] }), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/consolidate/`]: (body: unknown) =>
        (asked++ === 0 && !(body as { confirm_over_balance?: boolean })?.confirm_over_balance)
          ? { status: 409, body: { needs_confirmation: true, detail:
              "Consolidating should cost about $0.40, more than the estimated $0.10 left." } }
          : { status: 201, body: { drafted: [] } },
    });
    await user.click(await screen.findByRole("button", { name: "Consolidate with Claude" }));
    expect(await screen.findByText(/more than the estimated \$0\.10 left/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Consolidate anyway" }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.url.endsWith("/consolidate/"))
      .map((c) => c.body)).toEqual([undefined, { confirm_over_balance: true }]));
  });

  it("removes an accepted row from the map after a confirm", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession({ map_rows: [{ ...ROW, state: "accepted" }] }),
                                  aMe(), { "POST /api/strategy-map-rows/r1/remove/": ROW });
    vi.stubGlobal("confirm", () => true);
    await user.click(await screen.findByRole("button",
                                             { name: "Remove Supervisor overload from the map" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/r1/remove/")))
      .toBe(true));
  });

  it("does not offer Remove on a converted row", async () => {
    showSession(aSession({ map_rows: [{ ...ROW, state: "accepted", converted_to: "goal" }] }));
    await screen.findByText(/1\. Supervisor overload/);
    expect(screen.queryByRole("button", { name: /Remove Supervisor overload/ }))
      .not.toBeInTheDocument();
  });
});
