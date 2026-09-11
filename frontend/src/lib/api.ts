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
  pipeline_positions: PipelinePosition[];
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
  domains?: string[];
  address?: { lines?: string[] } | null;
  is_client_company: boolean;
  seat_count: number | null;
  seats_in_use: number;
  seats_available: number;
  primary_contact: string | null;
}

export type StageSemantic =
  | "entry" | "working" | "qualified" | "won" | "lost" | "parked" | "none";

export interface Stage {
  id: string;
  pipeline: string;
  code: string;
  label: string;
  /** What the stage MEANS. Behaviour keys on this, never on the label. */
  semantic: StageSemantic;
  position: number;
  is_terminal: boolean;
}

export interface ContactType {
  id: string;
  code: string;
  label: string;
  position: number;
}

export interface Pipeline {
  id: string;
  name: string;
  kind: "sales" | "referral" | "custom";
  position: number;
  stages: Stage[];
  contact_count: number;
}

export interface BoardColumn {
  stage: Stage;
  count: number;
  contacts: Contact[];
}

export interface Board {
  pipeline: Pipeline;
  columns: BoardColumn[];
}

/** Where a contact sits in ONE pipeline. A contact may have several. */
export interface PipelinePosition {
  pipeline: string;
  pipeline_name: string;
  pipeline_kind: string;
  stage: string;
  stage_code: string;
  stage_label: string;
  semantic: StageSemantic;
  entered_at: string;
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
  body_html: string;
  attachments: {
    id: string;
    filename: string;
    byte_size: number;
    content_type: string;
    /** False when the row exists but its bytes do not (FR-1.23b); null when
     *  storage could not be reached to check. */
    content_present: boolean | null;
  }[];
  /** Verified send-as addresses this draft may go from (FR-1.15c). */
  sender_options: { value: string; address: string; label: string }[];
  /** Where this WILL go, decided before approval (FR-0.7). */
  delivery: {
    target: "real" | "dev";
    label: string;
    is_local_build: boolean;
    detail?: string;
  };
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

export interface ImportPreview {
  first_name: string;
  last_name: string;
  email: string;
  company: string;
  title: string;
  phones: { number: string; is_primary: boolean }[];
  tags: string[];
  type_value: string;
  stage_value: string;
  contact_type: string;
  contact_type_label: string;
  /** One entry per pipeline this row will be placed in — there may be two. */
  placements: {
    pipeline: string;
    stage: string;
    stage_code: string;
    semantic: StageSemantic;
    from_column: string;
    fires_client_invariant: boolean;
  }[];
  value_ignored: boolean;
  /** FR-1.6a — this row will also add the client type and flag the company. */
  fires_client_invariant: boolean;
  note: string;
}

export interface ImportRow {
  id: string;
  row_number: number;
  raw: Record<string, string>;
  outcome: string;
  error_text: string;
  preview?: ImportPreview;
}

/** One rule in the value-mapping sub-step. */
export interface ValueRule {
  contact_type?: string;
  /** Pipeline id. A pipeline_stage block names it once for the whole column. */
  pipeline?: string;
  /** Stage code within that pipeline. */
  stage?: string;
  ignore?: boolean;
}

/** One value-mapped column: contact_type or pipeline_stage. */
export interface ValueBlock {
  column: string;
  pipeline?: string;
  values: Record<string, ValueRule>;
}

export interface ValueScan {
  targets: {
    target: "contact_type" | "pipeline_stage";
    column: string;
    values: { value: string; count: number }[];
  }[];
  contact_types: { code: string; label: string }[];
  pipelines: Pipeline[];
}

export interface MappingProfile {
  id: string;
  name: string;
  mapping: Record<string, string>;
  value_mapping: Record<string, ValueBlock>;
  updated_at: string;
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

export interface SendAsEntry {
  address: string;
  verification_status: string;
  is_primary: boolean;
  is_default: boolean;
  is_alias: boolean;
}

export interface GmailStatus {
  connected: boolean;
  email_address: string;
  scopes: string[];
  connected_at: string | null;
  tier2_enabled: boolean;
  /** The tenant's send-as alias — what every app message must come From. */
  alias: string;
  alias_verified: boolean;
  alias_verified_at: string | null;
  alias_listed: boolean;
  send_as: SendAsEntry[];
  send_as_error: string;
  is_sending_connection: boolean;
  transport: string;
  transport_label: string;
  practice_sending: { ok: boolean; detail: string; account: string };
  oauth_configured: boolean;
  /** FR-0.7 — gates the dev-only allow-list section. */
  is_local_build: boolean;
  verify_error?: string;
}

/** Module 2. A locked note the viewer has not unlocked arrives as a stub:
 *  the fields below `created_at` are absent, not empty (FR-2.11). */
export interface NoteLinks {
  contact: string | null; contact_name: string;
  company: string | null; company_name: string;
  task: string | null; task_title: string;
}

export interface NoteStub extends NoteLinks {
  id: string;
  title: string;
  is_locked: boolean;
  unlocked: boolean;
  stub: true;
  created_at: string;
  can_reset_pin: boolean;
}

export type TranscriptionState = "none" | "uploading" | "transcribing" | "done" | "failed";
export type SummaryState = "none" | "drafting" | "proposed" | "accepted" | "discarded" | "failed";

export interface NoteFull extends Omit<NoteStub, "stub"> {
  stub: false;
  title_is_auto: boolean;
  body: string;
  source: "manual" | "import" | "recording";
  created_by: string | null;
  created_by_name: string;
  updated_at: string;
  has_audio: boolean;
  audio_duration_seconds: number | null;
  transcription_state: TranscriptionState;
  transcription_error: string;
  /** Speech-to-Text finished and heard nothing — its own outcome, with its own help. */
  no_speech: boolean;
  transcript: string | null;
  summary_state: SummaryState;
  proposed_summary: string | null;
  summary: string | null;
  can_review_summary: boolean;
  retention_overdue: boolean;
}

export type Note = NoteStub | NoteFull;

export interface NotesSettings {
  audio_retention_days: number;
  max_recording_seconds: number;
  warn_at_seconds: number;
}

export interface Task {
  id: string; title: string; description: string; status: string;
  due_date: string | null; owner: string | null; contact: string | null;
}
