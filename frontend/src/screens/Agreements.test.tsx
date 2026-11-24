/** Owner agreements, the staff side: the status line per owner, the
 *  permissions screen, and countersigning that says whose signature it is. */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../lib/api";
import type { AgreementDetail as Detail, CompanyPage } from "../lib/agreements";
import { mockApi, renderRoute } from "../test/render";
import { AgreementDetail } from "./AgreementDetail";
import { AgreementsScreen } from "./Agreements";
import { AgreementSettings } from "./AgreementSettings";

const ME = { role: "ECC", full_name: "Jackie Doe" } as unknown as Me;
const CO = "11111111-1111-1111-1111-111111111111";
const ID = "22222222-2222-2222-2222-222222222222";
const STATUS = [["sent", "Sent", "2026-11-24T16:00:00Z"], ["opened", "Opened",
  "2026-11-24T16:05:00Z"], ["owner_signed", "Signed by owner", "2026-11-24T16:20:00Z"],
  ["countersigned", "Countersigned", null], ["form_started", "Form started", null],
  ["form_submitted", "Form submitted", null], ["sent_to_track", "Sent to Track", null]]
  .map(([key, label, at]) => ({ key: key!, label: label!, at }));

const PROGRAM = { sender: "testing", sender_label: "ENHQ's own sender (testing)",
  sender_domain: "", from_address: "", from_name: "Mountain Stays", reply_to: "",
  tested_at: null, domain_ready: false, paused_at: null, pause_reason: "", held: 0,
  warning: "Testing: owners would see Executives Now as the sender.", signer_id: "m1",
  signer_name: "Michael LeClerc", may_edit: true, may_set_signer: false };

function company(over: Partial<CompanyPage> = {}): CompanyPage {
  return {
    company: { id: CO, name: "Mountain Stays" }, may_work: true, may_edit_access: false,
    is_signer: false, may_countersign: true, program: PROGRAM as CompanyPage["program"],
    defaults: {} as CompanyPage["defaults"],
    agreements: [{ id: ID, number: 4, owner_name: "Alex Sample", owner_email: "a@x.co",
      owner_phone: "", property: "400 Lift Road, Park City, UT 84060", status: STATUS,
      cancelled: false, manager_percent: "30", signed_name: "Alex Sample" }], ...over };
}

afterEach(() => vi.unstubAllGlobals());

describe("owner agreements, staff side", () => {
  it("shows one status line per owner", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/agreements/companies/": company(),
      "/api/agreements/companies": { companies: [{ id: CO, name: "Mountain Stays" }] },
    }));
    renderRoute(<AgreementsScreen me={ME} />);
    expect(await screen.findByText("#4 Alex Sample")).toBeInTheDocument();
    const line = screen.getByRole("list", { name: "Status: Signed by owner" });
    expect(line.querySelectorAll("li.done")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "New owner" })).toBeInTheDocument();
    expect(screen.getByText(/owners would see Executives Now/)).toBeInTheDocument();
  });

  it("saves the permission ticks for everyone listed", async () => {
    const api = mockApi({
      [`/api/agreements/companies/${CO}/access`]: (body: unknown) => ({ body: body ?? {
        rows: [{ user_id: "u1", name: "Sandra Roe", role: "Client team member",
                 practice_owner: false, agreements: false, signed_pdfs: false,
                 intake: false }] } }),
      [`/api/agreements/companies/${CO}/authority`]: { people: [], authority: null },
      [`/api/agreements/companies/${CO}`]: company({ may_edit_access: true }),
    });
    vi.stubGlobal("fetch", api);
    renderRoute(<AgreementSettings me={ME} />, { path: "/s/:companyId", route: `/s/${CO}` });
    fireEvent.click(await screen.findByLabelText("Sandra Roe: owner agreements"));
    fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
    await waitFor(() => {
      const put = api.calls.find((c) => c.method === "PUT");
      expect(put?.body).toEqual({ rows: [expect.objectContaining({ user_id: "u1",
        agreements: true, signed_pdfs: false, intake: false })] });
    });
  });

  it("countersigning under the authorization says whose signature is applied", async () => {
    const detail = {
      ...company().agreements[0], company_id: CO, company_name: "Mountain Stays",
      template: "Rental Management Agreement", version: 1,
      terms: { owner_percent: "70", manager_percent: "30", fees: {}, additional_items: "",
               property_address: {} },
      terms_shown: { owner_percent: "70", manager_percent: "30", fees: {},
                     additional_items: "", property_address: {} },
      details: {}, address_changed: true, staff_address: "400 Lift Road",
      owner_address: "402 Lift Road", editable: false, may_work: true, may_countersign: true,
      countersign_as: "authorized", signer_name: "Michael LeClerc",
      authority: { id: "a1", principal: "Michael LeClerc", recorded_at: "", method: "typed",
                   recorded_on: "November 23, 2026", people: [], typed: "Michael LeClerc",
                   wording: "" },
      owner_signature: { name: "Alex Sample", at: "2026-11-24T16:20:00Z", ip: "203.0.113.9",
                         method: "typed" },
      manager_signature: null, agreement_date: null, has_owner_pdf: true,
      has_final_pdf: false, contract: { contract_id: 1, name: "Standard 30", flag: "" },
      intake: null, events: [], emails: [], sender: "testing", blocks: [],
    } as unknown as Detail;
    const api = mockApi({ [`POST /api/agreements/${ID}/countersign`]: { ...detail,
      may_countersign: false }, [`/api/agreements/${ID}`]: detail });
    vi.stubGlobal("fetch", api);
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    const button = await screen.findByRole("button",
                                           { name: "Apply Michael LeClerc's signature" });
    expect(screen.getAllByText(/The owner changed the address/)[0]).toBeInTheDocument();
    expect(screen.getByText(/under Michael LeClerc's authorization of November 23, 2026/))
      .toBeInTheDocument();
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I agree"));
    fireEvent.click(button);
    await waitFor(() => expect(api.calls.find((c) => c.url.endsWith("/countersign"))?.body)
      .toEqual({ agreed: true }));
  });
});
