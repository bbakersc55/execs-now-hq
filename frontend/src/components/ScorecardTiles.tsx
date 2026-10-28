import { useQuery } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import {
  CADENCE_LABEL, CADENCE_NOUN, KpiDef, PersonRow, Point, ROLLUP_WORDS, ReadingHistory,
  STATUS_LABEL, Status, Tile, fmt, fmtChange, ofTarget, targetText,
} from "../lib/scorecard";

/**
 * The scorecard's eight tiles (M5 part 1), drawn to the approved mock-up
 * (docs/design/kpi_scorecard/Main.dc.html): the KPI's name, the value large,
 * the target small beside it, a status pill, the period, and the tile's own
 * shape. Brand colors (the practice's, through --navy and --orange) carry the
 * chrome and the charts; green, amber and red are kept for status, always
 * with the words beside them. One click turns a tile over: how it is
 * measured, the last 13 readings and who entered the latest.
 */

export function StatusPill({ status }: { status: Status | null }) {
  if (!status) return <span className="sc-pill sc-none">No target</span>;
  return <span className={`sc-pill sc-${status}`}>{STATUS_LABEL[status]}</span>;
}

function scale(values: number[], pad = 0.08): [number, number] {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.abs(hi) || 1;
  return [lo - span * pad, hi + span * pad];
}

function known(points: Point[]) {
  return points.filter((p) => p.value !== null) as (Point & { value: number })[];
}

/** A target line: flat for a fixed target, stepped for a seasonal one. */
function targetPath(points: Point[], x: (i: number) => number, y: (v: number) => number,
  width: number) {
  const ts = points.map((p) => p.target);
  if (ts.every((t) => t === null)) return null;
  if (ts.every((t) => t === ts[0])) return `M0,${y(ts[0]!)} L${width},${y(ts[0]!)}`;
  return ts.map((t, i) => (t === null ? "" : `${i === 0 ? "M" : "L"}${x(i)},${y(t)}`))
    .filter(Boolean).join(" ");
}

export function Sparkline({ points, label }: { points: Point[]; label: string }) {
  const have = known(points);
  if (have.length < 2) return null;
  const n = points.length;
  const [lo, hi] = scale([...have.map((p) => p.value),
    ...points.map((p) => p.target).filter((t): t is number => t !== null)]);
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * 120);
  const y = (v: number) => 34 - ((v - lo) / (hi - lo)) * 32;
  const line = points.map((p, i) => (p.value === null ? null : `${x(i)},${y(p.value)}`))
    .filter(Boolean).join(" ");
  const target = targetPath(points, x, y, 120);
  return (
    <svg className="sc-spark" viewBox="0 0 120 36" width="100%" height="40"
      preserveAspectRatio="none" role="img" aria-label={label}>
      {target && <path d={target} fill="none" className="sc-target" strokeWidth="1"
        strokeDasharray="3 3" />}
      <polyline fill="none" className="sc-brand-stroke" strokeWidth="2" strokeLinejoin="round"
        points={line} />
    </svg>
  );
}

function Bars({ points, label }: { points: Point[]; label: string }) {
  const have = known(points);
  if (have.length === 0) return null;
  const n = points.length;
  const gap = 5;
  const w = (300 - gap * (n - 1)) / n;
  const top = Math.max(...have.map((p) => p.value),
    ...points.map((p) => p.target ?? 0)) * 1.06 || 1;
  const y = (v: number) => 85 - (Math.max(0, v) / top) * 80;
  const target = targetPath(points, (i) => i * (w + gap) + w / 2, y, 300);
  return (
    <svg viewBox="0 0 300 90" width="100%" height="64" preserveAspectRatio="none" role="img"
      aria-label={label}>
      {points.map((p, i) => p.value === null ? null : (
        <rect key={p.period_start} x={i * (w + gap)} y={y(p.value)} width={w}
          height={85 - y(p.value)} rx="2"
          className={i === n - 1 ? "sc-brand-fill" : "sc-brand-light-fill"} />
      ))}
      {target && <path d={target} fill="none" className="sc-target" strokeWidth="1.5"
        strokeDasharray="4 3" />}
    </svg>
  );
}

