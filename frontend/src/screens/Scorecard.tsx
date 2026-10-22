import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ScorecardTile } from "../components/ScorecardTiles";
import { Banner } from "../components/ui";
import { Me, api } from "../lib/api";
import {
  Board, CADENCE_LABEL, Cadence, Point, STATUS_LABEL, Starter, Tile, WINDOWS, WindowKey, fmt,
} from "../lib/scorecard";
import { useWords } from "../lib/words";

type View = "tiles" | "grid" | "meeting";

/** Where a company's scorecard lives: the portal's own for a client user,
 *  under the company for the practice. */
export function scorecardPath(me: Me, companyId?: string) {
  return me.role === "FCC" || me.role === "ECC" ? "/scorecard" : `/companies/${companyId}/scorecard`;
}

/**
 * The scorecard (M5 part 1), built to the approved mock-up
 * (docs/design/kpi_scorecard/Main and Grid): pages as tabs, the window
 * control, Tiles / Grid / Meeting, and "Enter readings" for whoever may. The
 * server sends only what the reader may see; this screen draws it.
 */
export function Scorecard({ me }: { me: Me }) {
  const { id } = useParams();
  const companyId = id ?? me.client_company ?? "";
  const w = useWords();
  const qc = useQueryClient();
  const [win, setWin] = useState<WindowKey>("this_week");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [applied, setApplied] = useState<{ from: string; to: string } | null>(null);
  const [page, setPage] = useState<string | null>(null);
  const [view, setView] = useState<View>("tiles");

  const params = new URLSearchParams({ company: companyId, window: win });
  if (win === "custom" && applied) { params.set("from", applied.from); params.set("to", applied.to); }
  if (page) params.set("page", page);
  const ready = win !== "custom" || applied !== null;
  const board = useQuery<Board>({
    queryKey: ["scorecard", companyId, win, applied?.from, applied?.to, page],
    queryFn: () => api.get<Board>(`/api/scorecard/?${params}`),
    enabled: ready && !!companyId,
    placeholderData: (previous) => previous,
  });

  if (board.isError) return <Banner kind="bad">{(board.error as Error).message}</Banner>;
  const b = board.data;
  if (!b) return <p>{ready ? `Loading the ${w.scorecard}…` : ""}</p>;
  const base = scorecardPath(me, companyId);
  const practice = !(me.role === "FCC" || me.role === "ECC");

  if (!b.exists || b.pages.length === 0) {
    return (
      <div className="sc-page">
        <ScorecardHead b={b} me={me} practice={practice} />
        {b.may_set_up
          ? <StartCard companyId={companyId} onMade={() => qc.invalidateQueries({ queryKey: ["scorecard", companyId] })} />
          : <div className="sc-tile"><p className="sc-empty">There is no {w.scorecard} here yet.</p></div>}
      </div>
    );
  }

  const tiles = b.kpis;
  const counts = b.counts;
  const missingLine = tiles.filter((t) => t.summary?.missing && !t.summary.open_period)
    .map((t) => `${t.name} is waiting on ${t.owner || "its reading owner"}`);
  const sub = [b.window.text,
    counts ? `${counts.in} of ${counts.of} readings in` : "",
    counts && (counts.behind || counts.off_track)
      ? [counts.behind ? `${counts.behind} behind` : "", counts.off_track ? `${counts.off_track} off track` : ""]
        .filter(Boolean).join(", ") : ""].filter(Boolean).join(" · ");

  return (
    <div className="sc-page">
      <ScorecardHead b={b} me={me} practice={practice} />
      <div className="sc-head">
        <div className="sc-head-text">
          <h1>{w.Scorecard}</h1>
          <div className="sc-sub">{sub}</div>
        </div>
        <div className="sc-controls">
          <label htmlFor="sc-window" className="sc-muted">Window</label>
          <select id="sc-window" className="sc-select" value={win}
            onChange={(e) => { setWin(e.target.value as WindowKey); if (e.target.value !== "custom") setApplied(null); }}>
            {WINDOWS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
          {win === "custom" && (
            <span className="sc-custom">
              <input type="date" aria-label="First day" value={from} onChange={(e) => setFrom(e.target.value)} />
              <input type="date" aria-label="Last day" value={to} onChange={(e) => setTo(e.target.value)} />
              <button className="small" disabled={!from || !to}
                onClick={() => setApplied({ from, to })}>Show</button>
            </span>
          )}
          <div role="group" aria-label="View" className="sc-views">
            {(["tiles", "grid", "meeting"] as View[]).map((v) => (
              <button key={v} type="button" aria-pressed={view === v}
                className={view === v ? "sc-view on" : "sc-view"} onClick={() => setView(v)}>
                {v === "tiles" ? "Tiles" : v === "grid" ? "Grid" : "Meeting"}</button>
            ))}
          </div>
          {b.may_enter && <Link className="sc-enter" to={`${base}/enter`}>Enter readings</Link>}
        </div>
      </div>

      {(b.notices ?? []).length > 0 && (
        <div className="sc-notice" role="status">
          <strong>Waiting on you:</strong>{" "}
          {b.notices!.map((n) => `${n.kpi}, ${n.text.charAt(0).toLowerCase()}${n.text.slice(1)}`).join("; ")}.
          {" "}<Link to={`${base}/enter`}>Enter readings</Link>
        </div>
      )}

      <PageTabs b={b} onPick={setPage} />

      {view === "grid" ? <Grid tiles={tiles} b={b} /> : (
        <div className="sc-grid">
          {tiles.length === 0 && <p className="sc-empty">No {w.kpis} on this page yet.</p>}
          {tiles.map((t) => <ScorecardTile key={t.id} t={t} />)}
        </div>
      )}
      {view === "meeting" && (
        <Meeting b={b} onExit={() => setView("tiles")} onPage={setPage} />
      )}

      <div className="sc-foot">
        <div>{missingLine.length ? `Missing: ${missingLine.join(" · ")}` : ""}</div>
        <div>Status: On track at or past target · Behind within 10% · Off track beyond</div>
      </div>
    </div>
  );
}

function ScorecardHead({ b, me, practice }: { b: Board; me: Me; practice: boolean }) {
  return (
    <div className="sc-context">
      {practice
        ? <><Link to={`/companies/${b.company.id}`}>{b.company.name}</Link>
          {b.may_set_up && <> · <Link to={`/companies/${b.company.id}#scorecard-setup`}>Set up</Link></>}</>
        : <>{b.company.name} · Signed in as {me.full_name || me.email}
          {me.portal?.level_label ? `, ${me.portal.level_label}` : ""}</>}
    </div>
  );
}

function PageTabs({ b, onPick }: { b: Board; onPick: (id: string) => void }) {
  if (b.pages.length < 2) return <div className="sc-tabs" role="tablist" aria-label="Scorecard pages">
    {b.pages.map((p) => <button key={p.id} type="button" role="tab" aria-selected="true"
      className="sc-tab on">{p.name}</button>)}</div>;
  return (
    <div className="sc-tabs" role="tablist" aria-label="Scorecard pages">
      {b.pages.map((p) => (
        <button key={p.id} type="button" role="tab" aria-selected={p.id === b.page}
          className={p.id === b.page ? "sc-tab on" : "sc-tab"} onClick={() => onPick(p.id)}>{p.name}</button>
      ))}
    </div>
  );
}

/** The classic weekly scorecard: KPIs down, the last 13 periods across, each
 *  cell colored by status (Grid.dc.html). One table per cadence. */
function Grid({ tiles, b }: { tiles: Tile[]; b: Board }) {
  const [cell, setCell] = useState<{ t: Tile; p: Point } | null>(null);
  // Narrower than the table, the box opens on its latest weeks.
  const toLatest = (el: HTMLDivElement | null) => {
    if (!el) return;
    // The newest week at the right edge of the box, the weeks before it
    // running back under the pinned KPI names.
    const now = el.querySelector<HTMLElement>("thead .sc-now");
    el.scrollLeft = now ? now.offsetLeft + now.offsetWidth - el.clientWidth : el.scrollWidth;
  };
  const groups: Record<string, Tile[]> = {};
  tiles.forEach((t) => { (groups[t.cadence] ??= []).push(t); });
  const download = () => {
    const lines: string[][] = [];
    Object.values(groups).forEach((ts) => {
      lines.push(["KPI", "Target", ...ts[0].history.map((p) => p.label), "Owner"]);
      ts.forEach((t) => lines.push([t.name, targetCell(t),
        ...t.history.map((p) => (p.value === null ? "" : String(p.value))), t.owner]));
      lines.push([]);
    });
    const csv = lines.map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${b.company.name} scorecard.csv`; a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      {Object.entries(groups).map(([cadence, ts]) => (
        <div key={cadence} className="sc-grid-box" ref={toLatest}>
          <table className="sc-table">
            <thead>
              <tr>
                <th scope="col" className="sc-kpi-col">KPI{Object.keys(groups).length > 1
                  ? <span className="sc-cadence"> · {CADENCE_LABEL[cadence as Cadence]}</span> : null}</th>
                <th scope="col" className="sc-num">Target</th>
                {ts[0].history.map((p, i) => (
                  <th key={p.period_start} scope="col"
                    className={i === ts[0].history.length - 1 ? "sc-c sc-now" : "sc-c"}>{p.label}</th>
                ))}
                <th scope="col" className="sc-owner">Owner</th>
              </tr>
            </thead>
            <tbody>
              {ts.map((t) => (
                <tr key={t.id}>
                  <th scope="row" className="sc-kpi-col">{rowName(t)}</th>
                  <td className="sc-num sc-muted">{targetCell(t)}</td>
                  {t.history.map((p, i) => (
                    <td key={p.period_start} className="sc-cell-td">
                      <button type="button"
                        className={`sc-cell sc-cell-${p.status ?? (p.value === null ? "missing" : "none")}${i === t.history.length - 1 ? " sc-cell-now" : ""}`}
                        aria-label={`${t.name}, ${p.label}: ${p.value === null ? "no reading" : fmt(t, p.value)}${p.status ? `, ${STATUS_LABEL[p.status]}` : ""}`}
                        onClick={() => setCell({ t, p })}>
                        {p.value === null ? "—" : fmt(t, p.value, { bare: true, compact: true })}
                      </button>
                    </td>
                  ))}
                  <td className="sc-owner sc-muted">{t.owner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {cell && (
        <div className="sc-cell-detail" role="status">
          {cell.t.name}, {cell.p.label}: {cell.p.value === null ? "no reading"
            : `${fmt(cell.t, cell.p.value)}, entered by ${cell.p.entered_by || "someone"}${cell.p.entered_at
              ? ` on ${new Date(cell.p.entered_at).toLocaleDateString()}` : ""}${cell.p.edited ? " (edited)" : ""}`}
        </div>
      )}
      <div className="sc-legend">
        <div className="sc-legend-keys">
          <span><i className="sc-key sc-cell-on_track" />On track</span>
          <span><i className="sc-key sc-cell-behind" />Behind, within 10%</span>
          <span><i className="sc-key sc-cell-off_track" />Off track</span>
          <span><i className="sc-key sc-cell-missing" />No reading yet</span>
        </div>
        <div>Click any cell for who entered it and when ·{" "}
          <button className="linklike" onClick={download}>Download this grid</button></div>
      </div>
    </>
  );
}

function rowName(t: Tile) {
  const unit = t.kind === "percent" ? "%" : t.kind === "money" ? "$" : t.kind === "rating"
    ? `of ${t.rating_scale ?? 5}` : t.kind === "duration" ? t.duration_unit : "";
  const extra = [unit, t.direction === "lower" ? "lower is better" : "",
    t.per_person ? (t.shape === "my_row" ? "yours" : t.total_label ?? "") : ""]
    .filter(Boolean).join(" · ");
  return <>{t.name}{extra && <span className="sc-unit"> · {extra}</span>}</>;
}

function targetCell(t: Tile) {
  if (t.direction === "range") return `${fmt(t, t.range_low, { bare: true })}–${fmt(t, t.range_high, { bare: true })}`;
  const last = [...t.history].reverse().find((p) => p.target !== null)?.target ?? null;
  if (last === null) return "—";
  return `${t.direction === "lower" ? "≤ " : ""}${fmt(t, last, { bare: true })}`;
}

/** Full screen, larger type, for a TV or a shared screen; cycles the pages
 *  when asked. */
function Meeting({ b, onExit, onPage }: { b: Board; onExit: () => void; onPage: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [cycle, setCycle] = useState(false);
  const w = useWords();
  useEffect(() => {
    const el = box.current as (HTMLDivElement & { requestFullscreen?: () => Promise<void> }) | null;
    el?.requestFullscreen?.().catch(() => undefined);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onExit(); };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => undefined);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!cycle || b.pages.length < 2) return;
    const timer = setInterval(() => {
      const at = b.pages.findIndex((p) => p.id === b.page);
      onPage(b.pages[(at + 1) % b.pages.length].id);
    }, 20000);
    return () => clearInterval(timer);
  }, [cycle, b.page, b.pages, onPage]);
  const name = b.pages.find((p) => p.id === b.page)?.name ?? "";
  return (
    <div className="sc-meeting" ref={box} role="dialog" aria-label={`${w.Scorecard}, meeting view`}>
      <div className="sc-meeting-head">
        <div>
          <div className="sc-meeting-title">{b.company.name} · {name}</div>
          <div className="sc-sub">{b.window.text}</div>
        </div>
        <div className="sc-controls">
          {b.pages.length > 1 && (
            <label className="sc-cycle"><input type="checkbox" checked={cycle}
              onChange={(e) => setCycle(e.target.checked)} /> Cycle pages</label>)}
          <button className="sc-view on" onClick={onExit}>Exit</button>
        </div>
      </div>
      <div className="sc-grid sc-grid-large">
        {b.kpis.map((t) => <ScorecardTile key={t.id} t={t} large />)}
      </div>
    </div>
  );
}

/** "Start the scorecard": three suggested KPIs per discipline, each one
 *  click to create (decided after the mock-up). */
export function StartCard({ companyId, onMade, compact = false }: {
  companyId: string; onMade: (kpiId: string) => void; compact?: boolean;
}) {
  const w = useWords();
  const starters = useQuery<{ starters: Starter[] }>({
    queryKey: ["scorecard-setup", companyId],
    queryFn: () => api.get(`/api/scorecard/setup/?company=${companyId}`),
  });
  const [error, setError] = useState("");
  const make = useMutation({
    mutationFn: (key: string) => api.post<{ id: string }>("/api/scorecard/starters/",
      { company: companyId, key }),
    onSuccess: (kpi) => { setError(""); onMade(kpi.id); },
    onError: (e: Error) => setError(e.message),
  });
  return (
    <section className={compact ? "sc-start compact" : "sc-tile sc-start"} aria-label={`Start the ${w.scorecard}`}>
      {!compact && <h3>Start the {w.scorecard}</h3>}
      <p className="sc-muted">Pick a few {w.kpis} to begin with. Each is made in one click, with a
        sensible target, and can be changed afterwards.</p>
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="sc-starters">
        {(starters.data?.starters ?? []).map((group) => (
          <div key={group.discipline}>
            <div className="sc-starter-head">{group.name}</div>
            {group.kpis.map((k) => (
              <button key={k.key} className="small" disabled={make.isPending}
                onClick={() => make.mutate(k.key)}>+ {k.name}</button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}


