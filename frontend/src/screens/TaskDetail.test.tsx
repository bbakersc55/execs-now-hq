import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID, TASK_ID, aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { TaskDetail } from "./TaskDetail";

function show(task = aTask(), extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    [`/api/tasks/${TASK_ID}/updates/`]: [],
    [`/api/tasks/${TASK_ID}/checklist/`]: [],
    [`/api/comments/?task=${TASK_ID}`]: [],
    "/api/notes/": [],
    ...extra,
    [`/api/tasks/${TASK_ID}/`]: task,
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = renderRoute(<TaskDetail me={me} />, { path: "/tasks/:id", route: `/tasks/${TASK_ID}` });
  return { fetchMock, ...view };
}

function patchBody(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.calls.find((c) => c.method === "PATCH")?.body as Record<string, unknown>;
}

describe("AC-3.3 — the client-facing line is prompted, not forced", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks for the line on a status change, and explains why", async () => {
    const user = userEvent.setup();
    show();
    await user.selectOptions(await screen.findByLabelText("Status"), "in_progress");
    const dialog = screen.getByRole("dialog", { name: /what this means for the client/i });
    expect(dialog).toHaveTextContent("optional");
    expect(dialog).toHaveTextContent(/reads as a changelog rather than as progress/);
  });

  it("saves the status change alone when the line is skipped", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask(), {
      [`PATCH /api/tasks/${TASK_ID}/`]: aTask({ status: "in_progress" }),
    });
    await user.selectOptions(await screen.findByLabelText("Status"), "in_progress");
    await user.click(screen.getByRole("button", { name: "Skip the line" }));
    await waitFor(() => expect(patchBody(fetchMock)).toEqual({ status: "in_progress" }));
  });

  it("sends the line with the change when one is written", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask(), {
      [`PATCH /api/tasks/${TASK_ID}/`]: aTask({ status: "waiting_on_client" }),
    });
    await user.selectOptions(await screen.findByLabelText("Status"), "waiting_on_client");
    await user.type(screen.getByLabelText(/One line on what this means/),
                    "We need your AP login to finish.");
    await user.click(screen.getByRole("button", { name: /Save change and line/ }));
    await waitFor(() => expect(patchBody(fetchMock)).toEqual({
      status: "waiting_on_client", client_facing_line: "We need your AP login to finish.",
    }));
  });

  it("does not prompt a client user — the line is the practice's", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask(), {
      [`PATCH /api/tasks/${TASK_ID}/`]: aTask({ status: "done" }),
    }, aMe({ role: "FCC", client_company: "co-1" }));
    await user.selectOptions(await screen.findByLabelText("Status"), "done");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(patchBody(fetchMock)).toEqual({ status: "done" }));
  });
});

describe("a task the client may not edit", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says so, and offers a comment instead (FR-3.9a)", async () => {
    show(aTask({ may_edit: false, may_delete: false, may_set_visibility: false }),
         {}, aMe({ role: "FCC", client_company: "co-1" }));
    expect(await screen.findByText(/the practice's to change/)).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toBeDisabled();
    expect(screen.getByLabelText("Add a comment")).toBeInTheDocument();
    expect(screen.queryByLabelText("Visible to the client")).not.toBeInTheDocument();
  });
});

describe("AC-3.4 in the UI — internal by default, and unmistakable", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("defaults a tenant comment to internal and says what will happen", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask(), {
      "POST /api/comments/": { id: "c1", body: "x", visibility: "internal",
                               author: { id: "u1", name: "Bryan" },
                               created_at: "2026-09-11T15:00:00Z",
                               task: TASK_ID, project: null, goal: null },
    });
    const box = await screen.findByLabelText("Add a comment");
    expect(screen.getByText("Internal only — the client will not see this.")).toBeInTheDocument();
    await user.type(box, "Their AP clerk is the bottleneck.");
    await user.click(screen.getByRole("button", { name: "Post comment" }));
    await waitFor(() => expect(
      fetchMock.calls.find((c) => c.url === "/api/comments/")?.body,
    ).toMatchObject({ visibility: "internal" }));
  });

  it("warns when the comment will be shared", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask(), {
      "POST /api/comments/": { id: "c2", body: "x", visibility: "shared",
                               author: { id: "u1", name: "Bryan" },
                               created_at: "2026-09-11T15:00:00Z",
                               task: TASK_ID, project: null, goal: null },
    });
    await user.type(await screen.findByLabelText("Add a comment"), "Mapped the flow.");
    await user.click(screen.getByLabelText("Share this comment with the client"));
    expect(screen.getByText("The client will see this comment.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Post shared comment" }));
    await waitFor(() => expect(
      fetchMock.calls.find((c) => c.url === "/api/comments/")?.body,
    ).toMatchObject({ visibility: "shared" }));
  });

  it("offers a client user no visibility choice at all", async () => {
    show(aTask(), {}, aMe({ role: "ECC", client_company: "co-1" }));
    expect(await screen.findByLabelText("Add a comment")).toBeInTheDocument();
    expect(screen.queryByLabelText("Share this comment with the client")).not.toBeInTheDocument();
    expect(screen.getByText("Your comments are shared with the practice.")).toBeInTheDocument();
  });
});

