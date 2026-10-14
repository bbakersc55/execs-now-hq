import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientTeams } from "../lib/api";
import { Work } from "../screens/Work";
import { COMPANY_ID, aCompany, aMe, aTask, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ClientTeamsCard } from "./ClientTeams";
import { PortalAccessCard } from "./PortalAccessCard";
import { StaffCreate } from "./StaffCreate";

/** P7 phase 2: the practice's Teams card, the Team field on a project and a
 *  task, the filter by team, and the invitation's three choices. */

const NAMES = [
  { id: "t0", name: "Everyone", is_default: true },
  { id: "t1", name: "Operations", is_default: false },
  { id: "t2", name: "Sales", is_default: false },
];

const card = (over: Partial<ClientTeams> = {}): ClientTeams => ({
  company: COMPANY_ID, may_manage: true,
  teams: [
    { ...NAMES[0], projects: 0, open_tasks: 1, people: [] },
    { ...NAMES[1], projects: 2, open_tasks: 4,
      people: [{ membership: "m2", name: "Ben Orji", level: "member" }] },
    { ...NAMES[2], projects: 1, open_tasks: 1, people: [] },
  ],
  people: [
    { id: "m1", name: "Dana Reyes", email: "dana@adapt.invalid", role: "FCC",
      may_create: "projects", leads_all_teams: false, teams: [] },
    { id: "m2", name: "Ben Orji", email: "ben@adapt.invalid", role: "ECC",
      may_create: "projects", leads_all_teams: false,
      teams: [{ team: "t1", level: "member" }] },
    { id: "m3", name: "Cy Vance", email: "cy@adapt.invalid", role: "ECC",
      may_create: "nothing", leads_all_teams: false, teams: [] },
  ],
  ...over,
});

function show(routes: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({ ...routes, "GET /api/client-teams/": card() });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<ClientTeamsCard me={me} company={aCompany()} />);
  return fetchMock;
}

const sent = (fetchMock: ReturnType<typeof mockApi>, method = "POST") =>
  fetchMock.calls.filter((c) => c.method === method).map((c) => [c.url, c.body]);

beforeEach(() => vi.unstubAllGlobals());

