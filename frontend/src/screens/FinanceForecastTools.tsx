import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Field, Pill } from "../components/ui";
import {
  ExplainAnswer, Forecast, ForecastAdjustment, ForecastAiStatus, ForecastHistory,
  ForecastLine, ForecastReview, ForecastView, PlannedLine, ReviewItem, api,
} from "../lib/api";
import { FINANCE_DISCLAIMER } from "../lib/finance";
import { dollars, longDate } from "../lib/money";
import type { Try } from "./FinanceForecast";

/**
 * What the practice owner says to the forecast (P6 M2, stop 2): planned
 * lines, corrections to the lines it found, what is left out, what is likely
 * annual; how good it has been; and the two buttons that ask Claude.
 *
 * Everything here goes through the forecast's own routes and comes back as
 * the whole forecast. Nothing Claude returns enters the forecast: the review
 * is a form, and each answer is the owner's own, confirmed one at a time.
 */

export type Send = (method: "post" | "patch" | "delete", path: string, body?: object) => void;
const today = () => new Date().toISOString().slice(0, 10);

// ------------------------------------------------------ one line's actions

const CHANGES: [string, string][] = [
  ["amount", "A different amount"], ["day", "A different day of the month"],
  ["pause", "Pause it"], ["end", "End it"], ["not_regular", "It is not regular"]];