function Line({ def, points, label }: { def: KpiDef; points: Point[]; label: string }) {
  const have = known(points);
  if (have.length < 2) return null;
  const n = points.length;
  const targets = points.map((p) => p.target).filter((t): t is number => t !== null);
  const band = (def.band ?? 10) / 100;
  const bandVals = def.direction === "range" && def.range_low !== null && def.range_high !== null
    ? [def.range_low, def.range_high]
    : targets.length ? [Math.min(...targets) * (1 - band / 2), Math.max(...targets) * (1 + band / 2)]
      : [];
  const [lo, hi] = scale([...have.map((p) => p.value), ...targets, ...bandVals]);
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * 300);
  const y = (v: number) => 86 - ((v - lo) / (hi - lo)) * 82;
  const line = points.map((p, i) => (p.value === null ? null : `${x(i)},${y(p.value)}`))
    .filter(Boolean).join(" ");
  const last = have[have.length - 1];
  const lastIndex = points.indexOf(last);
  const target = targetPath(points, x, y, 300);
  return (
    <svg viewBox="0 0 300 90" width="100%" height="64" preserveAspectRatio="none" role="img"
      aria-label={label}>
      {bandVals.length === 2 && (
        <rect x="0" y={y(bandVals[1])} width="300" height={Math.max(1, y(bandVals[0]) - y(bandVals[1]))}
          className="sc-band" />)}
      {target && <path d={target} fill="none" className="sc-target" strokeWidth="1.5"
        strokeDasharray="4 3" />}
      <polyline fill="none" className="sc-brand-stroke" strokeWidth="2.5" strokeLinejoin="round"
        points={line} />
      <circle cx={x(lastIndex)} cy={y(last.value)} r="3.5" className="sc-brand-fill" />
    </svg>
  );
}

function Gauge({ def, value, target, status }: {
  def: KpiDef; value: number; target: number | null; status: Status | null;
}) {
  let lo = 0;
  let hi: number;
  if (def.direction === "range" && def.range_low !== null && def.range_high !== null) {
    const span = def.range_high - def.range_low || 1;
    lo = def.range_low - span / 2;
    hi = def.range_high + span / 2;
  } else if (def.kind === "rating") {
    hi = def.rating_scale ?? 5;
    lo = target !== null && target > hi * 0.6 ? Math.floor(hi * 0.8) : 0;
  } else if (def.kind === "percent" && (target ?? 0) <= 100 && value <= 100) {
    hi = 100;
  } else {
    hi = Math.max(value, target ?? 0) * 1.25 || 1;
  }
  const at = (v: number) => {
    const f = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
    const angle = Math.PI * (1 - f);
    return [100 + 80 * Math.cos(angle), 100 - 80 * Math.sin(angle), angle] as const;
  };
  const [vx, vy] = at(value);
  const tick = target !== null && def.direction !== "range" ? at(target) : null;
  const label = `Gauge from ${fmt(def, lo)} to ${fmt(def, hi)} showing ${fmt(def, value)}`
    + (target !== null ? ` against a target of ${fmt(def, target)}` : "");
  return (
    <svg viewBox="0 0 200 110" width="150" height="84" role="img" aria-label={label}>
      <path d="M20,100 A80,80 0 0 1 180,100" fill="none" className="sc-track" strokeWidth="14"
        strokeLinecap="round" />
      <path d={`M20,100 A80,80 0 0 1 ${vx.toFixed(1)},${vy.toFixed(1)}`} fill="none"
        className={`sc-arc sc-arc-${status ?? "none"}`} strokeWidth="14" strokeLinecap="round" />
      <line x1="100" y1="100" x2={vx.toFixed(1)} y2={vy.toFixed(1)} className="sc-needle"
        strokeWidth="3" strokeLinecap="round" />
      <circle cx="100" cy="100" r="5" className="sc-needle-dot" />
      {tick && (
        <line x1={(100 + 70 * Math.cos(tick[2])).toFixed(1)}
          y1={(100 - 70 * Math.sin(tick[2])).toFixed(1)}
          x2={(100 + 90 * Math.cos(tick[2])).toFixed(1)}
          y2={(100 - 90 * Math.sin(tick[2])).toFixed(1)} className="sc-target" strokeWidth="3" />)}
    </svg>
  );
}

