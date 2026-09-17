import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Work } from "./Work";

const CO = "co-acme";

const GOALS = [
  aWorkParent({ id: "g1", kind: "goal", title: "Cut supervisor overload", client_company: CO }),
  aWorkParent({ id: "g2", kind: "goal", title: "Empty goal", client_company: CO }),
];
const PROJECTS = [
  aWorkParent({ id: "pr1", kind: "project", title: "Order-to-cash", client_company: CO, goal: "g1" }),
  aWorkParent({ id: "pr9", kind: "project", title: "Loose project", client_company: CO, goal: null }),
];
const TASKS = [
  aTask({ id: "t1", title: "Map the invoice process", goal: null, project: "pr1" }),
  aTask({ id: "t2", title: "Straight on the goal", goal: "g1", project: null }),
  aTask({ id: "t9", title: "Unfiled thing", goal: null, project: null }),
];

const LISTS = {
  "/api/goals/": GOALS,
  "/api/projects/": PROJECTS,
  // Before the bare "/api/tasks/": mockApi matches by prefix in insertion order,
  // so the plain key would otherwise answer the unfiled query too.
  "/api/tasks/?unfiled=1": [TASKS[2]],
  "/api/tasks/": TASKS,
  "/api/client-activity/": [],
  "/api/companies/": [],
  "/api/contacts/": [],
  "/api/portal-people/": [],
};

function open(me = aMe({ role: "FF" })) {
  vi.stubGlobal("fetch", mockApi(LISTS));
  renderRoute(<Work me={me} />);
}

/** The goal's own <li>, which holds the nested lists. Async, because every
 *  test here waits on the three queries the tree is built from. */
async function branch(title: string) {
  return (await screen.findByText(title)).closest("li")!;
}

describe("Work shows three levels at once, not one", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("nests projects under a goal and tasks under a project, expanded by default", async () => {
    open();
    const goal = await branch("Cut supervisor overload");
    // Level two, and level three inside it.
    const project = await within(goal).findByText("Order-to-cash");
    expect(within(project.closest("li")!).getByText("Map the invoice process"))
      .toBeInTheDocument();
    // A task filed on the goal itself sits beside the project, not under it.
    expect(within(goal).getByText("Straight on the goal")).toBeInTheDocument();
    expect(within(project.closest("li")!).queryByText("Straight on the goal")).toBeNull();
  });

  it("says so when a goal holds nothing, rather than looking broken", async () => {
    open();
    expect(await within(await branch("Empty goal")).findByText(/Nothing under this goal yet/))
      .toBeInTheDocument();
  });

  it("collapses one goal without touching the other, and says what is hidden", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByText("Order-to-cash");

    await user.click(screen.getByLabelText("Collapse Cut supervisor overload"));
    expect(screen.queryByText("Order-to-cash")).toBeNull();
    expect(screen.queryByText("Map the invoice process")).toBeNull();
    expect(await branch("Cut supervisor overload")).toHaveTextContent("2 items hidden");
    // The other goal is untouched.
    expect(within(await branch("Empty goal")).getByText(/Nothing under this goal yet/))
      .toBeInTheDocument();

    await user.click(screen.getByLabelText("Expand Cut supervisor overload"));
    expect(screen.getByText("Order-to-cash")).toBeInTheDocument();
  });

  it("remembers a collapse for that person, and not for anyone else", async () => {
    const user = userEvent.setup();
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    await screen.findByText("Order-to-cash");
    await user.click(screen.getByLabelText("Collapse Cut supervisor overload"));

    // Same person, new visit.
    vi.unstubAllGlobals();
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    expect(await screen.findByLabelText("Expand Cut supervisor overload")).toBeInTheDocument();

    // A colleague on the same laptop still sees it open.
    vi.unstubAllGlobals();
    open(aMe({ role: "VA", email: "someone@x.invalid" }));
    expect(await screen.findByText("Order-to-cash")).toBeInTheDocument();
  });

  it("leaves the unfiled sections exactly where they were", async () => {
    open();
    const loose = (await screen.findByText("Loose project")).closest("section")!;
    expect(loose).toHaveTextContent("Projects with no goal");
    const unfiled = screen.getByText("Tasks filed under nothing").closest("section")!;
    expect(within(unfiled).getByText("Unfiled thing")).toBeInTheDocument();
    // And they are not swept into the goals list.
    expect(within(await branch("Cut supervisor overload")).queryByText("Loose project")).toBeNull();
  });

  it("gives a client the same nesting on Our work", async () => {
    open(aMe({ role: "FCC", client_company: CO }));
    const goal = await branch("Cut supervisor overload");
    expect(await within(goal).findByText("Order-to-cash")).toBeInTheDocument();
    expect(within(goal).getByText("Map the invoice process")).toBeInTheDocument();
  });
});
