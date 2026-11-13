import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AutopayState, PayLinkPage, PortalInvoice, SubscriptionState } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ClientAutopay } from "../screens/ClientAutopay";
import { ClientInvoices } from "../screens/ClientInvoices";
import { PayLink } from "../screens/PayLink";
import { YourSubscription } from "../screens/YourSubscription";

// A card form that cannot start, wherever it is used.
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: () => { throw new Error("NMI's frames refused to start"); },
}));

const TOLD = "The card form could not be loaded, so nothing was charged. Practice has been told.";

/** Every place the card form is used reports to its own address, and the
 *  payer reads what the server answers (2026-11-13). */
describe("each card form reports a form that would not load", () => {
  beforeEach(() => vi.unstubAllGlobals());

  async function reported(fetchMock: ReturnType<typeof mockApi>, path: string) {
    expect(await screen.findByText(TOLD)).toBeInTheDocument();
    const posts = fetchMock.calls.filter((c) => c.method === "POST" && c.url === path);
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toMatchObject({ form: "component" });
  }

  it("the pay link", async () => {
    const page: PayLinkPage = {
      practice: "Practice", number: "INV-0007", amount_due_cents: 500, due_date: "2026-11-20",
      paid: false, test_mode: false, public_key: "pub", notice: "" };
    const fetchMock = mockApi({ "POST /api/pay/tok123/form-failed": { message: TOLD },
                                "GET /api/pay/tok123": page });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PayLink />, { path: "/pay/:token", route: "/pay/tok123" });
    await reported(fetchMock, "/api/pay/tok123/form-failed");
  });

  it("the portal's Pay", async () => {
    const row: PortalInvoice = {
      id: "inv1", number: "INV-0007", issue_date: "2026-11-01", due_date: "2026-11-16",
      total_cents: 500, balance_cents: 500, status: "sent", status_label: "Sent",
      overdue: false, pay_url: "", can_pay: true, pay_paused: false,
      payment_in_progress: false, test_mode: false };
    const fetchMock = mockApi({
      "POST /api/portal-invoices/inv1/form-failed/": { message: TOLD },
      "GET /api/portal-invoices/inv1/pay/": { public_key: "pub", test_mode: false,
                                              amount_cents: 500, number: "INV-0007" },
      "GET /api/portal-invoices/": [row],
      "GET /api/portal-autopay/": { status: 403, body: {} } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientInvoices />);
    await userEvent.click(await screen.findByRole("button", { name: "Pay invoice INV-0007" }));
    await reported(fetchMock, "/api/portal-invoices/inv1/form-failed/");
  });

  it("saving a card for auto-pay", async () => {
    const state: AutopayState = { ready: true, paused: false, test_mode: false,
      public_key: "pub", card: null, autopay: null, wording: "", wording_version: "1" };
    const fetchMock = mockApi({ "POST /api/portal-autopay/form-failed/": { message: TOLD },
                                "GET /api/portal-autopay/": state });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientAutopay />);
    await userEvent.click(await screen.findByRole("button", { name: "Save a card" }));
    await reported(fetchMock, "/api/portal-autopay/form-failed/");
  });

  it("a practice's subscription card", async () => {
    const state: SubscriptionState = { status: "needs_card", status_label: "No card yet",
      not_billed: false, plan: "Beta at cost", amount_cents: 2000, billing_email: "",
      card: null, next_charge_on: null, public_key: "pub-platform", test_mode: false,
      suspended: false, open_cents: 0, invoices: [], paused: false };
    const fetchMock = mockApi({ "POST /api/subscription/form-failed/": { message: TOLD },
                                "GET /api/subscription/": state });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<YourSubscription />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a card" }));
    await reported(fetchMock, "/api/subscription/form-failed/");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(TOLD));
  });
});
