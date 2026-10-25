import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { StageRules } from "./StageRules";

const stage = (id: string, label: string, semantic: string, position: number, contacts = 0) =>
  ({ id, pipeline: "p-sales", code: id, label, semantic, position, is_terminal: false, contacts });

const PIPELINES = [{
  id: "p-sales", name: "Sales", kind: "sales", position: 0, contact_count: 0,
  stages: [stage("s-prosp", "Prospecting", "working", 0, 3), stage("s-qual", "Qualified", "qualified", 1),
    stage("s-won", "Closed Won", "won", 2)],
}];

const RULE = {
  id: "r1", pipeline: "p-sales", trigger: "enters", from_stage: null, to_stage: "s-qual", idle_days: null,
  action_type: "create_task", task_title_template: "Follow up", task_due_offset_days: 3,
  task_client_visible: false, task_for: "contact_owner", task_assignee: null, email_template: null,
  send_by_offset_days: 7, move_to_stage: null, touch_cadence: "", notice_text: "", is_active: true, position: 0,
  summary: "When a contact reaches Qualified in Sales, create task 'Follow up' for their owner due in 3 days"
           + " (internal, hidden from the client).",
};
const WON = { ...RULE, id: "r2", trigger: "won", to_stage: null, task_title_template: "Kick off",
  summary: "When a contact is won in Sales, create task 'Kick off' for their owner due in 3 days (the client can see it)." };

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "/api/pipelines/": PIPELINES,
    "PATCH /api/stage-automations/r1/": { ...RULE, task_client_visible: true },
    "POST /api/stage-automations/examples/": { ...RULE, id: "r9" },
    "/api/stage-automations/examples/": [
      { key: "first_call", summary: "When a contact reaches Prospecting in Sales, create task 'Call {FirstName}'", added: false },
      { key: "won_kickoff", summary: "When a contact is won in Sales, create task 'Kick off'", added: true }],
    "POST /api/stage-automations/": { ...RULE, id: "r3" },
    "/api/stage-automations/": [RULE, WON],
    "POST /api/pipeline-stages/order/": [],
    "POST /api/pipeline-stages/": stage("s-new", "Discovery", "working", 3),
    "PATCH /api/pipeline-stages/": stage("s-qual", "Qualified lead", "qualified", 1),
    "DELETE /api/pipeline-stages/s-prosp/": () => ({ status: 400,
      body: ["“Prospecting” still holds 3 contacts. Move them to another stage first."] }),
    "/api/email-templates/": [{ id: "t1", name: "Proposal follow-up", subject: "", kind: "stage" }],
    "/api/staff/": [{ id: "m1", user: "u-va", email: "va@x.test", full_name: "Val Assist", role: "VA",
      invited_at: null, revoked_at: null, is_active: true }],
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<StageRules />);
  return fetchMock;
}

const sent = (fetchMock: ReturnType<typeof mockApi>, method: string, part: string) =>
  fetchMock.calls.find((c) => c.method === method && (part.startsWith("/api/") && part.endsWith("/")
    ? c.url === part : c.url.includes(part)))?.body as Record<string, unknown>;

