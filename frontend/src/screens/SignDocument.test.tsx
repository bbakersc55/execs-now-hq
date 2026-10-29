import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsCard } from "../components/Documents";
import { SignDocument as SignDocumentRow, SigningPage } from "../lib/api";
import { aContact, aMe, COMPANY_ID } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PortalDocuments } from "./PortalDocuments";
import { SignDocument } from "./SignDocument";

/** E-signature (2026-10-29): the public signing page, the company card, and
 *  the portal's list. */

const PAGE: SigningPage = {
  practice: "Summit Operations Partners", title: "Proposal", signer_name: "Dana Whitfield",
  signer_email: "dana@hooli.invalid", state: "sent", expires_at: "2026-11-28T14:00:00Z",
  sha256: "ab".repeat(32), consent_version: "2026-10-29",
  consent_text: "By signing electronically, I agree … under the U.S. ESIGN Act and UETA.",
};

function doc(over: Partial<SignDocumentRow> = {}): SignDocumentRow {
  return {
    id: "d1", title: "Proposal", state: "signed", state_label: "Signed",
    signer: { id: "c1", name: "Dana Whitfield", email: "dana@hooli.invalid" },
    sent_at: "2026-10-25T14:00:00Z", viewed_at: "2026-10-26T08:00:00Z",
    signed_at: "2026-10-27T09:00:00Z", declined_at: null, countersigned_at: null,
    completed_at: null, voided_at: null, expires_at: "2026-11-24T14:00:00Z",
    created_at: "2026-10-25T13:00:00Z", source: "template", template: "t1",
    template_name: "Proposal", fields: { Fee: "$6,000 a month" }, fields_used: ["Fee"],
    decline_reason: "", void_reason: "", countersigned_by: "", request: null,
    pdf_sha256: "ab".repeat(32), final_sha256: "", has_signed_pdf: true, has_final_pdf: false,
    from_rule: false, can: { send: false, refill: false, countersign: true, void: true },
    ...over,
  };
}

beforeEach(() => { vi.unstubAllGlobals(); });

describe("the signing page", () => {
  it("signs only once the consent line is ticked, and sends what was typed", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", mockApi({
      "POST /api/sign/tok": (body: unknown) => {
        sent.push(body);
        return { body: { state: "signed", detail: "Signed. Summit will countersign it." } };
      },
      "GET /api/sign/tok": PAGE,
    }));
    renderRoute(<SignDocument />, { path: "/sign/:token", route: "/sign/tok" });
    expect(await screen.findByRole("heading", { name: "Proposal" })).toBeInTheDocument();
    expect(screen.getByTitle("Proposal")).toHaveAttribute("src", "/api/sign/tok/pdf");
    expect(screen.getByText(/ESIGN Act/)).toBeInTheDocument();
    const sign = screen.getByRole("button", { name: "Sign" });
    expect(sign).toBeDisabled();
    expect(screen.getByLabelText("Type your signature")).toHaveValue("Dana Whitfield");
    await user.click(screen.getByLabelText("I agree to sign electronically"));
    expect(sign).toBeEnabled();
    await user.click(sign);
    expect(await screen.findByText(/Summit will countersign it/)).toBeInTheDocument();
    expect(sent).toEqual([{ agreed: true, method: "typed", typed: "Dana Whitfield", drawn: "" }]);
  });

  it("declines only with a reason", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", mockApi({
      "POST /api/sign/tok/decline": (body: unknown) => {
        sent.push(body);
        return { body: { state: "declined", detail: "Declined. Summit has been told why." } };
      },
      "GET /api/sign/tok": PAGE,
    }));
    renderRoute(<SignDocument />, { path: "/sign/:token", route: "/sign/tok" });
    await user.click(await screen.findByRole("button", { name: "Decline" }));
    const go = screen.getByRole("button", { name: "Decline to sign" });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText("Why you are declining"), "Over budget");
    await user.click(go);
    expect(await screen.findByText(/has been told why/)).toBeInTheDocument();
    expect(sent).toEqual([{ reason: "Over budget" }]);
  });

  it("says plainly when the link is spent", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/sign/old": () => ({ status: 404, body: {
        detail: "This signing link is not valid any more." } }),
    }));
    renderRoute(<SignDocument />, { path: "/sign/:token", route: "/sign/old" });
    expect(await screen.findByText("This signing link is not valid any more.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign" })).not.toBeInTheDocument();
  });
});

