import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalCreate } from "../components/PortalCreate";
import { HierarchyNote, StaffCreate } from "../components/StaffCreate";
import { Me, PortalRights } from "../lib/api";
import { WordsProvider } from "../lib/words";
import { TaskDetail } from "../screens/TaskDetail";
import { Tasks } from "../screens/Tasks";
import { TASK_ID, aMe, aTask } from "./fixtures";
import { mockApi, renderRoute } from "./render";

/** The practice's own words for the four levels, reaching the New forms, the
 *  task board and the task sheet (2026-10-15). */
const PAIRS = {
  goal: { singular: "objective", plural: "objectives" },
  project: { singular: "initiative", plural: "initiatives" },
  task: { singular: "action", plural: "actions" },
  step: { singular: "checkpoint", plural: "checkpoints" },
};
const DEFAULT = /\b(goals?|projects?|tasks?|steps?)\b/i;

const custom = (node: ReactNode) => <WordsProvider pairs={PAIRS}>{node}</WordsProvider>;

const LISTS = {
  "/api/companies/": [], "/api/goals/": [], "/api/projects/": [],
  "/api/portal-people/": [], "/api/contacts/": [], "/api/tasks/": [],
};

/** Everything a person reads, aria-labels and placeholders included. */
function readable(root: HTMLElement) {
  const attrs = Array.from(root.querySelectorAll("[aria-label],[placeholder],[title]"))
    .flatMap((el) => ["aria-label", "placeholder", "title"]
      .map((a) => el.getAttribute(a) ?? ""));
  return [root.textContent ?? "", ...attrs].join(" | ");
}

describe("the practice's words on the work screens", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the hierarchy note is composed from the practice's words", () => {
    const { container } = renderRoute(custom(<HierarchyNote />));
    expect(container.textContent).toContain(
      "An objective is a client outcome you are accountable for");
    expect(container.textContent).toContain("an initiative is a body of work toward it");
    expect(container.textContent).toContain(
      "An action can sit under an initiative, straight under an objective, or on its own.");
    expect(container.textContent).not.toMatch(DEFAULT);
  });

  it("the staff New forms use the practice's words throughout", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi(LISTS));
    const { container } = renderRoute(custom(<StaffCreate me={aMe({ role: "FF" })} />));
    expect(screen.getByRole("button", { name: "New action" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New initiative" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New objective" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New action" }));
    expect(screen.getByLabelText("Add a checkpoint to the new action")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create action" })).toBeInTheDocument();
    expect(screen.getByText("Show this action to the client")).toBeInTheDocument();
    expect(readable(container)).not.toMatch(DEFAULT);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "New objective" }));
    expect(screen.getByText(/An objective holds initiatives and actions\./)).toBeInTheDocument();
    expect(readable(container)).not.toMatch(DEFAULT);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "New initiative" }));
    expect(screen.getByText("An initiative groups actions, under an objective or on its own."))
      .toBeInTheDocument();
    expect(readable(container)).not.toMatch(DEFAULT);
  });

  it("the portal New forms use the practice's words", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi(LISTS));
    const portal = {
      may_create: { task: true, project: true, goal: true }, teams: [],
    } as unknown as PortalRights;
    const me: Me = aMe({ role: "ECC", client_company: "co-1", portal });
    const { container } = renderRoute(custom(<PortalCreate me={me} offer={["task", "project", "goal"]} />));

    await user.click(screen.getByRole("button", { name: "New action" }));
    expect(screen.getByLabelText("Initiative for the new action")).toBeInTheDocument();
    expect(readable(container)).not.toMatch(DEFAULT);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "New initiative" }));
    expect(container.textContent).toContain("An initiative groups your company's own actions. "
      + "Objectives are set with");
    expect(readable(container)).not.toMatch(DEFAULT);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "New objective" }));
    expect(screen.getByRole("button", { name: "Add the objective" })).toBeInTheDocument();
    expect(readable(container)).not.toMatch(DEFAULT);
  });

  it("the task sheet calls a step and a task by the practice's words", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`/api/tasks/${TASK_ID}/updates/`]: [
        { id: "u1", kind: "checklist_completed", from_value: "", to_value: "Call the bank",
          client_facing_line: "", acting_user: null, actor: { name: "Bryan" },
          source: "app", created_at: "2026-10-01T10:00:00Z", is_client_actor: false },
      ],
      [`/api/tasks/${TASK_ID}/checklist/`]: [],
      [`/api/comments/?task=${TASK_ID}`]: [],
      "/api/notes/": [],
      [`/api/tasks/${TASK_ID}/`]: aTask({ may_edit: true, may_delete: true }),
    }));
    renderRoute(custom(<TaskDetail me={aMe()} />),
                { path: "/tasks/:id", route: `/tasks/${TASK_ID}` });
    expect(await screen.findByRole("heading", { name: "Checkpoints" })).toBeInTheDocument();
    expect(screen.getByText("No checkpoints.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add checkpoint" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add a checkpoint…")).toBeInTheDocument();
    expect(screen.getByText(/Checkpoints are a flat list on purpose: an action cannot hold another action/))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit action" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete this action" })).toBeInTheDocument();
    expect(await screen.findByText("checkpoint done")).toBeInTheDocument();
    expect(screen.queryByText(/^No steps\.$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add step" })).not.toBeInTheDocument();
  });

  it("the board is titled and filtered in the practice's words", async () => {
    vi.stubGlobal("fetch", mockApi(LISTS));
    renderRoute(custom(<Tasks me={aMe()} />));
    expect(await screen.findByRole("heading", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByText("Everything across your objectives and initiatives, filed or not."))
      .toBeInTheDocument();
    expect(screen.getByLabelText("Search actions")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by initiative")).toBeInTheDocument();
    await waitFor(() => expect(
      screen.getByText("No actions yet. Add the first one from the button above."))
      .toBeInTheDocument());
    expect(screen.queryByText(/No tasks yet/)).not.toBeInTheDocument();
  });
});
