import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aTask } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Tasks } from "./Tasks";

const TASKS = [
  aTask({ id: "t1", title: "Map the invoice process", status: "not_started" }),
  aTask({ id: "t2", title: "Theirs to read only", status: "not_started", may_edit: false }),
];

const LISTS = {
  "/api/projects/": [],
  "/api/portal-people/": [],
  "/api/companies/": [],
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
  beforeEach(() => vi.unstubAllGlobals());

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
