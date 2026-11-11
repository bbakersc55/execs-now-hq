import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KpiLibraryPicker } from "../components/KpiLibrary";
import { CentersState, LibraryState } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CommandCentersSettings } from "./CommandCenters";

const ops = { code: "operations", name: "Operations Command Center", short_name: "Operations",
  discipline: "Operations", price_cents: 5000, description: "Six playbooks and more.",
  status: "available" as const, next: false, on: false };
const STATE: CentersState = {
  centers: [ops, { ...ops, code: "people", name: "People Command Center", short_name: "People",
    status: "coming", next: true }],
  cap_cents: 15000, owners_practice: false, can_switch: true, why_not: "", library_count: 3,
  price_line: "$50 a month is added to your subscription from December 1.",
};

describe("Settings → Command Centers (P8)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks before turning one on, saying what is added", async () => {
    const fetchMock = mockApi({
      "GET /api/command-centers/": STATE,
      "POST /api/command-centers/operations/": { ...STATE, centers: [{ ...ops, on: true }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<CommandCentersSettings me={aMe({ role: "FF" })} />);
    expect(await screen.findByText("Next")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button",
      { name: "Turn on the Operations Command Center" }));
    expect(screen.getByText(/\$50 a month is added/)).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ on: true }));
  });

  it("shows the switch refusing in the demo", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/command-centers/": { ...STATE, can_switch: false,
      why_not: "Command Centers are switched by Execs NOW HQ in the demo." } }));
    renderRoute(<CommandCentersSettings me={aMe({ role: "FF" })} />);
    expect(await screen.findByText(/switched by Execs NOW HQ in the demo/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on the Operations Command Center" }))
      .toBeDisabled();
  });
});

describe("From the library (P8)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("fills the KPI form from an entry, making nothing", async () => {
    const library: LibraryState = { can_edit: true,
      pages: [{ code: "customers", label: "Customers" }, { code: "operations", label: "Operations" }],
      entries: [{ id: null, key: "days_to_close_wo", page: "operations", source: "base",
        center: "", center_name: "", name: "Days to close a work order", kind: "duration",
        direction: "lower", cadence: "weekly", rollup: "average", duration_unit: "days",
        rating_scale: null, behind_band_pct: 25, guidance: "On track at 3 days or fewer.",
        feeds: ["track"], target_value: null, range_low: null, range_high: null }] };
    const fetchMock = mockApi({ "GET /api/scorecard/library/": library });
    vi.stubGlobal("fetch", fetchMock);
    const picked = vi.fn();
    renderRoute(<KpiLibraryPicker onPick={picked} onClose={() => {}} />);
    await userEvent.click(await screen.findByRole("tab", { name: "Operations" }));
    await userEvent.click(screen.getByRole("button", { name: "Use Days to close a work order" }));
    expect(picked).toHaveBeenCalledWith(expect.objectContaining({
      name: "Days to close a work order", kind: "duration", duration_unit: "days",
      direction: "lower", behind_band_pct: 25, note: "On track at 3 days or fewer." }));
    expect(fetchMock.calls.every((c) => c.method === "GET")).toBe(true);
  });
});
