import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe, aTask } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

/** Tier 1 of `docs/design_brief.md`: the shell, and the task editor as a panel
 *  over the board rather than a page of its own. */

const BRAND = { display_name: "Executives Now", product_name: "Execs NOW HQ",
                logo_url: "", palette: null };

function stubApp(extra: Record<string, unknown> = {}) {
  // `extra` goes first: the stub matcher takes the first key whose path
  // prefixes the url, so `/api/tasks/<id>/` has to be ahead of `/api/tasks/`
  // or the detail fetch is answered with the list.
  const fetchMock = mockApi({
    ...extra,
    "GET /api/me": aMe(),
    "GET /api/branding": BRAND,
    "GET /api/tasks/": [aTask({ title: "Map the invoice process" })],
    "GET /api/projects/": [],
    "GET /api/portal-people/": [],
    "GET /api/companies/": [],
    "GET /api/goals/": [],
    "GET /api/contacts/": [],
    // Anything the editor's panels ask for that this test does not care
    // about. Last, so every specific stub above still wins.
    "GET /api/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("the shell", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  it("groups the navigation and gives every item an icon", async () => {
    const { App } = await import("../App");
    stubApp();
    renderRoute(<App />, { path: "*", route: "/tasks" });

    expect(await screen.findByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("The work")).toBeInTheDocument();
    const nav = screen.getByRole("navigation");
    const links = [...nav.querySelectorAll("a")];
    expect(links.length).toBeGreaterThan(5);
    for (const link of links) {
      expect(link.querySelector("svg"), `${link.textContent} has no icon`).toBeTruthy();
    }
  });

  it("collapses to icons and remembers it", async () => {
    const user = userEvent.setup();
    const { App } = await import("../App");
    stubApp();
    const view = renderRoute(<App />, { path: "*", route: "/tasks" });

    const layout = () => document.querySelector(".layout")!;
    expect(await screen.findByText("Accounts")).toBeInTheDocument();
    expect(layout().className).not.toContain("collapsed");

    await user.click(screen.getByRole("button", { name: "Collapse the menu" }));
    expect(layout().className).toContain("collapsed");
    expect(localStorage.getItem("enhq.sidebar.collapsed")).toBe("1");

    // Remembered: a fresh mount comes back collapsed.
    view.unmount();
    renderRoute(<App />, { path: "*", route: "/tasks" });
    await waitFor(() => expect(document.querySelector(".layout")!.className)
      .toContain("collapsed"));
  });
});

describe("the task editor", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  const TASK_ID = "t-1";

  function stubTask() {
    // The editor's sub-resources hang off the task's own path, so they have to
    // be stubbed ahead of it — first match wins, and `/api/tasks/<id>/` would
    // otherwise answer `/api/tasks/<id>/checklist/` with the task.
    return stubApp({
      [`GET /api/tasks/${TASK_ID}/checklist/`]: [],
      [`GET /api/tasks/${TASK_ID}/updates/`]: [],
      [`GET /api/tasks/${TASK_ID}/`]: aTask({ id: TASK_ID, title: "Map the invoice process" }),
      "GET /api/comments/": [],
      "GET /api/notes/": [],
      "GET /api/stakeholders/candidates/": { company: null, company_name: "",
                                             outside: false, people: [] },
      "GET /api/stakeholders/": [],
    });
  }

  it("opens over the board from its own URL, and closes back to it", async () => {
    const user = userEvent.setup();
    const { App } = await import("../App");
    stubTask();
    renderRoute(<App />, { path: "*", route: `/tasks/${TASK_ID}` });

    // The board is behind it, not replaced by it.
    const sheet = await screen.findByRole("dialog");
    expect(sheet).toBeInTheDocument();
    // The board loads behind it rather than being replaced by it.
    expect(await screen.findByLabelText("Board")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Board")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const { App } = await import("../App");
    stubTask();
    renderRoute(<App />, { path: "*", route: `/tasks/${TASK_ID}` });

    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("the sidebar on a narrow window", () => {
  beforeEach(() => vi.unstubAllGlobals());

  /** jsdom has no layout, so `matchMedia` is the seam — which is also the
   *  seam the real thing uses. */
  function atWidth(narrow: boolean) {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: narrow, media: query,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, onchange: null,
      dispatchEvent: () => false,
    }));
  }

  it("collapses itself when the window is narrow", async () => {
    const { App } = await import("../App");
    atWidth(true);
    stubApp();
    renderRoute(<App />, { path: "*", route: "/tasks" });

    expect(await screen.findByRole("button", { name: "Expand the menu" }))
      .toBeInTheDocument();
  });

  it("leaves a wide window expanded", async () => {
    const { App } = await import("../App");
    atWidth(false);
    stubApp();
    renderRoute(<App />, { path: "*", route: "/tasks" });

    expect(await screen.findByRole("button", { name: "Collapse the menu" }))
      .toBeInTheDocument();
  });
});
