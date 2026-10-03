import { useQuery } from "@tanstack/react-query";
import { ReactNode, useEffect } from "react";
import { useParams } from "react-router-dom";

import { api } from "../lib/api";
import { Branding, setFavicon } from "../lib/branding";
import { applyPortalTokens } from "../lib/palette";

/**
 * A page reached from an emailed link, with no session (P2, owner
 * 2026-10-02). The link's own token names the practice, so the page asks for
 * that practice's branding through it and switches the tab from the product's
 * icon to the practice's mark, the title to its name, and the colors to its own.
 */
export function LinkBranded({ kind, children }: {
  kind: "cadence" | "precall" | "unsubscribe"; children: ReactNode;
}) {
  const { token = "" } = useParams();
  const via = `${kind}:${token}`;
  const { data: brand } = useQuery<Branding>({
    queryKey: ["branding", via],
    queryFn: () => api.get<Branding>(`/api/branding?via=${encodeURIComponent(via)}`),
    enabled: !!token,
    retry: false,
  });

  useEffect(() => {
    if (!brand?.display_name) return;
    applyPortalTokens(document.documentElement,
      { primary: brand.palette.header, accent: brand.palette.accent });
    setFavicon(brand.mark_url);
    document.title = brand.display_name;
  }, [brand]);

  return <>{children}</>;
}