function StatusStrip({ points }: { points: Point[] }) {
  return (
    <div className="sc-strip" aria-label={`Status by ${points.length > 1 ? "period" : "period"}, oldest first`}>
      {points.map((p) => (
        <span key={p.period_start} title={`${p.label}: ${p.status ? STATUS_LABEL[p.status]
          : p.value === null ? "no reading" : "no target"}`}
          className={`sc-strip-${p.status ?? (p.value === null ? "missing" : "none")}`} />
      ))}
    </div>
  );
}

function DeltaText({ def, delta }: { def: KpiDef; delta: Tile["delta"] }) {
  if (!delta || delta.change === 0) return null;
  // A change too small to show at the KPI's precision is no change at all.
  if (/^\$?0(\.0+)?( |$)/.test(fmtChange(def, delta.change))) return null;
  const arrow = delta.change > 0 ? "▲" : "▼";
  const tone = delta.better === null ? "" : delta.better ? "sc-good" : "sc-bad";
  return <div className={`sc-delta ${tone}`}>{arrow} {fmtChange(def, delta.change)}</div>;
}

function footer(t: Tile): string {
  const noun = CADENCE_NOUN[t.cadence];
  const parts = [CADENCE_LABEL[t.cadence]];
  if (t.direction === "lower") parts.push("lower is better");
  else parts.push(`${ROLLUP_WORDS[t.rollup]} over the window`);
  if (t.shape === "leaderboard") parts.push(t.leaderboard ? "per person, ranked"
    : "per person");
  else if (t.shape === "my_row") parts.push("only you see this row");
  else if (t.per_person && t.total_label) parts.push(t.total_label);
  else if (t.computed) parts.push(`computed: ${t.computed}`);
  else if (t.shape === "status") parts.push(`${t.history.length} ${noun}s of status`);
  else if (t.spark.length > 1) parts.push(`${t.spark.length} ${noun}s shown`);
  return parts.join(" · ");
}

/** The small mark on a value that is the open period's reading so far. */
export function SoFar({ on }: { on?: boolean }) {
  return on ? <span className="sc-so-far" title="The open period's reading so far: it is replaced at each refresh until the period closes"> so far</span> : null;
}

function Big({ def, s }: { def: KpiDef; s: NonNullable<Tile["summary"]> }) {
  return (
    <div className={`sc-big${s.stale ? " sc-stale" : ""}`}>{fmt(def, s.value)}<SoFar on={s.so_far} /></div>
  );
}

function Missing({ s }: { s: NonNullable<Tile["summary"]> }) {
  // Early in a week, the page's own line says this week's readings aren't
  // in yet; each tile need not say it again.
  if (!s.missing || s.carried) return null;
  const from = (s.stale || s.carried) && s.stale_from ? `; showing ${s.stale_from}` : "";
  return <div className={`sc-missing${s.carried ? "" : " sc-missing-closed"}`}>{s.missing}{from}</div>;
}

function progressWords(def: KpiDef, s: NonNullable<Tile["summary"]>): string {
  if (s.value === null || s.full_target === null) return "";
  const left = s.full_target - s.value;
  const days = s.days_left > 0 ? ` with ${s.days_left} day${s.days_left === 1 ? "" : "s"} left` : "";
  if (def.direction === "lower") {
    return left >= 0 ? `${fmt(def, left)} of room left${days}` : `${fmt(def, -left)} over`;
  }
  if (left <= 0) return `${fmt(def, -left)} past the target`;
  const pace = s.days_left > 0
    ? (s.value / s.full_target >= s.elapsed ? " · ahead of pace" : " · behind pace") : "";
  return `${fmt(def, left)} to go${days}${pace}`;
}

