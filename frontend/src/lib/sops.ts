/** The SOP studio (P10): the shapes `apps/sops` answers with. */

export type SopStatus = "draft" | "published" | "archived";
export type Audience = "company" | "teams" | "people";

export const STATUS_LABEL: Record<SopStatus, string> = {
  draft: "Draft", published: "Published", archived: "Archived",
};
export const STATUS_PILL: Record<SopStatus, string> = {
  draft: "warn", published: "ok", archived: "",
};

export interface SopCompany { id: string; name: string; is_practice: boolean }
export interface Role { name: string; does: string }
export interface Step { text: string; role: string; warning: string; images: string[] }
export interface Section { title: string; body: string }
export interface Attachment { id: string; name: string; kind: "image" | "pdf"; url: string }

export interface SopSummary {
  id: string; title: string; status: SopStatus; category: string; version: number;
  company: SopCompany; owner: string; review_date: string | null;
  published_at: string | null; updated_at: string; from_ai_app: boolean;
  reads: { asked: number; read: number } | null;
  /** The portal's own state: asked to read it, and read the version that asks. */
  mine?: { asked: boolean; read: boolean; read_at: string | null };
}

export interface SopList {
  sops: SopSummary[]; may_create: boolean; categories?: string[];
}

export interface Reads {
  asked: number; read: number; number: number; read_by?: string | null;
  outstanding: { membership: string; name: string }[];
  readers: { membership: string; name: string; at: string; version: number; late: boolean }[];
}

export interface SopMay {
  drafts: boolean; publishes: boolean; sees_reads: boolean; reminds: boolean;
  is_client: boolean; publish?: boolean; edit?: boolean;
}

export interface SopFull extends SopSummary {
  purpose: string; applies_when: string; roles: Role[]; steps: Step[]; sections: Section[];
  process_map: string; map_svg: string | null; owner_id: string | null; audience: Audience;
  teams: string[]; people: string[]; kpis: { id: string; name: string }[];
  attachments: Attachment[];
  versions: { number: number; change_note: string; minor: boolean; published_at: string;
    published_by: string; read_by: string | null }[];
  unpublished_changes: boolean; reads: Reads | null;
  comments: { id: string; text: string; by: string; at: string; version: number;
    resolved: boolean }[];
  brainstorms: { id: string; title: string; updated_at: string }[];
  may: SopMay; hints: Record<string, string>; last_version: number;
  choices?: {
    owners: { id: string; name: string; side: "client" | "practice" }[];
    teams: { id: string; name: string }[];
    people: { id: string; name: string }[];
    kpis: { id: string; name: string }[];
  };
}

/** What someone in the audience reads: the latest published version. */
export interface SopPortal {
  id: string; title: string; version: number; published_at: string; change_note: string;
  minor: boolean; purpose: string; applies_when: string; roles: Role[]; steps: Step[];
  sections: Section[]; owner: string; category: string; review_date: string | null;
  kpis: { id: string; name: string }[]; map_svg: string | null;
  attachments: { id: string; name: string; kind: "image" | "pdf"; url: string }[];
  asked: boolean; read: boolean; read_at: string | null; read_version: number | null;
  read_by: string | null; may: SopMay; reads?: Reads;
}

export interface MediaStatus {
  set: boolean; last4: string; verified_at: string | null; model: string;
  input_usd_per_mtok: string; output_usd_per_mtok: string;
  about_per_minute: { audio: string; video: string };
  limits: { audio: { minutes: number; mb: number }; video: { minutes: number; mb: number } };
  refused: string; notice: string; detail?: string;
}

export type ProposalKind = "draft" | "map" | "checklist" | "measures";

export interface DraftPayload {
  title: string; purpose: string; applies_when: string; roles: Role[];
  steps: { text: string; role: string; warning: string }[]; category: string;
}

export interface Proposal {
  id: string; kind: ProposalKind; label: string; state: "proposed" | "accepted" | "discarded";
  payload: Record<string, unknown>; why: string; result: Record<string, unknown>;
  decided_by: string; cost_usd: string | null;
  diff?: { fields?: Record<string, { from: string; to: string }>;
    steps?: { change: "same" | "added" | "removed"; text: string }[] };
}

export interface Price {
  kind: string; estimate_usd: string; tier: string; model: string; images: number;
  refused?: string; spent_usd?: string;
}

export interface Brainstorm {
  id: string; title: string; tier: "standard" | "deep"; company: SopCompany;
  sop: { id: string; title: string; status: SopStatus } | null;
  sources: { id: string; kind: string; label: string; title: string;
    state: "ready" | "reading" | "failed"; error: string; chars: number;
    seconds: number | null; kept: boolean; preview: string }[];
  messages: { id: string; role: "user" | "claude"; text: string; by: string; at: string;
    cost_usd: string | null }[];
  proposals: Proposal[]; spent_usd: string; price: Price; refused: string;
  media: MediaStatus;
  homes: { goals: { id: string; name: string }[];
    projects: { id: string; name: string; goal: string }[] };
  updated_at: string;
}

export interface PackChoices {
  runs: { id: string; name: string; tool: string; date: string }[];
  documents: { id: string; title: string; state: string }[];
  always: string[]; never: string; prompts: { title: string; prompt: string }[];
  may_edit_prompts: boolean;
}

export function longDay(value: string | null | undefined) {
  if (!value) return "";
  const d = value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

/** An SVG drawn by the server, shown as a picture: no script can run in it. */
export function svgSrc(svg: string) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function readsLine(r: { asked: number; read: number } | null | undefined) {
  if (!r || !r.asked) return "";
  return `${r.read} of ${r.asked} read`;
}
