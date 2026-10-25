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
  /** Part 3: where a fed KPI's readings come from, and why its last read
   *  failed (only for the practice and the reading owner). */
  feed?: { kind: "sheet" | "track" | "app"; text: string; error: string } | null;
}

export interface Tile extends KpiDef {
  shape: Shape; summary: Summary | null; delta: Delta | null; spark: Point[];
  history: Point[]; rows: PersonRow[]; total: boolean; total_label?: string;
  each_target?: number | null;
  /** The grid's columns are the window's own periods, with its roll-up beside. */
  history_is_window?: boolean;
}

export interface Notice {
  /** A missing reading, or a feed whose last read failed (part 3). */
  kind?: "reminder" | "feed";
  kpi: string; kpi_id: string; company: string; company_id: string;
  period_start: string | null; text: string; reminded_at: string | null;
}

export interface Board {
  exists: boolean;
  /** The practice's own scorecard ("My practice"). */
  practice?: boolean;
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
  /** Part 2: which bonus tabs this reader gets (decision 7). */
  bonus_views?: BonusViewKey[];
}

export type BonusViewKey = "mine" | "team" | "all";
export const BONUS_VIEW_LABEL: Record<BonusViewKey, string> = {
  mine: "My bonus", team: "Team bonus", all: "All bonuses" };

export interface BonusTier { from: number; share: number }

export interface BonusComponentRow {
  kpi: string; name: string; kind: KpiDef["kind"]; direction: string; rollup: string;
  weight: number; tiers: BonusTier[];
  value: number | null; value_text: string; target: number | null; target_text: string;
  expected: number | null; expected_text: string; achievement: number | null;
  tier: number | null; share: number; earned?: number;
  readings: { period_start: string; label: string; value: number }[];
  tracked: boolean; next?: { text: string; gain: number } | null;
}

export interface BonusRow {
  membership: string; name: string; full_amount?: number; amount?: number;
  prorated: boolean; days_on: number; days: number; joined_on: string | null;
  left_on: string | null; earned?: number; components: BonusComponentRow[];
  next?: string | null;
}

export interface BonusPlanHead {
  id: string; name: string; series: string; period: "monthly" | "quarterly";
  period_start: string; period_end: string; period_label: string; days_left: number;
  ended: boolean; closed: boolean; closed_at: string | null; closed_by: string;
  straight_line: boolean; cap_pct: number; amount: number;
  totals?: { people: number; earned: number; full: number } | null;
  corrections?: { membership: string; name: string; kpi: string; period: string;
    frozen: number | null; now: number | null }[];
  next_exists?: boolean;
}

export interface BonusEditorChoices {
  kpis: { id: string; name: string; kind: KpiDef["kind"]; direction: string; rollup: string;
    cadence: Cadence; target: number | null; people: string[] }[];
  members: { membership: string; name: string }[];
}

export interface BonusPayload {
  views: BonusViewKey[]; view: BonusViewKey | null;
  may_build: boolean; may_close: boolean; may_confirm_reopen: boolean; sees_amounts: boolean;
  practice: boolean; practice_name: string;
  editor?: BonusEditorChoices;
  // My bonus
  plan?: BonusPlanHead; me?: BonusRow;
  earlier?: { id: string; label: string; short: string; earned: number; full: number;
    closed: boolean }[];
  choices?: { id: string; label: string }[];
  // Team bonus and All bonuses
  periods?: { key: string; label: string }[]; period?: string | null;
  plans?: { plan: BonusPlanHead; rows: BonusRow[] }[];
  payroll?: { name: string; plan: string; period: string; earned: number }[];
  payroll_open?: string[];
}

export interface BonusPlanDraft {
  id?: string; name: string; period: "monthly" | "quarterly"; period_start: string;
  amount: string; straight_line: boolean; cap_pct: number;
  components: { kpi: string; weight: number | string; target_value: number | string | null;
    tiers: BonusTier[] }[];
  people: { membership: string; amount: string | null; joined_on: string | null;
    left_on: string | null }[];
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
  /** Weeks, newest first, each with the month it starts in for grouping. */
  choices: { day: string; label: string; month?: string }[];
  kpis: EntryKpi[];
  progress: { id: string; name: string; state: "in" | "waiting" | "yours"; owner: string }[];
  notices: Notice[];
}

export interface BulkSheet {
  cadence: Cadence;
  /** The cadences this person has something to enter in. */
  cadences?: Cadence[];
  periods: { start: string; label: string }[];
  lines: (KpiDef & { membership: string | null; person: string;
    cells: { period_start: string; value: number | null }[] })[];
  /** The first period shown, the earliest the picker offers, and its
   *  periods newest first (empty for daily, which takes a date). */
  from?: string | null; earliest?: string;
  choices?: { start: string; label: string }[];
  /** Where Earlier and Later go: a first period, "" for the latest, null for nowhere. */
  earlier?: string | null; later?: string | null;
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

export type StarterKpi = { key: string; name: string; kind: Kind } & Record<string, unknown>;

export interface Starter {
  discipline: string; name: string;
  kpis: StarterKpi[];
}

export interface SetupState {
  company: { id: string; name: string };
  /** The practice's own scorecard ("My practice"). */
  practice?: boolean;
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

/** Part 3: a KPI's Google Sheet feed, as the mapping screen gets it. */
export interface FeedConfig {
  spreadsheet_id: string; spreadsheet_name: string; tab: string; mode: "column" | "cell";
  refresh: "hourly" | "daily"; active: boolean;
  date_column: string; date_header: string; value_column: string; value_header: string;
  name_column: string; name_header: string; header_row: number | null; cell: string;
  people: Record<string, string>; last_run_at: string | null; last_success_at: string | null;
  last_error: string; account: string;
}

export interface FeedState {
  google: { ready: boolean; account: string; connected: boolean; reconnect: boolean; refusal: string };
  kpi: { id: string; name: string; per_person: boolean; cadence: Cadence; cadence_noun: string;
    people: { id: string; name: string }[] };
  feed: FeedConfig | null;
}

export interface SheetGrid {
  spreadsheet_id: string; title: string; tabs: { title: string; id: number }[]; tab: string;
  rows: string[][]; more_rows: number; header_row: number | null; account: string;
}

export interface FeedPreview {
  header_row: number | null;
  periods: { start: string; label: string; person: string; value: number; had: number | null;
    what: "new" | "update" | "same" | "kept" | "open"; says: string; rows: number[] }[];
  more: number;
  counts: Record<"new" | "update" | "same" | "kept" | "open", number>;
  skipped: { row: number; why: string }[]; skipped_more: number;
  unmatched: { name: string; rows: number }[];
  cell?: { ref: string; value: number | null; period: string; closes: string };
}

/** 0 -> A, 25 -> Z, 26 -> AA: a sheet's column letters. */
export function columnLetter(index: number): string {
  let out = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) out = String.fromCharCode(65 + ((n - 1) % 26)) + out;
  return out;
}

/** Rows pasted from a spreadsheet or a CSV file: tabs if there are any,
 *  else commas, with quoted cells kept whole. */
export function parsePasted(text: string): string[][] {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "").split("\n");
  const tabbed = lines.some((l) => l.includes("\t"));
  return lines.map((line) => {
    if (tabbed) return line.split("\t").map((c) => c.trim());
    const cells: string[] = [];
    let cell = ""; let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (quoted) {
        if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++; }
        else if (ch === '"') quoted = false;
        else cell += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === ",") { cells.push(cell.trim()); cell = ""; }
      else cell += ch;
    }
    cells.push(cell.trim());
    return cells;
  });
}
