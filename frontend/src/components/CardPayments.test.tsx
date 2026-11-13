import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutopayState, PAYMENTS_PAUSED, PortalInvoice, SubscriptionState } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ClientAutopay } from "../screens/ClientAutopay";
import { ClientInvoices } from "../screens/ClientInvoices";
import { YourSubscription } from "../screens/YourSubscription";
import { CardPaymentsSwitchCard } from "./CardPaymentsSwitch";
import { COLLECT_TAG_DATA, FIELDS_WITHIN, FORM_FAILED, NmiCardForm } from "./NmiCardForm";

vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: () => { throw new Error("the Payment Component must not load here"); },
}));

const VAULTIX = "https://secure.vaultixpay.com/token/Collect.js";
const TAG = 'script[src$="/token/Collect.js"]';

/** Collect.js's own list of settings, copied from its Config.js
 *  (`acceptableProperties`, served by secure.nmi.com and
 *  secure.vaultixpay.com alike, 2026-11-13). It builds its configuration
 *  from every data attribute on its script tag and throws, defining nothing,
 *  on any name not in this list. */
const COLLECT_ACCEPTS = [
  "callback", "paymentSelector", "paymentType", "theme", "primaryColor", "secondaryColor",
  "buttonText", "fields", "tokenizationKey", "cartCorrelationId", "source", "variant",
  "styleSniffer", "snifferClass", "customCss", "invalidCss", "validCss", "placeholderCss",
  "token", "validationCallback", "lookUpCallback", "timeoutDuration", "timeoutCallback",
  "focusCss", "googleFont", "fieldsAvailableCallback", "instructionText", "country", "price",
  "currency", "state", "zip", "collectShippingInfo", "collectBillingInfo", "nscript",
  "disableCardValidation", "blockEval"];

/** Collect.js as it behaves: it checks its tag's data attributes as it
 *  starts (and throws, defining nothing, on one it doesn't know), then
 *  configure() takes the fields and the callback, and startPaymentRequest()
 *  hands back a one-time token. */
function fakeCollect(tag: HTMLScriptElement) {
  const seen: { config?: Record<string, unknown>; starts: number; refused?: string } =
    { starts: 0 };
  const extra = Object.keys(tag.dataset).filter((k) => !COLLECT_ACCEPTS.includes(k));
  if (extra.length) {
    seen.refused = `You provided too many fields. Unexpected fields for ${extra.join(",")}`;
    window.dispatchEvent(new ErrorEvent("error", { message: seen.refused }));
    return seen;
  }
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
    const found = document.querySelector<HTMLScriptElement>(TAG);
    expect(found).not.toBeNull();
    return found!;
  });
  const seen = fakeCollect(tag);
  tag.onload?.(new Event("load"));
  return { tag, seen };
}

