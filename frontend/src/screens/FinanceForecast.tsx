import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Pill } from "../components/ui";
import {
  Forecast, ForecastLine, ForecastRow, ForecastView, ForecastWhatIf, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";
import {
  Adjusted, AskClaude, HowGood, LikelyAnnual, LineActions, NotCounted, Planned,
} from "./FinanceForecastTools";

/**
 * Finance → Forecast (P6 M2; matrix 13.18 to 13.20): the practice owner's,
 * and only for a practice with the Cash forecast module.
 *
 * Arithmetic on the practice's own books: cash today, then money in and out
 * week by week from what is known (invoices), what is regular (found in the
 * closed months), what is planned (typed by the owner) and the card. The
 * forecast itself is never stored. Every figure opens the lines it is made
 * of, and every line says where it came from.
 *
 * A what-if is a look: lines switched off, a what-if line switched on, an
 * amount tried. It is worked out by the server, drawn beside the forecast as
 * it stands, and saved nowhere.
 */

const VIEWS: [ForecastView, string][] = [
  ["30", "30 days"], ["90", "90 days"], ["180", "180 days"], ["months", "12 months"]];
const WEEKS: Record<string, number> = { "30": 5, "90": 13, "180": 26 };
const KIND = { known: "Known", regular: "Regular", card: "Card payment", planned: "Planned" };

export type Try = { off: string[]; on: string[]; amounts: Record<string, number> };
const NOTHING: Try = { off: [], on: [], amounts: {} };
const trying = (t: Try) => t.off.length + t.on.length + Object.keys(t.amounts).length > 0;

export function FinanceForecast() {
  const qc = useQueryClient();
  const [view, setView] = useState<ForecastView>("90");
  const [openRow, setOpenRow] = useState("");
  const [attempt, setAttempt] = useState<Try>(NOTHING);
  const [whatIf, setWhatIf] = useState<ForecastWhatIf | null>(null);
  const [error, setError] = useState("");
  const forecast = useQuery<Forecast>({
    queryKey: ["finance-forecast"],
    queryFn: () => api.get<Forecast>("/api/finance-forecast/") });
  const look = useMutation({
    mutationFn: (next: Try) => api.post<Forecast>("/api/finance-forecast/what-if/", next),
    onSuccess: (now) => { setError(""); setWhatIf(now.what_if); },
    onError: (e: Error) => setError(e.message) });
  // One look at a time: change what is tried, and ask the server again.
  const tryIt = (next: Try) => {
    setAttempt(next);
    if (trying(next)) look.mutate(next); else setWhatIf(null);
  };
  // Anything the owner says (a planned line, an adjustment, the floor) comes
  // back as the whole forecast; a look already open is worked out again.
  const said = (now: Forecast) => {
    setError(""); qc.setQueryData(["finance-forecast"], now);
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    if (trying(attempt)) look.mutate(attempt);
  };
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete";
                                           path: string; body?: object }) =>
      method === "post" ? api.post<Forecast>(`/api/finance-forecast/${path}`, body ?? {})
        : method === "patch" ? api.patch<Forecast>(`/api/finance-forecast/${path}`, body)
          : api.del<Forecast>(`/api/finance-forecast/${path}`),
    onSuccess: said, onError: (e: Error) => setError(e.message) });
  const send = (method: "post" | "patch" | "delete", path: string, body?: object) =>
    act.mutate({ method, path, body });

  if (forecast.isError) return <Banner kind="bad">{(forecast.error as Error).message}</Banner>;
  const data = forecast.data;
  if (!data) return <p>Working out the forecast…</p>;
  const months = view === "months";
  const pick = (rows: { weeks: ForecastRow[]; months: ForecastRow[] }) =>
    months ? rows.months : rows.weeks.slice(0, WEEKS[view]);
  const rows = pick(data);
  const other = whatIf && trying(attempt) ? pick(whatIf) : null;
  const summary = data.views[view];
  const byId = new Map(data.lines.map((line) => [line.id, line]));
  const last = rows[rows.length - 1].end;
  const within = data.lines.filter((line) => line.on_date <= last);
  const stale = data.accounts.filter((account) => account.stale);
  const span = months ? "the next 12 months" : `the next ${view} days`;
  const busy = act.isPending;
  const toggle = (group: string) => tryIt({ ...attempt, off: attempt.off.includes(group)
    ? attempt.off.filter((g) => g !== group) : [...attempt.off, group] });

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
          in the {months ? "month" : "week"} starting{" "}
          {longDate(summary.first_below_zero)}.</Banner>
      )}
      {!summary.first_below_zero && summary.first_below_floor && (
        <Banner kind="warn"><strong>Under your floor.</strong> The cash first falls below{" "}
          {dollars(data.floor_cents ?? 0)} in the {months ? "month" : "week"}{" "}
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
              <span className="small muted"> · {months ? summary.low_label
                : `the week of ${longDate(summary.low_start)}`}</span></dd>
          </div>
          <div>
            <dt className="small muted">Your floor</dt>
            <dd style={{ margin: 0 }}>
              <Floor cents={data.floor_cents} busy={busy}
                onSet={(floor_cents) => send("post", "floor/", { floor_cents })} />
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

      <WhatIf data={data} attempt={attempt} whatIf={other ? whatIf : null} view={view}
        busy={look.isPending} onTry={tryIt} />

      <Card title={`Cash, ${months ? "month by month" : "week by week"}`}
        actions={
          <span className="row tight" role="group" aria-label="How far ahead">
            {VIEWS.map(([key, label]) => (
              <button key={key} aria-pressed={view === key}
                className={view === key ? "small primary" : "ghost small"}
                onClick={() => { setView(key); setOpenRow(""); }}>{label}</button>
            ))}
          </span>}>
        <CashChart rows={rows} other={other} floor={data.floor_cents} months={months} />
        <div style={{ overflowX: "auto" }}>
          <table aria-label="The cash forecast as a table">
            <thead><tr><th>{months ? "Month" : "Week starting"}</th>
              <th className="money">Cash at the start</th><th className="money">Money in</th>
              <th className="money">Money out</th><th className="money">Cash at the end</th>
              {other && <th className="money">What if</th>}<th /></tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <RowAndLines key={row.start} row={row} months={months}
                  other={other ? other[index] : null} open={openRow === row.start}
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
        off={attempt.off} busy={busy} onToggle={toggle} send={send}
        note="Invoices you have sent, written, or scheduled, each on the day that client
              usually pays." />
      <Lines title="Regular"
        lines={within.filter((line) => line.kind === "regular" || line.kind === "card")}
        off={attempt.off} busy={busy} onToggle={toggle} send={send}
        amounts={attempt.amounts}
        onAmount={(group, cents) => {
          const amounts = { ...attempt.amounts };
          if (cents === null) delete amounts[group]; else amounts[group] = cents;
          tryIt({ ...attempt, amounts });
        }}
        note={data.ready
          ? "Found in your closed months, by category and payee. A charge on a card is "
            + "not cash until the card is paid, so it is listed here and counted in the "
            + "card's payment."
          : data.note} />
      <Planned planned={data.planned} attempt={attempt} busy={busy} onTry={tryIt}
        send={send} />
      <Adjusted adjustments={data.adjustments} busy={busy} send={send} />
      <NotCounted rows={data.left_out} busy={busy} send={send} />
      <LikelyAnnual rows={data.likely_annual} busy={busy} send={send} />
      <HowGood history={data.history} />
      <AskClaude view={view} includeNames={data.include_client_names} ready={data.ready}
        busy={busy} send={send} />
    </>
  );
}

