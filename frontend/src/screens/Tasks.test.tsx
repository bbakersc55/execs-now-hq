import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalPerson } from "../lib/api";
import { aCompany, aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Tasks } from "./Tasks";

const TASKS = [
  aTask({ id: "t1", title: "Map the invoice process", status: "not_started" }),
  aTask({ id: "t2", title: "Theirs to read only", status: "not_started", may_edit: false }),
];

const CO = "co-acme";
const CO2 = "co-ridge";

const COMPANIES = [
  aCompany({ id: CO, name: "Acme Facilities" }),
  aCompany({ id: CO2, name: "Ridgeline Freight" }),
];
const PROJECTS = [
  aWorkParent({ id: "pr1", kind: "project", title: "Order-to-cash",
                client_company: CO, client_company_name: "Acme Facilities" }),
  aWorkParent({ id: "pr2", kind: "project", title: "Fleet renewal",
                client_company: CO2, client_company_name: "Ridgeline Freight" }),
  aWorkParent({ id: "pr3", kind: "project", title: "Our own website",
                client_company: null, client_company_name: "" }),
];
const PEOPLE: PortalPerson[] = [
  { id: "u1", name: "Bryan Baker", role: "FF", company: null },
  { id: "u2", name: "Val the VA", role: "VA", company: null },
  { id: "u3", name: "Acme's founder", role: "FCC", company: CO },
  { id: "u4", name: "Ridgeline's founder", role: "FCC", company: CO2 },
];

const LISTS = {
  "/api/projects/": PROJECTS,
  "/api/portal-people/": PEOPLE,
  "/api/companies/": COMPANIES,
  "/api/contacts/": [],
  "/api/goals/": [],
};

function open(me = aMe({ role: "FF" }), routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ ...LISTS, "/api/tasks/": TASKS, ...routes });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Tasks me={me} />);
  return fetchMock;
}

async function showBoard() {
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText("View"), "board");
  return user;
}

function card(title: string) {
  return screen.getByText(title).closest("div.comment") as HTMLElement;
}

function column(label: string) {
  return screen.getByLabelText(`${label} column`);
}

/** One drag, as the browser fires it. jsdom has no drag, so the DataTransfer is
 *  a stand-in carrying the one thing the handlers read from it. */
function drag(from: Element, to: Element) {
  const data: Record<string, string> = {};
  const dataTransfer = {
    setData: (k: string, v: string) => { data[k] = v; },
    getData: (k: string) => data[k] ?? "",
    effectAllowed: "", dropEffect: "",
  };
  fireEvent.dragStart(from, { dataTransfer });
  fireEvent.dragOver(to, { dataTransfer });
  fireEvent.drop(to, { dataTransfer });
}

