import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ActingBanner } from "../components/ActAs";
import { PortalCreate } from "../components/PortalCreate";
import { Me, PortalRights } from "../lib/api";
import { COMPANY_ID, aMe, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Work } from "./Work";

/** P7 phase 4: the portal offers each person only what they may do. */

const BRAND = { display_name: "Executives Now", logo_url: "", mark_url: "", footer_text: "",
  palette: null, product_name: null };
const TEAMS = [
  { id: "t0", name: "Everyone", is_default: true },
  { id: "t1", name: "Operations", is_default: false },
];

function rights(over: Partial<PortalRights> = {}): PortalRights {
  return {
    level_label: "Member", may_create: { task: true, project: true, goal: false },
    edits_goals: false, has_teams_view: false, teams: [TEAMS[1]], may_propose_goal: false,
    ...over,
  };
}

const client = (portal: PortalRights, role: "FCC" | "ECC" = "ECC"): Me =>
  aMe({ role, client_company: COMPANY_ID, email: "ben@adapt.invalid", portal });

function create(me: Me, offer: ("task" | "project" | "goal")[] = ["task", "project", "goal"]) {
  const fetchMock = mockApi({
    "GET /api/branding": BRAND, "GET /api/projects/": [], "GET /api/portal-people/": [],
    "POST /api/goals/": aWorkParent({ id: "g9", title: "Ship same day" }),
    "POST /api/tasks/": { id: "k1", title: "Count stock", project: null },
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<PortalCreate me={me} offer={offer} />);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  try { window.localStorage.clear(); } catch { /* not needed */ }
});

describe("New, by what a person may create (§3)", () => {
  it("offers nothing to someone who only looks", () => {
    create(client(rights({ level_label: "Viewer",
      may_create: { task: false, project: false, goal: false }, teams: [] })));
    expect(screen.queryByRole("button", { name: /^New / })).toBeNull();
  });

  it("offers tasks only, and goals only with Goals too", () => {
    create(client(rights({ may_create: { task: true, project: false, goal: false } })));
    expect(screen.getByRole("button", { name: "New task" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New project" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New goal" })).toBeNull();
  });

  it("adds a goal with Goals too, sending only its words", async () => {
    const user = userEvent.setup();
    const fetchMock = create(client(rights({
      may_create: { task: true, project: true, goal: true } })));
    await user.click(screen.getByRole("button", { name: "New goal" }));
    await user.type(screen.getByLabelText("New goal title"), "Ship same day");
    await user.click(screen.getByRole("button", { name: "Add the goal" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(true));
    const sent = fetchMock.calls.find((c) => c.method === "POST")!;
    expect([sent.url, sent.body]).toEqual(["/api/goals/", { title: "Ship same day" }]);
    expect(await screen.findByText(/“Ship same day” added\./)).toBeInTheDocument();
  });
});

describe("which team, and who it can go to (§1.2, §2.2)", () => {
  it("asks for the team when there is more than one, and offers that team's people", async () => {
    const user = userEvent.setup();
    const fetchMock = create(client(rights({ teams: TEAMS })), ["task"]);
    await user.click(screen.getByRole("button", { name: "New task" }));
    const team = screen.getByRole("combobox", { name: "Team for the new task" });
    expect((team as HTMLSelectElement).value).toBe("t0");
    await user.selectOptions(team, "t1");
    await waitFor(() => expect(fetchMock.calls.map((c) => c.url))
      .toContain("/api/portal-people/?team=t1"));
    await user.type(screen.getByLabelText("New task title"), "Count stock");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(true));
    expect(fetchMock.calls.find((c) => c.method === "POST")!.body)
      .toEqual({ title: "Count stock", client_team: "t1" });
  });

  it("does not ask when there is only one", async () => {
    const user = userEvent.setup();
    const fetchMock = create(client(rights()), ["task"]);
    await user.click(screen.getByRole("button", { name: "New task" }));
    expect(screen.queryByRole("combobox", { name: "Team for the new task" })).toBeNull();
    await waitFor(() => expect(fetchMock.calls.map((c) => c.url))
      .toContain("/api/portal-people/?team=t1"));
  });
});

describe("Mine / My team / Everyone (§4.3)", () => {
  function work(me: Me) {
    const fetchMock = mockApi({
      "/api/branding": BRAND,
      "/api/goals/": [aWorkParent({ id: "g1", title: "Ship same day",
                                    client_company: COMPANY_ID,
                                    added_by: "Ben Orji, Adapt Inc" })],
      "/api/projects/": [], "/api/tasks/": [], "/api/portal-people/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Work me={me} />);
    return fetchMock;
  }

  it("is offered to a manager, and narrows both lists on the server", async () => {
    const user = userEvent.setup();
    const fetchMock = work(client(rights({ level_label: "Manager", has_teams_view: true })));
    const group = await screen.findByRole("group", { name: "Whose work" });
    expect(within(group).getByRole("button", { name: "Everyone" }))
      .toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "My team" }));
    await waitFor(() => {
      const urls = fetchMock.calls.map((c) => c.url);
      expect(urls).toContain("/api/tasks/?view=team");
      expect(urls).toContain("/api/projects/?view=team");
      expect(urls).toContain("/api/tasks/?unfiled=1&view=team");
    });
  });

  it("is not offered to a member", async () => {
    work(client(rights()));
    await screen.findByText("Ship same day");
    expect(screen.queryByRole("group", { name: "Whose work" })).toBeNull();
  });

  it("marks a goal a client user added, and drops the proposal line for Goals too", async () => {
    work(client(rights({ may_create: { task: true, project: true, goal: true } }), "FCC"));
    expect(await screen.findByText("Added by Ben Orji, Adapt Inc")).toBeInTheDocument();
    expect(screen.queryByText(/Goals are set together with/)).toBeNull();
    expect(screen.getByRole("button", { name: "New goal" })).toBeInTheDocument();
  });
});

describe("level names in the portal (P7-10)", () => {
  it("names the acted-as client user by their level in the banner", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ActingBanner me={aMe({ role: "ECC", acting: {
            real_name: "John Carter", real_email: "j@x.invalid", real_role: "FF",
            as_membership: "m2", as_name: "Lucius Fox", as_email: "l@x.invalid",
            as_role: "ECC", as_label: "Member", company: COMPANY_ID,
            company_name: "Wayne Industries" } })} />
        </MemoryRouter>
      </QueryClientProvider>);
    const banner = screen.getByRole("status", { name: "Acting as" });
    expect(banner).toHaveTextContent("John Carter is acting as Lucius Fox (Member, Wayne Industries)");
    expect(banner).not.toHaveTextContent("Client team member");
  });
});
