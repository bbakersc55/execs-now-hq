/** Owner agreements, the staff side (apps/agreements/views.py). */
import type { Block } from "../forms/agreementApi";
import { api } from "./api";

export type { Block };

export interface Address { street?: string; unit?: string; city?: string; state?: string;
  zip?: string }
export interface FeeRow { threshold: string; fee: string }
export interface Terms {
  owner_percent: string; manager_percent: string;
  fees: Record<"winter" | "summer" | "fall", FeeRow>;
  additional_items: string; property_address: Address;
}
export interface StatusStep { key: string; label: string; at: string | null }
export interface AgreementRow {
  id: string; number: number; owner_name: string; owner_email: string; owner_phone: string;
  property: string; status: StatusStep[]; cancelled: boolean; manager_percent: string | null;
  signed_name: string;
}
export interface Program {
  sender: "testing" | "domain"; sender_label: string; sender_domain: string;
  from_address: string; from_name: string; reply_to: string; tested_at: string | null;
  domain_ready: boolean; paused_at: string | null; pause_reason: string; held: number;
  warning: string; signer_id: string | null; signer_name: string; may_edit: boolean;
  may_set_signer: boolean; message?: string;
}
export interface CompanyPage {
  company: { id: string; name: string };
  may_work: boolean; may_edit_access: boolean; is_signer: boolean; may_countersign: boolean;
  program: Program; defaults: Terms; agreements: AgreementRow[];
}
export interface Authority {
  id: string; principal: string; recorded_by: string; recorded_at: string; recorded_on: string;
  people: { user_id: string; name: string }[]; method: "typed" | "drawn"; typed: string;
  wording: string;
}
export interface AgreementDetail extends AgreementRow {
  company_id: string; company_name: string; template: string; version: number | null;
  terms: Terms; terms_shown: Terms; details: Record<string, unknown>;
  address_changed: boolean; staff_address: string; owner_address: string;
  editable: boolean; may_work: boolean; may_countersign: boolean;
  countersign_as: "" | "signer" | "authorized"; authority: Authority | null;
  /** The exact words agreed when countersigning, from the server. */
  countersign_words: string;
  signer_name: string; signer_block: string;
  /** Ticked "Receives signed PDFs": may download the words the owner signed. */
  may_download_text: boolean;
  owner_signature: { name: string; at: string; ip: string | null; method: string } | null;
  manager_signature: { name: string; applied_by: string; under_authority: boolean;
                       authority_by: string; at: string; ip: string | null } | null;
  agreement_date: string | null; has_owner_pdf: boolean; has_final_pdf: boolean;
  contract: { contract_id: number | null; name: string; flag: string };
  intake: { id: string; number: number; status: string; may_open: boolean } | null;
  events: { kind: string; detail: string; at: string; by: string }[];
  emails: { kind: string; to: string; state: string; at: string; error: string }[];
  sender: "testing" | "domain";
  blocks: Block[];
  link?: string;
}
export interface AccessRow {
  user_id: string; name: string; role: string; practice_owner: boolean;
  agreements?: boolean; signed_pdfs?: boolean; intake?: boolean;
}
export interface AccessPage {
  company: { id: string; name: string };
  /** Which ticks are shown: what is switched on for the company. */
  columns: { agreements: boolean; signed_pdfs: boolean; intake: boolean };
  rows: AccessRow[];
}
export interface AuthorityPage {
  is_signer: boolean; signer_name: string; signer_title: string;
  authority: Authority | null;
  people: { user_id: string; name: string; role: string }[];
  wording: string;
}
export interface AgreementDocument {
  id: string; title: string; owner: string; property: string; date: string | null; pdf: string;
  /** The words the owner signed, as text; "" unless ticked for signed PDFs. */
  text: string;
}

const base = "/api/agreements";
export const agreements = {
  companies: () => api.get<{ companies: { id: string; name: string }[] }>(`${base}/companies`),
  company: (id: string) => api.get<CompanyPage>(`${base}/companies/${id}`),
  create: (id: string, body: { name: string; email: string; phone: string; terms: Terms }) =>
    api.post<AgreementDetail>(`${base}/companies/${id}/agreements`, body),
  preview: (id: string, terms: Terms) =>
    api.post<{ blocks: Block[]; terms: Terms }>(`${base}/companies/${id}/preview`, { terms }),
  get: (id: string) => api.get<AgreementDetail>(`${base}/${id}`),
  update: (id: string, body: Partial<{ name: string; email: string; phone: string;
    terms: Terms }>) => api.patch<AgreementDetail>(`${base}/${id}`, body),
  action: (id: string, action: "send" | "link" | "cancel") =>
    api.post<AgreementDetail>(`${base}/${id}/${action}`),
  countersign: (id: string, body: { agreed: boolean; method?: string; typed?: string;
    drawn?: string }) => api.post<AgreementDetail>(`${base}/${id}/countersign`, body),
  pdfUrl: (id: string, which: "owner" | "final" | "preview") => `${base}/${id}/pdf?which=${which}`,
  access: (id: string) => api.get<AccessPage>(`${base}/companies/${id}/access`),
  saveAccess: (id: string, rows: AccessRow[]) =>
    api.put<AccessPage>(`${base}/companies/${id}/access`, { rows }),
  signedTextUrl: (id: string) => `${base}/${id}/signed-text`,
  settings: (id: string) => api.get<Program>(`${base}/companies/${id}/settings`),
  saveSettings: (id: string, body: Record<string, unknown>) =>
    api.put<Program>(`${base}/companies/${id}/settings`, body),
  settingsAction: (id: string, action: "test" | "resume") =>
    api.post<Program>(`${base}/companies/${id}/settings`, { action }),
  authority: (id: string) => api.get<AuthorityPage>(`${base}/companies/${id}/authority`),
  record: (id: string, body: { method: string; typed: string; drawn: string; people: string[];
    agreed: boolean }) => api.post<AuthorityPage>(`${base}/companies/${id}/authority`, body),
  withdraw: (id: string) => api.del<AuthorityPage>(`${base}/companies/${id}/authority`),
  documents: (id: string) =>
    api.get<{ documents: AgreementDocument[] }>(`${base}/companies/${id}/documents`),
};

export const PERIODS: { key: "winter" | "summer" | "fall"; label: string }[] = [
  { key: "winter", label: "December 1 – March 31" },
  { key: "summer", label: "April 1 – July 31" },
  { key: "fall", label: "August 1 – November 30" },
];

/** The furthest step reached, for the one status line per owner. */
export function stage(row: AgreementRow): string {
  if (row.cancelled) return "Cancelled";
  const reached = row.status.filter((s) => s.at);
  return reached.length ? reached[reached.length - 1].label : "Not sent yet";
}
