import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PracticeRow, Practices } from "./Practices";

const EN: PracticeRow = {
  id: "11111111-1111-4111-8111-111111111111", display_name: "Executives Now",
  legal_name: "", domain: "", status: "active", created_at: "2026-09-09T16:14:43Z",
  archived_at: null, oauth_client: "internal", staff_count: 1, client_count: 3,
  ai_spend_this_month_usd: "0.23", last_activity_at: "2026-10-02T20:03:48Z",
};

describe("the Practices area (P2)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists each practice by its totals", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/platform/practices": [EN] }));
    renderRoute(<Practices />);
    const row = (await screen.findByText("Executives Now")).closest("tr")!;
    expect(within(row).getByText("$0.23")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(within(row).getByText("No legal name yet · no domain yet")).toBeInTheDocument();
  });

  it("adds a practice with the four details, and says the owner is not invited yet", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/platform/practices": (body: unknown) => ({ status: 201, body: {
        ...EN, id: "2", display_name: (body as { display_name: string }).display_name,
        status: "invited" } }),
      "GET /api/platform/practices": [EN],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Practices />);
    await screen.findByText("Executives Now");
    await user.type(screen.getByLabelText("Legal name"), "Blue Sky Business Consulting LLC");
    await user.type(screen.getByLabelText("Display name"), "Blue Sky Business Consulting");
    await user.type(screen.getByLabelText("Domain"), "blueskybizconsulting.com");
    await user.type(screen.getByLabelText("Owner's email"), "shawn@bluesky.invalid");
    await user.click(screen.getByRole("button", { name: "Add practice" }));
    expect(await screen.findByText(/Its owner has not been invited yet/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({
      legal_name: "Blue Sky Business Consulting LLC", display_name: "Blue Sky Business Consulting",
      domain: "blueskybizconsulting.com", owner_email: "shawn@bluesky.invalid" });
  });
});

describe("the area switch", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is shown only to the platform owner", async () => {
    const { AreaSwitch } = await import("../components/AreaSwitch");
    const { container, rerender } = renderRoute(
      <AreaSwitch me={aMe({ role: "FF" })} />);
    expect(container.querySelector("select")).toBeNull();
    rerender(<></>);
    renderRoute(<AreaSwitch me={{ ...aMe({ role: "FF" }), is_platform_owner: true,
      area: "practice", home_practice: "Executives Now" }} />);
    const select = screen.getByLabelText("Area");
    expect(within(select).getByRole("option", { name: "Executives Now" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Practices" })).toBeInTheDocument();
  });

  it("the app in the Practices area shows only Practices, as the platform owner", async () => {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me": { ...aMe({ role: "FF" }), role: null, area: "platform",
        is_platform_owner: true, home_practice: "Executives Now" },
      "GET /api/branding": { display_name: "", logo_url: "", mark_url: "", footer_text: "",
        palette: { header: "#1F2933", accent: "#7B8794", on_header: "#FFFFFF",
          on_accent: "#1F2933", gray_dark: "#6D6E71", gray_light: "#939598" },
        product_name: "Execs NOW HQ" },
      "GET /api/platform/practices": [EN],
    }));
    renderRoute(<App />, { path: "*", route: "/practices" });
    expect(await screen.findByText("Platform owner")).toBeInTheDocument();
    const nav = screen.getByRole("navigation");
    await waitFor(() => expect(within(nav).getAllByRole("link").map((a) => a.textContent))
      .toEqual(["Practices", "Feedback"]));
    expect(screen.queryByText("Contacts")).toBeNull();
  });
});
