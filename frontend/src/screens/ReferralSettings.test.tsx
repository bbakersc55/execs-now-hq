import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aContact } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ReferralSettings } from "./ReferralSettings";

const partner = (id: string, first: string, enrolled: boolean) => aContact({
  id, first_name: first, last_name: "Partner", type_codes: ["referral_partner"],
  referral_enrolled: enrolled, referral_next_touch_at: "2026-10-11T00:00:00Z" });

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/referral-settings/": { referral_blurb: "", referral_blurb_updated_at: null,
      blurb_age_days: null, marketing_flyer: null, marketing_flyer_name: "",
      marketing_flyer_bytes: 0, marketing_flyer_present: null },
    "GET /api/contacts/": [partner("p1", "Ann", true), partner("p2", "Ben", false)],
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<ReferralSettings />);
  return fetchMock;
}

/** Owner, 2026-09-28 — touches only for partners someone enrolled. */
describe("the partner table: enrolment", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows who is enrolled and hides the next touch of who is not", async () => {
    show();
    expect(await screen.findByText(/1 of 2 enrolled\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Draft touch for Ben Partner" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Draft touch for Ann Partner" })).toBeEnabled();
  });

  it("enrols one partner from their row", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/contacts/enroll-selected/":
      { changed_count: 1, skipped: [] } });
    await user.click(await screen.findByRole("button", { name: "Enroll Ben Partner" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ ids: ["p2"], program: "referral_touches" }));
  });

  it("unenrols the selected partners in one go", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/contacts/enroll-selected/":
      { changed_count: 1, skipped: [] } });
    await user.click(await screen.findByLabelText("Select Ann Partner"));
    await user.click(screen.getByRole("button", { name: "Unenroll selected" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ ids: ["p1"], program: "referral_touches", unenroll: true }));
  });
});
