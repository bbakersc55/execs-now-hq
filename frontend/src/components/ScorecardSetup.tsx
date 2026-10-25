import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { Modal } from "./shell";
import { Banner, Card } from "./ui";
import { Company, Me, api } from "../lib/api";
import { SetupKpi, SetupPage, SetupState, Starter, StarterKpi, fmt } from "../lib/scorecard";
import { useWords } from "../lib/words";
import { StartCard } from "../screens/Scorecard";

const AUDIENCE: Record<string, string> = {
  everyone: "Everyone at the company", leadership: "Senior leadership and up",
  team: "One team", each_person: "Each person sees their own",
};
const KPI_AUDIENCE: Record<string, string> = { page: "Same as its page", ...AUDIENCE };
delete KPI_AUDIENCE.everyone;
/** "My practice": the practice's own people, and no teams. */
const PRACTICE_AUDIENCE: Record<string, string> = {
  everyone: "Everyone at the practice", leadership: "The practice owner and associates",
  each_person: "Each person sees their own", owner: "The practice owner only",
};
const PRACTICE_KPI_AUDIENCE: Record<string, string> = { page: "Same as its page", ...PRACTICE_AUDIENCE };
delete PRACTICE_KPI_AUDIENCE.everyone;
const KINDS = { number: "Number", percent: "Percent", money: "Money", count: "Count",
  duration: "Duration", rating: "Rating" };
const DIRECTIONS = { higher: "Higher is better", lower: "Lower is better", range: "Within a range" };
const CADENCES = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly" };
const ROLLUPS = { sum: "Sum", average: "Average", last: "Last" };
const TILES = { number_trend: "Number with trend", gauge: "Gauge", progress: "Progress",
  bars: "Bars by period", line: "Line", status: "Status", leaderboard: "Leaderboard",
  my_row: "My row" };
const COMPONENTS = { "": "None", vision: "Vision", people: "People", data: "Data",
  issues: "Issues", process: "Process", traction: "Traction" };
