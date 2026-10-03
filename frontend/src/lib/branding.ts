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

/** The product's tab icon (manage.py build_favicons writes it). Staff only. */
export const PRODUCT_FAVICON = `${import.meta.env.BASE_URL}brand/favicon-32.png`;

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
