/**
 * The KPI scorecard (M5 part 1, docs/p6_m5_kpi_scorecard.md): what the API
 * sends and how a value is written. The server has already left out every
 * KPI and every per-person row the reader may not see; nothing here filters.
 */

export type Status = "on_track" | "behind" | "off_track";
export type Cadence = "daily" | "weekly" | "monthly" | "quarterly";
export type Kind = "number" | "percent" | "money" | "count" | "duration" | "rating";
export type Shape = "number_trend" | "gauge" | "progress" | "bars" | "line" | "status"
  | "leaderboard" | "my_row";
export type WindowKey = "this_week" | "this_month" | "this_quarter" | "year_to_date"
  | "last_year" | "custom";

export const STATUS_LABEL: Record<Status, string> = {
  on_track: "On track", behind: "Behind", off_track: "Off track",
};

export const WINDOWS: { key: WindowKey; label: string }[] = [
  { key: "this_week", label: "This week" }, { key: "this_month", label: "This month" },
  { key: "this_quarter", label: "This quarter" }, { key: "year_to_date", label: "Year to date" },
  { key: "last_year", label: "Last year" }, { key: "custom", label: "Custom dates…" },
];

export const CADENCE_NOUN: Record<Cadence, string> = {
  daily: "day", weekly: "week", monthly: "month", quarterly: "quarter",
};
export const CADENCE_LABEL: Record<Cadence, string> = {
  daily: "Daily", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly",
};
export const ROLLUP_WORDS: Record<string, string> = {
  sum: "sum", average: "average", last: "last reading",
};

export interface Point {
  period_start: string; label: string; value: number | null; target: number | null;
  status: Status | null; missing: boolean; edited: boolean; reading: string | null;
  entered_by: string; entered_at: string | null; source: string;
}

export interface Summary {
  value: number | null; target: number | null; status: Status | null; stale: boolean;
  stale_from?: string; missing: string | null; open_period?: boolean; carried?: boolean;
  periods: number; periods_in: number; full_target: number | null;
  days_left: number; elapsed: number;
}

export interface PersonRow {
  membership: string; name: string; you: boolean; value: number | null;
  target: number | null; status: Status | null; stale: boolean; rank?: number | null;
  summary: Summary; delta: Delta | null; spark: Point[]; history: Point[];
}

export interface Delta { change: number; better: boolean | null }

export interface KpiDef {
  id: string; name: string; kind: Kind; direction: "higher" | "lower" | "range";
  cadence: Cadence; rollup: "sum" | "average" | "last"; tile: Shape; unit: string;
  duration_unit: string; rating_scale: number | null; note: string; component: string;
  per_person: boolean; leaderboard: boolean; page: string; range_low: number | null;
  range_high: number | null; fixed_target: number | null; band: number | null;
  owner: string; owner_id: string | null; may_enter: boolean;
  /** A computed KPI's formula in words ("Revenue ÷ Bookings"); "" otherwise. */
  computed: string;
}

export interface Tile extends KpiDef {
  shape: Shape; summary: Summary | null; delta: Delta | null; spark: Point[];
  history: Point[]; rows: PersonRow[]; total: boolean; total_label?: string;
  each_target?: number | null;
}

export interface Notice {
  kpi: string; kpi_id: string; company: string; company_id: string;
  period_start: string; text: string; reminded_at: string;
}

export interface Board {
  exists: boolean;
  company: { id: string; name: string };
  week_start?: "monday" | "sunday";
  window: { key: WindowKey; label: string; first: string; last: string; text: string };
  pages: { id: string; name: string; audience: string }[];
  page: string | null;
  kpis: Tile[];
  may_set_up: boolean;
  may_enter: boolean;
  counts?: { in: number; of: number; on_track: number; behind: number; off_track: number };
  notices?: Notice[];
}

export interface EntryField {
  membership: string | null; name: string; you: boolean; value: number | null;
  reading: string | null; edited: boolean; last: number | null;
}

export interface EntryKpi extends KpiDef {
  page_name: string; period_start: string; period_label: string; target: number | null;
  fields: EntryField[];
}

export interface EntryForm {
  period: { day: string; week_start: string; label: string; closes: string; open: boolean };
  choices: { day: string; label: string }[];
  kpis: EntryKpi[];
  progress: { id: string; name: string; state: "in" | "waiting" | "yours"; owner: string }[];
  notices: Notice[];
}