const FORMULAS = { sum: "first + second", difference: "first − second",
  ratio: "first ÷ second", average: "average of the two" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type Draft = Record<string, unknown> & { month_targets?: Record<string, string | number> };

/**
 * The company page's scorecard card (M5 part 1): only the practice owner and
 * associates set a scorecard up (decided after the mock-up). Pages and their
 * audiences, the week start, and each KPI's definition; KPIs reorder by drag
 * (or the arrows) and archive with their readings kept. Every change is in
 * Activity.
 */
export function ScorecardSetup({ me, company }: { me: Me; company: Company }) {
  const w = useWords();
  const qc = useQueryClient();
  const { hash, search } = useLocation();
  const box = useRef<HTMLDivElement>(null);
  const key = ["scorecard-setup", company.id];
  const state = useQuery<SetupState>({
    queryKey: key, queryFn: () => api.get<SetupState>(`/api/scorecard/setup/?company=${company.id}`),
    enabled: me.role === "FF" || me.role === "CF",
  });
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  // A starter KPI fills the new-KPI form in; nothing is made until Save.
  const [starter, setStarter] = useState<StarterKpi | null>(null);
  const [newPage, setNewPage] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);
  useEffect(() => {
    if (state.data && hash === "#scorecard-setup") box.current?.scrollIntoView?.({ block: "start" });
  }, [state.data !== undefined, hash]); // eslint-disable-line react-hooks/exhaustive-deps
  // From the scorecard view's "Start the scorecard": ?starter=<key> opens it here.
  useEffect(() => {
    const wanted = new URLSearchParams(search).get("starter");
    const all = (state.data as (SetupState & { starters?: Starter[] }) | undefined)?.starters ?? [];
    const found = all.flatMap((g) => g.kpis).find((k) => k.key === wanted);
    if (found) { setStarter(found); setEditing("new"); }
  }, [state.data !== undefined, search]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["scorecard", company.id] });
  };
  const act = useMutation({
    mutationFn: ({ method, url, body }: { method: "post" | "patch"; url: string; body?: unknown; done?: string }) =>
      api[method](url, body),
    onSuccess: (_r, v) => { refresh(); setNote(v.done ? { kind: "ok", text: v.done } : null); },
    onError: (e: Error) => setNote({ kind: "bad", text: e.message }),
  });

  if (!(me.role === "FF" || me.role === "CF") || !company.is_client_company) return null;
  const s = state.data;
  if (!s || !Array.isArray(s.pages) || !Array.isArray(s.kpis)) return null;
  const livePages = s.pages.filter((p) => !p.archived);
  const live = s.kpis.filter((k) => !k.archived);
  const archived = s.kpis.filter((k) => k.archived);

  const move = (page: SetupPage, ids: string[]) =>
    act.mutate({ method: "post", url: "/api/scorecard/kpis/order/", body: { page: page.id, ids } });

  return (
    <div id="scorecard-setup" ref={box}>
      <Card title={w.Scorecard} actions={s.exists && live.length > 0
        ? <Link className="btn small" to={`/companies/${company.id}/scorecard`}>Open the {w.scorecard}</Link> : undefined}>
        {note && <Banner kind={note.kind}>{note.text}</Banner>}
        {live.length === 0 && (
          <StartCard compact companyId={company.id}
            onPick={(k) => { setStarter(k); setEditing("new"); }} />
        )}
        {s.exists && (
          <div className="row tight sc-setup-row">
            <label htmlFor="sc-week" className="small">The week runs</label>
            <select id="sc-week" value={s.week_start}
              onChange={(e) => act.mutate({ method: "patch", url: "/api/scorecard/setup/",
                body: { company: company.id, week_start: e.target.value }, done: "The week start is saved." })}>
              <option value="monday">Monday to Sunday</option>
              <option value="sunday">Sunday to Saturday</option>
            </select>
          </div>
        )}

        {livePages.map((page, pi) => {
          const kpis = live.filter((k) => k.page === page.id).sort((a, b) => a.position - b.position);
          const ids = kpis.map((k) => k.id);
          return (
            <div key={page.id} className="sc-setup-page">
              <PageLine page={page} teams={s.teams} practice={!!s.practice} first={pi === 0} last={pi === livePages.length - 1}
                empty={kpis.length === 0}
                onSave={(body, done) => act.mutate({ method: "patch", url: `/api/scorecard/pages/${page.id}/`, body, done })}
                onMove={(dir) => {
                  const order = livePages.map((p) => p.id);
                  const at = order.indexOf(page.id);
                  [order[at], order[at + dir]] = [order[at + dir], order[at]];
                  act.mutate({ method: "post", url: "/api/scorecard/pages/order/", body: { company: company.id, ids: order } });
                }}
                onArchive={() => act.mutate({ method: "post", url: `/api/scorecard/pages/${page.id}/archive/`,
                  done: `The page “${page.name}” is archived.` })} />
              {kpis.length === 0 ? <p className="small muted">No {w.kpis} on this page.</p> : (
                <ul className="sc-setup-kpis">
                  {kpis.map((k, i) => (
                    <li key={k.id} draggable onDragStart={() => setDragging(k.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => {
                        if (!dragging || dragging === k.id || !ids.includes(dragging)) return;
                        const order = ids.filter((x) => x !== dragging);
                        order.splice(order.indexOf(k.id), 0, dragging);
                        setDragging(null);
                        move(page, order);
                      }}
                      className={dragging === k.id ? "dragging" : ""}>
                      <span className="sc-drag" aria-hidden="true">⋮⋮</span>
                      <span className="sc-setup-name">{k.name}
                        <span className="small muted"> · {KINDS[k.kind]}, {CADENCES[k.cadence]}, {TILES[k.tile]}
                          {k.per_person ? `, per person (${k.people.length})` : ""}
                          {k.computed ? ` · computed: ${k.computed}`
                            : k.owner ? ` · entered by ${k.owner}` : " · no reading owner"}
                          {k.target_value !== null ? ` · target ${fmt(k, k.target_value)}` : ""}
                          {Object.keys(k.month_targets).length ? " · seasonal" : ""}</span></span>
                      <span className="sc-setup-tools">
                        <button className="ghost small" aria-label={`Move ${k.name} up`} disabled={i === 0}
                          onClick={() => { const o = [...ids]; [o[i - 1], o[i]] = [o[i], o[i - 1]]; move(page, o); }}>↑</button>
                        <button className="ghost small" aria-label={`Move ${k.name} down`} disabled={i === kpis.length - 1}
                          onClick={() => { const o = [...ids]; [o[i + 1], o[i]] = [o[i], o[i + 1]]; move(page, o); }}>↓</button>
                        <button className="ghost small" aria-label={`Edit ${k.name}`}
                          onClick={() => setEditing(editing === k.id ? null : k.id)}>Edit</button>
                        <button className="ghost small" aria-label={`Archive ${k.name}`}
                          onClick={() => act.mutate({ method: "post", url: `/api/scorecard/kpis/${k.id}/archive/`,
                            done: `${k.name} is archived; its readings are kept.` })}>Archive</button>
                      </span>
                      {editing === k.id && (
                        <KpiForm state={s} kpi={k} onDone={(text) => { setEditing(null); refresh(); setNote({ kind: "ok", text }); }} />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}

        {s.exists && (
          <div className="row tight sc-setup-row">
            <button className="primary small" onClick={() => {
              setStarter(null); setEditing(editing === "new" ? null : "new"); }}>
              Add {w.aKpi}</button>
            <input aria-label="New page name" placeholder="New page, e.g. Sales" value={newPage}
              onChange={(e) => setNewPage(e.target.value)} />
            <button className="small" disabled={!newPage.trim()} onClick={() => {
              act.mutate({ method: "post", url: "/api/scorecard/pages/",
                body: { company: company.id, name: newPage }, done: `The page “${newPage.trim()}” is added.` });
              setNewPage("");
            }}>Add the page</button>
          </div>
        )}
        {!s.exists && live.length === 0 && (
          <button className="small" onClick={() => act.mutate({ method: "post", url: "/api/scorecard/setup/",
            body: { company: company.id } })}>Or start with an empty {w.scorecard}</button>
        )}
        {editing === "new" && (
          <KpiForm key={starter?.key ?? "blank"} state={s} kpi={null} initial={starter}
            onCancel={() => { setEditing(null); setStarter(null); }}
            onDone={(text) => { setEditing(null); setStarter(null); refresh(); setNote({ kind: "ok", text }); }} />
        )}

        {(archived.length > 0 || s.pages.some((p) => p.archived)) && (
          <details className="sc-archived">
            <summary className="small">Archived</summary>
            {archived.map((k) => (
              <div key={k.id} className="row tight">
                <span>{k.name}</span>
                <button className="ghost small" aria-label={`Restore ${k.name}`}
                  onClick={() => act.mutate({ method: "post", url: `/api/scorecard/kpis/${k.id}/restore/`,
                    done: `${k.name} is back on the ${w.scorecard}.` })}>Restore</button>
              </div>
            ))}
            {s.pages.filter((p) => p.archived).map((p) => (
              <div key={p.id} className="row tight">
                <span>Page: {p.name}</span>
                <button className="ghost small" aria-label={`Restore the page ${p.name}`}
                  onClick={() => act.mutate({ method: "post", url: `/api/scorecard/pages/${p.id}/restore/` })}>Restore</button>
              </div>
            ))}
          </details>
        )}
      </Card>
    </div>
  );
}

function PageLine({ page, teams, practice = false, first, last, empty, onSave, onMove, onArchive }: {
  page: SetupPage; teams: SetupState["teams"]; practice?: boolean; first: boolean; last: boolean; empty: boolean;
  onSave: (body: Record<string, unknown>, done?: string) => void; onMove: (dir: number) => void;
  onArchive: () => void;
}) {
  const [name, setName] = useState(page.name);
  return (
    <div className="sc-page-line">
      <input aria-label={`Name of the page ${page.name}`} value={name} onChange={(e) => setName(e.target.value)}
        onBlur={() => name.trim() && name !== page.name && onSave({ name }, "The page is renamed.")} />
      <select aria-label={`Who sees ${page.name}`} value={page.audience}
        onChange={(e) => onSave({ audience: e.target.value, team: e.target.value === "team" ? teams[0]?.id : null },
          "Who sees the page is saved.")}>
        {Object.entries(practice ? PRACTICE_AUDIENCE : AUDIENCE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {page.audience === "team" && (
        <select aria-label={`Team for ${page.name}`} value={page.team ?? ""}
          onChange={(e) => onSave({ audience: "team", team: e.target.value }, "The page's team is saved.")}>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      )}
      <button className="ghost small" aria-label={`Move the page ${page.name} up`} disabled={first} onClick={() => onMove(-1)}>↑</button>
      <button className="ghost small" aria-label={`Move the page ${page.name} down`} disabled={last} onClick={() => onMove(1)}>↓</button>
      {empty && <button className="ghost small" onClick={onArchive}>Archive the page</button>}
    </div>
  );
}

/** A KPI's edit form in a pop-up, for the scorecard view's tile (Details →
 *  Edit), so the practice need not go back to the company page. */
export function KpiEditModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const state = useQuery<SetupState>({
    queryKey: ["scorecard-setup", companyId],
    queryFn: () => api.get<SetupState>(`/api/scorecard/setup/?company=${companyId}`),
  });
  const kpi = state.data?.kpis.find((k) => k.id === kpiId);
  return (
    <Modal label={kpi ? `Edit ${kpi.name}` : "Edit"} wide onClose={onClose}
      title={kpi ? `Edit ${kpi.name}` : "Edit"}>
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      {!state.data ? <p>Loading…</p> : kpi
        ? <KpiForm state={state.data} kpi={kpi} onDone={onSaved} onCancel={onClose} />
        : <p>That KPI is no longer here.</p>}
    </Modal>
  );
}

function KpiForm({ state, kpi, onDone, onCancel, initial }: {
  state: SetupState; kpi: SetupKpi | null; onDone: (text: string) => void;
  onCancel?: () => void; initial?: StarterKpi | null;
}) {
  const w = useWords();
  const livePages = state.pages.filter((p) => !p.archived);
  const [d, setD] = useState<Draft>(() => kpi ? {
    name: kpi.name, page: kpi.page, kind: kpi.kind, direction: kpi.direction, cadence: kpi.cadence,
    rollup: kpi.rollup, target_value: kpi.target_value ?? "", range_low: kpi.range_low ?? "",
    range_high: kpi.range_high ?? "", behind_band_pct: kpi.behind_band_pct, duration_unit: kpi.duration_unit || "hours",
    rating_scale: kpi.rating_scale ?? 5, reading_owner: kpi.reading_owner ?? "", per_person: kpi.per_person,
    person_total: kpi.person_total, leaderboard: kpi.leaderboard, tile: kpi.tile, audience: kpi.audience,
    audience_team: kpi.audience_team ?? "", note: kpi.note, strategy_component: kpi.strategy_component,
    people: kpi.people, month_targets: { ...kpi.month_targets },
    formula: kpi.formula, source_a: kpi.source_a ?? "", source_b: kpi.source_b ?? "",
  } : {
    name: "", page: livePages[0]?.id ?? "", kind: "number", direction: "higher", cadence: "weekly",
    rollup: "sum", target_value: "", range_low: "", range_high: "", behind_band_pct: 10,
    duration_unit: "hours", rating_scale: 5, reading_owner: "", per_person: false, person_total: "sum",
    leaderboard: false, tile: "number_trend", audience: "page", audience_team: "", note: "",
    strategy_component: "", people: [], month_targets: {},
    formula: "", source_a: "", source_b: "",
    ...(initial ? Object.fromEntries(Object.entries(initial).filter(([k]) => k !== "key")) : {}),
  });
  const [seasonal, setSeasonal] = useState(Object.keys(d.month_targets ?? {}).length > 0);
  const [error, setError] = useState<{ text: string; field?: string } | null>(null);
  const set = (k: string, v: unknown) => setD({ ...d, [k]: v });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...d, company: state.company.id,
        month_targets: seasonal ? d.month_targets : {},
        audience_team: d.audience === "team" ? d.audience_team || state.teams[0]?.id : null,
        reading_owner: d.formula ? null : d.reading_owner || null,
        per_person: d.formula ? false : d.per_person,
        source_a: d.formula ? d.source_a || null : null,
        source_b: d.formula ? d.source_b || null : null };
      return kpi ? api.patch(`/api/scorecard/kpis/${kpi.id}/`, body) : api.post("/api/scorecard/kpis/", body);
    },
    onSuccess: () => onDone(kpi ? `${d.name} is saved.` : `${d.name} is added.`),
    onError: (e: Error) => setError({ text: e.message, field: (e as { data?: { field?: string } }).data?.field }),
  });
  const choice = (k: string, label: string, options: Record<string, string>) => (
    <label className="sc-form-field"><span>{label}</span>
      <select value={String(d[k] ?? "")} onChange={(e) => set(k, e.target.value)}>
        {Object.entries(options).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select></label>
  );
  const text = (k: string, label: string, props: Record<string, unknown> = {}) => (
    <label className="sc-form-field"><span>{label}</span>
      <input value={String(d[k] ?? "")} onChange={(e) => set(k, e.target.value)}
        aria-invalid={error?.field === k} {...props} /></label>
  );
  const people = (d.people as string[]) ?? [];
  // One step only: company KPIs of the same cadence that are not computed.
  const sources = Object.fromEntries([["", "Choose…"], ...state.kpis
    .filter((k) => !k.archived && !k.formula && !k.per_person && k.cadence === d.cadence
      && k.id !== kpi?.id)
    .map((k) => [k.id, k.name])]);
  return (
    <form className="sc-kpi-form" aria-label={kpi ? `Edit ${kpi.name}` : `New ${w.kpi}`}
      onSubmit={(e) => { e.preventDefault(); save.mutate(); }}
      // Only the button saves: Enter in a field doesn't make the KPI.
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") e.preventDefault();
      }}>
      {error && <Banner kind="bad">{error.text}</Banner>}
      <div className="sc-form-grid">
        {text("name", "Name", { maxLength: 120, placeholder: "Occupancy" })}
        {choice("page", "Page", Object.fromEntries(livePages.map((p) => [p.id, p.name])))}
        {choice("kind", "Kind", KINDS)}
        {d.kind === "duration" && choice("duration_unit", "In", { days: "Days", hours: "Hours", minutes: "Minutes" })}
        {d.kind === "rating" && choice("rating_scale", "Out of", { 5: "5", 10: "10" })}
        {choice("direction", "Direction", DIRECTIONS)}
        {choice("cadence", "Entered", CADENCES)}
        {choice("rollup", "Over a window", ROLLUPS)}
        {d.direction === "range" ? <>
          {text("range_low", "Range, low", { inputMode: "decimal" })}
          {text("range_high", "Range, high", { inputMode: "decimal" })}
        </> : text("target_value", seasonal ? "Target, other months" : "Target", { inputMode: "decimal" })}
        {text("behind_band_pct", "Behind within (%)", { inputMode: "decimal" })}
        {choice("tile", "Tile", TILES)}
        {!d.formula && choice("reading_owner", "Reading owner", Object.fromEntries([["", "Nobody yet"],
          ...state.owners.map((o) => [o.id, `${o.name}${o.side === "practice" ? " (practice)" : ""}`])]))}
        {choice("audience", "Who sees it", state.practice ? PRACTICE_KPI_AUDIENCE : KPI_AUDIENCE)}
        {d.audience === "team" && choice("audience_team", "Team",
          Object.fromEntries(state.teams.map((t) => [t.id, t.name])))}
        {choice("strategy_component", "Strategy component", COMPONENTS)}
      </div>
      {d.direction !== "range" && (
        <label className="sc-check"><input type="checkbox" checked={seasonal}
          onChange={(e) => setSeasonal(e.target.checked)} /> A target per month (seasonal)</label>
      )}
      {seasonal && d.direction !== "range" && (
        <div className="sc-months">
          {MONTHS.map((m, i) => (
            <label key={m} className="sc-form-field"><span>{m}</span>
              <input inputMode="decimal" aria-label={`Target for ${m}`}
                value={String(d.month_targets?.[String(i + 1)] ?? "")}
                onChange={(e) => set("month_targets", { ...d.month_targets, [String(i + 1)]: e.target.value })} />
            </label>
          ))}
        </div>
      )}
      <label className="sc-check"><input type="checkbox" checked={!!d.formula}
        onChange={(e) => set("formula", e.target.checked ? "ratio" : "")} /> Computed: worked out
        from two other {w.kpis} on the same cadence, and never entered</label>
      {!!d.formula && (
        <div className="sc-form-grid">
          {choice("source_a", `First ${w.kpi}`, sources)}
          {choice("formula", "Worked out as", FORMULAS)}
          {choice("source_b", `Second ${w.kpi}`, sources)}
        </div>
      )}
      {!d.formula && <label className="sc-check"><input type="checkbox" checked={!!d.per_person}
        onChange={(e) => set("per_person", e.target.checked)} /> Per person: one reading per person</label>}
      {!d.formula && !!d.per_person && (
        <div className="sc-people">
          {state.people.length === 0 && <span className="small muted">The company has no portal users yet.</span>}
          {state.people.map((p) => (
            <label key={p.id} className="sc-check"><input type="checkbox" checked={people.includes(p.id)}
              onChange={(e) => set("people", e.target.checked ? [...people, p.id] : people.filter((x) => x !== p.id))} />
              {" "}{p.name}</label>
          ))}
          <div className="sc-form-grid">
            {choice("person_total", "Company total", { sum: "Sum", average: "Average" })}
          </div>
          <label className="sc-check"><input type="checkbox" checked={!!d.leaderboard}
            onChange={(e) => set("leaderboard", e.target.checked)} /> Show a leaderboard: everyone in the
            audience sees each other's numbers</label>
        </div>
      )}
      {text("note", "How it's measured (shown on the back of the tile)", { maxLength: 200 })}
      <div className="row tight">
        <button type="submit" className="primary small" disabled={save.isPending}>
          {kpi ? "Save" : `Add the ${w.kpi}`}</button>
        {onCancel && <button type="button" className="small" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
