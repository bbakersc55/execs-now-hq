// Session-cookie auth with CSRF (assumption G2). No tokens anywhere.

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-CSRFToken": csrfToken(),
      ...(isForm || body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: isForm ? (body as FormData) : body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail || `${response.status} ${response.statusText}`;
    throw Object.assign(new Error(detail), { status: response.status, data });
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

export interface Me {
  authenticated: boolean;
  email: string;
  full_name: string;
  role: "FF" | "CF" | "VA" | "FCC" | "ECC" | null;
  tenant: string | null;
  client_company: string | null;
}

export interface Contact {
  id: string;
  first_name: string;
  last_name: string;
  title: string;
  company: string | null;
  owner: string | null;
  stage: string | null;
  stage_code: string | null;
  source: string;
  background: string;
  tags: string[];
  emails: { id: string; address: string; is_primary: boolean }[];
  phones: { id: string; number: string; is_primary: boolean }[];
  type_codes: string[];
  referral_fee_terms: string;
  referral_cadence: string;
  referral_touch_mode: string;
  referral_next_touch_at: string | null;
  referral_onboarded_at: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface Company {
  id: string;
  name: string;
  industry: string;
  is_client_company: boolean;
  seat_count: number | null;
  seats_in_use: number;
  seats_available: number;
  primary_contact: string | null;
}

export interface Stage {
  id: string;
  code: string;
  label: string;
  position: number;
  is_terminal: boolean;
}

export interface OutboxMessage {
  id: string;
  state: string;
  producer: string;
  to_contact: string | null;
  to_address: string;
  from_address: string;
  subject: string;
  body_text: string;
  is_ai_generated: boolean;
  warning: string;
  send_by: string | null;
  sent_at: string | null;
  dev_real_send: boolean;
  created_at: string;
}

export interface ImportBatch {
  id: string;
  filename: string;
  status: string;
  counts: Record<string, number>;
  rolled_back_at: string | null;
  created_at: string;
}

export interface ImportRow {
  id: string;
  row_number: number;
  raw: Record<string, string>;
  outcome: string;
  error_text: string;
}

export interface StaffMember {
  id: string;
  email: string;
  full_name: string;
  role: string;
  invited_at: string | null;
  revoked_at: string | null;
  is_active: boolean;
}
