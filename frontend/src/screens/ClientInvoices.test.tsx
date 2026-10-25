import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalInvoice } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ClientInvoices } from "./ClientInvoices";

// NMI's component stands in here as a button that hands back a token, the
// way the real one does after the card is typed into NMI's own fields.
const mounted: { key: string; onPay: (e: { token: string }) => Promise<true | string> }[] = [];
let lastReturn: true | string | undefined;
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: {
    tokenizationKey: string; onPay: (e: { token: string }) => Promise<true | string> }) => {
    mounted.push({ key: options.tokenizationKey, onPay: options.onPay });
    const button = document.createElement("button");
    button.textContent = "NMI pay";
    button.onclick = async () => { lastReturn = await options.onPay({ token: "tok-from-nmi" }); };
    box.appendChild(button);
    return { destroy: () => button.remove() };
  },
}));

const OPEN: PortalInvoice = {
  id: "a", number: "INV-0007", issue_date: "2026-10-01", due_date: "2026-10-16",
  total_cents: 680000, balance_cents: 580000, status: "partially_paid",
  status_label: "Partly paid", overdue: false, pay_url: "", can_pay: true,
  payment_in_progress: false, test_mode: true };
const CONFIG = { public_key: "pub-practice-key", test_mode: true, amount_cents: 580000,
                 number: "INV-0007" };

describe("paying an invoice in the portal (P4 part 2)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); mounted.length = 0; lastReturn = undefined; });

  it("shows Pay only where the server says it can be paid", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-invoices/": [
      OPEN, { ...OPEN, id: "b", number: "INV-0003", can_pay: false, status: "paid",
              balance_cents: 0 },
      { ...OPEN, id: "c", number: "INV-0004", can_pay: false, payment_in_progress: true }] }));
    renderRoute(<ClientInvoices />);
    expect(await screen.findByRole("button", { name: "Pay invoice INV-0007" }))
      .toHaveTextContent("Pay $5,800.00");
    expect(screen.queryByRole("button", { name: "Pay invoice INV-0003" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Pay invoice INV-0004" })).toBeNull();
    expect(screen.getByText("Payment being checked")).toBeInTheDocument();
    // At phone width each invoice is a card, each fact under its name.
    const row = screen.getByText("INV-0007").closest("tr") as HTMLElement;
    expect(row.closest("table")).toHaveClass("cards-on-phone");
    expect([...row.querySelectorAll("td[data-label]")].map((td) => td.getAttribute("data-label")))
      .toEqual(["Issued", "Due", "Total", "Still owed", "Status"]);
  });

  it("mounts NMI's fields with the practice's key, says Test mode, and pays with the token",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/portal-invoices/a/pay/": CONFIG,
        "POST /api/portal-invoices/a/pay/": () => ({ status: 200, body: {
          status: "approved", message: "Thank you. $5,800.00 was paid on invoice INV-0007.",
          balance_cents: 0, invoice_status: "paid" } }),
        "GET /api/portal-invoices/": [OPEN],
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<ClientInvoices />);
      await user.click(await screen.findByRole("button", { name: "Pay invoice INV-0007" }));
      await waitFor(() => expect(mounted).toHaveLength(1));
      expect(mounted[0].key).toBe("pub-practice-key");
      expect(screen.getAllByText("Test mode").length).toBeGreaterThan(0);
      await user.click(screen.getByRole("button", { name: "NMI pay" }));
      expect(await screen.findByRole("status")).toHaveTextContent("was paid on invoice INV-0007");
      expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
        { payment_token: "tok-from-nmi" });
      expect(lastReturn).toBe(true);
      // The form closes once paid.
      await waitFor(() => expect(screen.queryByRole("button", { name: "NMI pay" })).toBeNull());
    });

  it("keeps the form open on a decline and hands the component NMI's words", async () => {
    const user = userEvent.setup();
    const declined = "The card was declined, and nothing was charged.";
    vi.stubGlobal("fetch", mockApi({
      "GET /api/portal-invoices/a/pay/": CONFIG,
      "POST /api/portal-invoices/a/pay/": () => ({ status: 200, body: {
        status: "declined", message: declined, balance_cents: 580000,
        invoice_status: "partially_paid" } }),
      "GET /api/portal-invoices/": [OPEN],
    }));
    renderRoute(<ClientInvoices />);
    await user.click(await screen.findByRole("button", { name: "Pay invoice INV-0007" }));
    await waitFor(() => expect(mounted).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "NMI pay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(declined);
    expect(lastReturn).toBe(declined);
    expect(screen.getByRole("button", { name: "NMI pay" })).toBeInTheDocument();
  });

  it("says plainly when the answer is being checked", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/portal-invoices/a/pay/": CONFIG,
      "POST /api/portal-invoices/a/pay/": () => ({ status: 200, body: {
        status: "unknown", message: "We did not hear back from the card processor.",
        balance_cents: 580000, invoice_status: "partially_paid" } }),
      "GET /api/portal-invoices/": [OPEN],
    }));
    renderRoute(<ClientInvoices />);
    await user.click(await screen.findByRole("button", { name: "Pay invoice INV-0007" }));
    await waitFor(() => expect(mounted).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "NMI pay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not hear back");
  });
});
