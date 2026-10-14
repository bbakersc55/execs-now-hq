import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientTeams } from "../lib/api";
import { COMPANY_ID, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { YourTeam } from "./YourTeam";

/** P7 phase 3: the client owner's own Teams card, in the portal. */

const BRAND = { display_name: "Executives Now", logo_url: "", mark_url: "", footer_text: "",
  palette: null, product_name: null };

const OWNER = aMe({ role: "FCC", email: "dana@adapt.invalid", full_name: "Dana Reyes",
                    client_company: COMPANY_ID });

const card = (ownerMayCreate = "projects"): ClientTeams => ({
  company: COMPANY_ID, may_manage: true,
  teams: [
    { id: "t0", name: "Everyone", is_default: true, projects: 0, open_tasks: 1, people: [] },
    { id: "t1", name: "Operations", is_default: false, projects: 2, open_tasks: 4,
      people: [{ membership: "m2", name: "Ben Orji", level: "member" }] },
  ],
  people: [
    { id: "m1", name: "Dana Reyes", email: "dana@adapt.invalid", role: "FCC",
      may_create: ownerMayCreate, leads_all_teams: false, teams: [] },
    { id: "m2", name: "Ben Orji", email: "ben@adapt.invalid", role: "ECC",
      may_create: "projects", leads_all_teams: false,
      teams: [{ team: "t1", level: "member" }] },
  ],
});

function show(me = OWNER, data = card()) {
  const fetchMock = mockApi({ "GET /api/client-teams/": data, "GET /api/branding": BRAND,
                              "POST /api/client-teams/": data });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<YourTeam me={me} />);
  return fetchMock;
}

beforeEach(() => vi.unstubAllGlobals());

describe("Your team, the client owner's page", () => {
  it("shows their company's Teams card, and says where to check what someone sees", async () => {
    const fetchMock = show();
    expect(await screen.findByRole("heading", { name: "Your team" })).toBeInTheDocument();
    await screen.findByRole("table", { name: "Teams" });
    expect(fetchMock.calls[0].url).toContain(`/api/client-teams/?company=${COMPANY_ID}`);
    expect(screen.getByText(/“Act as a colleague” in your account menu/)).toBeInTheDocument();
    expect(screen.queryByText(/See the portal as/)).toBeNull();
    expect(await screen.findByText(/own settings are set by Executives Now/))
      .toBeInTheDocument();
  });

  it("leaves a client owner's own settings to the practice", async () => {
    show();
    const people = await screen.findByRole("table", { name: "People and their levels" });
    const dana = within(people).getByRole("row", { name: /Dana Reyes/ });
    expect(within(dana).queryByRole("combobox")).toBeNull();
    expect(within(dana).getByText("Projects and tasks")).toBeInTheDocument();
    await waitFor(() => expect(within(dana).getByText(/set by Executives Now/))
      .toBeInTheDocument());
  });

  it("offers nobody more to create than the client owner may create", async () => {
    show();
    const ben = await screen.findByRole("combobox", { name: "What Ben Orji may create" });
    const options = within(ben).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((o) => [o.textContent, o.disabled])).toEqual([
      ["Nothing", false], ["Tasks only", false], ["Projects and tasks", false],
      ["Goals too", true]]);
  });

  it("offers Goals too once the practice has given it to the client owner", async () => {
    show(OWNER, card("goals"));
    const ben = await screen.findByRole("combobox", { name: "What Ben Orji may create" });
    expect((within(ben).getByRole("option", { name: "Goals too" }) as HTMLOptionElement)
      .disabled).toBe(false);
  });

  it("sends a change for their own company", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.type(await screen.findByLabelText("Name of the new team"), "Front office");
    await user.click(screen.getByRole("button", { name: "Add a team" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(true));
    const sent = fetchMock.calls.find((c) => c.method === "POST")!;
    expect(sent.url).toContain("/api/client-teams/");
    expect(sent.body).toEqual({ company: COMPANY_ID, name: "Front office" });
  });

  it("asks nothing for a client user who is not the client owner", async () => {
    const fetchMock = show(aMe({ role: "ECC", client_company: COMPANY_ID }));
    await screen.findByRole("heading", { name: "Your team" });
    expect(screen.queryByRole("table", { name: "Teams" })).toBeNull();
    expect(fetchMock.calls.filter((c) => c.url.includes("/api/client-teams/"))).toEqual([]);
  });
});

describe("the portal's sidebar", () => {
  const app = async (role: "FCC" | "ECC") => {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({ "GET /api/me": aMe({ role, client_company: COMPANY_ID }),
      "GET /api/branding": BRAND, "GET /api/": [] }));
    renderRoute(<App />, { path: "*", route: "/work" });
    await screen.findAllByText("Our work");
  };

  it("has Your team for the client owner", async () => {
    await app("FCC");
    expect(screen.getAllByRole("link", { name: /Your team/ }).length).toBeGreaterThan(0);
  });

  it("does not have it for anyone else in the portal", async () => {
    await app("ECC");
    expect(screen.queryByRole("link", { name: /Your team/ })).toBeNull();
  });
});
