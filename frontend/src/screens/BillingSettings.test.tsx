import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { BillingSettings, PaymentAccountState } from "./BillingSettings";

const NONE: PaymentAccountState = {
  environment: "sandbox", private_key_last4: "", public_key_last4: "", checked_at: null,
  check_ok: null, check_detail: "", ready: false, live_allowed: false, gateway: "nmi",
  pricing_program: "dual_pricing", pricing_program_label: "Dual pricing",
};
const CONNECTED: PaymentAccountState = {
  ...NONE, private_key_last4: "9f2c", public_key_last4: "7Qa1",
  checked_at: "2026-10-21T15:00:00Z", check_ok: true, check_detail: "Connected", ready: true,
};

describe("Settings → Billing (P4 part 1)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says it is not connected, and shows the pricing program read-only", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/payment-account/": NONE }));
    renderRoute(<BillingSettings />);
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("Dual pricing")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Pricing program/)).toBeNull();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled();
  });

  it("sends both keys once, clears them from the page, and shows only their last four",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/payment-account/": NONE,
        "POST /api/payment-account/": () => ({ status: 200, body: CONNECTED }),
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<BillingSettings />);
      await screen.findByText("Not connected");
      await user.type(screen.getByLabelText("Private API key"), "private-test-value");
      await user.type(screen.getByLabelText("Public tokenization key"), "public-test-value");
      await user.click(screen.getByRole("button", { name: "Test and save" }));
      expect(await screen.findByText("Connected")).toBeInTheDocument();
      expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({
        environment: "sandbox", private_key: "private-test-value",
        public_key: "public-test-value" });
      expect(screen.getByLabelText("Private API key")).toHaveValue("");
      expect(screen.getByLabelText("Public tokenization key")).toHaveValue("");
      expect(screen.getByText("…9f2c")).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("private-test-value");
    });

  it("shows NMI's refusal and keeps what was typed", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/payment-account/": NONE,
      "POST /api/payment-account/": () => ({ status: 400, body: {
        detail: "NMI refused the private key. Nothing was changed." } }),
    }));
    renderRoute(<BillingSettings />);
    await screen.findByText("Not connected");
    await user.type(screen.getByLabelText("Private API key"), "wrong");
    await user.type(screen.getByLabelText("Public tokenization key"), "pub");
    await user.click(screen.getByRole("button", { name: "Test and save" }));
    expect(await screen.findByText(/NMI refused the private key/)).toBeInTheDocument();
    expect(screen.getByLabelText("Private API key")).toHaveValue("wrong");
  });

  it("offers live only where live keys are accepted", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/payment-account/": NONE }));
    renderRoute(<BillingSettings />);
    expect(await screen.findByRole("radio", { name: "Live" })).toBeDisabled();
    expect(screen.getByText(/accepted only on the production app/)).toBeInTheDocument();
  });

  it("tests the stored keys again, and says when nothing reaches NMI", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/payment-account/": { ...CONNECTED, gateway: "stub" },
      "POST /api/payment-account/test/": () => ({ status: 200, body: CONNECTED }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<BillingSettings />);
    expect(await screen.findByText(/switched off on this server/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url.includes("/test/"))).toBe(true));
  });
});
