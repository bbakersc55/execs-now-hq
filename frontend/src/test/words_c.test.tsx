import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LinkPicker } from "../components/LinkPicker";
import { MeetingProposal, StrategySessionRow } from "../lib/api";
import { WordsProvider } from "../lib/words";
import { Branding } from "../screens/Branding";
import { Duplicates } from "../screens/Duplicates";
import { Meetings } from "../screens/Meetings";
import { LinkChips } from "../screens/NoteDetail";
import { SessionDetail } from "../screens/SessionDetail";
import { StageRules } from "../screens/StageRules";
import { aMe } from "./fixtures";
import { mockApi, renderRoute } from "./render";

/**
 * The practice's own words (2026-10-15) on the CRM, notes, meeting-queue and
 * strategy-session screens. Each case draws with custom words and checks that
 * they show and the default words do not, in the places the hierarchy is named.
 */
const PAIRS = {
  goal: { singular: "objective", plural: "objectives" },
  project: { singular: "initiative", plural: "initiatives" },
  task: { singular: "action", plural: "actions" },
  step: { singular: "checkpoint", plural: "checkpoints" },
};
const custom = (node: ReactNode) => <WordsProvider pairs={PAIRS}>{node}</WordsProvider>;

beforeEach(() => vi.unstubAllGlobals());

describe("stage rules, in the practice's words", () => {
  it("names the follow-up as the practice's task", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "/api/pipelines/": [{ id: "p", name: "Sales", kind: "sales", position: 0,
                            contact_count: 0, stages: [] }],
      "/api/stage-automations/examples/": [],
      "/api/stage-automations/": [{
        id: "r1", pipeline: "p", trigger: "won", from_stage: null, to_stage: null, idle_days: null,
        action_type: "create_task", task_title_template: "", task_due_offset_days: 3,
        task_client_visible: false, task_for: "contact_owner", task_assignee: null,
        email_template: null, send_by_offset_days: 7, move_to_stage: null, touch_cadence: "",
        notice_text: "", is_active: true, position: 0, summary: "Rule one" }],
      "/api/email-templates/": [],
      "/api/staff/": [],
    }));
    renderRoute(custom(<StageRules />));
    expect(await screen.findByLabelText("Client can see the action: Rule one"))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add a rule to Sales" }));
    expect(screen.getByRole("option", { name: "Create an action" })).toBeInTheDocument();
    expect(screen.getByText("Action title")).toBeInTheDocument();
    expect(screen.getByText("Client can see this action")).toBeInTheDocument();
    expect(screen.queryByText(/\btasks?\b/i)).not.toBeInTheDocument();
  });
});

describe("duplicates, in the practice's words", () => {
  it("counts the practice's tasks", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/contacts/duplicate-groups/": [{
        key: "a", reasons: ["same name"], suggested_survivor: "x", dismissed_pairs: [],
        contacts: ["x", "y"].map((id, n) => ({
          id, name: "Mike Eller", company: "", emails: [], created_at: "2026-09-22T00:00:00Z",
          last_meeting: null, meetings: 0, tasks: n === 0 ? 1 : 3, notes: 0 })) }],
    }));
    renderRoute(custom(<Duplicates />));
    expect(await screen.findByText(/1 action, 0 notes/)).toBeInTheDocument();
    expect(screen.getByText(/3 actions, 0 notes/)).toBeInTheDocument();
    expect(screen.queryByText(/\btasks?\b/)).not.toBeInTheDocument();
  });
});

describe("notes, in the practice's words", () => {
  it("names the linked task and the link picker's task in the practice's word", () => {
    vi.stubGlobal("fetch", mockApi({ "/api/tasks/": [] }));
    renderRoute(custom(<>
      <LinkChips note={{ task: "t1", task_title: "Map it" } as never} />
      <LinkPicker value={{ contact: null, company: null, task: null }} onChange={() => {}} />
    </>));
    expect(screen.getByRole("link", { name: "Action: Map it" })).toBeInTheDocument();
    expect(screen.getByText("Action (optional, and separate from the above)"))
      .toBeInTheDocument();
    expect(screen.getByRole("option", { name: "No action" })).toBeInTheDocument();
    expect(screen.queryByText(/\btask\b/i)).not.toBeInTheDocument();
  });
});

