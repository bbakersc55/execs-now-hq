import { useState } from "react";

import type { Point } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * A balance over time (P6 M4 stop 3): what was entered as a solid 2px line,
 * and, where there is one, the plan's projection after it, dashed in its own
 * colour, so the two are never told apart by colour alone. A target is a
 * labelled reference line. The same readout is on hover and on keyboard
 * focus, and every value the chart draws is also said in words beside it, so
 * the picture gates nothing.
 */
export function SeriesChart({ label, history, projection = [], target, targetLabel,
                              height = 200, zero = true }: {
  label: string; history: Point[]; projection?: Point[]; target?: number | null;
  targetLabel?: string; height?: number;
  /** Whether the scale reaches down to $0: yes for a balance paid down or
   *  saved up, no for a figure (net worth) whose movement is the point. */
  zero?: boolean;
}) {
  const [at, setAt] = useState<number | null>(null);
  const all = [...history, ...projection];
  if (all.length === 0) return null;
  // Drawn at about the width it is shown at, so its text stays text-sized.
  const W = 960, H = height, L = 64, R = 16, T = 10, B = 24;
  const time = (p: Point) => new Date(`${p.on_date}T00:00:00Z`).getTime();
  const t0 = time(all[0]), t1 = Math.max(time(all[all.length - 1]), t0 + 1);
  const values = [...all.map((p) => p.cents), ...(target ? [target] : []),
                  ...(zero ? [0] : [])];
  const low = Math.min(...values), high = Math.max(...values);
  const pad = Math.max((high - low) * 0.08, 100);
  const min = low - pad, max = high + pad;
  const x = (p: Point) => L + ((time(p) - t0) * (W - L - R)) / (t1 - t0);
  const y = (cents: number) => T + ((max - cents) * (H - T - B)) / (max - min);
  const path = (series: Point[]) => series.map((p, i) => `${i ? "L" : "M"}${
    x(p).toFixed(1)},${y(p.cents).toFixed(1)}`).join(" ");
  // The projection starts where what was entered ends.
  const ahead = projection.length && history.length
    ? [history[history.length - 1], ...projection] : projection;
  const short = (cents: number) => {
    const d = cents / 100;
    return Math.abs(d) >= 1_000_000 ? `$${(d / 1_000_000).toFixed(1)}m`
      : Math.abs(d) >= 1000 ? `${d < 0 ? "-" : ""}$${Math.abs(Math.round(d / 1000))}k`
        : `${d < 0 ? "-" : ""}$${Math.abs(Math.round(d))}`;
  };
  const year = (p: Point) => p.on_date.slice(0, 4);
  const sameYear = year(all[0]) === year(all[all.length - 1]);
  const tick = (p: Point) => new Date(`${p.on_date}T00:00:00Z`).toLocaleDateString(
    "en-US", sameYear ? { month: "short", timeZone: "UTC" }
      : { year: "numeric", timeZone: "UTC" });
  // A tick for each new month (or year), never two of the same and never
  // crowded together.
  const shownTicks: Point[] = [];
  for (const p of all) {
    const prev = shownTicks[shownTicks.length - 1];
    if (prev && (tick(prev) === tick(p) || x(p) - x(prev) < 80)) continue;
    shownTicks.push(p);
  }
  const point = at === null ? null : all[at];
  const projected = at !== null && at >= history.length;
  const move = (clientX: number, box: DOMRect) => {
    const px = ((clientX - box.left) / box.width) * W;
    let best = 0;
    all.forEach((p, i) => { if (Math.abs(x(p) - px) < Math.abs(x(all[best]) - px)) best = i; });
    setAt(best);
  };
  const first = all[0], last = all[all.length - 1];
  return (
    <figure style={{ margin: "var(--s2) 0" }}>
      {projection.length > 0 && (
        <ul className="row tight small" aria-label={`What the lines are, ${label}`}
          style={{ listStyle: "none", padding: 0, margin: "0 0 var(--s1)" }}>
          <li><svg width="22" height="8" aria-hidden="true"><line x1="0" x2="22" y1="4"
            y2="4" stroke="var(--chart-1)" strokeWidth="2" /></svg> Entered</li>
          <li><svg width="22" height="8" aria-hidden="true"><line x1="0" x2="22" y1="4"
            y2="4" stroke="var(--chart-2)" strokeWidth="2" strokeDasharray="5 3" /></svg>{" "}
            Projected</li>
        </ul>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
        aria-label={`${label}: ${dollars(first.cents)} on ${longDate(first.on_date)} to ${
          dollars(last.cents)} on ${longDate(last.on_date)}${
          projection.length ? " (projected)" : ""}.`}
        style={{ width: "100%", height: "auto", display: "block" }}
        onPointerMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setAt(null)} onBlur={() => setAt(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setAt(Math.min(all.length - 1, (at ?? -1) + 1));
          if (e.key === "ArrowLeft") setAt(Math.max(0, (at ?? all.length) - 1));
        }}>
        {[min + pad, (min + max) / 2, max - pad].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="11"
              fill="var(--muted)">{short(v)}</text>
          </g>
        ))}
        {target ? (
          <>
            <line x1={L} x2={W - R} y1={y(target)} y2={y(target)} stroke="var(--muted)"
              strokeDasharray="2 4" />
            <text x={L + 4} y={y(target) - 4} fontSize="11" fill="var(--muted)">
              {targetLabel ?? "target"}, {short(target)}</text>
          </>
        ) : null}
        {history.length > 0 && (
          <path d={path(history)} data-series="entered" fill="none" stroke="var(--chart-1)"
            strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        )}
        {ahead.length > 0 && (
          <path d={path(ahead)} data-series="projected" fill="none" stroke="var(--chart-2)"
            strokeWidth="2" strokeDasharray="5 3" strokeLinejoin="round" />
        )}
        {shownTicks.map((p) => (
          <text key={p.on_date} x={x(p)} y={H - 6} textAnchor="middle" fontSize="11"
            fill="var(--muted)">{tick(p)}</text>
        ))}
        {point && (
          <>
            <line x1={x(point)} x2={x(point)} y1={T} y2={H - B} stroke="var(--line-strong)" />
            <circle cx={x(point)} cy={y(point.cents)} r="5"
              fill={projected ? "var(--chart-2)" : "var(--chart-1)"}
              stroke="var(--surface)" strokeWidth="2" />
          </>
        )}
      </svg>
      <figcaption className="small" role="status" aria-label={`The point on ${label}`}
        style={{ minHeight: "1.4em" }}>
        {point ? <><strong>{dollars(point.cents)}</strong>{" "}
          <span className="muted">{projected ? "projected for" : "on"}{" "}
            {longDate(point.on_date)}</span></>
          : <span className="muted">Point at the line, or use the arrow keys, for a
            figure.</span>}
      </figcaption>
    </figure>
  );
}
