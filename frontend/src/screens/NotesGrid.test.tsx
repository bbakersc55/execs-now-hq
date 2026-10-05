import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aNote } from "../test/fixtures";
import { mockApi } from "../test/render";
import { Notes } from "./Notes";

const CARDS = [
  { id: "n2", title: "Private thoughts", is_locked: true, created_at: "2026-09-21T15:00:00Z" },
  { id: "n1", title: "Acme kickoff", is_locked: false, created_at: "2026-09-20T15:00:00Z" },
];
const OPTIONS = {
  companies: [{ id: "co1", name: "Acme Freight" }],
  contacts: [{ id: "c1", name: "Dana Reyes" }],
};
const grid = (results = CARDS, total = results.length) => ({ total, results, ...OPTIONS });

const OPEN = aNote({ id: "n1", title: "Acme kickoff", title_is_auto: false,
                     body: "Dispatch is the bottleneck.",
                     contact: "c1", contact_name: "Dana Reyes" });

function Address() {
  const location = useLocation();
  return <output aria-label="address">{location.pathname + location.search}</output>;
}

function show(route = "/notes", extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    "GET /api/notes/settings/": { audio_retention_days: 30 },
    "GET /api/notes/n1/": OPEN,
    ...extra,
    "GET /api/notes/browse/": grid(),
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
      <MemoryRouter initialEntries={[route]}>
        <Address />
        <Routes>
          <Route path="/notes" element={<Notes me={me} />} />
          <Route path="/notes/:id" element={<Notes me={me} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

/** The query string of the latest request for the grid. */
function asked(fetchMock: ReturnType<typeof mockApi>) {
  const urls = fetchMock.calls.map((c) => c.url).filter((u) => u.includes("/browse/"));
  return new URLSearchParams(urls[urls.length - 1].split("?")[1]);
}

/**
 * Notes as a grid of cards (UI spec §9): each note is a card with its name and
 * its date, and a note opens as the page.
 */
describe("the notes grid", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows each note as a card with its name, its date and nothing else", async () => {
    const fetchMock = show();

    const card = await screen.findByRole("link", { name: /Acme kickoff/ });
    expect(card).toHaveClass("note-card");
    expect(card).toHaveAttribute("href", "/notes/n1");
    expect(card).toHaveTextContent(/^Acme kickoffSep 20, 2026$/);
    // The latest twenty, until asked for more.
    expect(asked(fetchMock).get("limit")).toBe("20");
  });

  it("marks a locked note with a lock and shows no more of it", async () => {
    show();

    const locked = await screen.findByRole("link", { name: /Private thoughts/ });
    expect(within(locked).getByLabelText("Locked")).toBeInTheDocument();
    const open = screen.getByRole("link", { name: /Acme kickoff/ });
    expect(within(open).queryByLabelText("Locked")).not.toBeInTheDocument();
  });

  it("offers older notes when there are more than the latest twenty", async () => {
    const user = userEvent.setup();
    const fetchMock = show("/notes", { "GET /api/notes/browse/?limit=20": grid(CARDS, 143) });

    expect(await screen.findByText("Latest 2 of 143 notes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show older" }));

    await vi.waitFor(() => expect(asked(fetchMock).get("limit")).toBe("40"));
  });

  it("has no Show older when everything is already shown", async () => {
    show();
    expect(await screen.findByText("2 notes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show/ })).not.toBeInTheDocument();
  });

  it("searches as you type, and asks for every match rather than twenty", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("link", { name: /Acme kickoff/ });

    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search notes" }), "acme");

    await vi.waitFor(() => expect(asked(fetchMock).get("q")).toBe("acme"));
    expect(asked(fetchMock).get("limit")).toBe("200");
    expect(await screen.findByText("2 notes match")).toBeInTheDocument();
  });

  it("filters by company, contact, date and name, each shown as a chip", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("link", { name: /Acme kickoff/ });

    await user.selectOptions(screen.getByLabelText("Filter by company"), "co1");
    await user.selectOptions(screen.getByLabelText("Filter by contact"), "c1");
    await user.selectOptions(screen.getByLabelText("Filter by date"), "7");
    await user.type(screen.getByLabelText("Filter by name"), "kick");

    await vi.waitFor(() => expect(asked(fetchMock).get("name")).toBe("kick"));
    const sent = asked(fetchMock);
    expect(sent.get("company")).toBe("co1");
    expect(sent.get("contact")).toBe("c1");
    // Seven days back from the start of today, and open-ended.
    const after = new Date(sent.get("after")!);
    const days = (Date.now() - after.getTime()) / 86_400_000;
    expect(days).toBeGreaterThanOrEqual(7);
    expect(days).toBeLessThan(8);
    expect(sent.get("before")).toBeNull();

    for (const chip of ["Company: Acme Freight", "Contact: Dana Reyes",
                        "Date: Last 7 days", "Name: kick"]) {
      expect(screen.getByRole("button", { name: `Clear filter ${chip}` })).toBeInTheDocument();
    }
    // Said where the filter is, not left to be discovered.
    expect(screen.getByText(/Locked notes are left out of the company and contact filters/))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filter Company: Acme Freight" }));
    await vi.waitFor(() => expect(asked(fetchMock).get("company")).toBeNull());
    expect(asked(fetchMock).get("contact")).toBe("c1");
  });

  it("takes a custom date range as whole days", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("link", { name: /Acme kickoff/ });

    await user.selectOptions(screen.getByLabelText("Filter by date"), "custom");
    await user.type(screen.getByLabelText("From date"), "2026-09-01");
    await user.type(screen.getByLabelText("To date"), "2026-09-30");

    await vi.waitFor(() => expect(asked(fetchMock).get("before")).not.toBeNull());
    const sent = asked(fetchMock);
    expect(new Date(sent.get("after")!)).toEqual(new Date("2026-09-01T00:00:00"));
    // "To" includes the whole of that day.
    expect(new Date(sent.get("before")!)).toEqual(new Date("2026-10-01T00:00:00"));
  });

  it("says when nothing matches, differently from having no notes", async () => {
    show("/notes?q=zzz", { "GET /api/notes/browse/?q=zzz": grid([]) });
    expect(await screen.findByText("No notes match.")).toBeInTheDocument();
  });

  it("opens a note as the page, and Back to notes keeps the search and filters", async () => {
    const user = userEvent.setup();
    show("/notes?q=acme&company=co1");

    await user.click(await screen.findByRole("link", { name: /Acme kickoff/ }));

    expect(await screen.findByText("Dispatch is the bottleneck.")).toBeInTheDocument();
    expect(screen.queryByRole("searchbox", { name: "Search notes" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Back to notes/ }));

    expect(screen.getByLabelText("address")).toHaveTextContent("/notes?q=acme&company=co1");
    expect(await screen.findByRole("searchbox", { name: "Search notes" })).toHaveValue("acme");
    expect(screen.getByLabelText("Filter by company")).toHaveValue("co1");
  });

  it("goes back to the plain grid from a note opened directly", async () => {
    show("/notes/n1");
    expect(await screen.findByRole("link", { name: /Back to notes/ }))
      .toHaveAttribute("href", "/notes");
  });

  it("keeps the recording retention card for the practice owner", async () => {
    show();
    expect(await screen.findByText("Recording audio retention")).toBeInTheDocument();
  });
});
