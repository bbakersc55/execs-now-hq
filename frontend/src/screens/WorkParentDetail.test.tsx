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


describe("Editing what a goal or project says", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const CONTACTS = [
    { id: "c1", first_name: "Dana", last_name: "Okafor", company: COMPANY_ID },
    { id: "c9", first_name: "Sam", last_name: "Other", company: "co-2" },
  ];

  function show(me = aMe(), entity = GOAL, kind: "goal" | "project" = "goal") {
    const plural = kind === "goal" ? "goals" : "projects";
    const fetchMock = mockApi({
      [`/api/${plural}/${entity.id}/children/`]: { projects: [], tasks: [] },
      [`PATCH /api/${plural}/${entity.id}/`]: (body: unknown) => ({ body: { ...entity, ...(body as object) } }),
      [`/api/${plural}/${entity.id}/`]: entity,
      "/api/contacts/": CONTACTS,
      "/api/stakeholders/": [],
      "/api/comments/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<WorkParentDetail me={me} kind={kind} />, {
      path: `/work/${plural}/:id`, route: `/work/${plural}/${entity.id}`,
    });
    return fetchMock;
  }

  it("saves the title, description, target date and client owner", async () => {
    const user = userEvent.setup();
    const fetchMock = show();

    await user.click(await screen.findByRole("button", { name: "Edit details" }));
    const title = screen.getByLabelText("Goal title");
    await user.clear(title);
    await user.type(title, "Cut order-to-cash to 20 days, phase 2");
    await user.type(screen.getByLabelText("Goal description"), "From 41 days.");
    await user.type(screen.getByLabelText("Target date"), "2026-12-31");
    await waitFor(() => expect(
      Array.from((screen.getByLabelText("Client owner") as HTMLSelectElement).options)
        .map((o) => o.text)).toEqual(["Nobody", "Dana Okafor"]));
    await user.selectOptions(screen.getByLabelText("Client owner"), "c1");
    await user.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      title: "Cut order-to-cash to 20 days, phase 2",
      description: "From 41 days.",
      target_date: "2026-12-31",
      client_owner_contact: "c1",
    }));
  });

  it("a project also carries a start date", async () => {
    const user = userEvent.setup();
    const project = aWorkParent({ id: "pr1", kind: "project", title: "Order-to-cash" });
    const fetchMock = show(aMe(), project, "project");

    await user.click(await screen.findByRole("button", { name: "Edit details" }));
    await user.type(screen.getByLabelText("Start date"), "2026-10-01");
    await user.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toMatchObject({ start_date: "2026-10-01", title: "Order-to-cash" }));
  });

  it("a client is never offered it", async () => {
    show(aMe({ role: "FCC", client_company: COMPANY_ID }));
    expect(await screen.findByText(/Cut order-to-cash/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit details" })).not.toBeInTheDocument();
  });
});