describe("the Teams card on a client company", () => {
  it("lists each team with what it holds, and each person with their level on each", async () => {
    show();
    const teams = await screen.findByRole("table", { name: "Teams" });
    const rows = within(teams).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Everyone · the default0 projects, 1 open task0"),
      expect.stringContaining("Operations2 projects, 4 open tasks1"),
      expect.stringContaining("Sales1 project, 1 open task0"),
    ]);
    // The default team is renamed like any other, and is never archived.
    expect(screen.queryByRole("button", { name: "Archive Everyone" })).toBeNull();
    expect(screen.getByRole("button", { name: "Archive Sales" })).toBeInTheDocument();

    const people = screen.getByRole("table", { name: "People and their levels" });
    expect(within(people).getByLabelText("Ben Orji on Operations")).toHaveValue("member");
    expect(within(people).getByLabelText("Ben Orji on Sales")).toHaveValue("");
    expect(within(people).getByLabelText("What Cy Vance may create")).toHaveValue("nothing");
    // The client owner has everything: no level to set, by name and not by code.
    expect(people).toHaveTextContent("Client owner: everything, in every team.");
    expect(within(people).queryByLabelText("Dana Reyes on Operations")).toBeNull();
    expect(people).toHaveTextContent("On no team: sees only work that is theirs.");
    expect(document.body.textContent).not.toMatch(/\b(FCC|ECC)\b/);
  });

  it("sets a level, senior leadership and may-create, each as it is changed", async () => {
    const fetchMock = show({
      "POST /api/client-teams/t2/level/": () => ({ body: card() }),
      "POST /api/client-teams/t1/level/": () => ({ body: card() }),
      "POST /api/client-teams/person/": () => ({ body: card() }),
    });
    await userEvent.selectOptions(await screen.findByLabelText("Ben Orji on Sales"), "manager");
    await userEvent.selectOptions(screen.getByLabelText("Ben Orji on Operations"), "");
    await userEvent.click(
      screen.getByLabelText("Ben Orji is senior leadership of every team"));
    await userEvent.selectOptions(screen.getByLabelText("What Ben Orji may create"), "goals");
    await waitFor(() => expect(sent(fetchMock)).toEqual([
      ["/api/client-teams/t2/level/", { membership: "m2", level: "manager" }],
      ["/api/client-teams/t1/level/", { membership: "m2", level: null }],
      ["/api/client-teams/person/", { membership: "m2", leads_all_teams: true }],
      ["/api/client-teams/person/", { membership: "m2", may_create: "goals" }],
    ]));
    // The four levels and the four settings, by name.
    const level = screen.getByLabelText("Cy Vance on Sales");
    expect(within(level).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Not on it", "Viewer", "Member", "Manager", "Senior leadership"]);
    expect(within(screen.getByLabelText("What Cy Vance may create"))
      .getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Nothing", "Tasks only", "Projects and tasks", "Goals too"]);
  });

  it("adds and renames a team, and shows the server's refusal in its own words", async () => {
    const fetchMock = show({
      "POST /api/client-teams/": (body: unknown) =>
        (body as { name: string }).name === "Sales"
          ? { status: 400, body: { detail: "Adapt CFO already has a team called Sales." } }
          : { status: 201, body: card() },
      "PATCH /api/client-teams/t1/": () => ({ body: card() }),
    });
    const name = await screen.findByLabelText("Name of the new team");
    const add = screen.getByRole("button", { name: "Add a team" });
    expect(add).toBeDisabled();
    await userEvent.type(name, "Sales");
    await userEvent.click(add);
    expect(await screen.findByText("Adapt CFO already has a team called Sales."))
      .toBeInTheDocument();
    await userEvent.clear(name);
    await userEvent.type(name, "Front office");
    await userEvent.click(add);
    expect(await screen.findByText("“Front office” added.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Rename Operations" }));
    const box = screen.getByLabelText("New name for Operations");
    await userEvent.clear(box);
    await userEvent.type(box, "Ops");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PATCH")).toEqual([
      ["/api/client-teams/t1/", { name: "Ops" }]]));
    expect(sent(fetchMock)).toEqual([
      ["/api/client-teams/", { company: COMPANY_ID, name: "Sales" }],
      ["/api/client-teams/", { company: COMPANY_ID, name: "Front office" }]]);
  });

  it("says what archiving will move before it is confirmed, and moves nothing if declined",
    async () => {
      const asked = vi.fn(() => false);
      vi.stubGlobal("confirm", asked);
      const fetchMock = show({
        "GET /api/client-teams/t1/archive/": {
          projects: 2, tasks: 1, people: 4, people_left_on_no_team: 3, moves_to: "Everyone" },
        "POST /api/client-teams/t1/archive/": () => ({ body: {
          ...card(), archived: { projects: 2, tasks: 1, people_moved: 3,
                                 moved_to: "Everyone" } } }),
      });
      await userEvent.click(await screen.findByRole("button", { name: "Archive Operations" }));
      await waitFor(() => expect(asked).toHaveBeenCalledTimes(1));
      expect(asked).toHaveBeenCalledWith(
        "Archive Operations? Its 2 project(s) and 1 task(s) in no project move to Everyone. "
        + "3 of its 4 people are on no other team and join Everyone at the level they hold "
        + "now. Nothing is deleted, and everyone keeps their sign-in.");
      expect(sent(fetchMock)).toEqual([]);

      asked.mockReturnValue(true);
      await userEvent.click(screen.getByRole("button", { name: "Archive Operations" }));
      expect(await screen.findByText(
        "Archived. 2 project(s), 1 task(s) and 3 person(s) moved to Everyone. Nothing was "
        + "deleted.")).toBeInTheDocument();
      expect(sent(fetchMock)).toEqual([["/api/client-teams/t1/archive/", {}]]);
    });

  it("is not drawn, and asks nothing, for an assistant", async () => {
    const fetchMock = show({}, aMe({ role: "VA" }));
    await waitFor(() => expect(fetchMock.calls).toEqual([]));
    expect(screen.queryByRole("heading", { name: "Teams" })).toBeNull();
  });
});