describe("the board: dragging a card changes its status, the long way round", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();   // a remembered client would filter the list
  });

  it("asks for the client-facing line, then patches exactly like the task page", async () => {
    const fetchMock = open();
    await showBoard();

    drag(card("Map the invoice process"), column("In progress"));

    // The same prompt, in the same words, as changing status on the task itself.
    const prompt = await screen.findByRole("dialog",
      { name: "What this means for the client" });
    expect(prompt).toHaveTextContent("Map the invoice process");
    expect(prompt).toHaveTextContent(/reads as a changelog rather than as progress/);

    await userEvent.setup().type(screen.getByLabelText(/One line on what this means/),
                                 "Parts are ordered.");
    await userEvent.setup().click(screen.getByRole("button", { name: /Save change and line/ }));

    await waitFor(() => {
      const patch = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(patch).toBeDefined();
      expect(patch!.url).toBe("/api/tasks/t1/");
      expect(patch!.body).toEqual({
        status: "in_progress", client_facing_line: "Parts are ordered.",
      });
    });
  });

  it("writes nothing at all until the prompt is answered", async () => {
    const fetchMock = open();
    await showBoard();
    drag(card("Map the invoice process"), column("In progress"));
    await screen.findByRole("dialog", { name: "What this means for the client" });
    expect(fetchMock.calls.find((c) => c.method === "PATCH")).toBeUndefined();

    await userEvent.setup().click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock.calls.find((c) => c.method === "PATCH")).toBeUndefined();
  });

  it("skipping the line saves the status alone", async () => {
    const fetchMock = open();
    await showBoard();
    drag(card("Map the invoice process"), column("Blocked"));
    await screen.findByRole("dialog", { name: "What this means for the client" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Skip the line" }));

    await waitFor(() => {
      const patch = fetchMock.calls.find((c) => c.method === "PATCH")!;
      expect(patch.body).toEqual({ status: "blocked" });
    });
  });

  it("a client is not asked for the line — it is the practice's", async () => {
    const fetchMock = open(aMe({ role: "FCC", client_company: "co1" }));
    await showBoard();
    drag(card("Map the invoice process"), column("Done"));

    await waitFor(() => {
      const patch = fetchMock.calls.find((c) => c.method === "PATCH")!;
      expect(patch.body).toEqual({ status: "done" });
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a drop back into the same column does nothing", async () => {
    const fetchMock = open();
    await showBoard();
    drag(card("Map the invoice process"), column("Not started"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "PATCH")).toBeUndefined();
  });

  it("a task the person may not edit is not draggable, and says so if dropped", async () => {
    const fetchMock = open();
    await showBoard();
    expect(card("Theirs to read only")).toHaveAttribute("draggable", "false");

    drag(card("Theirs to read only"), column("Done"));
    expect(await screen.findByText("That task is not yours to change.")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "PATCH")).toBeUndefined();
  });

  it("keeps opening the card as the other way in", async () => {
    open();
    await showBoard();
    expect(within(card("Map the invoice process")).getByRole("link"))
      .toHaveAttribute("href", "/tasks/t1");
  });

  it("the list view is unchanged and has no drag", async () => {
    open();
    await screen.findByRole("table");
    expect(screen.queryByLabelText("Not started column")).not.toBeInTheDocument();
  });
});


describe("Tasks carries the same company dimension as Work", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  const chooser = () => screen.getByLabelText("Filter by client company");
  const projectFilter = () => screen.getByLabelText("Filter by project");
  const assigneeFilter = () => screen.getByLabelText("Filter by assignee");

  /** What the screen last asked the server for — the filters are the server's
   *  work, as they were before this. */
  function asked(fetchMock: ReturnType<typeof open>) {
    return [...fetchMock.calls].reverse()
      .find((c) => c.url.startsWith("/api/tasks/"))!.url;
  }

  it("defaults to all clients, then asks the server for one", async () => {
    const user = userEvent.setup();
    const fetchMock = open();
    await screen.findByRole("table");
    expect(chooser()).toHaveValue("");
    expect(asked(fetchMock)).toBe("/api/tasks/?");

    await user.selectOptions(chooser(), CO2);
    await waitFor(() => expect(asked(fetchMock)).toBe("/api/tasks/?client_company=co-ridge"));

    // The practice's own work has no id, so it travels as its own word.
    await user.selectOptions(chooser(), "internal");
    await waitFor(() => expect(asked(fetchMock)).toBe("/api/tasks/?client_company=internal"));

    await user.selectOptions(chooser(), "");
    await waitFor(() => expect(asked(fetchMock)).toBe("/api/tasks/?"));
  });

  it("narrows the project and assignee filters to that client, as the New task form does",
     async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("table");
    // All clients: everything is on offer.
    expect(within(projectFilter()).getByText("Fleet renewal")).toBeInTheDocument();
    expect(within(assigneeFilter()).getByText("Ridgeline's founder")).toBeInTheDocument();

    await user.selectOptions(chooser(), CO);
    expect(within(projectFilter()).getByText("Order-to-cash")).toBeInTheDocument();
    expect(within(projectFilter()).queryByText("Fleet renewal")).toBeNull();
    expect(within(projectFilter()).queryByText("Our own website")).toBeNull();
    // The practice can always be assigned; only this client's people join them.
    expect(within(assigneeFilter()).getByText("Bryan Baker")).toBeInTheDocument();
    expect(within(assigneeFilter()).getByText("Acme's founder")).toBeInTheDocument();
    expect(within(assigneeFilter()).queryByText("Ridgeline's founder")).toBeNull();
  });

  it("offers the practice's own people alone on internal work", async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole("table");

    await user.selectOptions(chooser(), "internal");
    expect(within(projectFilter()).getByText("Our own website")).toBeInTheDocument();
    expect(within(projectFilter()).queryByText("Order-to-cash")).toBeNull();
    expect(within(assigneeFilter()).getByText("Val the VA")).toBeInTheDocument();
    expect(within(assigneeFilter()).queryByText("Acme's founder")).toBeNull();
  });

  it("drops a project chosen for the client just left, rather than asking for nothing",
     async () => {
    const user = userEvent.setup();
    const fetchMock = open();
    await screen.findByRole("table");

    await user.selectOptions(chooser(), CO);
    await user.selectOptions(projectFilter(), "pr1");
    await waitFor(() => expect(asked(fetchMock))
      .toBe("/api/tasks/?client_company=co-acme&project=pr1"));

    await user.selectOptions(chooser(), CO2);
    expect(projectFilter()).toHaveValue("");
    await waitFor(() => expect(asked(fetchMock)).toBe("/api/tasks/?client_company=co-ridge"));
  });

  it("remembers the client per person, and keeps its own memory from Work's", async () => {
    const user = userEvent.setup();
    open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    await screen.findByRole("table");
    await user.selectOptions(chooser(), CO2);

    cleanup();
    vi.unstubAllGlobals();
    const fetchMock = open(aMe({ role: "FF", email: "bryan@x.invalid" }));
    await screen.findByRole("table");
    expect(chooser()).toHaveValue(CO2);
    expect(asked(fetchMock)).toBe("/api/tasks/?client_company=co-ridge");

    // A colleague on the same laptop is still on all clients.
    cleanup();
    vi.unstubAllGlobals();
    open(aMe({ role: "VA", email: "someone@x.invalid" }));
    await screen.findByRole("table");
    expect(chooser()).toHaveValue("");

    // Each screen remembers its own: narrowing Work does not narrow Tasks.
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.setItem("work-company:alone@x.invalid", JSON.stringify(CO));
    open(aMe({ role: "FF", email: "alone@x.invalid" }));
    await screen.findByRole("table");
    expect(chooser()).toHaveValue("");
  });

  it("leaves the portal alone: no selector, and no companies request", async () => {
    const fetchMock = open(aMe({ role: "FCC", client_company: CO, email: "f@x.invalid" }));
    await screen.findByRole("table");

    expect(screen.queryByLabelText("Filter by client company")).toBeNull();
    expect(projectFilter()).toBeInTheDocument();     // the others are untouched
    expect(asked(fetchMock)).toBe("/api/tasks/?");
    expect(fetchMock.calls.some((c) => c.url.startsWith("/api/companies/"))).toBe(false);
  });
});
