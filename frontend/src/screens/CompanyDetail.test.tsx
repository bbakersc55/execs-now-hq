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
      "/api/portal-access/candidates/": {
        company: COMPANY_ID, company_name: "Adapt CFO", is_client_company: true,
        seat_count: 3, seats_in_use: 2, seat_refusal: null, people: [],
      },
      "/api/portal-access/": {
        company: COMPANY_ID, seat_count: 3, seats_in_use: 2, seats_available: 1,
        may_manage: true, people: [],
      },
      "/api/contacts/": [
        aContact(),
        aContact({ id: "other", first_name: "Dana", last_name: "Reyes" }),
        // A contact at a DIFFERENT company must not appear here.
        aContact({ id: "elsewhere", first_name: "Sam", company: "another-company" }),
      ],
    });

    expect(await screen.findByRole("heading", { name: "Adapt CFO" })).toBeInTheDocument();
    expect(screen.getByText("client company")).toBeInTheDocument();
    // From the portal-access count, which lands after the company record.
    expect(await screen.findByText(/2 of 3 seats used/)).toBeInTheDocument();

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
    expect(granted).toEqual({ contact: "p1", role: "ECC" });
    expect(await screen.findByText(/Access granted and a sign-in link sent/)).toBeInTheDocument();
  });

  it("preselects each person's default role and grants the one chosen", async () => {
    const posted: unknown[] = [];
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ primary_contact: "p1" }),
      "/api/portal-access/candidates/": candidates([
        aPerson({ role: "FCC" }),
        aPerson({ contact: "p2", name: "Ben Orji", email: "ben@adapt.invalid" }),
      ]),
      "POST /api/portal-access/": (body: unknown) => {
        posted.push(body);
        return { status: 201, body: { id: "m1" } };
      },
      "/api/portal-access/": ACCESS,
      "/api/contacts/": [],
    });

    expect(await screen.findByLabelText("Grant Dana Reyes as")).toHaveValue("FCC");
    expect(screen.getByLabelText("Grant Ben Orji as")).toHaveValue("ECC");

    await userEvent.selectOptions(screen.getByLabelText("Grant Ben Orji as"), "FCC");
    await userEvent.click(screen.getAllByRole("button", { name: "Grant" })[1]);
    await waitFor(() => expect(posted).toEqual([{ contact: "p2", role: "FCC" }]));
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

describe("changing an existing portal user's role", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const PEOPLE = [
    { id: "m1", role: "FCC", email: "dana@adapt.invalid", name: "Dana Reyes",
      contact: "p1", invited_at: null },
    { id: "m2", role: "ECC", email: "ben@adapt.invalid", name: "Ben Orji",
      contact: "p2", invited_at: null },
  ];

  function withPatch(onPatch: (body: unknown) => void) {
    return renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "PATCH /api/portal-access/m1/": (body: unknown) => {
        onPatch(body);
        return { status: 200, body: { ...PEOPLE[0], role: "ECC", changed: true, sessions_ended: 1 } };
      },
      "PATCH /api/portal-access/m2/": (body: unknown) => {
        onPatch(body);
        return { status: 200, body: { ...PEOPLE[1], role: "FCC", changed: true, sessions_ended: 0 } };
      },
      "/api/portal-access/candidates/": {
        company: COMPANY_ID, company_name: "Adapt CFO", is_client_company: true,
        seat_count: 3, seats_in_use: 2, seat_refusal: null, people: [],
      },
      "/api/portal-access/": {
        company: COMPANY_ID, seat_count: 3, seats_in_use: 2, seats_available: 1,
        may_manage: true, people: PEOPLE,
      },
      "/api/contacts/": [],
    });
  }

  it("widens to founder without asking", async () => {
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmMock);
    const patches: unknown[] = [];
    withPatch((b) => patches.push(b));

    await userEvent.selectOptions(await screen.findByLabelText("Role for Ben Orji"), "FCC");
    await waitFor(() => expect(patches).toEqual([{ role: "FCC" }]));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/Role changed to founder/)).toBeInTheDocument();
  });

  it("asks before narrowing to employee, and sends nothing if declined", async () => {
    const patches: unknown[] = [];
    vi.stubGlobal("confirm", vi.fn(() => false));
    withPatch((b) => patches.push(b));

    await userEvent.selectOptions(await screen.findByLabelText("Role for Dana Reyes"), "ECC");
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/sessions and any unused sign-in links end/));
    expect(patches).toEqual([]);

    vi.stubGlobal("confirm", vi.fn(() => true));
    await userEvent.selectOptions(screen.getByLabelText("Role for Dana Reyes"), "ECC");
    await waitFor(() => expect(patches).toEqual([{ role: "ECC" }]));
    expect(await screen.findByText(/1 session\(s\) ended/)).toBeInTheDocument();
  });

  it("is not offered to a VA", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany(),
      "/api/contacts/": [],
    }));
    renderRoute(<CompanyDetail me={aMe({ role: "VA" })} />, {
      path: "/companies/:id", route: `/companies/${COMPANY_ID}`,
    });
    expect(await screen.findByRole("heading", { name: "Adapt CFO" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Role for/)).not.toBeInTheDocument();
  });
});

