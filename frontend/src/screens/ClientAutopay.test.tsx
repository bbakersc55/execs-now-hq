import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AutopayState } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ClientAutopay } from "./ClientAutopay";

const mounted: { key: string; text?: string }[] = [];
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: {
    tokenizationKey: string; payButtonText?: string;
    onPay: (e: { token: string }) => Promise<true | string> }) => {
    mounted.push({ key: options.tokenizationKey, text: options.payButtonText });
    const button = document.createElement("button");
    button.textContent = "NMI save";
    button.onclick = () => { void options.onPay({ token: "tok-card" }); };
    box.appendChild(button);
    return { destroy: () => button.remove() };
  },
}));

const NONE: AutopayState = {
  ready: true, test_mode: true, public_key: "pub-practice-key", card: null, autopay: null,
  wording: "I authorize Executives Now to charge the card on file for Acme.",
  wording_version: "2026-10-21" };
const CARD = { brand: "Visa", last4: "1111", expires: "10/29", added_by: "Dana Reyes",
               added_at: "2026-10-21T10:00:00Z" };

describe("the card on file and auto-pay (P4 part 4)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); mounted.length = 0; });

  it("saves a card through NMI's fields with the practice's key", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/portal-autopay/card/": () => ({ status: 200, body: { ...NONE, card: CARD } }),
      "GET /api/portal-autopay/": NONE,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientAutopay />);
    await user.click(await screen.findByRole("button", { name: "Save a card" }));
    await waitFor(() => expect(mounted).toEqual([
      { key: "pub-practice-key", text: "Save this card" }]));
    await user.click(screen.getByRole("button", { name: "NMI save" }));
    expect(await screen.findByText("Visa ending 1111")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { payment_token: "tok-card" });
  });

  it("turns auto-pay on only once the wording is agreed, sending its version", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/portal-autopay/consent/": () => ({ status: 200, body: {
        ...NONE, card: CARD, autopay: { since: "2026-10-21T10:00:00Z", by: "Dana Reyes" } } }),
      "GET /api/portal-autopay/": { ...NONE, card: CARD },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientAutopay />);
    expect(await screen.findByText(/I authorize Executives Now/)).toBeInTheDocument();
    const on = screen.getByRole("button", { name: "Turn auto-pay on" });
    expect(on).toBeDisabled();
    await user.click(screen.getByLabelText("I agree"));
    await user.click(on);
    expect(await screen.findByText("Auto-pay on")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { agree: true, version: "2026-10-21" });
    expect(screen.getByRole("button", { name: "Turn auto-pay off" })).toBeInTheDocument();
  });

  it("shows nothing to a client team member", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-autopay/": () => ({ status: 403, body: {
      detail: "Only a client owner can manage the card on file and auto-pay." } }) }));
    const { container } = renderRoute(<ClientAutopay />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
