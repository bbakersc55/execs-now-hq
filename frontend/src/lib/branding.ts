/// <reference types="vite/client" />
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

/** /api/branding: the practice's name, colors and images, and (staff only)
 *  the product's name. A client is never told the product's name. */
export interface Branding {
  display_name: string;
  logo_url: string;
  /** The practice's mark, or its initials: never the product's (D2). */
  mark_url: string;
  footer_text: string;
  palette: { header: string; accent: string; on_header: string; on_accent: string;
             gray_dark: string; gray_light: string };
  product_name: string | null;
  /** The sign-in page offers "Sign in with Microsoft" (2026-10-27). */
  microsoft_sign_in?: boolean;
}

export function useBranding() {
  return useQuery<Branding>({
    queryKey: ["branding"],
    queryFn: () => api.get<Branding>("/api/branding"),
    retry: false,
  });
}

/** The practice's display name, for text that would otherwise say "your
 *  fractional" (P1, D7). "your practice" until branding has loaded. */
export function usePracticeName(): string {
  return useBranding().data?.display_name || "your practice";
}

/** The product's name, as config/branding.py PRODUCT_NAME has it: for the
 *  alt text of the product's own artwork, where no payload names it. */
export const PRODUCT_NAME = "Execs NOW HQ";

const BRAND = `${import.meta.env.BASE_URL}brand/`;

/** The product's tab icon (scripts/brand/build_brand.py writes it). Staff only. */
export const PRODUCT_FAVICON = `${BRAND}favicon-32.png`;

/** The product's artwork (docs/brand/README.md, owner 2026-11-05). Only on
 *  the surfaces that name the product: the sign-in page with no practice
 *  named, and the Practices area. Never on a practice's or a client's. */
export const PRODUCT_ART = {
  /** Two lines, standard colors: the sign-in page, on white. */
  stacked: `${BRAND}svg/enhq-stacked-standard.svg`,
  /** One line, reversed: the Practices area's dark blue sidebar and bar. */
  lineReversed: `${BRAND}svg/enhq-line-reversed.svg`,
  /** The square alone, reversed: the collapsed sidebar. */
  markReversed: `${BRAND}svg/enhq-mark-reversed.svg`,
};

/** Point the page's icon link at `href`, creating the link if there is none. */
export function setFavicon(href: string) {
  if (!href) return;
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== href) link.setAttribute("href", href);
}