function Body({ t }: { t: Tile }) {
  const s = t.summary;
  if (!s || (s.value === null && t.shape !== "leaderboard")) {
    return <p className="sc-empty">No readings yet.</p>;
  }
  const label = `${t.name}: the last ${t.spark.length} ${CADENCE_NOUN[t.cadence]}s`;
  switch (t.shape) {
    case "gauge":
      return (
        <div className="sc-gauge-row">
          <Gauge def={t} value={s.value!} target={s.target} status={s.status} />
          <div className="sc-gauge-text">
            <Big def={t} s={s} />
            <div className="sc-muted">
              {t.kind === "rating" ? `of ${t.rating_scale ?? 5} · ` : ""}{targetText(t, s.target)}
            </div>
          </div>
        </div>
      );
    case "progress": {
      const pct = s.full_target ? Math.max(0, Math.min(100, (s.value! / s.full_target) * 100)) : 0;
      return (
        <>
          <div className="sc-value-row">
            <Big def={t} s={s} />
            <div className="sc-muted">{ofTarget(t, s.value, s.full_target, !!t.target_live)}</div>
          </div>
          <div className="sc-progress" role="img"
            aria-label={`${Math.round(pct)}% of the target`}>
            <div className="sc-progress-fill" style={{ width: `${pct}%` }} />
            {s.days_left > 0 && <div className="sc-progress-pace"
              style={{ left: `${Math.round(s.elapsed * 100)}%` }} />}
          </div>
          <div className="sc-words">{progressWords(t, s)}</div>
        </>
      );
    }
    case "bars":
      return (
        <>
          <div className="sc-value-row">
            <Big def={t} s={s} />
            <div className="sc-muted">{targetText(t, s.target)}</div>
          </div>
          <Bars points={t.spark} label={label} />
        </>
      );
    case "line":
      return (
        <>
          <div className="sc-value-row">
            <Big def={t} s={s} />
            <DeltaText def={t} delta={t.delta} />
            <div className="sc-muted">{targetText(t, s.target)}</div>
          </div>
          <Line def={t} points={t.spark} label={label} />
        </>
      );
    case "status":
      return (
        <>
          <div className="sc-value-row">
            <div className={`sc-small-value${s.stale ? " sc-stale" : ""}`}>{fmt(t, s.value)}<SoFar on={s.so_far} /></div>
            <div className="sc-muted">{targetText(t, s.target)}</div>
          </div>
          <StatusStrip points={t.history} />
        </>
      );
    case "leaderboard":
      return <Leaderboard t={t} />;
    default:
      return (
        <>
          <div className="sc-value-row">
            <Big def={t} s={s} />
            <DeltaText def={t} delta={t.delta} />
            <div className="sc-muted">{targetText(t, s.target)}</div>
          </div>
          <Sparkline points={t.spark} label={label} />
        </>
      );
  }
}

