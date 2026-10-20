import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { AiGate } from "../components/DemoVisitor";
import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Pill } from "../components/ui";
import {
  ExplainAnswer, ForecastAiStatus, ForecastRow, ForecastView, ForecastWhatIf,
  PersonalForecast, PersonalForecastLine, PersonalPlanned, PersonalReview,
  PersonalReviewItem, api,
} from "../lib/api";
import { dollars, longDate, toCents } from "../lib/money";
import { CashChart, Floor } from "./FinanceForecast";
import { Draft, HowGood, PlannedForm } from "./FinanceForecastTools";

/**
 * Personal → Forecast (P6 M4 stop 3, decision 15): M2's forecast on the
 * household's own accounts. Its own page, and never drawn in the same chart
 * as the business forecast.
 *
 * Every figure is the server's arithmetic on the owner's own lines: cash
 * today, what is known (pay from the practice, debts under the plan, yearly
 * bills, estimated tax), what is regular, what is planned. A what-if is a
 * look, worked out by the server and saved nowhere.
 */

const VIEWS: [ForecastView, string][] = [
  ["30", "30 days"], ["90", "90 days"], ["180", "180 days"], ["months", "12 months"]];
const WEEKS: Record<string, number> = { "30": 5, "90": 13, "180": 26 };
const KIND = { known: "Known", regular: "Regular", planned: "Planned" };

type Try = { off: string[]; on: string[]; amounts: Record<string, number> };
type Send = (method: "post" | "patch" | "delete", path: string, body?: object) => void;
const NOTHING: Try = { off: [], on: [], amounts: {} };
const trying = (t: Try) => t.off.length + t.on.length + Object.keys(t.amounts).length > 0;
const today = () => new Date().toISOString().slice(0, 10);

