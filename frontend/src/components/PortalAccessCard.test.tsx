import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aMe, COMPANY_ID } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PortalAccessCard } from "./PortalAccessCard";

const DAY = 24 * 60 * 60 * 1000;
const from_now = (days: number) => new Date(Date.now() + days * DAY).toISOString();

function person(over: Record<string, unknown> = {}) {
  return { id: "m1", role: "ECC", email: "priya@acme.invalid", name: "Priya Shah",
           contact: "c1", invited_at: "2026-10-01T15:00:00Z", signed_in: false,
           invitation_expires_at: from_now(5), ...over };
}

function open(people: unknown[], routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    // First: the stub takes the first route a URL starts with, and the list
    // below is a prefix of every other portal-access address.
    ...routes,
    "/api/portal-access/candidates/": {
      company: COMPANY_ID, company_name: "Acme", is_client_company: true,
      seat_count: 3, seats_in_use: people.length, seat_refusal: null, people: [],
    },
    "/api/portal-access/": {
      company: COMPANY_ID, seat_count: 3, seats_in_use: people.length,
      seats_available: 3 - people.length, may_manage: true, people,
    },
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<PortalAccessCard me={aMe()} company={aCompany()} />);
  return fetchMock;
}

const row = async (name: string) =>
  (await screen.findByText(name)).closest("tr") as HTMLElement;

describe("Resend invitation, on a portal-access row", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends a fresh invitation to that person and says how long it lasts", async () => {
    const user = userEvent.setup();
    const fetchMock = open([person()], {
      "POST /api/portal-access/m1/resend/": () => ({ body: { ...person(), sent: true } }),
    });

    await user.click(within(await row("Priya Shah"))
      .getByRole("button", { name: "Resend invitation" }));

    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url === "/api/portal-access/m1/resend/")).toBe(true));
    expect(await screen.findByText(
      /A new invitation is on its way to priya@acme\.invalid\. Its link is valid for 7 days/,
    )).toBeInTheDocument();
  });

  it("never revokes or grants to do it", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmSpy);
    const fetchMock = open([person()], {
      "POST /api/portal-access/m1/resend/": () => ({ body: { ...person(), sent: true } }),
    });

    await user.click(within(await row("Priya Shah"))
      .getByRole("button", { name: "Resend invitation" }));
    await screen.findByText(/A new invitation is on its way/);

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(fetchMock.calls.filter((c) => c.method === "DELETE")).toEqual([]);
    expect(fetchMock.calls.filter((c) => c.method === "POST").map((c) => c.url))
      .toEqual(["/api/portal-access/m1/resend/"]);
  });

  it("says so when the email could not be sent", async () => {
    const user = userEvent.setup();
    open([person()], {
      "POST /api/portal-access/m1/resend/": () => ({ body: { ...person(), sent: false } }),
    });

    await user.click(within(await row("Priya Shah"))
      .getByRole("button", { name: "Resend invitation" }));

    expect(await screen.findByText(/could not be sent/)).toBeInTheDocument();
    expect(screen.queryByText(/is on its way/)).not.toBeInTheDocument();
  });

  it("shows the server's refusal in its own words", async () => {
    const user = userEvent.setup();
    open([person()], {
      "POST /api/portal-access/m1/resend/": () => ({
        status: 400, body: { detail: "That sign-in has been deactivated, so no link can be sent." },
      }),
    });

    await user.click(within(await row("Priya Shah"))
      .getByRole("button", { name: "Resend invitation" }));

    expect(await screen.findByText(/That sign-in has been deactivated/)).toBeInTheDocument();
  });

  it("each row says where that person stands with their invitation", async () => {
    open([
      person(),
      person({ id: "m2", name: "Dana Reyes", email: "dana@acme.invalid",
               invitation_expires_at: from_now(-2) }),
      person({ id: "m3", name: "Sam Ortiz", email: "sam@acme.invalid", signed_in: true,
               invitation_expires_at: null }),
    ]);

    expect(within(await row("Priya Shah")).getByText(/Invited · link valid until/))
      .toBeInTheDocument();
    expect(within(await row("Dana Reyes")).getByText(/Invitation expired .* not signed in/))
      .toBeInTheDocument();
    expect(within(await row("Sam Ortiz")).getByText("Has signed in")).toBeInTheDocument();
    // Offered on every row: an expired invitation is the case it exists for.
    expect(screen.getAllByRole("button", { name: "Resend invitation" })).toHaveLength(3);
  });
});
