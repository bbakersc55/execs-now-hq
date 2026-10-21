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
  // A demo visitor's copy that started being set up again (a reset) answers
  // so: asking who we are again shows its setup page (2026-10-17).
  if ((response.status === 401 && path !== "/api/me") || data?.demo_setting_up) {
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
  /** What this practice calls its goals, projects, tasks and steps (lib/words). */
  words?: import("./words").WordPairs;
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
  /** P6 M1: the modules this practice has ("bookkeeping"). Staff only. */
  modules?: string[];
  /** Which of the three environments (owner, 2026-09-29). */
  environment?: "local" | "demo" | "production";
  /** FR-3.42 — set while the real person acts as another user. Everything
   *  above then describes the acted-as user. */
  acting?: Acting | null;
  /** P7 phase 4: a client user's rights. Null for the practice. */
  portal?: PortalRights | null;
  /** A demo visitor's own copy (2026-10-17); null everywhere else. */
  demo_visitor?: DemoVisitorInfo | null;
}

/** apps/tenancy/demo/visitors.py `describe`. */
export interface DemoVisitorInfo {
  /** The visitor's one tick on first sign-in is still to give. */
  agreement_required: boolean;
  agreement_version: string;
  /** The days the copy was given. */
  days: number;
  state: "setting_up" | "ready" | "failed";
  expires_at: string;
  deletes_on: string;
  read_only: boolean;
  /** Why its AI is off, or "" when it is on. Every AI control shows this. */
  ai_stop: string;
  ai_spent_today_usd: string;
  ai_spent_total_usd: string;
  ai_per_day_usd: string;
  ai_in_all_usd: string;
  reset_count: number;
}

export interface Acting {
  real_name: string; real_email: string; real_role: string;
  as_membership: string; as_name: string; as_email: string; as_role: string;
  /** P7-10: what the acted-as client user is called, by level. */
  as_label?: string;
  company: string; company_name: string;
}

/** P7 phase 4: what a client user may do, so the portal offers only that. */
export interface PortalRights {
  level_label: string;
  may_create: { task: boolean; project: boolean; goal: boolean };
  edits_goals: boolean;
  /** Offered "Mine / My team / Everyone". */
  has_teams_view: boolean;
  /** The teams they may put new work on. */
  teams: ClientTeamName[];
  may_propose_goal: boolean;
  /** False for a viewer (§2.4a): they read comments and add none. */
  may_comment?: boolean;
}

/** GET /api/act-as/candidates/ — who the real person may act as. */
export interface ActAsCandidate {
  membership: string; name: string; email: string; role: string;
  company: string; company_name: string;
}

/** GET /api/activity/ — the practice's feed across every account. */
export const ACTIVITY_CATEGORIES = [
  "work", "comment", "note", "email", "pipeline",
  "import", "portal", "team", "act_as", "digest", "settings",
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
  linkedin_url?: string;
  alignable_url?: string;
  emails: { id: string; address: string; is_primary: boolean }[];
  phones: { id: string; number: string; is_primary: boolean }[];
  type_codes: string[];
  referral_fee_terms: string;
  referral_cadence: string;
  /** "template" (My template) or "claude" (Draft with Claude). */
  referral_touch_mode: string;
  /** The partner's own touch template; null means the practice's. */
  referral_template?: string | null;
  referral_next_touch_at: string | null;
  referral_onboarded_at: string | null;
  /** On the touch cadence — only ever because someone enrolled them. */
  referral_enrolled?: boolean;
  /** Who referred them into Sales; null when no one, or no one you may see. */
  referred_by?: ReferredBy | null;
  created_at?: string;
  updated_at?: string;
}

export interface ReferredBy {
  /** The referral's own id. */
  id: string;
  referrer: string;
  referrer_name: string;
  referred_on: string;
  note: string;
  outcome: "" | "won" | "lost";
}

/** Someone who sent the practice a prospect (owner, 2026-10-20). */
export interface Referral {
  id: string;
  direction: "inbound" | "outbound";
  referrer: { id: string; name: string };
  prospect: { id: string; name: string; company: string };
  pipeline: string;
  /** Where the prospect stands now; null if they have left the pipeline. */
  stage: { label: string; semantic: string } | null;
  outcome: "" | "won" | "lost";
  outcome_at: string | null;
  referred_on: string;
  note: string;
  fee_terms: string;
}

export interface Company {
  id: string;
  name: string;
  industry: string;
  linkedin_url?: string;
  alignable_url?: string;
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
  /** The "Referred by" cell, whom it matched, or why it matched no one. */
  referred_by?: string;
  referrer_name?: string;
  referrer_problem?: string;
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
  /** A folder the practice added, or null for the built-in one its link gives it. */
  folder?: string | null;
  folder_name?: string;
  built_in_folder?: "internal" | "contacts" | "companies";
}

/** A notes folder, with how many notes are in it as the grid is narrowed. */
export interface NoteFolder { id: string; name: string; built_in?: boolean; notes?: number }

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
export interface PortalPerson {
  id: string; name: string; role: string; company: string | null;
  /** P7-10: a client user's level ("Manager"), or "Client owner". */
  label?: string;
}

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
  /** P7: the client team it is on (its project's, for a task in one). Null
   *  and "" for the practice's own work. */
  client_team: string | null;
  client_team_name: string;
  created_at: string;
  updated_at: string;
  may_edit: boolean;
  may_delete: boolean;
  may_set_visibility: boolean;
  /** P7 phase 4: why a client may see this and not change it, said once at
   *  the top of its sheet. "" where they may, and always for the practice. */
  read_only_line?: string;
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
  /** P7, on a project only: the client team it is on. */
  client_team?: string | null;
  client_team_name?: string;
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
  /** P7 phase 4, for a client user: what they may do with it, and why not
   *  once where they may not. Absent for the practice, whose screens decide
   *  by role. */
  may_edit?: boolean;
  may_delete?: boolean;
  read_only_line?: string;
  /** On a goal a client user added (P7-7): "<name>, <client company>". */
  added_by?: string;
  /** On a goal, for a client who may change it: the fields that are theirs. */
  editable_fields?: string[];
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
            /** P7-10: "Client owner", or their highest level on any team. */
            level_label: string;
            teams: { team: string; name: string; level: string }[];
            may_create: string; leads_all_teams: boolean;
            contact: string | null; invited_at: string | null;
            /** Whether they have ever signed in. */
            signed_in: boolean;
            /** When the invitation they still hold runs out (it may have), or
             *  null if they hold none. */
            invitation_expires_at: string | null }[];
}

