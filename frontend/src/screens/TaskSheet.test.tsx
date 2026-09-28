import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aTask } from "../test/fixtures";
import { mockApi } from "../test/render";
import { Tasks } from "./Tasks";

const TASK = aTask({ id: "t1", title: "Map the invoice process", status: "not_started" });

/** The board with the sheet open over it, both routes live, as the app has them. */
function openSheet(routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...routes,
    "/api/tasks/t1/updates/": [],
    "/api/tasks/t1/checklist/": [],
    "/api/tasks/t1/": TASK,
    "/api/tasks/": [TASK],
    "/api/comments/": [],
    "/api/notes/": [],
    "/api/projects/": [],
    "/api/portal-people/": [],
    "/api/companies/": [],
    "/api/contacts/": [],
    "/api/goals/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tasks/t1"]}>
        <Routes>
          <Route path="/tasks" element={<Tasks me={aMe()} />} />
          <Route path="/tasks/:id" element={<Tasks me={aMe()} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const sheet = () => document.querySelector(".sheet") as HTMLElement | null;

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