describe("an invitation names the team, the level and what they may create", () => {
  const candidates = (role = "ECC") => ({
    company: COMPANY_ID, company_name: "Adapt CFO", is_client_company: true, seat_count: 3,
    seats_in_use: 0, seat_refusal: null,
    people: [{ contact: "p1", name: "Ben Orji", email: "ben@adapt.invalid", title: "",
               role, refusal: null }],
  });
  const ACCESS = { company: COMPANY_ID, seat_count: 3, seats_in_use: 0, seats_available: 3,
                   may_manage: true, people: [] };

  function open(role = "ECC") {
    const fetchMock = mockApi({
      "/api/portal-access/candidates/": candidates(role),
      "POST /api/portal-access/": () => ({ status: 201, body: { id: "m9" } }),
      "/api/portal-access/": ACCESS,
      "/api/client-teams/names/": NAMES,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PortalAccessCard me={aMe()} company={aCompany()} />);
    return fetchMock;
  }

  it("starts at the default team, Member, projects and tasks (P7-9)", async () => {
    const fetchMock = open();
    expect(await screen.findByLabelText("Team for Ben Orji")).toHaveValue("t0");
    expect(screen.getByLabelText("Level for Ben Orji")).toHaveValue("member");
    expect(screen.getByLabelText("What Ben Orji may create")).toHaveValue("projects");
    await userEvent.click(screen.getByRole("button", { name: "Grant" }));
    await waitFor(() => expect(sent(fetchMock)).toEqual([["/api/portal-access/", {
      contact: "p1", role: "ECC", level: "member", may_create: "projects" }]]));
  });

  it("sends what was chosen", async () => {
    const fetchMock = open();
    await userEvent.selectOptions(await screen.findByLabelText("Team for Ben Orji"), "t2");
    await userEvent.selectOptions(screen.getByLabelText("Level for Ben Orji"), "viewer");
    await userEvent.selectOptions(screen.getByLabelText("What Ben Orji may create"),
                                  "nothing");
    await userEvent.click(screen.getByRole("button", { name: "Grant" }));
    await waitFor(() => expect(sent(fetchMock)).toEqual([["/api/portal-access/", {
      contact: "p1", role: "ECC", team: "t2", level: "viewer", may_create: "nothing" }]]));
  });

  it("asks a client owner nothing: they have everything", async () => {
    const fetchMock = open("FCC");
    expect(await screen.findByLabelText("Grant Ben Orji as")).toHaveValue("FCC");
    expect(screen.queryByLabelText("Level for Ben Orji")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Grant" }));
    await waitFor(() => expect(sent(fetchMock)).toEqual([["/api/portal-access/", {
      contact: "p1", role: "FCC" }]]));
  });

  it("lists who is there by their level, where the role's name used to be all there was",
    async () => {
      const person = { id: "m2", role: "ECC", email: "ben@adapt.invalid", name: "Ben Orji",
                       contact: "p2", invited_at: null, signed_in: true,
                       invitation_expires_at: null, level_label: "Manager",
                       teams: [{ team: "t1", name: "Operations", level: "manager" },
                               { team: "t2", name: "Sales", level: "member" }],
                       may_create: "projects", leads_all_teams: false };
      vi.stubGlobal("fetch", mockApi({
        "/api/portal-access/candidates/": { ...candidates(), people: [] },
        "/api/portal-access/": { ...ACCESS, seats_in_use: 1, people: [person] },
      }));
      renderRoute(<PortalAccessCard me={aMe()} company={aCompany()} />);
      const row = (await screen.findByText("Ben Orji")).closest("tr") as HTMLElement;
      expect(row).toHaveTextContent("Manager · Operations, Sales");
    });
});

describe("the Team field and the filter by team", () => {
  const COMPANIES = [{ id: COMPANY_ID, name: "Adapt CFO", is_client_company: true }];
  const lists = {
    "/api/companies/": COMPANIES, "/api/goals/": [], "/api/portal-people/": [],
    "/api/contacts/": [],
  };

  it("files a new project and a new task on the team chosen, and on none for internal work",
    async () => {
      const posted: [string, unknown][] = [];
      // The writes first: a route with no method answers every method.
      const fetchMock = mockApi({
        "POST /api/projects/": (body: unknown) => {
          posted.push(["project", body]);
          return { status: 201, body: aWorkParent({ id: "p9", kind: "project",
                                                    title: "Route planning" }) };
        },
        "POST /api/tasks/": (body: unknown) => {
          posted.push(["task", body]);
          return { status: 201, body: aTask({ id: "k9", title: "Book the venue" }) };
        },
        ...lists, "/api/projects/": [],
        "/api/client-teams/names/": NAMES,
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<StaffCreate me={aMe()} />);

      await userEvent.click(screen.getByRole("button", { name: "New project" }));
      // Internal work is on no team: there is nothing to choose.
      expect(screen.queryByLabelText("Team for the new project")).toBeNull();
      await userEvent.type(screen.getByLabelText("New project title"), "Route planning");
      await userEvent.selectOptions(
        screen.getByLabelText("Client company for the new item"), COMPANY_ID);
      const team = await screen.findByLabelText("Team for the new project");
      expect(team).toHaveValue("t0");                // the default, until another is chosen
      await userEvent.selectOptions(team, "t2");
      await userEvent.click(screen.getByRole("button", { name: "Create project" }));
      await waitFor(() => expect(posted).toHaveLength(1));

      await userEvent.click(screen.getByRole("button", { name: "New task" }));
      await userEvent.type(screen.getByLabelText("New task title"), "Book the venue");
      await userEvent.selectOptions(
        screen.getByLabelText("Client company for the new item"), COMPANY_ID);
      await userEvent.selectOptions(await screen.findByLabelText("Team for the new task"),
                                    "t1");
      await userEvent.click(screen.getByRole("button", { name: "Create task" }));
      await waitFor(() => expect(posted).toHaveLength(2));
      expect(posted[0]).toEqual(["project", {
        title: "Route planning", client_company: COMPANY_ID, client_team: "t2" }]);
      expect(posted[1][1]).toMatchObject({
        title: "Book the venue", client_company: COMPANY_ID, client_team: "t1" });
    });

  it("a task in a project is on the project's team, which is shown and not asked", async () => {
    let sentTask: Record<string, unknown> = {};
    vi.stubGlobal("fetch", mockApi({
      "POST /api/tasks/": (body: unknown) => {
        sentTask = body as Record<string, unknown>;
        return { status: 201, body: aTask({ id: "k9", title: "Train nights" }) };
      },
      ...lists,
      "/api/projects/": [aWorkParent({ id: "p1", kind: "project", title: "Ops playbook",
                                       client_company: COMPANY_ID, goal: null,
                                       client_team: "t1", client_team_name: "Operations" })],
      "/api/client-teams/names/": NAMES,
    }));
    renderRoute(<StaffCreate me={aMe()} offer={["task"]} />);
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(screen.getByLabelText("New task title"), "Train nights");
    await userEvent.selectOptions(
      screen.getByLabelText("Client company for the new item"), COMPANY_ID);
    await userEvent.selectOptions(await screen.findByLabelText("Team for the new task"), "t2");
    await userEvent.selectOptions(screen.getByLabelText("Project for the new task"), "p1");
    expect(screen.queryByLabelText("Team for the new task")).toBeNull();
    expect(screen.getByText("Operations, the project's team.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(sentTask.project).toBe("p1"));
    expect("client_team" in sentTask).toBe(false);
  });

  it("Work narrows to one team once a client is chosen, and never narrows the goals",
    async () => {
      vi.stubGlobal("fetch", mockApi({
        "/api/companies/": COMPANIES,
        "/api/goals/": [aWorkParent({ id: "g1", title: "Cut order-to-cash",
                                      client_company: COMPANY_ID })],
        "/api/projects/": [
          aWorkParent({ id: "p1", kind: "project", title: "Ops playbook", goal: null,
                        client_company: COMPANY_ID, client_team: "t1",
                        client_team_name: "Operations" }),
          aWorkParent({ id: "p2", kind: "project", title: "Sales playbook", goal: null,
                        client_company: COMPANY_ID, client_team: "t2",
                        client_team_name: "Sales" })],
        "/api/tasks/": [],
        "/api/goal-order/pending/": [], "/api/goal-proposals/pending/": [],
        "/api/client-activity/": [], "/api/client-teams/names/": NAMES,
        "/api/branding/": {},
      }));
      renderRoute(<Work me={aMe()} />);
      expect(await screen.findByText("Ops playbook")).toBeInTheDocument();
      // With every client in view there is no one company's teams to choose from.
      expect(screen.queryByLabelText("Filter by team")).toBeNull();
      await userEvent.selectOptions(screen.getByLabelText("Filter by client company"),
                                    COMPANY_ID);
      await userEvent.selectOptions(await screen.findByLabelText("Filter by team"), "t2");
      expect(screen.queryByText("Ops playbook")).toBeNull();
      expect(screen.getByText("Sales playbook")).toBeInTheDocument();
      expect(screen.getByText("Cut order-to-cash")).toBeInTheDocument();
    });
});