function Leaderboard({ t }: { t: Tile }) {
  const top = Math.max(...t.rows.map((r) => Math.max(r.value ?? 0, r.target ?? 0)), 0) || 1;
  if (t.rows.length === 0) return <p className="sc-empty">Nobody is tracked yet.</p>;
  return (
    <div className="sc-board" role="list">
      {t.rows.map((r: PersonRow, i) => (
        <div key={r.membership} className="sc-board-row" role="listitem">
          <span className="sc-muted">{r.rank ?? (t.leaderboard ? "—" : i + 1)}</span>
          <span className="sc-board-name">{r.name}{r.you && <span className="sc-muted"> (you)</span>}</span>
          <span className="sc-board-bar"><span className={`sc-board-fill sc-fill-${r.status ?? "none"}`}
            style={{ width: `${Math.max(0, Math.min(100, ((r.value ?? 0) / top) * 100))}%` }} /></span>
          <span className={`sc-board-value${r.stale ? " sc-stale" : ""}`}>{fmt(t, r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** What the practice owner and associates can do to a KPI from its tile. */
export interface TileManage {
  onEdit: () => void; onArchive: () => void; busy?: boolean;
  /** Part 3: set up or change the KPI's Google Sheet feed. */
  onFeed?: () => void;
  /** Part 4: its Track PMS measure. */
  onTrack?: () => void;
  /** "My practice": a measure "From this app". */
  onApp?: () => void;
  /** Part 5: its HubSpot measure. */
  onHubSpot?: () => void;
}

/** M5 ties: the task a KPI's tile offers, and the one already made. */
export interface TileTask { onMake: (t: Tile) => void; busy?: boolean }

function TaskLine({ t, task, front }: { t: Tile; task?: TileTask; front: boolean }) {
  if (t.open_task) {
    return <div className="sc-task">Task: <Link to={`/tasks/${t.open_task.id}`}>{t.open_task.title}</Link></div>;
  }
  if (!task || !t.may_make_task) return null;
  if (front && !t.offer_task) return null;
  const unit = CADENCE_NOUN[t.cadence] ?? "period";
  return (
    <div className={front ? "sc-task sc-task-offer" : "sc-task"}>
      {front && <span>Off track {t.off_track_run} {unit}s running. </span>}
      <button type="button" className="small" disabled={task.busy}
        aria-label={`Make a task for ${t.name}`} onClick={() => task.onMake(t)}>Make a task</button>
    </div>
  );
}

function Back({ t, manage, task }: { t: Tile; manage?: TileManage; task?: TileTask }) {
  const [open, setOpen] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const latest = [...t.history].reverse().find((p) => p.value !== null);
  return (
    <div className="sc-back">
      <div className="sc-back-note">
        {t.note ? <><strong>How it's measured.</strong> {t.note}</> : "No note on how it's measured."}
        {t.computed && <div>Worked out each period from {t.computed}.</div>}
        {t.target_live && <div className="sc-back-target">Target {t.target_live.value === null
          ? "not read yet" : fmt(t, t.target_live.value)}, live from {t.target_live.text}.</div>}
        {t.feed && <div className="sc-back-feed">{t.feed.text}.
          {t.feed.error && <div className="sc-field-error"><strong>Last read failed:</strong> {t.feed.error}</div>}</div>}
      </div>
      <table className="sc-back-table">
        <thead><tr><th>Period</th><th className="money">Reading</th><th>Status</th></tr></thead>
        <tbody>
          {[...t.history].reverse().map((p) => (
            <tr key={p.period_start}>
              <td>{p.label}</td>
              <td className="money">{fmt(t, p.value)}<SoFar on={p.so_far} />{p.edited && <span className="sc-edited"> edited</span>}</td>
              <td>
                {p.status ? STATUS_LABEL[p.status] : p.missing ? "No reading" : "—"}
                {t.may_enter && p.reading && (
                  <button className="ghost small" aria-label={`History of ${p.label}`}
                    onClick={(e) => { e.stopPropagation(); setOpen(open === p.reading ? null : p.reading); }}>
                    History</button>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && <HistoryList reading={open} def={t} />}
      <TaskLine t={t} task={task} front={false} />
      <div className="sc-muted">
        {latest ? (latest.source === "app"
          ? <>Latest worked out from this app
            {latest.entered_at ? ` on ${new Date(latest.entered_at).toLocaleDateString()}` : ""}.</>
          : latest.source === "hubspot"
          ? <>Latest worked out from HubSpot
            {latest.entered_at ? ` on ${new Date(latest.entered_at).toLocaleDateString()}` : ""}.</>
          : latest.source === "track"
          ? <>Latest worked out from Track
            {latest.entered_at ? ` on ${new Date(latest.entered_at).toLocaleDateString()}` : ""}.</>
          : latest.source === "sheet"
          ? <>Latest read from the Google Sheet
            {latest.entered_at ? ` on ${new Date(latest.entered_at).toLocaleDateString()}` : ""}.</>
          : <>Latest entered by {latest.entered_by || "someone"}
            {latest.entered_at ? ` on ${new Date(latest.entered_at).toLocaleDateString()}` : ""}
            {latest.source === "hand" ? ", by hand" : latest.source ? `, from ${latest.source}` : ""}.</>)
          : "No readings yet."}
      </div>
      {manage && (
        <div className="sc-back-manage">
          {archiving ? (
            <>
              <span className="sc-muted">Archive {t.name}? Its readings are kept, and it can be restored
                on the company page.</span>
              <button type="button" className="small" disabled={manage.busy}
                onClick={manage.onArchive}>Archive</button>
              <button type="button" className="ghost small" onClick={() => setArchiving(false)}>Keep it</button>
            </>
          ) : (
            <>
              <button type="button" className="small" aria-label={`Edit ${t.name}`}
                onClick={manage.onEdit}>Edit</button>
              {manage.onFeed && !t.computed && (
                <button type="button" className="ghost small" aria-label={`Sheet feed for ${t.name}`}
                  onClick={manage.onFeed}>{t.feed?.kind === "sheet" ? "Sheet feed" : "Feed from a sheet"}</button>)}
              {manage.onApp && !t.computed && !t.per_person && (
                <button type="button" className="ghost small" aria-label={`From this app for ${t.name}`}
                  onClick={manage.onApp}>{t.feed?.kind === "app" ? "From this app" : "Read from this app"}</button>)}
              {manage.onTrack && !t.computed && !t.per_person && (
                <button type="button" className="ghost small" aria-label={`Track measure for ${t.name}`}
                  onClick={manage.onTrack}>{t.feed?.kind === "track" ? "Track measure" : "Feed from Track"}</button>)}
              {manage.onHubSpot && !t.computed && !t.per_person && (
                <button type="button" className="ghost small" aria-label={`HubSpot measure for ${t.name}`}
                  onClick={manage.onHubSpot}>{t.feed?.kind === "hubspot" ? "HubSpot measure" : "Feed from HubSpot"}</button>)}
              <button type="button" className="ghost small" aria-label={`Archive ${t.name}`}
                onClick={() => setArchiving(true)}>Archive</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function HistoryList({ reading, def }: { reading: string; def: KpiDef }) {
  const q = useQuery<ReadingHistory>({
    queryKey: ["scorecard-history", reading],
    queryFn: () => api.get<ReadingHistory>(`/api/scorecard/readings/${reading}/history/`),
  });
  if (!q.data) return <p className="sc-muted">Loading the history…</p>;
  return (
    <div className="sc-history" role="region" aria-label={`History of ${q.data.period}`}>
      <div className="sc-muted">{q.data.period}</div>
      <ul>
        {q.data.changes.map((c, i) => (
          <li key={i}>{fmt(def, c.value)}
            {c.previous !== null && <span className="sc-muted"> (was {fmt(def, c.previous)})</span>}
            {" "}by {c.by || "someone"}, {new Date(c.at).toLocaleString()}</li>
        ))}
      </ul>
    </div>
  );
}

/** One KPI's tile. `large` is the Meeting view's bigger type. */
export function ScorecardTile({ t, large = false, actions, manage, task }: {
  t: Tile; large?: boolean; actions?: ReactNode; manage?: TileManage; task?: TileTask;
}) {
  const [flipped, setFlipped] = useState(false);
  const s = t.summary;
  const title = t.shape === "my_row" ? `${t.name}, yours` : t.name;
  const latest = [...t.history].reverse().find((p) => p.value !== null);
  return (
    <section className={`sc-tile${large ? " sc-large" : ""}`} aria-label={title}>
      <div className="sc-tile-head">
        <div className="sc-tile-name">{title}</div>
        {t.shape === "leaderboard"
          ? <span className="sc-muted">{t.each_target != null
            ? `${t.direction === "lower" ? "keep under" : "target"} ${fmt(t, t.each_target)} each` : ""}</span>
          : <StatusPill status={s?.status ?? null} />}
      </div>
      {flipped ? <Back t={t} manage={manage} task={task} /> : (
        <>
          <Body t={t} />
          {s && <Missing s={s} />}
          <TaskLine t={t} task={task} front />
        </>
      )}
      <div className="sc-tile-foot">
        <span>{footer(t)}{latest?.edited && !flipped && <span className="sc-edited"> · edited</span>}</span>
        <span className="sc-tile-tools">
          {actions}
          <button className="sc-flip" aria-pressed={flipped}
            aria-label={flipped ? `Front of ${t.name}` : `Back of ${t.name}`}
            onClick={() => setFlipped(!flipped)}>{flipped ? "Front" : "Details"}</button>
        </span>
      </div>
    </section>
  );
}
