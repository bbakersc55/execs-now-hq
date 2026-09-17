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
    throw Object.assign(new Error(refusal(response, data)), { status: response.status, data });
  }
  return data as T;
}

/** The server's own words. DRF puts a field refusal under the field's name
 *  rather than `detail`, which used to surface as a bare "400 Bad Request". */
function refusal(response: Response, data: unknown): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) return record.detail;
    const said = Object.values(record).flat().filter((v): v is string => typeof v === "string");
    if (said.length) return said.join(" ");
  }
  return `${response.status} ${response.statusText}`;
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
  /** True only on a localhost build: gates the development-only controls. */
  dev_tools?: boolean;
  /** FR-3.42 — set while the real person acts as another user. Everything
   *  above then describes the acted-as user. */
  acting?: Acting | null;
}

export interface Acting {
  real_name: string; real_email: string; real_role: string;
  as_membership: string; as_name: string; as_email: string; as_role: string;
  company: string; company_name: string;
}

/** GET /api/act-as/candidates/ — who the real person may act as. */
export interface ActAsCandidate {
  membership: string; name: string; email: string; role: string;
  company: string; company_name: string;
}

/** GET /api/activity/ — the practice's feed across every account. */
export const ACTIVITY_CATEGORIES = [
  "work", "comment", "note", "email", "pipeline",
  "import", "portal", "act_as", "digest", "settings",
] as const;

export type ActivityCategory = (typeof ACTIVITY_CATEGORIES)[number];

/** The practice's feed. Client roles are refused the endpoint outright. */
export interface ActivityEntry {
  id: string; at: string; category: ActivityCategory; kind: string; text: string;
  entity: { type: string; id: string; title: string } | null;
  company: { id: string; name: string } | null;
  contact: { id: string; name: string } | null;
  /** The person who did it. With `on_behalf_of`, the real person acting as them. */
  by: string; on_behalf_of: string | null;
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
  /** Matrix 9.5 — absent for a VA: seat usage is the FF's and an assigned CF's. */
  seats_in_use?: number;
  seats_available?: number;
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

export type WorkStatus =
  | "not_started" | "in_progress" | "blocked" | "waiting_on_client" | "done" | "cancelled";

export interface Person { id: string | null; name: string }

/** /api/portal-people/ — for a client user, only their own company's users. */
export interface PortalPerson { id: string; name: string; role: string; company: string | null }

/** Module 3. `may_edit` / `may_delete` carry FR-3.9a, so the UI never
 *  re-derives the client-edit rule and cannot drift from the server. */
export interface Task {
  id: string;
  title: string;
  description: string;
  status: WorkStatus;
  priority: number;
  priority_label: string;
  due_date: string | null;
  project: string | null;
  project_title: string;
  goal: string | null;
  goal_title: string;
  client_company: string | null;
  client_company_name: string;
  owner: Person;
  assignee: Person;
  client_owner_contact: Person;
  contact: string | null;
  is_client_visible: boolean;
  created_by_client: boolean;
  created_at: string;
  updated_at: string;
  may_edit: boolean;
  may_delete: boolean;
  may_set_visibility: boolean;
}

/** A goal or a project. `status` is what to show; `status_override` is what a
 *  person set by hand, and `status_is_derived` says which you are looking at. */
export interface WorkParent {
  id: string;
  kind: "goal" | "project";
  title: string;
  description: string;
  status: WorkStatus;
  status_override: WorkStatus | null;
  status_is_derived: boolean;
  client_company: string | null;
  client_company_name: string;
  owner: Person;
  client_owner_contact: Person;
  target_date: string | null;
  created_at: string;
  goal?: string | null;
  goal_title?: string;
  start_date?: string | null;
  created_by_client?: boolean;
}

export interface WorkComment {
  /** FR-3.42 — the real person, when written while acting as `author`. */
  acting_user?: Person | null;
  id: string; body: string; visibility: "internal" | "shared";
  author: Person; created_at: string;
  task: string | null; project: string | null; goal: string | null;
}

export interface ChecklistItem { id: string; text: string; is_done: boolean; position: number }

export interface TaskUpdateRow {
  id: string; kind: string; from_value: string; to_value: string;
  client_facing_line: string; actor: Person; source: string;
  /** FR-3.42 — the real person, when written while acting as `actor`. */
  acting_user?: Person | null;
  is_client_actor: boolean; created_at: string;
}

export interface Stakeholder {
  id: string; contact: Person; cadence: "every_update" | "weekly" | "monthly";
  is_muted: boolean; level: "task" | "project" | "goal"; attached_to: string;
  effective: boolean; last_notified_at: string | null;
}

export interface DigestRow {
  id: string; contact: Person; to_address: string;
  cadence: "every_update" | "weekly" | "monthly";
  state: "pending" | "approved" | "sent" | "expired" | "skipped";
  is_ai_generated: boolean; is_stale: boolean; stale_reason: string;
  period_start: string; period_end: string; send_window_at: string;
  generated_at: string; approved_by: Person; approved_at: string | null;
  item_count: number; body_text: string; body_html?: string;
}

/** GET /api/stakeholders/candidates/ — who "Who hears about this" offers. */
export interface StakeholderCandidates {
  company: string | null; company_name: string; outside: boolean;
  people: { contact: string; name: string; email: string; company_name: string;
            is_practice: boolean }[];
}

/** GET /api/digests/upcoming/ — every-update content waiting on its quiet window. */
export interface UpcomingDigest {
  contact: Person; cadence: "every_update"; update_count: number; tasks: string[];
  last_change_at: string; generates_at: string;
  /** The window has closed; the next tick generates it. */
  due: boolean;
}

/** GET /api/digests/tick-status/ — is the scheduled tick running? */
export interface TickStatus {
  last_success_at: string | null; last_failure_at: string | null; last_failure: string;
  stale: boolean; stale_after_minutes: number;
}

export interface PortalAccess {
  company: string; seat_count: number | null; seats_in_use: number;
  seats_available: number | null; may_manage: boolean;
  people: { id: string; role: string; email: string; name: string;
            contact: string | null; invited_at: string | null }[];
}

/** Who may be granted portal access, and for anyone who may not, the reason. */
export interface PortalCandidates {
  company: string | null;
  company_name: string | null;
  is_client_company: boolean;
  seat_count: number | null;
  seats_in_use: number;
  /** Set when the company itself blocks a grant: no seats allocated, or none free. */
  seat_refusal: string | null;
  people: { contact: string; name: string; email: string; title: string;
            role: string; refusal: string | null }[];
}

export interface ProgressReport {
  since: string; until: string; body_text: string; updates: TaskUpdateRow[];
}