describe("the company's Documents card", () => {
  const people = [aContact({ id: "c1", first_name: "Dana", last_name: "Whitfield",
    company: COMPANY_ID, emails: [{ id: "e1", address: "dana@hooli.invalid", is_primary: true }] })];

  it("lets the practice owner countersign with the consent ticked", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", mockApi({
      [`GET /api/documents/?company=${COMPANY_ID}`]: [doc()],
      "POST /api/documents/d1/countersign/": (body: unknown) => {
        sent.push(body);
        return { body: doc({ state: "complete", state_label: "Complete" }) };
      },
      "GET /api/mailboxes/": { mailboxes: [], default: null, is_local_build: true },
    }));
    renderRoute(<DocumentsCard me={aMe({ role: "FF", full_name: "Bryan Baker" })}
      companyId={COMPANY_ID} people={people} />);
    expect(await screen.findByText("Needs your countersignature.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Countersign" }));
    const go = screen.getAllByRole("button", { name: "Countersign" }).at(-1)!;
    expect(go).toBeDisabled();
    await user.click(screen.getByLabelText("I agree to sign electronically"));
    await user.click(go);
    await waitFor(() => expect(sent).toEqual([
      { agreed: true, method: "typed", typed: "Bryan Baker", drawn: "" }]));
  });

  it("shows an assistant the state and nothing to act on", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`GET /api/documents/?company=${COMPANY_ID}`]: [{
        id: "d1", title: "Proposal", state: "viewed", state_label: "Viewed",
        signer: { id: "c1", name: "Dana Whitfield", email: "dana@hooli.invalid" },
        sent_at: "2026-10-25T14:00:00Z", viewed_at: "2026-10-26T08:00:00Z", signed_at: null,
        declined_at: null, countersigned_at: null, completed_at: null, voided_at: null,
        expires_at: "2026-11-24T14:00:00Z", created_at: "2026-10-25T13:00:00Z" }],
    }));
    renderRoute(<DocumentsCard me={aMe({ role: "VA" })} companyId={COMPANY_ID} people={people} />);
    expect(await screen.findByText("Viewed")).toBeInTheDocument();
    for (const name of ["New document", "PDF", "Void", "Countersign", "Send for signature"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("link", { name: "PDF" })).not.toBeInTheDocument();
  });

  it("previews a template's document and puts its email in the Outbox", async () => {
    const user = userEvent.setup();
    const calls: { url: string; body: unknown }[] = [];
    const created = doc({ id: "d2", state: "draft", state_label: "Draft",
      can: { send: true, refill: true, countersign: false, void: true } });
    const fetchMock = mockApi({
      [`GET /api/documents/?company=${COMPANY_ID}`]: [],
      "GET /api/document-templates/": [{ id: "t1", name: "Proposal", title: "Proposal",
        body: "{Fee}", original: "proposal", is_original: true, changed: false, used_for: [],
        fields_used: ["Fee"], updated_at: "" }],
      "GET /api/mailboxes/": { mailboxes: [], default: null, is_local_build: true },
      "POST /api/documents/d2/send/": (body: unknown) => {
        calls.push({ url: "send", body }); return { body: created };
      },
      "POST /api/documents/": (body: unknown) => {
        calls.push({ url: "create", body }); return { status: 201, body: created };
      },
    });
    const preview = vi.fn(async () => ({ ok: true, status: 200,
      blob: async () => new Blob(["%PDF"], { type: "application/pdf" }) } as Response));
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).startsWith("/api/documents/preview/") ? preview() : fetchMock(input, init));
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:preview",
                                              revokeObjectURL: () => undefined }));
    renderRoute(<DocumentsCard me={aMe({ role: "FF" })} companyId={COMPANY_ID} people={people} />);
    await user.click(await screen.findByRole("button", { name: /New document/ }));
    await user.type(await screen.findByLabelText("Fee"), "$6,000 a month");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByTitle("Preview")).toHaveAttribute("src", "blob:preview");
    await user.click(screen.getByRole("button", { name: "Send for approval" }));
    expect(await screen.findByText(/is in the Outbox, waiting for approval/)).toBeInTheDocument();
    expect(calls).toEqual([
      { url: "create", body: { company: COMPANY_ID, signer: "c1", template: "t1",
                               fields: { Fee: "$6,000 a month" } } },
      { url: "send", body: { mailbox: null } },
    ]);
  });
});

describe("the portal's Documents", () => {
  it("lists their company's documents with the signed copy", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/portal-documents/": [{ ...doc({ state: "complete", state_label: "Complete",
        completed_at: "2026-10-28T10:00:00Z" }), has_pdf: true }],
    }));
    renderRoute(<PortalDocuments />);
    expect(await screen.findByText("Complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Signed copy" }))
      .toHaveAttribute("href", "/api/portal-documents/d1/pdf/");
  });
});
