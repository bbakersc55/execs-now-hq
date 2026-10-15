import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CommentsPanel } from "./CommentsPanel";

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
