/** The worksheet engine (P12, docs/p12_tools.md): what /api/tools/ and
 * /api/tool-runs/ send. */

export type FieldType = "text" | "long_text" | "number" | "money" | "percent" | "date" |
  "choice" | "person" | "people" | "table" | "computed";
export const INPUT_TYPES: FieldType[] = ["text", "long_text", "number", "money", "percent",
  "date", "choice", "person", "people"];
export const FIELD_TYPE_LABEL: Record<FieldType, string> = {
  text: "Text", long_text: "Long text", number: "Number", money: "Money", percent: "Percent",
  date: "Date", choice: "Choice", person: "A person", people: "People", table: "Table",
  computed: "Computed" };
export const FORMATS = ["number", "money", "percent", "text", "list", "hours", "people"] as const;
export type Format = (typeof FORMATS)[number];

export interface ToolField {
  key: string; label: string; type: FieldType; options?: string[]; formula?: string;
  format?: Format; columns?: ToolField[]; max_lines?: number; help?: string;
}
export interface ToolSection { title: string; fields: ToolField[] }
export interface ToolResult { key: string; label: string; formula: string; format?: Format;
  note?: string }
export interface ToolView { type: "org_chart" | "cadence"; table?: string; name?: string;
  parent?: string; person?: string; agenda?: string }
export interface ToolDefinition {
  sections: ToolSection[]; results?: ToolResult[]; views?: ToolView[]; actions?: string[];
}

export interface ToolSummary { ref: string; name: string; description: string; shipped: boolean;
  source_key?: string }
export interface ToolFull { key: string; id: string | null; name: string; description: string;
  definition: ToolDefinition; shipped: boolean; source_key?: string; from_ai?: boolean }

export type RowValues = Record<string, unknown> & { _flag?: boolean };
export type RunValues = Record<string, unknown>;

export interface Cell { value: unknown; text: string; error: string }
export interface Evaluation {
  values: RunValues;
  computed: Record<string, Cell>;
  tables: Record<string, Record<string, Cell>[]>;
  results: { key: string; label: string; format: Format; value: unknown; text: string;
    error: string; note: string; numeric: boolean }[];
}

export interface RunSummary {
  id: string; name: string; tool_name: string; tool_key: string; tool_id: string | null;
  run_date: string; company: { id: string; name: string; is_practice: boolean };
  shared_with_client: boolean; updated_at: string; may_edit: boolean;
}
export interface RunFull extends RunSummary {
  definition: ToolDefinition; values: RunValues; evaluation: Evaluation;
  choices?: { people: string[]; kpis: { id: string; name: string; cadence: string }[];
    sop_sources: { id: string; label: string }[]; has_plan: boolean };
}

export interface Shelf { tools: ToolSummary[]; recent: RunSummary[]; may_build: boolean }

export interface CalendarPreview {
  events: { name: string; cadence: string; day: string; first: string; time: string;
    minutes: number; rrule: string; attendees: string[]; agenda: string[]; note: string }[];
  connected: boolean; demo: boolean;
}
