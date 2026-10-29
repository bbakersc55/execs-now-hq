import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { BonusArea, bonusLead } from "../components/ScorecardBonus";
import { SheetFeedModal } from "../components/ScorecardFeed";
import { BestyFeedModal } from "../components/ScorecardBesty";
import { HubSpotFeedModal } from "../components/ScorecardHubSpot";
import { TrackFeedModal } from "../components/ScorecardTrack";
import { AppFeedModal } from "../components/ScorecardApp";
import { KpiEditModal } from "../components/ScorecardSetup";
import { ScorecardTile } from "../components/ScorecardTiles";
import { AiGate } from "../components/DemoVisitor";
import { Banner, Card } from "../components/ui";
import { Me, api } from "../lib/api";
import {
  BONUS_VIEW_LABEL, Board, BonusViewKey, CADENCE_LABEL, COMPONENTS, Cadence, Point, STATUS_LABEL,
  Starter, StarterKpi, Tile, WINDOWS, WindowKey, fmt,
} from "../lib/scorecard";
import { useRemembered } from "../lib/remembered";
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
  const navigate = useNavigate();
  const [win, setWin] = useState<WindowKey>("this_week");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [applied, setApplied] = useState<{ from: string; to: string } | null>(null);
  const [page, setPage] = useState<string | null>(null);
  const [view, setView] = useState<View>("tiles");
  const [bonus, setBonus] = useState<BonusViewKey | null>(null);
  // The practice edits or archives a KPI from its tile (Details → Edit).
  const [editKpi, setEditKpi] = useState<string | null>(null);
  // Part 3: a KPI's Google Sheet feed, from its tile (Details → Feed from a sheet).
  const [feedKpi, setFeedKpi] = useState<string | null>(null);
  const [trackKpi, setTrackKpi] = useState<string | null>(null);
  const [hubspotKpi, setHubspotKpi] = useState<string | null>(null);
  const [bestyKpi, setBestyKpi] = useState<string | null>(null);
  const [appKpi, setAppKpi] = useState<string | null>(null);
  const [search, setSearch] = useSearchParams();
  // "Reconnect Google" is a browser redirect; its outcome comes back here.
  useEffect(() => {
    const connected = search.get("sheets_connected");
    const failed = search.get("sheets_error");
    if (connected) setManaged({ kind: "ok", text: `Google is reconnected for ${connected}, with read-only access to Sheets. Open a tile's Details, then "Feed from a sheet".` });
    if (failed) setManaged({ kind: "bad", text: failed });
    if (connected || failed) setSearch({}, { replace: true });
  }, [search, setSearch]);
  const [managed, setManaged] = useState<{ kind: string; text: string } | null>(null);
  // M5 ties: the scorecard grouped by the strategy component each KPI serves.
  const [grouped, setGrouped] = useRemembered("sc-group-by-component", false);
  // M5 ties: "Make a task" on a tile, referencing the KPI.
  const makeTask = useMutation({
    mutationFn: (t: Tile) => api.post<{ id: string; title: string }>("/api/tasks/", {
      ...(t.task_draft ?? { title: `Look into ${t.name}`, description: "" }),
      client_company: companyId, kpi: t.id }),
    onSuccess: (task) => {
      setManaged({ kind: "ok", text: `${w.Task} made: ${task.title}.` });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
    },
    onError: (e: Error) => setManaged({ kind: "bad", text: e.message }),
  });
  const archive = useMutation({
    mutationFn: (t: Tile) => api.post(`/api/scorecard/kpis/${t.id}/archive/`, {}),
    onSuccess: (_r, t) => {
      setManaged({ kind: "ok", text: `${t.name} is archived; its readings are kept.` });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard-setup", companyId] });
    },
    onError: (e: Error) => setManaged({ kind: "bad", text: e.message }),
  });

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
  // A missing reading asks for a number; a failing feed says what went wrong (part 3).
  const waiting = (b.notices ?? []).filter((n) => n.kind !== "feed");
  const failing = (b.notices ?? []).filter((n) => n.kind === "feed");
  const base = scorecardPath(me, companyId);
  const practice = !(me.role === "FCC" || me.role === "ECC");

  if (!b.exists || b.pages.length === 0) {
    return (
      <div className="sc-page">
        <ScorecardHead b={b} me={me} practice={practice} />
        {b.may_set_up
          ? <StartCard companyId={companyId}
            onPick={(k) => navigate(b.practice
              ? `/scorecard/practice/setup?starter=${encodeURIComponent(k.key)}#scorecard-setup`
              : `/companies/${companyId}?starter=${encodeURIComponent(k.key)}#scorecard-setup`)} />
          : <div className="sc-tile"><p className="sc-empty">There is no {w.scorecard} here yet.</p></div>}
      </div>
    );
  }

  if (bonus && (b.bonus_views ?? []).includes(bonus)) {
    return (
      <div className="sc-page">
        <ScorecardHead b={b} me={me} practice={practice} />
        <div className="sc-head">
          <div className="sc-head-text">
            <h1>{w.Scorecard}</h1>
            <div className="sc-sub">{bonusLead(bonus)}</div>
          </div>
        </div>
        <PageTabs b={b} onPick={(id) => { setBonus(null); setPage(id); }} bonus={bonus} onBonus={setBonus} />
        <BonusArea companyId={companyId} view={bonus} companyName={b.company.name} />
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

      {waiting.length > 0 && (
        <div className="sc-notice" role="status">
          <strong>Waiting on you:</strong>{" "}
          {waiting.map((n) => `${n.kpi}, ${n.text.charAt(0).toLowerCase()}${n.text.slice(1)}`).join("; ")}.
          {" "}<Link to={`${base}/enter`}>Enter readings</Link>
        </div>
      )}
      {failing.length > 0 && (
        <div className="sc-notice" role="alert">
          {failing.map((n) => (
            <div key={n.kpi_id}><strong>{n.kpi}'s sheet couldn't be read.</strong> {n.text} Its last
              readings are kept.</div>
          ))}
        </div>
      )}

      <PageTabs b={b} onPick={setPage} bonus={null} onBonus={setBonus} />
      {managed && <Banner kind={managed.kind}>{managed.text}</Banner>}
      {appKpi && (
        <AppFeedModal companyId={companyId} kpiId={appKpi} onClose={() => setAppKpi(null)}
          onSaved={(text) => { setAppKpi(null); setManaged({ kind: "ok", text }); }} />
      )}
      {trackKpi && (
        <TrackFeedModal companyId={companyId} kpiId={trackKpi} onClose={() => setTrackKpi(null)}
          onSaved={(text) => { setTrackKpi(null); setManaged({ kind: "ok", text }); }} />
      )}
      {hubspotKpi && (
        <HubSpotFeedModal companyId={companyId} kpiId={hubspotKpi} onClose={() => setHubspotKpi(null)}
          onSaved={(text) => { setHubspotKpi(null); setManaged({ kind: "ok", text }); }} />
      )}
      {bestyKpi && (
        <BestyFeedModal companyId={companyId} kpiId={bestyKpi} onClose={() => setBestyKpi(null)}
          onSaved={(text) => { setBestyKpi(null); setManaged({ kind: "ok", text }); }} />
      )}
      {feedKpi && (
        <SheetFeedModal companyId={companyId} kpiId={feedKpi} onClose={() => setFeedKpi(null)}
          onSaved={(text) => { setFeedKpi(null); setManaged({ kind: "ok", text }); }} />
      )}
      {editKpi && (
        <KpiEditModal companyId={companyId} kpiId={editKpi} onClose={() => setEditKpi(null)}
          onSaved={(text) => {
            setEditKpi(null); setManaged({ kind: "ok", text });
            qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
            qc.invalidateQueries({ queryKey: ["scorecard-setup", companyId] });
          }} />
      )}

      {b.may_set_up && view === "tiles" && <AskClaude companyId={companyId} />}

      {view === "grid" ? <Grid tiles={tiles} b={b} /> : (() => {
        const drawn = (list: Tile[]) => list.map((t) => <ScorecardTile key={t.id} t={t}
          task={{ onMake: (x) => makeTask.mutate(x), busy: makeTask.isPending }}
          manage={b.may_set_up ? {
            onEdit: () => setEditKpi(t.id), onArchive: () => archive.mutate(t),
            onFeed: () => setFeedKpi(t.id),
            // The practice's own scorecard reads this app, a client's reads Track,
            // HubSpot or Besty.
            ...(b.practice ? { onApp: () => setAppKpi(t.id) }
              : { onTrack: () => setTrackKpi(t.id), onHubSpot: () => setHubspotKpi(t.id),
                onBesty: () => setBestyKpi(t.id) }),
            busy: archive.isPending } : undefined} />);
        const tagged = tiles.some((t) => t.component);
        return (
          <>
            {tagged && view === "tiles" && (
              <label className="row tight small sc-group-toggle">
                <input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />
                Group by component
              </label>
            )}
            {grouped && tagged ? (
              ([...Object.entries(COMPONENTS).filter(([key]) => key), ["", "No component"]] as
                [string, string][])
                .map(([key, label]) => [label, tiles.filter((t) => (t.component || "") === key)] as const)
                .filter(([, list]) => list.length > 0)
                .map(([label, list]) => (
                  <section key={label} className="sc-component" aria-label={label}>
                    <h2 className="sc-component-head">{label}</h2>
                    <div className="sc-grid">{drawn(list)}</div>
                  </section>
                ))
            ) : (
              <div className="sc-grid">
                {tiles.length === 0 && <p className="sc-empty">No {w.kpis} on this page yet.</p>}
                {drawn(tiles)}
              </div>
            )}
          </>
        );
      })()}
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
      {practice && b.practice
        ? <>My practice
          {b.may_set_up && <> · <Link to="/scorecard/practice/setup">Set up</Link></>}</>
        : practice
        ? <><Link to={`/companies/${b.company.id}`}>{b.company.name}</Link>
          {b.may_set_up && <> · <Link to={`/companies/${b.company.id}#scorecard-setup`}>Set up</Link></>}</>
        : <>{b.company.name} · Signed in as {me.full_name || me.email}
          {me.portal?.level_label ? `, ${me.portal.level_label}` : ""}</>}
    </div>
  );
}

