import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CommentsPanel, suggest, typingMention } from "./CommentsPanel";

const PORTAL = {
  level_label: "Viewer", may_create: { task: false, project: false, goal: false },
  edits_goals: false, has_teams_view: false, teams: [], may_propose_goal: false,
};
const COMMENT = {
  id: "c1", body: "On track for Friday.", visibility: "shared", created_at: "2026-10-14T15:00:00Z",
  author: { id: "u1", name: "John Carter" }, acting_user: null,
};

function open(mayComment: boolean) {
  vi.stubGlobal("fetch", mockApi({ "/api/comments/": [COMMENT] }));
  renderRoute(<CommentsPanel target="task" id="k1" me={aMe({
    role: "ECC", client_company: COMPANY_ID,
    portal: { ...PORTAL, may_comment: mayComment } })} />);
}

describe("comments, for someone who only looks (P7 §2.4a)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows a viewer the thread and no box to add to it", async () => {
    open(false);
    expect(await screen.findByText("On track for Friday.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Add a comment")).toBeNull();
    expect(screen.queryByRole("button", { name: "Post comment" })).toBeNull();
  });

  it("offers the box to anyone who may comment", async () => {
    open(true);
    expect(await screen.findByText("On track for Friday.")).toBeInTheDocument();
    expect(screen.getByLabelText("Add a comment")).toBeInTheDocument();
  });
});

describe("@ suggestions in a comment box (2026-10-27)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function staff() {
    const fetchMock = mockApi({
      "/api/comments/mentionable/": (() => ({ body: [
        { id: "u2", name: "Olive Owner" }, { id: "u3", name: "Val Assistant" }] })) as never,
      "/api/comments/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<CommentsPanel target="task" id="k1" me={aMe({ role: "FF" })} />);
    return fetchMock;
  }

  it("suggests names as you type @, and puts the full name in", async () => {
    const user = userEvent.setup();
    staff();
    const box = await screen.findByLabelText("Add a comment") as HTMLTextAreaElement;
    await user.type(box, "Thanks @v");
    const list = await screen.findByRole("listbox", { name: "People to mention" });
    expect(within(list).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Val Assistant"]);
    await user.keyboard("{Enter}");
    expect(box.value).toBe("Thanks @Val Assistant ");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("asks the server who may be mentioned, for the visibility being written", async () => {
    const user = userEvent.setup();
    const fetchMock = staff();
    await screen.findByLabelText("Add a comment");
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.url === "/api/comments/mentionable/?task=k1&visibility=internal")).toBe(true));
    await user.click(screen.getByLabelText("Share this comment with the client"));
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.url === "/api/comments/mentionable/?task=k1&visibility=shared")).toBe(true));
  });

  it("offers nothing for an @ inside a word, and closes on Escape", async () => {
    const user = userEvent.setup();
    staff();
    const box = await screen.findByLabelText("Add a comment");
    await user.type(box, "mail me at bob@o");
    expect(screen.queryByRole("listbox")).toBeNull();
    await user.type(box, " @o");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

describe("where an @ is being typed", () => {
  it("finds the word after an @ at a word's start", () => {
    expect(typingMention("hi @Ol", 6)).toEqual({ start: 3, query: "Ol" });
    expect(typingMention("@", 1)).toEqual({ start: 0, query: "" });
    expect(typingMention("a@b", 3)).toBeNull();
    expect(suggest([{ id: "1", name: "Olive Owner" }], "own")).toHaveLength(1);
  });
});