describe("seat usage after a revoke", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("updates the header and the card together, from one count", async () => {
    // The bug: the header read the company record and still said "2 of 3 seats
    // used" while the card said "1 of 3 seats in use", until a reload.
    vi.stubGlobal("confirm", vi.fn(() => true));
    let inUse = 2;
    const person = { id: "m2", role: "ECC", email: "ben@adapt.invalid", name: "Ben Orji",
                     contact: "p2", invited_at: null };
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      // The company record is deliberately stale: it must not be what the header reads.
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ seats_in_use: 2, seats_available: 1 }),
      "DELETE /api/portal-access/m2/": () => {
        inUse = 1;
        return { status: 200, body: { sessions_ended: 1, links_invalidated: 0 } };
      },
      "/api/portal-access/candidates/": {
        company: COMPANY_ID, company_name: "Adapt CFO", is_client_company: true,
        seat_count: 3, seats_in_use: 2, seat_refusal: null, people: [],
      },
      "/api/portal-access/": () => ({
        status: 200,
        body: { company: COMPANY_ID, seat_count: 3, seats_in_use: inUse,
                seats_available: 3 - inUse, may_manage: true,
                people: inUse === 2 ? [person] : [] },
      }),
      "/api/contacts/": [],
    });

    expect(await screen.findByText(/2 of 3 seats used/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 seats in use/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));

    expect(await screen.findByText(/1 of 3 seats in use/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 3 seats used/)).toBeInTheDocument();
    expect(screen.queryByText(/2 of 3 seats/)).not.toBeInTheDocument();
  });
});

describe("the primary contact on the People list", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const people = [
    aContact({ id: "p1", first_name: "Dana", last_name: "Reyes" }),
    aContact({ id: "p2", first_name: "Ben", last_name: "Orji" }),
  ];

  it("marks the primary contact and sets another from the list", async () => {
    let body: unknown = null;
    renderCompany({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`PATCH /api/companies/${COMPANY_ID}/`]: (b: unknown) => {
        body = b;
        return { status: 200, body: aCompany({ is_client_company: false, primary_contact: "p2" }) };
      },
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ is_client_company: false, primary_contact: "p1" }),
      "/api/contacts/": people,
    });

    expect(await screen.findByText("primary contact")).toBeInTheDocument();
    // No button on the person who already is.
    expect(screen.queryByRole("button", { name: "Set Dana Reyes as primary contact" }))
      .not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Set Ben Orji as primary contact" }));
    await waitFor(() => expect(body).toEqual({ primary_contact: "p2" }));
    expect(await screen.findByText(/Ben Orji is now the primary contact/)).toBeInTheDocument();
    expect(screen.getByText(/nobody's existing portal role changed/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Set Dana Reyes as primary contact" }))
      .toBeInTheDocument();
  });

  it("is not offered to a VA (matrix 4.8)", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`/api/companies/${COMPANY_ID}/timeline/`]: [],
      [`/api/companies/${COMPANY_ID}/`]: aCompany({ is_client_company: false, primary_contact: "p1" }),
      "/api/contacts/": people,
    }));
    renderRoute(<CompanyDetail me={aMe({ role: "VA" })} />, {
      path: "/companies/:id", route: `/companies/${COMPANY_ID}`,
    });
    expect(await screen.findByText("primary contact")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /as primary contact/ })).not.toBeInTheDocument();
  });

});