// ---------------------------------------------------------------- the what-if

function WhatIf({ data, attempt, whatIf, view, busy, onTry }: {
  data: Forecast; attempt: Try; whatIf: ForecastWhatIf | null; view: ForecastView;
  busy: boolean; onTry: (next: Try) => void;
}) {
  const [client, setClient] = useState("");
  const on = trying(attempt);
  const name = (group: string) => {
    if (group.startsWith("client:")) {
      return `${data.clients.find((c) => `client:${c.id}` === group)?.name ?? "A client"} `
        + "(every invoice)";
    }
    return data.lines.find((line) => line.group === group)?.label
      ?? data.planned.find((p) => p.id === group)?.description ?? "A line";
  };
  const difference = whatIf ? whatIf.difference_at_low[view] : 0;
  return (
    <Card title="What if">
      <p className="small muted" style={{ marginTop: 0 }}>
        Try the forecast without a client, with a cost you are thinking about, or with a
        different draw. It is worked out again beside the forecast as it stands, and
        nothing is saved.
      </p>
      <div className="row tight">
        <select aria-label="A client to try the forecast without" value={client}
          style={{ width: "auto" }} onChange={(e) => setClient(e.target.value)}>
          <option value="">Without a client…</option>
          {data.clients.filter((c) => !attempt.off.includes(`client:${c.id}`))
            .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button className="small" disabled={!client || busy}
          onClick={() => { onTry({ ...attempt, off: [...attempt.off, `client:${client}`] });
                           setClient(""); }}>Try it</button>
        <span className="small muted">Or use "Try without" and "Try another amount" on any
          line below, and "Try it" on a what-if line you have planned.</span>
      </div>
      {on && (
        <div role="status" aria-label="The what-if" className="banner info"
          style={{ display: "block", marginTop: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}>
            <strong>What if:</strong>{" "}
            {[...attempt.off.map((g) => `without ${name(g)}`),
              ...attempt.on.map((id) => `with ${name(id)}`),
              ...Object.entries(attempt.amounts).map(
                ([g, cents]) => `${name(g)} at ${dollars(cents)}`)].join("; ")}.
          </p>
          {whatIf ? (
            <p className="small" style={{ margin: "var(--s1) 0 0" }}>
              The lowest point would be <strong>{dollars(whatIf.views[view].low_cents)}
              </strong>, {difference === 0 ? "the same as it stands"
                : `${dollars(Math.abs(difference))} ${difference > 0 ? "higher" : "lower"} `
                  + "than it stands"}
              {whatIf.views[view].first_below_zero
                ? `; below zero from ${longDate(whatIf.views[view].first_below_zero!)}` : ""}.
            </p>
          ) : <p className="small muted" style={{ margin: "var(--s1) 0 0" }}>
            Working it out…</p>}
          <button className="ghost small" style={{ marginTop: "var(--s2)" }}
            onClick={() => onTry(NOTHING)}>Clear the what-if</button>
        </div>
      )}
    </Card>
  );
}

// ----------------------------------------------------------------- the floor

export function Floor({ cents, busy, onSet }: {
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

function RowAndLines({ row, other, lines, open, months, onToggle }: {
  row: ForecastRow; other: ForecastRow | null; lines: ForecastLine[]; open: boolean;
  months: boolean; onToggle: () => void;
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
        {other && (
          <td className="money">{dollars(other.end_cents)}
            {other.below_zero && <> <Pill kind="bad">below zero</Pill></>}</td>
        )}
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
          {other && <td />}
          <td />
        </tr>
      ))}
    </>
  );
}

/** The lines of one kind, one row for each thing (a rent, an invoice, a
 *  schedule) with when it next falls and how often in the span shown. */
function Lines({ title, lines, note, off, amounts, busy, onToggle, onAmount, send }: {
  title: string; lines: ForecastLine[]; note: string; off: string[]; busy: boolean;
  amounts?: Record<string, number>;
  onToggle: (group: string) => void;
  onAmount?: (group: string, cents: number | null) => void;
  send: (method: "post" | "patch" | "delete", path: string, body?: object) => void;
}) {
  const groups = new Map<string, ForecastLine[]>();
  for (const line of lines) groups.set(line.group, [...(groups.get(line.group) ?? []), line]);
  const things = [...groups.values()];
  return (
    <Card title={`${title} (${things.length})`}>
      <p className="small muted" style={{ marginTop: 0 }}>{note}</p>
      {things.length > 0 && (
        <details>
          <summary className="small">Show {things.length === 1 ? "it" : `all ${things.length}`}
          </summary>
          <table aria-label={`${title} lines`}>
            <thead><tr><th>Next</th><th>What</th><th>Where it comes from</th>
              <th className="money">In</th><th className="money">Out</th><th /></tr></thead>
            <tbody>
              {things.map((rows) => {
                const line = rows[0];
                const tried = off.includes(line.group);
                return (
                  <tr key={line.group} style={tried ? { opacity: 0.55 } : undefined}>
                    <td style={{ whiteSpace: "nowrap" }}>{longDate(line.on_date)}
                      {rows.length > 1 && <div className="small muted">
                        {rows.length} times shown</div>}</td>
                    <td><Link to={line.link}>{line.label}</Link>
                      {line.category && <div className="small muted">{line.category}</div>}
                      {line.cadence && <> <Pill>{line.cadence}</Pill></>}
                      {!line.counted && <> <Pill>on a card</Pill></>}
                      {tried && <> <Pill kind="warn">tried without</Pill></>}</td>
                    <td className="small">{line.detail}
                      {line.adjusted && <div><strong>{line.adjusted}</strong></div>}</td>
                    <td className="money">{line.direction === "in"
                      ? dollars(line.amount_cents) : ""}</td>
                    <td className="money">{line.direction === "out"
                      ? dollars(line.amount_cents) : ""}</td>
                    <td className="money">
                      <LineActions line={line} tried={tried} busy={busy}
                        trial={amounts?.[line.group]} onToggle={() => onToggle(line.group)}
                        onAmount={onAmount ? (cents) => onAmount(line.group, cents)
                          : undefined}
                        send={send} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

// ----------------------------------------------------------------- the chart

/**
 * The cash at the end of each week or month as a 2px line, with zero and the
 * floor as labelled reference lines. With a what-if, a second series: its
 * own colour, dashed, so it is never told apart by colour alone, with a
 * legend and its name at the end of the line. Every value is also in the
 * table under it, so the picture gates nothing, and the same readout is on
 * hover and on keyboard focus.
 */
export function CashChart({ rows, other, floor, months }: {
  rows: ForecastRow[]; other: ForecastRow[] | null; floor: number | null; months: boolean;
}) {
  const [at, setAt] = useState<number | null>(null);
  const W = 720, H = 220, L = 64, R = other ? 72 : 16, T = 12, B = 28;
  const values = [...rows, ...(other ?? [])].map((row) => row.end_cents);
  const refs = [0, ...(floor !== null ? [floor] : [])];
  const low = Math.min(...values, ...refs), high = Math.max(...values, ...refs);
  const pad = Math.max((high - low) * 0.08, 100);
  const min = low - pad, max = high + pad;
  const x = (i: number) => L + (rows.length === 1 ? 0 : (i * (W - L - R)) / (rows.length - 1));
  const y = (cents: number) => T + ((max - cents) * (H - T - B)) / (max - min);
  const path = (series: ForecastRow[]) => series.map((row, i) => `${i ? "L" : "M"}${
    x(i).toFixed(1)},${y(row.end_cents).toFixed(1)}`).join(" ");
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
  const end = rows.length - 1;
  return (
    <figure style={{ margin: "0 0 var(--s3)" }}>
      {other && (
        <ul className="row tight small" aria-label="What the lines are"
          style={{ listStyle: "none", padding: 0, margin: "0 0 var(--s1)" }}>
          <li><svg width="22" height="8" aria-hidden="true"><line x1="0" x2="22" y1="4"
            y2="4" stroke="var(--chart-1)" strokeWidth="2" /></svg> As it stands</li>
          <li><svg width="22" height="8" aria-hidden="true"><line x1="0" x2="22" y1="4"
            y2="4" stroke="var(--chart-2)" strokeWidth="2" strokeDasharray="5 3" /></svg>{" "}
            What if</li>
        </ul>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
        aria-label={`Cash at the end of each ${months ? "month" : "week"}, from ${
          dollars(rows[0].end_cents)} to ${dollars(rows[end].end_cents)}.${
          other ? ` What if: from ${dollars(other[0].end_cents)} to ${
            dollars(other[end].end_cents)}.` : ""} The table below has every figure.`}
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
        <text x={L + 4} y={y(0) - 4} fontSize="11" fill="var(--muted)">zero</text>
        {floor !== null && (
          <>
            <line x1={L} x2={W - R} y1={y(floor)} y2={y(floor)} stroke="var(--muted)"
              strokeDasharray="2 4" />
            {/* Above its line, or below it when it would sit on "zero". */}
            <text x={L + 4} fontSize="11" fill="var(--muted)"
              y={Math.abs(y(floor) - y(0)) < 14 && y(floor) <= y(0) ? y(floor) - 16
                : y(floor) - 4}>
              your floor, {short(floor)}</text>
          </>
        )}
        <path d={path(rows)} data-series="forecast" fill="none" stroke="var(--chart-1)"
          strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {other && (
          <>
            <path d={path(other)} data-series="what-if" fill="none" stroke="var(--chart-2)"
              strokeWidth="2" strokeDasharray="5 3" strokeLinejoin="round" />
            {/* Named at the end of each line: never by colour alone. Text in
                the text colour; the mark beside it carries the series. */}
            <text x={x(end) + 6} y={y(rows[end].end_cents) + 4} fontSize="11"
              fill="var(--text)">as it stands</text>
            <text x={x(end) + 6} fontSize="11" fill="var(--text)"
              y={y(other[end].end_cents) + (Math.abs(y(other[end].end_cents)
                - y(rows[end].end_cents)) < 12 ? 16 : 4)}>what if</text>
          </>
        )}
        {rows.map((row, i) => (i % step === 0 || i === rows.length - 1) && (
          <text key={row.start} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11"
            fill="var(--muted)">{label(row)}</text>
        ))}
        {hovered && at !== null && (
          <>
            <line x1={x(at)} x2={x(at)} y1={T} y2={H - B} stroke="var(--line-strong)" />
            <circle cx={x(at)} cy={y(hovered.end_cents)} r="5" fill="var(--chart-1)"
              stroke="var(--surface)" strokeWidth="2" />
            {other && <circle cx={x(at)} cy={y(other[at].end_cents)} r="5"
              fill="var(--chart-2)" stroke="var(--surface)" strokeWidth="2" />}
          </>
        )}
      </svg>
      <figcaption className="small" role="status" aria-label="The point on the chart"
        style={{ minHeight: "1.4em" }}>
        {hovered && at !== null ? (
          <><strong>{dollars(hovered.end_cents)}</strong>{" "}
            <span className="muted">at the end of {months ? hovered.label
              : `the week of ${longDate(hovered.start)}`}
            {hovered.below_zero ? " · below zero"
              : hovered.below_floor ? " · under your floor" : ""}</span>
            {other && <> · what if <strong>{dollars(other[at].end_cents)}</strong></>}</>
        ) : <span className="muted">Point at the line, or use the arrow keys, for a
          figure.</span>}
      </figcaption>
    </figure>
  );
}