describe("branding preview, in the practice's words", () => {
  it("previews the portal's navigation with the practice's words", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/settings/branding": {
      display_name: "", practice_name: "Acme", primary_color: "#1F2933",
      accent_color: "#7B8794", footer_text: "", has_logo: false, has_mark: false,
      branding_updated_at: null, defaults: { primary_color: "#1F2933", accent_color: "#7B8794" },
    } }));
    renderRoute(custom(<Branding />));
    const portal = await screen.findByLabelText("Portal preview");
    expect(within(portal).getByText("Actions")).toBeInTheDocument();
    expect(within(portal).getByText("New action")).toBeInTheDocument();
    expect(within(portal).queryByText(/task/i)).not.toBeInTheDocument();
  });
});

describe("the meeting queue, in the practice's words", () => {
  const SEAT = { user_id: "u3", company_id: "co1", company_name: "Acme" };
  const PROPOSAL = {
    id: "p1", state: "pending", title: "Acme review", meeting_date: "2026-09-20",
    proposed_summary: "", summary: "", summary_discarded: false,
    source_file: { id: "f1", name: "Acme notes", mime_type: "application/vnd.google-apps.document",
                   state: "parsed", skip_reason: "", error: "", owner_email: "b@x.test",
                   web_view_link: "https://d/f1", fetched_at: "2026-09-22T09:00:00Z" },
    meeting: null, counts: { pending: 1, approved: 0, rejected: 0 },
    items: [{ id: "i2", kind: "action_item", state: "pending", source_excerpt: "",
              position: 0, created_record_type: "", created_record_id: null, actioned_at: null,
              owner_contact_name: "Dana Reyes", owner_seat: SEAT,
              payload: { text: "Send the Q3 margin breakdown", proposed_due_date: "2026-09-25",
                         proposed_owner_text: "Dana Reyes", proposed_owner_contact_id: "c1",
                         owner_side: "other", owner_kind: "client",
                         proposed_outcome: "follow_up" } }],
  } as unknown as MeetingProposal;

  it("offers to make it the practice's task, and files it under its goal and project",
    async () => {
      const user = userEvent.setup();
      vi.stubGlobal("fetch", mockApi({
        "GET /api/meeting-proposals/p1/": PROPOSAL,
        "GET /api/meeting-proposals/": [PROPOSAL],
        "GET /api/drive-watch/backfill/": { folder: {
          folder_name: "Notes", readable_here: 0, readable_in_subfolders: 0, subfolders: [],
          readable_total: 0, outstanding: 0, oldest: null, newest: null,
          per_note_usd: "0.05", per_note_is_measured: false, estimate_usd: "0", minutes: 0 },
          backfill: null },
        "GET /api/drive-watch/": { connected: true, google_connected: true, drive_access: true,
          drive_account: "b@x.test", folder_id: "f", folder_name: "Notes",
          last_polled_at: null, last_error: "", has_cursor: true, files_pending: 0,
          files_failed: 0, files_skipped: 0, backfill: null },
        "GET /api/portal-people/": [{ id: "u3", name: "Dana Reyes", role: "FCC",
                                      company: "co1" }],
        "GET /api/goals/": [], "GET /api/projects/": [], "GET /api/tasks/": [],
      }));
      renderRoute(custom(<Meetings me={aMe()} />), { path: "/meetings", route: "/meetings" });
      await user.click(await screen.findByRole("button", { name: "Review" }));

      expect(await screen.findByRole("radio", { name: /— make it an action$/ }))
        .toBeInTheDocument();
      expect(screen.getByText(/Follow up — an action for .* to check it happened/))
        .toBeInTheDocument();
      expect(screen.getByText(/keep it on Dana Reyes's record, no action/)).toBeInTheDocument();

      await user.click(screen.getByRole("radio", { name: /Assign in the portal/ }));
      expect(screen.getByText(/Dana Reyes's action, waiting on the client/))
        .toBeInTheDocument();
      const tool = await screen.findByRole("group", { name: "File it for Acme" });
      expect(within(tool).getByLabelText("Assign the client's action to")).toBeInTheDocument();
      const goal = within(tool).getByLabelText("Under which objective");
      expect(within(goal).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["No objective", "A new objective…"]);
      const project = within(tool).getByLabelText("In which initiative");
      expect(within(project).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["No initiative", "A new initiative…"]);
      const task = within(tool).getByLabelText("Which action");
      expect(within(task).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["A new action, from this item"]);
      expect(within(tool).getByText("Objective")).toBeInTheDocument();
      await user.selectOptions(goal, "new");
      expect(within(tool).getByPlaceholderText("The new objective")).toBeInTheDocument();
      await user.selectOptions(project, "new");
      expect(within(tool).getByPlaceholderText("The new initiative")).toBeInTheDocument();
      expect(screen.queryByText(/\b(task|goal|project)s?\b/i)).not.toBeInTheDocument();
    });
});

describe("converting a strategy map, in the practice's words", () => {
  it("converts rows into the practice's goals and projects", async () => {
    const user = userEvent.setup();
    const ID = "11111111-2222-4333-8444-555555555555";
    const session = {
      id: ID, state: "complete", template: { id: "t1", name: "Ops" },
      contact: { id: "c1", name: "Dana Reyes" }, company: { id: "co1", name: "Acme" },
      visionary: null, integrator: null, owner: "Bryan Baker", scheduled_at: null,
      started_at: null, budget_minutes: 70, current_section: "", current_section_at: null,
      precall_sent: false, precall_expires_at: null, precall_questions_sent_at: null,
      prep: null, pinned_questions: [], fractional_note: "", precall_default_intro: "",
      mirror: { goal: "", unlocks: "" }, proposed_mirror: { goal: "", unlocks: "" },
      pdf_include_flags: { fractional_notes: false, mechanics: false,
                           diagnostic_observations: false, alignment_observation: false,
                           investment: false },
      has_pdf: false, converted_at: null, created_at: "2026-09-18T12:00:00Z",
      sections: [], answers: [], map_rows: [],
      six_key_components: { scores: [], ratings: {}, answered: 0, of: 6, average: null,
                            complete: false, lowest: null },
      path_notes: [], must_ask: { outstanding: [], answered: 0, of: 0 },
    } as unknown as StrategySessionRow;
    const rows = ["Decide faster", "Hire a lead"].map((title, n) => ({
      row: `r${n}`, position: n, title, the_fix: "", root_cause: "", owner_text: "",
      client_owner_contact: null, measurable: "", horizon: 30, target_date: null,
      suggested: "goal", needs_baseline: false }));
    vi.stubGlobal("fetch", mockApi({
      [`GET /api/strategy-sessions/${ID}/conversion-preview/`]: { rows },
      [`POST /api/strategy-sessions/${ID}/convert/`]: { created: [
        { as: "goal", title: "Decide faster" }, { as: "project", title: "Hire a lead" }] },
      "GET /api/strategy-sessions/": session,
    }));
    renderRoute(custom(<SessionDetail me={aMe()} />),
                { path: "/strategy/:id", route: `/strategy/${ID}` });

    const select = await screen.findByLabelText("Convert Hire a lead as");
    expect(within(select).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["An objective", "An initiative", "Leave it out"]);
    expect(screen.getByText(/An objective carrying a measurable needs a/)).toBeInTheDocument();
    expect(screen.getByText(/Creates 2 objectives and 0 initiatives/)).toBeInTheDocument();
    await user.selectOptions(select, "project");
    expect(screen.getByText(/Creates 1 objective and 1 initiative/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create the work" }));
    await waitFor(() => expect(
      screen.getByText("Created 2 — Decide faster (objective), Hire a lead (initiative)."))
      .toBeInTheDocument());
  });
});

describe("with no words chosen", () => {
  it("reads exactly as before", () => {
    vi.stubGlobal("fetch", mockApi({ "/api/tasks/": [] }));
    render(<MemoryRouter><LinkChips note={{ task: "t1", task_title: "Map it" } as never} />
    </MemoryRouter>);
    expect(screen.getByRole("link", { name: "Task: Map it" })).toBeInTheDocument();
  });
});
