import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Me, SIGNED_OUT_EVENT, api } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

const BRAND = { display_name: "Executives Now", product_name: "Execs NOW HQ",
                logo_url: "", palette: null };

function stubApp(me: Me, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/me": me,
    "GET /api/branding": BRAND,
    "POST /auth/sign-out": { signed_out: true },
    "GET /api/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function showApp(me: Me, extra: Record<string, unknown> = {}, route = "/tasks") {
  const { App } = await import("../App");
  const fetchMock = stubApp(me, extra);
  renderRoute(<App />, { path: "*", route });
  await screen.findByRole("banner", { name: "Top bar" });
  return fetchMock;
}

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Your account/ }));
  return screen.getByRole("menu", { name: "Your account" });
}

/** The top bar (UI 3 spec §2): who is signed in, and the way out. */
describe("the top bar", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  it("names the person, their role by name, and the practice in the menu", async () => {
    const user = userEvent.setup();
    await showApp(aMe({ role: "CF", full_name: "Casey Field" }));

    const menu = await openMenu(user);

    expect(within(menu).getByText("Casey Field")).toBeInTheDocument();
    expect(within(menu).getByText("Associate · Executives Now")).toBeInTheDocument();
    // Never the code.
    expect(menu).not.toHaveTextContent(/\bCF\b/);
  });

  it("is no longer in the sidebar: no name block and no Collapse there", async () => {
    await showApp(aMe());

    const sidebar = document.querySelector(".sidebar") as HTMLElement;
    expect(within(sidebar).queryByText("Bryan Baker")).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: /the menu/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("banner", { name: "Top bar" })).getByRole("button", { name: "Collapse the menu" }))
      .toBeInTheDocument();
  });

  it("signs out on the server and leaves for the sign-in screen", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetchMock = await showApp(aMe());

    const menu = await openMenu(user);
    await user.click(within(menu).getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(fetchMock.calls.some((c) => c.method === "POST" && c.url === "/auth/sign-out"))
      .toBe(true);
  });

  it("opens and closes by keyboard, and gives focus back", async () => {
    const user = userEvent.setup();
    await showApp(aMe());
    const button = await screen.findByRole("button", { name: /Your account/ });

    button.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")[0]).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it.each([
    ["FF", true], ["CF", true], ["VA", true], ["FCC", false], ["ECC", false],
  ] as const)("shows Feedback to staff only (%s)", async (role, shown) => {
    await showApp(aMe({ role, client_company: shown ? null : "co1" }));
    const bar = screen.getByRole("banner", { name: "Top bar" });
    expect(!!within(bar).queryByRole("button", { name: "Feedback" })).toBe(shown);
  });

  it("gives a client owner Act as a colleague in the menu, and no one else", async () => {
    const user = userEvent.setup();
    await showApp(aMe({ role: "FCC", client_company: "co1" }), {
      "GET /api/act-as/candidates/": [
        { membership: "m2", name: "Eli Chen", email: "eli@example.invalid", role: "ECC",
          company: "co1", company_name: "Acme" }],
    });
    const menu = await openMenu(user);
    expect(await within(menu).findByLabelText("Act as a colleague")).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
  });

  it("offers a practice owner no Act as a colleague: it never existed for staff", async () => {
    const user = userEvent.setup();
    await showApp(aMe({ role: "FF" }));
    const menu = await openMenu(user);
    expect(within(menu).queryByLabelText("Act as a colleague")).not.toBeInTheDocument();
  });

  it("shows the sign-in screen when the server says the session has ended", async () => {
    const fetchMock = await showApp(aMe());
    // The next "who am I" is refused, as after 12 hours without activity.
    fetchMock.mockImplementation(async () => ({
      ok: false, status: 401, statusText: "Unauthorized",
      text: async () => JSON.stringify({ authenticated: false }),
    } as Response));

    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));

    await waitFor(() => expect(screen.queryByRole("banner", { name: "Top bar" })).not.toBeInTheDocument());
  });
});

describe("what the app tells the server about activity", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends how long the person has been idle with every request", async () => {
    const seen: Record<string, string>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      seen.push(init?.headers as Record<string, string>);
      return { ok: true, status: 200, statusText: "OK", text: async () => "{}" } as Response;
    }));
    vi.useFakeTimers();
    try {
      window.dispatchEvent(new Event("pointerdown"));
      await api.get("/api/tasks/");
      vi.advanceTimersByTime(90_000);
      // A background refresh a minute and a half later: no click in between.
      await api.get("/api/tasks/");
      window.dispatchEvent(new Event("keydown"));
      await api.get("/api/tasks/");
    } finally {
      vi.useRealTimers();
    }
    expect(seen.map((h) => h["X-Idle-Seconds"])).toEqual(["0", "90", "0"]);
  });

  it("announces a refused session so the app can show the sign-in screen", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 401, statusText: "Unauthorized",
      text: async () => JSON.stringify({ detail: "Signed out." }),
    } as Response)));
    const heard = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, heard);
    await expect(api.get("/api/tasks/")).rejects.toThrow("Signed out.");
    window.removeEventListener(SIGNED_OUT_EVENT, heard);
    expect(heard).toHaveBeenCalledTimes(1);
  });
});
