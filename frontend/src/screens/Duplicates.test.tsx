import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { Duplicates } from "./Duplicates";

const GROUP = {
  key: "a", reasons: ["same email address", "same name"], suggested_survivor: "old",
  dismissed_pairs: [] as [string, string][],
  contacts: [
    { id: "old", name: "Mike Eller", company: "", emails: ["eller.mike@populist.test"],
      created_at: "2026-09-22T22:52:22Z", last_meeting: "2026-09-10", meetings: 1,
      tasks: 9, notes: 0 },
    { id: "new", name: "Mike Eller", company: "", emails: ["eller.mike@populist.test"],
      created_at: "2026-09-28T16:43:07Z", last_meeting: "2026-09-10", meetings: 1,
      tasks: 0, notes: 0 },
  ],
};

describe("merge duplicates (owner, 2026-09-29)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function show(groups: unknown[]) {
    const fetchMock = mockApi({
      "GET /api/contacts/duplicate-groups/": groups,
      "POST /api/contacts/merge-group/": { id: "old" },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Duplicates />, { path: "/contacts/duplicates", route: "/contacts/duplicates" });
    return fetchMock;
  }

  it("shows each group with why, and what tells its members apart", async () => {
    show([GROUP]);
    expect(await screen.findByText("same email address")).toBeInTheDocument();
    expect(screen.getByText(/9 tasks, 0 notes · added 2026-09-22/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /added 2026-09-22/ })).toBeChecked();
  });

  it("merges the rest into the chosen survivor in one click", async () => {
    const user = userEvent.setup();
    const fetchMock = show([GROUP]);
    await user.click(await screen.findByRole("radio", { name: /added 2026-09-28/ }));
    await user.click(screen.getByRole("button", { name: "Merge into Mike Eller (a)" }));
    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.url.endsWith("/merge-group/"));
      expect(post?.body).toEqual({ survivor: "new", absorbed: ["old"] });
    });
    expect(await screen.findByText("Merged 1 into Mike Eller.")).toBeInTheDocument();
  });

  it("says plainly when there is nothing to merge", async () => {
    show([]);
    expect(await screen.findByText(/No likely duplicates/)).toBeInTheDocument();
  });

  it("marks a group not duplicates, and Undo takes it back (2026-10-03)", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/contacts/not-duplicates/": (body: unknown) =>
        ({ body: (body as { undo?: boolean }).undo ? { undone: 1 } : { dismissed: 1 } }),
      "GET /api/contacts/duplicate-groups/": [GROUP],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Duplicates />, { path: "/contacts/duplicates", route: "/contacts/duplicates" });
    await user.click(await screen.findByRole("button", { name: "Not duplicates (a)" }));
    expect(await screen.findByText(/won't be suggested together again/)).toBeInTheDocument();
    const sent = fetchMock.calls.filter((c) => c.url === "/api/contacts/not-duplicates/");
    expect(sent[0].body).toEqual({ contacts: ["old", "new"] });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText(/they are back in the list/)).toBeInTheDocument();
    expect(fetchMock.calls.filter((c) => c.url === "/api/contacts/not-duplicates/")[1].body)
      .toEqual({ contacts: ["old", "new"], undo: true });
  });

  it("says when a group is back only because a newer contact matches", async () => {
    show([{ ...GROUP, dismissed_pairs: [["new", "old"]] }]);
    expect(await screen.findByText(/were already marked not\s+duplicates/)).toBeInTheDocument();
  });
});
