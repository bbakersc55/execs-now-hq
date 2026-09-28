import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aTask } from "../test/fixtures";
import { ToastHost } from "../components/ui";
import { mockApi } from "../test/render";
import { Tasks } from "./Tasks";

const TASK = aTask({ id: "t1", title: "Map the invoice process", status: "not_started" });

/** Where the router is, for asserting where a close lands. */
function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

/**
 * The board with the sheet open over it, both routes live, as the app has
 * them. `history` is what the browser has behind the sheet: by default nothing,
 * which is a sheet opened from a direct link.
 */
function openSheet(routes: Record<string, unknown> = {},
                   history: string[] = ["/tasks/t1"]) {
  const fetchMock = mockApi({
    ...routes,
    "/api/tasks/t1/updates/": [],
    "/api/tasks/t1/checklist/": [],
    "DELETE /api/tasks/t1/": () => ({ status: 204, body: null }),
    "/api/tasks/t1/": TASK,
    "/api/tasks/": [TASK],
    "/api/comments/": [],
    "/api/notes/": [],
    "/api/projects/": [],
    "/api/portal-people/": [],
    "/api/companies/": [],
    "/api/contacts/": [],
    "/api/goals/": [],
    // Twice: first so a test's own routes are matched before the defaults
    // (matching is by prefix, in order), and again so its values win.
    ...routes,
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={history} initialIndex={history.length - 1}>
        <Routes>
          <Route path="/tasks" element={<Tasks me={aMe()} />} />
          <Route path="/tasks/:id" element={<Tasks me={aMe()} />} />
          <Route path="/work" element={<h1>Work screen</h1>} />
        </Routes>
        <Where />
        <ToastHost />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const sheet = () => document.querySelector(".sheet") as HTMLElement | null;
const where = () => screen.getByTestId("where").textContent;

/**
 * "Save changes" ends an edit, so it closes the sheet and the board says so.
 * Every other change on the sheet is one of several, so it confirms in place.
 */
describe("the task sheet: what closes it and what does not", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("closes after Save changes and says Saved on the board", async () => {
    const user = userEvent.setup();
    const fetchMock = openSheet({
      "PATCH /api/tasks/t1/": { ...TASK, title: "Map the invoice process end to end" },
    });

    await user.click(await screen.findByRole("button", { name: "Edit task" }));
    await user.type(screen.getByLabelText("Title"), " end to end");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(sheet()).toBeNull());
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    expect(fetchMock.calls.find((c) => c.method === "PATCH")!.body)
      .toEqual({ title: "Map the invoice process end to end" });
  });

  it("stays open, with the form and the error, when the save fails", async () => {
    const user = userEvent.setup();
    openSheet({
      "PATCH /api/tasks/t1/": () => ({ status: 400, body: { detail: "Title is too long." } }),
    });

    await user.click(await screen.findByRole("button", { name: "Edit task" }));
    await user.type(screen.getByLabelText("Title"), "!");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await within(sheet()!).findByText(/Title is too long/)).toBeInTheDocument();
    expect(within(sheet()!).getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("keeps the sheet open on an inline change and confirms it there", async () => {
    const user = userEvent.setup();
    openSheet({ "PATCH /api/tasks/t1/": { ...TASK, priority: 3 } });

    await user.selectOptions(await screen.findByLabelText("Priority"), "3");

    await waitFor(() => expect(within(sheet()!).getByText("Saved")).toBeInTheDocument());
    expect(sheet()).not.toBeNull();
  });

  it("keeps the sheet open on a step and says the step was added", async () => {
    const user = userEvent.setup();
    openSheet({ "POST /api/tasks/t1/checklist/": { id: "s1", text: "Pull the AR aging",
                                                   is_done: false } });

    await user.type(await screen.findByLabelText("New step"), "Pull the AR aging");
    await user.click(screen.getByRole("button", { name: "Add step" }));

    expect(await within(sheet()!).findByText("Step added")).toBeInTheDocument();
  });

  it("keeps the sheet open on a comment and says it was posted", async () => {
    const user = userEvent.setup();
    openSheet({ "POST /api/comments/": { id: "c1" } });

    await user.type(await screen.findByLabelText("Add a comment"), "Called their AP lead.");
    await user.click(screen.getByRole("button", { name: "Post comment" }));

    expect(await within(sheet()!).findByText("Posted")).toBeInTheDocument();
  });

  it("keeps the sheet open on a client line and says it was added", async () => {
    const user = userEvent.setup();
    openSheet({ "POST /api/tasks/t1/narrative/": {} });

    await user.type(await screen.findByLabelText("Client-facing line"),
                    "Invoices now go out the same day.");
    await user.click(screen.getByRole("button", { name: "Add it" }));

    expect(await within(sheet()!).findByText("Added")).toBeInTheDocument();
  });
});

/**
 * Every way out of the sheet goes back to where it was opened from, with that
 * screen as it was. Only a sheet with nothing behind it lands on the board.
 */
describe("the task sheet: where closing it takes you", () => {
  beforeEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  /** Opened the way a person does: from the board, after narrowing it. */
  async function fromTheFilteredBoard(routes: Record<string, unknown> = {}) {
    const user = userEvent.setup();
    openSheet(routes, ["/tasks"]);
    await user.type(await screen.findByLabelText("Search tasks"), "invoice");
    await user.click(await screen.findByRole("link", { name: /Map the invoice process/ }));
    await within(await waitFor(() => sheet()!)).findByRole("button", { name: "Edit task" });
    return user;
  }

  async function backOnTheBoard() {
    await waitFor(() => expect(sheet()).toBeNull());
    expect(where()).toBe("/tasks");
    expect(screen.getByLabelText("Search tasks")).toHaveValue("invoice");
  }

  it("Escape goes back to the board with its filters", async () => {
    const user = await fromTheFilteredBoard();
    await user.keyboard("{Escape}");
    await backOnTheBoard();
  });

  it("the close button goes back to the board with its filters", async () => {
    const user = await fromTheFilteredBoard();
    await user.click(within(sheet()!).getByRole("button", { name: "Close" }));
    await backOnTheBoard();
  });

  it("Save changes goes back to the board with its filters, and says Saved", async () => {
    const user = await fromTheFilteredBoard({ "PATCH /api/tasks/t1/": TASK });
    await user.click(within(sheet()!).getByRole("button", { name: "Edit task" }));
    await user.type(screen.getByLabelText("Title"), "!");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await backOnTheBoard();
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("the list view survives the round trip too", async () => {
    localStorage.setItem("enhq.tasks.board", "0");
    const user = userEvent.setup();
    openSheet({}, ["/tasks"]);
    await user.click(await screen.findByRole("link", { name: /Map the invoice process/ }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(sheet()).toBeNull());
    expect(screen.queryByLabelText("Board")).not.toBeInTheDocument();
  });

  it("goes back to Work when it was opened from Work", async () => {
    const user = userEvent.setup();
    openSheet({}, ["/work", "/tasks/t1"]);
    await within(await waitFor(() => sheet()!)).findByRole("button", { name: "Edit task" });
    await user.keyboard("{Escape}");
    expect(await screen.findByRole("heading", { name: "Work screen" })).toBeInTheDocument();
  });

  it("lands on the board when it was opened from a direct link", async () => {
    const user = userEvent.setup();
    openSheet();
    await within(await waitFor(() => sheet()!)).findByRole("button", { name: "Edit task" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(sheet()).toBeNull());
    expect(where()).toBe("/tasks");
  });

  it("a delete goes back to the board, not Work, and says Deleted", async () => {
    const user = await fromTheFilteredBoard();
    await user.click(within(sheet()!).getByRole("button", { name: "Delete this task" }));
    await backOnTheBoard();
    expect(await screen.findByRole("status")).toHaveTextContent("Deleted");
  });

  it("a delete from a direct link lands on the board, not Work", async () => {
    const user = userEvent.setup();
    const fetchMock = openSheet();
    await user.click(await screen.findByRole("button", { name: "Delete this task" }));
    await waitFor(() => expect(sheet()).toBeNull());
    expect(where()).toBe("/tasks");
    expect(await screen.findByRole("status")).toHaveTextContent("Deleted");
    expect(fetchMock.calls.some((c) => c.method === "DELETE")).toBe(true);
  });
});

/**
 * 2026-09-28 — three "Follow up" tasks made by the Phase 1 stage automation
 * looked as if they would not open. The title line opened them; the rest of
 * the card, four fifths of it on a one-line title, showed a pointer and did
 * nothing. Every task opens from anywhere on its card, and a task that cannot
 * be opened says so.
 */
describe("the task sheet: every task opens, or says why not", () => {
  beforeEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  /** Shaped as the stage automation makes it: internal, unassigned, no history. */
  const FROM_AUTOMATION = aTask({
    id: "t1", title: "Follow up", status: "not_started", due_date: "2026-09-14",
    client_company: null, client_company_name: "", project: null, goal: null,
    assignee: { id: null, name: "" }, client_owner_contact: { id: null, name: "" },
    owner: { id: "u1", name: "Bryan Baker" }, is_client_visible: false,
  });

  function board(detail: unknown = FROM_AUTOMATION, list: unknown[] = [FROM_AUTOMATION]) {
    return openSheet({
      "/api/tasks/t1/updates/": [], "/api/tasks/t1/checklist/": [],
      "/api/tasks/t1/": detail, "/api/tasks/": list,
    }, ["/tasks"]);
  }

  it("opens from a click anywhere on the card, not only the title", async () => {
    const user = userEvent.setup();
    board();
    await user.click(await screen.findByText("overdue 2026-09-14"));
    await waitFor(() => expect(where()).toBe("/tasks/t1"));
    expect(await within(sheet()!).findByRole("heading", { name: "Follow up" }))
      .toBeInTheDocument();
  });

  it("opens from a double click on the card too", async () => {
    const user = userEvent.setup();
    board();
    const card = (await screen.findByRole("link", { name: "Follow up" })).closest(".task-card")!;
    await user.dblClick(card);
    expect(await within(await waitFor(() => sheet()!))
      .findByRole("heading", { name: "Follow up" })).toBeInTheDocument();
  });

  it("still opens from the title link", async () => {
    const user = userEvent.setup();
    board();
    await user.click(await screen.findByRole("link", { name: "Follow up" }));
    expect(await within(await waitFor(() => sheet()!))
      .findByRole("heading", { name: "Follow up" })).toBeInTheDocument();
  });

  it("says why when the task fails to load, rather than calling it a permission", async () => {
    const user = userEvent.setup();
    openSheet({
      "/api/tasks/t1/updates/": [], "/api/tasks/t1/checklist/": [],
      "/api/tasks/t1/": () => ({ status: 500, body: { detail: "Server error" } }),
      "/api/tasks/": [FROM_AUTOMATION],
    }, ["/tasks"]);
    await user.click(await screen.findByText("overdue 2026-09-14"));
    expect(await within(await waitFor(() => sheet()!))
      .findByText(/This task could not be opened/)).toBeInTheDocument();
  });

  it("shows a task that cannot be drawn as an error inside the sheet", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    // No assignee object at all: the sheet cannot render this.
    board({ ...FROM_AUTOMATION, assignee: null });
    await user.click(await screen.findByText("overdue 2026-09-14"));
    const panel = await waitFor(() => sheet()!);
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/failed to render/);
    // The board behind it is still there.
    expect(screen.getByLabelText("Board")).toBeInTheDocument();
  });

  it("says so when a card has no id to open", async () => {
    const user = userEvent.setup();
    board(FROM_AUTOMATION, [{ ...FROM_AUTOMATION, id: "" }]);
    await user.click(await screen.findByText("overdue 2026-09-14"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be opened/);
    expect(sheet()).toBeNull();
  });
});
