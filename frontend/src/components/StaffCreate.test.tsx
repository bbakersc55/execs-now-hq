import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Tasks } from "../screens/Tasks";
import { Work } from "../screens/Work";
import { aMe, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { StaffCreate } from "./StaffCreate";

const CO = "co-acme";
const OTHER = "co-2";
const anFf = () => aMe({ role: "FF" });

const GOALS = [
  aWorkParent({ id: "g1", kind: "goal", title: "Their goal", client_company: CO }),
  aWorkParent({ id: "g2", kind: "goal", title: "Our own goal", client_company: null }),
  aWorkParent({ id: "g9", kind: "goal", title: "Someone else's goal", client_company: OTHER }),
];
const PROJECTS = [
  aWorkParent({ id: "pr1", kind: "project", title: "Their project", client_company: CO, goal: "g1" }),
  aWorkParent({ id: "pr2", kind: "project", title: "Their loose project", client_company: CO, goal: null }),
  aWorkParent({ id: "pr3", kind: "project", title: "Our own project", client_company: null, goal: null }),
];
const PEOPLE = [
  { id: "u1", name: "Bryan Baker", role: "FF", company: null },
  { id: "u2", name: "Casey Contractor", role: "CF", company: null },
  { id: "u3", name: "Dana Reyes", role: "FCC", company: CO },
  { id: "u9", name: "Sam Other", role: "ECC", company: OTHER },
];
const COMPANIES = [
  { id: CO, name: "Acme Foods", is_client_company: true },
  { id: OTHER, name: "Other Co", is_client_company: true },
  { id: "v1", name: "A vendor", is_client_company: false },
];
const CONTACTS = [
  { id: "c1", first_name: "Dana", last_name: "Reyes", company: CO },
  { id: "c9", first_name: "Sam", last_name: "Other", company: OTHER },
];

const LISTS = {
  "/api/companies/": COMPANIES,
  "/api/goals/": GOALS,
  "/api/projects/": PROJECTS,
  "/api/portal-people/": PEOPLE,
  "/api/contacts/": CONTACTS,
};

function options(label: string) {
  return Array.from((screen.getByLabelText(label) as HTMLSelectElement).options).map((o) => o.text);
}

describe("The practice's own New task (the portal had one; staff did not)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function open(routes: Record<string, unknown> = {}) {
    const fetchMock = mockApi({ ...LISTS, ...routes });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<StaffCreate me={anFf()} offer={["task"]} />);
    return fetchMock;
  }

  it("sends every field the form collects, then the steps in order", async () => {
    const user = userEvent.setup();
    const steps: unknown[] = [];
    const fetchMock = open({
      "/api/tasks/t9/checklist/": (body: unknown) => { steps.push(body); return { body: {} }; },
      "POST /api/tasks/": { id: "t9", title: "Map the invoice process", project: "pr1", goal: "g1" },
    });
    await user.click(screen.getByRole("button", { name: "New task" }));

    await user.type(screen.getByLabelText("New task title"), "Map the invoice process");
    await user.type(screen.getByLabelText("New task description"), "End to end.");
    await waitFor(() => expect(options("Client company for the new item")).toContain("Acme Foods"));
    await user.selectOptions(screen.getByLabelText("Client company for the new item"), CO);
    await user.selectOptions(screen.getByLabelText("Goal for the new task"), "g1");
    await user.selectOptions(screen.getByLabelText("Project for the new task"), "pr1");
    await user.selectOptions(screen.getByLabelText("Assign the new task to"), "u2");
    await user.selectOptions(screen.getByLabelText("Client owner for the new item"), "c1");
    await user.type(screen.getByLabelText("Due date for the new task"), "2026-10-01");
    await user.selectOptions(screen.getByLabelText("Priority for the new task"), "2");

    await user.type(screen.getByLabelText("Add a step to the new task"), "Pull the AP export");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    await user.type(screen.getByLabelText("Add a step to the new task"), "Map the approvals");
    await user.click(screen.getByRole("button", { name: "Add step" }));

    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(steps).toHaveLength(2));
    const posted = fetchMock.calls.find((c) => c.url === "/api/tasks/" && c.method === "POST");
    expect(posted!.body).toEqual({
      title: "Map the invoice process",
      description: "End to end.",
      client_company: CO,
      goal: "g1",
      project: "pr1",
      assignee: "u2",
      client_owner_contact: "c1",
      due_date: "2026-10-01",
      priority: 2,
      is_client_visible: true,
    });
    expect(steps).toEqual([{ text: "Pull the AP export" }, { text: "Map the approvals" }]);
  });

  it("narrows every picker to the chosen company, and re-narrows when it changes", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "New task" }));
    await waitFor(() => expect(options("Goal for the new task")).toEqual(["No goal", "Our own goal"]));
    expect(options("Project for the new task")).toEqual(["No project", "Our own project"]);
    // Internal work: the practice's own people only, and no client owner.
    expect(options("Assign the new task to")).toEqual(["Unassigned", "Bryan Baker", "Casey Contractor"]);
    expect(screen.getByLabelText("Client owner for the new item")).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Client company for the new item"), CO);
    await waitFor(() => expect(options("Goal for the new task")).toEqual(["No goal", "Their goal"]));
    expect(options("Project for the new task"))
      .toEqual(["No project", "Their project", "Their loose project"]);
    expect(options("Assign the new task to"))
      .toEqual(["Unassigned", "Bryan Baker", "Casey Contractor", "Dana Reyes"]);
    expect(options("Client owner for the new item")).toEqual(["Nobody yet", "Dana Reyes"]);

    // Picking a goal narrows the projects to that goal's own.
    await user.selectOptions(screen.getByLabelText("Goal for the new task"), "g1");
    expect(options("Project for the new task")).toEqual(["No project", "Their project"]);
  });

  it("clears choices that belonged to the company you just left", async () => {
    const user = userEvent.setup();
    const fetchMock = open({ "POST /api/tasks/": { id: "t9", title: "Switched" } });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Switched");
    await waitFor(() => expect(options("Client company for the new item")).toContain("Acme Foods"));
    await user.selectOptions(screen.getByLabelText("Client company for the new item"), CO);
    await user.selectOptions(screen.getByLabelText("Goal for the new task"), "g1");
    await user.selectOptions(screen.getByLabelText("Client owner for the new item"), "c1");

    await user.selectOptions(screen.getByLabelText("Client company for the new item"), OTHER);
    await user.click(screen.getByRole("button", { name: "Create task" }));

    const posted = fetchMock.calls.find((c) => c.url === "/api/tasks/" && c.method === "POST");
    expect(posted!.body).toEqual({
      title: "Switched", client_company: OTHER, priority: 1, is_client_visible: true,
    });
  });

  it("an internal task is never client-visible, and a client one can be hidden", async () => {
    const user = userEvent.setup();
    const fetchMock = open({ "POST /api/tasks/": { id: "t9", title: "Quiet one" } });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Quiet one");
    const tick = () => screen.getByLabelText("Show this task to the client");
    expect(tick()).toBeDisabled();
    expect(tick()).not.toBeChecked();

    await waitFor(() => expect(options("Client company for the new item")).toContain("Acme Foods"));
    await user.selectOptions(screen.getByLabelText("Client company for the new item"), CO);
    expect(tick()).toBeChecked();
    await user.click(tick());
    await user.click(screen.getByRole("button", { name: "Create task" }));

    const posted = fetchMock.calls.find((c) => c.url === "/api/tasks/" && c.method === "POST");
    expect((posted!.body as { is_client_visible: boolean }).is_client_visible).toBe(false);
  });

  it("says which steps were not added rather than implying they were", async () => {
    const user = userEvent.setup();
    open({
      // A function route, because a plain object is always served as a 200.
      "/api/tasks/t9/checklist/": () => ({ status: 400, body: { detail: "Too long." } }),
      "POST /api/tasks/": { id: "t9", title: "Partly" },
    });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("New task title"), "Partly");
    await user.type(screen.getByLabelText("Add a step to the new task"), "A step");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(screen.getByText(/1 step\(s\) were not added/)).toBeInTheDocument());
    expect(screen.getByText(/Too long\./)).toBeInTheDocument();
  });
});

