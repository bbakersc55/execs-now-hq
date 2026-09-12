import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { GrantPortalAccess } from "./GrantPortalAccess";

const CONTACT = "c1";

function candidate(over: Record<string, unknown> = {}, person: Record<string, unknown> = {}) {
  return {
    company: "co1", company_name: "Acme Facilities", is_client_company: true,
    seat_count: 3, seats_in_use: 1, seat_refusal: null,
    people: [{
      contact: CONTACT, name: "Dana Reyes", email: "dana@acme.invalid",
      title: "COO", role: "ECC", refusal: null, ...person,
    }],
    ...over,
  };
}

describe("GrantPortalAccess", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function render(routes: Record<string, unknown>, me = aMe()) {
    vi.stubGlobal("fetch", mockApi(routes));
    return renderRoute(<GrantPortalAccess me={me} contactId={CONTACT} />);
  }

  it("grants from the contact page with no search involved", async () => {
    let granted: unknown = null;
    render({
      "/api/portal-access/candidates/": candidate(),
      "POST /api/portal-access/": (body: unknown) => {
        granted = body;
        return { status: 201, body: { id: "m1", role: "ECC" } };
      },
    });

    expect(await screen.findByText(/1 of 3 seats in use/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Grant portal access" }));
    expect(granted).toEqual({ contact: CONTACT });
    expect(await screen.findByText(/Access granted and a sign-in link sent/)).toBeInTheDocument();
  });

  it("explains a refusal instead of offering a button that would fail", async () => {
    render({
      "/api/portal-access/candidates/": candidate(
        { is_client_company: false },
        { refusal: "Dana is not at a client company, so there is nothing to give them access to." },
      ),
    });

    expect(await screen.findByText(/not at a client company/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Grant portal access" })).not.toBeInTheDocument();
  });

  it("surfaces the seat refusal the server gives", async () => {
    render({
      "/api/portal-access/candidates/": candidate(
        { seat_count: null, seat_refusal: "No seats have been allocated to Acme Facilities yet." },
        { refusal: "No seats have been allocated to Acme Facilities yet." },
      ),
    });

    expect(await screen.findByText(/No seats have been allocated/)).toBeInTheDocument();
  });

  it("is not there for a VA or a client user", async () => {
    // Matrix §9 — a VA never grants, so a VA is not shown the control. No
    // request is made either: the card is gone before it asks.
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<GrantPortalAccess me={aMe({ role: "VA" })} contactId={CONTACT} />);
    expect(screen.queryByText("Portal access")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
