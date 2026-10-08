import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Invoice, InvoiceList, InvoiceRow, PortalInvoice } from "../lib/api";
import { dollars, lineAmount, longDate, plain, toCents } from "../lib/money";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ClientInvoices } from "./ClientInvoices";
import { InvoiceDetail } from "./InvoiceDetail";
import { Invoices } from "./Invoices";
import { InvoiceSettings } from "./InvoiceSettings";

/** P4A — client invoicing without a processor: the practice's screens and a
 *  client's view. */

const ID = "11111111-aaaa-4bbb-8ccc-222222222222";
const ONE = `/api/invoices/${ID}/`;

function row(more: Partial<InvoiceRow> = {}): InvoiceRow {
  return { id: ID, kind: "one_off", number: "INV-0007", status: "sent", status_label: "Sent",
           overdue: false, client_company: { id: "co1", name: "Acme Facilities" },
           contact: { id: "c1", name: "Dana Reyes" }, issue_date: "2026-10-01",
           due_date: "2026-10-16", total_cents: 680000, paid_cents: 0, balance_cents: 680000,
           from_schedule: false, send_state: "", ...more };
}

function invoice(more: Partial<Invoice> = {}): Invoice {
  return {
    ...row(), subtotal_cents: 680000, tax_cents: 0, currency: "usd",
    notes: "Thank you.", terms: "Net 15.", pay_instructions: "Bank transfer to Example Bank.",
    pay_url: "", email_to: "dana@acme.invalid", email_subject: "Invoice INV-0007 from Us",
    email_body: "Hi Dana,\n\nInvoice INV-0007 for $6,800.00 is attached.",
    bill_to: { name: "Dana Reyes", company: "Acme Facilities", email: "dana@acme.invalid" },
    has_pdf: true, sent_at: "2026-10-01T15:00:00Z", voided_at: null, void_reason: "",
    lines: [{ id: "l1", description: "Monthly retainer", quantity: "1.00",
              unit_price_cents: 500000, amount_cents: 500000 },
            { id: "l2", description: "Workshop", quantity: "1.50", unit_price_cents: 120000,
              amount_cents: 180000 }],
    payments: [], merge_fields: ["Client", "First name", "Number", "Total", "Due date",
                                 "Practice"],
    ...more };
}

const LIST: InvoiceList = {
  invoices: [row(), row({ id: "i2", number: "INV-0006", status: "partially_paid",
                          status_label: "Partly paid", overdue: true, paid_cents: 100000,
                          balance_cents: 580000 }),
             row({ id: "i3", number: "", status: "draft", status_label: "Draft",
                   from_schedule: true }),
             row({ id: "i4", number: "INV-0008", status: "ready", status_label: "Ready to send",
                   send_state: "waiting" }),
             row({ id: "i5", number: "INV-0005", kind: "contact", client_company: null,
                   contact: { id: "c9", name: "Lee Okafor" } })],
  totals: { invoiced_cents: 2040000, paid_cents: 100000, outstanding_cents: 1940000,
            overdue_cents: 580000 },
  drafts_from_schedules: 1,
};
const COMPANIES = [{ id: "co1", name: "Acme Facilities", industry: "", is_client_company: true,
                     seat_count: null, primary_contact: null },
                   { id: "co2", name: "A prospect", industry: "", is_client_company: false,
                     seat_count: null, primary_contact: null }];
const CONTACTS = [{ id: "c1", first_name: "Dana", last_name: "Reyes", company: "co1" },
                  { id: "c2", first_name: "Sam", last_name: "Other", company: "co2" }];

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

