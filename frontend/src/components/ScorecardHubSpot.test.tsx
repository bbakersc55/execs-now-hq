import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HubSpotConnectionCard, HubSpotFeedModal } from "./ScorecardHubSpot";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

const SCOPES = ["crm.objects.deals.read", "crm.objects.contacts.read", "crm.objects.owners.read"];
const MEASURES = [
  { key: "deals_won", label: "Deals won", object: "deals", kind: "count", snapshot: false },
  { key: "pipeline_value", label: "Pipeline value", object: "deals", kind: "money", snapshot: true },
  { key: "calls_logged", label: "Calls logged", object: "calls", kind: "count", snapshot: false },
];
const OPTIONS = { measures: MEASURES, error: "",
  owners: [{ id: "501", name: "Ana Ruiz", email: "ana@alpine.example" }],
  stages: [{ id: "qualifiedtobuy", name: "Qualified to buy" }] };

describe("HubSpot (M5 part 5)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the practice owner pastes a token, told the read scopes; it is a password field and never shown back", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/hubspot/connection/": { connected: true, demo: false, token_last4: "acme", scopes: SCOPES },
      "/api/scorecard/hubspot/connection/": { connected: false, demo: false, scopes: SCOPES },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<HubSpotConnectionCard me={aMe({ role: "FF" })} companyId="c1" />);
    await user.click(await screen.findByRole("button", { name: "Connect HubSpot" }));
    for (const scope of SCOPES) expect(screen.getByText(scope)).toBeInTheDocument();
    const field = screen.getByLabelText("Access token");
    expect(field).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(field, "pat-na1-0000-acme");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual(
      { company: "c1", token: "pat-na1-0000-acme" }));
  });

  it("the practice owner tests it; an associate sees the state and can't", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/hubspot/connection/test/": { connected: true, demo: false, scopes: SCOPES },
      "/api/scorecard/hubspot/connection/": { connected: true, demo: false, token_last4: "acme",
        scopes: SCOPES, checked_at: "2026-10-26T10:00:00Z", check_ok: true, check_detail: "Connected: 2 deal pipelines." },
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = renderRoute(<HubSpotConnectionCard me={aMe({ role: "FF" })} companyId="c1" />);
    expect(await screen.findByText(/Connected: 2 deal pipelines/)).toBeInTheDocument();
    expect(screen.getByText(/token ending acme/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ company: "c1" }));
    view.unmount();
    renderRoute(<HubSpotConnectionCard me={aMe({ role: "CF" })} companyId="c1" />);
    expect(await screen.findByText(/Connected: 2 deal pipelines/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
  });

  it("the picker groups the menu, offers owners, and a stage for pipeline value only", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/hubspot/feed/": { feed: {}, run: { ok: true, new: 0 } },
      "/api/scorecard/hubspot/feed/": { kpi: { id: "k1", name: "Pipeline", kind: "money", per_person: false }, connected: true, feed: null },
      "/api/scorecard/hubspot/options/": OPTIONS,
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    renderRoute(<HubSpotFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={onSaved} />);
    const picker = await screen.findByLabelText("Measure");
    await waitFor(() => expect(screen.getByRole("group", { name: "Activity logged" })).toBeInTheDocument());
    await user.selectOptions(picker, "deals_won");
    expect(screen.getByLabelText("Owner")).toBeInTheDocument();
    expect(screen.queryByLabelText("Stage")).toBeNull();
    await user.selectOptions(picker, "pipeline_value");
    await user.selectOptions(screen.getByLabelText("Owner"), "501");
    await user.selectOptions(screen.getByLabelText("Stage"), "qualifiedtobuy");
    expect(screen.getByText(/read as each period closes and kept/)).toBeInTheDocument();
    // Off for a sum by default; turned on here.
    const readOpen = screen.getByLabelText("Also read the current period as it goes");
    expect(readOpen).not.toBeChecked();
    await user.click(readOpen);
    await user.click(screen.getByRole("button", { name: "Save the measure" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      company: "c1", kpi: "k1", measure: "pipeline_value", owner_id: "501", owner_name: "Ana Ruiz",
      stage_id: "qualifiedtobuy", stage_name: "Qualified to buy", read_open: true }));
    expect(onSaved).toHaveBeenCalledWith("Pipeline now reads from HubSpot. Its first reading comes when this period closes.");
  });

  it("a company with no connection says where to add it", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/hubspot/feed/": {
      kpi: { id: "k1", name: "Calls", kind: "count", per_person: false }, connected: false, feed: null } }));
    renderRoute(<HubSpotFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={() => {}} />);
    expect(await screen.findByText(/no HubSpot connection yet/)).toBeInTheDocument();
  });
});
