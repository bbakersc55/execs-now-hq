// Session-cookie auth with CSRF (assumption G2). No tokens anywhere.

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * When the person last did something in this tab. Every request says how long
 * ago that was, so a screen that refreshes itself does not keep a staff
 * session alive: 12 hours without a click, a key or a scroll signs them out
 * (UI 3 spec §2a). Loading the page counts as doing something.
 */
let lastActive = Date.now();
if (typeof window !== "undefined") {
  for (const type of ["pointerdown", "keydown", "wheel", "touchstart", "scroll"]) {
    window.addEventListener(type, () => { lastActive = Date.now(); },
                            { capture: true, passive: true });
  }
}

/** Fired when the server says the session is over, so the app can show the
 *  sign-in screen instead of a screen full of refusals. */
export const SIGNED_OUT_EVENT = "enhq:signed-out";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-CSRFToken": csrfToken(),
      "X-Idle-Seconds": String(Math.round((Date.now() - lastActive) / 1000)),
      ...(isForm || body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: isForm ? (body as FormData) : body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (response.status === 401 && path !== "/api/me") {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
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
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

export interface Me {
  authenticated: boolean;
  email: string;
  full_name: string;
  role: "FF" | "CF" | "VA" | "FCC" | "ECC" | null;
  /** What the role is called (P1): never show `role` itself. */
  role_label?: string | null;
  /** P2: may switch to the Practices area. */
  is_platform_owner?: boolean;
  /** P2: "platform" in the Practices area, where no practice is bound. */
  area?: "practice" | "platform";
  /** P2: the platform owner's own practice, for the switch's label. */
  home_practice?: string | null;
  /** P2: a practice owner who has not accepted the beta agreement yet. */
  agreement_required?: boolean;
  tenant: string | null;
  client_company: string | null;
  /** True only on a localhost build: gates the development-only controls. */
  dev_tools?: boolean;
  /** Which of the three environments (owner, 2026-09-29). */
  environment?: "local" | "demo" | "production";
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
  /** Pipeline board only: the company's name, "" when there is none. */
  company_name?: string;
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
  /** On the touch cadence — only ever because someone enrolled them. */
  referral_enrolled?: boolean;
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
  /** Everyone in the stage, whatever is loaded or searched. */
  count: number;
  /** How many of them match the board's search; the same as `count` without one. */
  matched?: number;
  /** The first 100 of those, or all of them once the column is expanded. */
  contacts: Contact[];
}

export interface Board {
  pipeline: Pipeline;
  /** The search the server ran for this answer, "" when it ran none. */
  q?: string;
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

export type MeasurableKind = "numeric" | "qualitative" | "none" | null;

/** A goal or a project. `status` is what to show; `status_override` is what a
 *  person set by hand, and `status_is_derived` says which you are looking at. */
export interface WorkParent {
  id: string;
  kind: "goal" | "project";
  title: string;
  /** Goals, in a list: the place a current goal holds in its company's order
   *  of priority. Null for a historical or an internal goal. */
  priority?: number | null;
  is_historical?: boolean;
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
  /** Module 4B, on a goal only. The Work screen leads with the measure when
   *  there is one, exactly as the value report does (FR-4B.18). */
  measurable_kind?: MeasurableKind;
  kind_is_undecided?: boolean;
  measurable?: string;
  measurable_unit?: string;
  how_we_will_know?: string;
  direction?: "" | "up_is_good" | "down_is_good";
  baseline_value?: string | null;
  baseline_at?: string | null;
  target_value?: string | null;
  horizon_days?: number | null;
  outcome_statement?: string;
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
  /** `late`: reached its send time unapproved. Not sent; still sendable by hand. */
  state: "pending" | "approved" | "late" | "sent" | "expired" | "skipped";
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
            contact: string | null; invited_at: string | null;
            /** Whether they have ever signed in. */
            signed_in: boolean;
            /** When the invitation they still hold runs out (it may have), or
             *  null if they hold none. */
            invitation_expires_at: string | null }[];
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

// --- Module 4B — the client value report ------------------------------------


/** A goal's measure. `kind_is_undecided` is the practice's nudge (FR-4B.6a) and
 *  is never true in a client's response: *not yet decided* is a fact about the
 *  practice's work, not about the engagement. */
export interface GoalMeasure {
  kind: MeasurableKind;
  kind_is_undecided: boolean;
  measurable: string;
  unit: string;
  how_we_will_know: string;
  direction: "" | "up_is_good" | "down_is_good";
  baseline: { value: string | null; at: string | null };
  current: { value: string; at: string; note: string } | null;
  target: string | null;
  movement: "" | "better" | "worse" | "level";
  reading_count: number;
  /** From three readings up, a dated baseline counting as one (ruling D). */
  show_chart: boolean;
  series: { at: string; value: string; is_baseline: boolean; note: string }[];
}

export interface GoalMilestoneRow {
  id: string; title: string; due_date: string | null; occurred_at: string | null;
  state: "hit" | "late" | "ahead" | "due";
  /** What the state is called on screen (P1). */
  state_label: string;
  is_derived: boolean; source_task: string | null;
}

export interface GoalResolutionRow {
  id: string; resolution: string; label: string; reason: string; at: string; by: string;
}

export interface GoalNarrativeRow {
  id?: string;
  state?: "drafting" | "proposed" | "accepted" | "discarded" | "failed";
  /** Absent from a client's response entirely — never merely unrendered. */
  proposed_body?: string;
  body: string;
  accepted_at?: string | null;
  accepted_by?: string;
  version_count?: number;
}

/** A goal a client owner proposed, and the practice's answer. */
export interface GoalProposal {
  id: string; company: string; company_name: string;
  title: string; why: string;
  state: "pending" | "accepted" | "declined"; state_label: string;
  proposed_by: string; proposed_at: string;
  decided_by: string; decided_at: string | null; decision_note: string;
  /** The goal it became, and what the practice called it. */
  goal: string | null; goal_title: string;
}

/** One company's proposed goals. A client owner proposes (`may_propose`); the
 *  practice owner or an assigned associate answers (`may_decide`). */
export interface GoalProposals {
  company: string; may_propose: boolean; may_decide: boolean;
  proposals: GoalProposal[];
}

/** A client's proposed order for their company's goals, and what became of it. */
export interface GoalOrderProposal {
  id: string; company: string; company_name: string;
  state: "pending" | "accepted" | "declined" | "superseded"; state_label: string;
  order: { id: string; title: string }[];
  note: string; proposed_by: string; proposed_at: string;
  decided_by: string; decided_at: string | null; decision_note: string;
}

/** The order of a company's current goals. The practice sets it
 *  (`may_reorder`); a client proposes one (`may_propose`). */
export interface GoalOrder {
  company: string;
  order: { id: string; title: string }[];
  may_reorder: boolean;
  may_propose: boolean;
  proposal: GoalOrderProposal | null;
  last_decided: GoalOrderProposal | null;
}

/** The work under one goal: its projects with their tasks, and the tasks
 *  filed straight on it. */
export interface GoalTree {
  projects: (WorkParent & { tasks: Task[] })[];
  tasks: Task[];
}

export interface GoalBlock {
  id: string;
  title: string;
  client_company: string | null;
  outcome_statement: string;
  /** The product rule, decided on the server: a number leads, or the outcome
   *  statement does. **Never percent-of-tasks-done** (FR-4B.21). */
  /** `none` is a real answer: a goal converted from a map row has nothing
   *  written about it yet, and repeating its title is not a headline. */
  headline: { kind: "measure" | "outcome" | "none"; text: string };
  /** Staff only — what this goal is still waiting for someone to write. */
  awaiting?: string[];
  measure: GoalMeasure;
  completion: { done: number; of: number; percent: number | null };
  status: WorkStatus;
  target_date: string | null;
  horizon_days: number | null;
  client_owner_contact: string;
  is_historical: boolean;
  resolution: GoalResolutionRow | null;
  resolutions: GoalResolutionRow[];
  milestones: GoalMilestoneRow[];
  narrative: GoalNarrativeRow | null;
  source_map_row: string | null;
  measurements?: { id: string; value: string; measured_at: string; note: string;
                   recorded_by: string }[];
}

/** One axis across the whole engagement (FR-4B.36a). Derived at read time. */
export interface EngagementTimeline {
  from: string; to: string; today: string;
  spans: { goal: string; title: string; start: string; end: string;
           is_historical: boolean }[];
  marks: { goal: string; goal_title: string;
           kind: "start" | "milestone" | "reading" | "resolution";
           at: string; label: string; detail: string }[];
}

export interface ValueReport {
  company: { id: string; name: string };
  timeline: EngagementTimeline;
  current: GoalBlock[];
  historical: GoalBlock[];
  generated_at: string;
}

export interface ValueReportExport {
  id: string; goal: string | null; goal_title: string; client_company: string;
  scope: "goal" | "all-goals"; byte_size: number;
  narrative_version: string | null; exported_at: string; exported_by: Person;
}

// --- Module 4 — the strategy session ----------------------------------------

/** `null` is a real value: a rating whose number has not been taken yet
 *  (incident, 2026-09-22). */
export type AnswerValue = Record<string, string | number | boolean | null>;

export interface StrategyQuestion {
  key: string;
  prompt: string;
  prompt_template?: string;
  ask_when: "precall" | "live";
  must_ask: boolean;
  area: string;
  response_schema: "free_text" | "rating_1_10" | "diagnostic_triple" | "value_pair"
    | "agreed_note" | "path_reaction";
  is_fractional_observation: boolean;
  has_fractional_note: boolean;
  is_financial: boolean;
  /** Asked only if the call has time — a muted tag in the live view. */
  ask_if_time?: boolean;
  /** Builder only: still worded exactly as the example it came from. */
  from_example?: boolean;
  position: number;
  /** A builder template's question (P3): its short name, and whether its
   *  answer shows in the PDF header. */
  label?: string;
  pdf_chip?: boolean;
}

/** What a section of a builder template does (P3). */
export type SectionKind = "precall" | "ratings" | "diagnostic" | "mirror" | "map"
  | "values" | "paths" | "scope"
  | "custom";

export interface StrategySection {
  code: string; title: string; position: number;
  time_budget_minutes: number | null;
  questions: StrategyQuestion[];
  /** Only on a builder template's section (P3). */
  kind?: SectionKind;
}

/** GET /api/strategy-templates/ — every template, archived ones last. */
export interface StrategyTemplateRow {
  id: string; name: string; discipline: string; version: number; is_default: boolean;
  archived_at: string | null;
  /** How many sessions were started from it. */
  sessions: number;
  sections: StrategySection[];
  /** Only on a template made in the builder (P3): whether it can start a
   *  session, and what it still needs if not. */
  format?: "v3";
  ready?: boolean;
  missing?: string[];
}

/** A builder template's own text and limits (P3). */
export interface BuilderSettings {
  advisor_role: string; rating_scale: string;
  path_a_title: string; path_a_points: string[];
  path_b_title: string; path_b_points: string[];
  diagnostic_size: number;
}

export interface BuilderSection {
  code: string; kind: SectionKind; title: string; time_budget_minutes: number | null;
  included: boolean; optional: boolean; response_schema: string | null;
  most: number; fixed_count: boolean; questions: StrategyQuestion[];
  /** Only on a section the practice added (P3 part two): whether it prints
   *  on the document, and the kinds of answer its questions may take. */
  custom?: boolean; show_in_pdf?: boolean; schemas?: string[];
}

/** GET /api/strategy-template-builder/<id>/ — one builder template (P3). */
export interface BuilderTemplate {
  id: string; name: string; format: "v3"; is_default: boolean;
  archived_at: string | null; settings: BuilderSettings;
  ready: boolean; missing: string[]; merge_fields: string[];
  sections: BuilderSection[];
  /** Only on a template made from an example (P3 §9): which one, and which
   *  settings are still exactly its own. Each question then carries
   *  `from_example`. Computed by the server on every read, never stored. */
  example?: { start_from: string; version: number; unchanged_settings: string[] };
}

/** POST …/paste/ — "Paste several" (P3 §9.5): the list shown back, each
 *  line fine or refused with why. `added` is empty until it is confirmed. */
export interface PastedLine { prompt: string; label: string; ok: boolean; why: string }
export interface PasteResult {
  section: string; lines: PastedLine[]; adding: number; added: string[]; stale: boolean;
  template: BuilderTemplate;
}

/** The live ones, default first — what the start form and Apply offer. */
export function activeTemplates(all: StrategyTemplateRow[] | undefined) {
  return (all ?? []).filter((t) => !t.archived_at)
    .sort((a, b) => Number(b.is_default) - Number(a.is_default)
      || a.name.localeCompare(b.name));
}

export interface StrategyAnswerRow {
  question_key: string; value: AnswerValue; fractional_note: string;
  answered_by: "prospect" | "fractional"; updated_at: string;
}

export interface MapRow {
  id: string; position: number;
  /** The focused format's card (owner, 2026-09-29): all the PDF shows. */
  header?: string; statement?: string;
  bottleneck: string; root_cause: string; the_fix: string;
  owner_text: string; horizon: number | null; measurable: string; mechanics_note: string;
  state: "proposed" | "accepted" | "discarded";
  converted_to: "" | "goal" | "project";
  from_ai: boolean;
  /** A consolidated row: the rows it merges, as Claude cited them. */
  merged_from?: { id: string; bottleneck: string; state: string }[];
}

/** §8's tray (owner, 2026-09-21). A pro or a con on one of the two paths;
 *  only an accepted one reaches the prospect's PDF. */
export interface PathNote {
  id: string; path: "a" | "b"; kind: "pro" | "con"; text: string;
  position: number; state: "proposed" | "accepted" | "discarded"; from_ai: boolean;
}

/** Session prep (owner, 2026-09-21) — **fractional-only**. It is absent from a
 *  VA's payload entirely, and reaches no prospect surface. */
export interface PrepQuestion {
  id: string; text: string; why: string; position: number;
  is_pinned: boolean; note: string;
}

export interface SessionPrep {
  id: string;
  state: "drafting" | "ready" | "failed";
  website_url: string;
  notes: string;
  summary: string;
  bottlenecks: string[];
  /** One per pre-call question, with today's wording beside it. Never applied
   *  by the app: the fractional copies one into the template editor. */
  rewordings: { key: string; current: string; suggested: string; why: string }[];
  /** Suggestions refused because they would have changed a question's shape. */
  dropped_rewordings?: string[];
  questions: PrepQuestion[];
  web_searches: number;
}

/** What a send panel must show before it will send (incident, 2026-09-22). */
export interface SendPreview {
  subject: string; to_address: string; from_address: string;
  body_text: string; body_html: string;
}

/** A diagnostic question Claude proposed from the pre-call form (focused
 *  template, owner 2026-09-29). Only an accepted one is asked. */
export interface DiagnosticProposal {
  id: string;
  rule: "lowest_rating" | "growth" | "snapshot_gap" | "precall_gap" | "manual";
  rule_label: string;
  basis: string; prompt: string; state: "proposed" | "accepted" | "discarded";
  question_key: string; from_ai: boolean;
}

export interface StrategySessionRow {
  id: string;
  /** classic | focused | v3, frozen with the session's snapshot. */
  format?: "classic" | "focused" | "v3";
  /** A v3 session (P3): the scale line above its ratings, and how many
   *  diagnostic questions it starts with and may hold. */
  rating_scale?: string;
  diagnostic?: { size: number; most: number };
  diagnostic_proposals?: DiagnosticProposal[];
  state: "draft" | "precall_sent" | "precall_complete" | "in_call" | "complete"
    | "converted" | "lost";
  /** What it was started from, as its snapshot records it. */
  template: { id: string | null; name: string };
  /** Session management (owner, 2026-09-26), said by the server so the screen
   *  never offers what the API would refuse. "" means allowed. */
  archived_at?: string | null;
  may_archive?: boolean;
  may_delete?: boolean;
  delete_refusal?: string;
  reset_refusal?: string;
  contact: Person | null;
  company: { id: string; name: string } | null;
  visionary: Person | null;
  integrator: Person | null;
  owner: string;
  scheduled_at: string | null;
  started_at: string | null;
  budget_minutes: number;
  current_section: string;
  current_section_at: string | null;
  precall_sent: boolean;
  precall_expires_at: string | null;
  /** Set when the questions went out in the body of an email instead of as a
   *  link (owner, 2026-09-21). */
  precall_questions_sent_at?: string | null;
  /** The opening line the fractional edits before that send. */
  precall_default_intro?: string;
  mirror: { goal: string; unlocks: string };
  proposed_mirror: { goal: string; unlocks: string };
  pdf_include_flags: Record<string, boolean>;
  has_pdf: boolean;
  converted_at: string | null;
  created_at: string;
  // Present on a single session, not in the list.
  sections?: StrategySection[];
  answers?: StrategyAnswerRow[];
  map_rows?: MapRow[];
  path_notes?: PathNote[];
  prep?: SessionPrep | null;
  /** The fractional's own note on this session. Fractional-only. */
  fractional_note?: string;
  pinned_questions?: PrepQuestion[];
  six_key_components?: {
    scores: { key: string; rating: number; comment: string;
              answered_by: "prospect" | "fractional" | "" }[];
    ratings: Record<string, number>; answered: number; of: number;
    average: number | null; complete: boolean; lowest: string | null;
  };
  must_ask?: { outstanding: string[]; answered: number; of: number };
}

export interface ConversionRow {
  row: string; position: number; title: string; the_fix: string; root_cause: string;
  owner_text: string; client_owner_contact: Person | null; measurable: string;
  horizon: number | null; target_date: string | null;
  suggested: "goal" | "project"; needs_baseline: boolean;
}

export interface PreCallForm {
  practice: string; company: string; first_name: string;
  sections: { code: string; title: string; scale: string; questions: {
    key: string; prompt: string; response_schema: StrategyQuestion["response_schema"];
    value: AnswerValue | null;
  }[] }[];
  answered: number; of: number; complete: boolean;
}


// --- Module 5 — meeting ingestion -------------------------------------------

/** GET /api/dashboard/ — the landing page (design brief, Tier 2).
 *
 *  One call rather than five, so the scoping rules cannot drift between this
 *  screen and the screens it summarises. */
export interface Dashboard {
  window_days: number;
  tiles: {
    tasks_due: number;
    /** Named separately from `tasks_due`, and included in it. */
    tasks_overdue: number;
    digests_pending: number;
    pipeline_moves: number;
    goals_open: number;
  };
  due_by_day: { date: string | null; label: string; count: number;
                overdue: boolean }[];
  digests: { id: string; contact: string; cadence: string; period_end: string;
             ai_prose: boolean; stale: boolean }[];
  pipeline: { id: string; contact: string; name: string; pipeline: string;
              from: string; to: string; at: string }[];
  clients: { id: string; name: string; open_tasks: number; overdue: number;
             open_goals: number }[];
  /** AI credit and budget — the FF's only (FR-0.9); null for everyone else. */
  ai?: AiBudget | null;
  /** Set only while automatic AI work is paused or stopped (owner,
   *  2026-09-29). Amounts for the FF only. */
  ai_paused?: AiGuard | null;
  /** Open commitments by people outside the practice, and how many are overdue. */
  waiting?: { open: number; overdue: number };
}

/** GET /api/ai-budget/ (owner, 2026-09-28). The balance is an **estimate**:
 *  credits the FF entered, less what this app has logged since that day. */
/** GET /api/ai-guard/ — the daily cap on unattended AI spend (owner,
 *  2026-09-29). The amounts and the list are the FF's only. */
export interface AiGuard {
  paused: boolean;
  resumes_at: string | null;
  skipped_today: number;
  stopped_after_two_failures: number;
  cap_usd?: string;
  spent_today_usd?: string;
  skipped?: { reason: "daily_cap" | "failed_twice"; purpose: string; job: string;
              target_type: string; target_id: string | null; at: string }[];
}

/** What a paused or stopped day says, in one sentence, for any staff role. */
export function aiPausedMessage(g: AiGuard): string {
  const parts: string[] = [];
  if (g.paused) {
    parts.push("Automatic AI work is paused for the rest of today: the daily limit"
      + (g.cap_usd ? ` of $${g.cap_usd}` : "") + " is reached"
      + (g.spent_today_usd ? ` ($${g.spent_today_usd} spent)` : "")
      + `. ${g.skipped_today} item${g.skipped_today === 1 ? "" : "s"} wait until tomorrow;`
      + " anything you run yourself still works.");
  }
  if (g.stopped_after_two_failures > 0) {
    parts.push(`${g.stopped_after_two_failures} automatic job${
      g.stopped_after_two_failures === 1 ? "" : "s"} failed twice on the same input and`
      + " will not be retried until someone runs it again.");
  }
  return parts.join(" ");
}

export interface AiBudget {
  console_url: string;
  credits_usd: string | null;
  credits_as_of: string | null;
  spent_since_credits: string | null;
  estimated_balance: string | null;
  monthly_budget_usd: string | null;
  month_spend: string;
  month_start: string;
  next_import: { remaining: number; cost_usd: string } | null;
  warnings: { kind: "budget" | "balance"; message: string }[];
}

/** A 409 that is a question — "this would run past the estimated AI
 *  balance; go ahead anyway?" — rather than a refusal. */
export function asksToConfirm(error: unknown): boolean {
  const e = error as { status?: number; data?: { needs_confirmation?: boolean } };
  return e?.status === 409 && !!e.data?.needs_confirmation;
}

/** GET /api/meetings/?contact= | ?company= — call notes (FR-5.8d). */
export interface MeetingNote {
  id: string;
  date: string | null;
  title: string;
  /** The accepted summary, or empty when it was discarded. Never invented. */
  summary: string;
  client_company: string | null;
  others: { contact: string; name: string; is_practice: boolean }[];
  practice: string[];
  source_link: string;
  source_name: string;
}

/** Module 6 — the shared history (FR-6.7) and the unmatched queue (FR-6.8). */
export interface EmailThreadRow {
  id: string;
  subject: string;
  contact: string | null;
  contact_name: string;
  last_message_at: string | null;
  message_count: number;
  poll_error: string;
  messages?: ThreadMessage[];
}

export interface ThreadMessage {
  id: string;
  direction: "inbound" | "outbound";
  from_address: string;
  to_addresses: string[];
  subject: string;
  /** Quoted history trimmed off for reading; the raw message is always kept. */
  body: string;
  has_more: boolean;
  matched_by: string;
  at: string;
  attachments: { id: string; filename: string; content_type: string;
                 byte_size: number }[];
}

export interface UnmatchedRow {
  id: string;
  from_address: string;
  from_name: string;
  subject: string;
  body: string;
  /** Why it could not be placed, in the words the queue shows. */
  reason: string;
  state: "pending" | "filed" | "discarded";
  received_at: string | null;
  filed_contact: string | null;
}

export interface InboundHealth {
  can_read: boolean;
  detail: string;
  account: string;
  threads_watched: number;
  last_polled_at: string | null;
  waiting: number;
  errors: number;
}

/** GET /api/drive-watch/ — the folder behind the queue, and its health.
 *
 *  `google_connected` and `drive_access` are separate because they fail
 *  separately: a practice can have a Google account connected for sending mail
 *  that has never been asked for Drive. */
/** A file whose read failed, named (owner, 2026-09-29). */
export interface FailedFile {
  id: string;
  name: string;
  error: string;
  web_view_link: string;
  automatic_failures: number;
  /** False once the automatic tries are used up: only Read again reads it. */
  retries_automatically: boolean;
}

export interface DriveHealth {
  connected: boolean;
  google_connected: boolean;
  drive_access: boolean;
  drive_account: string;
  folder_id: string;
  folder_name: string;
  last_polled_at: string | null;
  last_error: string;
  has_cursor: boolean;
  files_pending: number;
  files_failed: number;
  /** Failed and no longer retried by itself; each needs Read again. */
  files_needing_person?: number;
  files_skipped: number;
  /** The folder's past: the decision made about it, or null if none yet. */
  backfill: Backfill | null;
  /** Kept out of the first folder by the exclusion list. */
  excluded: number;
  /** Further folders the same watch reads (owner, 2026-09-28). */
  folders: WatchFolder[];
  /** Titles never read, in any watched folder. */
  exclusions: { id: string; pattern: string; source: "seed" | "manual" | "ignored" }[];
}

export interface WatchFolder {
  id: string;
  folder_id: string;
  folder_name: string;
  /** "any": every folder below it, reading only Docs named like the pattern. */
  depth: "one" | "any";
  name_pattern: string;
  files_recorded: number;
  excluded: number;
}

/** GET /api/drive-watch/backfill/ — what the folder already holds.
 *
 *  Drive's cursor starts at "now", so none of this is visible to the poller.
 *  Reading it is a choice with a price, which is why the count and the
 *  estimate are separate from the act of starting. */
export interface FolderPast {
  folder_name: string;
  readable_here: number;
  readable_in_subfolders: number;
  subfolders: { name: string; readable: number }[];
  readable_total: number;
  /** What is left to read — already-imported notes are not counted twice. */
  outstanding: number;
  /** Kept out by the exclusion list: recorded as skipped, never read, not costed. */
  excluded?: number;
  /** The same meeting as a note already recorded from any watched folder:
   *  not read again, and not in the count or the cost. */
  already_recorded?: number;
  /** How many of these another folder's panel offers too — importing either
   *  reads them once. */
  shared_with?: { folder: string | null; folder_name: string; count: number }[];
  oldest: string;
  newest: string;
  per_note_usd: string;
  /** True when the figure is this practice's own average rather than a model. */
  per_note_is_measured: boolean;
  estimate_usd: string;
  minutes: number;
}

export interface BackfillPlan {
  since: string;
  outstanding: number;
  excluded?: number;
  per_note_usd: string;
  per_note_is_measured: boolean;
  estimate_usd: string;
  minutes: number;
}

export interface Backfill {
  id: string;
  scope: "now" | "since" | "all";
  since: string | null;
  state: "declined" | "running" | "done" | "cancelled" | "failed";
  running: boolean;
  planned: number;
  done: number;
  skipped: number;
  failed: number;
  remaining: number;
  estimated_cost_usd: string;
  cost_usd: string;
  last_error: string;
  /** Which extra folder this imports; null for the first folder. */
  folder?: string | null;
  folder_name?: string;
  /** Appended when the recorded figures proved wrong; they are never rewritten. */
  correction_note?: string;
  started_at: string;
  finished_at: string | null;
}

/** POST /api/drive-watch/check/ — what that folder turned out to be, read live
 *  and saved nowhere until it is confirmed. */
export interface DriveFolder {
  folder_id: string;
  name: string;
  files: number;
  readable: number;
  truncated: boolean;
  /** Counted at the depth the watch reads it (owner, 2026-09-30). */
  depth?: "one" | "any";
  name_pattern?: string;
  in_subfolders?: number;
}

/** One proposed thing. **Nothing here exists yet**: approving is what creates
 *  it, and every item carries the passage it was drawn from (FR-5.14). */
/** GET /api/contacts/duplicate-groups/ (owner, 2026-09-29). */
export interface DuplicateMember {
  id: string; name: string; company: string; emails: string[];
  created_at: string; last_meeting: string | null;
  meetings: number; tasks: number; notes: number;
}
export interface DuplicateGroup {
  key: string; reasons: string[]; contacts: DuplicateMember[];
  suggested_survivor: string;
  /** Pairs in this group a person already said are not duplicates; the group
   *  is back only because a newer contact matches them (2026-10-03). */
  dismissed_pairs: [string, string][];
}

/** A contact a name or address could be, with what tells same-named people
 *  apart (owner, 2026-09-29). */
export interface ContactCandidate {
  contact_id: string; name: string; company: string; email: string;
  match_reason: string; confidence: number; rank: number;
  emails?: string[]; last_meeting?: string | null;
}

export interface ProposalItem {
  id: string;
  /** Looked up when the proposal is opened, for a pending participant. */
  candidates?: ContactCandidate[] | null;
  /** Everyone an action item's owner could be, for a pending one. */
  owner_candidates?: ContactCandidate[] | null;
  kind: "participant" | "action_item" | "deliverable";
  state: "pending" | "approved" | "rejected";
  source_excerpt: string;
  position: number;
  created_record_type: string;
  created_record_id: string | null;
  actioned_at: string | null;
  /** FR-5.9e — this participant is the practice: shown, never asked about. */
  is_practice?: boolean;
  payload: {
    practice_name?: string; practice_role?: string; is_practice?: boolean;
    parsed_name?: string; parsed_email?: string; parsed_title?: string;
    parsed_company?: string; proposed_contact_type?: string;
    new_contact_candidate?: Record<string, string>;
    existing_candidates?: { contact_id: string; name: string; company: string;
                            email: string; match_reason: string; confidence: number;
                            rank: number }[];
    /** FR-5.10a — the company the notes named, what might already be it, and
     *  the domain a new one would get (blank for a public mail provider). */
    parsed_company_domain?: string;
    company_candidates?: { company_id: string; name: string; match_reason: string;
                           confidence: number; rank: number }[];
    service_categories?: string[];
    text?: string; proposed_owner_text?: string;
    proposed_owner_contact_id?: string | null; proposed_due_date?: string | null;
    proposed_stakeholders?: { contact_id: string; cadence: string }[];
    /** Who owns an action item (2026-09-28): the practice, someone else, or
     *  "" when nobody was named. Missing on items parsed before it existed. */
    owner_side?: "practice" | "other" | "";
    owner_kind?: "client" | "prospect" | "vendor" | "third_party" | "";
    owner_practice_name?: string;
    owner_has_seat?: boolean;
    proposed_outcome?: "follow_up" | "record_only" | "portal" | "";
  };
  /** The owner's contact, by name, when the notes' owner matched one. */
  owner_contact_name?: string;
}

/** Something a person outside the practice said they would do (2026-09-28). */
export interface Commitment {
  id: string;
  state: "open" | "done";
  outcome: "follow_up" | "record_only" | "portal";
  outcome_label: string;
  owner_name: string;
  owner_kind: string;
  contact: string | null;
  company: string | null;
  company_name: string;
  text: string;
  due_date: string | null;
  follow_up_date: string | null;
  overdue: boolean;
  task: string | null;
  meeting: { id: string; title: string; date: string | null } | null;
  source_excerpt: string;
  done_at: string | null;
}

export type DismissReason = "no_meeting" | "not_relevant" | "vendor_pitch" | "other";

export interface MeetingProposal {
  id: string;
  state: "pending" | "partially_actioned" | "actioned" | "rejected" | "superseded"
    | "dismissed";
  title: string;
  meeting_date: string | null;
  /** Set only while dismissed (owner, 2026-09-28): why, by whom, when. */
  dismissed?: { reason: DismissReason; reason_label: string; note: string;
                by: string; at: string | null } | null;
  proposed_summary: string;
  summary: string;
  summary_discarded: boolean;
  source_file: { id: string; name: string; mime_type: string; state: string;
                 skip_reason: string; error: string; owner_email: string;
                 web_view_link: string; fetched_at: string | null };
  meeting: string | null;
  counts: { pending: number; approved: number; rejected: number };
  items?: ProposalItem[];
  source_text?: string;
}


/** Campaigns (owner, 2026-09-28): one marketing email, merged per person, queued
 *  for approval as one Outbox row each. */
export interface Campaign {
  id: string;
  name: string;
  subject: string;
  /** "alias" (the practice address), "self" (your own), or a verified address. */
  sender: string;
  body_mode: "rich" | "html";
  body_html: string;
  send_as_is: boolean;
  created_at: string;
  updated_at: string;
  created_by_name: string;
  stats: { recipients: number; queued: number; sent: number; unsubscribed: number;
           not_sent: number };
}

export interface CampaignCandidate {
  id: string; name: string; email: string; company: string;
  /** Why they cannot be queued ("no email address", …), or "". */
  unsendable: string;
}

export const MERGE_FIELDS = ["{FirstName}", "{Company}", "{FractionalName}"] as const;

// ------------------------------------------------------------ invoices (P4A)

export type InvoiceStatus = "draft" | "ready" | "sent" | "partially_paid" | "paid" | "void";

/** One row of GET /api/invoices/. Amounts are whole cents. */
export interface InvoiceRow {
  id: string; kind: "one_off" | "recurring" | "contact"; number: string;
  status: InvoiceStatus; status_label: string; overdue: boolean;
  client_company: { id: string; name: string } | null;
  contact: { id: string; name: string };
  issue_date: string; due_date: string;
  total_cents: number; paid_cents: number; balance_cents: number;
  from_schedule: boolean;
  /** For a ready invoice: is its email waiting for approval, or sent back? */
  send_state: "" | "waiting" | "sent_back";
}

export interface InvoiceLine {
  id?: string; description: string; quantity: string; unit_price_cents: number;
  amount_cents?: number;
}

export interface InvoicePayment {
  id: string; amount_cents: number; paid_on: string; method: string; method_label: string;
  reference: string; note: string; recorded_by: string; removed: boolean;
  remove_reason: string; removed_by: string;
}

export interface Invoice extends InvoiceRow {
  subtotal_cents: number; tax_cents: number; currency: string;
  notes: string; terms: string; pay_instructions: string; pay_url: string;
  email_to: string; email_subject: string; email_body: string;
  bill_to: { name?: string; company?: string; email?: string; address?: string };
  has_pdf: boolean; sent_at: string | null; voided_at: string | null; void_reason: string;
  lines: InvoiceLine[]; payments: InvoicePayment[]; merge_fields: string[];
}

export interface InvoiceTotals {
  invoiced_cents: number; paid_cents: number; outstanding_cents: number;
  overdue_cents: number;
}

export interface InvoiceList {
  invoices: InvoiceRow[]; totals: InvoiceTotals; drafts_from_schedules: number;
}

export interface InvoiceSettingsData {
  prefix: string; next_value: number; next_number: string; terms_days: number;
  default_notes: string; default_terms: string; pay_instructions: string;
  email_subject: string; email_body: string; merge_fields: string[];
}

export interface InvoiceSchedule {
  id: string; client_company: { id: string; name: string };
  contact: { id: string; name: string };
  day_of_month: number; next_on: string; ends_on: string | null;
  lines: InvoiceLine[]; total_cents: number; notes: string; terms: string;
  is_active: boolean;
}

export interface InvoiceEvent {
  at: string; what: string; by: string; before: string; after: string; reason: string;
  amount_cents: number | null; to: string;
}

/** GET /api/portal-invoices/ — what a client sees of an invoice. */
export interface PortalInvoice {
  id: string; number: string; issue_date: string; due_date: string;
  total_cents: number; balance_cents: number; status: InvoiceStatus; status_label: string;
  overdue: boolean; pay_url: string;
}
