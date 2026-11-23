import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Review } from "../lib/intake";
import { mockApi } from "../test/render";
import { LockedBanner, StaffCard } from "./IntakeReview";

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
