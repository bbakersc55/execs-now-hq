import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClearTestPayments, GatewayModeBanner } from "../components/TestMode";
import { RefundForm } from "../components/CardRefunds";
import { Invoice, InvoiceList } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { BillingSettings } from "./BillingSettings";
import { InvoiceDetail } from "./InvoiceDetail";
import { Invoices } from "./Invoices";

/** 2026-11-16: void and refund from the app, and knowing when the card
 *  processor is in Test Mode. */

const ID = "11111111-aaaa-4bbb-8ccc-333333333333";
const ONE = `/api/invoices/${ID}/`;
const BANNER = "The card processor is in Test Mode: no money moves.";

function paidInvoice(more: Partial<Invoice> = {}): Invoice {
  return {
    id: ID, kind: "one_off", number: "INV-0009", status: "paid", status_label: "Paid",
    overdue: false, client_company: { id: "co1", name: "Acme Facilities" },
    contact: { id: "c1", name: "Dana Reyes" }, issue_date: "2026-11-01",
    due_date: "2026-11-16", terms_days: 15, terms_label: "Net 15",
    total_cents: 50000, paid_cents: 50000, balance_cents: 0, test_paid_cents: 0,
    from_schedule: false, send_state: "",
    subtotal_cents: 50000, tax_cents: 0, currency: "usd", notes: "", terms: "",
    pay_instructions: "Bank transfer.", pay_url: "", email_to: "dana@acme.invalid",
    email_subject: "Invoice", email_body: "Hi", bill_to: {}, has_pdf: true,
    sent_at: "2026-11-01T15:00:00Z", voided_at: null, void_reason: "",
    lines: [{ id: "l1", description: "Retainer", quantity: "1.00", unit_price_cents: 50000,
              amount_cents: 50000 }],
    payments: [{ id: "p1", amount_cents: 50000, paid_on: "2026-11-16", method: "card",
                 method_label: "Card", reference: "Card Visa …1111", note: "",
                 recorded_by: "Dana Reyes", removed: false, remove_reason: "", removed_by: "",
                 is_test: false, card: true, can_refund: true, refundable_cents: 50000,
                 can_void_invoice: true }],
    merge_fields: [], refunds: [], nmi_events: [],
    ...more };
}

beforeEach(() => { vi.unstubAllGlobals(); });

function show(data: Invoice, extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({ [`GET ${ONE}history/`]: [], ...extra, [`GET ${ONE}`]: data });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<InvoiceDetail me={me} />, { path: "/invoices/:id", route: `/invoices/${ID}` });
  return fetchMock;
}