describe("a client edits and comments on a task (FR-3.9a)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const anEcc = () => aMe({ role: "ECC", client_company: COMPANY_ID });
  const PROJECTS = [
    aWorkParent({ id: "pr1", kind: "project", title: "Our tidy-up", client_company: COMPANY_ID }),
    aWorkParent({ id: "pr9", kind: "project", title: "Someone else's", client_company: "co-2" }),
  ];
  const PEOPLE = [
    { id: "u1", name: "Dana Reyes", role: "FCC", company: COMPANY_ID },
    { id: "u2", name: "Priya Shah", role: "ECC", company: COMPANY_ID },
    { id: "u9", name: "Bryan Baker", role: "FF", company: null },
    { id: "u8", name: "Sam Other", role: "ECC", company: "co-2" },
  ];
  const options = (label: string) =>
    Array.from((screen.getByLabelText(label) as HTMLSelectElement).options).map((o) => o.text);

  it("edits title, project and assignee, offering only their own company's", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(
      aTask({ created_by_client: true, may_set_visibility: false,
              assignee: { id: "u1", name: "Dana Reyes" } }),
      {
        [`PATCH /api/tasks/${TASK_ID}/`]: aTask({ title: "Chase the supplier twice" }),
        "/api/projects/": PROJECTS, "/api/portal-people/": PEOPLE,
      },
      anEcc(),
    );

    await user.click(await screen.findByRole("button", { name: "Edit task" }));
    await waitFor(() => expect(options("Project")).toEqual(["No project", "Our tidy-up"]));
    await waitFor(() => expect(options("Assignee")).toEqual(["Unassigned", "Dana Reyes", "Priya Shah"]));

    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Chase the supplier twice");
    await user.selectOptions(screen.getByLabelText("Project"), "pr1");
    await user.selectOptions(screen.getByLabelText("Assignee"), "u2");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    // Only what changed is sent.
    await waitFor(() => expect(patchBody(fetchMock)).toEqual({
      title: "Chase the supplier twice", project: "pr1", assignee: "u2",
    }));
  });

  it("offers no edit when the task is the practice's", async () => {
    show(aTask({ may_edit: false, may_delete: false, may_set_visibility: false }), {}, anEcc());
    expect(await screen.findByText(/the practice's to change/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit task" })).not.toBeInTheDocument();
  });

  it("does not let saving go out with nothing changed", async () => {
    const user = userEvent.setup();
    show(aTask({ created_by_client: true }), {
      "/api/projects/": PROJECTS, "/api/portal-people/": PEOPLE,
    }, anEcc());
    await user.click(await screen.findByRole("button", { name: "Edit task" }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("posts a comment, shared by definition, with no visibility sent", async () => {
    const user = userEvent.setup();
    const { fetchMock } = show(aTask({ may_edit: false, may_delete: false }), {
      "POST /api/comments/": { id: "c3", body: "Can we move this to Friday?", visibility: "shared",
                               author: { id: "u2", name: "Priya Shah" },
                               created_at: "2026-09-14T15:00:00Z",
                               task: TASK_ID, project: null, goal: null },
    }, anEcc());
    await user.type(await screen.findByLabelText("Add a comment"), "Can we move this to Friday?");
    await user.click(screen.getByRole("button", { name: "Post comment" }));
    await waitFor(() => expect(
      fetchMock.calls.find((c) => c.method === "POST" && c.url === "/api/comments/")?.body,
    ).toEqual({ task: TASK_ID, body: "Can we move this to Friday?" }));
  });
});

describe("the six statuses", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("renders each one distinctly, and waiting-on-client is its own", async () => {
    const { container } = show(aTask({ status: "waiting_on_client" }));
    await screen.findByLabelText("Status");
    const pill = container.querySelector(".pill.status-waiting_on_client");
    expect(pill).toBeTruthy();
    expect(pill).toHaveTextContent("Waiting on client");
    // Not styled as "blocked": the two are different things (FR-3.8).
    expect(container.querySelector(".pill.status-blocked")).toBeFalsy();
    // All six are offered, each with its own label.
    const options = [...container.querySelectorAll('select[aria-label="Status"] option')]
      .map((o) => o.textContent);
    expect(options).toEqual(["Not started", "In progress", "Blocked", "Waiting on client",
                             "Done", "Cancelled"]);
  });
});
