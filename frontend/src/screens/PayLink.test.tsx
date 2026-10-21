import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PayLinkPage } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { PayLink } from "./PayLink";

// NMI's component stands in as a button that hands back a token.
const mounted: { key: string }[] = [];
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: {
    tokenizationKey: string; onPay: (e: { token: string }) => Promise<true | string> }) => {
    mounted.push({ key: options.tokenizationKey });
    const button = document.createElement("button");
    button.textContent = "NMI pay";
    button.onclick = () => { void options.onPay({ token: "tok-from-nmi" }); };
    box.appendChild(button);
    return { destroy: () => button.remove() };
  },
}));

const OPEN: PayLinkPage = {
  practice: "Executives Now", number: "INV-0007", amount_due_cents: 580000,
  due_date: "2026-10-16", paid: false, test_mode: true, public_key: "pub-practice-key",
  notice: "" };
const at = { path: "/pay/:token", route: "/pay/tok123" };

describe("the pay link's page (P4 part 3)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); mounted.length = 0; });

  it("shows the practice, the number, the amount, the due date, the PDF and the card form",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/pay/tok123": OPEN }));
      renderRoute(<PayLink />, at);
      expect(await screen.findByText("Executives Now")).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Invoice INV-0007");
      expect(screen.getByText("$5,800.00")).toBeInTheDocument();
      expect(screen.getByText("Test mode")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Download invoice INV-0007" }))
        .toHaveAttribute("href", "/api/pay/tok123/pdf");
      await waitFor(() => expect(mounted).toEqual([{ key: "pub-practice-key" }]));
    });

  it("pays with the token and says so", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/pay/tok123": () => ({ status: 200, body: {
        status: "approved", message: "Thank you. $5,800.00 was paid on invoice INV-0007.",
        balance_cents: 0, invoice_status: "paid" } }),
      "GET /api/pay/tok123": OPEN,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PayLink />, at);
    await user.click(await screen.findByRole("button", { name: "NMI pay" }));
    expect(await screen.findByRole("status")).toHaveTextContent("was paid on invoice INV-0007");
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { payment_token: "tok-from-nmi" });
  });

  it("shows Paid and no card form once paid", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/pay/tok123": {
      ...OPEN, paid: true, amount_due_cents: 0, public_key: "" } }));
    renderRoute(<PayLink />, at);
    expect(await screen.findByText("Paid")).toBeInTheDocument();
    expect(screen.queryByText("Pay by card")).toBeNull();
    expect(mounted).toEqual([]);
  });

  it("says why there is no card form", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/pay/tok123": {
      ...OPEN, public_key: "", notice: "A payment on this invoice is already under way." } }));
    renderRoute(<PayLink />, at);
    expect(await screen.findByText("A payment on this invoice is already under way."))
      .toBeInTheDocument();
    expect(mounted).toEqual([]);
  });

  it("shows the server's words for a link that does not work", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/pay/tok123": () => ({ status: 404, body: {
      detail: "This payment link is not valid. Ask the practice that sent the invoice for a "
        + "new one." } }) }));
    renderRoute(<PayLink />, at);
    expect(await screen.findByText(/This payment link is not valid/)).toBeInTheDocument();
  });
});