/** P7: a client company's team, for a picker. */
export interface ClientTeamName { id: string; name: string; is_default: boolean }

/** P7 phase 2: the Teams card of one client company. */
export interface ClientTeams {
  company: string; may_manage: boolean;
  teams: (ClientTeamName & {
    projects: number; open_tasks: number;
    people: { membership: string; name: string; level: string }[];
  })[];
  people: { id: string; name: string; email: string; role: string;
            may_create: string; leads_all_teams: boolean;
            teams: { team: string; level: string }[] }[];
  /** Only on the answer to an archive: what moved, and where. */
  archived?: { projects: number; tasks: number; people_moved: number; moved_to: string };
}

export interface ClientTeamArchivePreview {
  projects: number; tasks: number; people: number; people_left_on_no_team: number;
  moves_to: string;
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
  /** One of the eight parts taken off the prospect's map. Sent only then. */
  off_map?: boolean;
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
  /** Written by hand on the map: who wrote it. */
  added_by?: string;
  /** Drafted from the call notes, and the passage it rests on, word for word.
   *  Sent only to the practice owner and an associate on their own prospect. */
  from_call_notes?: boolean; source_passage?: string;
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
  /** The notes of the call, attached as context for Claude's drafts. Absent
   *  when there are none, and for anyone they are not shown to. */
  call_notes?: { source: string; source_label: string; title: string; characters: number;
                 text: string; added_by: string; added_at: string };
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
  /** P5: absent or null for everyone but the practice owner. */
  finance?: FinanceMonth | null;
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
  /** For an action item's owner: their portal seat as it is now, if any. */
  seat?: PortalSeat | null;
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
    /** Claude's reading (2026-10-20): something the practice promised the
     *  client. Pre-ticks "Promised to <company>". */
    promised_to_client?: boolean;
  };
  /** The owner's contact, by name, when the notes' owner matched one. */
  owner_contact_name?: string;
  /** The owner's portal seat as it is now, for a pending action item. */
  owner_seat?: PortalSeat | null;
  /** The client a promise in this meeting is made to, for a pending line. */
  promised_to?: { id: string; name: string } | null;
}

/** A client user's portal sign-in: who, and for which client company. */
export interface PortalSeat { user_id: string; company_id: string; company_name: string }

/** Something a person outside the practice said they would do (2026-09-28). */
export interface Commitment {
  id: string;
  state: "open" | "done";
  outcome: "follow_up" | "record_only" | "portal" | "promised";
  /** "theirs": someone else owes it. "ours" (2026-10-20): the practice
   *  promised it to the client. */
  side?: "theirs" | "ours";
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
  /** Owner, 2026-10-19: up to three files, copied onto every draft it makes. */
  attachments?: { id: string; filename: string; byte_size: number }[];
  /** "When this campaign is sent", per person: a stage to move them to, and a
   *  referral-touch cadence to enrol them at. Empty: nothing. */
  on_sent_stage?: string | null;
  on_sent_pipeline?: string | null;
  on_sent_cadence?: "" | "monthly" | "bimonthly" | "quarterly";
  /** What {FirstName} becomes on the real send for someone with no first name. */
  first_name_fallback?: string;
  stats: { recipients: number; queued: number; sent: number; unsubscribed: number;
           not_sent: number };
}

export interface CampaignCandidate {
  id: string; name: string; email: string; company: string;
  /** Why they cannot be queued ("no email address", …), or "". */
  unsendable: string;
}

/**
 * The template library's merge fields (owner, 2026-10-20): one style
 * everywhere, mirrored from apps/crm/services/templates.py. The last two mean
 * something only in their own emails.
 */
export const TEMPLATE_FIELDS: { field: string; label: string }[] = [
  { field: "{FirstName}", label: "First name" },
  { field: "{LastName}", label: "Last name" },
  { field: "{Company}", label: "Company" },
  { field: "{FractionalName}", label: "Your name" },
  { field: "{PracticeName}", label: "The practice's name" },
  { field: "{PracticeNews}", label: "What you're working on lately (Referral settings)" },
  { field: "{FeeTerms}", label: "Their referral fee terms" },
  { field: "{ProspectName}", label: "Who they referred (thank-yous only)" },
  { field: "{FlyerNote}", label: "The flyer line (a new partner's email only)" },
];

/** The fields a campaign can use: all but the two that belong to one email. */
export const MERGE_FIELDS = TEMPLATE_FIELDS.slice(0, 7).map((f) => f.field);

export interface EmailTemplate {
  id: string;
  name: string;
  kind: string;
  subject: string;
  /** Plain text with merge fields; never the signature. */
  body: string;
  first_name_fallback: string;
  /** A built-in template's key, "" for one the practice wrote. */
  original: string;
  is_original: boolean;
  /** A built-in one that no longer reads as the original. */
  changed: boolean;
  /** Where it is in use, in words. */
  used_for: string[];
  updated_at: string;
}

export type TemplateUseKey =
  "referral_touch" | "referral_onboarding" | "thanks_recorded" | "thanks_won" | "thanks_lost";

export interface TemplateUse { use: TemplateUseKey; label: string; template: string; }

// ------------------------------------------------------------ invoices (P4A)

export type InvoiceStatus = "draft" | "ready" | "sent" | "partially_paid" | "paid" | "void";