describe("money, with no floating-point dollars", () => {
  it("reads what was typed into cents, or says it is not an amount", () => {
    expect(toCents("19.99")).toBe(1999);
    expect(toCents("$1,200")).toBe(120000);
    expect(toCents("45.5")).toBe(4550);
    expect(toCents("0.07")).toBe(7);
    for (const bad of ["", "abc", "1.999", "-5", "1.2.3"]) expect(toCents(bad)).toBeNull();
  });

  it("shows cents as dollars, and multiplies as the server does", () => {
    expect(dollars(680000)).toBe("$6,800.00");
    expect(dollars(7)).toBe("$0.07");
    expect(plain(120050)).toBe("1200.50");
    // 2.75 x 199.99 = 549.9725; 0.33 x 1000.01 = 330.0033; 0.5 x 0.01 rounds up.
    expect(lineAmount("2.75", 19999)).toBe(54997);
    expect(lineAmount("0.33", 100001)).toBe(33000);
    expect(lineAmount("0.5", 1)).toBe(1);
    expect(lineAmount("lots", 100)).toBe(0);
    expect(longDate("2026-10-16")).toBe("October 16, 2026");
  });
});

describe("the invoices list", () => {
  function show(me = aMe(), route = "/", list = LIST, extra: Record<string, unknown> = {}) {
    const fetchMock = mockApi({
      ...extra, "GET /api/invoice-schedules/": [], "GET /api/companies/": COMPANIES,
      "GET /api/contacts/": CONTACTS, "GET /api/invoices/": list });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Invoices me={me} />, { route });
    return fetchMock;
  }

  it("lists every invoice with its totals, and marks what needs attention", async () => {
    show();
    const totals = await screen.findByLabelText("Totals");
    expect(totals).toHaveTextContent("Invoiced$20,400.00");
    expect(totals).toHaveTextContent("Outstanding$19,400.00");
    expect(totals).toHaveTextContent("Overdue$5,800.00");
    expect(screen.getByRole("link", { name: "INV-0007" })).toHaveAttribute(
      "href", `/invoices/${ID}`);
    expect(screen.getByText("Overdue", { selector: ".pill" })).toBeInTheDocument();
    expect(screen.getByText("from a schedule")).toBeInTheDocument();
    expect(screen.getByText("waiting to be approved")).toBeInTheDocument();
    expect(screen.getByText("Not a client")).toBeInTheDocument();
    expect(screen.getByText(/One draft written by a recurring invoice is waiting/))
      .toBeInTheDocument();
    // A draft shows no balance: nothing is owed on it yet.
    const draft = screen.getByRole("link", { name: "Draft" }).closest("tr") as HTMLElement;
    expect(within(draft).getAllByText("$6,800.00")).toHaveLength(1);
  });

  it("filters by status and client, and downloads exactly what is listed", async () => {
    const fetchMock = show();
    await screen.findByLabelText("Totals");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "overdue");
    await userEvent.selectOptions(screen.getByLabelText("Client company"), "co1");
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url === "/api/invoices/?status=overdue&company=co1")).toBe(true));
    expect(await screen.findByLabelText("Totals for what is listed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download as CSV" })).toHaveAttribute(
      "href", "/api/invoices/export/?status=overdue&company=co1");
    // Only client companies can be billed from here.
    expect(within(screen.getByLabelText("Client company")).queryByText("A prospect"))
      .not.toBeInTheDocument();
  });

  it("starts a draft for someone at a client company", async () => {
    const fetchMock = show(aMe(), "/", LIST, {
      "POST /api/invoices/": () => ({ status: 201, body: invoice({ status: "draft" }) }) });
    await userEvent.click(await screen.findByRole("button", { name: "New invoice" }));
    const start = screen.getByRole("button", { name: "Start the draft" });
    expect(start).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Client company to invoice"), "co1");
    const people = await screen.findByLabelText("Addressed to");
    await waitFor(() => expect(within(people).getByText("Dana Reyes")).toBeInTheDocument());
    expect(within(people).queryByText("Sam Other")).not.toBeInTheDocument();
    await userEvent.selectOptions(people, "c1");
    await userEvent.click(start);
    await waitFor(() => expect(sent(fetchMock, "/api/invoices/")).toEqual([
      { client_company: "co1", contact: "c1", lines: [] }]));
  });

  it("lets only the practice owner invoice someone who is not a client", async () => {
    show(aMe({ role: "CF" }));
    await userEvent.click(await screen.findByRole("button", { name: "New invoice" }));
    expect(screen.queryByText(/someone who is not a client/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Invoice settings" })).not.toBeInTheDocument();
  });

  it("says what a recurring invoice does, and pauses one", async () => {
    const schedule = { id: "s1", client_company: { id: "co1", name: "Acme Facilities" },
                       contact: { id: "c1", name: "Dana Reyes" }, day_of_month: 5,
                       next_on: "2026-11-05", ends_on: null, lines: [], total_cents: 680000,
                       notes: "", terms: "", is_active: true };
    const fetchMock = mockApi({
      "PATCH /api/invoice-schedules/s1/": () => ({ body: { ...schedule, is_active: false } }),
      "GET /api/invoice-schedules/": [schedule], "GET /api/companies/": COMPANIES,
      "GET /api/invoices/": LIST });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Invoices me={aMe()} />);
    expect(await screen.findByText(/does not number it and\s+does not send it/))
      .toBeInTheDocument();
    expect(await screen.findByText("November 5, 2026")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", {
      name: "Pause the recurring invoice for Acme Facilities" }));
    await waitFor(() => expect(sent(fetchMock, "/api/invoice-schedules/s1/"))
      .toEqual([{ is_active: false }]));
  });
});

