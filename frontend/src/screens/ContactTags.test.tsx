import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PageLinks } from "../components/ui";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ContactTags } from "./ContactTags";
import { settingsFor } from "./Settings";

const TAGS = [{ tag: "board", contacts: 2 }, { tag: "Denver", contacts: 5 }];

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ "GET /api/contact-tags/": TAGS, ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<ContactTags />);
  return fetchMock;
}
const posts = (fetchMock: ReturnType<typeof show>) =>
  fetchMock.calls.filter((c) => c.method === "POST").map((c) => [c.url, c.body]);

describe("Settings, Tags (2026-10-12)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is the practice owner's section, and nobody else's", () => {
    const has = (role: string) => settingsFor(aMe({ role: role as never }))
      .some((s) => s.to === "/settings/tags");
    expect(has("FF")).toBe(true);
    expect(["CF", "VA", "FCC", "ECC"].map(has)).toEqual([false, false, false, false]);
  });

  it("lists each tag with how many contacts have it", async () => {
    show();
    const table = await screen.findByRole("table", { name: "Tags" });
    expect([...table.querySelectorAll("tbody tr")].map((tr) => tr.textContent))
      .toEqual(["board2RenameRemove", "Denver5RenameRemove"]);
  });

  it("renames a tag everywhere, and says when two will become one", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/contact-tags/rename/": {
      changed: 2, tags: [{ tag: "Denver", contacts: 6 }] } });
    await user.click(await screen.findByRole("button", { name: "Rename board" }));
    const name = screen.getByLabelText("New name for board");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.clear(name);
    await user.type(name, "Denver");
    expect(screen.getByText(/exists already: the two will become one tag/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(fetchMock)).toEqual([
      ["/api/contact-tags/rename/", { tag: "board", to: "Denver" }]]));
    expect(await screen.findByText("Renamed on 2 contacts.")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Tags" });
    expect(within(table).queryByText("board")).toBeNull();
  });

  it("removes a tag only after saying how many contacts it is on", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/contact-tags/remove/": {
      changed: 5, tags: [{ tag: "board", contacts: 2 }] } });
    await user.click(await screen.findByRole("button", { name: "Remove Denver" }));
    expect(screen.getByText(/Remove "Denver" from 5 contacts\? The contacts stay\./))
      .toBeInTheDocument();
    expect(posts(fetchMock)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Remove it" }));
    await waitFor(() => expect(posts(fetchMock)).toEqual([
      ["/api/contact-tags/remove/", { tag: "Denver" }]]));
    expect(await screen.findByText("Removed on 5 contacts.")).toBeInTheDocument();
  });
});

describe("LinkedIn and Alignable are links (2026-10-12)", () => {
  it("shows the ones there are, opening in a new tab, and nothing when there are none", () => {
    const { unmount } = renderRoute(
      <PageLinks linkedin="https://www.linkedin.com/in/dana" alignable="" />);
    const link = screen.getByRole("link", { name: "LinkedIn" });
    expect(link).toHaveAttribute("href", "https://www.linkedin.com/in/dana");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "Alignable" })).toBeNull();
    unmount();
    const { container } = renderRoute(<PageLinks />);
    expect(container.querySelector(".page-links")).toBeNull();
  });
});