/** One row of GET /api/invoices/. Amounts are whole cents. */
export interface InvoiceRow {
  id: string; kind: "one_off" | "recurring" | "contact"; number: string;
  status: InvoiceStatus; status_label: string; overdue: boolean;
  client_company: { id: string; name: string } | null;
  contact: { id: string; name: string };
  issue_date: string; due_date: string;
  /** Payment terms in days (0 is due on receipt), and as they are said. The
   *  due date is the issue date and these. */
  terms_days: number; terms_label: string;
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
  /** Where its payments are entered in the books, "" for what its kind
   *  usually goes to. Sent to the practice owner only. */
  income_category?: string;
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
  terms_label: string;
  default_notes: string; default_terms: string; pay_instructions: string;
  email_subject: string; email_body: string; merge_fields: string[];
}

export interface InvoiceSchedule {
  id: string; client_company: { id: string; name: string };
  contact: { id: string; name: string };
  day_of_month: number; next_on: string; ends_on: string | null;
  lines: InvoiceLine[]; total_cents: number; notes: string; terms: string;
  /** Its own payment terms, or null for the practice's; and what that is today. */
  terms_days: number | null; terms_label: string;
  /** Its own, or "" for the practice's as it stands when each is written. */
  pay_instructions: string; email_subject: string; email_body: string;
  is_active: boolean;
  /** As on an invoice: the practice owner's only. */
  income_category?: string;
}

/** The finance settings (the practice owner's). */
export interface FinanceSettingsData {
  locked_through: string | null; invoice_income_category: string;
  /** By the kind of invoice; "" is "as anything else". */
  recurring_income_category?: string; one_off_income_category?: string;
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
  /** P4 part 2: Pay shows; a payment is being checked; the practice's
   *  account is NMI's sandbox (shown as "Test mode"). */
  can_pay: boolean; payment_in_progress: boolean; test_mode: boolean;
}

/** GET /api/portal-invoices/:id/pay/ — the card form's key, at runtime. */
export interface PayConfig {
  public_key: string; test_mode: boolean; amount_cents: number; number: string;
}

/** POST /api/portal-invoices/:id/pay/ — how the payment ended. */
export interface PayResult {
  status: "approved" | "declined" | "unknown" | "failed";
  message: string; balance_cents: number; invoice_status: InvoiceStatus;
}

// ------------------------------------------------------------- the books (P5)

export type EntryKind = "income" | "expense" | "transfer" | "owner" | "held";

export interface FinanceAccount {
  id: string; name: string; kind: "bank" | "card" | "cash"; kind_label: string;
  last4: string; opening_balance_cents: number; opening_on: string; closed: boolean;
  /** P6 M1: whether the month close asks for a reconciliation of it. */
  reconciled_monthly?: boolean;
  /** P6 M4: "mixed" — each line sorted to a side. */
  side?: "business" | "mixed";
}

export interface FinanceCategory {
  id: string; name: string; type: "income" | "expense" | "owner" | "held";
  type_label: string; cpa_code: string; position: number; archived: boolean;
  system: boolean; used?: boolean;
  /** P6 M1: the category above it, where it is a sub-category. */
  parent?: string | null;
  /** Where a combined category went. */
  merged_into?: string | null;
  is_contractor?: boolean;
}

/** What a combine or a split would move, counted before anything moves. */
export interface CategoryMoveCount {
  entries: number; first_on: string | null; last_on: string | null;
  from: string; to: string;
  rules?: number; sub_categories?: number;
  new?: boolean; under?: string | null; contains?: string; left?: number;
}

export interface StartingChartPlan {
  add: { name: string; type: FinanceCategory["type"]; parent: string | null }[];
  skipped: { name: string; why: string }[];
  note: string; added?: number;
}

export interface CategoryChange {
  id: string; kind: "merge" | "split"; kind_label: string; from: string; to: string;
  entries_moved: number; first_on: string | null; last_on: string | null;
  contains: string; at: string; by: string;
}

export interface FinanceEntry {
  /** P6 M4: "" business, "personal" (an owner draw for personal spending),
   *  "to_sort" (a Mixed account's line waiting for a side). */
  side?: "" | "personal" | "to_sort" | "paid_personally";
  id: string; kind: EntryKind; kind_label: string; direction: "in" | "out";
  on_date: string; amount_cents: number;
  category: { id: string; name: string } | null;
  account: { id: string; name: string } | null;
  to_account: { id: string; name: string } | null;
  description: string; counterparty: string;
  client_company: { id: string; name: string } | null;
  reference: string; source: "manual" | "invoice" | "import"; source_label: string;
  invoice: { id: string; number: string } | null;
  removed: boolean; remove_reason: string;
  /** Who it was paid to, where that is a 1099 payee. */
  payee_contact?: string;
  /** An owner draw that was an estimated tax payment. */
  estimated_tax?: "" | "federal" | "state";
}

/** What the CPA's worksheet asks for at year end and the books cannot know. */
export interface YearFacts {
  year: number; total_miles: number | null; business_miles: number | null;
  home_square_feet: number | null; office_square_feet: number | null;
}

export interface FinanceEntryList {
  entries: FinanceEntry[]; count: number;
  totals: { income_cents: number; expenses_cents: number; net_cents: number };
}

export interface PnlRow {
  id: string; name: string; cpa_code: string; amounts: number[]; total: number;
  /** What sits on a parent itself, beside its sub-categories. */
  direct?: boolean;
  /** P6 M1: its sub-categories, where it has any. */
  children?: PnlRow[];
}

export interface PnlSection { rows: PnlRow[]; totals: number[]; total: number }

export interface Pnl {
  year: number; by: "month" | "quarter"; periods: string[];
  income: PnlSection; expenses: PnlSection; net: number[]; net_total: number;
  uncategorized: { count: number; amount_cents: number }; years: number[];
}

export interface BalanceView {
  as_of: string;
  cash: { id: string; name: string; kind: string; last4: string; amount_cents: number;
          closed: boolean;
          /** What the bank's own file said on its last line, against the books. */
          bank_said?: { on: string; cents: number; books_cents: number;
                        difference_cents: number } | null }[];
  unplaced_cents: number; unplaced_count: number; cash_total_cents: number;
  cards: { id: string; name: string; kind: string; last4: string; amount_cents: number;
           closed: boolean }[];
  tax_held_cents: number; owed_total_cents: number; net_cents: number;
  owed_to_you_cents: number;
}

