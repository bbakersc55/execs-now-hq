import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { StageRules } from "./StageRules";

const stage = (id: string, label: string, semantic: string, position: number) =>
  ({ id, pipeline: "p-sales", code: id, label, semantic, position, is_terminal: false });

const PIPELINES = [{
  id: "p-sales", name: "Sales", kind: "sales", position: 0, contact_count: 0,
  stages: [stage("s-qual", "Qualified", "active", 1), stage("s-won", "Closed Won", "won", 2)],
}];

const RULE = {
  id: "r1", pipeline: "p-sales", from_stage: null, to_stage: "s-qual",
  action_type: "create_task", task_title_template: "Follow up", task_due_offset_days: 3,
  task_client_visible: false, email_template: null, send_by_offset_days: 7, is_active: true,
  summary: "When a contact reaches Qualified in Sales, create task 'Follow up' due in 3 days"
           + " (internal, hidden from the client).",
};

function show() {
  const fetchMock = mockApi({
    "/api/pipelines/": PIPELINES,
    "PATCH /api/stage-automations/r1/": { ...RULE, task_client_visible: true },
    "POST /api/stage-automations/": { ...RULE, id: "r2" },
    "/api/stage-automations/": [RULE],
    "/api/email-templates/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<StageRules />);
  return fetchMock;
}

const sent = (fetchMock: ReturnType<typeof mockApi>, method: string) =>
  fetchMock.calls.find((c) => c.method === method)?.body as Record<string, unknown>;

/**
 * A stage rule's task is internal unless the FF ticks "Client can see this
 * task" — except on the won stage, whose task is for the new client.
 */
describe("stage rules: whether the client sees the task", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("starts unticked, and sends internal, for an ordinary stage", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("option", { name: "Qualified" });
    await user.selectOptions(screen.getByLabelText("When a contact becomes"), "s-qual");

    expect(screen.getByLabelText("Client can see this task")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST")).toMatchObject({
      to_stage: "s-qual", task_client_visible: false,
    }));
  });

  it("starts ticked for the won stage", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("option", { name: "Closed Won" });
    await user.selectOptions(screen.getByLabelText("When a contact becomes"), "s-won");

    expect(screen.getByLabelText("Client can see this task")).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST"))
      .toMatchObject({ to_stage: "s-won", task_client_visible: true }));
  });

  it("sends what the FF chose, over either default", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("option", { name: "Closed Won" });
    await user.selectOptions(screen.getByLabelText("When a contact becomes"), "s-won");
    await user.click(screen.getByLabelText("Client can see this task"));   // untick

    await user.click(screen.getByRole("button", { name: "Add rule" }));
    await waitFor(() => expect(sent(fetchMock, "POST"))
      .toMatchObject({ to_stage: "s-won", task_client_visible: false }));
  });

  it("changes an existing rule from the list", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const box = await screen.findByLabelText(/Client can see the task: When a contact reaches/);
    expect(box).not.toBeChecked();

    await user.click(box);
    await waitFor(() => expect(sent(fetchMock, "PATCH"))
      .toEqual({ task_client_visible: true }));
  });
});
