/** Owner agreements, the staff side: the status line per owner, the
 *  permissions screen, and countersigning that says whose signature it is. */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../lib/api";
import type { AgreementDetail as Detail, CompanyPage } from "../lib/agreements";
import { mockApi, renderRoute } from "../test/render";
import { NAV } from "../App";
import { AgreementDetail } from "./AgreementDetail";
import { AgreementNew, AgreementsScreen } from "./Agreements";
import { AgreementSettings } from "./AgreementSettings";
import { PeoplePermissions } from "./PeoplePermissions";

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
      cancelled: false, manager_percent: "30", signed_name: "Alex Sample",
      turn: "Waiting for SkyRun's signature" }], ...over };
}

afterEach(() => vi.unstubAllGlobals());
let DETAIL: Detail;

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
    const page = { company: { id: CO, name: "Mountain Stays" },
      columns: { agreements: true, signed_pdfs: true, intake: true },
      rows: [{ user_id: "u1", name: "Sandra Roe", role: "Client team member",
               practice_owner: false, agreements: false, signed_pdfs: false, intake: false }] };
    const api = mockApi({
      [`/api/agreements/companies/${CO}/access`]: (body: unknown) => ({ body: body
        ? { ...page, rows: (body as { rows: unknown[] }).rows } : page }),
    });
    vi.stubGlobal("fetch", api);
    renderRoute(<PeoplePermissions me={ME} />, { path: "/p/:companyId", route: `/p/${CO}` });
    fireEvent.click(await screen.findByLabelText("Sandra Roe: Owner agreements"));
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
      signer_block: "Michael LeClerc, President", may_download_text: false,
      countersign_words: "I am applying SkyRun Park City's signature, the one Dana Fictional "
        + "adopted for the block that reads “Michael LeClerc, President”, to this agreement, "
        + "under the authorization Dana Fictional recorded on November 23, 2026.",
      authority: { id: "a1", principal: "Michael LeClerc", recorded_by: "Dana Fictional",
                   recorded_at: "", method: "typed", recorded_on: "November 23, 2026",
                   people: [], typed: "Michael LeClerc", wording: "" },
      owner_signature: { name: "Alex Sample", at: "2026-11-24T16:20:00Z", ip: "203.0.113.9",
                         method: "typed" },
      manager_signature: null, agreement_date: null, has_owner_pdf: true,
      has_final_pdf: false, contract: { contract_id: 1, name: "Standard 30", flag: "" },
      intake: null, events: [], emails: [], sender: "testing", blocks: [],
      owners: [{ position: 1, name: "Alex Sample", title: "", email: "a@x.co",
                 signed_at: "2026-11-24T16:20:00Z", turn: false }],
      co_owners: [], shared_email: false, turn_position: null, words_problem: "",
      may_cancel: true, may_restart: false, cancel_reason: "", started_from: null,
      successor: null,
      owner_signatures: [{ position: 1, name: "Alex Sample", at: "2026-11-24T16:20:00Z",
                           ip: "203.0.113.9" }],
    } as unknown as Detail;
    DETAIL = detail;
    const api = mockApi({ [`POST /api/agreements/${ID}/countersign`]: { ...detail,
      may_countersign: false }, [`/api/agreements/${ID}`]: detail });
    vi.stubGlobal("fetch", api);
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    const button = await screen.findByRole("button", { name: "Apply SkyRun's signature" });
    expect(screen.getAllByText(/The owner changed the address/)[0]).toBeInTheDocument();
    // The words are the server's: they name the account that recorded it.
    expect(screen.getByText(/under the authorization Dana Fictional recorded on November 23/))
      .toBeInTheDocument();
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I agree"));
    fireEvent.click(button);
    await waitFor(() => expect(api.calls.find((c) => c.url.endsWith("/countersign"))?.body)
      .toEqual({ agreed: true }));
  });
});

