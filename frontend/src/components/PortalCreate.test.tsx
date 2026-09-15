import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Tasks } from "../screens/Tasks";
import { Work } from "../screens/Work";
import { aMe, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PortalCreate } from "./PortalCreate";

const CO = "co-acme";
const anEcc = () => aMe({ role: "ECC", client_company: CO });

const PORTAL_PROJECTS = [
  aWorkParent({ id: "pr1", kind: "project", title: "Our tidy-up", client_company: CO }),
  // A stale or wider response must still not be offered.
  aWorkParent({ id: "pr9", kind: "project", title: "Someone else's", client_company: "co-2" }),
];
const PORTAL_PEOPLE = [
  { id: "u1", name: "Dana Reyes", role: "FCC", company: CO },
  { id: "u2", name: "Priya Shah", role: "ECC", company: CO },
  { id: "u9", name: "Bryan Baker", role: "FF", company: null },
  { id: "u8", name: "Sam Other", role: "ECC", company: "co-2" },
];

function options(label: string) {
  return Array.from((screen.getByLabelText(label) as HTMLSelectElement).options).map((o) => o.text);
}

function created(title = "Chase the supplier") {
  return { id: "t9", title, project: "pr1" };
}

describe("New task in the portal (FR-3.35)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function open(routes: Record<string, unknown> = {}) {
    const fetchMock = mockApi({
      ...routes,
      "/api/projects/": PORTAL_PROJECTS,
      "/api/portal-people/": PORTAL_PEOPLE,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PortalCreate me={anEcc()} />);
    return fetchMock;
  }

  it("offers only this company's projects and this company's people", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "New task" }));
    await waitFor(() => expect(options("Project for the new task")).toEqual(["No project", "Our tidy-up"]));
    await waitFor(() => expect(options("Assign the new task to"))
      .toEqual(["Unassigned", "Dana Reyes", "Priya Shah"]));
  });

  it("creates the task with project, assignee and due date, then its steps in order", async () => {
    const user = userEvent.setup();
    const steps: unknown[] = [];
    const fetchMock = open({
      "POST /api/tasks/t9/checklist/": (body: unknown) => {
        steps.push(body);
        return { status: 201, body: { id: `s${steps.length}` } };
      },
      "POST /api/tasks/": () => ({ status: 201, body: created() }),
    });

    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Chase the supplier");
    await waitFor(() => expect(options("Project for the new task")).toContain("Our tidy-up"));
    await user.selectOptions(screen.getByLabelText("Project for the new task"), "pr1");
    await user.selectOptions(screen.getByLabelText("Assign the new task to"), "u2");
    await user.type(screen.getByLabelText("Due date for the new task"), "2026-10-01");
    await user.type(screen.getByLabelText("Add a step to the new task"), "Call them");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    await user.type(screen.getByLabelText("Add a step to the new task"), "Confirm the date{Enter}");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    expect(await screen.findByText(/“Chase the supplier” created/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST" && c.url === "/api/tasks/")?.body)
      .toEqual({ title: "Chase the supplier", project: "pr1", assignee: "u2", due_date: "2026-10-01" });
    expect(steps).toEqual([{ text: "Call them" }, { text: "Confirm the date" }]);
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "/tasks/t9");
  });

  it("sends nothing optional that was left empty", async () => {
    const user = userEvent.setup();
    const fetchMock = open({ "POST /api/tasks/": () => ({ status: 201, body: created("Quick one") }) });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Quick one");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText(/“Quick one” created/);
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ title: "Quick one" });
    expect(fetchMock.calls.some((c) => c.url.includes("checklist"))).toBe(false);
  });

  it("names a step that failed instead of reporting success", async () => {
    const user = userEvent.setup();
    open({
      "POST /api/tasks/t9/checklist/": (body: unknown) => (body as { text: string }).text === "Second"
        ? { status: 403, body: { detail: "This task is the practice's to change." } }
        : { status: 201, body: { id: "s1" } },
      "POST /api/tasks/": () => ({ status: 201, body: created() }),
    });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Chase the supplier");
    for (const s of ["First", "Second"]) {
      await user.type(screen.getByLabelText("Add a step to the new task"), `${s}{Enter}`);
    }
    await user.click(screen.getByRole("button", { name: "Create task" }));
    expect(await screen.findByText(/1 step\(s\) were not added: “Second”/)).toBeInTheDocument();
    expect(screen.queryByText(/“Chase the supplier” created\./)).not.toBeInTheDocument();
  });

  it("shows a refusal and adds no steps when the task itself is refused", async () => {
    const user = userEvent.setup();
    const fetchMock = open({
      "POST /api/tasks/": () => ({ status: 400, body: { detail: "You can assign this only to someone at your own company." } }),
    });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Nope");
    await user.type(screen.getByLabelText("Add a step to the new task"), "Never sent{Enter}");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    expect(await screen.findByText(/only to someone at your own company/)).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.includes("checklist"))).toBe(false);
    // The form stays open with what was typed, so nothing is lost.
    expect(screen.getByLabelText("New task title")).toHaveValue("Nope");
  });
});

describe("New project in the portal (FR-3.35a)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("creates a project that is never filed under a goal", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/projects/": () => ({ status: 201, body: { id: "pr2", title: "Supplier cleanup" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PortalCreate me={anEcc()} />);

    await user.click(screen.getByRole("button", { name: "New project" }));
    expect(screen.queryByLabelText(/goal/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("New project title"), "Supplier cleanup");
    await user.type(screen.getByLabelText("New project description"), "Drop the dead ones.");
    await user.type(screen.getByLabelText("Target date for the new project"), "2026-11-30");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByText(/“Supplier cleanup” created/)).toBeInTheDocument();
    const body = fetchMock.calls.find((c) => c.method === "POST")?.body;
    expect(body).toEqual({ title: "Supplier cleanup", description: "Drop the dead ones.",
                           target_date: "2026-11-30" });
    expect(body).not.toHaveProperty("goal");
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "/work/projects/pr2");
  });
});

describe("where the portal offers them", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const WORK_ROUTES = {
    "/api/goals/": [], "/api/projects/": PORTAL_PROJECTS, "/api/tasks/": [],
    "/api/portal-people/": PORTAL_PEOPLE, "/api/companies/": [], "/api/client-activity/": [],
  };

  it("Our work offers New task and New project to a client, and no goal control", async () => {
    vi.stubGlobal("fetch", mockApi(WORK_ROUTES));
    renderRoute(<Work me={anEcc()} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New project" })).toBeInTheDocument();
    expect(screen.queryByLabelText("What to add")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "A goal" })).not.toBeInTheDocument();
  });

  it("Tasks offers New task to a client", async () => {
    vi.stubGlobal("fetch", mockApi(WORK_ROUTES));
    renderRoute(<Tasks me={aMe({ role: "FCC", client_company: CO })} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
  });

  it("the practice keeps its own Add form rather than the portal's", async () => {
    vi.stubGlobal("fetch", mockApi(WORK_ROUTES));
    renderRoute(<Work me={aMe()} />);
    expect(await screen.findByLabelText("What to add")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
    renderRoute(<Tasks me={aMe()} />);
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
  });
});