/** The dashboard's finance figures: the practice owner's only. */
export interface FinanceMonth {
  revenue_cents: number; expenses_cents: number; net_cents: number;
  margin_percent: number | null; month: string; year: number;
  /** P6 M2: the lowest cash in the next 13 weeks. Null without the Cash
   *  forecast module or two closed months. */
  forecast?: { low_cents: number; week_of: string; below_zero: boolean;
               below_floor: boolean } | null;
}

// ----------------------------------------- the import, rules and 1099 (P5, 2)

export interface ImportMapping {
  date: string; date_format: string; description: string; amount: string; sign: string;
  debit: string; credit: string; balance: string; reference: string; bank_id: string;
}

export interface ImportDetected {
  header: string[]; sample: Record<string, string>[]; lines: number;
  mapping: ImportMapping; from_saved: boolean;
  /** "ofx" for a bank's own file (OFX, QFX, QBO): its columns are the
   *  format's, so `fixed` is true and there is nothing to map. */
  kind?: "csv" | "ofx" | "pdf"; fixed?: boolean;
  /** A PDF statement only: how long it is, about what Claude's reading of
   *  it costs, and why it cannot be read when it cannot. */
  pages?: number; estimate_usd?: string; refused?: string;
  date_formats: { value: string; label: string }[];
}

export type ImportOutcome = "new" | "duplicate" | "invoice_payment" | "transfer"
  | "transfer_match" | "ignore" | "error";

export interface BankImportRow {
  id: string; row_number: number; on_date: string | null; amount_cents: number | null;
  direction: "in" | "out" | ""; description: string; outcome: ImportOutcome;
  outcome_label: string;
  category: { id: string; name: string } | null;
  other_account: { id: string; name: string } | null;
  payee_contact: string;
  matched: { id: string; on_date: string; description: string; counterparty: string;
             amount_cents: number } | null;
  rule: { id: string; contains: string } | null;
  error: string; raw: Record<string, string> | null;
  /** P6 M4: "" business, "personal", "split" or "to_sort". */
  side?: "" | "personal" | "split" | "to_sort";
  personal_category?: { id: string; name: string } | null;
  split_business_cents?: number | null;
}

/** What is kept from a PDF statement: its period, its two balances, whether
 *  the lines read add up to them, where the PDF is, and what the read cost. */
export interface StatementFacts {
  pdf: string; period_start: string | null; period_end: string | null;
  opening_balance_cents: number | null; closing_balance_cents: number | null;
  adds_up: { in_cents: number; out_cents: number; expected_cents: number;
             difference_cents: number } | null;
  cost_usd: string | null;
}

/** A PDF statement imported for one account and month, on the Reconcile screen. */
export interface KeptStatement {
  id: string; filename: string; pdf: string; period_start: string | null;
  period_end: string; closing_balance_cents: number | null;
}

export interface BankImportBatch {
  id: string; account: { id: string; name: string }; filename: string;
  status: "dry_run" | "committed" | "rolled_back"; status_label: string;
  counts: Record<string, number>; created_at: string; committed_at: string | null;
  last_balance_cents: number | null; last_balance_on: string | null;
  source?: "csv" | "ofx" | "pdf";
  /** For an import read from a PDF statement, the statement's own facts. */
  statement?: StatementFacts | null;
  rows?: BankImportRow[];
  rolled_back?: { removed: number; unmatched: number;
                  kept: { on_date: string; amount_cents: number; description: string }[] };
}

export interface FinanceRule {
  id: string; contains: string; treat_as: "category" | "transfer" | "ignore";
  category: { id: string; name: string } | null;
  other_account: { id: string; name: string } | null;
  account: { id: string; name: string } | null; is_active: boolean;
  /** P6 M4: "" business, "personal" or "split". */
  side?: "" | "personal" | "split"; split_percent?: number | null;
  personal_category?: { id: string; name: string } | null;
}

export interface PayeeReport {
  year: number; threshold_cents: number; default_threshold_cents: number; over: number;
  payees: { contact: string; name: string; company: string; is_payee: boolean;
            total_cents: number; by_card_cents: number; reportable_cents: number;
            over_threshold: boolean }[];
}

// ------------------------- reconciliation and month close (P6 M1, stop 2)

export type ReconcileCellState = "not_started" | "open" | "finished" | "not_needed" | "before";

export interface ReconcileCell {
  state: ReconcileCellState; id?: string; statement_on?: string;
  finished_at?: string | null; difference_cents?: number;
}

export interface ReconcileGrid {
  months: { month: string; label: string; state: "open" | "closed" | "locked_before";
            closed_at: string | null; closed_by: string }[];
  accounts: { id: string; name: string; kind: "bank" | "card" | "cash"; kind_label: string;
              last4: string; reconciled_monthly: boolean; opening_on: string;
              opening_balance_cents: number; next_month: string | null;
              cells: Record<string, ReconcileCell>;
              /** By month: the PDF statements imported for it. */
              statements?: Record<string, KeptStatement[]>;
              bank_said?: { on: string; cents: number } | null }[];
  locked_through: string | null;
  /** The close that set the lock; null when it was typed before closing existed. */
  locked_by: { month: string; by: string; at: string } | null;
  next_to_close: string | null; guided: boolean; today: string;
}

export interface ReconcileLine {
  id: string; on_date: string; amount_cents: number; way: "in" | "out";
  description: string; counterparty: string; kind: EntryKind; kind_label: string;
  cleared: boolean; carried: boolean; from_bank: boolean;
}

export interface ReconcileHint {
  kind: "untick" | "wrong_way" | "swapped" | "missing"; entry: string | null; text: string;
}

