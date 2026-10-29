import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BestyConnectionCard, BestyFeedModal } from "./ScorecardBesty";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

const MEASURES = [
  { key: "tasks_open", label: "Ops tasks open", tool: "export_ops_tasks", kind: "count", scope: "member" },
  { key: "upsell_revenue", label: "Upsell revenue", tool: "export_upsell_events", kind: "money", scope: "upsell" },
  { key: "response_time", label: "Guest response time (average)", tool: "compute_response_time", kind: "duration", scope: "responder" },
  { key: "reviews_received", label: "Reviews received", tool: "export_reviews", kind: "count", scope: "total" },
  { key: "owner_messages", label: "Messages to owners (sent by people)", tool: "export_messages", kind: "count", scope: "owner" },
];
const OPTIONS = { measures: MEASURES, error: "",
  members: [{ id: "m1", name: "Dana Whitfield" }], owners: [{ id: "9001", name: "Harbor View Holdings" }],
  upsell_types: [{ id: "late_checkout", name: "Late checkout" }],
  responders: [{ id: "", name: "Everyone, autopilot included" }, { id: "people", name: "People only (no autopilot)" }] };
const STATE = { kpi: { id: "k1", name: "Owner touches", kind: "count", per_person: false, read_open_default: false },
  connected: true, feed: null };

describe("Besty (M5 part 6)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the practice owner pastes the token into a password field; it is never shown back", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/besty/connection/": { connected: true, demo: false, token_last4: "acme" },
      "/api/scorecard/besty/connection/": { connected: false, demo: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<BestyConnectionCard me={aMe({ role: "FF" })} companyId="c1" />);
    await user.click(await screen.findByRole("button", { name: "Connect Besty" }));
    const field = screen.getByLabelText("MCP token");
    expect(field).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(field, "besty-0000-acme");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual(
      { company: "c1", token: "besty-0000-acme" }));
  });

  it("the practice owner tests it; an associate sees the state and can't", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/besty/connection/test/": { connected: true, demo: false },
      "/api/scorecard/besty/connection/": { connected: true, demo: false, token_last4: "acme",
        checked_at: "2026-10-28T10:00:00Z", check_ok: true, check_detail: "Connected: 124 read-only tools." },
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = renderRoute(<BestyConnectionCard me={aMe({ role: "FF" })} companyId="c1" />);
    expect(await screen.findByText(/Connected: 124 read-only tools/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ company: "c1" }));
    view.unmount();
    renderRoute(<BestyConnectionCard me={aMe({ role: "CF" })} companyId="c1" />);
    expect(await screen.findByText(/Connected: 124 read-only tools/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect Besty" })).toBeNull();
  });

  it("the picker groups the menu and offers each measure's own choices", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/besty/feed/": { feed: {}, run: { ok: true, new: 4 } },
      "/api/scorecard/besty/feed/": STATE,
      "/api/scorecard/besty/options/": OPTIONS,
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    renderRoute(<BestyFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={onSaved} />);
    const picker = await screen.findByLabelText("Measure");
    await waitFor(() => expect(screen.getByRole("group", { name: "Owners" })).toBeInTheDocument());
    for (const g of ["Ops tasks", "Upsells", "Guests"]) expect(screen.getByRole("group", { name: g })).toBeInTheDocument();
    await user.selectOptions(picker, "reviews_received");
    expect(screen.queryByLabelText("Team member")).toBeNull();
    await user.selectOptions(picker, "upsell_revenue");
    expect(screen.getByLabelText("Upsell type")).toBeInTheDocument();
    await user.selectOptions(picker, "response_time");
    await user.selectOptions(screen.getByLabelText("Whose replies"), "member:m1");
    await user.selectOptions(picker, "owner_messages");
    await user.selectOptions(screen.getByLabelText("Owner"), "9001");
    expect(screen.getByLabelText("Team member")).toHaveValue("m1");
    expect(screen.getByLabelText("Also read the current period as it goes")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save the measure" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      company: "c1", kpi: "k1", measure: "owner_messages", read_open: false, member_id: "m1",
      member_name: "Dana Whitfield", owner_id: "9001", owner_name: "Harbor View Holdings", param: "" }));
    expect(onSaved).toHaveBeenCalledWith("Owner touches now reads from Besty: 4 readings for past periods.");
  });

  it("a company with no connection says where to add it", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/besty/feed/": { ...STATE, connected: false } }));
    renderRoute(<BestyFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={() => {}} />);
    expect(await screen.findByText(/no Besty connection yet/)).toBeInTheDocument();
  });
});
