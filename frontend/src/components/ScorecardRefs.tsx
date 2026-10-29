import { Ref, SetupKpi, SetupState } from "../lib/scorecard";

/** Where a live target or a computed KPI's operand comes from, in words. */
const KIND_WORDS: Record<string, string> = {
  value: "Its readings",
  target: "Its target",
  kpi: "Another KPI's latest reading",
  sheet_column: "A column of its sheet",
  sheet_cell: "A cell of its sheet",
  track: "A field of its Track feed",
  hubspot: "A field of its HubSpot feed",
  besty: "A field of its Besty feed",
};

/** The feed kinds a KPI can name, by the feed it has: a KPI with no feed
 *  yet may name any, and its number comes with the feed's first read. */
function feedKinds(kpi: SetupKpi | null | undefined): Ref["kind"][] {
  const feed = kpi?.feed;
  if (!feed) return ["sheet_column", "sheet_cell", "track", "hubspot", "besty"];
  if (feed.kind === "sheet") return [feed.mode === "cell" ? "sheet_cell" : "sheet_column"];
  if (feed.kind === "track" || feed.kind === "hubspot" || feed.kind === "besty") return [feed.kind];
  return [];
}

/** The choice of where a number comes from, and the one field it needs:
 *  a KPI, a column (heading or letter), a cell, or a Track, HubSpot or Besty field. */
export function RefPicker({ id, label, value, onChange, base, of, state, kpis, invalid }: {
  id: string; label: string; value: Ref | null | undefined; onChange: (r: Ref | null) => void;
  /** The first choices: "typed" for a target, "value" and "target" for an operand. */
  base: { kind: Ref["kind"]; label: string }[];
  /** The KPI whose feed the column, cell or field belongs to. */
  of: SetupKpi | null | undefined;
  state: SetupState; kpis?: SetupKpi[]; invalid?: boolean;
}) {
  const kind = value?.kind || base[0].kind;
  const kinds = [...base.map((b) => b.kind), ...(kpis ? ["kpi" as const] : []), ...feedKinds(of)];
  const words = (k: string) => base.find((b) => b.kind === k)?.label ?? KIND_WORDS[k];
  const set = (patch: Partial<Ref>) => onChange({ ...(value ?? { kind }), ...patch } as Ref);
  const fields = kind === "track" ? state.fields?.track : kind === "hubspot" ? state.fields?.hubspot
    : kind === "besty" ? state.fields?.besty : null;
  return (
    <>
      <label className="sc-form-field"><span>{label}</span>
        <select id={id} value={kind} aria-invalid={invalid}
          onChange={(e) => {
            const k = e.target.value as Ref["kind"];
            onChange(base.some((b) => b.kind === k) && (k === "" || k === "value") ? null : { kind: k });
          }}>
          {kinds.map((k) => <option key={k} value={k}>{words(k)}</option>)}
        </select></label>
      {kind === "kpi" && kpis && (
        <label className="sc-form-field"><span>Taken from</span>
          <select value={value?.kpi ?? ""} onChange={(e) => set({ kpi: e.target.value })}>
            <option value="">Choose…</option>
            {kpis.map((k) => <option key={k.id} value={k.id}>{k.name}{k.helper ? " (helper)" : ""}</option>)}
          </select></label>
      )}
      {kind === "sheet_column" && (
        <label className="sc-form-field"><span>Column heading or letter</span>
          <input value={value?.header || value?.column || ""} placeholder="Total Homeowners"
            onChange={(e) => {
              const text = e.target.value;
              // A letter or two is a column's letter; anything else its heading.
              set(/^[A-Z]{1,2}$/.test(text.trim())
                ? { column: text.trim().toUpperCase(), header: "" } : { header: text, column: "" });
            }} /></label>
      )}
      {kind === "sheet_cell" && (
        <label className="sc-form-field"><span>Cell</span>
          <input value={value?.cell ?? ""} placeholder="B2" onChange={(e) => set({ cell: e.target.value })} /></label>
      )}
      {fields && (
        <label className="sc-form-field"><span>Field</span>
          <select value={value?.measure ?? ""} onChange={(e) => set({ measure: e.target.value })}>
            <option value="">Choose…</option>
            {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select></label>
      )}
    </>
  );
}