describe("Refund or cancel this payment", () => {
  it("gives back all that is left by default, needs a reason, and says what happened",
     async () => {
    const after = paidInvoice({ status: "sent", status_label: "Sent", paid_cents: 0,
                                balance_cents: 50000, message:
                                "Cancelled before it settled: $500.00 will not reach the "
                                + "card statement." });
    const fetchMock = show(paidInvoice(), { [`POST ${ONE}refund/`]: () => ({ body: after }) });
    await userEvent.click(await screen.findByRole("button",
      { name: "Refund or cancel the payment of $500.00" }));
    // Money that went through the processor comes back through it: no Remove.
    expect(screen.queryByRole("button", { name: /Remove the payment/ })).not.toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Refund or cancel this payment" });
    expect(within(form).getByLabelText("Amount to give back")).toHaveValue("500.00");
    const give = within(form).getByRole("button", { name: "Give back $500.00" });
    expect(give).toBeDisabled();                       // no reason yet
    await userEvent.type(within(form).getByLabelText("Why the money is given back"),
                         "Agreed with Dana.");
    await userEvent.click(within(form).getByLabelText("and void the invoice"));
    await userEvent.click(give);
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url === `${ONE}refund/`)).toBe(true));
    const body = fetchMock.calls.find((c) => c.url === `${ONE}refund/`)!.body;
    expect(body).toEqual({ payment: "p1", amount_cents: 50000, reason: "Agreed with Dana.",
                           void_invoice: true });
    expect(await screen.findByRole("status")).toHaveTextContent("Cancelled before it settled");
  });

  it("offers voiding the invoice only with a full refund, and refuses more than is left",
     async () => {
    const onSubmit = vi.fn();
    render(<RefundForm refundable={50000} canVoidInvoice busy={false}
      onSubmit={onSubmit} onCancel={() => undefined} />);
    const amount = screen.getByLabelText("Amount to give back");
    expect(screen.getByLabelText("and void the invoice")).toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, "100");
    expect(screen.queryByLabelText("and void the invoice")).not.toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, "600");
    expect(screen.getByText(/more than the \$500\.00/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Why the money is given back"), "x");
    expect(screen.getByRole("button", { name: "Give back $600.00" })).toBeDisabled();
  });

  it("is the practice owner's alone, and a card payment is refunded, never removed",
     async () => {
    show(paidInvoice(), {}, aMe({ role: "CF" }));
    await screen.findByText("Invoice INV-0009");
    expect(screen.queryByRole("button", { name: /Refund or cancel/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove the payment/ })).not.toBeInTheDocument();
  });

  it("lists what was given back, and shows a test payment as a test", async () => {
    show(paidInvoice({
      status: "partially_paid", status_label: "Partly paid", paid_cents: 40000,
      test_paid_cents: 40000, balance_cents: 10000,
      payments: [{ ...paidInvoice().payments[0], is_test: true, refundable_cents: 40000,
                   can_void_invoice: false }],
      refunds: [{ id: "r1", kind: "refund", kind_label: "Refunded", status: "done",
                  status_label: "Done", amount_cents: 10000, reason: "Part credit.",
                  source: "app", source_label: "Made here", nmi_transaction_id: "77",
                  response_text: "", is_test: true, problem: "", by: "Bryan Baker",
                  at: "2026-11-16T16:00:00Z", payment: "p1", cleared: false }] }));
    const given = await screen.findByLabelText("Given back");
    expect(within(given).getByText("Part credit.")).toBeInTheDocument();
    expect(within(given).getByText("Test")).toBeInTheDocument();
    expect(screen.getByText(/paid while the card processor was in Test Mode/))
      .toBeInTheDocument();
  });

  it("records a refund made in the processor's portal with one click", async () => {
    const fetchMock = show(paidInvoice({ nmi_events: [{
      id: "e1", kind: "refund", kind_label: "Refund", amount_cents: 50000,
      happened_at: "2026-11-15T12:00:00Z", transaction_id: "88", outcome: "matched",
      note: "Refunded $500.00 in NMI on Nov 15.", invoice: ID, invoice_number: "INV-0009",
      reviewed: false, can_record: true, recorded: false, full: true }] }),
      { "POST /api/nmi-events/e1/record/": () => ({ body: {} }) });
    await userEvent.click(await screen.findByLabelText("and void the invoice"));
    await userEvent.click(screen.getByRole("button", { name: "Record this refund" }));
    await waitFor(() => expect(fetchMock.calls.find(
      (c) => c.url === "/api/nmi-events/e1/record/")?.body).toEqual({ void_invoice: true }));
  });
});

