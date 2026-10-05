import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Me } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Profile, ProfileData } from "./Profile";

const MINE: ProfileData = {
  email: "casey@example.invalid", full_name: "Casey Field", role_label: "Associate",
  practice: "Executives Now", client_company_name: null, editable: true,
};

function show(profile: ProfileData = MINE, patch?: unknown) {
  const fetchMock = mockApi({
    "PATCH /api/me/profile": patch ?? ((body: unknown) => ({
      body: { ...profile, full_name: (body as { full_name: string }).full_name } })),
    "GET /api/me/profile": profile,
    "GET /api/me": aMe(),
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Profile />);
  return fetchMock;
}

/** Profile (UI 3 spec §5). */
describe("Profile", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the name to edit, and the account by role name and practice", async () => {
    show();
    expect(await screen.findByLabelText("Full name")).toHaveValue("Casey Field");
    expect(screen.getByText("Associate")).toBeInTheDocument();
    expect(screen.getByText("Executives Now")).toBeInTheDocument();
    expect(screen.getByText("casey@example.invalid")).toBeInTheDocument();
  });

  it("has no way to change the sign-in email, and says why", async () => {
    show();
    await screen.findByLabelText("Full name");
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByText(/cannot be changed here/)).toBeInTheDocument();
  });

  it("saves a changed name and says so", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const field = await screen.findByLabelText("Full name");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await user.clear(field);
    await user.type(field, "Casey Fielding");
    await user.click(save);

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const sent = fetchMock.calls.find((c) => c.method === "PATCH")!;
    expect(sent.body).toEqual({ full_name: "Casey Fielding" });
  });

  it("shows the server's refusal in its own words", async () => {
    const user = userEvent.setup();
    show(MINE, () => ({ status: 400, body: { full_name: "Enter your name." } }));
    const field = await screen.findByLabelText("Full name");
    await user.type(field, "x");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Enter your name.")).toBeInTheDocument();
  });

  it("is read-only while acting as the person, and says why", async () => {
    show({ ...MINE, full_name: "Dana Reyes", role_label: "Client owner",
           client_company_name: "Acme Freight", editable: false });
    expect(await screen.findByLabelText("Full name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByText(/Their profile is theirs to change/)).toBeInTheDocument();
    expect(screen.getByText("Acme Freight")).toBeInTheDocument();
  });
});

describe("Profile in the menu", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  async function menuFor(me: Me) {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me/profile": MINE,
      "GET /api/me": me,
      "GET /api/branding": { display_name: "Executives Now", product_name: "Execs NOW HQ",
                             logo_url: "", palette: null },
      "GET /api/": [],
    }));
    renderRoute(<App />, { path: "*", route: "/tasks" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Your account/ }));
    return { user, menu: screen.getByRole("menu", { name: "Your account" }) };
  }

  it.each([["FF", null], ["CF", null], ["VA", null], ["FCC", "co1"], ["ECC", "co1"]] as const)(
    "offers Profile to %s, and it opens the page", async (role, company) => {
      const { user, menu } = await menuFor(aMe({ role, client_company: company }));
      await user.click(within(menu).getByRole("menuitem", { name: "Profile" }));
      expect(await screen.findByLabelText("Full name")).toHaveValue("Casey Field");
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });

  it("renames the person in the top bar once the new name is saved", async () => {
    const { App } = await import("../App");
    let name = "Casey Field";
    vi.stubGlobal("fetch", mockApi({
      "PATCH /api/me/profile": (body: unknown) => {
        name = (body as { full_name: string }).full_name;
        return { body: { ...MINE, full_name: name } };
      },
      "GET /api/me/profile": () => ({ body: { ...MINE, full_name: name } }),
      "GET /api/me": () => ({ body: aMe({ role: "CF", full_name: name }) }),
      "GET /api/branding": { display_name: "Executives Now", product_name: "Execs NOW HQ",
                             logo_url: "", palette: null },
      "GET /api/": [],
    }));
    renderRoute(<App />, { path: "*", route: "/profile" });
    const user = userEvent.setup();
    const field = await screen.findByLabelText("Full name");

    await user.clear(field);
    await user.type(field, "Casey Fielding");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("button", { name: "Your account: Casey Fielding" }))
      .toBeInTheDocument();
  });
});
