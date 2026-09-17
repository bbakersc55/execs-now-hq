import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Activity } from "./Activity";

const CO = { id: "co1", name: "Acme Foods", is_client_company: true };

const ENTRIES = [
  { id: "c-1", at: "2026-09-15T15:00:00Z", category: "comment", kind: "internal",
    text: "left an internal comment on “Fix the loading dock”: their AP clerk is the bottleneck",
    entity: { type: "task", id: "t1", title: "Fix the loading dock" },
    company: CO, contact: null, by: "Bryan Baker", on_behalf_of: "Priya Shah" },
  { id: "u-1", at: "2026-09-15T14:00:00Z", category: "work", kind: "status_changed",
    text: "moved “Fix the loading dock” from Not started to In progress",
    entity: { type: "task", id: "t1", title: "Fix the loading dock" },
    company: CO, contact: null, by: "Dana Reyes", on_behalf_of: null },
  { id: "a-1", at: "2026-09-15T13:00:00Z", category: "pipeline", kind: "stage.changed",
    text: "moved Ola New to a new stage", entity: null,
    company: null, contact: { id: "ct1", name: "Ola New" },
    by: "Bryan Baker", on_behalf_of: null },
];

const LISTS = {
  "/api/companies/": [CO],
  "/api/contacts/": [{ id: "ct1", first_name: "Ola", last_name: "New", company: "co1" }],
  "/api/portal-people/": [{ id: "u1", name: "Bryan Baker", role: "FF", company: null }],
};

function open(me = aMe({ role: "FF" }), routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ ...LISTS, "/api/activity/": ENTRIES, ...routes });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Activity me={me} />);
  return fetchMock;
}

describe("the practice's activity feed (FR-3.41a — it was the client's)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists everything across the accounts, saying who acted on whose behalf", async () => {
    open();
    const acted = await screen.findByText(/their AP clerk is the bottleneck/);
    expect(acted.closest("li")).toHaveTextContent("Bryan Baker on behalf of Priya Shah");
    const plain = screen.getByText(/from Not started to In progress/).closest("li")!;
    expect(plain).toHaveTextContent("Dana Reyes moved");
    expect(plain).not.toHaveTextContent("on behalf of");
    // The company and contact each row belongs to, and a way into it.
    expect(plain).toHaveTextContent("Acme Foods");
    expect(screen.getByText(/moved Ola New to a new stage/).closest("li"))
      .toHaveTextContent("Ola New");
    expect(screen.getAllByRole("link", { name: "open" })[0]).toHaveAttribute("href", "/tasks/t1");
  });

  it("shows internal comments, which the client's log never did", async () => {
    open();
    expect(await screen.findByText(/their AP clerk is the bottleneck/)).toBeInTheDocument();
    expect(screen.getByText(/left an internal comment/)).toBeInTheDocument();
  });

  it("sends every filter to the server and can clear them again", async () => {
    const user = userEvent.setup();
    const fetchMock = open();
    await screen.findByText(/from Not started to In progress/);

    await user.selectOptions(screen.getByLabelText("Filter by company"), "co1");
    await user.selectOptions(screen.getByLabelText("Filter by contact"), "ct1");
    await user.selectOptions(screen.getByLabelText("Filter by who acted"), "u1");
    await user.selectOptions(screen.getByLabelText("Filter by type"), "pipeline");
    await user.type(screen.getByLabelText("From date"), "2026-09-01");
    await user.type(screen.getByLabelText("To date"), "2026-09-30");

    await waitFor(() => {
      const last = fetchMock.calls.filter((c) => c.url.startsWith("/api/activity/")).pop()!;
      expect(last.url).toContain("company=co1");
      expect(last.url).toContain("contact=ct1");
      expect(last.url).toContain("actor=u1");
      expect(last.url).toContain("category=pipeline");
      expect(last.url).toContain("since=2026-09-01T00%3A00%3A00");
      expect(last.url).toContain("until=2026-09-30T23%3A59%3A59");
    });

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => {
      const last = fetchMock.calls.filter((c) => c.url.startsWith("/api/activity/")).pop()!;
      expect(last.url).toBe("/api/activity/?");
    });
  });

  it("offers no control that could change an entry", async () => {
    open();
    await screen.findByText(/from Not started to In progress/);
    // Filters are the only controls; nothing writes.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save|edit|delete|remove/i }))
      .not.toBeInTheDocument();
    expect(screen.getByText(/Nobody can edit or remove an entry/)).toBeInTheDocument();
  });

  it("asks nothing of the server for a client, who is refused it", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Activity me={aMe({ role: "ECC", client_company: "co1" })} />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("Not available.")).toBeInTheDocument();
  });
});
