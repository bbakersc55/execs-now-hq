import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Review } from "../lib/intake";
import type { Me } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { LockedBanner, SendCard, StaffCard, TaxShow } from "./IntakeReview";

// The owner-to-unit link's start date, made plain (owner, 2026-11-23).
const NOTE = "Owner linked in Track. The link takes effect on December 1, 2026. Until then "
  + "some Track screens won't show the owner on the unit.";

function aReview(over: Partial<Review> = {}): Review {
  return {
    id: "sub-1", number: 1, status: "submitted", locked: false, sent_at: null,
    today: "2026-11-23", link_note: "",
    staff: {
      node_id: 24, contract_id: 1, management_agreement: "full_service",
      start_date: "2026-12-01", contract_effective_date: "2026-12-01", unit_type_id: null,
      unit_name: "Unit", short_name: "Unit", bath_types: {}, sleeps_total: null, shares: {},
      untick: [], keywords: null, custom: {}, owner_mode: "new", existing_owner_id: null,
      reuse_contacts: {}, no_value: [],
    },
    lists: { nodes: [], contracts: [], unit_types: [], lodging_types: [], code_types: [] },
    staff_fields: [],
    derived: { rooms: [], counts: {}, sleeps_worked_out: 0, sleeps_total: 0,
               derived_amenities: [], amenities: [], custom: {}, keyword_presets: [],
               codes: [], unit_type_suggested: null },
    people: [],
    tax: { kind: "ssn", label: "Social Security number or ITIN", held: true, last4: "6789",
           by_phone: false, may_show: true, ack_needed: false, removed: "" },
    plan: { mode: "new", summary: [], problems: [], warnings: [], steps: [], secrets: [] },
    run: null, may_send: true, test_mode: false, agreement: null,
    ...over,
  } as unknown as Review;
}

describe("IntakeReview: the link's start date", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says what the start date does, and Start today sets only the start date", async () => {
    const api = mockApi({ "PATCH /api/intake/submissions/sub-1/staff": aReview({
      staff: { ...aReview().staff, start_date: "2026-11-23" } }) });
    vi.stubGlobal("fetch", api);
    const saved = vi.fn();
    render(<StaffCard r={aReview()} onSaved={saved} />);

    expect(screen.getByText("Track shows the owner on the unit from this date."))
      .toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start today" }));

    await waitFor(() => expect(saved).toHaveBeenCalled());
    const patches = api.calls.filter((c) => c.method === "PATCH");
    // The practice's today, from the server; the Contract Effective Date is left alone.
    expect(patches).toEqual([{ url: "/api/intake/submissions/sub-1/staff", method: "PATCH",
                               body: { changes: { start_date: "2026-11-23" } } }]);
  });

  it("has nothing to do when the start date is already today", () => {
    render(<StaffCard r={aReview({ staff: { ...aReview().staff, start_date: "2026-11-23" } })}
      onSaved={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Start today" })).toBeDisabled();
  });

  it("tells the locked record when the link starts later, and only then", () => {
    const { rerender } = render(<LockedBanner r={aReview({ locked: true,
      sent_at: "2026-11-20T22:44:41Z", link_note: NOTE })} />);
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    expect(screen.getByText(/This is now a locked record/)).toBeInTheDocument();

    rerender(<LockedBanner r={aReview({ locked: true, sent_at: "2026-11-20T22:44:41Z" })} />);
    expect(screen.queryByText(/takes effect/)).not.toBeInTheDocument();
  });
});

describe("IntakeReview: the full tax number (owner, 2026-11-24)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks for a code by email, then shows the number for 60 seconds", async () => {
    const api = mockApi({
      "POST /api/intake/submissions/sub-1/tax-code": { sent_to: "jackie@mountainstays.net" },
      "POST /api/intake/submissions/sub-1/tax-show": { value: "123-45-6789", seconds: 60 },
    });
    vi.stubGlobal("fetch", api);
    render(<TaxShow id="sub-1" last4="6789" />);
    fireEvent.click(screen.getByRole("button", { name: "Show full number" }));
    const box = await screen.findByLabelText(/Code sent to jackie@mountainstays.net/);
    fireEvent.change(box, { target: { value: "482913" } });
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Show" }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      await vi.waitFor(() => expect(screen.getByLabelText("The full tax number"))
        .toHaveTextContent("123-45-6789"));
      expect(api.calls.find((c) => c.url.endsWith("/tax-show"))?.body)
        .toEqual({ code: "482913" });
      await act(async () => { vi.advanceTimersByTime(59_000); });
      expect(screen.getByLabelText("The full tax number")).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(2_000); });
      expect(screen.queryByText("123-45-6789")).toBeNull();
      expect(screen.getByRole("button", { name: "Show full number" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a real send while a number is held waits for the tick, and sends it", async () => {
    const api = mockApi({ "POST /api/intake/submissions/sub-1/send": { run: {
      id: "r1", state: "queued", steps: [], error: "", test: false,
      created_at: "2026-11-24T17:00:00Z", finished_at: null } } });
    vi.stubGlobal("fetch", api);
    const r = aReview({ tax: { ...aReview().tax, ack_needed: true } });
    renderRoute(<SendCard r={r} me={{} as Me} onDone={vi.fn()} />);
    const send = screen.getByRole("button", { name: "Send to Track" });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I have what I need from the full tax number/));
    expect(send).toBeEnabled();
    fireEvent.click(send);
    await waitFor(() => expect(api.calls.find((c) => c.url.endsWith("/send"))?.body)
      .toEqual({ tax_ack: true }));
  });
});
