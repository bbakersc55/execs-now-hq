import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmailTemplate, PortalInvoice } from "../lib/api";
import { aContact, aMe, CONTACT_TYPES, PIPELINES } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ClientInvoices } from "./ClientInvoices";
import { Contacts } from "./Contacts";
import { EmailTemplates, MergeFieldBar } from "./EmailTemplates";
import { billingLine, PracticeRow, Practices } from "./Practices";

vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: {
    onPay: (e: { token: string }) => Promise<true | string> }) => {
    const button = document.createElement("button");
    button.textContent = "NMI pay";
    button.onclick = () => { void options.onPay({ token: "tok-from-nmi" }); };
    box.appendChild(button);
    return { destroy: () => button.remove() };
  },
}));

/** Five findings from the demo on 3021a05 (Bryan, 2026-10-22). */
describe("demo findings, 2026-10-22", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("T2: New template sends a subject, so it is made rather than refused", async () => {
    const user = userEvent.setup();
    const made: EmailTemplate = {
      id: "t9", name: "New template", kind: "general", subject: "A note from {PracticeName}",
      body: "Hi {FirstName},", first_name_fallback: "there", original: "", is_original: false,
      changed: false, used_for: [], updated_at: "2026-10-22T12:00:00Z" };
    const fetchMock = mockApi({
      "POST /api/email-templates/": () => ({ status: 201, body: made }),
      "GET /api/email-templates/": [made],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<EmailTemplates />);
    await user.click(await screen.findByRole("button", { name: /New template/ }));
    expect(await screen.findByText("Template added.")).toBeInTheDocument();
    const sent = fetchMock.calls.find((c) => c.method === "POST")?.body as { subject: string };
    expect(sent.subject.trim()).not.toBe("");
  });

  it("T5: one email's composer greys the fields that only work elsewhere", () => {
    render(<MergeFieldBar oneEmail />);
    expect(screen.getByRole("button", { name: "{FirstName}" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "{ProspectName}" })).toBeNull();
    expect(screen.getByLabelText("{ProspectName}, only in referral thank-yous"))
      .toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("(only in referral thank-yous)")).toBeInTheDocument();
    expect(screen.getByLabelText("{PayLink}, only in invoice emails")).toBeInTheDocument();
  });

  it("T5: the template editor still offers every field", () => {
    render(<MergeFieldBar />);
    expect(screen.getByRole("button", { name: "{ProspectName}" })).toBeInTheDocument();
  });

  it("T5: Email these contacts previews the email and names a field with nothing", async () => {
    const user = userEvent.setup();
    const thanks: EmailTemplate = {
      id: "t1", name: "Referral thank-you: won", kind: "general",
      subject: "Good news, and thank you",
      body: "Good news: {ProspectName} has decided to work with us.",
      first_name_fallback: "there", original: "thanks_won", is_original: true,
      changed: false, used_for: [], updated_at: "2026-10-20T12:00:00Z" };
    const dana = aContact({ id: "c1", first_name: "Dana", last_name: "Reyes" });
    const fetchMock = mockApi({
      "POST /api/contacts/draft-emails/preview/": () => ({ status: 200, body: {
        to: "Dana Reyes", subject: "Good news, and thank you",
        body: "Good news:  has decided to work with us.",
        empty: [{ field: "ProspectName", label: "Who they referred (thank-yous)",
                  why: "only in referral thank-yous", people: 1, of: 1 }] } }),
      "GET /api/email-templates/": [thanks],
      "GET /api/contacts/": [dana],
      "GET /api/contact-types/": CONTACT_TYPES,
      "GET /api/pipelines/": PIPELINES,
      "GET /api/notes/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Contacts me={aMe()} />);
    await user.click(await screen.findByRole("checkbox", { name: "Select Dana Reyes" }));
    await user.click(screen.getByRole("button", { name: "Draft email" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Start from a template" }), "t1");
    const preview = await screen.findByRole("note", {}, { timeout: 3000 });
    expect(preview).toHaveTextContent(
      "{ProspectName} has nothing (only in referral thank-yous), so it reads as blank.");
    expect(screen.getByLabelText("Preview")).toHaveTextContent("has decided to work with us.");
    const asked = fetchMock.calls.find((c) => c.url.includes("preview"))?.body as {
      ids: string[]; body_text: string };
    expect(asked.ids).toEqual(["c1"]);
  });

  it("B2: every practice row shows its amount, card and pricing program at a glance", () => {
    const base = {
      id: "p", display_name: "Blue Sky", legal_name: "", domain: "", status: "invited",
      created_at: "2026-10-22T12:00:00Z", archived_at: null, oauth_client: "internal",
      pricing_program: "interchange_plus", staff_count: 1, client_count: 0,
      ai_spend_this_month_usd: "0.00", last_activity_at: null } as PracticeRow;
    const sub = { status: "needs_card", not_billed: false, amount_cents: 2000,
      plan_cents: 2000, overridden: false, card_on_file: false, open_cents: 0,
      oldest_open_days: null, eligible_for_suspension: false, suspended_at: null };
    expect(billingLine({ ...base, subscription: sub }))
      .toBe("$20.00 a month · No card yet · Interchange-plus");
    expect(billingLine({ ...base, subscription: { ...sub, status: "active", card_on_file: true },
                         pricing_program: "" }))
      .toBe("$20.00 a month · Card on file · no pricing program yet");
    expect(billingLine({ ...base, subscription: { ...sub, status: "not_billed",
                                                  not_billed: true } }))
      .toBe("Not billed, your own practice · Interchange-plus");
  });

  it("B2: the line is on the row without opening anything", async () => {
    const row = {
      id: "11111111-1111-4111-8111-111111111111", display_name: "Blue Sky",
      legal_name: "", domain: "", status: "invited", created_at: "2026-10-22T12:00:00Z",
      archived_at: null, oauth_client: "internal", pricing_program: "dual_pricing",
      staff_count: 1, client_count: 0, ai_spend_this_month_usd: "0.00",
      last_activity_at: null, subscription: { status: "needs_card", not_billed: false,
        amount_cents: 2000, plan_cents: 2000, overridden: false, card_on_file: false,
        open_cents: 0, oldest_open_days: null, eligible_for_suspension: false,
        suspended_at: null } } as PracticeRow;
    vi.stubGlobal("fetch", mockApi({ "GET /api/platform/practices": [row] }));
    renderRoute(<Practices />);
    expect(await screen.findByLabelText("Billing of Blue Sky"))
      .toHaveTextContent("$20.00 a month · No card yet · Dual pricing");
  });

  it("B3 and B5: Pay opens over the page with the amount and Test mode in its header, "
    + "and the list is asked again once paid", async () => {
    const user = userEvent.setup();
    const open: PortalInvoice = {
      id: "a", number: "INV-0007", issue_date: "2026-10-01", due_date: "2026-10-16",
      total_cents: 580000, balance_cents: 580000, status: "sent", status_label: "Sent",
      overdue: false, pay_url: "", can_pay: true, payment_in_progress: false,
      test_mode: true };
    let paid = false;
    const fetchMock = mockApi({
      "GET /api/portal-invoices/a/pay/": { public_key: "pub", test_mode: true,
                                           amount_cents: 580000, number: "INV-0007" },
      "POST /api/portal-invoices/a/pay/": () => { paid = true; return { status: 200, body: {
        status: "approved", message: "Thank you. $5,800.00 was paid on invoice INV-0007.",
        balance_cents: 0, invoice_status: "paid" } }; },
      "GET /api/portal-invoices/": () => ({ status: 200, body: [paid
        ? { ...open, status: "paid", status_label: "Paid", balance_cents: 0, can_pay: false }
        : open] }),
      "GET /api/portal-autopay/": { ready: false, test_mode: true, public_key: "", card: null,
                                    autopay: null, wording: "", wording_version: "" },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientInvoices />);
    await user.click(await screen.findByRole("button", { name: "Pay invoice INV-0007" }));
    const dialog = await screen.findByRole("dialog", { name: "Pay invoice INV-0007" });
    const head = within(dialog).getByRole("heading");
    expect(head).toHaveTextContent("Pay invoice INV-0007: $5,800.00");
    await waitFor(() => expect(within(head).getByText("Test mode")).toBeInTheDocument());
    expect(document.querySelector(".sheet-backdrop")).not.toBeNull();
    await user.click(await within(dialog).findByRole("button", { name: "NMI pay" }));
    expect(await screen.findByRole("status")).toHaveTextContent("was paid on invoice INV-0007");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Paid")).toBeInTheDocument();
    expect(screen.queryByText(/Loading/)).toBeNull();
  });
});
