/** The owner's agreement, by its link's token (apps/agreements/views_public.py). */
import { FormError } from "./api";

export interface Span { t: "text" | "bold" | "term"; v: string; k?: string }
export type Block =
  | { type: "title" | "heading"; text: string }
  | { type: "para"; indent: number; spans: Span[] }
  | { type: "list"; items: { level: number; spans: Span[] }[] }
  | { type: "section_30"; paras: string[] }
  | { type: "owner_section"; lines: ({ note: string } | { fields: { label: string; key: string;
      value: string }[] })[] }
  | { type: "signatures"; signer_name: string; signer_title: string }
  | { type: "page_break" };

export interface Address { street?: string; unit?: string; city?: string; state?: string;
  zip?: string }
export interface Details {
  owner_type?: "person" | "entity"; first_name?: string; last_name?: string;
  entity_name?: string; signer_title?: string; phone?: string; email?: string;
  business_phone?: string;
  mailing?: { street?: string; street2?: string; city?: string; state?: string; zip?: string };
  bedrooms?: string; bathrooms?: string; square_feet?: number | string;
  emergency?: { name?: string; address?: string; phone?: string };
  property_address?: Address;
}

export interface AgreementPage {
  state: "open" | "signed" | "complete";
  number: number; title: string; brand_name: string; first_name: string;
  blocks: Block[];
  terms: { owner_percent: string; manager_percent: string; section_30: string[];
           property_address: string };
  staff_address: Address;
  details: Details;
  prefill: { name: string; email: string; phone: string };
  missing: string[];
  consent: string;
  signed_at: string | null; countersigned_at: string | null;
  onboarding_choice: "" | "now" | "later";
  has_pdf: boolean;
  signer_name: string;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method, credentials: "omit",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!response.ok) {
    const detail = (data as { detail?: string } | null)?.detail;
    throw new FormError(detail || "Something went wrong. Please try again.", response.status);
  }
  return data as T;
}

export function agreementApi(token: string) {
  const base = `/api/fa/${encodeURIComponent(token)}`;
  return {
    pdf: `${base}/pdf`,
    load: () => call<AgreementPage>("GET", base),
    saveDetails: (details: Details) =>
      call<{ details: Details; missing: string[]; blocks: Block[] }>("PATCH", `${base}/details`,
                                                                  { details }),
    sign: (body: { method: "typed" | "drawn"; typed: string; drawn: string; agreed: boolean }) =>
      call<AgreementPage>("POST", `${base}/sign`, body),
    onboarding: (choice: "now" | "later") =>
      call<{ link: string; choice: string }>("POST", `${base}/onboarding`, { choice }),
  };
}
