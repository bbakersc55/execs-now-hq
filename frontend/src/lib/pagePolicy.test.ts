/** P16: the page's policy follows the address; card forms only on card
 *  pages; Plaid only on bank pages (docs/p16_card_page_scripts.md). */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadPlaidLink } from "../components/BankConnections";
import {
  allowedOnCardPage, cardFormRefusal, cardPageAddress, documentPolicy, navigation,
  plaidRefusal, policyForPath, reloadForPolicy, usePagePolicy,
} from "./pagePolicy";

export function servedAs(kind: "card" | "bank" | null) {
  document.querySelector('meta[name="enhq-page-policy"]')?.remove();
  if (kind === null) return;
  const meta = document.createElement("meta");
  meta.name = "enhq-page-policy";
  meta.content = kind;
  document.head.appendChild(meta);
}

describe("the page's policy", () => {
  let reloads: number;
  beforeEach(() => {
    reloads = 0;
    vi.spyOn(navigation, "reload").mockImplementation(() => { reloads += 1; });
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    servedAs(null);
    document.querySelectorAll("script[data-test]").forEach((s) => s.remove());
  });

  it("knows the bank pages, with or without a closing slash", () => {
    expect(policyForPath("/finance/import")).toBe("bank");
    expect(policyForPath("/finance/personal/import/")).toBe("bank");
    expect(policyForPath("/settings/finance")).toBe("bank");
    for (const path of ["/", "/invoices", "/pay/abc", "/settings/billing", "/finance",
                        "/finance/importer", "/settings/finance/x"])
      expect(policyForPath(path)).toBe("card");
  });

  it("reads what the server says it served", () => {
    expect(documentPolicy()).toBeNull();
    servedAs("bank");
    expect(documentPolicy()).toBe("bank");
  });

  it("reloads when the address needs the other policy, once per address", () => {
    servedAs("card");
    const { rerender } = renderHook(({ path }) => usePagePolicy(path),
      { initialProps: { path: "/invoices" } });
    expect(reloads).toBe(0);
    rerender({ path: "/finance/import" });                 // moved inside the app
    expect(reloads).toBe(1);
    // The reloaded page: had the server served the card policy again, the
    // app would not reload in a loop.
    renderHook(() => usePagePolicy("/finance/import"));
    expect(reloads).toBe(1);
    expect(reloadForPolicy("/finance/import")).toBe(false);
    // Served right, it settles, and a later move may reload again.
    servedAs("bank");
    renderHook(() => usePagePolicy("/finance/import"));
    servedAs("card");
    expect(reloadForPolicy("/finance/import")).toBe(true);
    expect(reloads).toBe(2);
  });

  it("leaves the laptop's dev server alone (no policy said)", () => {
    renderHook(() => usePagePolicy("/finance/import"));
    expect(reloads).toBe(0);
  });

  it("lets a card form show only on a card page with nothing from elsewhere", () => {
    servedAs("card");
    expect(cardFormRefusal(true)).toBe("");
    const collect = document.createElement("script");
    collect.src = "https://secure.vaultixpay.com/token/Collect.js";
    collect.dataset.test = "1";
    document.head.appendChild(collect);
    expect(cardFormRefusal(true)).toBe("");
    const plaid = document.createElement("script");
    plaid.src = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
    plaid.dataset.test = "1";
    document.head.appendChild(plaid);
    expect(cardFormRefusal(true)).toMatch(/A script from elsewhere is on this page: .*plaid/);
    plaid.remove();
    servedAs("bank");
    expect(cardFormRefusal(true)).toMatch(/allows a script that card pages don't/);
    servedAs(null);
    expect(cardFormRefusal(true)).toMatch(/not served with the card page policy/);
    expect(cardFormRefusal(false)).toBe("");               // the laptop's dev server
  });

  it("allows ENHQ's own scripts and the gateway's Collect.js, nothing else", () => {
    const here = "https://app.example.test";
    expect(allowedOnCardPage("/static/assets/index-A.js", here)).toBe(true);
    expect(allowedOnCardPage("https://secure.nmi.com/token/Collect.js", here)).toBe(true);
    expect(allowedOnCardPage("https://secure.nmi.com/token/other.js", here)).toBe(false);
    expect(allowedOnCardPage("http://secure.nmi.com/token/Collect.js", here)).toBe(false);
    expect(allowedOnCardPage("https://evil.example.test/token/Collect.js", here)).toBe(false);
  });

  it("sends a suspended practice's owner on a bank address to a card page", () => {
    window.history.pushState({}, "", "/settings/finance");
    expect(cardPageAddress()).toBe("/");
    window.history.pushState({}, "", "/settings/billing");
    expect(cardPageAddress()).toBe(window.location.href);
  });

  it("never loads Plaid on a card page", async () => {
    servedAs("card");
    expect(plaidRefusal()).toMatch(/Import page or in Settings, Finance/);
    await expect(loadPlaidLink()).rejects.toThrow(/Import page/);
    expect(document.querySelector('script[src*="plaid"]')).toBeNull();
    servedAs("bank");
    expect(plaidRefusal()).toBe("");
  });
});
