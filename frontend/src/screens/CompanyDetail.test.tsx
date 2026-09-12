import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID, aCompany, aContact, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CompanyDetail } from "./CompanyDetail";

function renderCompany(routes: Record<string, unknown>) {
  vi.stubGlobal("fetch", mockApi(routes));
  return renderRoute(<CompanyDetail me={aMe()} />, {
    path: "/companies/:id",
    route: `/companies/${COMPANY_ID}`,
  });
}

describe("CompanyDetail", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("renders a company with contacts, a client flag and seat usage", async () => {
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [
        { kind: "stage", when: "2026-09-11T00:16:58Z", text: "Eric moved to Prospecting (Sales)" },
      ],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "/api/contacts/": [
        aContact(),
        aContact({ id: "other", first_name: "Dana", last_name: "Reyes" }),
        // A contact at a DIFFERENT company must not appear here.
        aContact({ id: "elsewhere", first_name: "Sam", company: "another-company" }),
      ],
    });

    expect(await screen.findByRole("heading", { name: "Adapt CFO" })).toBeInTheDocument();
    expect(screen.getByText("client company")).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 seats used/)).toBeInTheDocument();

    // Only this company's people, and each with their pipeline position.
    expect(await screen.findByText("People (2)")).toBeInTheDocument();
    expect(screen.getByText("Hassam Khan")).toBeInTheDocument();
    expect(screen.getByText("Dana Reyes")).toBeInTheDocument();
    expect(screen.queryByText("Sam Khan")).not.toBeInTheDocument();
    expect(screen.getAllByText("Sales: Prospecting")).toHaveLength(2);

    expect(screen.getByText(/moved to Prospecting/)).toBeInTheDocument();
  });

  it("renders a contact who is in no pipeline", async () => {
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "/api/contacts/": [aContact({ pipeline_positions: [] })],
    });

    expect(await screen.findByText("no pipeline")).toBeInTheDocument();
  });

  it("survives a contact payload with no pipeline_positions field at all", async () => {
    // The shape that takes a screen down if anything reads `.length` on it
    // unguarded: an older cached response, or a leaner serializer later.
    const { pipeline_positions: _omitted, ...withoutPositions } = aContact();
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "/api/contacts/": [withoutPositions],
    });

    expect(await screen.findByText("Hassam Khan")).toBeInTheDocument();
    expect(screen.getByText("no pipeline")).toBeInTheDocument();
  });

  it("renders a non-client company with no seats and no contacts", async () => {
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany({
        is_client_company: false, seat_count: null, seats_in_use: 0,
        seats_available: 0, industry: "",
      }),
      "/api/contacts/": [],
    });

    expect(await screen.findByRole("heading", { name: "Adapt CFO" })).toBeInTheDocument();
    expect(screen.getByText("No industry")).toBeInTheDocument();
    expect(screen.queryByText("client company")).not.toBeInTheDocument();
    expect(screen.queryByText(/seats used/)).not.toBeInTheDocument();
    expect(await screen.findByText("No contacts at this company.")).toBeInTheDocument();
  });
});

describe("the portal-access picker", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const ACCESS = {
    company: COMPANY_ID, seat_count: 3, seats_in_use: 0, seats_available: 3,
    may_manage: true, people: [],
  };

  function candidates(people: unknown[], extra: Record<string, unknown> = {}) {
    return {
      company: COMPANY_ID, company_name: "Adapt CFO", is_client_company: true,
      seat_count: 3, seats_in_use: 0, seat_refusal: null, people, ...extra,
    };
  }

  function aPerson(over: Record<string, unknown> = {}) {
    return {
      contact: "p1", name: "Dana Reyes", email: "dana@adapt.invalid",
      title: "COO", role: "ECC", refusal: null, ...over,
    };
  }

  it("offers the company's people with nothing typed, and grants one", async () => {
    // The bug: the picker searched every contact in the tenant by full text, so
    // it showed nobody until a whole indexed word was typed.
    let granted: unknown = null;
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ seats_in_use: 0, seats_available: 3 }),
      "/api/portal-access/candidates/": candidates([
        aPerson(), aPerson({ contact: "p2", name: "Ben Orji", email: "ben@adapt.invalid" }),
      ]),
      "POST /api/portal-access/": (body: unknown) => {
        granted = body;
        return { status: 201, body: { id: "m1", role: "ECC" } };
      },
      "/api/portal-access/": ACCESS,
      "/api/contacts/": [],
    });

    const buttons = await screen.findAllByRole("button", { name: "Grant" });
    expect(buttons).toHaveLength(2);
    expect(screen.getByText("Dana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Ben Orji")).toBeInTheDocument();

    await userEvent.click(buttons[0]);
    expect(granted).toEqual({ contact: "p1" });
    expect(await screen.findByText(/Access granted and a sign-in link sent/)).toBeInTheDocument();
  });

  it("passes what is typed to the server as a plain fragment", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      urls.push(url);
      const body = url.startsWith("/api/portal-access/candidates/")
        ? candidates([aPerson()])
        : url.startsWith("/api/portal-access/") ? ACCESS
        : url.startsWith(`/api/companies/${COMPANY_ID}/timeline`) ? []
        : url.startsWith(`/api/companies/${COMPANY_ID}/`) ? aCompany()
        : [];
      return new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));
    renderRoute(<CompanyDetail me={aMe()} />, {
      path: "/companies/:id", route: `/companies/${COMPANY_ID}`,
    });

    await userEvent.type(await screen.findByLabelText("Narrow this company's people"), "Dan");
    await waitFor(() => expect(urls.some((u) => u.includes("candidates/") && u.includes("q=Dan")))
      .toBe(true));
    // Never the global contact search, which is what missed everyone.
    expect(urls.some((u) => u.includes("/api/contacts/search/"))).toBe(false);
  });

  it("shows why someone cannot be granted instead of hiding them", async () => {
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "/api/portal-access/candidates/": candidates([
        aPerson({ email: "", refusal: "Dana has no email address, so no sign-in link can be sent." }),
      ]),
      "/api/portal-access/": ACCESS,
      "/api/contacts/": [],
    });

    expect(await screen.findByText(/Dana has no email address/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant" })).toBeDisabled();
  });

  it("says no seats are allocated rather than implying no limit", async () => {
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ seat_count: null }),
      "/api/portal-access/candidates/": candidates(
        [aPerson({ refusal: "No seats have been allocated to Adapt CFO yet." })],
        { seat_count: null, seat_refusal: "No seats have been allocated to Adapt CFO yet." },
      ),
      "/api/portal-access/": { ...ACCESS, seat_count: null, seats_available: 0 },
      "/api/contacts/": [],
    });

    expect(await screen.findByText(/No seats allocated yet/)).toBeInTheDocument();
    expect(screen.queryByText(/no seat limit set/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant" })).toBeDisabled();
  });
});
