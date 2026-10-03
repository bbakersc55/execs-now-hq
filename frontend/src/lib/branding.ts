import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

/** /api/branding: the practice's name, colors and images, and (staff only)
 *  the product's name. A client is never told the product's name. */
export interface Branding {
  display_name: string;
  logo_url: string;
  palette: { header: string; accent: string; gray_dark: string; gray_light: string };
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