export function PersonalForecastPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<ForecastView>("90");
  const [openRow, setOpenRow] = useState("");
  const [attempt, setAttempt] = useState<Try>(NOTHING);
  const [whatIf, setWhatIf] = useState<ForecastWhatIf | null>(null);
  const [error, setError] = useState("");
  const forecast = useQuery<PersonalForecast>({
    queryKey: ["personal-forecast"],
    queryFn: () => api.get<PersonalForecast>("/api/personal/forecast") });
  const look = useMutation({
    mutationFn: (next: Try) => api.post<PersonalForecast>("/api/personal/forecast/what-if",
                                                          next),
    onSuccess: (now) => { setError(""); setWhatIf(now.what_if); },
    onError: (e: Error) => setError(e.message) });
  const tryIt = (next: Try) => {
    setAttempt(next);
    if (trying(next)) look.mutate(next); else setWhatIf(null);
  };
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete";
                                           path: string; body?: object }) => {
      const url = `/api/personal/forecast/${path}`;
      return method === "post" ? api.post<PersonalForecast>(url, body ?? {})
        : method === "patch" ? api.patch<PersonalForecast>(url, body)
          : api.del<PersonalForecast>(url);
    },
    onSuccess: (now) => {
      setError(""); qc.setQueryData(["personal-forecast"], now);
      qc.invalidateQueries({ queryKey: ["personal-sides"] });
      if (trying(attempt)) look.mutate(attempt);
    },
    onError: (e: Error) => setError(e.message) });
  const send: Send = (method, path, body) => act.mutate({ method, path, body });

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
  const name = (group: string) => data.lines.find((l) => l.group === group)?.label
    ?? data.planned.find((p) => p.id === group)?.description ?? "A line";
  const difference = whatIf ? whatIf.difference_at_low[view] : 0;

  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        How much your household is likely to have in its accounts, if pay comes as it has
        been coming and spending goes on as it has been going. Arithmetic on your own
        lines, not a prediction, and separate from your practice's forecast. Every line it
        is made of is below.
      </p>
      {error && <Banner kind="bad">{error}</Banner>}
      {data.note && <Banner kind="info">{data.note}</Banner>}
      {summary.first_below_zero && (
        <Banner kind="bad"><strong>Below zero.</strong> On these figures your accounts run
          out in the {months ? "month" : "week"} starting{" "}
          {longDate(summary.first_below_zero)}.</Banner>
      )}
      {!summary.first_below_zero && summary.first_below_floor && (
        <Banner kind="warn"><strong>Under your floor.</strong> Your accounts first fall
          below {dollars(data.floor_cents ?? 0)} in the {months ? "month" : "week"}{" "}
          starting {longDate(summary.first_below_floor)}.</Banner>
      )}

      <Card title="Personal: your household's cash">
        <dl className="row" aria-label="The personal forecast in three figures"
          style={{ margin: 0, alignItems: "flex-start" }}>
          <div>
            <dt className="small muted">In your accounts today</dt>
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
                onSet={(floor_cents) => send("post", "floor", { floor_cents })} />
            </dd>
          </div>
        </dl>
        <ul className="small muted" aria-label="Where today's figure comes from"
          style={{ margin: "var(--s3) 0 0", paddingLeft: "1.1rem" }}>
          {data.accounts.map((account) => (
            <li key={account.id}>{account.name}: {dollars(account.amount_cents)}
              {account.last_entry_on
                ? <>, lines through {longDate(account.last_entry_on)}</> : <>, no lines</>}
            </li>
          ))}
          <li>A card is not cash: what is charged on it leaves when the card is paid, so
            its payment is a line below and its charges are not.</li>
        </ul>
        {stale.length > 0 && (
          <Banner kind="warn">{stale.map((a) => a.name).join(" and ")}{" "}
            {stale.length === 1 ? "has" : "have"} no line in the last 14 days. Import its
            statement so the forecast starts from today, not from then.</Banner>
        )}
      </Card>

      {trying(attempt) && (
        <div role="status" aria-label="The what-if" className="banner info"
          style={{ display: "block" }}>
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
                  + "than it stands"}; at the end of {span},{" "}
              <strong>{dollars(whatIf.views[view].end_cents)}</strong>.
            </p>
          ) : <p className="small muted" style={{ margin: "var(--s1) 0 0" }}>
            Working it out…</p>}
          <button className="ghost small" style={{ marginTop: "var(--s2)" }}
            onClick={() => tryIt(NOTHING)}>Clear the what-if</button>
        </div>
      )}

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
          <table aria-label="The personal forecast as a table">
            <thead><tr><th>{months ? "Month" : "Week starting"}</th>
              <th className="money">At the start</th><th className="money">Money in</th>
              <th className="money">Money out</th><th className="money">At the end</th>
              {other && <th className="money">What if</th>}<th /></tr></thead>
            <tbody>
              {rows.map((row, index) => {
                const open = openRow === row.start;
                const mine = row.lines.map((id) => byId.get(id)!).filter(Boolean);
                const label = months ? row.label : longDate(row.start);
                return [
                  <tr key={row.start}>
                    <td>{label}</td>
                    <td className="money">{dollars(row.start_cents)}</td>
                    <td className="money">{row.in_cents ? dollars(row.in_cents)
                      : <span className="muted">—</span>}</td>
                    <td className="money">{row.out_cents ? dollars(row.out_cents)
                      : <span className="muted">—</span>}</td>
                    <td className="money"><strong>{dollars(row.end_cents)}</strong>
                      {row.below_zero ? <> <Pill kind="bad">below zero</Pill></>
                        : row.below_floor && <> <Pill kind="warn">under your floor</Pill></>}
                    </td>
                    {other && <td className="money">{dollars(other[index].end_cents)}</td>}
                    <td className="money">
                      {mine.length > 0 && (
                        <button className="ghost small" aria-expanded={open}
                          aria-label={`${open ? "Hide" : "Show"} the ${mine.length} line${
                            mine.length === 1 ? "" : "s"} of ${label}`}
                          onClick={() => setOpenRow(open ? "" : row.start)}>
                          {open ? "Hide" : `${mine.length} line${mine.length === 1 ? "" : "s"}`}
                        </button>
                      )}
                    </td>
                  </tr>,
                  ...(open ? mine.map((line) => (
                    <tr key={line.id} className="small">
                      <td style={{ paddingLeft: "var(--s5)" }}>{longDate(line.on_date)}</td>
                      <td colSpan={2}>{line.label}{" "}
                        <span className="muted">{KIND[line.kind].toLowerCase()}</span></td>
                      <td className="money">{line.direction === "out"
                        ? dollars(line.amount_cents) : ""}</td>
                      <td className="money">{line.direction === "in"
                        ? dollars(line.amount_cents) : ""}</td>
                      {other && <td />}<td />
                    </tr>
                  )) : []),
                ];
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Lines title="Known" lines={within.filter((l) => l.kind === "known")} attempt={attempt}
        onToggle={toggle} busy={busy} send={send} tryIt={tryIt}
        note="Pay from the practice at the cadence you have paid yourself, each debt's
              payment under your payoff plan, yearly bills your budget spreads, and
              estimated tax on its dates." />
      <Lines title="Regular" lines={within.filter((l) => l.kind === "regular")}
        attempt={attempt} onToggle={toggle} busy={busy} send={send} tryIt={tryIt} regular
        note={data.ready
          ? "Found in your complete months, by category and payee: monthly when seen in two "
            + "of the last three, as often a month as it has come. Moves between your own "
            + "accounts are neither in nor out."
          : data.note} />
      <PlannedCard planned={data.planned} goals={data.goals_not_drawn} attempt={attempt}
        busy={busy} tryIt={tryIt} send={send} />
      {data.adjustments.length > 0 && (
        <Card title={`What you changed (${data.adjustments.length})`}>
          <ul className="plain">
            {data.adjustments.map((adj) => (
              <li key={adj.id} className="row tight">
                <span><strong>{adj.label}</strong>: {adj.text}
                  {adj.source === "review" && <> <Pill>from a review</Pill></>}</span>
                <button className="ghost small" disabled={busy}
                  aria-label={`Undo: ${adj.label}`}
                  onClick={() => send("delete", `adjustments/${adj.id}`)}>Undo</button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <HowGood history={data.history}
        note="For each month: the forecast as it stood the first time it was worked out in
              that month, beside what happened in your accounts after it." />
      <AskClaude view={view} ready={data.ready} busy={busy} send={send} />
    </>
  );
}

// ---------------------------------------------------------- lines by kind

function Lines({ title, lines, note, attempt, busy, regular, onToggle, tryIt, send }: {
  title: string; lines: PersonalForecastLine[]; note: string; attempt: Try; busy: boolean;
  regular?: boolean; onToggle: (group: string) => void; tryIt: (next: Try) => void;
  send: Send;
}) {
  const groups = new Map<string, PersonalForecastLine[]>();
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
                const tried = attempt.off.includes(line.group);
                return (
                  <tr key={line.group} style={tried ? { opacity: 0.55 } : undefined}>
                    <td style={{ whiteSpace: "nowrap" }}>{longDate(line.on_date)}
                      {rows.length > 1 && <div className="small muted">
                        {rows.length} times shown</div>}</td>
                    <td><Link to={line.link}>{line.label}</Link>
                      {line.category && line.category !== line.label
                        && <div className="small muted">{line.category}</div>}
                      {line.cadence && <> <Pill>{line.cadence}</Pill></>}
                      {tried && <> <Pill kind="warn">tried without</Pill></>}</td>
                    <td className="small">{line.detail}
                      {line.adjusted && <div><strong>{line.adjusted}</strong></div>}</td>
                    <td className="money">{line.direction === "in"
                      ? dollars(line.amount_cents) : ""}</td>
                    <td className="money">{line.direction === "out"
                      ? dollars(line.amount_cents) : ""}</td>
                    <td className="money">
                      <LineActions line={line} tried={tried} busy={busy} regular={!!regular}
                        trial={attempt.amounts[line.group]} onToggle={() => onToggle(line.group)}
                        onAmount={(cents) => {
                          const amounts = { ...attempt.amounts };
                          if (cents === null) delete amounts[line.group];
                          else amounts[line.group] = cents;
                          tryIt({ ...attempt, amounts });
                        }} send={send} />
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

/** Try without it, try another amount; for a Regular line, also say it is
 *  not regular or set its amount from a date (kept, and undoable). */
function LineActions({ line, tried, trial, busy, regular, onToggle, onAmount, send }: {
  line: PersonalForecastLine; tried: boolean; trial?: number; busy: boolean; regular: boolean;
  onToggle: () => void; onAmount: (cents: number | null) => void; send: Send;
}) {
  const [mode, setMode] = useState<"" | "try" | "set">("");
  const [cents, setCents] = useState(trial ?? line.amount_cents);
  const [from, setFrom] = useState(today());
  if (mode) {
    return (
      <span className="row tight" style={{ justifyContent: "flex-end" }}>
        <PriceBox label={`${mode === "try" ? "Try" : "Set"} ${line.label} at`} cents={cents}
          onChange={setCents} />
        {mode === "set" && (
          <input type="date" aria-label={`${line.label}: from`} value={from}
            style={{ width: "auto" }} onChange={(e) => setFrom(e.target.value)} />
        )}
        <button className="small" disabled={busy || cents <= 0} onClick={() => {
          if (mode === "try") onAmount(cents);
          else send("post", "adjustments", { group: line.group, kind: "amount",
                                             amount_cents: cents, from_date: from });
          setMode("");
        }}>{mode === "try" ? "Try it" : "Save"}</button>
        <button className="ghost small" onClick={() => setMode("")}>Cancel</button>
      </span>
    );
  }
  return (
    <span className="row tight" style={{ justifyContent: "flex-end" }}>
      <button className="ghost small" aria-pressed={tried}
        aria-label={`${tried ? "Put back" : "Try without"} ${line.label}`}
        onClick={onToggle}>{tried ? "Put it back" : "Try without"}</button>
      {trial !== undefined ? (
        <button className="ghost small" onClick={() => onAmount(null)}
          aria-label={`Stop trying another amount for ${line.label}`}>
          Stop trying {dollars(trial)}</button>
      ) : (
        <button className="ghost small" aria-label={`Try another amount for ${line.label}`}
          onClick={() => { setCents(line.amount_cents); setMode("try"); }}>
          Try another amount</button>
      )}
      {regular && (
        <>
          <button className="ghost small" disabled={busy}
            aria-label={`Set another amount for ${line.label}`}
            onClick={() => { setCents(line.amount_cents); setMode("set"); }}>
            Change it</button>
          <button className="ghost small" disabled={busy}
            aria-label={`${line.label} is not regular`}
            onClick={() => send("post", "adjustments", { group: line.group,
                                                         kind: "not_regular" })}>
            Not regular</button>
        </>
      )}
    </span>
  );
}

// ------------------------------------------------------------- planned

const EVERY = { monthly: "every month", quarterly: "every three months",
                yearly: "every year" };

const plannedBody = (draft: Draft) => ({
  name: draft.description.trim(), direction: draft.direction,
  amount_cents: draft.amount_cents, on_date: draft.on_date, repeat: draft.repeat,
  is_what_if: draft.is_what_if });

function PlannedCard({ planned, goals, attempt, busy, tryIt, send }: {
  planned: PersonalPlanned[]; goals: PersonalForecast["goals_not_drawn"]; attempt: Try;
  busy: boolean; tryIt: (next: Try) => void; send: Send;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <Card title={`Planned (${planned.length})`}
      actions={!adding && <button className="small" onClick={() => setAdding(true)}>
        Add a planned line</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        What your history cannot show: a goal's target on its date, a trip, a bonus, a
        large purchase. A what-if is drawn beside the forecast only while you try it.
      </p>
      {adding && (
        <PlannedForm label="The new planned line" start={{}} busy={busy} save="Add it"
          until={false} placeholder="A trip, a bonus, a new roof"
          onCancel={() => setAdding(false)}
          onSave={(draft) => { send("post", "planned", plannedBody(draft));
                               setAdding(false); }} />
      )}
      {planned.length > 0 && (
        <table aria-label="Planned lines">
          <tbody>
            {planned.map((row) => {
              const tried = attempt.on.includes(row.id);
              return (
                <tr key={row.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{longDate(row.next_on ?? row.on_date)}
                    {row.repeat && <div className="small muted">{EVERY[row.repeat]}</div>}</td>
                  <td>{row.description}
                    {row.goal && <> <Pill>a goal</Pill></>}
                    {row.state === "what_if" && <> <Pill>what-if</Pill></>}
                    {row.state === "lapsed" && <> <Pill kind="warn">did not happen?</Pill></>}
                    {tried && <> <Pill kind="warn">being tried</Pill></>}</td>
                  <td className="money">{row.direction === "in" ? "in " : "out "}
                    {dollars(row.amount_cents)}</td>
                  <td className="money">
                    {row.state === "what_if" && (
                      <>
                        <button className="ghost small" aria-pressed={tried}
                          aria-label={`${tried ? "Stop trying" : "Try"} ${row.description}`}
                          onClick={() => tryIt({ ...attempt, on: tried
                            ? attempt.on.filter((id) => id !== row.id)
                            : [...attempt.on, row.id] })}>
                          {tried ? "Stop trying" : "Try it"}</button>{" "}
                        <button className="ghost small" disabled={busy}
                          aria-label={`Plan ${row.description}`}
                          onClick={() => send("patch", `planned/${row.id}`,
                                              { is_what_if: false })}>
                          Save as planned</button>{" "}
                      </>
                    )}
                    {row.goal ? (
                      <Link className="small" to="/finance/personal/goals">Change the goal</Link>
                    ) : (
                      <button className="ghost small" disabled={busy}
                        aria-label={`Remove ${row.description}`}
                        onClick={() => send("delete", `planned/${row.id}`)}>Remove</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {goals.length > 0 && (
        <p className="small muted">
          {goals.map((g) => g.name).join(" and ")}{" "}
          {goals.length === 1 ? "has" : "have"} no date: saved for, never spent on a day,
          so not a line here. What you set aside stays in{" "}
          {goals[0].account ?? "your accounts"}, which the forecast counts.
        </p>
      )}
    </Card>
  );
}

// ------------------------------------------------------ the Claude buttons

const price = (usd: string | undefined) => `about $${Number(usd ?? 0).toFixed(2)}`;

function AskClaude({ view, ready, busy, send }: {
  view: ForecastView; ready: boolean; busy: boolean; send: Send;
}) {
  const qc = useQueryClient();
  const status = useQuery<ForecastAiStatus>({
    queryKey: ["personal-forecast-ai"],
    queryFn: () => api.get<ForecastAiStatus>("/api/personal/forecast/ask") });
  const [answer, setAnswer] = useState<ExplainAnswer | null>(null);
  const [review, setReview] = useState<PersonalReview | null>(null);
  const [error, setError] = useState("");
  const spent = () => qc.invalidateQueries({ queryKey: ["personal-forecast-ai"] });
  const explain = useMutation({
    mutationFn: () => api.post<ExplainAnswer>("/api/personal/forecast/ask/explain", {
      view: view === "months" ? "180" : view }),
    onSuccess: (data) => { setAnswer(data); setError(""); spent(); },
    onError: (e: Error) => { setError(e.message); spent(); } });
  const ask = useMutation({
    mutationFn: () => api.post<PersonalReview>("/api/personal/forecast/ask/review", {}),
    onSuccess: (data) => { setReview(data); setError(""); spent(); },
    onError: (e: Error) => { setError(e.message); spent(); } });
  const s = status.data;
  const waiting = explain.isPending || ask.isPending;
  return (
    <Card title="Ask Claude">
      <p className="small muted" style={{ marginTop: 0 }}>
        The numbers are arithmetic on your lines; Claude never supplies one. What is sent
        is amounts, dates and category names: never a merchant's name, an account's name
        or number, a retirement balance, or your name. Nothing is sent until you press,
        and nothing it says enters the forecast unless you confirm it.
      </p>
      {error && <Banner kind="bad">{error}</Banner>}
      {s?.refused ? <p className="small muted">{s.refused}</p> : (
        <div className="row tight">
          <AiGate>
            <button className="small" disabled={waiting || !s}
              onClick={() => explain.mutate()}>
              {explain.isPending ? "Asking Claude…"
                : `Explain this forecast (${price(s?.estimate_usd)})`}</button>
            <button className="small" disabled={waiting || !s || !ready}
              onClick={() => ask.mutate()}>
              {ask.isPending ? "Asking Claude…"
                : `Review with Claude (${price(s?.review_estimate_usd)})`}</button>
          </AiGate>
          {s && <span className="small muted">{s.used_today} of {s.cap} used today.</span>}
        </div>
      )}
      {!ready && !s?.refused && <p className="small muted">A review reads your complete
        months, so it needs two of them.</p>}
      {answer && (
        <div className="banner info" role="note" aria-label="Explanation"
          style={{ marginTop: "var(--s3)", display: "block" }}>
          <p className="small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{answer.text}</p>
          <p className="tiny muted" style={{ margin: "var(--s2) 0 0" }}>
            This cost ${Number(answer.cost_usd).toFixed(4)}. {answer.used_today} of{" "}
            {answer.cap} used today. {answer.disclaimer}</p>
        </div>
      )}
      {review && <Review review={review} busy={busy} send={send}
        onClose={() => setReview(null)} />}
    </Card>
  );
}

const seen = (item: PersonalReviewItem) => item.months.map(
  (m) => `${m.month} ${dollars(m.amount_cents)}`).join(", ");

function Review({ review, busy, send, onClose }: {
  review: PersonalReview; busy: boolean; send: Send; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [done, setDone] = useState<Record<string, string>>({});
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState("");
  const answered = (key: string, text: string) => setDone((now) => ({ ...now, [key]: text }));
  // Stop 4 (decision 25): an envelope or the set-aside, changed through the
  // ordinary routes with the app's amount, which the owner can edit first.
  const change = useMutation({
    mutationFn: ({ url, method, body }: { key: string; text: string; url: string;
                                           method: "post" | "patch"; body: object }) =>
      method === "post" ? api.post(url, body) : api.patch(url, body),
    onSuccess: (_data, { key, text }) => {
      setFailed(""); answered(key, text);
      for (const k of ["personal-budget", "personal-taxes", "personal-pay-yourself"]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    },
    onError: (e: Error) => setFailed(e.message) });
  const envelopes = review.envelopes ?? [];
  const goals = review.goals ?? [];
  const aside = review.set_aside ?? [];
  const nothing = review.one_offs.length + review.missed.length + envelopes.length
    + goals.length + aside.length + review.questions.length === 0;
  return (
    <section aria-label="The review" className="panel" style={{ marginTop: "var(--s3)" }}>
      <p className="small" style={{ marginTop: 0 }}>
        <strong>Claude's review.</strong> Answer what you want to; each answer is yours and
        is sent when you press its button. Closing this changes nothing.{" "}
        <span className="muted">This cost ${Number(review.cost_usd).toFixed(4)}.{" "}
          {review.used_today} of {review.cap} used today.</span>
      </p>
      {nothing && <p className="small">It found nothing to question.</p>}
      {review.one_offs.length > 0 && <h4>Regular lines that look like one-offs</h4>}
      {review.one_offs.map((item) => (
        <div key={item.group} role="group" aria-label={`Review of ${item.label}`}
          style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>{item.label}</strong>
            <span className="muted"> · {item.category}</span>: {item.why}{" "}
            <span className="muted">In your lines: {seen(item)}.</span></p>
          {done[item.group] ? <p className="small muted">{done[item.group]}</p> : (
            <div className="row tight">
              <button className="small" disabled={busy}
                onClick={() => { send("post", "adjustments", { group: item.group,
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
        <div key={item.group} role="group" aria-label={`Review of ${item.label}`}
          style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>{item.label}</strong>
            <span className="muted"> · {item.category}</span>: {item.why}{" "}
            <span className="muted">In your lines: {seen(item)}.</span></p>
          {done[item.group] ? <p className="small muted">{done[item.group]}</p> : (
            <>
              <PlannedForm label={`Adding ${item.label}`} busy={busy} save="Add it"
                until={false}
                start={{ description: item.label, direction: item.direction,
                         amount_cents: item.last_amount_cents, repeat: item.cadence ?? "",
                         on_date: item.next_on ?? today() }}
                onSave={(draft) => { send("post", "planned", plannedBody(draft));
                                     answered(item.group, "Added as a planned line."); }} />
              <button className="ghost small"
                onClick={() => answered(item.group, "Not added.")}>No</button>
            </>
          )}
        </div>
      ))}
      {failed && <Banner kind="bad">{failed}</Banner>}
      {envelopes.length > 0 && <h4>Envelopes that look out of line</h4>}
      {envelopes.map((item) => {
        const key = `e:${item.id}`;
        const text = amounts[key] ?? (item.proposed_cents / 100).toFixed(0);
        const cents = toCents(text);
        return (
          <div key={key} role="group" aria-label={`Review of ${item.name}`}
            style={{ marginBottom: "var(--s3)" }}>
            <p className="small" style={{ margin: 0 }}><strong>{item.name}</strong>: {item.why}{" "}
              <span className="muted">Planned {dollars(item.planned_cents)} a month; spent{" "}
                {item.months.map((m) => `${m.month} ${dollars(m.amount_cents)}`).join(", ")}.
              </span></p>
            {done[key] ? <p className="small muted">{done[key]}</p> : (
              <div className="row tight">
                <input aria-label={`New amount for ${item.name}`} value={text}
                  style={{ width: "6rem" }}
                  onChange={(e) => setAmounts({ ...amounts, [key]: e.target.value })} />
                <button className="small" disabled={busy || change.isPending || cents === null}
                  onClick={() => change.mutate({
                    key, text: `${item.name} is ${dollars(cents!)} a month now.`,
                    url: `/api/personal/envelopes/${item.id}`, method: "patch",
                    body: { planned_cents: cents } })}>Set it a month</button>
                <button className="ghost small"
                  onClick={() => answered(key, "Left as it is.")}>Leave it</button>
              </div>
            )}
          </div>
        );
      })}
      {goals.length > 0 && <h4>Goals</h4>}
      {goals.map((item) => (
        <div key={item.id} role="group" aria-label={`Review of ${item.name}`}
          style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>{item.name}</strong>: {item.why}{" "}
            <span className="muted">{dollars(item.progress_cents)} of{" "}
              {dollars(item.target_cents)}, {dollars(item.monthly_cents)} a month
              {item.target_on ? `, by ${longDate(item.target_on)}` : ""}.</span>{" "}
            <Link to="/finance/personal/goals">Change it under Goals</Link></p>
        </div>
      ))}
      {aside.map((item) => {
        const key = "s:set_aside";
        return (
          <div key={key} role="group" aria-label="Review of the tax set-aside"
            style={{ marginBottom: "var(--s3)" }}>
            <h4>The tax set-aside</h4>
            <p className="small" style={{ margin: 0 }}>{item.why}{" "}
              <span className="muted">Now {item.percent_now ?? "no"}% of each draw; the
                estimate suggests {item.suggested_percent}%. An estimate: confirm with your
                CPA.</span></p>
            {done[key] ? <p className="small muted">{done[key]}</p> : (
              <div className="row tight">
                <button className="small" disabled={busy || change.isPending}
                  onClick={() => change.mutate({
                    key, text: `The set-aside is ${item.suggested_percent}% of each draw now.`,
                    url: "/api/personal/taxes/set-aside", method: "post",
                    body: { year: item.year, percent_per_draw: String(item.suggested_percent) } })}>
                  Use {item.suggested_percent}%</button>
                <button className="ghost small"
                  onClick={() => answered(key, "Left as it is.")}>Leave it</button>
              </div>
            )}
          </div>
        );
      })}
      {review.questions.length > 0 && <h4>What your history cannot show</h4>}
      {review.questions.map((item, index) => {
        const key = `q${index}`;
        return (
          <div key={key} role="group" aria-label={`Question ${index + 1}`}
            style={{ marginBottom: "var(--s3)" }}>
            <p className="small" style={{ margin: 0 }}>{item.question}</p>
            {done[key] ? <p className="small muted">{done[key]}</p> : (
              <>
                <PlannedForm label={`Answer ${index + 1}`} busy={busy} until={false}
                  save="Add it to the forecast" start={{}}
                  placeholder="A trip, a bonus, a new roof"
                  onSave={(draft) => { send("post", "planned", plannedBody(draft));
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
