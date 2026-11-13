/** The plans engine (P11, docs/p11_plans_engine.md): what /api/plans/ sends. */

export type HorizonKey = "picture" | "year" | "quarter" | "month" | "week";
export const HORIZON_KEYS: HorizonKey[] = ["picture", "year", "quarter", "month", "week"];
/** The defaults; a practice renames them under Settings → Branding → Wording. */
export const DEFAULT_HORIZONS: Record<HorizonKey, string> = {
  picture: "Three-year picture",
  year: "This year's goals",
  quarter: "This quarter's priorities",
  month: "This month's plan",
  week: "This week's sprint",
};

export type PlanStatus = "on_track" | "off_track" | "done" | "dropped";
export const PLAN_STATUSES: { key: PlanStatus; label: string }[] = [
  { key: "on_track", label: "On track" }, { key: "off_track", label: "Off track" },
  { key: "done", label: "Done" }, { key: "dropped", label: "Dropped" }];

export interface PlanTask {
  id: string; title: string; status: string; status_label: string; done: boolean;
  due_date: string | null; owner: string; client_owner: string; team: string;
  team_id: string | null; project: string;
}

/** A teammate's sprint task in This week: read only, nothing to open. */
export interface TeammateTask {
  title: string; owner: string; status: string; status_label: string; done: boolean;
  read_only: true;
}

export interface PlanKpi {
  id: string; name: string; value_text: string; target_text: string;
  status: "on_track" | "behind" | "off_track" | null; status_label: string; period: string;
}

export interface PlanItemRow {
  id: string; horizon: HorizonKey; period_start: string; period_label: string;
  title: string; done_means: string; status: PlanStatus; status_label: string;
  owner: { id: string; name: string } | null;
  serves: { id: string; title: string; horizon: HorizonKey } | null;
  served_by: { id: string; title: string; horizon: HorizonKey; status: PlanStatus;
    status_label: string; period_label: string }[];
  goal: { id: string; title: string } | null;
  project: { id: string; title: string } | null;
  client_team: { id: string; name: string } | null;
  target_value: number | null;
  tasks: PlanTask[]; kpis: PlanKpi[];
  state: "proposed" | "accepted" | "discarded"; source: string; source_label: string;
  drew_on: string[]; from_ai_app: boolean; from_ai: boolean; proposed_by: string;
  may_edit: boolean;
}

export interface PlanColumn {
  key: HorizonKey; name: string; period_start: string; period_label: string;
  is_current: boolean; previous: string; next: string;
  items: PlanItemRow[]; proposals: PlanItemRow[];
  closed: { summary: string; closed_at: string } | null;
  last_close: { summary: string; period_label: string; closed_at: string } | null;
  close_offer: { period_start: string; label: string; late: boolean } | null;
}

export interface PlanAccess {
  horizons: HorizonKey[]; edits: boolean; may_close: boolean; may_draft: boolean;
  sees_tray: boolean; may_add: HorizonKey[]; may_propose: HorizonKey[];
}

export interface PlanChoices {
  people: { id: string; name: string; side: "practice" | "client" }[];
  goals: { id: string; title: string }[];
  projects: { id: string; title: string }[];
  tasks: { id: string; title: string; due_date: string | null }[];
  kpis: { id: string; name: string }[];
  teams: { id: string; name: string }[];
}

export interface PlanPayload {
  company: { id: string; name: string; is_practice: boolean; fiscal_year_start: number;
    week_start: string; sprint_team_tasks?: boolean };
  today: string; access: PlanAccess; horizons: PlanColumn[]; choices: PlanChoices | null;
}

export interface WeekPayload {
  company: { id: string; name: string }; name: string; period_start: string;
  period_label: string;
  sprint: { id: string; title: string; done_means: string; status: PlanStatus;
    status_label: string; owner: { id: string; name: string } | null; may_edit: boolean } | null;
  mine: PlanTask[]; team: (PlanTask | TeammateTask)[]; others: PlanTask[];
  /** P11, 2026-11-13: each of the person's teams, the sprint's tasks on it. */
  team_lines?: { team: string; done: number; total: number }[];
  /** Whether this company shows teammates' sprint tasks. */
  teammates?: boolean;
  serves: { id: string; title: string; horizon: HorizonKey; name: string;
    status_label: string }[];
  done?: number; total?: number; access: PlanAccess;
}

export interface PlanSource { type: string; id: string; label: string; detail: string }

export interface SourcesPayload {
  sources: PlanSource[];
  ai: { estimate_usd: string; used_today: number; cap: number; refused: string };
}

export interface CloseWalk {
  horizon: "week" | "month" | "quarter"; period_start: string; period_label: string;
  sprint: string;
  rows: { kind: "task" | "item"; id: string; title: string; status: string;
    suggested: "done" | "not_done" }[];
  next: { period_start: string; period_label: string };
}

export interface PlansIndex {
  plans: { id: string; company_id: string; name: string; is_practice: boolean;
    week: { sprint: string; done: number; total: number; off_track: number } | null }[];
  names: Record<HorizonKey, string>;
}

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

/** "about $0.12": the price said before the press. */
export function about(usd: string | number | null | undefined) {
  return `about $${Number(usd ?? 0).toFixed(2)}`;
}
