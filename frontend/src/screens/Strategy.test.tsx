import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreCallForm, StrategySessionRow } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PreCallForm as PreCall } from "./PreCallForm";
import { SessionDetail } from "./SessionDetail";
import { SessionTemplate } from "./SessionTemplate";

const TOKEN = "a-public-token";
const SESSION_ID = "11111111-2222-4333-8444-555555555555";

function aForm(overrides: Partial<PreCallForm> = {}): PreCallForm {
  return {
    practice: "Executives Now", company: "Acme Facilities", first_name: "Dana",
    answered: 0, of: 2, complete: false,
    sections: [
      { code: "snapshot", title: "Snapshot: where they are today", questions: [
        { key: "s1_revenue", prompt: "Revenue — last year / this year",
          response_schema: "free_text", value: null },
      ]},
      { code: "six_key_components", title: "Six Key Components: self-rating",
        questions: [
          { key: "s2_vision", prompt: "Vision", response_schema: "rating_1_10",
            value: null },
        ]},
    ],
    ...overrides,
  };
}

function aSession(overrides: Partial<StrategySessionRow> = {}): StrategySessionRow {
  return {
    id: SESSION_ID, state: "in_call",
    contact: { id: "c1", name: "Dana Reyes" },
    company: { id: "co1", name: "Acme Facilities" },
    visionary: null, integrator: null, owner: "Bryan Baker",
    scheduled_at: null, started_at: "2026-09-18T12:00:00Z", budget_minutes: 70,
    current_section: "", current_section_at: null,
    precall_sent: true, precall_expires_at: "2026-10-18T14:00:00Z",
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
    expect(await screen.findByText(/0 of 7/)).toBeInTheDocument();
    expect(screen.getByText("25 min")).toBeInTheDocument();
    expect(screen.getByText("must ask")).toBeInTheDocument();
  });

  it("keeps a drafted row in the tray until someone accepts it", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      "POST /api/strategy-map-rows/r1/accept/": {},
    });
    expect(await screen.findByText(/Tray — 1 proposed/)).toBeInTheDocument();
    expect(screen.getByText(/The map — 0 rows/)).toBeInTheDocument();
    // The worked example stands in for an empty map.
    expect(screen.getByText(/1 supervisor covering 14 sites/)).toBeInTheDocument();

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
    expect(screen.getByRole("button", { name: /Send it again/ })).toBeInTheDocument();
  });
});

describe("per-section pacing", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("starts a section's clock when its header is clicked", async () => {
    const user = userEvent.setup();
    const fetchMock = showSession(aSession(), aMe(), {
      [`PATCH /api/strategy-sessions/${SESSION_ID}/`]: aSession(),
    });
    await screen.findByText(/Diagnostic/);
    await user.click(screen.getByRole("button", { name: /Start Diagnostic/ }));
    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(patched?.body).toEqual({ current_section: "diagnostic" });
    });
  });

  it("counts the current section against its own budget", async () => {
    const twelveMinutesAgo = new Date(Date.now() - 12 * 60_000).toISOString();
    showSession(aSession({ current_section: "diagnostic",
                           current_section_at: twelveMinutesAgo }));
    expect(await screen.findByText("12 of 25 min")).toBeInTheDocument();
    // The sections not being run show their budget and nothing else.
    expect(screen.getByText("15 min")).toBeInTheDocument();
  });

  it("flags a section that has run over", async () => {
    const longAgo = new Date(Date.now() - 40 * 60_000).toISOString();
    showSession(aSession({ current_section: "diagnostic", current_section_at: longAgo }));
    const pill = await screen.findByText("40 of 25 min");
    expect(pill).toHaveClass("warn");
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
      prompt: "How do you know last night went well?", ask_when: "precall" }] });
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
