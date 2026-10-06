import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Me } from "../lib/api";
import { aCompany, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ClientStatus } from "./ClientStatus";
import { StaffCreate } from "./StaffCreate";

const CO = aCompany({ id: "co1", name: "Referred Co", is_client_company: false });
const state = (is_client_company: boolean, undo_blockers: string[] = []) =>
  ({ id: "co1", is_client_company, undo_blockers });

function show(me: Me, now: ReturnType<typeof state>, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "POST /api/companies/co1/mark-client/": state(true),
    "POST /api/companies/co1/unmark-client/": state(false),
    "GET /api/companies/co1/client-status/": now,
    // Last, so a test's own answer replaces the default for the same route.
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<ClientStatus me={me} company={{ ...CO, is_client_company: now.is_client_company }} />);
  return fetchMock;
}
const posts = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.calls.filter((c) => c.method === "POST").map((c) => c.url);

/** Mark as a client, and its undo (beta feedback, 2026-10-05, item D). */
describe("a company's client status", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("explains why a non-client company is not offered, and how it becomes one", async () => {
    show(aMe({ role: "VA" }), state(false));

    const card = (await screen.findByRole("heading", { name: "Not a client company" }))
      .closest("section")!;
    expect(card).toHaveTextContent(/for client companies only/);
    expect(card).toHaveTextContent(/reaches Closed Won on the Pipeline/);
    expect(card).toHaveTextContent(/practice owner marks it as a client/);
    expect(within(card).getByRole("link", { name: "Open the Pipeline" }))
      .toHaveAttribute("href", "/pipeline");
  });

  it.each(["CF", "VA"] as const)("offers %s no way to mark or unmark", async (role) => {
    show(aMe({ role }), state(false));
    await screen.findByRole("heading", { name: "Not a client company" });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says exactly what marking sets, and what Closed Won does that it does not", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aMe({ role: "FF" }), state(false));

    await user.click(await screen.findByRole("button", { name: "Mark as a client" }));
    const ask = screen.getByRole("group", { name: "Mark as a client" });

    expect(ask).toHaveTextContent(/It sets one thing: Referred Co becomes a client company/);
    expect(ask).toHaveTextContent(/Unlike reaching Closed Won, it does not move anyone on the Pipeline/);
    expect(ask).toHaveTextContent(/give any contact the client type/);
    expect(ask).toHaveTextContent(/run any stage automation: no task is created and no email is drafted/);
    expect(ask).toHaveTextContent(/audit trail/);
    // Nothing happens until it is confirmed.
    expect(posts(fetchMock)).toEqual([]);

    await user.click(within(ask).getByRole("button", { name: "Yes, mark as a client" }));

    expect(await screen.findByRole("heading", { name: "Client company" })).toBeInTheDocument();
    expect(posts(fetchMock)).toEqual(["/api/companies/co1/mark-client/"]);
  });

  it("can be cancelled without marking anything", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aMe({ role: "FF" }), state(false));
    await user.click(await screen.findByRole("button", { name: "Mark as a client" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(posts(fetchMock)).toEqual([]);
    expect(screen.getByRole("button", { name: "Mark as a client" })).toBeInTheDocument();
  });

  it("undoes a mark made by mistake, after asking", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aMe({ role: "FF" }), state(true));

    await user.click(await screen.findByText("Marked as a client by mistake?"));
    await user.click(screen.getByRole("button", { name: "Not a client after all" }));
    expect(posts(fetchMock)).toEqual([]);
    expect(screen.getByText(/Nothing is deleted/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Yes, it is not a client" }));

    expect(await screen.findByRole("heading", { name: "Not a client company" }))
      .toBeInTheDocument();
    expect(posts(fetchMock)).toEqual(["/api/companies/co1/unmark-client/"]);
  });

  it("says what blocks the undo instead of offering it", async () => {
    const user = userEvent.setup();
    show(aMe({ role: "FF" }), state(true, [
      "1 person has portal access. Remove their access first.",
      "It has 2 goals filed under it. Move or delete them first.",
    ]));

    await user.click(await screen.findByText("Marked as a client by mistake?"));

    expect(screen.getByText("1 person has portal access. Remove their access first."))
      .toBeInTheDocument();
    expect(screen.getByText(/2 goals filed under it/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Not a client/ })).not.toBeInTheDocument();
  });

  it("shows the reasons if the undo is refused after all", async () => {
    const user = userEvent.setup();
    show(aMe({ role: "FF" }), state(true), {
      "POST /api/companies/co1/unmark-client/": () => ({ status: 409, body: {
        detail: "This company cannot stop being a client yet.",
        ...state(true, ["1 task filed under it."]) } }),
    });
    await user.click(await screen.findByText("Marked as a client by mistake?"));
    await user.click(screen.getByRole("button", { name: "Not a client after all" }));
    await user.click(screen.getByRole("button", { name: "Yes, it is not a client" }));

    expect(await screen.findByText("This company cannot stop being a client yet."))
      .toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("1 task filed under it.")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Client company" })).toBeInTheDocument();
  });
});

describe("the client company dropdown on New goal", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function showForm(companies: unknown[]) {
    vi.stubGlobal("fetch", mockApi({
      "/api/companies/": companies, "/api/goals/": [], "/api/projects/": [],
      "/api/portal-people/": [], "/api/contacts/": [],
    }));
    renderRoute(<StaffCreate me={aMe({ role: "FF" })} />);
  }

  it("explains itself when the practice has a company that is not listed", async () => {
    // Shawn's first day: one company added, and the dropdown said "Internal".
    const user = userEvent.setup();
    showForm([{ id: "c1", name: "Blue Sky's first company", is_client_company: false }]);
    await user.click(screen.getByRole("button", { name: "New goal" }));

    const field = (await screen.findByLabelText("Client company for the new item"))
      .closest(".field")!;
    await waitFor(() => expect(field).toHaveTextContent("Only client companies are listed."));
    expect(field).toHaveTextContent(/reaches Closed Won on the Pipeline/);
    expect(field).toHaveTextContent(/practice owner marks it as a client on the company's page/);
    expect(within(field as HTMLElement).getByRole("link", { name: "Companies" }))
      .toHaveAttribute("href", "/companies");
  });

  it("says nothing when every company is already a client", async () => {
    const user = userEvent.setup();
    showForm([{ id: "c1", name: "Acme", is_client_company: true }]);
    await user.click(screen.getByRole("button", { name: "New goal" }));
    await screen.findByRole("option", { name: "Acme" });
    expect(screen.queryByText(/Only client companies are listed/)).not.toBeInTheDocument();
  });
});
