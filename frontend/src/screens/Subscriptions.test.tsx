import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubscriptionState } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { PracticeRow, Practices } from "./Practices";
import { Suspended } from "./Suspended";
import { YourSubscription } from "./YourSubscription";

const mounted: { key: string; text?: string }[] = [];
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: {
    tokenizationKey: string; payButtonText?: string;
    onPay: (e: { token: string }) => Promise<true | string> }) => {
    mounted.push({ key: options.tokenizationKey, text: options.payButtonText });
    const button = document.createElement("button");
    button.textContent = "NMI save";
    button.onclick = () => { void options.onPay({ token: "tok-sub" }); };
    box.appendChild(button);
    return { destroy: () => button.remove() };
  },
}));

const NEEDS: SubscriptionState = {
  status: "needs_card", status_label: "Needs a card", not_billed: false, plan: "Beta at cost",
  amount_cents: 2000, billing_email: "owner@acme.invalid", card: null, next_charge_on: null,
  public_key: "platform-public", test_mode: true, suspended: false, open_cents: 0,
  invoices: [] };
const CARD = { brand: "Visa", last4: "1111", expires: "10/29" };
const OPEN = {
  id: "inv1", number: "ENH-202611-acme", period_start: "2026-11-01", total_cents: 2000,
  status: "open" as const, status_label: "Open", paid_at: null, checking: false,
  last_charge_text: "Do not honor" };

describe("your subscription (P4 part 5)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); mounted.length = 0; });

  it("saves the practice's card with the platform's key and shows the next charge",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "POST /api/subscription/card/": () => ({ status: 200, body: {
          ...NEEDS, status: "active", status_label: "Active", card: CARD,
          next_charge_on: "2026-11-01", message: "The card is saved." } }),
        "GET /api/subscription/": NEEDS,
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<YourSubscription />);
      expect(await screen.findByText(/\$20\.00 a month/)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Add a card" }));
      await waitFor(() => expect(mounted).toEqual([
        { key: "platform-public", text: "Save this card" }]));
      await user.click(screen.getByRole("button", { name: "NMI save" }));
      expect(await screen.findByText("Visa ending 1111")).toBeInTheDocument();
      expect(screen.getByText(/Next charge: November 1, 2026/)).toBeInTheDocument();
    });

  it("pays what is open with Pay now and lists the invoice with its PDF", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/subscription/pay-now/": () => ({ status: 200, body: {
        ...NEEDS, status: "active", card: CARD, open_cents: 0,
        invoices: [{ ...OPEN, status: "paid", status_label: "Paid", last_charge_text: "" }],
        message: "Thank you. $20.00 was charged for invoice ENH-202611-acme." } }),
      "GET /api/subscription/": { ...NEEDS, status: "past_due", status_label: "Past due",
                                  card: CARD, open_cents: 2000, invoices: [OPEN] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<YourSubscription />);
    expect(await screen.findByText("Do not honor")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download invoice ENH-202611-acme" }))
      .toHaveAttribute("href", "/api/subscription/inv1/pdf/");
    await user.click(screen.getByRole("button", { name: "Pay now $20.00" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Thank you");
  });

  it("says the owner's own practice is not billed", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/subscription/": {
      ...NEEDS, status: "not_billed", not_billed: true } }));
    renderRoute(<YourSubscription />);
    expect(await screen.findByText("Your practice is not billed.")).toBeInTheDocument();
  });

  it("shows a suspended practice's owner the billing screen, and others only who can pay",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/subscription/": {
        ...NEEDS, suspended: true, card: CARD, open_cents: 2000, invoices: [OPEN] } }));
      renderRoute(<Suspended me={aMe({ role: "FF" })} />);
      expect(screen.getByRole("heading", { level: 1 }))
        .toHaveTextContent("Your practice is suspended until the invoice is paid");
      expect(await screen.findByRole("button", { name: "Pay now $20.00" })).toBeInTheDocument();
      renderRoute(<Suspended me={aMe({ role: "VA" })} />);
      expect(screen.getByText("Your practice owner can pay it under Settings → Billing."))
        .toBeInTheDocument();
    });
});

const ROW: PracticeRow = {
  id: "22222222-2222-4222-8222-222222222222", display_name: "Blue Sky", legal_name: "",
  domain: "", status: "active", created_at: "2026-09-09T16:14:43Z", archived_at: null,
  oauth_client: "external", pricing_program: "", staff_count: 1, client_count: 0,
  ai_spend_this_month_usd: "0.00", last_activity_at: null,
  subscription: { status: "past_due", not_billed: false, amount_cents: 2000, plan_cents: 2000,
                  overridden: false, card_on_file: true, open_cents: 2000,
                  oldest_open_days: 31, eligible_for_suspension: true, suspended_at: null },
};

describe("subscriptions on the Practices screen (P4 part 5)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("flags 30 days unpaid and suspends only when the owner presses Suspend", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = mockApi({
      [`POST /api/platform/practices/${ROW.id}/suspend`]: () => ({ status: 200, body: {
        ...ROW, status: "suspended" } }),
      "GET /api/platform/practices": [ROW],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Practices />);
    const card = (await screen.findByText("Blue Sky")).closest("article")!;
    expect(within(card).getByText("Overdue 30+ days: suspend?")).toBeInTheDocument();
    expect(within(card).getByText(/\$20\.00 open for 31 days/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Suspend" }));
    expect(await screen.findByText(/is suspended until its invoice is paid/))
      .toBeInTheDocument();
  });

  it("sets a practice's own monthly amount", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      [`PATCH /api/platform/practices/${ROW.id}`]: () => ({ status: 200, body: {
        ...ROW, subscription: { ...ROW.subscription!, amount_cents: 1500, overridden: true } } }),
      "GET /api/platform/practices": [ROW],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Practices />);
    await user.click(await screen.findByRole("button", {
      name: "Change the amount for Blue Sky" }));
    await user.type(screen.getByLabelText("Monthly amount for Blue Sky"), "15");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/now pays \$15\.00 a month, from the next month/))
      .toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual(
      { subscription_amount_cents: 1500 });
  });
});
