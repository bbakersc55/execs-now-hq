import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aNote } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Notes } from "./Notes";

const LIST = [
  { id: "n1", title: "Acme kickoff", is_locked: false,
    created_at: "2026-09-20T09:00:00Z", contact: "c1", contact_name: "Dana Reyes",
    company: null, company_name: "", task: null, task_title: "" },
  { id: "n2", title: "Private thoughts", is_locked: true,
    created_at: "2026-09-21T09:00:00Z", contact: null, contact_name: "",
    company: null, company_name: "", task: null, task_title: "" },
];

const OPEN = aNote({ id: "n1", title: "Acme kickoff", title_is_auto: false,
                     body: "Dispatch is the bottleneck.",
                     contact: "c1", contact_name: "Dana Reyes" });

function show(route = "/notes", extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/notes/settings/": { audio_retention_days: 30 },
    "GET /api/notes/n1/": OPEN,
    "GET /api/notes/": LIST,
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Notes me={aMe()} />, { path: "/notes/:id?", route });
  return fetchMock;
}

/**
 * Notes as a panel (design brief, Tier 2): **list on the left, note on the
 * right**. A note is read in the context of the others, so the others stay on
 * screen while one is open.
 */
describe("the notes panel", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists notes beside an empty right-hand pane", async () => {
    show();

    expect(await screen.findByRole("link", { name: /Acme kickoff/ }))
      .toBeInTheDocument();
    expect(screen.getByText(/Choose a note to read it here/)).toBeInTheDocument();
  });

  it("opens a note beside the list, not instead of it", async () => {
    show("/notes/n1");

    // The note is open…
    expect(await screen.findByText("Dispatch is the bottleneck.")).toBeInTheDocument();
    // …and the list is still there, with the open one marked.
    const link = screen.getByRole("link", { name: /Acme kickoff/ });
    expect(link).toHaveClass("on");
    expect(screen.getByRole("link", { name: /Private thoughts/ })).toBeInTheDocument();
    // No "back to notes" link: it would point at where you already are.
    expect(screen.queryByRole("link", { name: /← Notes/ })).not.toBeInTheDocument();
  });

  it("marks a locked note in the list without opening it", async () => {
    show();

    const locked = await screen.findByRole("link", { name: /Private thoughts/ });
    expect(within(locked).getByText(/🔒/)).toBeInTheDocument();
  });

  it("searches as you type, with no button to press", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("link", { name: /Acme kickoff/ });

    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search notes" }), "acme");

    await vi.waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.includes("q=acme"))).toBe(true));
  });

  it("says when a search matches nothing, differently from having nothing", async () => {
    const user = userEvent.setup();
    show("/notes", { "GET /api/notes/": (() => {
      let first = true;
      return () => {
        const body = first ? LIST : [];
        first = false;
        return { status: 200, body };
      };
    })() });
    await screen.findByRole("link", { name: /Acme kickoff/ });

    await user.type(screen.getByRole("searchbox", { name: "Search notes" }), "zzz");

    expect(await screen.findByText("No notes match that search.")).toBeInTheDocument();
  });
});