describe("one invoice", () => {
  function show(data: Invoice, me = aMe(), extra: Record<string, unknown> = {}) {
    const fetchMock = mockApi({ ...extra, [`GET ${ONE}history/`]: [
      { at: "2026-10-01T15:00:00Z", what: "invoice_sent", by: "Bryan Baker", before: "ready",
        after: "sent", reason: "", amount_cents: null, to: "dana@acme.invalid" }],
      [`GET ${ONE}`]: data });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<InvoiceDetail me={me} />, { path: "/invoices/:id", route: `/invoices/${ID}` });
    return fetchMock;
  }
  const draft = () => invoice({ status: "draft", status_label: "Draft", number: "",
                                has_pdf: false, sent_at: null });

  it("edits a draft, totals it as it is typed, and saves cents", async () => {
    const fetchMock = show(draft(), aMe(), { [`PATCH ${ONE}`]: () => ({ body: draft() }) });
    expect(await screen.findByText("Draft invoice")).toBeInTheDocument();
    expect(screen.getByText("Total $6,800.00")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save the draft" });
    expect(save).toBeDisabled();
    const price = screen.getByLabelText("Price of line 2");
    await userEvent.clear(price);
    await userEvent.type(price, "1,000.50");
    expect(screen.getByText("Total $6,500.75")).toBeInTheDocument();
    // Unsaved changes are saved before it can be made ready.
    expect(screen.getByRole("button", { name: "Make it ready to send" })).toBeDisabled();
    await userEvent.click(save);
    await waitFor(() => expect(sent(fetchMock, ONE)).toHaveLength(1));
    expect(sent(fetchMock, ONE)[0]).toMatchObject({ lines: [
      { description: "Monthly retainer", quantity: "1.00", unit_price_cents: 500000 },
      { description: "Workshop", quantity: "1.50", unit_price_cents: 100050 }] });
    expect(screen.getByRole("link", { name: "Preview the PDF" })).toHaveAttribute(
      "href", `${ONE}preview/`);
  });

  it("says what making ready does, and does it", async () => {
    const fetchMock = show(draft(), aMe(), {
      [`POST ${ONE}make-ready/`]: () => ({ body: invoice({ status: "ready" }) }) });
    expect(await screen.findByText(/gives the invoice its number, fixes its wording/))
      .toBeInTheDocument();
    expect(screen.getByText(/It sends nothing/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Make it ready to send" }));
    await waitFor(() => expect(sent(fetchMock, "make-ready/")).toEqual([{}]));
  });

  it("shows the whole email of a ready invoice, and only the practice owner sends it",
    async () => {
      const ready = invoice({ status: "ready", status_label: "Ready to send",
                              send_state: "waiting", sent_at: null });
      const fetchMock = show(ready, aMe(), { [`POST ${ONE}send/`]: () => ({ body: invoice() }) });
      const email = await screen.findByLabelText("The email as it will be sent");
      expect(email).toHaveTextContent("dana@acme.invalid");
      expect(email).toHaveTextContent("Invoice INV-0007 from Us");
      expect(email).toHaveTextContent("Attached: Invoice-INV-0007.pdf");
      expect(screen.getByText(/Sending it is your approval/)).toBeInTheDocument();
      expect(screen.queryByLabelText("Description of line 1")).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Send to dana@acme.invalid" }));
      await waitFor(() => expect(sent(fetchMock, "send/")).toEqual([{}]));
      cleanup();
      vi.unstubAllGlobals();
      show(ready, aMe({ role: "CF" }));
      expect(await screen.findAllByText(/goes when the practice owner approves it/))
        .not.toHaveLength(0);
      expect(screen.queryByRole("button", { name: /^Send to/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Void the invoice" })).not.toBeInTheDocument();
    });

  it("records a payment for no more than is owed", async () => {
    const fetchMock = show(invoice(), aMe(), {
      [`POST ${ONE}payments/`]: () => ({ body: invoice({ status: "partially_paid" }) }) });
    const amount = await screen.findByLabelText("Amount received");
    expect(amount).toHaveValue("6800.00");
    await userEvent.clear(amount);
    await userEvent.type(amount, "7000");
    expect(screen.getByRole("button", { name: "Record the payment" })).toBeDisabled();
    expect(screen.getByText(/more than the \$6,800.00 still owed/)).toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, "2000");
    await userEvent.type(screen.getByLabelText("Payment reference"), "CHK 2231");
    await userEvent.selectOptions(screen.getByLabelText("How it was paid"), "check");
    await userEvent.click(screen.getByRole("button", { name: "Record the payment" }));
    await waitFor(() => expect(sent(fetchMock, "payments/")).toHaveLength(1));
    expect(sent(fetchMock, "payments/")[0]).toMatchObject({
      amount_cents: 200000, method: "check", reference: "CHK 2231" });
  });

  it("removes a payment only with a reason, and shows a removed one struck through",
    async () => {
      const paid = invoice({ status: "partially_paid", status_label: "Partly paid",
                             paid_cents: 200000, balance_cents: 480000, payments: [
          { id: "p1", amount_cents: 200000, paid_on: "2026-10-03", method: "check",
            method_label: "Check", reference: "CHK 2231", note: "", recorded_by: "Bryan Baker",
            removed: false, remove_reason: "", removed_by: "" },
          { id: "p2", amount_cents: 5000, paid_on: "2026-10-04", method: "other",
            method_label: "Other", reference: "", note: "", recorded_by: "Bryan Baker",
            removed: true, remove_reason: "Wrong invoice", removed_by: "Bryan Baker" }] });
      const fetchMock = show(paid, aMe(), {
        [`POST ${ONE}remove-payment/`]: () => ({ body: paid }) });
      expect(await screen.findByText("removed: Wrong invoice")).toBeInTheDocument();
      const ask = vi.spyOn(window, "prompt").mockReturnValue("  ");
      await userEvent.click(screen.getByRole("button", {
        name: "Remove the payment of $2,000.00" }));
      expect(sent(fetchMock, "remove-payment/")).toEqual([]);
      ask.mockReturnValue("Entered twice");
      await userEvent.click(screen.getByRole("button", {
        name: "Remove the payment of $2,000.00" }));
      await waitFor(() => expect(sent(fetchMock, "remove-payment/")).toEqual([
        { payment: "p1", reason: "Entered twice" }]));
      // And it cannot be voided while money counts against it.
      expect(screen.getByRole("button", { name: "Void the invoice" })).toBeDisabled();
      expect(screen.getByText(/Remove the payment first/)).toBeInTheDocument();
    });

  it("voids only with a reason and a confirmation", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = show(invoice(), aMe(), {
      [`POST ${ONE}void/`]: () => ({ body: invoice({ status: "void" }) }) });
    const button = await screen.findByRole("button", { name: "Void the invoice" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Why the invoice is being voided"), "Billed twice");
    await userEvent.click(button);
    expect(confirmed).toHaveBeenCalled();
    await waitFor(() => expect(sent(fetchMock, "void/")).toEqual([{ reason: "Billed twice" }]));
  });

  it("shows a void invoice with its reason, its PDF and nothing to do to it", async () => {
    show(invoice({ status: "void", status_label: "Void", voided_at: "2026-10-05T12:00:00Z",
                   void_reason: "Billed twice." }));
    expect(await screen.findByText(/Billed twice\. Its number is kept/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download the PDF" })).toHaveAttribute(
      "href", `${ONE}pdf/`);
    for (const name of ["Void the invoice", "Record the payment", "Send again"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    const history = screen.getByLabelText("History of this invoice");
    expect(history).toHaveTextContent("Sent · to dana@acme.invalid · Bryan Baker");
  });

  it("shows no way to pay online while there is no pay link", async () => {
    show(invoice());
    await screen.findByText(/Bank transfer to Example Bank/);
    expect(screen.queryByText(/Pay now|Pay online/i)).not.toBeInTheDocument();
  });
});

describe("invoice settings", () => {
  it("says why how-to-pay matters, and saves numbers as numbers", async () => {
    const data = { prefix: "INV-", next_value: 12, next_number: "INV-0012", terms_days: 15,
                   default_notes: "", default_terms: "", pay_instructions: "",
                   email_subject: "Invoice {Number} from {Practice}", email_body: "Hi",
                   merge_fields: ["Number", "Practice"] };
    const fetchMock = mockApi({ "POST /api/invoice-settings/": () => ({ body: data }),
                                "GET /api/invoice-settings/": data });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<InvoiceSettings />);
    expect(await screen.findByText(/cannot be made ready without it/)).toBeInTheDocument();
    expect(screen.getByText(/will be INV-0012/)).toBeInTheDocument();
    expect(screen.getByText(/raised, to carry on from another system, and never lowered/))
      .toBeInTheDocument();
    await userEvent.type(screen.getAllByLabelText("How to pay")[0], "By check.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "/api/invoice-settings/")).toHaveLength(1));
    expect(sent(fetchMock, "/api/invoice-settings/")[0]).toMatchObject({
      pay_instructions: "By check.", next_value: 12, terms_days: 15, prefix: "INV-" });
  });
});

describe("a client's invoices", () => {
  const ROWS: PortalInvoice[] = [
    { id: "a", number: "INV-0007", issue_date: "2026-10-01", due_date: "2026-10-16",
      total_cents: 680000, balance_cents: 580000, status: "partially_paid",
      status_label: "Partly paid", overdue: true, pay_url: "" },
    { id: "b", number: "INV-0003", issue_date: "2026-08-01", due_date: "2026-08-16",
      total_cents: 500000, balance_cents: 0, status: "paid", status_label: "Paid",
      overdue: false, pay_url: "" },
    { id: "c", number: "INV-0002", issue_date: "2026-07-01", due_date: "2026-07-16",
      total_cents: 500000, balance_cents: 500000, status: "void", status_label: "Void",
      overdue: false, pay_url: "" }];

  it("shows what they were sent, what is owed, and each PDF", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-invoices/": ROWS }));
    renderRoute(<ClientInvoices />);
    const first = (await screen.findByText("INV-0007")).closest("tr") as HTMLElement;
    expect(first).toHaveTextContent("$6,800.00");
    expect(first).toHaveTextContent("$5,800.00");
    expect(first).toHaveTextContent("Due October 16, 2026");
    expect(screen.getByRole("link", { name: "Download invoice INV-0007" }))
      .toHaveAttribute("href", "/api/portal-invoices/a/pdf/");
    // A void one is listed, marked, and owes nothing.
    const gone = screen.getByText("INV-0002").closest("tr") as HTMLElement;
    expect(gone).toHaveTextContent("Void");
    expect(within(gone).getAllByText("$5,000.00")).toHaveLength(1);
    expect(screen.queryByText(/Pay now|Pay online/i)).not.toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-invoices/": [] }));
    renderRoute(<ClientInvoices />);
    expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
  });
});