export interface BulkSheet {
  cadence: Cadence;
  periods: { start: string; label: string }[];
  lines: (KpiDef & { membership: string | null; person: string;
    cells: { period_start: string; value: number | null }[] })[];
}

export interface ReadingHistory {
  kpi: string; period: string;
  changes: { value: number; previous: number | null; by: string; at: string }[];
}

export interface SetupPage {
  id: string; name: string; audience: string; team: string | null; archived: boolean;
  position: number;
}

export interface SetupKpi extends KpiDef {
  position: number; archived: boolean; audience: string; audience_team: string | null;
  person_total: "sum" | "average"; target_value: number | null; behind_band_pct: number;
  reading_owner: string | null; strategy_component: string;
  month_targets: Record<string, number>; people: string[];
  formula: "" | "sum" | "difference" | "ratio" | "average";
  source_a: string | null; source_b: string | null;
}

export interface Starter {
  discipline: string; name: string;
  kpis: ({ key: string; name: string; kind: Kind } & Record<string, unknown>)[];
}

export interface SetupState {
  company: { id: string; name: string };
  exists: boolean;
  week_start: "monday" | "sunday";
  pages: SetupPage[];
  kpis: SetupKpi[];
  teams: { id: string; name: string; is_default: boolean }[];
  owners: { id: string; name: string; side: "practice" | "client" }[];
  people: { id: string; name: string }[];
  starters: Starter[];
}

// ------------------------------------------------------------ formatting

const trim = (n: number, places: number) =>
  n.toLocaleString("en-US", { maximumFractionDigits: places, minimumFractionDigits: 0 });

/** A value in the KPI's own unit: "78%", "$184,200", "36 h", "11 min", "4.7". */
export function fmt(def: Pick<KpiDef, "kind" | "duration_unit">, value: number | null,
  opts: { bare?: boolean; compact?: boolean } = {}): string {
  if (value === null || value === undefined) return "—";
  switch (def.kind) {
    case "percent": return `${trim(value, 1)}${opts.bare ? "" : "%"}`;
    case "money":
      // The grid's cells: "$45.7k", "$1.2M".
      if (opts.compact && Math.abs(value) >= 10000) {
        const [n, unit] = Math.abs(value) >= 1e6 ? [value / 1e6, "M"] : [value / 1e3, "k"];
        return `${value < 0 ? "-" : ""}$${trim(Math.abs(n), 1)}${unit}`;
      }
      return `${value < 0 ? "-" : ""}$${trim(Math.abs(value), Math.abs(value) >= 1000 ? 0 : 2)}`;
    case "count": return trim(value, 0);
    case "duration": {
      if (opts.bare) return trim(value, 1);
      const unit = def.duration_unit === "minutes" ? "min"
        : def.duration_unit === "days" ? (value === 1 ? "day" : "days") : "h";
      return `${trim(value, 1)} ${unit}`;
    }
    case "rating": return trim(value, 1);
    default: return trim(value, 2);
  }
}

/** The change since the last reading: "3 pts" for a percent, "2 h", "$1,200". */
export function fmtChange(def: Pick<KpiDef, "kind" | "duration_unit">, change: number): string {
  const size = Math.abs(change);
  if (def.kind === "percent") return `${trim(size, 1)} pts`;
  return fmt(def, size);
}

/** "target 82%", "keep under 40 h", "48 to 72 hours". */
export function targetText(def: KpiDef, target: number | null): string {
  if (def.direction === "range") {
    if (def.range_low === null || def.range_high === null) return "";
    return `range ${fmt(def, def.range_low)} to ${fmt(def, def.range_high)}`;
  }
  if (target === null) return "no target";
  return def.direction === "lower" ? `keep under ${fmt(def, target)}` : `target ${fmt(def, target)}`;
}

/** The unit beside an entry field. */
export function unitLabel(def: Pick<KpiDef, "kind" | "duration_unit" | "rating_scale">): string {
  switch (def.kind) {
    case "percent": return "%";
    case "money": return "$";
    case "duration": return def.duration_unit || "hours";
    case "rating": return `of ${def.rating_scale ?? 5}`;
    case "count": return "count";
    default: return "";
  }
}

export const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