function PageTabs({ b, onPick, bonus, onBonus }: {
  b: Board; onPick: (id: string) => void; bonus: BonusViewKey | null;
  onBonus: (v: BonusViewKey) => void;
}) {
  const single = b.pages.length < 2 && !(b.bonus_views ?? []).length;
  return (
    <div className="sc-tabs" role="tablist" aria-label="Scorecard pages">
      {b.pages.map((p) => {
        const on = !bonus && (single || p.id === b.page);
        return (
          <button key={p.id} type="button" role="tab" aria-selected={on}
            className={on ? "sc-tab on" : "sc-tab"} onClick={() => onPick(p.id)}>{p.name}</button>
        );
      })}
      {(b.bonus_views ?? []).map((v) => (
        <button key={v} type="button" role="tab" aria-selected={bonus === v}
          className={bonus === v ? "sc-tab on" : "sc-tab"} onClick={() => onBonus(v)}>
          {BONUS_VIEW_LABEL[v]}</button>
      ))}
    </div>
  );
}

/** The window's value for the grid's last column: the tile's own roll-up,
 *  and nothing for a value carried from before the window. */
function windowValue(t: Tile) {
  const s = t.summary;
  return s && !s.stale && !s.carried ? s : null;
}

/** The classic weekly scorecard: KPIs down, periods across, each cell colored
 *  by status (Grid.dc.html). One table per cadence. A window of several
 *  periods (a quarter, the year so far, custom dates) draws its own periods,
 *  then its roll-up, the tile's value; a window of one, the last 13. */