describe("the test sender's warnings (owner, 2026-11-24)", () => {
  const WARN = /owners? would see Executives Now/;

  it("shows on Settings", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`/api/agreements/companies/${CO}/authority`]: { people: [], authority: null },
      [`/api/agreements/companies/${CO}`]: company({ may_edit_access: true }),
    }));
    renderRoute(<AgreementSettings me={ME} />, { path: "/s/:companyId", route: `/s/${CO}` });
    expect((await screen.findAllByText(WARN)).length).toBeGreaterThan(0);
  });

  it("shows on New owner", async () => {
    vi.stubGlobal("fetch", mockApi({ [`/api/agreements/companies/${CO}`]: company({
      defaults: { owner_percent: "70", manager_percent: "30", additional_items: "",
                  fees: { winter: { threshold: "0", fee: "0" }, summer: { threshold: "0",
                          fee: "0" }, fall: { threshold: "0", fee: "0" } },
                  property_address: {} } }) }));
    renderRoute(<AgreementNew me={ME} />, { route: `/?company=${CO}` });
    expect(await screen.findByText(/Owner email is on ENHQ's own sender \(testing\): the owner would see Executives Now/))
      .toBeInTheDocument();
  });

  it("shows on the Send card of an unsigned agreement", async () => {
    vi.stubGlobal("fetch", mockApi({ [`/api/agreements/${ID}`]: {
      ...DETAIL, editable: true, may_countersign: false, owner_signature: null,
      address_changed: false, status: STATUS.map((x) => ({ ...x, at: null })),
      turn_position: 1, owner_signatures: [],
      owners: [{ ...DETAIL.owners[0], signed_at: null, turn: true }] } }));
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    expect(await screen.findByRole("button", { name: "Send by email" })).toBeInTheDocument();
    expect(screen.getByText(/Owner email is on ENHQ's own sender \(testing\): the owner would see Executives Now/))
      .toBeInTheDocument();
  });
});

describe("no trace when owner agreements are off", () => {
  it("has no menu item without has_agreements, and one with it", () => {
    const items = NAV.filter((n) => n.to === "/agreements");
    expect(items.length).toBeGreaterThan(0);
    for (const role of ["FF", "FCC", "ECC"] as const) {
      const me = { role, has_agreements: false } as Me;
      expect(items.filter((n) => (!n.roles || n.roles.includes(role))
        && (!n.when || n.when(me)))).toHaveLength(0);
      const on = { role, has_agreements: true } as Me;
      expect(items.filter((n) => (!n.roles || n.roles.includes(role))
        && (!n.when || n.when(on)))).toHaveLength(1);
    }
  });
});

describe("People and permissions (owner, 2026-11-24)", () => {
  it("shows only the columns for what is on", async () => {
    vi.stubGlobal("fetch", mockApi({ [`/api/agreements/companies/${CO}/access`]: {
      company: { id: CO, name: "Mountain Stays" },
      columns: { agreements: false, signed_pdfs: false, intake: true },
      rows: [{ user_id: "u1", name: "Jackie Doe", role: "Client team member",
               practice_owner: false, intake: true }] } }));
    renderRoute(<PeoplePermissions me={ME} />, { path: "/p/:companyId", route: `/p/${CO}` });
    expect(await screen.findByLabelText("Jackie Doe: Owner intake")).toBeChecked();
    expect(screen.queryByText("Owner agreements")).not.toBeInTheDocument();
    expect(screen.queryByText("Receives signed PDFs")).not.toBeInTheDocument();
  });
});

describe("more than one owner (owner, 2026-11-24)", () => {
  it("adds up to three more owners on New owner, and warns when they share an email",
    async () => {
      const api = mockApi({
        [`POST /api/agreements/companies/${CO}/agreements`]: { ...DETAIL, id: ID },
        [`POST /api/agreements/${ID}/send`]: DETAIL,
        [`/api/agreements/companies/${CO}`]: company({
          defaults: { owner_percent: "70", manager_percent: "30", additional_items: "",
                      fees: { winter: { threshold: "0", fee: "0" }, summer: { threshold: "0",
                              fee: "0" }, fall: { threshold: "0", fee: "0" } },
                      property_address: {} } }),
      });
      vi.stubGlobal("fetch", api);
      renderRoute(<AgreementNew me={ME} />, { route: `/?company=${CO}` });
      fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Alex Sample" } });
      fireEvent.change(screen.getByLabelText("Email"), { target: { value: "us@x.co" } });
      for (let i = 0; i < 3; i++) {
        fireEvent.click(screen.getByRole("button", { name: "+ Add another owner" }));
      }
      expect(screen.queryByRole("button", { name: "+ Add another owner" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Remove owner 4" }));
      fireEvent.click(screen.getByRole("button", { name: "Remove owner 3" }));
      fireEvent.change(screen.getByLabelText("Owner 2: name"), { target: { value: "Pat Sample" } });
      expect(screen.getByRole("button", { name: "Send by email" })).toBeDisabled();
      fireEvent.change(screen.getByLabelText("Owner 2: email"), { target: { value: "US@x.co" } });
      expect(screen.getByText("These owners share an email address. Each gets their own link."))
        .toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Send by email" }));
      await waitFor(() => {
        const made = api.calls.find((c) => c.url.endsWith("/agreements") && c.method === "POST");
        expect((made?.body as { co_owners: unknown }).co_owners).toEqual([
          { name: "Pat Sample", email: "US@x.co", title: "" }]);
      });
    });

  it("lists the owners in order, whose turn it is, and sends to them", async () => {
    const api = mockApi({
      [`POST /api/agreements/${ID}/send`]: DETAIL,
      [`/api/agreements/${ID}`]: { ...DETAIL, may_countersign: false, turn_position: 2,
        owners: [DETAIL.owners[0], { position: 2, name: "Pat Sample", title: "Trustee",
                 email: "pat@x.co", signed_at: null, turn: true }] },
    });
    vi.stubGlobal("fetch", api);
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    expect(await screen.findByText("Their turn")).toBeInTheDocument();
    expect(screen.getByText(/The owners are fixed once the first owner has signed/))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Email Pat Sample again" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.endsWith("/send"))).toBe(true));
  });

  it("cancels only with a reason, and says who is told", async () => {
    const api = mockApi({
      [`POST /api/agreements/${ID}/cancel`]: { ...DETAIL, cancelled: true, may_cancel: false,
        cancel_reason: "Wrong split", may_restart: true },
      [`/api/agreements/${ID}`]: { ...DETAIL, may_countersign: false },
    });
    vi.stubGlobal("fetch", api);
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel this agreement" }));
    expect(screen.getByText(/emailed that the agreement was withdrawn/)).toBeInTheDocument();
    const go = screen.getByRole("button", { name: "Cancel the agreement" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Why is it being cancelled/),
                     { target: { value: "Wrong split" } });
    fireEvent.click(go);
    await waitFor(() => expect(api.calls.find((c) => c.url.endsWith("/cancel"))?.body)
      .toEqual({ reason: "Wrong split" }));
    expect(await screen.findByText(/Cancelled: Wrong split/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start a new agreement from this one" }))
      .toBeInTheDocument();
  });

  it("names an Exhibit A change that blocks countersigning, with what to do", async () => {
    vi.stubGlobal("fetch", mockApi({ [`/api/agreements/${ID}`]: { ...DETAIL,
      may_countersign: false, words_problem: "SkyRun can't sign this agreement: Exhibit A's "
        + "quantities were changed after the owner signed. To put it right, cancel this "
        + "agreement, then press \"Start a new agreement from this one\" and send it." } }));
    renderRoute(<AgreementDetail me={ME} />, { path: "/a/:id", route: `/a/${ID}` });
    expect(await screen.findByText(/Exhibit A's quantities were changed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply SkyRun's signature" })).toBeNull();
  });
});
