import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { LibraryEntry, LibraryState, api } from "../lib/api";
import { StarterKpi } from "../lib/scorecard";
import { Modal } from "./shell";
import { Banner, Field, Pill } from "./ui";

const FEED_NAMES: Record<string, string> = {
  hand: "By hand", sheet: "Google Sheets", track: "Track", app: "This app", hubspot: "HubSpot",
  besty: "Besty", reviews: "Google reviews",
};
const KINDS = ["number", "percent", "money", "count", "duration", "rating"];
const DIRECTIONS: [string, string][] = [["higher", "Higher is better"],
  ["lower", "Lower is better"], ["range", "Within a range"]];
const CADENCES = ["daily", "weekly", "monthly", "quarterly"];
const ROLLUPS = ["sum", "average", "last"];

/** A library entry as the KPI form's starting values: nothing is made until
 *  the form is saved, as with a starter. */
export function asStarter(entry: LibraryEntry): StarterKpi {
  const out: Record<string, unknown> = {
    key: `library:${entry.key || entry.id}`, name: entry.name, kind: entry.kind,
    direction: entry.direction, cadence: entry.cadence, rollup: entry.rollup,
    behind_band_pct: entry.behind_band_pct ?? 10,
  };
  for (const f of ["duration_unit", "rating_scale", "target_value", "range_low", "range_high"] as const)
    if (entry[f] !== null && entry[f] !== undefined && entry[f] !== "") out[f] = entry[f];
  if (entry.guidance) out.note = entry.guidance.slice(0, 200);
  return out as StarterKpi;
}

/**
 * "From the library" (P8): the KPI library's four pages, Customers,
 * Operations, Team and Money. The base library, each Command Center's list
 * on top, and the practice's own entries. Using one fills in the new-KPI
 * form; editing a shipped one makes the practice's own copy.
 */