describe("stage rules, part 2: one card per stage", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows each stage as a card holding its rules, and won or lost on the pipeline's own card", async () => {
    show();
    const qualified = await screen.findByRole("region", { name: "Stage Qualified" });
    expect(await within(qualified).findByText(RULE.summary)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Stage Prospecting" })).getByText("3 contacts")).toBeInTheDocument();
    expect(screen.getByText(WON.summary)).toBeInTheDocument();
    expect(within(qualified).queryByText(WON.summary)).toBeNull();
  });

  it("renames, reorders, adds and refuses to remove a stage that holds contacts, in words", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const name = await screen.findByLabelText("Name of Qualified");
    await user.clear(name);
    await user.type(name, "Qualified lead{Enter}");
    await waitFor(() => expect(sent(fetchMock, "PATCH", "/api/pipeline-stages/s-qual/")).toEqual({ label: "Qualified lead" }));
    await user.click(screen.getByRole("button", { name: "Move Qualified up" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/pipeline-stages/order/")).toEqual(
      { pipeline: "p-sales", ids: ["s-qual", "s-prosp", "s-won"] }));
    await user.type(screen.getByLabelText("New stage name"), "Discovery");
    await user.click(screen.getByRole("button", { name: "Add stage" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/pipeline-stages/")).toMatchObject({ label: "Discovery" }));
    // Bryan, 2026-10-24: the refusal shows on the card itself, at once, and
    // nothing is asked of the server.
    await user.click(screen.getByRole("button", { name: "Remove Prospecting" }));
    const prospecting = screen.getByRole("region", { name: "Stage Prospecting" });
    expect(await within(prospecting).findByRole("alert")).toHaveTextContent(
      "Prospecting still holds 3 contacts. Move them to another stage first.");
    expect(within(prospecting).queryByRole("button", { name: "Remove" })).toBeNull();
    expect(fetchMock.calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("shows the server's refusal on the stage's own card", async () => {
    const user = userEvent.setup();
    show({ "DELETE /api/pipeline-stages/s-qual/": () => ({ status: 400,
      body: ["People have moved through “Qualified”, and their history keeps it."] }) });
    await user.click(await screen.findByRole("button", { name: "Remove Qualified" }));
    const qualified = screen.getByRole("region", { name: "Stage Qualified" });
    await user.click(within(qualified).getByRole("button", { name: "Remove" }));
    expect(await within(qualified).findByRole("alert")).toHaveTextContent("history keeps it");
  });

  it("adds a rule for sitting idle that moves the contact", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByRole("button", { name: "Add a rule to Prospecting" }));
    const form = screen.getByRole("group", { name: "New rule for Prospecting" });
    await user.selectOptions(within(form).getByLabelText("When"), "idle");
    await user.clear(within(form).getByLabelText("Days with no activity"));
    await user.type(within(form).getByLabelText("Days with no activity"), "14");
    await user.selectOptions(within(form).getByLabelText("Then"), "move_stage");
    await user.selectOptions(within(form).getByLabelText("Move to"), "s-qual");
    await user.click(within(form).getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/stage-automations/")).toMatchObject({
      trigger: "idle", to_stage: "s-prosp", idle_days: 14, action_type: "move_stage", move_to_stage: "s-qual",
      from_stage: null }));
  });

  it("a task for a named team member, a notice, and referral touches send what they choose", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByRole("button", { name: "Add a rule to Qualified" }));
    let form = screen.getByRole("group", { name: "New rule for Qualified" });
    await user.selectOptions(within(form).getByLabelText("Coming from"), "s-prosp");
    await user.type(within(form).getByLabelText("Task title"), "Call {{FirstName}");
    await user.selectOptions(within(form).getByLabelText("For"), "member");
    await user.selectOptions(await within(form).findByLabelText("Team member"), "u-va");
    await user.click(within(form).getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/stage-automations/")).toMatchObject({
      trigger: "enters", from_stage: "s-prosp", task_title_template: "Call {FirstName}",
      task_for: "member", task_assignee: "u-va" }));

    fetchMock.calls.length = 0;
    await user.click(screen.getByRole("button", { name: "Add a rule to Sales" }));
    form = screen.getByRole("group", { name: "New rule for Sales" });
    await user.selectOptions(within(form).getByLabelText("When"), "lost");
    await user.selectOptions(within(form).getByLabelText("Then"), "notify");
    await user.type(within(form).getByLabelText("The notice"), "Lost one");
    await user.click(within(form).getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/stage-automations/")).toMatchObject({
      trigger: "lost", to_stage: null, action_type: "notify", notice_text: "Lost one" }));
  });

  it("a won rule starts with the client seeing the task", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByRole("button", { name: "Add a rule to Sales" }));
    const form = screen.getByRole("group", { name: "New rule for Sales" });
    await user.type(within(form).getByLabelText("Task title"), "Kick off");
    await user.click(within(form).getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/stage-automations/")).toMatchObject({
      trigger: "won", task_client_visible: true }));
  });

  it("offers the starter rules not yet added, one click each", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const add = await screen.findByRole("button", { name: /^Add: When a contact reaches Prospecting/ });
    expect(screen.queryByRole("button", { name: /^Add: When a contact is won/ })).toBeNull();
    await user.click(add);
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/stage-automations/examples/")).toEqual({ pipeline: "p-sales", key: "first_call" }));
  });

  it("turns a rule off, and ticks whether the client sees its task", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByLabelText(`On: ${RULE.summary}`));
    await waitFor(() => expect(sent(fetchMock, "PATCH", "/api/stage-automations/r1/")).toEqual({ is_active: false }));
  });
});