export interface Reconciliation {
  id: string;
  account: { id: string; name: string; kind: "bank" | "card" | "cash"; kind_label: string };
  month: string; month_label: string; statement_on: string;
  statement_balance_cents: number; state: "open" | "finished"; state_label: string;
  finished_at: string | null; finished_by: string;
  reopened_at: string | null; reopened_by: string; reopen_reason: string;
  starting_balance_cents: number; cleared_in_cents: number; cleared_out_cents: number;
  expected_cents: number; difference_cents: number;
  lines: ReconcileLine[]; first: boolean; period_start: string; hints: ReconcileHint[];
  statements?: KeptStatement[];
  unplaced: { id: string; on_date: string; amount_cents: number; description: string;
              counterparty: string }[];
  cannot_reopen: string; can_discard: boolean;
}

export interface ReconcileReport {
  id: string; account: Reconciliation["account"]; month: string; month_label: string;
  statement_on: string; statement_balance_cents: number; starting_balance_cents: number;
  cleared_in_cents: number; cleared_out_cents: number; expected_cents: number;
  difference_cents: number; finished_at: string | null; finished_by: string;
  practice: string; cleared: ReconcileLine[]; outstanding: ReconcileLine[];
  outstanding_in_cents: number; outstanding_out_cents: number; disclaimer: string;
}

export interface MonthChecklistLine {
  code: "reconciled" | "categorized" | "placed" | "payees"; label: string;
  blocks: boolean; ok: boolean; count: number; detail: string; link: string;
}

export interface MonthDetail {
  month: string; label: string; state: "open" | "closed" | "locked_before";
  checklist: MonthChecklistLine[]; cannot_close: string;
  history: { closed_at: string; closed_by: string;
             warnings: { code: string; label: string; count: number }[];
             reopened_at: string | null; reopened_by: string; reopen_reason: string }[];
  reopen_note: string; reopened?: string[];
}

export interface ReopenPlan {
  month: string; label: string; also: string[]; locked_through_after: string; note: string;
}

export interface ExplainStatus {
  estimate_usd: string; used_today: number; cap: number; resets_at: string;
  refused: string; disclaimer: string;
}

export interface ExplainAnswer {
  text: string; cost_usd: string; disclaimer: string; used_today: number; cap: number;
}

/** What a bulk change to entries would do, counted before it does it. */
export interface BulkPlan {
  action: "recategorize" | "remove"; chosen: number; count: number;
  first_on: string | null; last_on: string | null; to: string;
  left_out: { why: string; label: string; count: number }[];
}

export interface BulkChange {
  id: string; at: string; action: "recategorize" | "remove"; count: number; to: string;
  first_on: string | null; last_on: string | null; reason: string; by: string;
}

// ------------------------------------------- the cash forecast (P6 M2, stop 1)

export interface ForecastRow {
  start: string; end: string; label: string; start_cents: number; in_cents: number;
  out_cents: number; end_cents: number; lines: string[];
  below_floor: boolean; below_zero: boolean;
}

export interface ForecastLine {
  id: string; kind: "known" | "regular" | "card" | "planned"; direction: "in" | "out";
  /** What every occurrence of one thing shares: what an adjustment or a
   *  what-if names. */
  group: string; client: string; who: string;
  /** What the owner changed about it, in words, and that adjustment's id. */
  adjusted: string; adjustment: string; what_if?: boolean;
  amount_cents: number; on_date: string; label: string; detail: string;
  cadence: "" | "monthly" | "quarterly" | "yearly"; category: string; link: string;
  /** False for a charge on a card: it is cash when the card is paid. */
  counted: boolean; on_card: string;
}

export interface ForecastSummary {
  low_cents: number; low_start: string; low_label: string; end_cents: number;
  first_below_floor: string | null; first_below_zero: string | null;
}

export type ForecastView = "30" | "90" | "180" | "months";

export interface Forecast {
  as_of: string; ready: boolean; closed_months: number; closed_through: string | null;
  note: string; cash_today_cents: number; unplaced_cents: number;
  accounts: { id: string; name: string; kind: string; amount_cents: number;
              last_entry_on: string | null; reconciled_through: string | null;
              stale: boolean }[];
  floor_cents: number | null; weeks: ForecastRow[]; months: ForecastRow[];
  views: Record<ForecastView, ForecastSummary>; lines: ForecastLine[];
  left_out: { id: string; group: string; label: string; amount_cents: number;
              due_date: string; days_overdue: number; why: string; adjustment: string;
              link: string }[];
  likely_annual: { id: string; group: string; label: string; category: string;
                   direction: "in" | "out"; amount_cents: number; last_on: string;
                   likely_on: string; detail: string }[];
  include_client_names: boolean;
  planned: PlannedLine[]; adjustments: ForecastAdjustment[];
  clients: { id: string; name: string }[]; history: ForecastHistory[];
  /** A look, saved nowhere; null when nothing is being tried. */
  what_if: ForecastWhatIf | null;
  disclaimer: string;
}

export interface PlannedLine {
  id: string; description: string; direction: "in" | "out"; amount_cents: number;
  on_date: string; repeat: "" | "monthly" | "quarterly" | "yearly"; until: string | null;
  is_what_if: boolean; source: "" | "review" | "annual";
  state: "planned" | "what_if" | "happened" | "lapsed"; next_on: string | null;
}

export interface ForecastAdjustment {
  id: string; group: string; label: string; kind: string; text: string; source: string;
  at: string; by: string;
}

export interface ForecastHistory {
  month: string; label: string; taken_on: string;
  forecast: { in_cents: number; out_cents: number; end_cents: number };
  actual: { in_cents: number; out_cents: number; end_cents: number };
  largest: { name: string; forecast_cents: number; actual_cents: number;
             difference_cents: number }[];
}

export interface ForecastWhatIf {
  weeks: ForecastRow[]; months: ForecastRow[];
  views: Record<ForecastView, ForecastSummary>;
  difference_at_low: Record<ForecastView, number>;
  off: string[]; on: string[]; amounts: Record<string, number>;
}