export function LineActions({ line, tried, busy, trial, onToggle, onAmount, send }: {
  line: ForecastLine; tried: boolean; busy: boolean; trial?: number;
  onToggle: () => void; onAmount?: (cents: number | null) => void; send: Send;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("amount");
  const [cents, setCents] = useState(line.amount_cents);
  const [day, setDay] = useState("1");
  const [from, setFrom] = useState(today());
  const [until, setUntil] = useState("");
  const [expected, setExpected] = useState(line.on_date);
  const family = line.group.split(":")[0];
  const regular = family === "pattern" || family === "tax";
  const invoice = family === "invoice";
  // Closed, the form goes back to how it opens: the next change is its own.
  const done = () => { setOpen(false); setKind("amount"); setFrom(today()); setUntil(""); };
  return (
    <>
      <button className="ghost small" aria-pressed={tried}
        aria-label={`${tried ? "Put back" : "Try without"} ${line.label}`}
        onClick={onToggle}>{tried ? "Put back" : "Try without"}</button>
      {(regular || invoice) && (
        <>{" "}<button className="ghost small" aria-expanded={open}
          aria-label={`Change ${line.label}`} onClick={() => setOpen(!open)}>
          {open ? "Close" : "Change…"}</button></>
      )}
      {open && regular && (
        <div className="panel" role="group" aria-label={`Change ${line.label}`}
          style={{ textAlign: "left", marginTop: "var(--s2)" }}>
          <div className="row tight">
            <select aria-label={`How ${line.label} changes`} value={kind}
              style={{ width: "auto" }} onChange={(e) => setKind(e.target.value)}>
              {CHANGES.filter(([value]) => family === "pattern" || value !== "day")
                .map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </select>
            {kind === "amount" && (
              <PriceBox label={`The new amount of ${line.label}`} cents={cents}
                onChange={setCents} />)}
            {kind === "day" && (
              <input type="number" min={1} max={31} value={day} style={{ width: "5rem" }}
                aria-label={`The new day of the month for ${line.label}`}
                onChange={(e) => setDay(e.target.value)} />)}
            {kind !== "not_regular" && (
              <label className="small inline">from
                <input type="date" aria-label={`From when ${line.label} changes`}
                  value={from} style={{ width: "auto" }}
                  onChange={(e) => setFrom(e.target.value)} /></label>)}
            {kind === "pause" && (
              <label className="small inline">until
                <input type="date" aria-label={`Until when ${line.label} is paused`}
                  value={until} style={{ width: "auto" }}
                  onChange={(e) => setUntil(e.target.value)} /></label>)}
          </div>
          <div className="row tight" style={{ marginTop: "var(--s2)" }}>
            <button className="small primary" disabled={busy}
              onClick={() => {
                send("post", "adjust/", {
                  line: line.group, kind,
                  ...(kind === "amount" ? { amount_cents: cents } : {}),
                  ...(kind === "day" ? { day_of_month: Number(day) } : {}),
                  ...(kind !== "not_regular" ? { from_date: from } : {}),
                  ...(kind === "pause" && until ? { until_date: until } : {}) });
                done();
              }}>Save the change</button>
            {onAmount && kind === "amount" && (
              <button className="ghost small"
                onClick={() => { onAmount(cents); done(); }}>
                Only try this amount</button>)}
            {onAmount && trial !== undefined && (
              <button className="ghost small" onClick={() => { onAmount(null); done(); }}>
                Stop trying {dollars(trial)}</button>)}
          </div>
          <p className="tiny muted" style={{ margin: "var(--s2) 0 0" }}>
            A change is kept, shown beside the line, and can be undone. Trying an amount
            is a look and is not kept.</p>
        </div>
      )}
      {open && invoice && (
        <div className="panel" role="group" aria-label={`Change ${line.label}`}
          style={{ textAlign: "left", marginTop: "var(--s2)" }}>
          <div className="row tight">
            <label className="small inline">I expect it on
              <input type="date" aria-label={`When you expect ${line.label}`}
                value={expected} style={{ width: "auto" }}
                onChange={(e) => setExpected(e.target.value)} /></label>
            <button className="small primary" disabled={busy || !expected}
              onClick={() => { send("post", "adjust/", { line: line.group, kind: "expected",
                                                         expected_on: expected });
                               done(); }}>Move it</button>
            <button className="ghost small" disabled={busy}
              onClick={() => { send("post", "adjust/", { line: line.group,
                                                         kind: "leave_out" });
                               done(); }}>Leave it out</button>
          </div>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------ planned lines

type Draft = { description: string; direction: "in" | "out"; amount_cents: number;
               on_date: string; repeat: "" | "monthly" | "quarterly"; until: string;
               is_what_if: boolean };

/** The form a planned line is typed in: also what a confirmed "likely
 *  annual" item and an answer in a review are. The amount is the owner's. */
export function PlannedForm({ start, label, busy, save, onSave, onCancel }: {
  start: Partial<Draft>; label: string; busy: boolean; save: string;
  onSave: (draft: Draft) => void; onCancel?: () => void;
}) {
  const [form, setForm] = useState<Draft>({
    description: "", direction: "out", amount_cents: 0, on_date: today(), repeat: "",
    until: "", is_what_if: false, ...start });
  const set = (patch: Partial<Draft>) => setForm({ ...form, ...patch });
  return (
    <div role="group" aria-label={label}>
      <div className="row">
        <Field label="What it is">
          <input aria-label={`${label}: what it is`} value={form.description}
            maxLength={200} placeholder="A hire, new equipment, a deposit"
            onChange={(e) => set({ description: e.target.value })} />
        </Field>
        <Field label="Money">
          <select aria-label={`${label}: in or out`} value={form.direction}
            onChange={(e) => set({ direction: e.target.value as "in" | "out" })}>
            <option value="out">Going out</option>
            <option value="in">Coming in</option>
          </select>
        </Field>
        <Field label="Amount">
          <PriceBox label={`${label}: amount`} cents={form.amount_cents}
            onChange={(amount_cents) => set({ amount_cents })} />
        </Field>
        <Field label="When">
          <input type="date" aria-label={`${label}: date`} value={form.on_date}
            onChange={(e) => set({ on_date: e.target.value })} />
        </Field>
        <Field label="How often">
          <select aria-label={`${label}: how often`} value={form.repeat}
            onChange={(e) => set({ repeat: e.target.value as Draft["repeat"],
                                   until: e.target.value ? form.until : "" })}>
            <option value="">Once</option>
            <option value="monthly">Every month</option>
            <option value="quarterly">Every three months</option>
          </select>
        </Field>
        {form.repeat && (
          <Field label="Until (empty: until further notice)">
            <input type="date" aria-label={`${label}: until`} value={form.until}
              onChange={(e) => set({ until: e.target.value })} />
          </Field>
        )}
      </div>
      <div className="row tight">
        <label className="small inline">
          <input type="checkbox" checked={form.is_what_if}
            onChange={(e) => set({ is_what_if: e.target.checked })} />
          A what-if: drawn beside the forecast, not counted until I try it
        </label>
        <button className="small primary"
          disabled={busy || !form.description.trim() || form.amount_cents <= 0
            || !form.on_date}
          onClick={() => onSave(form)}>{save}</button>
        {onCancel && <button className="ghost small" onClick={onCancel}>Cancel</button>}
      </div>
    </div>
  );
}

const body = (draft: Draft) => ({
  description: draft.description.trim(), direction: draft.direction,
  amount_cents: draft.amount_cents, on_date: draft.on_date, repeat: draft.repeat,
  until: draft.repeat && draft.until ? draft.until : null, is_what_if: draft.is_what_if });

const STATE = { planned: "", what_if: "what-if", happened: "happened",
                lapsed: "did not happen?" };

export function Planned({ planned, attempt, busy, onTry, send }: {
  planned: PlannedLine[]; attempt: Try; busy: boolean; onTry: (next: Try) => void;
  send: Send;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <Card title={`Planned (${planned.filter((p) => p.state !== "happened").length})`}
      actions={!adding && <button className="small" onClick={() => setAdding(true)}>
        Add a planned line</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        What your books cannot know: a hire, a client who has said they are leaving, new
        equipment, a deposit. A planned line is in the forecast until it happens, you
        remove it, or its date passes. It never becomes an entry in your books.
      </p>
      {adding && (
        <PlannedForm label="The new planned line" start={{}} busy={busy} save="Add it"
          onCancel={() => setAdding(false)}
          onSave={(draft) => { send("post", "planned/", body(draft)); setAdding(false); }} />
      )}
      {planned.length > 0 && (
        <table aria-label="Planned lines">
          <tbody>
            {planned.map((row) => {
              const tried = attempt.on.includes(row.id);
              return (
                <tr key={row.id} className={row.state === "happened" ? "muted" : undefined}>
                  <td style={{ whiteSpace: "nowrap" }}>{longDate(row.on_date)}
                    {row.repeat && <div className="small muted">
                      {row.repeat === "monthly" ? "every month" : "every three months"}
                      {row.until ? ` until ${longDate(row.until)}` : ""}</div>}</td>
                  <td>{row.description}
                    {STATE[row.state] && <> <Pill kind={row.state === "lapsed" ? "warn" : ""}>
                      {STATE[row.state]}</Pill></>}
                    {row.source === "review" && <> <Pill>from a review</Pill></>}
                    {row.source === "annual" && <> <Pill>confirmed as annual</Pill></>}
                    {tried && <> <Pill kind="warn">being tried</Pill></>}</td>
                  <td className="money">{row.direction === "in" ? "in " : "out "}
                    {dollars(row.amount_cents)}</td>
                  <td className="money">
                    {row.state === "what_if" && (
                      <>
                        <button className="ghost small" aria-pressed={tried}
                          aria-label={`${tried ? "Stop trying" : "Try"} ${row.description}`}
                          onClick={() => onTry({ ...attempt, on: tried
                            ? attempt.on.filter((id) => id !== row.id)
                            : [...attempt.on, row.id] })}>
                          {tried ? "Stop trying" : "Try it"}</button>{" "}
                        <button className="ghost small" disabled={busy}
                          aria-label={`Plan ${row.description}`}
                          onClick={() => send("patch", `planned/${row.id}/`,
                                              { is_what_if: false })}>
                          Save as planned</button>{" "}
                      </>
                    )}
                    {row.state !== "happened" && (
                      <>
                        <button className="ghost small" disabled={busy}
                          aria-label={`${row.description} happened`}
                          onClick={() => send("post", `planned/${row.id}/happened/`)}>
                          This happened</button>{" "}
                        <button className="ghost small" disabled={busy}
                          aria-label={`Remove ${row.description}`}
                          onClick={() => send("delete", `planned/${row.id}/`)}>
                          Remove</button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// ------------------------------------------- adjustments, left out, annual

export function Adjusted({ adjustments, busy, send }: {
  adjustments: ForecastAdjustment[]; busy: boolean; send: Send;
}) {
  if (adjustments.length === 0) return null;
  return (
    <Card title={`What you have changed (${adjustments.length})`}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Your own corrections to lines the forecast found. Each is kept from one month's
        close to the next, and can be undone.</p>
      <table aria-label="What you have changed"><tbody>
        {adjustments.map((row) => (
          <tr key={row.id}>
            <td>{row.label}{row.source === "review" && <> <Pill>from a review</Pill></>}</td>
            <td>{row.text}</td>
            <td className="small muted">{longDate(row.at.slice(0, 10))}, {row.by}</td>
            <td className="money">
              <button className="ghost small" disabled={busy}
                aria-label={`Undo the change to ${row.label}`}
                onClick={() => send("post", `adjust/${row.id}/undo/`)}>Undo</button></td>
          </tr>
        ))}
      </tbody></table>
    </Card>
  );
}

export function NotCounted({ rows, busy, send }: {
  rows: Forecast["left_out"]; busy: boolean; send: Send;
}) {
  const [when, setWhen] = useState<Record<string, string>>({});
  return (
    <Card title="Not counted">
      <p className="small muted" style={{ marginTop: 0 }}>
        Invoices more than 60 days past due, and any you left out. They are not in the
        forecast: hoping is not forecasting. Put one back with the day you expect it.</p>
      {rows.length === 0 && <p className="small">None.</p>}
      {rows.length > 0 && <table aria-label="Not counted"><tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td><Link to={row.link}>{row.label}</Link>
              <div className="small muted">{row.why}; due {longDate(row.due_date)}
                {row.days_overdue > 0 ? `, ${row.days_overdue} days ago` : ""}</div></td>
            <td className="money">{dollars(row.amount_cents)}</td>
            <td className="money">
              {row.adjustment ? (
                <button className="ghost small" disabled={busy}
                  aria-label={`Put back ${row.label}`}
                  onClick={() => send("post", `adjust/${row.adjustment}/undo/`)}>
                  Put it back</button>
              ) : (
                <span className="row tight" style={{ justifyContent: "flex-end" }}>
                  <input type="date" aria-label={`When you expect ${row.label}`}
                    value={when[row.id] ?? ""} style={{ width: "auto" }}
                    onChange={(e) => setWhen({ ...when, [row.id]: e.target.value })} />
                  <button className="ghost small" disabled={busy || !when[row.id]}
                    aria-label={`Put back ${row.label}`}
                    onClick={() => send("post", "adjust/", {
                      line: row.group, kind: "expected", expected_on: when[row.id] })}>
                    Put it back on that day</button>
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody></table>}
    </Card>
  );
}

export function LikelyAnnual({ rows, busy, send }: {
  rows: Forecast["likely_annual"]; busy: boolean; send: Send;
}) {
  const [open, setOpen] = useState("");
  return (
    <Card title="Likely annual, to confirm">
      <p className="small muted" style={{ marginTop: 0 }}>
        Seen once, about a year ago, and not since. They are <strong>not in the
        forecast</strong> until you confirm them, with the amount and the day you expect
        this year.
      </p>
      {rows.length === 0 && <p className="small">None.</p>}
      {rows.length > 0 && <table aria-label="Likely annual, to confirm"><tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.label}{row.category && <span className="muted"> · {row.category}</span>}
              <div className="small muted">last on {longDate(row.last_on)}; likely again
                about {longDate(row.likely_on)}</div>
              {open === row.id && (
                <PlannedForm label={`Confirming ${row.label}`} busy={busy}
                  save="Confirm it" onCancel={() => setOpen("")}
                  start={{ description: row.label, direction: row.direction,
                           amount_cents: row.amount_cents,
                           on_date: row.likely_on < today() ? today() : row.likely_on }}
                  onSave={(draft) => {
                    send("post", "planned/", { ...body(draft), source: "annual",
                                               line: row.group });
                    setOpen("");
                  }} />
              )}</td>
            <td className="money">{dollars(row.amount_cents)}</td>
            <td className="money">
              <button className="ghost small" aria-label={`Confirm ${row.label}`}
                onClick={() => setOpen(open === row.id ? "" : row.id)}>Confirm…</button>{" "}
              <button className="ghost small" disabled={busy}
                aria-label={`${row.label} is not regular`}
                onClick={() => send("post", "adjust/", { line: row.group,
                                                         kind: "not_regular" })}>
                Not regular</button>
            </td>
          </tr>
        ))}
      </tbody></table>}
    </Card>
  );
}

// ------------------------------------------------------ how good it has been

export function HowGood({ history }: { history: ForecastHistory[] }) {
  if (history.length === 0) return null;
  const gap = (cents: number) => `${cents > 0 ? "+" : cents < 0 ? "−" : ""}${
    dollars(Math.abs(cents))}`;
  return (
    <Card title="How good it has been">
      <p className="small muted" style={{ marginTop: 0 }}>
        For each closed month: the forecast as it stood when the month began, beside what
        happened. There is no score. The differences are the information.</p>
      <div style={{ overflowX: "auto" }}>
        <table aria-label="How good it has been">
          <thead><tr><th>Month</th><th className="money">Cash at the end, forecast</th>
            <th className="money">Actual</th><th className="money">Money in</th>
            <th className="money">Money out</th><th>The largest differences</th></tr></thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.month}>
                <td>{row.label}
                  {row.taken_on.slice(8) !== "01" && <div className="small muted">
                    as it stood on {longDate(row.taken_on)}</div>}</td>
                <td className="money">{dollars(row.forecast.end_cents)}</td>
                <td className="money"><strong>{dollars(row.actual.end_cents)}</strong>
                  <div className="small muted">
                    {gap(row.actual.end_cents - row.forecast.end_cents)}</div></td>
                <td className="money">{dollars(row.actual.in_cents)}
                  <div className="small muted">forecast {dollars(row.forecast.in_cents)}
                  </div></td>
                <td className="money">{dollars(row.actual.out_cents)}
                  <div className="small muted">forecast {dollars(row.forecast.out_cents)}
                  </div></td>
                <td className="small">{row.largest.length === 0 ? "None." : row.largest.map(
                  (each) => `${each.name}: forecast ${dollars(each.forecast_cents)}, was ${
                    dollars(each.actual_cents)}`).join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ------------------------------------------------------- the Claude buttons

const price = (usd: string | undefined) => `about $${Number(usd ?? 0).toFixed(2)}`;

export function AskClaude({ view, includeNames, ready, busy, send }: {
  view: ForecastView; includeNames: boolean; ready: boolean; busy: boolean; send: Send;
}) {
  const qc = useQueryClient();
  // What a press costs and how many are left today. Asks Claude nothing.
  const status = useQuery<ForecastAiStatus>({
    queryKey: ["finance-forecast-ai"],
    queryFn: () => api.get<ForecastAiStatus>("/api/finance-forecast/explain/") });
  const [answer, setAnswer] = useState<ExplainAnswer | null>(null);
  const [review, setReview] = useState<ForecastReview | null>(null);
  const [error, setError] = useState("");
  const spent = () => qc.invalidateQueries({ queryKey: ["finance-forecast-ai"] });
  const explain = useMutation({
    mutationFn: () => api.post<ExplainAnswer>("/api/finance-forecast/explain/", {
      view: view === "months" ? "180" : view }),
    onSuccess: (data) => { setAnswer(data); setError(""); spent(); },
    onError: (e: Error) => { setError(e.message); spent(); } });
  const ask = useMutation({
    mutationFn: () => api.post<ForecastReview>("/api/finance-forecast/review/", {}),
    onSuccess: (data) => { setReview(data); setError(""); spent(); },
    onError: (e: Error) => { setError(e.message); spent(); } });
  const s = status.data;
  const waiting = explain.isPending || ask.isPending;
  return (
    <Card title="Ask Claude">
      <p className="small muted" style={{ marginTop: 0 }}>
        The forecast's numbers are arithmetic on your books; Claude never supplies one.
        It can explain the forecast, and it can review how your books were read and ask
        what they cannot know. Nothing is sent until you press, and nothing it says
        enters the forecast unless you confirm it.
      </p>
      <label className="row tight small">
        <input type="checkbox" checked={includeNames} disabled={busy}
          onChange={(e) => send("post", "client-names/", { include: e.target.checked })} />
        Include client names in AI explanations
      </label>
      <p className="small muted" style={{ marginTop: "var(--s1)" }}>
        {includeNames
          ? "Clients are sent by name. Invoice numbers and contact details never are."
          : "Clients are sent as “Client A”, “Client B”, never by name. The payees and "
            + "categories of your expenses are sent by name."}
      </p>
      {error && <Banner kind="bad">{error}</Banner>}
      {s?.refused ? <p className="small muted">{s.refused}</p> : (
        <div className="row tight">
          <button className="small" disabled={waiting || !s} onClick={() => explain.mutate()}>
            {explain.isPending ? "Asking Claude…"
              : `Explain this forecast (${price(s?.estimate_usd)})`}</button>
          <button className="small" disabled={waiting || !s || !ready}
            onClick={() => ask.mutate()}>
            {ask.isPending ? "Asking Claude…"
              : `Review with Claude (${price(s?.review_estimate_usd)})`}</button>
          {s && <span className="small muted">{s.used_today} of {s.cap} used today.</span>}
        </div>
      )}
      {!ready && !s?.refused && <p className="small muted">A review reads your closed
        months, so it needs two of them.</p>}
      {answer && (
        <div className="banner info" role="note" aria-label="Explanation"
          style={{ marginTop: "var(--s3)", display: "block" }}>
          <p className="small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{answer.text}</p>
          <p className="tiny muted" style={{ margin: "var(--s2) 0 0" }}>
            This cost ${Number(answer.cost_usd).toFixed(4)}. {answer.used_today} of{" "}
            {answer.cap} used today. {FINANCE_DISCLAIMER}</p>
        </div>
      )}
      {review && <Review review={review} busy={busy} send={send}
        onClose={() => setReview(null)} />}
    </Card>
  );
}

const seen = (item: ReviewItem) => item.months.map(
  (m) => `${m.month} ${dollars(m.amount_cents)}`).join(", ");

/** The three lists of a review, as a form. Each answer is sent, one at a
 *  time, only when its own button is pressed. Closing it changes nothing. */
function Review({ review, busy, send, onClose }: {
  review: ForecastReview; busy: boolean; send: Send; onClose: () => void;
}) {
  const [done, setDone] = useState<Record<string, string>>({});
  const answered = (key: string, text: string) => setDone({ ...done, [key]: text });
  const nothing = review.one_offs.length + review.missed.length
    + review.questions.length === 0;
  return (
    <section aria-label="The review" className="panel" style={{ marginTop: "var(--s3)" }}>
      <p className="small" style={{ marginTop: 0 }}>
        <strong>Claude's review.</strong> Answer what you want to; each answer is yours
        and is sent when you press its button. Closing this changes nothing.{" "}
        <span className="muted">This cost ${Number(review.cost_usd).toFixed(4)}.{" "}
          {review.used_today} of {review.cap} used today.</span>
      </p>
      {nothing && <p className="small">It found nothing to question.</p>}

      {review.one_offs.length > 0 && <h4>Regular lines that look like one-offs</h4>}
      {review.one_offs.map((item) => (
        <div key={item.group} role="group" aria-label={`Review of ${item.who}`}
          style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>{item.who}</strong>
            {item.category && <span className="muted"> · {item.category}</span>}:{" "}
            {item.why} <span className="muted">In your books: {seen(item)}.</span></p>
          {done[item.group] ? <p className="small muted">{done[item.group]}</p> : (
            <div className="row tight">
              <button className="small" disabled={busy}
                onClick={() => { send("post", "adjust/", { line: item.group,
                                                           kind: "not_regular",
                                                           source: "review" });
                                 answered(item.group, "Taken out of the forecast."); }}>
                It is a one-off</button>
              <button className="ghost small"
                onClick={() => answered(item.group, "Left as a regular line.")}>
                It is regular</button>
            </div>
          )}
        </div>
      ))}

      {review.missed.length > 0 && <h4>Looks recurring, and was not picked up</h4>}
      {review.missed.map((item) => (
        <div key={item.group} role="group" aria-label={`Review of ${item.who}`}
          style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>{item.who}</strong>
            {item.category && <span className="muted"> · {item.category}</span>}:{" "}
            {item.why} <span className="muted">In your books: {seen(item)}.</span></p>
          {done[item.group] ? <p className="small muted">{done[item.group]}</p> : (
            <>
              <PlannedForm label={`Adding ${item.who}`} busy={busy} save="Add it"
                start={{ description: item.who, direction: item.direction,
                         amount_cents: item.last_amount_cents, repeat: "monthly" }}
                onSave={(draft) => { send("post", "planned/", { ...body(draft),
                                                                source: "review" });
                                     answered(item.group, "Added as a planned line."); }} />
              <button className="ghost small"
                onClick={() => answered(item.group, "Not added.")}>No</button>
            </>
          )}
        </div>
      ))}

      {review.questions.length > 0 && <h4>What your books cannot know</h4>}
      {review.questions.map((item, index) => {
        const key = `q${index}`;
        return (
          <div key={key} role="group" aria-label={`Question ${index + 1}`}
            style={{ marginBottom: "var(--s3)" }}>
            <p className="small" style={{ margin: 0 }}>{item.question}</p>
            {done[key] ? <p className="small muted">{done[key]}</p> : (
              <>
                <PlannedForm label={`Answer ${index + 1}`} busy={busy}
                  save="Add it to the forecast" start={{}}
                  onSave={(draft) => { send("post", "planned/", { ...body(draft),
                                                                  source: "review" });
                                       answered(key, "Added as a planned line."); }} />
                <button className="ghost small"
                  onClick={() => answered(key, "Nothing planned.")}>Nothing planned</button>
              </>
            )}
          </div>
        );
      })}
      <p className="tiny muted" role="note" aria-label="Review disclaimer">
        {review.disclaimer}</p>
      <button className="ghost small" onClick={onClose}>Close the review</button>
    </section>
  );
}
