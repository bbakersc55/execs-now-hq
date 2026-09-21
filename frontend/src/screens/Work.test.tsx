import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Work } from "./Work";

const CO = "co-acme";
const CO2 = "co-ridge";

const COMPANIES = [
  aCompany({ id: CO, name: "Acme Facilities" }),
  aCompany({ id: CO2, name: "Ridgeline Freight" }),
  // A client with nothing filed yet, which is a real state on day one.
  aCompany({ id: "co-empty", name: "Zephyr Labs" }),
];

/** One of each, so a heading cannot be right by accident: two clients and the
 *  practice's own work, which has no company at all. */
const acme = { client_company: CO, client_company_name: "Acme Facilities" };
const ridge = { client_company: CO2, client_company_name: "Ridgeline Freight" };
const ours = { client_company: null, client_company_name: "" };

const GOALS = [
  aWorkParent({ id: "g1", kind: "goal", title: "Cut supervisor overload", ...acme }),
  aWorkParent({ id: "g2", kind: "goal", title: "Empty goal", ...acme }),
  aWorkParent({ id: "g3", kind: "goal", title: "Ridgeline's goal", ...ridge }),
  aWorkParent({ id: "g4", kind: "goal", title: "Our own systems", ...ours }),
];
const PROJECTS = [
  aWorkParent({ id: "pr1", kind: "project", title: "Order-to-cash", ...acme, goal: "g1" }),
  aWorkParent({ id: "pr9", kind: "project", title: "Loose project", ...acme, goal: null }),
  aWorkParent({ id: "pr8", kind: "project", title: "Our own loose project", ...ours,
                goal: null }),
];
const TASKS = [
  aTask({ id: "t1", title: "Map the invoice process", goal: null, project: "pr1", ...acme }),
  aTask({ id: "t2", title: "Straight on the goal", goal: "g1", project: null, ...acme }),
  aTask({ id: "t9", title: "Unfiled thing", goal: null, project: null, ...acme }),
  aTask({ id: "t8", title: "Our own unfiled thing", goal: null, project: null, ...ours }),
];

const LISTS = {
  "/api/goals/": GOALS,
  "/api/projects/": PROJECTS,
  // Before the bare "/api/tasks/": mockApi matches by prefix in insertion order,
  // so the plain key would otherwise answer the unfiled query too.
  "/api/tasks/?unfiled=1": [TASKS[2], TASKS[3]],
  "/api/tasks/": TASKS,
  "/api/client-activity/": [],
  "/api/companies/": COMPANIES,
  "/api/contacts/": [],
  "/api/portal-people/": [],
};

/** A card by its title, so a heading inside it cannot be confused with the
 *  identically-worded option in the selector above. */
function card(title: string) {
  return screen.getByText(title).closest("section")! as HTMLElement;
}

function headings(title: string) {
  return within(card(title)).queryAllByRole("heading", { level: 4 }).map((h) => h.textContent);
}

function open(me = aMe({ role: "FF" })) {
  const fetchMock = mockApi(LISTS);
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Work me={me} />);
  return fetchMock;
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
    // A project and its tasks are one block (`.project-block` since Tier 1 of
    // the design brief; it used to be the project's own <li>).
    const block = project.closest(".project-block") as HTMLElement;
    expect(within(block).getByText("Map the invoice process")).toBeInTheDocument();
    // A task filed on the goal itself sits beside the project, not under it.
    expect(within(goal).getByText("Straight on the goal")).toBeInTheDocument();
    expect(within(block).queryByText("Straight on the goal")).toBeNull();
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


describe("Work carries a company dimension", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  const chooser = () => screen.getByLabelText("Filter by client company");

  it("groups all three lists by client, the practice's own work last", async () => {
    open();
    await screen.findByText("Order-to-cash");
    const internal = "Internal — the practice's own";

    expect(headings("Goals"))
      .toEqual(["Acme Facilities", "Ridgeline Freight", internal]);
    // A client with no work in view gets no empty heading: the groups are built
    // from the rows, not from the company list.
    expect(headings("Goals")).not.toContain("Zephyr Labs");
    expect(headings("Projects with no goal")).toEqual(["Acme Facilities", internal]);
    expect(headings("Tasks filed under nothing")).toEqual(["Acme Facilities", internal]);
  });

  it("defaults to all clients, and narrows all three lists together", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByText("Ridgeline's goal");
    expect(chooser()).toHaveValue("");
    expect(screen.getByText("Cut supervisor overload")).toBeInTheDocument();

    await user.selectOptions(chooser(), CO2);
    expect(screen.getByText("Ridgeline's goal")).toBeInTheDocument();
    expect(screen.queryByText("Cut supervisor overload")).toBeNull();
    expect(screen.queryByText("Our own systems")).toBeNull();
    // The two unfiled sections narrow with it rather than staying whole.
    expect(within(card("Projects with no goal")).getByText("None.")).toBeInTheDocument();
    expect(within(card("Tasks filed under nothing")).getByText("None.")).toBeInTheDocument();
  });

  it("narrows to the practice's own work, which belongs to no client", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByText("Our own systems");

    await user.selectOptions(chooser(), "internal");
    expect(screen.getByText("Our own systems")).toBeInTheDocument();
    expect(screen.queryByText("Cut supervisor overload")).toBeNull();
    expect(screen.queryByText("Ridgeline's goal")).toBeNull();

    const unfiled = card("Tasks filed under nothing");
    expect(within(unfiled).getByText("Our own unfiled thing")).toBeInTheDocument();
    expect(within(unfiled).queryByText("Unfiled thing")).toBeNull();
  });

  it("says a client has no goals rather than showing an empty card", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByText("Order-to-cash");

    await user.selectOptions(chooser(), "co-empty");
    expect(within(card("Goals")).getByText("No goals for this client yet."))
      .toBeInTheDocument();
  });

  it("remembers the client per person, not for the colleague beside them", async () => {
    const user = userEvent.setup();
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    await screen.findByText("Ridgeline's goal");
    await user.selectOptions(chooser(), CO2);

    // Same person, new visit.
    cleanup();
    vi.unstubAllGlobals();
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    expect(await screen.findByText("Ridgeline's goal")).toBeInTheDocument();
    expect(screen.queryByText("Cut supervisor overload")).toBeNull();

    // A colleague on the same laptop is still on all clients.
    cleanup();
    vi.unstubAllGlobals();
    open(aMe({ role: "VA", email: "someone@x.invalid" }));
    expect(await screen.findByText("Cut supervisor overload")).toBeInTheDocument();
  });

  it("falls back to all clients when the remembered one is gone", async () => {
    // Deleted, no longer a client, or a CF who lost the assignment. Filtering
    // to nothing with no way to see why is the failure being avoided.
    window.localStorage.setItem("work-company:bryan@x.invalid",
                                JSON.stringify("co-vanished"));
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));

    expect(await screen.findByText("Cut supervisor overload")).toBeInTheDocument();
    expect(screen.getByText("Ridgeline's goal")).toBeInTheDocument();
    expect(chooser()).toHaveValue("");
  });

  it("leaves the portal alone: no selector, no headings, no companies request", async () => {
    const fetchMock = open(aMe({ role: "FCC", client_company: CO, email: "f@x.invalid" }));
    await screen.findByText("Cut supervisor overload");

    expect(screen.queryByLabelText("Filter by client company")).toBeNull();
    expect(headings("Goals")).toEqual([]);
    // `/api/companies/` is staff-only and would 403; it is never asked for.
    expect(fetchMock.calls.some((c) => c.url.startsWith("/api/companies/"))).toBe(false);
  });
});
