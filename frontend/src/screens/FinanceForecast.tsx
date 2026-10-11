import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Pill } from "../components/ui";
import {
  Forecast, ForecastLine, ForecastRow, ForecastView, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * Finance → Forecast (P6 M2, stop 1; matrix 13.18, 13.19): the practice
 * owner's, and only for a practice with the Cash forecast module.
 *
 * Arithmetic on the practice's own books: cash today, then money in and out
 * week by week from what is known (invoices), what is regular (found in the
 * closed months) and the card. Nothing here is stored but the floor, and
 * nothing here asks Claude anything. Every figure opens the lines it is made
 * of, and every line says where it came from.
 */

const VIEWS: [ForecastView, string][] = [
  ["30", "30 days"], ["90", "90 days"], ["180", "180 days"], ["months", "12 months"]];
const WEEKS: Record<string, number> = { "30": 5, "90": 13, "180": 26 };
const KIND = { known: "Known", regular: "Regular", card: "Card payment" };

export function FinanceForecast() {
  const qc = useQueryClient();
  const [view, setView] = useState<ForecastView>("90");
  const [openRow, setOpenRow] = useState("");
  const forecast = useQuery<Forecast>({
    queryKey: ["finance-forecast"],
    queryFn: () => api.get<Forecast>("/api/finance-forecast/") });
  const [error, setError] = useState("");
  const floor = useMutation({
    mutationFn: (floor_cents: number | null) =>
      api.post<Forecast>("/api/finance-forecast/floor/", { floor_cents }),
    onSuccess: (now) => {
      setError(""); qc.setQueryData(["finance-forecast"], now);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => setError(e.message) });

  if (forecast.isError) return <Banner kind="bad">{(forecast.error as Error).message}</Banner>;
  const data = forecast.data;
  if (!data) return <p>Working out the forecast…</p>;
  const rows = view === "months" ? data.months : data.weeks.slice(0, WEEKS[view]);
  const summary = data.views[view];
  const byId = new Map(data.lines.map((line) => [line.id, line]));
  const last = rows[rows.length - 1].end;
  const within = data.lines.filter((line) => line.on_date <= last);
  const stale = data.accounts.filter((account) => account.stale);
  const span = view === "months" ? "the next 12 months" : `the next ${view} days`;

  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        This is how much cash your practice is likely to have in the bank, if clients pay
        as they have been paying and your costs go on as they have been going. It is
        arithmetic on your own books, not a prediction. Every line it is made of is below.
      </p>
      {error && <Banner kind="bad">{error}</Banner>}
      {data.note && <Banner kind="info">{data.note}</Banner>}
      {summary.first_below_zero && (
        <Banner kind="bad"><strong>Below zero.</strong> On these figures the cash runs out
          in the {view === "months" ? "month" : "week"} starting{" "}
          {longDate(summary.first_below_zero)}.</Banner>
      )}
      {!summary.first_below_zero && summary.first_below_floor && (
        <Banner kind="warn"><strong>Under your floor.</strong> The cash first falls below{" "}
          {dollars(data.floor_cents ?? 0)} in the {view === "months" ? "month" : "week"}{" "}
          starting {longDate(summary.first_below_floor)}.</Banner>
      )}

      <Card>
        <dl className="row" aria-label="The forecast in three figures"
          style={{ margin: 0, alignItems: "flex-start" }}>
          <div>
            <dt className="small muted">Cash today</dt>
            <dd style={{ margin: 0 }}><strong>{dollars(data.cash_today_cents)}</strong></dd>
          </div>
          <div>
            <dt className="small muted">Lowest in {span}</dt>
            <dd style={{ margin: 0 }}><strong>{dollars(summary.low_cents)}</strong>
              <span className="small muted"> · {view === "months" ? summary.low_label
                : `the week of ${longDate(summary.low_start)}`}</span></dd>
          </div>
          <div>
            <dt className="small muted">Your floor</dt>
            <dd style={{ margin: 0 }}>
              <Floor cents={data.floor_cents} busy={floor.isPending}
                onSet={(cents) => floor.mutate(cents)} />
            </dd>
          </div>
        </dl>
        <ul className="small muted" aria-label="Where cash today comes from"
          style={{ margin: "var(--s3) 0 0", paddingLeft: "1.1rem" }}>
          {data.accounts.map((account) => (
            <li key={account.id}>{account.name}: {dollars(account.amount_cents)}
              {account.reconciled_through
                ? <>, reconciled through {longDate(account.reconciled_through)}</>
                : <>, not reconciled yet</>}
              {account.last_entry_on
                ? <>, entries through {longDate(account.last_entry_on)}</> : <>, no entries</>}
            </li>
          ))}
          {data.unplaced_cents > 0 && <li>Received and not yet placed in an account:{" "}
            {dollars(data.unplaced_cents)}</li>}
        </ul>
        {stale.length > 0 && (
          <Banner kind="warn">{stale.map((a) => a.name).join(" and ")}{" "}
            {stale.length === 1 ? "has" : "have"} no entry in the last 14 days. A forecast
            that starts from a stale balance is wrong from its first row: import or enter
            what has happened since.</Banner>
        )}
      </Card>

      <Card title={`Cash, ${view === "months" ? "month by month" : "week by week"}`}
        actions={
          <span className="row tight" role="group" aria-label="How far ahead">
            {VIEWS.map(([key, label]) => (
              <button key={key} aria-pressed={view === key}
                className={view === key ? "small primary" : "ghost small"}
                onClick={() => { setView(key); setOpenRow(""); }}>{label}</button>
            ))}
          </span>}>
        <CashChart rows={rows} floor={data.floor_cents} months={view === "months"} />
        <div style={{ overflowX: "auto" }}>
          <table aria-label="The cash forecast as a table">
            <thead><tr><th>{view === "months" ? "Month" : "Week starting"}</th>
              <th className="money">Cash at the start</th><th className="money">Money in</th>
              <th className="money">Money out</th><th className="money">Cash at the end</th>
              <th /></tr></thead>
            <tbody>
              {rows.map((row) => (
                <RowAndLines key={row.start} row={row} months={view === "months"}
                  open={openRow === row.start}
                  lines={row.lines.map((id) => byId.get(id)!).filter(Boolean)}
                  onToggle={() => setOpenRow(openRow === row.start ? "" : row.start)} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="small" style={{ marginBottom: 0 }}>
          <a className="btn small" href="/api/finance-forecast/export/">
            Download the forecast</a>{" "}
          <span className="muted">180 days by week, with every line behind it. Each
            download is recorded.</span>
        </p>
      </Card>

      <Lines title="Known" lines={within.filter((line) => line.kind === "known")}
        note="Invoices you have sent, written, or scheduled, each on the day that client
              usually pays." />
      <Lines title="Regular" lines={within.filter((line) => line.kind !== "known")}
        note={data.ready
          ? "Found in your closed months, by category and payee. A charge on a card is "
            + "not cash until the card is paid, so it is listed here and counted in the "
            + "card's payment."
          : data.note} />

      {data.left_out.length > 0 && (
        <Card title="Overdue, not counted">
          <p className="small muted" style={{ marginTop: 0 }}>
            More than 60 days past due. They are left out of the forecast: hoping is not
            forecasting.</p>
          <table aria-label="Overdue, not counted"><tbody>
            {data.left_out.map((row) => (
              <tr key={row.id}>
                <td><Link to={row.link}>{row.label}</Link></td>
                <td>due {longDate(row.due_date)}, {row.days_overdue} days ago</td>
                <td className="money">{dollars(row.amount_cents)}</td>
              </tr>
            ))}
          </tbody></table>
        </Card>
      )}

      {data.likely_annual.length > 0 && (
        <Card title="Likely annual, to confirm">
          <p className="small muted" style={{ marginTop: 0 }}>
            Seen once, about a year ago, and not since. They are <strong>not in the
            forecast</strong>. Confirming one, so that it is, comes with planned lines.
          </p>
          <table aria-label="Likely annual, to confirm"><tbody>
            {data.likely_annual.map((row) => (
              <tr key={row.id}>
                <td>{row.label}{row.category
                  && <span className="muted"> · {row.category}</span>}</td>
                <td>last on {longDate(row.last_on)}; likely again about{" "}
                  {longDate(row.likely_on)}</td>
                <td className="money">{dollars(row.amount_cents)}</td>
              </tr>
            ))}
          </tbody></table>
        </Card>
      )}
    </>
  );
}

// ----------------------------------------------------------------- the floor

function Floor({ cents, busy, onSet }: {
  cents: number | null; busy: boolean; onSet: (cents: number | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(cents ?? 0);
  if (!editing) {
    return (
      <span className="row tight">
        <strong>{cents === null ? "Not set" : dollars(cents)}</strong>
        <button className="ghost small" onClick={() => { setValue(cents ?? 0);
                                                         setEditing(true); }}>
          {cents === null ? "Set a floor" : "Change"}</button>
      </span>
    );
  }
  return (
    <span className="row tight">
      <PriceBox label="The least cash you want in the bank" cents={value}
        onChange={setValue} disabled={busy} />
      <button className="small" disabled={busy}
        onClick={() => { onSet(value); setEditing(false); }}>Save the floor</button>
      {cents !== null && (
        <button className="ghost small" disabled={busy}
          onClick={() => { onSet(null); setEditing(false); }}>No floor</button>
      )}
      <button className="ghost small" onClick={() => setEditing(false)}>Cancel</button>
    </span>
  );
}

// ----------------------------------------------------------------- the table

function RowAndLines({ row, lines, open, months, onToggle }: {
  row: ForecastRow; lines: ForecastLine[]; open: boolean; months: boolean;
  onToggle: () => void;
}) {
  const name = months ? row.label : longDate(row.start);
  return (
    <>
      <tr>
        <td>{name}</td>
        <td className="money">{dollars(row.start_cents)}</td>
        <td className="money">{row.in_cents ? dollars(row.in_cents)
          : <span className="muted">—</span>}</td>
        <td className="money">{row.out_cents ? dollars(row.out_cents)
          : <span className="muted">—</span>}</td>
        <td className="money"><strong>{dollars(row.end_cents)}</strong>
          {row.below_zero ? <> <Pill kind="bad">below zero</Pill></>
            : row.below_floor && <> <Pill kind="warn">under your floor</Pill></>}</td>
        <td className="money">
          {lines.length > 0 && (
            <button className="ghost small" aria-expanded={open}
              aria-label={`${open ? "Hide" : "Show"} the ${lines.length} line${
                lines.length === 1 ? "" : "s"} of ${name}`}
              onClick={onToggle}>{open ? "Hide" : `${lines.length} line${
                lines.length === 1 ? "" : "s"}`}</button>
          )}
        </td>
      </tr>
      {open && lines.map((line) => (
        <tr key={line.id} className="small">
          <td style={{ paddingLeft: "var(--s5)" }}>{longDate(line.on_date)}</td>
          <td colSpan={2}><Link to={line.link}>{line.label}</Link>{" "}
            <span className="muted">{KIND[line.kind].toLowerCase()}</span></td>
          <td className="money">{line.direction === "out" ? dollars(line.amount_cents) : ""}</td>
          <td className="money">{line.direction === "in" ? dollars(line.amount_cents) : ""}</td>
          <td />
        </tr>
      ))}
    </>
  );
}

function Lines({ title, lines, note }: { title: string; lines: ForecastLine[]; note: string }) {
  return (
    <Card title={`${title} (${lines.length})`}>
      <p className="small muted" style={{ marginTop: 0 }}>{note}</p>
      {lines.length > 0 && (
        <details>
          <summary className="small">Show {lines.length === 1 ? "it" : `all ${lines.length}`}
          </summary>
          <table aria-label={`${title} lines`}>
            <thead><tr><th>When</th><th>What</th><th>Where it comes from</th>
              <th className="money">In</th><th className="money">Out</th></tr></thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{longDate(line.on_date)}</td>
                  <td><Link to={line.link}>{line.label}</Link>
                    {line.category && <div className="small muted">{line.category}</div>}
                    {line.cadence && <> <Pill>{line.cadence}</Pill></>}
                    {!line.counted && <> <Pill>on a card</Pill></>}</td>
                  <td className="small">{line.detail}</td>
                  <td className="money">{line.direction === "in"
                    ? dollars(line.amount_cents) : ""}</td>
                  <td className="money">{line.direction === "out"
                    ? dollars(line.amount_cents) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

// ----------------------------------------------------------------- the chart

/**
 * One series, the cash at the end of each week or month, as a 2px line; the
 * floor and zero as labelled reference lines. A single series needs no
 * legend: the card's title names it. Every value is also in the table under
 * it, so the picture gates nothing, and the same readout is on hover and on
 * keyboard focus.
 */
function CashChart({ rows, floor, months }: {
  rows: ForecastRow[]; floor: number | null; months: boolean;
}) {
  const [at, setAt] = useState<number | null>(null);
  const W = 720, H = 220, L = 64, R = 16, T = 12, B = 28;
  const values = rows.map((row) => row.end_cents);
  const refs = [0, ...(floor !== null ? [floor] : [])];
  const low = Math.min(...values, ...refs), high = Math.max(...values, ...refs);
  const pad = Math.max((high - low) * 0.08, 100);
  const min = low - pad, max = high + pad;
  const x = (i: number) => L + (rows.length === 1 ? 0 : (i * (W - L - R)) / (rows.length - 1));
  const y = (cents: number) => T + ((max - cents) * (H - T - B)) / (max - min);
  const path = rows.map((row, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${
    y(row.end_cents).toFixed(1)}`).join(" ");
  const ticks = [min + pad, (min + max) / 2, max - pad];
  const short = (cents: number) => {
    const d = cents / 100;
    return Math.abs(d) >= 1000 ? `${d < 0 ? "-" : ""}$${Math.abs(Math.round(d / 100) / 10)}k`
      : `${d < 0 ? "-" : ""}$${Math.abs(Math.round(d))}`;
  };
  const step = Math.max(1, Math.ceil(rows.length / 7));
  const label = (row: ForecastRow) => months ? row.label.slice(0, 3)
    : new Date(`${row.start}T00:00:00Z`).toLocaleDateString("en-US", {
      month: "short", day: "numeric", timeZone: "UTC" });
  const hovered = at === null ? null : rows[at];
  const move = (clientX: number, box: DOMRect) => {
    const px = ((clientX - box.left) / box.width) * W;
    const i = Math.round(((px - L) / (W - L - R)) * (rows.length - 1));
    setAt(Math.max(0, Math.min(rows.length - 1, i)));
  };
  return (
    <figure style={{ margin: "0 0 var(--s3)" }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
        aria-label={`Cash at the end of each ${months ? "month" : "week"}, from ${
          dollars(values[0])} to ${dollars(values[values.length - 1])}. The table below `
          + "has every figure."}
        style={{ width: "100%", height: "auto", display: "block" }}
        onPointerMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setAt(null)} onBlur={() => setAt(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setAt(Math.min(rows.length - 1, (at ?? -1) + 1));
          if (e.key === "ArrowLeft") setAt(Math.max(0, (at ?? rows.length) - 1));
        }}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} stroke="var(--line)" />
            <text x={L - 8} y={y(tick) + 4} textAnchor="end" fontSize="11"
              fill="var(--muted)">{short(tick)}</text>
          </g>
        ))}
        {/* Zero and the floor: reference lines, each with its name on it. */}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--line-strong)" />
        <text x={W - R} y={y(0) - 4} textAnchor="end" fontSize="11" fill="var(--muted)">
          zero</text>
        {floor !== null && (
          <>
            <line x1={L} x2={W - R} y1={y(floor)} y2={y(floor)} stroke="var(--muted)"
              strokeDasharray="4 4" />
            <text x={W - R} y={y(floor) - 4} textAnchor="end" fontSize="11"
              fill="var(--muted)">your floor, {short(floor)}</text>
          </>
        )}
        <path d={path} fill="none" stroke="var(--navy)" strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" />
        {rows.map((row, i) => (i % step === 0 || i === rows.length - 1) && (
          <text key={row.start} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11"
            fill="var(--muted)">{label(row)}</text>
        ))}
        {hovered && at !== null && (
          <>
            <line x1={x(at)} x2={x(at)} y1={T} y2={H - B} stroke="var(--line-strong)" />
            <circle cx={x(at)} cy={y(hovered.end_cents)} r="5" fill="var(--navy)"
              stroke="var(--surface)" strokeWidth="2" />
          </>
        )}
      </svg>
      <figcaption className="small" role="status" aria-label="The point on the chart"
        style={{ minHeight: "1.4em" }}>
        {hovered ? (
          <><strong>{dollars(hovered.end_cents)}</strong>{" "}
            <span className="muted">at the end of {months ? hovered.label
              : `the week of ${longDate(hovered.start)}`}
            {hovered.below_zero ? " · below zero"
              : hovered.below_floor ? " · under your floor" : ""}</span></>
        ) : <span className="muted">Point at the line, or use the arrow keys, for a
          figure.</span>}
      </figcaption>
    </figure>
  );
}