describe("Collect.js from the white-label host (2026-11-10)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    document.querySelectorAll(TAG).forEach((t) => t.remove());
    delete window.CollectJS;
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("loads Collect.js from the host with the practice's key and posts its token", async () => {
    const fetchMock = mockApi({ "POST /api/x/pay/": { status: "approved", message: "Paid.",
                                                      balance_cents: 0 } });
    vi.stubGlobal("fetch", fetchMock);
    const done = vi.fn();
    render(<NmiCardForm publicKey="pub-practice" amountCents={5000} payPath="/api/x/pay/"
      onDone={done} form={{ kind: "collect", script_url: VAULTIX }} />);
    const { tag, seen } = await loadScript();
    expect(seen.refused).toBeUndefined();
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

  it("puts only settings Collect.js accepts on its script tag (the live failure of 2026-11-13)",
    async () => {
      render(<NmiCardForm publicKey="pub" amountCents={100} payPath="/api/x/pay/"
        onDone={() => {}} form={{ kind: "collect", script_url: VAULTIX }} />);
      const { tag } = await loadScript();
      const names = Object.keys(tag.dataset);
      expect(names.sort()).toEqual([...COLLECT_TAG_DATA].sort());
      for (const name of names) expect(COLLECT_ACCEPTS).toContain(name);
      // No other attribute either: the address and the two settings (and
      // `async`, where the browser writes it as an attribute).
      expect(tag.getAttributeNames().filter((n) => n !== "async").sort())
        .toEqual(["data-tokenization-key", "data-variant", "src"]);
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

describe("a card form that would not load is never silent (2026-11-13)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    document.querySelectorAll(TAG).forEach((t) => t.remove());
    delete window.CollectJS;
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  const SAID = "The card form could not be loaded, so nothing was charged. Northwind has been "
    + "told. Please try again later, or pay another way: Check to PO Box 1.";

  function reporting() {
    const fetchMock = mockApi({ "POST /api/x/form-failed/": { message: SAID } });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }
  const reports = (fetchMock: ReturnType<typeof mockApi>) =>
    fetchMock.calls.filter((c) => c.url === "/api/x/form-failed/");

  it("Collect.js refusing as it starts: the payer reads the practice's words, reported once",
    async () => {
      const fetchMock = reporting();
      render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
        onDone={() => {}} failurePath="/api/x/form-failed/"
        form={{ kind: "collect", script_url: VAULTIX }} />);
      const tag = await waitFor(() => {
        const found = document.querySelector<HTMLScriptElement>(TAG);
        expect(found).not.toBeNull();
        return found!;
      });
      // What the live page saw: the script threw as it started.
      window.dispatchEvent(new ErrorEvent("error", {
        message: "Uncaught Error: You provided too many fields. Unexpected fields for x" }));
      tag.onload?.(new Event("load"));
      expect(await screen.findByRole("alert")).toHaveTextContent(SAID);
      expect(reports(fetchMock)).toHaveLength(1);
      const body = reports(fetchMock)[0].body as Record<string, string>;
      expect(body.form).toBe("collect");
      expect(body.host).toBe("secure.vaultixpay.com");
      expect(body.reason).toMatch(/did not start: .*too many fields/);
      expect(screen.queryByRole("button", { name: /Pay/ })).toBeNull();
    });

  it("the script not fetched at all", async () => {
    const fetchMock = reporting();
    render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
      onDone={() => {}} failurePath="/api/x/form-failed/"
      form={{ kind: "collect", script_url: VAULTIX }} />);
    const tag = await waitFor(() => document.querySelector<HTMLScriptElement>(TAG)!);
    tag.onerror?.(new Event("error"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Northwind has been told");
    expect((reports(fetchMock)[0].body as { reason: string }).reason)
      .toMatch(/could not be fetched/);
  });

  it("configure() refusing the settings", async () => {
    const fetchMock = reporting();
    render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
      onDone={() => {}} failurePath="/api/x/form-failed/"
      form={{ kind: "collect", script_url: VAULTIX }} />);
    const tag = await waitFor(() => document.querySelector<HTMLScriptElement>(TAG)!);
    window.CollectJS = { configure: () => { throw new Error("Invalid theme provided"); },
                         startPaymentRequest: () => {} };
    tag.onload?.(new Event("load"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Northwind has been told");
    expect((reports(fetchMock)[0].body as { reason: string }).reason)
      .toBe("Collect.js refused the form's settings: Invalid theme provided");
  });

  it("fields that never appear count as not loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = reporting();
    render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
      onDone={() => {}} failurePath="/api/x/form-failed/"
      form={{ kind: "collect", script_url: VAULTIX }} />);
    const { seen } = await loadScript();
    await waitFor(() => expect(seen.config).toBeDefined());
    expect(reports(fetchMock)).toHaveLength(0);
    vi.advanceTimersByTime(FIELDS_WITHIN + 10);
    expect(await screen.findByRole("alert")).toHaveTextContent("Northwind has been told");
    expect((reports(fetchMock)[0].body as { reason: string }).reason)
      .toMatch(/did not appear within 20 seconds/);
  });

  it("with no answer from the server the payer still reads what to do", async () => {
    vi.stubGlobal("fetch", mockApi({ "POST /api/x/form-failed/": { status: 500, body: {} } }));
    render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
      onDone={() => {}} failurePath="/api/x/form-failed/"
      form={{ kind: "collect", script_url: VAULTIX }} />);
    const tag = await waitFor(() => document.querySelector<HTMLScriptElement>(TAG)!);
    tag.onerror?.(new Event("error"));
    expect(await screen.findByRole("alert")).toHaveTextContent(FORM_FAILED);
  });

  it("NMI's Payment Component failing to start is reported too", async () => {
    const fetchMock = reporting();
    render(<NmiCardForm publicKey="pub" amountCents={500} payPath="/api/x/pay/"
      onDone={() => {}} failurePath="/api/x/form-failed/" form={{ kind: "component" }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Northwind has been told");
    const body = reports(fetchMock)[0].body as Record<string, string>;
    expect(body.form).toBe("component");
    expect(body.reason).toMatch(/must not load here/);
  });
});

describe("Collect.js is one per page (2026-11-13)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    document.querySelectorAll(TAG).forEach((t) => t.remove());
    delete window.CollectJS;
  });

  it("the form opened last owns it; the earlier one waits and takes it back", async () => {
    function Page({ both }: { both: boolean }) {
      return (
        <>
          <NmiCardForm publicKey="pub" amountCents={0} payPath="/api/a/" onDone={() => {}}
            buttonText="Save this card" onToken={async () => true}
            form={{ kind: "collect", script_url: VAULTIX }} />
          {both && <NmiCardForm publicKey="pub" amountCents={700} payPath="/api/b/"
            onDone={() => {}} form={{ kind: "collect", script_url: VAULTIX }} />}
        </>
      );
    }
    const { rerender } = render(<Page both={false} />);
    const { seen } = await loadScript();
    await waitFor(() => expect(seen.config).toBeDefined());
    const first = (seen.config!.fields as Record<string, { selector: string }>).ccnumber.selector;

    rerender(<Page both />);
    expect(await screen.findByTestId("card-form-waiting")).toHaveTextContent(
      "Another card form is open on this page. Close it to use this one.");
    await waitFor(() => expect((seen.config!.fields as Record<string, { selector: string }>)
      .ccnumber.selector).not.toBe(first));
    expect(screen.getByRole("button", { name: "Pay $7.00" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save this card" })).toBeNull();

    rerender(<Page both={false} />);
    await waitFor(() => expect((seen.config!.fields as Record<string, { selector: string }>)
      .ccnumber.selector).toBe(first));
    expect(screen.queryByTestId("card-form-waiting")).toBeNull();
    expect(screen.getByRole("button", { name: "Save this card" })).toBeInTheDocument();
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
