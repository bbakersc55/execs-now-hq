import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID, aMe, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { WorkParentDetail } from "./WorkParentDetail";

const GOAL = aWorkParent();

function showGoal(me = aMe(), post: (body: unknown) => { status?: number; body: unknown }) {
  const fetchMock = mockApi({
    "POST /api/tasks/": post,
    [`/api/goals/${GOAL.id}/children/`]: { projects: [], tasks: [] },
    [`/api/goals/${GOAL.id}/`]: GOAL,
    "/api/stakeholders/": [],
    "/api/comments/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<WorkParentDetail me={me} kind="goal" />, {
    path: "/work/goals/:id", route: `/work/goals/${GOAL.id}`,
  });
  return fetchMock;
}

describe("Add a task here, on a goal (Check 5)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("works for a client, who sends no company — the server sets their own", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    showGoal(aMe({ role: "ECC", client_company: COMPANY_ID }), (body) => {
      sent = body;
      return { status: 201, body: { id: "t1", title: "Send the AP export" } };
    });

    await user.type(await screen.findByLabelText("New task title"), "Send the AP export");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(sent).toEqual({ title: "Send the AP export", goal: GOAL.id }));
    await waitFor(() => expect(screen.getByLabelText("New task title")).toHaveValue(""));
    expect(screen.queryByText(/Bad Request/)).not.toBeInTheDocument();
  });

  it("the practice still files it under the goal's company", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    showGoal(aMe(), (body) => {
      sent = body;
      return { status: 201, body: { id: "t1" } };
    });
    await user.type(await screen.findByLabelText("New task title"), "Map the flow");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(sent).toEqual({
      title: "Map the flow", goal: GOAL.id, client_company: COMPANY_ID,
    }));
  });

  it("shows a refusal in the server's words, never a bare 400", async () => {
    const user = userEvent.setup();
    showGoal(aMe({ role: "ECC", client_company: COMPANY_ID }), () => ({
      status: 400, body: { goal: ["That goal is not available to you."] },
    }));
    await user.type(await screen.findByLabelText("New task title"), "Nope");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByText("That goal is not available to you.")).toBeInTheDocument();
    expect(screen.queryByText(/400/)).not.toBeInTheDocument();
  });
});
