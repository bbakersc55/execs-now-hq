import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TrackConnectionCard, TrackFeedModal } from "./ScorecardTrack";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

const MEASURES = [
  { key: "occupancy", label: "Occupancy", stream: "reservations", kind: "percent", scope: "property" },
  { key: "maint_open", label: "Maintenance work orders open", stream: "maintenance", kind: "count", scope: "assignee" },
];

describe("Track PMS (M5 part 4)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the practice owner connects it; the secret is a password field and never shown back", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/track/connection/": { connected: true, demo: false, domain: "acme.trackhs.com", key_last4: "1234" },
      "/api/scorecard/track/connection/": { connected: false, demo: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<TrackConnectionCard me={aMe({ role: "FF" })} companyId="c1" />);
    await user.click(await screen.findByRole("button", { name: "Connect Track" }));
    await user.type(screen.getByLabelText("Track address"), "acme.trackhs.com");
    await user.type(screen.getByLabelText("API key"), "k-1234");
    await user.type(screen.getByLabelText("API secret"), "s-9876");
    expect(screen.getByLabelText("API secret")).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual(
      { company: "c1", domain: "acme.trackhs.com", key: "k-1234", secret: "s-9876" }));
  });

  it("an associate sees the state, and can't connect or test", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/track/connection/": {
      connected: true, demo: false, domain: "acme.trackhs.com", key_last4: "1234",
      checked_at: "2026-10-24T10:00:00Z", check_ok: true, check_detail: "Connected: 12 active units." } }));
    renderRoute(<TrackConnectionCard me={aMe({ role: "CF" })} companyId="c1" />);
    expect(await screen.findByText(/Connected: 12 active units/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
  });

  it("the picker offers the menu by stream, and properties or assignees by the measure", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/track/feed/": { feed: {}, run: { ok: true, new: 13 } },
      "/api/scorecard/track/feed/": { kpi: { id: "k1", name: "Open work orders", kind: "count", per_person: false,
        read_open_default: true }, connected: true, feed: null },
      "/api/scorecard/track/options/": { measures: MEASURES, error: "",
        units: [{ id: "101", name: "Beach House" }], assignees: [{ id: "11", name: "Track user 11", work_orders: 4 }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    renderRoute(<TrackFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={onSaved} />);
    const picker = await screen.findByLabelText("Measure");
    await waitFor(() => expect(screen.getByRole("group", { name: "Maintenance" })).toBeInTheDocument());
    await user.selectOptions(picker, "occupancy");
    expect(screen.getByRole("option", { name: "Beach House" })).toBeInTheDocument();
    await user.selectOptions(picker, "maint_open");
    await user.selectOptions(screen.getByLabelText("Assigned to"), "11");
    // On by the KPI's roll-up; turned off here.
    const readOpen = screen.getByLabelText("Also read the current period as it goes");
    expect(readOpen).toBeChecked();
    await user.click(readOpen);
    await user.click(screen.getByRole("button", { name: "Save the measure" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      company: "c1", kpi: "k1", measure: "maint_open", unit_id: "", unit_name: "", assignee_id: "11",
      read_open: false }));
    expect(onSaved).toHaveBeenCalledWith("Open work orders now reads from Track: 13 readings for past periods.");
  });
});