export function KpiLibraryPicker({ onPick, onClose }: {
  onPick: (kpi: StarterKpi) => void; onClose: () => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<LibraryState>({ queryKey: ["kpi-library"],
    queryFn: () => api.get<LibraryState>("/api/scorecard/library/") });
  const [page, setPage] = useState("customers");
  const [editing, setEditing] = useState<LibraryEntry | "new" | null>(null);
  const s = state.data;
  const shown = (s?.entries ?? []).filter((e) => e.page === page);
  const refresh = () => qc.invalidateQueries({ queryKey: ["kpi-library"] });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/scorecard/library/${id}/`),
    onSuccess: refresh,
  });
  return (
    <Modal label="The KPI library" title="From the library" onClose={onClose} wide>
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        Pick one to fill in the form; nothing is made until you save it. Your clients'
        scorecards are never changed by the library.
      </p>
      <div className="row tight" role="tablist" aria-label="Library pages" style={{ flexWrap: "wrap" }}>
        {(s?.pages ?? []).map((p) => (
          <button key={p.code} role="tab" aria-selected={page === p.code}
            className={page === p.code ? "primary small" : "small"}
            onClick={() => { setPage(p.code); setEditing(null); }}>{p.label}</button>
        ))}
        {s?.can_edit && (
          <button className="small ghost" onClick={() => setEditing("new")}>Add an entry</button>
        )}
      </div>
      {editing && <EntryForm entry={editing === "new" ? null : editing} page={page}
        onDone={() => { setEditing(null); refresh(); }} onCancel={() => setEditing(null)} />}
      {!s ? <p className="muted">Loading the library…</p> : (
        <ul className="library-list">
          {shown.map((e) => (
            <li key={`${e.source}:${e.id ?? e.key}`} className="library-entry">
              <div>
                <strong>{e.name}</strong>{" "}
                {e.source === "center" && <Pill>{e.center_name}</Pill>}
                {e.source === "practice" && <Pill kind="ok">{e.key ? "Yours, edited" : "Yours"}</Pill>}
                <div className="small muted">
                  {e.kind}{e.duration_unit ? ` in ${e.duration_unit}` : ""} ·{" "}
                  {DIRECTIONS.find(([d]) => d === e.direction)?.[1].toLowerCase()} · {e.cadence},{" "}
                  {e.rollup === "last" ? "latest reading" : e.rollup}
                </div>
                {e.guidance && <div className="small">{e.guidance}</div>}
                {e.feeds.length > 0 && <div className="small muted">
                  Feeds: {e.feeds.map((f) => FEED_NAMES[f] ?? f).join(", ")}</div>}
              </div>
              <div className="row tight library-actions">
                <button className="primary small" aria-label={`Use ${e.name}`}
                  onClick={() => onPick(asStarter(e))}>Use</button>
                {s.can_edit && e.source !== "practice" && (
                  <button className="small ghost" onClick={() => setEditing(e)}>Edit for my practice</button>
                )}
                {s.can_edit && e.source === "practice" && (
                  <>
                    <button className="small ghost" onClick={() => setEditing(e)}>Edit</button>
                    <button className="small ghost" onClick={() => remove.mutate(e.id!)}>Remove</button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function EntryForm({ entry, page, onDone, onCancel }: {
  entry: LibraryEntry | null; page: string; onDone: () => void; onCancel: () => void;
}) {
  const [d, setD] = useState({
    name: entry?.name ?? "", page: entry?.page ?? page, kind: entry?.kind ?? "number",
    direction: entry?.direction ?? "higher", cadence: entry?.cadence ?? "weekly",
    rollup: entry?.rollup ?? "sum", guidance: entry?.guidance ?? "",
    duration_unit: entry?.duration_unit || "days", rating_scale: entry?.rating_scale ?? 5,
    behind_band_pct: entry?.behind_band_pct ?? 10, feeds: entry?.feeds ?? [],
  });
  const save = useMutation({
    mutationFn: () => entry?.source === "practice"
      ? api.patch(`/api/scorecard/library/${entry.id}/`, d)
      : api.post("/api/scorecard/library/", { ...d, ...(entry ? { source_key: entry.key } : {}) }),
    onSuccess: onDone,
  });
  const set = (k: string, v: unknown) => setD({ ...d, [k]: v });
  return (
    <form className="library-form" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {entry && entry.source !== "practice" && (
        <p className="small muted" style={{ marginTop: 0 }}>Your copy replaces this entry in your
          practice's library only.</p>
      )}
      <div className="row tight" style={{ flexWrap: "wrap" }}>
        <Field label="Name"><input aria-label="Entry name" value={d.name}
          onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Page"><select aria-label="Entry page" value={d.page}
          onChange={(e) => set("page", e.target.value)}>
          {["customers", "operations", "team", "money"].map((p) =>
            <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}</select></Field>
        <Field label="Kind"><select aria-label="Entry kind" value={d.kind}
          onChange={(e) => set("kind", e.target.value)}>
          {KINDS.map((k) => <option key={k}>{k}</option>)}</select></Field>
        <Field label="Direction"><select aria-label="Entry direction" value={d.direction}
          onChange={(e) => set("direction", e.target.value)}>
          {DIRECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Cadence"><select aria-label="Entry cadence" value={d.cadence}
          onChange={(e) => set("cadence", e.target.value)}>
          {CADENCES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Roll-up"><select aria-label="Entry roll-up" value={d.rollup}
          onChange={(e) => set("rollup", e.target.value)}>
          {ROLLUPS.map((r) => <option key={r}>{r}</option>)}</select></Field>
      </div>
      <Field label="Status bands"><input aria-label="Entry guidance" value={d.guidance}
        placeholder="On track at 95% or more; behind within 5%."
        onChange={(e) => set("guidance", e.target.value)} /></Field>
      <div className="row tight">
        <button className="primary small" type="submit" disabled={!d.name.trim() || save.isPending}>
          Save to the library</button>
        <button className="small ghost" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