export interface ForecastAiStatus {
  estimate_usd: string; review_estimate_usd: string; used_today: number; cap: number;
  resets_at: string; refused: string; disclaimer: string; include_client_names: boolean;
}

export interface ReviewItem {
  group: string; who: string; category: string; direction: "in" | "out";
  months: { month: string; amount_cents: number }[]; last_on: string;
  last_amount_cents: number; why: string; amount_cents?: number; detail?: string;
  /** A regular line's own cadence; for one that was not picked up, the
   *  cadence the review proposed, with the date it next falls. */
  cadence?: PlannedLine["repeat"]; next_on?: string;
}

export interface ForecastReview {
  one_offs: ReviewItem[]; missed: ReviewItem[];
  questions: { topic: string; question: string }[];
  cost_usd: string; disclaimer: string; used_today: number; cap: number;
}

// ------------------------------------------------- P6 M4: personal finance

export interface PersonalCategory {
  id: string; name: string; type: "expense" | "income" | "transfer";
  parent: string | null; position: number; system: boolean;
  tax_group: string; tax_group_label: string; archived: boolean;
}

export interface PersonalChart {
  categories: PersonalCategory[];
  tax_groups: { code: string; label: string }[];
}

export interface PersonalAccount {
  id: string; name: string; kind: "bank" | "card" | "cash"; kind_label: string;
  last4: string; closed: boolean; side: "personal" | "mixed"; in_books: boolean;
  opening_balance_cents?: number; opening_on?: string;
  /** A personal account: what it holds (a card: what is owed), and the last
   *  statement reconciled. */
  balance_cents?: number; reconciled_through?: string | null;
}

export interface PersonalLine {
  id: string;
  /** "line": in the ledger; "entry": a Mixed account's line waiting for a side. */
  kind: "line" | "entry";
  on_date: string; amount_cents: number; direction: "in" | "out"; description: string;
  category: { id: string; name: string; tax_group?: string } | null;
  account: { id: string; name: string } | null;
  from_books: boolean; source: string; to_sort: boolean;
  /** Decision 3: the practice's, paid from this personal account. */
  paid_for?: { entry: string; category: string } | null;
  /** Decision 7: one side of a move between the household's own accounts. */
  transfer?: boolean;
}

export interface PersonalLines {
  lines: PersonalLine[]; to_sort: number; threshold_cents: number;
}

export type PersonalSide = "personal" | "business" | "split" | "to_sort";

export interface PersonalImportRow {
  id: string; row_number: number; on_date: string | null; amount_cents: number | null;
  direction: "in" | "out" | ""; description: string;
  outcome: "new" | "duplicate" | "transfer_match" | "ignore" | "error";
  outcome_label: string; side: PersonalSide;
  category: { id: string; name: string } | null;
  business_category: { id: string; name: string } | null;
  split_business_cents: number | null;
  matched: { id: string; on_date: string; description: string; account: string } | null;
  rule: { id: string; contains: string } | null;
  error: string; raw: Record<string, string> | null;
}

export interface PersonalImport {
  id: string; account: { id: string; name: string }; filename: string;
  status: "dry_run" | "committed" | "rolled_back"; status_label: string;
  counts: Record<string, number>; created_at: string; committed_at: string | null;
  source: "csv" | "ofx" | "pdf";
  statement: Omit<StatementFacts, "pdf"> | null;
  rows?: PersonalImportRow[];
  rolled_back?: { removed: number;
                  kept: { on_date: string; amount_cents: number; description: string }[] };
}

export interface PersonalReconciliation {
  id: string; account: { id: string; name: string; kind: string };
  statement_on: string; statement_balance_cents: number; state: "open" | "finished";
  finished_at: string | null; starting_balance_cents: number; cleared_in_cents: number;
  cleared_out_cents: number; difference_cents: number;
  lines?: { id: string; on_date: string; amount_cents: number; direction: "in" | "out";
            description: string; cleared: boolean }[];
}

/** "Sort these with Claude" (decision 6): the price before, the proposals after. */
export interface SortWithClaudeStatus {
  estimate_usd: string; used_today: number; cap: number; resets_at: string;
  refused: string; disclaimer: string; lines: number; most: number;
}

export interface SortProposal {
  kind: "line" | "entry"; id: string; description: string; amount_cents: number;
  direction: "in" | "out"; side: "personal" | "business";
  category: { id: string; name: string }; match: string; why: string;
}

export interface SortProposals {
  proposals: SortProposal[]; cost_usd: string; used_today: number; cap: number;
  disclaimer: string;
}

// ------------------------------------------- P6 M4 stop 2: the budget

/** apps/personal/budget.py `month_view`, one envelope. */
export interface Envelope {
  id: string; name: string; kind: "everyday" | "savings" | "income"; kind_label: string;
  rolls: boolean; category: string | null; goal: string | null;
  source: "history" | "typed" | "goal" | "yearly" | "debt" | "tax"; source_label: string;
  planned_cents: number; history_cents: number | null; carried_cents: number;
  moved_in_cents: number; moved_out_cents: number; spent_cents: number; left_cents: number;
  yearly_cents: number | null; yearly_month: number | null; over: boolean; stood: boolean;
}

export interface BudgetMonth {
  month: string; month_label: string; envelopes: Envelope[]; income: Envelope[];
  income_planned_cents: number; income_received_cents: number;
  planned_cents: number; spent_cents: number; unassigned_cents: number;
  over_income: { id: string; name: string; planned_cents: number }[];
  unbudgeted: { category: string; name: string; spent_cents: number }[];
}

export interface PersonalGoal {
  id: string; name: string; target_cents: number; target_on: string | null;
  saved_cents: number; set_aside_cents: number; progress_cents: number; percent: number;
  monthly_cents: number; monthly_chosen: boolean; months_of_envelopes: number | null;
  account: { id: string; name: string } | null; envelope: string | null;
  planned: { id: string; on_date: string; amount_cents: number } | null;
}