function Grid({ tiles, b }: { tiles: Tile[]; b: Board }) {
  const [cell, setCell] = useState<{ t: Tile; p: Point } | null>(null);
  // Narrower than the table, the box opens on its latest weeks.
  const toLatest = (el: HTMLDivElement | null) => {
    if (!el) return;
    // The newest week at the right edge of the box, the weeks before it
    // running back under the pinned KPI names.
    // With a window's roll-up after the periods, that column is the edge.
    const now = el.querySelector<HTMLElement>("thead .sc-window")
      ?? el.querySelector<HTMLElement>("thead .sc-now");
    el.scrollLeft = now ? now.offsetLeft + now.offsetWidth - el.clientWidth : el.scrollWidth;
  };
  const groups: Record<string, Tile[]> = {};
  tiles.forEach((t) => { (groups[t.cadence] ??= []).push(t); });
  const download = () => {
    const lines: string[][] = [];
    Object.values(groups).forEach((ts) => {
      const rolled = !!ts[0].history_is_window;
      lines.push(["KPI", "Target", ...ts[0].history.map((p) => p.label),
        ...(rolled ? [b.window.label] : []), "Owner"]);
      ts.forEach((t) => {
        const w = windowValue(t);
        lines.push([t.name, targetCell(t),
          ...t.history.map((p) => (p.value === null ? "" : String(p.value))),
          ...(rolled ? [w?.value == null ? "" : String(w.value)] : []), t.owner]);
      });
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
                {ts[0].history_is_window && (
                  <th scope="col" className="sc-c sc-window">{b.window.label}</th>
                )}
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
                        aria-label={`${t.name}, ${p.label}: ${p.value === null ? "no reading" : fmt(t, p.value)}${p.so_far ? " so far" : ""}${p.status ? `, ${STATUS_LABEL[p.status]}` : ""}`}
                        onClick={() => setCell({ t, p })}>
                        {p.value === null ? "—" : fmt(t, p.value, { bare: true, compact: true })}
                        {p.so_far && <span className="sc-so-far" aria-hidden="true">so far</span>}
                      </button>
                    </td>
                  ))}
                  {ts[0].history_is_window && (() => {
                    const w = windowValue(t);
                    return (
                      <td className="sc-cell-td">
                        <span className={`sc-cell sc-cell-${w?.status ?? (w?.value == null ? "missing" : "none")} sc-cell-window`}
                          aria-label={`${t.name}, ${b.window.label}: ${w?.value == null ? "no reading" : fmt(t, w.value)}${w?.status ? `, ${STATUS_LABEL[w.status]}` : ""}`}>
                          {w?.value == null ? "—" : fmt(t, w.value, { bare: true, compact: true })}
                        </span>
                      </td>
                    );
                  })()}
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
              ? ` on ${new Date(cell.p.entered_at).toLocaleDateString()}` : ""}${cell.p.edited ? " (edited)" : ""}${cell.p.so_far ? ", so far: replaced at each refresh until the period closes" : ""}`}
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

/** "Start the scorecard": three suggested KPIs per discipline. Choosing one
 *  opens the new-KPI form filled in with it; nothing is made until Save
 *  (Bryan, 2026-10-22: a starter used to be made on the click). */
export function StartCard({ companyId, onPick, compact = false }: {
  companyId: string; onPick: (starter: StarterKpi) => void; compact?: boolean;
}) {
  const w = useWords();
  const starters = useQuery<{ starters: Starter[] }>({
    queryKey: ["scorecard-setup", companyId],
    queryFn: () => api.get(`/api/scorecard/setup/?company=${companyId}`),
  });
  return (
    <section className={compact ? "sc-start compact" : "sc-tile sc-start"} aria-label={`Start the ${w.scorecard}`}>
      {!compact && <h3>Start the {w.scorecard}</h3>}
      <p className="sc-muted">Pick a few {w.kpis} to begin with. Each opens filled in, with a
        sensible target, to change before you save it.</p>
      <div className="sc-starters">
        {(starters.data?.starters ?? []).map((group) => (
          <div key={group.discipline}>
            <div className="sc-starter-head">{group.name}</div>
            {group.kpis.map((k) => (
              <button key={k.key} type="button" className="small" onClick={() => onPick(k)}>+ {k.name}</button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}




interface AiStatus { explain_estimate_usd: string; note_estimate_usd: string; used_today: number;
  cap: number; refused: string }

const price = (usd: string | undefined) => `about $${Number(usd ?? 0).toFixed(2)}`;

/** M5 ties: "Explain this scorecard" and "Draft the weekly note", with Claude on
 *  the practice's key. Nothing is sent until a button is pressed; the note is
 *  a draft to copy, never saved or sent from here. */
function AskClaude({ companyId }: { companyId: string }) {
  const w = useWords();
  const qc = useQueryClient();
  const status = useQuery<AiStatus>({
    queryKey: ["scorecard-ai", companyId],
    queryFn: () => api.get<AiStatus>(`/api/scorecard/ai/?company=${companyId}`),
  });
  const [answer, setAnswer] = useState<{ purpose: string; text: string } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const ask = useMutation({
    mutationFn: (purpose: "explain" | "note") =>
      api.post<{ text: string }>("/api/scorecard/ai/", { company: companyId, purpose })
        .then((r) => ({ purpose, text: r.text })),
    onSuccess: (r) => { setAnswer(r); setError(""); setCopied(false); },
    onError: (e: Error) => setError(e.message),
    onSettled: () => qc.invalidateQueries({ queryKey: ["scorecard-ai", companyId] }),
  });
  const s = status.data;
  return (
    <Card title="Ask Claude">
      <p className="small muted" style={{ marginTop: 0 }}>
        Claude reads this {w.scorecard}'s totals, targets and notes, and the last meeting's notes. No one's own
        numbers and nothing about bonuses are sent. Nothing is sent until you press.</p>
      {error && <Banner kind="bad">{error}</Banner>}
      {s?.refused ? <p className="small muted">{s.refused}</p> : (
        <div className="row tight sc-ai-buttons">
          <AiGate>
            <button className="small" disabled={!s || ask.isPending} onClick={() => ask.mutate("explain")}>
              {ask.isPending && ask.variables === "explain" ? "Asking Claude…"
                : `Explain this ${w.scorecard} (${price(s?.explain_estimate_usd)})`}</button>
            <button className="small" disabled={!s || ask.isPending} onClick={() => ask.mutate("note")}>
              {ask.isPending && ask.variables === "note" ? "Asking Claude…"
                : `Draft the weekly note (${price(s?.note_estimate_usd)})`}</button>
          </AiGate>
          {s && <span className="small muted">{s.used_today} of {s.cap} used today.</span>}
        </div>
      )}
      {answer && (
        <div className="banner info sc-ai-answer" role="note"
          aria-label={answer.purpose === "note" ? "The weekly note, drafted" : "Explanation"}>
          <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{answer.text}</p>
          {answer.purpose === "note" && (
            <button className="ghost small" onClick={() => {
              navigator.clipboard?.writeText(answer.text).then(() => setCopied(true)).catch(() => {});
            }}>{copied ? "Copied" : "Copy the draft"}</button>
          )}
        </div>
      )}
    </Card>
  );
}
