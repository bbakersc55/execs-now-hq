// One place for the site's names, addresses and switches.
export const PRODUCT = "Execs NOW HQ";
export { SITE_URL } from "./site-url.mjs";
export const APP_URL = "https://app.getexecutivesnow.com";
export const CONTACT_EMAIL = "info@execsnowhq.com";
export const LEGAL_ENTITY = "Noble Rose LLC d/b/a Execs NOW HQ";
export const PRACTICE = "Executives Now";
// Which square crop of the headshot /about shows: "a" (head and shoulders)
// or "b" (tighter). Both are in public/about/.
export const HEADSHOT: "a" | "b" = "a";
// GA4 is read at build; with no id set, no analytics script is emitted.
export const GA4_ID = (import.meta.env.PUBLIC_GA4_ID ?? "").trim();
export const DEFAULT_DESCRIPTION =
  "Execs NOW HQ runs a fractional practice in one place, in your brand: CRM, strategy calls, client portal, scorecards, proposals, invoices and books, with nothing sent or decided without you.";
// The privacy policy and terms: approved by Bryan 2026-11-09. While
// LEGAL_DRAFT is true, both are kept out of the sitemap and marked noindex.
export const LEGAL_DRAFT = false;
export const LEGAL_EFFECTIVE = "Effective November 9, 2026";
export const LIMITED_USE =
  "Execs NOW HQ's use and transfer to any other app of information received from Google APIs will adhere to the Google API Services User Data Policy, including the Limited Use requirements.";