export interface CashFlow {
  months: string[]; labels: string[]; so_far: string;
  rows: { type: "income" | "expense"; name: string; cents: number[];
          children: { name: string; cents: number[] }[] }[];
  in_cents: number[]; out_cents: number[]; net_cents: number[];
}

export interface Budget {
  has_budget: boolean;
  proposal: null | {
    ready: boolean; least_months: number; months: string[];
    envelopes: { category: PersonalCategory; kind: string; amounts: number[];
                 proposed_cents: number }[];
  };
  month: BudgetMonth | null;
  goals: PersonalGoal[];
  coming_up: { id: string; name: string; on_date: string; amount_cents: number;
               direction: "in" | "out"; goal: string | null }[];
  cash_flow: CashFlow;
  questions_waiting: number;
  /** Stop 3: open debts, so Unassigned can go toward them. */
  debts: number;
}

/** apps/personal/questions.py `represent`. */
export interface BudgetQuestion {
  id: string; kind: "keep" | "normal" | "yearly" | "coming"; run: string; text: string;
  detail: { proposed_cents?: number; suggested_cents?: number; choices?: number[];
            cents?: number; month?: number; monthly_cents?: number };
  state: string; envelope: string | null; category: string | null;
}

// ------------------------------- P6 M4 stop 3: forecast, debts, the rest

/** apps/personal/forecast.py `build`: M2's shape, on the household's money. */
export interface PersonalForecastLine extends Omit<ForecastLine, "kind" | "cadence" |
  "client" | "who" | "on_card"> {
  kind: "known" | "regular" | "planned"; cadence: string; what_if: boolean;
}

export interface PersonalPlanned {
  id: string; description: string; direction: "in" | "out"; amount_cents: number;
  on_date: string; repeat: "" | "monthly" | "quarterly" | "yearly"; is_what_if: boolean;
  state: "planned" | "what_if" | "lapsed"; goal: string | null; next_on: string | null;
}

export interface PersonalForecast {
  as_of: string; ready: boolean; complete_months: number; note: string;
  cash_today_cents: number; accounts: Forecast["accounts"]; floor_cents: number | null;
  weeks: ForecastRow[]; months: ForecastRow[];
  views: Record<ForecastView, ForecastSummary>; lines: PersonalForecastLine[];
  planned: PersonalPlanned[];
  goals_not_drawn: { id: string; name: string; monthly_cents: number;
                     account: string | null }[];
  adjustments: Omit<ForecastAdjustment, "by">[];
  history: ForecastHistory[]; what_if: ForecastWhatIf | null; disclaimer: string;
}

export interface PersonalReviewItem {
  group: string; label: string; category: string; direction: "in" | "out";
  months: { month: string; amount_cents: number }[]; last_on: string;
  last_amount_cents: number; why: string; amount_cents?: number; detail?: string;
  cadence?: PersonalPlanned["repeat"]; next_on?: string;
}

export interface PersonalReview {
  one_offs: PersonalReviewItem[]; missed: PersonalReviewItem[];
  /** Stop 4 (decision 25): changes to envelopes, goals and the set-aside. The
   *  amounts are the app's; Claude says which and why. */
  envelopes?: ReviewEnvelope[]; goals?: ReviewGoal[]; set_aside?: ReviewSetAside[];
  questions: { question: string }[];
  cost_usd: string; disclaimer: string; used_today: number; cap: number;
}

export interface ReviewEnvelope {
  id: string; name: string; planned_cents: number; kind: string; proposed_cents: number;
  months: { month: string; amount_cents: number }[]; why: string;
}

export interface ReviewGoal {
  id: string; name: string; target_cents: number; progress_cents: number;
  monthly_cents: number; target_on: string | null; why: string;
}

export interface ReviewSetAside {
  id: string; year: number; percent_now: string | null; suggested_percent: number;
  still_needed_cents: number; saved_cents: number; why: string;
}

// ------------------------------------------------ P6 M4 stop 4: taxes and the CPA

export interface TaxInputs {
  year: number; filing_status: string; state: string; state_rate_percent: string | null;
  last_year_tax_cents: number | null; last_year_taxable_cents: number | null;
  effective_rate_percent: string | null; other_income_cents: number | null;
  medical_miles: number | null; charitable_miles: number | null; hsa_cents: number | null;
  /** The QBI deduction: "" none, "20" for 20% of net profit. */
  qbi?: "" | "20";
}

export interface TaxPayment {
  id: string; on_date: string; amount_cents: number; which: "federal" | "state";
  from: "practice" | "household"; link: string; quarter: number; quarter_label: string;
}

export interface TaxQuarter {
  label: string; on_date: string; amount_cents: number; safe_harbor_cents: number | null;
  paid_cents: number; next: boolean; past: boolean;
}

export interface TaxEstimate {
  year: number; as_of: string; confirm: string; ready: boolean; missing: string[];
  brackets_year: number; brackets_note: string; inputs: TaxInputs;
  statuses: Record<string, string>;
  profit: { so_far_cents: number; for_year_cents: number; through: string;
            share_of_year: number };
  other_income: { cents: number; from: "typed" | "lines"; so_far_cents: number | null };
  withholding_cents: number; payments: TaxPayment[]; paid_cents: number;
  set_aside: { percent_per_draw: string | null; saved_cents: number };
  method?: "brackets" | "rate"; se_tax_cents?: number; se_half_cents?: number;
  gross_cents?: number; adjusted_cents?: number;
  deduction?: { cents: number; kind: "standard" | "itemized"; standard_cents: number;
                itemized_cents: number };
  taxable_cents?: number; qbi_cents?: number; federal_taxable_cents?: number;
  federal_cents?: number; state_cents?: number;
  state_rate_percent?: string | null; total_cents?: number; required_cents?: number;
  still_needed_cents?: number;
  safe_harbor?: { percent: number; last_year_tax_cents: number; target_cents: number;
                  required_cents: number; why: string } | null;
  quarters?: TaxQuarter[];
  by_next?: { on_date: string; label: string; needed_cents: number;
              safe_harbor_cents: number | null } | null;
  draws?: { average_draw_cents: number; months_left: number; draws_ahead_cents: number;
            to_cover_cents: number; suggested_percent: number | null;
            since_last_payment_cents: { since: string; drawn_cents: number;
                                        cents: number } | null };
  envelope?: { id: string | null; planned_cents: number | null; saved_cents: number;
               needed_by_next_cents: number | null; next_on: string | null;
               short_cents: number | null; suggested_monthly_cents: number;
               months_left: number };
}

