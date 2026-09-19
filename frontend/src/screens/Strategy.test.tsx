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
      { code: "mirror", title: "The mirror", position: 4, time_budget_minutes: 5,
        questions: [] },
      { code: "strategy_map", title: "Strategy Map", position: 5,
        time_budget_minutes: 15, questions: [] },
    ],
    answers: [],
    map_rows: [
      { id: "r1", position: 0, bottleneck: "Supervisor overload", root_cause: "14 sites",
        the_fix: "Area lead per 8", owner_text: "Integrator", horizon: 60,
        measurable: "Inspections per site", mechanics_note: "", state: "proposed",
        converted_to: "", from_ai: true },
    ],
    six_key_components: { ratings: { s2_vision: 8, s2_data: 3 }, answered: 2, of: 6,
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