describe("The practice's own New project and New goal", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends the description and dates the portal form always had", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...LISTS,
      "POST /api/projects/": { id: "pr9", title: "Order-to-cash", goal: "g1" },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<StaffCreate me={anFf()} />);

    await user.click(screen.getByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project title"), "Order-to-cash");
    await user.type(screen.getByLabelText("New project description"), "Invoices end to end.");
    await waitFor(() => expect(options("Client company for the new item")).toContain("Acme Foods"));
    await user.selectOptions(screen.getByLabelText("Client company for the new item"), CO);
    await user.selectOptions(screen.getByLabelText("Goal for the new project"), "g1");
    await user.type(screen.getByLabelText("Start date for the new project"), "2026-10-01");
    await user.type(screen.getByLabelText("Target date for the new project"), "2026-12-31");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    const posted = fetchMock.calls.find((c) => c.url === "/api/projects/" && c.method === "POST");
    expect(posted!.body).toEqual({
      title: "Order-to-cash",
      description: "Invoices end to end.",
      client_company: CO,
      goal: "g1",
      start_date: "2026-10-01",
      target_date: "2026-12-31",
    });
  });

  it("a goal takes no goal and no start date", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ ...LISTS, "POST /api/goals/": { id: "g9", title: "Cut DSO" } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<StaffCreate me={anFf()} />);

    await user.click(screen.getByRole("button", { name: "New goal" }));
    expect(screen.queryByLabelText("Goal for the new project")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Start date for the new project")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("New goal title"), "Cut DSO");
    await user.type(screen.getByLabelText("Target date for the new goal"), "2026-12-31");
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    const posted = fetchMock.calls.find((c) => c.url === "/api/goals/" && c.method === "POST");
    expect(posted!.body).toEqual({ title: "Cut DSO", target_date: "2026-12-31" });
  });
});

