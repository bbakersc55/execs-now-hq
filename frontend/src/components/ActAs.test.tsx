import { screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalAccessCard } from "./PortalAccessCard";
import { aCompany, aMe, COMPANY_ID } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ActAsButton, ActAsColleague, ActingBanner } from "./ActAs";

const ACTING = {
  real_name: "Bryan Baker", real_email: "bryan@practice.invalid", real_role: "FF",
  as_membership: "m2", as_name: "Priya Shah", as_email: "priya@acme.invalid", as_role: "ECC",
  company: COMPANY_ID, company_name: "Acme Facilities",
};

/** Renders `element` at "/" plus a marker route, so navigation is observable. */
function at(element: ReactElement) {
  return renderRoute(
    <Routes>
      <Route path="/" element={element} />
      <Route path="/work" element={<p>WORK SCREEN</p>} />
      <Route path="/companies/:id" element={<p>COMPANY SCREEN</p>} />
    </Routes>,
    { path: "/*", route: "/" },
  );
}

describe("the acting-as banner (FR-3.42)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("names both people, says no email is sent, and stops explicitly", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/act-as/stop/": { stopped: true, return_to: `/companies/${COMPANY_ID}` },
    });
    vi.stubGlobal("fetch", fetchMock);
    at(<ActingBanner me={aMe({ role: "ECC", acting: ACTING })} />);

    const banner = screen.getByRole("status", { name: "Acting as" });
    expect(banner).toHaveTextContent("Bryan Baker is acting as Priya Shah");
    expect(banner).toHaveTextContent("employee, Acme Facilities");
    expect(banner).toHaveTextContent("no email is sent");

    await user.click(screen.getByRole("button", { name: "Stop acting as Priya Shah" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url === "/api/act-as/stop/")).toBe(true));
    expect(await screen.findByText("COMPANY SCREEN")).toBeInTheDocument();
  });

  it("is absent when nobody is acting", () => {
    at(<ActingBanner me={aMe()} />);
    expect(screen.queryByRole("status", { name: "Acting as" })).not.toBeInTheDocument();
  });
});

describe("starting to act as someone", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks first, then starts and lands in the portal", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/act-as/": { as_name: "Priya Shah" } });
    vi.stubGlobal("fetch", fetchMock);
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmMock);
    at(<ActAsButton membership="m2" name="Priya Shah" />);

    await user.click(screen.getByRole("button", { name: "Act as Priya Shah" }));
    expect(confirmMock).toHaveBeenCalledWith(expect.stringMatching(/no email is sent/));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ membership: "m2" }));
    expect(await screen.findByText("WORK SCREEN")).toBeInTheDocument();
  });

  it("sends nothing if the confirmation is declined", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({});
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => false));
    at(<ActAsButton membership="m2" name="Priya Shah" />);
    await user.click(screen.getByRole("button", { name: "Act as Priya Shah" }));
    expect(fetchMock.calls).toEqual([]);
  });

  it("is on each portal user row for the practice, and gone while acting", async () => {
    const access = {
      company: COMPANY_ID, seat_count: 3, seats_in_use: 1, seats_available: 2, may_manage: true,
      people: [{ id: "m2", role: "ECC", email: "priya@acme.invalid", name: "Priya Shah",
                 contact: "p2", invited_at: null }],
    };
    const routes = {
      "/api/portal-access/candidates/": { company: COMPANY_ID, company_name: "Acme",
        is_client_company: true, seat_count: 3, seats_in_use: 1, seat_refusal: null, people: [] },
      "/api/portal-access/": access,
    };
    vi.stubGlobal("fetch", mockApi(routes));
    const { unmount } = renderRoute(<PortalAccessCard me={aMe()} company={aCompany()} />);
    expect(await screen.findByRole("button", { name: "Act as Priya Shah" })).toBeInTheDocument();
    unmount();

    vi.stubGlobal("fetch", mockApi(routes));
    renderRoute(<PortalAccessCard me={aMe({ acting: ACTING })} company={aCompany()} />);
    expect(await screen.findByText("Priya Shah")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Act as Priya Shah" })).not.toBeInTheDocument();
  });

  it("offers a founder user their colleagues, and nobody else a picker", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/act-as/": { as_name: "Priya Shah" },
      "/api/act-as/candidates/": [{ membership: "m2", name: "Priya Shah",
        email: "priya@acme.invalid", role: "ECC", company: COMPANY_ID, company_name: "Acme" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    at(<ActAsColleague me={aMe({ role: "FCC", client_company: COMPANY_ID })} />);
    await user.selectOptions(await screen.findByLabelText("Act as a colleague"), "m2");
    await user.click(screen.getByRole("button", { name: "Act as" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ membership: "m2" }));

    const quiet = vi.fn();
    vi.stubGlobal("fetch", quiet);
    for (const role of ["ECC", "FF", "VA"] as const) {
      const { unmount } = at(<ActAsColleague me={aMe({ role })} />);
      expect(screen.queryByLabelText("Act as a colleague")).not.toBeInTheDocument();
      unmount();
    }
    expect(quiet).not.toHaveBeenCalled();
  });
});
