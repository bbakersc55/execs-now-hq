import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutopayState, PAYMENTS_PAUSED, PortalInvoice, SubscriptionState } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ClientAutopay } from "../screens/ClientAutopay";
import { ClientInvoices } from "../screens/ClientInvoices";
import { YourSubscription } from "../screens/YourSubscription";
import { CardPaymentsSwitchCard } from "./CardPaymentsSwitch";
import { NmiCardForm } from "./NmiCardForm";

vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: () => { throw new Error("the Payment Component must not load here"); },
}));

const VAULTIX = "https://secure.vaultixpay.com/token/Collect.js";

/** Collect.js as it behaves: configure() takes the fields and the callback;
 *  startPaymentRequest() hands back a one-time token. */
function fakeCollect() {
  const seen: { config?: Record<string, unknown>; starts: number } = { starts: 0 };
  window.CollectJS = {
    configure: (config) => { seen.config = config; },
    startPaymentRequest: () => {
      seen.starts += 1;
      (seen.config!.callback as (r: { token: string }) => void)({ token: "tok-from-collect" });
    },
  };
  return seen;
}

/** The script tag the form adds, loaded. */
async function loadScript() {
  const tag = await waitFor(() => {
    const found = document.querySelector<HTMLScriptElement>("script[data-collect-js]");
    expect(found).not.toBeNull();
    return found!;
  });
  const seen = fakeCollect();
  tag.onload?.(new Event("load"));
  return { tag, seen };
}

describe("Collect.js from the white-label host (2026-11-10)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    document.querySelectorAll("script[data-collect-js]").forEach((t) => t.remove());
    delete window.CollectJS;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("loads Collect.js from the host with the practice's key and posts its token", async () => {
    const fetchMock = mockApi({ "POST /api/x/pay/": { status: "approved", message: "Paid.",
                                                      balance_cents: 0 } });
    vi.stubGlobal("fetch", fetchMock);
    const done = vi.fn();
    render(<NmiCardForm publicKey="pub-practice" amountCents={5000} payPath="/api/x/pay/"
      onDone={done} form={{ kind: "collect", script_url: VAULTIX }} />);
    const { tag, seen } = await loadScript();
    expect(tag.src).toBe(VAULTIX);
    expect(tag.dataset.tokenizationKey).toBe("pub-practice");
    expect(tag.dataset.variant).toBe("inline");
    await waitFor(() => expect(seen.config).toBeDefined());
    const fields = seen.config!.fields as Record<string, { selector: string }>;
    for (const f of ["ccnumber", "ccexp", "cvv"])
      expect(document.querySelector(fields[f].selector)).not.toBeNull();
    const pay = screen.getByRole("button", { name: "Pay $50.00" });
    expect(pay).toBeDisabled();                       // until the fields are there
    (seen.config!.fieldsAvailableCallback as () => void)();
    await waitFor(() => expect(pay).toBeEnabled());
    await userEvent.click(pay);
    expect(seen.starts).toBe(1);
    await waitFor(() => expect(done).toHaveBeenCalledWith(
      expect.objectContaining({ status: "approved" })));
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ payment_token: "tok-from-collect" });
  });

  it("hands the token to a card being saved, not to a payment", async () => {
    const onToken = vi.fn(async () => true as const);
    render(<NmiCardForm publicKey="pub" amountCents={0} payPath="/api/unused/"
      onDone={() => {}} buttonText="Save this card" onToken={onToken}
      form={{ kind: "collect", script_url: VAULTIX }} />);
    const { seen } = await loadScript();
    await waitFor(() => expect(seen.config).toBeDefined());
    (seen.config!.fieldsAvailableCallback as () => void)();
    await userEvent.click(await screen.findByRole("button", { name: "Save this card" }));
    await waitFor(() => expect(onToken).toHaveBeenCalledWith("tok-from-collect"));
  });

  it("says so when the processor does not answer", async () => {
    render(<NmiCardForm publicKey="pub" amountCents={100} payPath="/api/x/pay/"
      onDone={() => {}} form={{ kind: "collect", script_url: VAULTIX }} />);
    const { seen } = await loadScript();
    await waitFor(() => expect(seen.config).toBeDefined());
    (seen.config!.timeoutCallback as () => void)();
    expect(await screen.findByText(/did not answer/)).toBeInTheDocument();
  });
});

const OPEN: PortalInvoice = {
  id: "a", number: "INV-0007", issue_date: "2026-10-01", due_date: "2026-10-16",
  total_cents: 680000, balance_cents: 580000, status: "sent", status_label: "Sent",
  overdue: false, pay_url: "", can_pay: false, pay_paused: true,
  payment_in_progress: false, test_mode: false };

describe("card payments paused (2026-11-10)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the words where Pay would be, and no Pay", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-invoices/": [OPEN],
                                     "GET /api/portal-autopay/": { status: 403, body: {} } }));
    renderRoute(<ClientInvoices />);
    expect(await screen.findByText(PAYMENTS_PAUSED)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pay invoice/ })).toBeNull();
  });

  it("offers no card to save on auto-pay", async () => {
    const state: AutopayState = { ready: true, paused: true, test_mode: false, public_key: "",
      card: null, autopay: null, wording: "", wording_version: "1" };
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-autopay/": state }));
    renderRoute(<ClientAutopay />);
    expect(await screen.findByText(PAYMENTS_PAUSED)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save a card" })).toBeNull();
  });

  it("offers no card and no Pay now on the practice's subscription", async () => {
    const state: SubscriptionState = { status: "past_due", status_label: "Past due",
      not_billed: false, plan: "Micro practice", amount_cents: 19900, billing_email: "",
      card: { brand: "Visa", last4: "1111", expires: "10/29" }, next_charge_on: null,
      public_key: "", test_mode: false, suspended: false, open_cents: 19900, invoices: [],
      paused: true };
    vi.stubGlobal("fetch", mockApi({ "GET /api/subscription/": state }));
    renderRoute(<YourSubscription />);
    expect(await screen.findByText(PAYMENTS_PAUSED)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pay now/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replace the card" })).toBeNull();
  });

  it("lets the platform owner pause and resume them", async () => {
    const base = { changed_at: null, live_calls: true, environment: "live",
                   api_host: "secure.vaultixpay.com", card_form: "collect" };
    const fetchMock = mockApi({
      "GET /api/platform/card-payments/": { ...base, paused: "", held: false, changed_by: "" },
      "POST /api/platform/card-payments/": (body: unknown) => ({ body: {
        ...base, paused: (body as { paused: boolean }).paused ? "held" : "",
        held: (body as { paused: boolean }).paused, changed_by: "Bryan Baker" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<CardPaymentsSwitchCard />);
    expect(await screen.findByText("Taking card payments")).toBeInTheDocument();
    expect(screen.getByText("secure.vaultixpay.com")).toBeInTheDocument();
    expect(screen.getByText(/Collect\.js/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pause card payments" }));
    expect(await screen.findByText("Card payments are paused")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ paused: true });
    await userEvent.click(screen.getByRole("button", { name: "Resume card payments" }));
    expect(await screen.findByText("Taking card payments")).toBeInTheDocument();
  });
});
