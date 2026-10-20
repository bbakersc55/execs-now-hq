import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aContact } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Contact, Referral } from "../lib/api";
import { ReferralsCard, ReferredByRow, ReferrerPicker, referrerChoices } from "./Referrals";

const mark = aContact({ id: "mark", first_name: "Mark", last_name: "Ellis",
  type_codes: ["prospect"], emails: [{ id: "e2", address: "mark@x.invalid", is_primary: true }] });
const marta = aContact({ id: "marta", first_name: "Marta", last_name: "Diaz",
  type_codes: ["referral_partner"], emails: [] });
const dana = aContact({ id: "dana", first_name: "Dana", last_name: "Cole", referred_by: null });

function referral(overrides: Partial<Referral> = {}): Referral {
  return {
    id: "r1", direction: "inbound", referrer: { id: "marta", name: "Marta Diaz" },
    prospect: { id: "dana", name: "Dana Cole", company: "Acme" }, pipeline: "p",
    stage: { label: "Initial Contact Made", semantic: "entry" }, outcome: "",
    outcome_at: null, referred_on: "2026-10-20", note: "", fee_terms: "",
    ...overrides,
  };
}

describe("Referrals", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists referral partners first, and never the prospect themselves", () => {
    const picks = referrerChoices([mark, marta, dana] as Contact[], "mar", "dana");
    expect(picks.map((c) => c.id)).toEqual(["marta", "mark"]);
    expect(referrerChoices([mark, dana] as Contact[], "", "dana").map((c) => c.id)).toEqual(["mark"]);
    expect(referrerChoices([mark] as Contact[], "mark@x").map((c) => c.id)).toEqual(["mark"]);
  });

  it("the picker shows matches as they type and hands back the choice", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "/api/contacts/": [mark, marta, dana] }));
    const onChange = vi.fn();
    renderRoute(<ReferrerPicker value={null} onChange={onChange} excludeId="dana" />);
    await user.type(screen.getByLabelText("Referred by"), "mar");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Marta Diazreferral partner", "Mark Ellismark@x.invalid"]);
    await user.click(options[1]);
    expect(onChange).toHaveBeenCalledWith({ id: "mark", name: "Mark Ellis" });
  });

  it("records who referred a prospect from their Details card", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/contacts/": [mark, marta, dana],
      "POST /api/referrals/": { status: 201, body: referral() },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<table><tbody><ReferredByRow contact={dana} /></tbody></table>);
    await user.click(screen.getByRole("button", { name: "Add who referred them" }));
    expect(screen.getByText(/join Sales at the first stage/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Referred by"), "marta");
    await user.click(await screen.findByRole("option", { name: /Marta Diaz/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ prospect: "dana", referrer: "marta" }));
  });

  it("names the referrer with a way to change or remove it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "DELETE /api/referrals/r1/": { status: 204, body: null } });
    vi.stubGlobal("fetch", fetchMock);
    const referred = { ...dana, referred_by: { id: "r1", referrer: "marta",
      referrer_name: "Marta Diaz", referred_on: "2026-10-20", note: "", outcome: "" as const } };
    renderRoute(<table><tbody><ReferredByRow contact={referred} /></tbody></table>);
    expect(screen.getByRole("link", { name: "Marta Diaz" })).toHaveAttribute(
      "href", "/contacts/marta");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "DELETE" && c.url.endsWith("/api/referrals/r1/"))).toBe(true));
  });

  it("the referrer's card lists each referral's stage and outcome", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/referrals/?referrer=marta": [
        referral(),
        referral({ id: "r2", prospect: { id: "eli", name: "Eli Park", company: "" },
          stage: { label: "Closed Won", semantic: "won" }, outcome: "won",
          outcome_at: "2026-10-22T15:00:00Z" }),
        referral({ id: "r3", prospect: { id: "fay", name: "Fay Lin", company: "" },
          stage: { label: "Closed Lost", semantic: "lost" }, outcome: "lost",
          outcome_at: "2026-10-23T15:00:00Z" }),
      ],
    }));
    renderRoute(<ReferralsCard contactId="marta" partner />);
    expect(await screen.findByText("3 referred · 1 won · 1 lost")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Eli Park" })).toHaveAttribute("href", "/contacts/eli");
    expect(screen.getByText("Closed Won")).toBeInTheDocument();
    expect(screen.getByText(/^Won /)).toBeInTheDocument();
    expect(screen.getByText(/^Lost /)).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("stays out of the way for someone who has referred no one and is no partner", async () => {
    const fetchMock = mockApi({ "/api/referrals/?referrer=dana": [] });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderRoute(<ReferralsCard contactId="dana" partner={false} />);
    await waitFor(() => expect(fetchMock.calls.length).toBe(1));
    expect(container.textContent).toBe("");
  });
});
