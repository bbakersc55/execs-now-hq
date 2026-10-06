import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Me } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { SETTINGS, settingsFor } from "./Settings";

const BRAND = { display_name: "Executives Now", product_name: "Execs NOW HQ",
                logo_url: "", palette: null };

async function showApp(me: Me, route: string, extra: Record<string, unknown> = {}) {
  const { App } = await import("../App");
  vi.stubGlobal("fetch", mockApi({
    ...extra,
    "GET /api/me": me,
    "GET /api/branding": BRAND,
    "GET /api/notes/settings/": { audio_retention_days: 30 },
    "GET /api/": [],
  }));
  renderRoute(<App />, { path: "*", route });
  await screen.findByRole("banner", { name: "Top bar" });
}

const sections = () => within(screen.getByRole("navigation", { name: "Settings" }))
  .getAllByRole("link").map((a) => a.textContent);

/** Settings (UI 3 spec §4): one page, sections by role, the old addresses. */
describe("Settings", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  it("lists every section for the practice owner", () => {
    expect(settingsFor(aMe({ role: "FF" })).map((s) => s.label)).toEqual([
      "Email", "Branding", "Team", "Stage automations", "Referral settings", "Digests",
      "Notes", "AI usage",
    ]);
  });

  it("lists only their own email connection for an associate", () => {
    expect(settingsFor(aMe({ role: "CF" })).map((s) => s.to)).toEqual(["/settings/email"]);
  });

  it.each(["VA", "FCC", "ECC"] as const)("lists nothing for %s", (role) => {
    expect(settingsFor(aMe({ role }))).toEqual([]);
  });

  it("lists nothing in the Practices area, where no practice is bound", () => {
    expect(settingsFor(aMe({ role: null, area: "platform", is_platform_owner: true })))
      .toEqual([]);
  });

  it("shows no role a section the sidebar did not already show it", () => {
    // The sidebar's Settings group, as it was before UI 3.
    const before: Record<string, string[]> = {
      "/settings/email": ["FF", "CF"], "/settings/branding": ["FF"], "/referrals": ["FF"],
      "/rules": ["FF"], "/staff": ["FF"], "/ai-usage": ["FF"],
      // New address; the card on Notes was the practice owner's only.
      "/settings/notes": ["FF"],
      // New with the editable digest day (2026-10-05); its endpoint lets only
      // the practice owner change it.
      "/settings/digests": ["FF"],
    };
    for (const section of SETTINGS) {
      expect(section.roles, section.to).toEqual(before[section.to]);
    }
    expect(SETTINGS.map((s) => s.to).sort()).toEqual(Object.keys(before).sort());
  });

  it("has left the sidebar and is reached from the profile menu", async () => {
    const user = userEvent.setup();
    await showApp(aMe({ role: "FF" }), "/tasks");

    const sidebar = document.querySelector(".sidebar") as HTMLElement;
    for (const label of ["Settings", "Branding", "Team", "Staff", "AI usage", "Stage automations"]) {
      expect(within(sidebar).queryByText(label), label).not.toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: /Your account/ }));
    await user.click(screen.getByRole("menuitem", { name: "Settings" }));

    // /settings opens the first section the person has.
    await waitFor(() => expect(sections()).toHaveLength(8));
    expect(screen.getByRole("link", { name: "Email" })).toHaveClass("on");
  });

  it.each([["VA", null], ["FCC", "co1"], ["ECC", "co1"]] as const)(
    "gives %s no Settings entry in the menu", async (role, company) => {
      const user = userEvent.setup();
      await showApp(aMe({ role, client_company: company }), "/tasks");
      await user.click(screen.getByRole("button", { name: /Your account/ }));
      expect(screen.queryByRole("menuitem", { name: "Settings" })).not.toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
    });

  it("says so when someone with no settings opens /settings anyway", async () => {
    await showApp(aMe({ role: "VA" }), "/settings");
    expect(await screen.findByText("There are no settings for your role."))
      .toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Settings" })).not.toBeInTheDocument();
  });

  it.each(["/settings/email", "/settings/branding", "/referrals", "/rules", "/staff",
           "/ai-usage"])("still opens %s at its old address, inside Settings", async (path) => {
    await showApp(aMe({ role: "FF" }), path);
    await waitFor(() => expect(sections()).toHaveLength(8));
    const here = SETTINGS.find((s) => s.to === path)!;
    expect(screen.getByRole("link", { name: here.label })).toHaveClass("on");
    expect(document.querySelector(".settings-body")).not.toBeEmptyDOMElement();
  });

  it("shows an associate their one section and nothing else", async () => {
    await showApp(aMe({ role: "CF" }), "/settings");
    await waitFor(() => expect(sections()).toEqual(["Email"]));
  });

  it("holds Recording audio retention, for the practice owner", async () => {
    await showApp(aMe({ role: "FF" }), "/settings/notes");
    expect(await screen.findByText("Recording audio retention")).toBeInTheDocument();
    expect(screen.getByLabelText("Keep audio for (days)")).toHaveValue(30);
  });

  it("does not offer the retention page to an associate", async () => {
    await showApp(aMe({ role: "CF" }), "/settings/notes");
    await screen.findByRole("banner", { name: "Top bar" });
    expect(screen.queryByText("Recording audio retention")).not.toBeInTheDocument();
  });

  it("no longer shows the retention card on Notes", async () => {
    await showApp(aMe({ role: "FF" }), "/notes", {
      "GET /api/notes/browse/": { total: 0, results: [], companies: [], contacts: [] },
    });
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
    expect(screen.queryByText("Recording audio retention")).not.toBeInTheDocument();
  });
});