describe("Who sees a creation control", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("Tasks offers the practice its own form", async () => {
    vi.stubGlobal("fetch", mockApi({ ...LISTS, "/api/tasks/": [] }));
    renderRoute(<Tasks me={anFf()} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
  });

  it("Tasks still offers a client theirs", async () => {
    vi.stubGlobal("fetch", mockApi({ ...LISTS, "/api/tasks/": [] }));
    renderRoute(<Tasks me={aMe({ role: "ECC", client_company: CO })} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
  });

  it("Work offers the practice all three", async () => {
    vi.stubGlobal("fetch", mockApi({ ...LISTS, "/api/tasks/": [], "/api/client-activity/": [] }));
    renderRoute(<Work me={anFf()} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New project" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New goal" })).toBeInTheDocument();
  });

  it("Work never offers a client a goal", async () => {
    vi.stubGlobal("fetch", mockApi({ ...LISTS, "/api/tasks/": [] }));
    renderRoute(<Work me={aMe({ role: "ECC", client_company: CO })} />);
    expect(await screen.findByRole("button", { name: "New task" })).toBeInTheDocument();
    // FR-3.35a — a client never creates a goal.
    expect(screen.queryByRole("button", { name: "New goal" })).not.toBeInTheDocument();
  });

  it("renders nothing at all for a client role", () => {
    vi.stubGlobal("fetch", mockApi(LISTS));
    renderRoute(<StaffCreate me={aMe({ role: "FCC", client_company: CO })} />);
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
  });
});
