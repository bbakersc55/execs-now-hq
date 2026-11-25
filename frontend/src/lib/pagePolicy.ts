/**
 * Which content security policy this page was served with, and keeping it
 * right while moving around inside the app (docs/p16_card_page_scripts.md).
 *
 * The server serves every page of the app with the card policy (scripts from
 * ENHQ and the gateway only), except the bank pages, which add Plaid's one
 * script (apps/cardpages/policy.py, BANK_PATHS: the same list as below). A
 * page's policy holds for as long as the page does, and moving inside the app
 * never asks the server again. So moving from a card-policy page to a bank
 * page, or back, reloads the page, and the server serves the other policy. A
 * card form shows only on a card-policy page with no script from anywhere
 * else on it (`cardFormRefusal`); Plaid loads only on a bank page.
 */
import { useEffect } from "react";

export type PagePolicy = "card" | "bank";

/** The bank pages: where "Connect a bank" opens Plaid. */
export const BANK_PATHS = ["/finance/import", "/finance/personal/import", "/settings/finance"];

/** The gateway's script addresses a card page may carry (Collect.js). */
export const GATEWAY_SCRIPT_HOSTS = ["secure.nmi.com", "secure.vaultixpay.com"];

export function policyForPath(path: string): PagePolicy {
  const clean = "/" + path.replace(/^\/+|\/+$/g, "");
  return BANK_PATHS.includes(clean) ? "bank" : "card";
}

/** The policy the server says it served this page with; null where no
 *  server said (the laptop's dev server, a test). */
export function documentPolicy(): PagePolicy | null {
  const value = document.querySelector('meta[name="enhq-page-policy"]')?.getAttribute("content");
  return value === "card" || value === "bank" ? value : null;
}

const RELOADED = "enhq-page-policy-reloaded";

/** How the page is reloaded or sent elsewhere; tests put a stand-in here. */
export const navigation = {
  reload: () => window.location.reload(),
  assign: (url: string) => window.location.assign(url),
};

/** Reload this page so the server serves `path`'s policy, once: a second
 *  try for the same address is refused, and false says so. */
export function reloadForPolicy(path: string, go: () => void = () => navigation.reload()):
  boolean {
  try {
    if (sessionStorage.getItem(RELOADED) === path) return false;
    sessionStorage.setItem(RELOADED, path);
  } catch {
    /* no storage: reload anyway, the server is right about the address */
  }
  go();
  return true;
}

function settled() {
  try { sessionStorage.removeItem(RELOADED); } catch { /* nothing to clear */ }
}

/** In the app's root: whenever the address changes, the page's policy must
 *  be the address's, or the page is reloaded. */
export function usePagePolicy(pathname: string) {
  useEffect(() => {
    const served = documentPolicy();
    if (served === null) return;
    if (served === policyForPath(pathname)) settled();
    else reloadForPolicy(pathname);
  }, [pathname]);
}

/** A script element's address that may be on a card page: ENHQ's own, or
 *  the gateway's Collect.js. */
export function allowedOnCardPage(src: string, origin = window.location.origin): boolean {
  let url: URL;
  try { url = new URL(src, origin); } catch { return false; }
  if (url.origin === origin) return true;
  return url.protocol === "https:" && GATEWAY_SCRIPT_HOSTS.includes(url.host)
    && url.pathname === "/token/Collect.js";
}

/** Why a card form may not show on this page, or "" when it may. */
export function cardFormRefusal(production = import.meta.env.PROD): string {
  const served = documentPolicy();
  if (served === null && production)
    return "This page was not served with the card page policy.";
  if (served === "bank") return "This page allows a script that card pages don't.";
  const others = Array.from(document.scripts).map((s) => s.src)
    .filter((src) => src && !allowedOnCardPage(src));
  if (others.length) return `A script from elsewhere is on this page: ${others.join(", ")}`;
  return "";
}

/** Where to reload to when a card form may not show here: this address if it
 *  is a card page's, else the app's start (a suspended practice's owner sees
 *  the subscription card on every address). */
export function cardPageAddress(): string {
  return policyForPath(window.location.pathname) === "card" ? window.location.href : "/";
}

/** Plaid may load only on a bank page. */
export function plaidRefusal(): string {
  return documentPolicy() === "card"
    ? "The bank's sign-in opens on the Import page or in Settings, Finance." : "";
}