export interface PayYourself {
  needed_cents: number | null; envelopes_cents: number; other_income_cents: number;
  paid: { months: number; average_cents: number | null; drawn_cents: number;
          spent_cents: number; tax_cents: number; start: string | null; end: string | null };
  difference_cents: number | null; pay_category: string; matched: number;
  forecasting: boolean;
  business_line: { group: string; amount_cents: number | null; cadence: string;
                   adjusted: string; on_date: string | null } | null;
}

export interface WorksheetRow { name: string; amount_cents: number; note: string; sub: boolean }

export interface BusinessWorksheet {
  year: number; title: string;
  sections: { title: string; rows: WorksheetRow[]; total_label: string;
              total_cents: number }[];
  net_cents: number; has_paid_personally: boolean;
  paid_personally: { name: string; amount_cents: number; note: string }[];
  estimated: { on_date: string; federal_cents: number | null; state_cents: number | null }[];
  estimated_federal_cents: number; estimated_state_cents: number;
  facts: { name: string; value: number | null }[]; disclaimer: string;
}

export interface CpaRow {
  kind: "line" | "item"; id: string; on_date: string | null; item: string;
  description: string; charity: string; account: string; amount_cents: number;
}

export interface CpaGroup {
  group: string; label: string; rows: CpaRow[]; total_cents: number;
  miles: number | null; miles_label: string;
}

export interface CpaFact {
  key: string; label: string; total_cents: number | null; note: string;
  quarters?: { label: string; due_on: string; total_cents: number;
               payments: { on_date: string; which: string; from: string;
                           amount_cents: number }[] }[];
  accounts?: { name: string; cents: number; from: string; detail: string }[];
  lines?: number;
}

export interface CpaPage {
  year: number; business: BusinessWorksheet;
  personal: {
    year: number; groups: CpaGroup[]; facts: CpaFact[]; inputs: TaxInputs; confirm: string;
    standard: { itemized_cents: number; standard_cents: number | null; status: string;
                status_label: string; figures_year: number | null; note: string;
                figures_note: string };
  };
}

export interface SideEnding {
  ready: boolean; cash_today_cents: number; end_cents: number; low_cents: number;
  low_start: string;
}

export interface Sides { days: number; personal: SideEnding; business: SideEnding | null }

export interface Point { on_date: string; cents: number }

export interface PersonalDebt {
  id: string; name: string; kind: string; kind_label: string; whose: string | null;
  whose_name: string; balance_cents: number; balance_on: string | null;
  balance_source: "import" | "entered" | "none"; rate_percent: string | null;
  minimum_cents: number | null; due_day: number | null;
  account: { id: string; name: string } | null;
  category: { id: string; name: string } | null;
  plan_position: number | null; payoff_on: string | null; interest_cents: number | null;
  never: boolean; history: Point[]; projected: Point[];
}

export interface Debts {
  order: "snowball" | "avalanche"; other_order: "snowball" | "avalanche";
  order_label?: string; other_order_label?: string;
  extra_cents: number; saved_extra_cents: number; saved_order: "snowball" | "avalanche";
  total_cents: number; minimums_cents: number; debt_free_on: string | null;
  interest_cents: number | null;
  /** What the other order would cost (+) or save (-), in interest and months. */
  other: { interest_cents: number | null; months: number | null;
           debt_free_on: string | null };
  extra_saves: { interest_cents: number | null; months: number | null;
                 debt_free_on: string | null };
  debts: PersonalDebt[];
}

export interface Holding {
  id: string; name: string; kind: "retirement" | "investment"; kind_label: string;
  whose: string | null; whose_name: string; balance_cents: number;
  balance_on: string | null; target_cents: number | null; target_year: number | null;
  contribution_text: string; typed_monthly_cents: number | null;
  contributions: { monthly_cents: number; recognized: boolean;
                   months: { month: string; cents: number }[] };
  status: null | { on_track: boolean; projected_cents: number; months: number;
                   short_cents: number; needed_monthly_cents: number;
                   projection: Point[] };
  history: Point[];
}

export interface Holdings {
  assumed_return_percent: string; estimate: string; holdings: Holding[];
  total_cents: number;
}

export interface Member {
  id: string; name: string; relation: "self" | "spouse" | "partner" | "other";
  relation_label: string; expected_withholding_cents: number | null; is_you: boolean;
}

export interface Household {
  members: Member[];
  things: { thing: "account" | "category" | "debt" | "holding" | "asset"; id: string;
            name: string; what: string; label: string; whose: string | null }[];
  income: { category: string; whose: string | null; whose_name: string;
            monthly_cents: number }[];
}

export interface Asset {
  id: string; name: string; kind: "home" | "vehicle" | "other"; kind_label: string;
  whose: string | null; debt: { id: string; name: string } | null;
  value_cents: number; value_on: string | null;
}

export interface NetWorth {
  as_of: string; assets_cents: number; debts_cents: number; total_cents: number;
  assets: { kind: string; name: string; cents: number }[];
  debts: { kind: string; name: string; cents: number }[];
  series: Point[]; change_cents: number | null; since: string | null;
  equity: { id: string; name: string; kind: string; value_cents: number; value_on: string;
            debt: string; owed_cents: number; owed_on: string | null;
            equity_cents: number }[];
  things: Asset[];
}

/** A reply to a marketing email that asks to leave (owner, 2026-10-19). */
export interface LeaveRequest {
  id: string; subject: string; from_address: string; received_at: string | null;
  said: string; contact: { id: string; name: string } | null;
  answered: { subject: string; producer: string; sent_at: string | null } | null;
}
