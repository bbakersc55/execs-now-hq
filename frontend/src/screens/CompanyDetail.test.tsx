import { screen } from "@testing-library/react";
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