describe("the card processor's Test Mode", () => {
  it("says so plainly while it is on, and why when it can't be read", () => {
    const { unmount } = render(<GatewayModeBanner again="Press Test connection."
      mode={{ test_mode: true, read_at: "2026-11-16T15:00:00Z", banner: BANNER,
              unknown: "" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(BANNER);
    unmount();
    const why = "Couldn't read whether the card processor is in Test Mode, so card payments "
      + "work as before (as if it were not). It did not answer.";
    render(<GatewayModeBanner again="" showUnknown
      mode={{ test_mode: null, read_at: "2026-11-16T15:00:00Z", banner: "", unknown: why }} />);
    expect(screen.getByText(why)).toBeInTheDocument();
  });

  it("offers Clear test payments only once it reads live, with reopen or void", async () => {
    const onClear = vi.fn();
    const { rerender } = render(<ClearTestPayments busy={false} onClear={onClear}
      summary={{ payments: 2, cards: 1, amount_cents: 70000, can_clear: false }} />);
    expect(screen.queryByRole("button", { name: "Clear test payments" })).not.toBeInTheDocument();
    rerender(<ClearTestPayments busy={false} onClear={onClear}
      summary={{ payments: 2, cards: 1, amount_cents: 70000, can_clear: true }} />);
    expect(screen.getByText("2 test payments")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Void their invoices"));
    await userEvent.click(screen.getByRole("button", { name: "Clear test payments" }));
    expect(onClear).toHaveBeenCalledWith("void");
  });

  it("asks reopen or void with no default, and Clear waits for a choice (INV-0005)", async () => {
    const onClear = vi.fn();
    render(<ClearTestPayments busy={false} onClear={onClear}
      summary={{ payments: 1, cards: 1, amount_cents: 1234, can_clear: true }} />);
    expect(screen.getByRole("group", { name: "Reopen their invoices, or void them? Choose one." }))
      .toBeInTheDocument();
    expect(screen.getByLabelText("Reopen their invoices")).not.toBeChecked();
    expect(screen.getByLabelText("Void their invoices")).not.toBeChecked();
    const clear = screen.getByRole("button", { name: "Clear test payments" });
    expect(clear).toBeDisabled();
    await userEvent.click(clear);
    expect(onClear).not.toHaveBeenCalled();
    expect(screen.getByText(/One dated after its automatic billing ended is voided either way/))
      .toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Reopen their invoices"));
    expect(clear).toBeEnabled();
    await userEvent.click(clear);
    expect(onClear).toHaveBeenCalledWith("reopen");
  });

  it("gives two panels on one page radios of their own", async () => {
    const one = vi.fn(), two = vi.fn();
    render(<>
      <ClearTestPayments busy={false} onClear={one}
        summary={{ payments: 1, cards: 0, amount_cents: 100, can_clear: true }} />
      <ClearTestPayments busy={false} onClear={two} what="charges"
        summary={{ payments: 1, cards: 0, amount_cents: 100, can_clear: true }} />
    </>);
    const [voidOne, voidTwo] = screen.getAllByLabelText("Void their invoices");
    const [reopenOne] = screen.getAllByLabelText("Reopen their invoices");
    expect(voidOne.getAttribute("name")).not.toEqual(voidTwo.getAttribute("name"));
    await userEvent.click(voidOne);
    await userEvent.click(screen.getAllByLabelText("Reopen their invoices")[1]);
    expect(voidOne).toBeChecked();
    expect(reopenOne).not.toBeChecked();
    // Said for a practice's invoices only: subscriptions have no agreement.
    expect(screen.getAllByText(/voided either way/)).toHaveLength(1);
    await userEvent.click(screen.getAllByRole("button", { name: "Clear test payments" })[0]);
    expect(one).toHaveBeenCalledWith("void");
    expect(two).not.toHaveBeenCalled();
  });

  it("shows the banner and the clearing on Invoices for the practice owner", async () => {
    const list: InvoiceList = {
      invoices: [], totals: { invoiced_cents: 0, paid_cents: 0, outstanding_cents: 0,
                              overdue_cents: 0 },
      drafts_from_schedules: 0,
      gateway_mode: { test_mode: false, read_at: "2026-11-16T15:00:00Z", banner: "",
                      unknown: "" },
      test_payments: { payments: 1, cards: 0, amount_cents: 50000, can_clear: true } };
    const fetchMock = mockApi({
      "GET /api/invoices/": list, "GET /api/companies/": [], "GET /api/nmi-events/": [],
      "POST /api/payment-account/clear-test-payments/": () => ({ body: {
        cleared: { payments: 1, reopened: 1, voided: 0, cards: 0 } } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Invoices me={aMe()} />, { path: "/invoices", route: "/invoices" });
    await userEvent.click(await screen.findByLabelText("Reopen their invoices"));
    await userEvent.click(screen.getByRole("button", { name: "Clear test payments" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "1 test payment cleared, 1 invoice reopened.");
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { invoices: "reopen" });
  });

  it("shows the banner on Billing while the processor is in Test Mode", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/payment-account/": {
        environment: "live", private_key_last4: "aaaa", public_key_last4: "bbbb",
        checked_at: "2026-11-16T15:00:00Z", check_ok: true, check_detail: "Connected.",
        ready: true, live_allowed: true, gateway: "nmi", paused: "", api_host: "secure.nmi.com",
        pricing_program: "", pricing_program_label: "",
        gateway_mode: { test_mode: true, read_at: "2026-11-16T15:00:00Z", banner: BANNER,
                        unknown: "" },
        test_payments: { payments: 1, cards: 0, amount_cents: 50000, can_clear: false } },
      "GET /api/subscription/": { status: "not_billed", status_label: "Not billed",
                                  not_billed: true, invoices: [] } }));
    renderRoute(<BillingSettings />, { path: "/settings/billing", route: "/settings/billing" });
    expect(await screen.findByRole("alert")).toHaveTextContent(BANNER);
    expect(screen.queryByRole("button", { name: "Clear test payments" })).not.toBeInTheDocument();
  });
});
