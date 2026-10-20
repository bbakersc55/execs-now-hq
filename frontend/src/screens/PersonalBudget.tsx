import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { AiGate } from "../components/DemoVisitor";
import { Modal } from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  Budget, BudgetMonth, BudgetQuestion, CashFlow, Envelope, PersonalAccount, PersonalGoal, api,
} from "../lib/api";
import { dollars, longDate, toCents } from "../lib/money";
import { NetWorthCard, SidesCard } from "./PersonalWorth";
import { PayYourselfCard } from "./PersonalTaxes";

/**
 * The budget that builds itself (P6 M4 stop 2, decisions 9–14): the
 * personal Overview, the app's own questions, goals, the Cash flow table and
 * "Explain this budget". Every number is the server's arithmetic on the
 * owner's own lines; Claude explains only when asked, and is priced first.
 */

/** Whole dollars when there are no cents: "$820", "$1,380", "$12.50". */
function money(cents: number) {
  const text = dollars(cents);
  return text.endsWith(".00") ? text.slice(0, -3) : text;
}

function useBudget() {
  return useQuery<Budget>({ queryKey: ["personal-budget"],
                            queryFn: () => api.get<Budget>("/api/personal/budget") });
}

function useRefreshBudget() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["personal-budget", "personal-questions", "personal-goals"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

// ---------------------------------------------------------------- Overview

export function PersonalOverview() {
  const budget = useBudget();
  const refresh = useRefreshBudget();
  const [asking, setAsking] = useState(false);
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const accept = useMutation({
    mutationFn: () => api.post<{ envelopes: number; questions_waiting: number }>(
      "/api/personal/budget/accept"),
    onSuccess: (r) => {
      setSaid({ kind: "ok", text: `${r.envelopes} envelopes, from your history.` });
      refresh();
      if (r.questions_waiting) setAsking(true);
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }),
  });
  const data = budget.data;
  if (budget.isError) return <Banner kind="bad">{(budget.error as Error).message}</Banner>;
  if (!data) return <p>Loading…</p>;
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      {!data.has_budget ? (
        <Proposal data={data} onUse={() => accept.mutate()} busy={accept.isPending} />
      ) : (
        <>
          {data.questions_waiting > 0 && (
            <Banner kind="info">
              <span>{data.questions_waiting === 1 ? "One question" :
                `${data.questions_waiting} questions`} about your budget, one screen each,
                any of them skippable.{" "}
                <button className="link" onClick={() => setAsking(true)}>Answer them</button>
              </span>
            </Banner>
          )}
          <Unassigned month={data.month!} goals={data.goals} debts={data.debts}
            onSaid={setSaid} />
          <Envelopes month={data.month!} onSaid={setSaid} />
          <Income month={data.month!} />
          <GoalsSummary goals={data.goals} />
          {/* Stop 4: decision 20, the loop between the two sides. */}
          <PayYourselfCard />
          {/* Stop 3: both sides' cash in 90 days, and net worth. */}
          <SidesCard />
          <NetWorthCard />
          {data.coming_up.length > 0 && (
            <Card title="Coming up">
              <ul className="plain">
                {data.coming_up.map((p) => (
                  <li key={p.id}>{longDate(p.on_date)}: {p.name},{" "}
                    {p.direction === "in" ? "in " : ""}{money(p.amount_cents)}
                    {p.goal && <span className="muted small"> (a goal)</span>}</li>
                ))}
              </ul>
            </Card>
          )}
          <ExplainBudget />
        </>
      )}
      <CashFlowTable flow={data.cash_flow} />
      {data.has_budget && (
        <p className="small">
          <button className="link" onClick={() => api.post("/api/personal/questions")
            .then(() => setAsking(true))}>
            Something coming that your history doesn't show?</button>
        </p>
      )}
      {asking && <BudgetQuestions onClose={() => { setAsking(false); refresh(); }} />}
    </>
  );
}

function Proposal({ data, onUse, busy }: { data: Budget; onUse: () => void; busy: boolean }) {
  const p = data.proposal!;
  if (!p.ready) {
    return (
      <Card title="Personal: your budget">
        <Empty>Your budget is proposed from your history once your lines cover{" "}
          {p.least_months} months. They cover {p.months.length} so far: import your
          accounts' statements under Import.</Empty>
      </Card>
    );
  }
  const labels = p.months.map((m) => new Date(`${m}T12:00:00`).toLocaleDateString(
    undefined, { month: "short" }));
  return (
    <Card title="Personal: your budget, from your history">
      <p className="small muted" style={{ marginTop: 0 }}>
        Each amount is the middle of your last {p.months.length} months in that category, to
        the nearest $10. Nothing is set until you use it, and you can change any of it
        after.</p>
      <table className="data" aria-label="Proposed budget">
        <thead><tr><th>Category</th>{labels.map((l, i) => <th key={i} className="num">{l}</th>)}
          <th className="num">Proposed</th></tr></thead>
        <tbody>
          {p.envelopes.map((row) => (
            <tr key={row.category.id}>
              <td>{row.category.name}{row.kind === "income" && <Pill>Income</Pill>}</td>
              {row.amounts.map((a, i) => <td key={i} className="num muted">{money(a)}</td>)}
              <td className="num"><strong>{money(row.proposed_cents)}</strong>
                <div className="tiny muted">From your history</div></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="primary" disabled={busy} onClick={onUse}>
        {busy ? "Setting it up…" : "Use this budget"}</button>
    </Card>
  );
}

function Unassigned({ month, goals, debts, onSaid }: {
  month: BudgetMonth; goals: PersonalGoal[]; debts: number;
  onSaid: (s: { kind: string; text: string }) => void;
}) {
  const refresh = useRefreshBudget();
  const qc = useQueryClient();
  const left = month.unassigned_cents;
  const [goal, setGoal] = useState("");
  const [amount, setAmount] = useState("");
  // Stop 3: a debt is a place for it too, as the payoff plan's extra.
  const assign = useMutation({
    mutationFn: (cents: number | null) => api.post("/api/personal/budget/assign",
      goal === "debts" ? { debts: true, amount_cents: cents } : { goal, amount_cents: cents }),
    onSuccess: () => {
      setAmount("");
      onSaid({ kind: "ok", text: goal === "debts" ? "Put toward your debts: the payoff "
        + "plan's extra went up by it." : "Put toward the goal." });
      refresh();
      qc.invalidateQueries({ queryKey: ["personal-debts"] });
    },
    onError: (e: Error) => onSaid({ kind: "bad", text: e.message }),
  });
  return (
    <Card title={`Personal: ${month.month_label}`}>
      <div className="row" style={{ gap: "var(--s5)", flexWrap: "wrap" }}>
        <Figure label="Income planned" cents={month.income_planned_cents}
          note={`${money(month.income_received_cents)} in so far`} />
        <Figure label="Envelopes" cents={month.planned_cents}
          note={`${money(month.spent_cents)} spent so far`} />
        <Figure label="Unassigned" cents={left} bad={left < 0} />
      </div>
      {left > 0 && (
        <div style={{ marginTop: "var(--s3)" }}>
          <p className="small" style={{ margin: "0 0 var(--s2)" }}>
            {money(left)} of this month's income has no job yet. Where does the rest go?</p>
          {goals.length === 0 && debts === 0 ? (
            <p className="small muted">Add a goal under Goals, or a debt under Debts, and it
              can go there.</p>
          ) : (
            <div className="row tight">
              <select aria-label="Put it toward" value={goal} style={{ width: "auto" }}
                onChange={(e) => setGoal(e.target.value)}>
                <option value="">A goal or your debts…</option>
                {goals.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                {debts > 0 && <option value="debts">Your debts (the payoff plan's extra)
                  </option>}
              </select>
              <input aria-label="How much a month" placeholder={plainDollars(left)}
                value={amount} style={{ width: "7rem" }}
                onChange={(e) => setAmount(e.target.value)} />
              <button disabled={!goal || toCents(amount || plainDollars(left)) === null
                || assign.isPending}
                onClick={() => assign.mutate(toCents(amount || plainDollars(left)))}>
                Put it there</button>
            </div>
          )}
        </div>
      )}
      {left < 0 && (
        <p className="small" role="alert" style={{ color: "var(--bad)", marginBottom: 0 }}>
          Your envelopes plan {money(-left)} more than your income. Over the income:{" "}
          {month.over_income.map((r) => `${r.name} (${money(r.planned_cents)})`).join(", ")}.
        </p>
      )}
    </Card>
  );
}

function plainDollars(cents: number) {
  return (cents / 100).toFixed(cents % 100 ? 2 : 0);
}

function Figure({ label, cents, note, bad }: {
  label: string; cents: number; note?: string; bad?: boolean;
}) {
  return (
    <div>
      <div className="tiny muted">{label}</div>
      <div style={{ fontSize: "var(--t-20)", fontWeight: 600,
                    color: bad ? "var(--bad)" : undefined }}>{money(cents)}</div>
      {note && <div className="tiny muted">{note}</div>}
    </div>
  );
}

function Envelopes({ month, onSaid }: {
  month: BudgetMonth; onSaid: (s: { kind: string; text: string }) => void;
}) {
  const refresh = useRefreshBudget();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [from, setFrom] = useState<Record<string, string>>({});
  const fail = (e: Error) => onSaid({ kind: "bad", text: e.message });
  const change = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api.patch(`/api/personal/envelopes/${id}`, body),
    onSuccess: () => { setEditing(null); refresh(); }, onError: fail,
  });
  const cover = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api.post(`/api/personal/envelopes/${id}/cover`, { month: month.month, ...body }),
    onSuccess: () => refresh(), onError: fail,
  });
  const spare = month.envelopes.filter((e) => e.left_cents > 0);
  return (
    <Card title="Envelopes">
      <p className="small muted" style={{ marginTop: 0 }}>
        Everyday envelopes start fresh each month; saving-up ones (goals, yearly bills,
        taxes) keep what is left. Each has the switch.</p>
      <table className="data envelopes" aria-label="Envelopes">
        <thead><tr><th>Envelope</th><th className="num">Planned</th><th className="num">Spent</th>
          <th className="num">Left</th><th>Keeps what is left</th></tr></thead>
        <tbody>
          {month.envelopes.map((e) => (
            <EnvelopeRow key={e.id} e={e} editing={editing === e.id} value={value}
              onEdit={() => { setEditing(e.id); setValue(plainDollars(e.planned_cents)); }}
              onValue={setValue}
              onSave={() => change.mutate({ id: e.id, body: { planned_cents: toCents(value) } })}
              onRolls={(rolls) => change.mutate({ id: e.id, body: { rolls } })}>
              {e.over && !e.stood && (
                <div className="row tight" role="group" aria-label={`${e.name} is over`}>
                  <span className="small" style={{ color: "var(--bad)" }}>
                    {money(-e.left_cents)} over. Take it from</span>
                  <select aria-label={`Take ${e.name}'s overspend from`}
                    value={from[e.id] ?? ""} style={{ width: "auto" }}
                    onChange={(ev) => setFrom({ ...from, [e.id]: ev.target.value })}>
                    <option value="">another envelope…</option>
                    {spare.filter((s) => s.id !== e.id).map((s) => (
                      <option key={s.id} value={s.id}>{s.name} ({money(s.left_cents)} left)
                      </option>))}
                  </select>
                  <button className="small" disabled={!from[e.id] || cover.isPending}
                    onClick={() => cover.mutate({ id: e.id,
                      body: { from_envelope: from[e.id],
                              amount_cents: Math.min(-e.left_cents,
                                spare.find((s) => s.id === from[e.id])?.left_cents ?? 0) } })}>
                    Move it</button>
                  <button className="small ghost" disabled={cover.isPending}
                    onClick={() => cover.mutate({ id: e.id, body: { stand: true } })}>
                    Let it stand</button>
                </div>
              )}
            </EnvelopeRow>
          ))}
        </tbody>
      </table>
      {month.unbudgeted.length > 0 && (
        <p className="small muted">Spent this month with no envelope:{" "}
          {month.unbudgeted.map((u) => `${u.name} ${money(u.spent_cents)}`).join(", ")}.</p>
      )}
    </Card>
  );
}

function EnvelopeRow({ e, editing, value, onEdit, onValue, onSave, onRolls, children }: {
  e: Envelope; editing: boolean; value: string; onEdit: () => void;
  onValue: (v: string) => void; onSave: () => void; onRolls: (r: boolean) => void;
  children?: React.ReactNode;
}) {
  const extra = e.carried_cents + e.moved_in_cents - e.moved_out_cents;
  return (
    <>
      <tr className={e.over ? "over" : ""} aria-label={e.name}>
        <td>
          <strong>{e.name}</strong>
          <div className="tiny muted">{e.yearly_cents
            ? `A yearly bill of ${money(e.yearly_cents)}, spread`
            : e.goal ? "For a goal"
              : e.source === "tax" ? <>Set aside for tax: Left is what is set aside so
                far (<Link to="/finance/personal/taxes">Taxes</Link>). An estimate.</>
                : e.source_label}</div>
        </td>
        <td className="num">
          {editing ? (
            <span className="row tight" style={{ justifyContent: "flex-end" }}>
              <input aria-label={`Planned for ${e.name}`} value={value} style={{ width: "6rem" }}
                onChange={(ev) => onValue(ev.target.value)} />
              <button className="small primary" disabled={toCents(value) === null}
                onClick={onSave}>Save</button>
            </span>
          ) : e.goal ? money(e.planned_cents) : (
            <button className="link" aria-label={`Change ${e.name}'s amount`} onClick={onEdit}>
              {money(e.planned_cents)}</button>
          )}
          {extra !== 0 && <div className="tiny muted">{extra > 0 ? "+" : ""}{money(extra)}{" "}
            {e.carried_cents ? "kept from last month" : "moved"}</div>}
        </td>
        <td className="num">{money(e.spent_cents)}</td>
        <td className="num" style={{ color: e.over ? "var(--bad)" : undefined,
                                     fontWeight: e.over ? 600 : undefined }}>
          {money(e.left_cents)}</td>
        <td>
          <input type="checkbox" checked={e.rolls} style={{ width: "auto" }}
            aria-label={`${e.name} keeps what is left`}
            onChange={(ev) => onRolls(ev.target.checked)} />
        </td>
      </tr>
      {children && <tr className="over-ask"><td colSpan={5}>{children}</td></tr>}
    </>
  );
}

function Income({ month }: { month: BudgetMonth }) {
  if (month.income.length === 0) return null;
  return (
    <Card title="Income">
      <table className="data" aria-label="Income">
        <thead><tr><th>From</th><th className="num">Planned</th><th className="num">In so far</th>
        </tr></thead>
        <tbody>{month.income.map((e) => (
          <tr key={e.id}><td>{e.name}</td><td className="num">{money(e.planned_cents)}</td>
            <td className="num">{money(e.spent_cents)}</td></tr>))}</tbody>
      </table>
    </Card>
  );
}

function GoalsSummary({ goals }: { goals: PersonalGoal[] }) {
  if (goals.length === 0) return null;
  return (
    <Card title="Goals">
      <div className="card-grid">
        {goals.map((g) => <GoalCard key={g.id} g={g} />)}
      </div>
    </Card>
  );
}

function GoalCard({ g, onOpen }: { g: PersonalGoal; onOpen?: () => void }) {
  return (
    <article className="card" aria-label={`Goal: ${g.name}`}>
      <div className="spread"><strong>{g.name}</strong>
        <span className="small muted">{g.target_on ? `by ${longDate(g.target_on)}` : "no date"}
        </span></div>
      <div className="meter" role="progressbar" aria-label={`${g.name}: ${g.percent}%`}
        aria-valuenow={g.percent} aria-valuemin={0} aria-valuemax={100}
        style={{ margin: "var(--s2) 0", maxWidth: "none" }}>
        <span style={{ width: `${g.percent}%` }} /></div>
      <div className="small">{money(g.progress_cents)} of {money(g.target_cents)}
        <span className="muted"> · {money(g.monthly_cents)} a month</span></div>
      {onOpen && <button className="link small" onClick={onOpen}>Open</button>}
    </article>
  );
}

// ------------------------------------------------------------- questions

/** Decision 13: one screen each, any of them skippable. */
export function BudgetQuestions({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const waiting = useQuery<BudgetQuestion[]>({
    queryKey: ["personal-questions"],
    queryFn: () => api.get<BudgetQuestion[]>("/api/personal/questions") });
  const [said, setSaid] = useState("");
  const [problem, setProblem] = useState("");
  const [answered, setAnswered] = useState(0);
  const send = useMutation({
    mutationFn: ({ q, body }: { q: BudgetQuestion; body: object }) =>
      api.post<{ said: string; waiting: BudgetQuestion[] }>(
        `/api/personal/questions/${q.id}`, body),
    onSuccess: (r) => {
      setSaid(r.said); setProblem(""); setAnswered(answered + 1);
      qc.setQueryData(["personal-questions"], r.waiting);
    },
    onError: (e: Error) => setProblem(e.message),
  });
  const list = waiting.data ?? [];
  const q = list[0];
  const total = answered + list.length;
  return (
    <Modal title="About your budget" label="Questions about your budget" onClose={onClose}>
      {said && <Banner kind="ok">{said}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {!waiting.data ? <p>Loading…</p> : !q ? (
        <>
          <p>That's all of them. Your budget has what you said.</p>
          <button className="primary" onClick={onClose}>Done</button>
        </>
      ) : (
        <div key={q.id}>
          <p className="tiny muted" style={{ marginTop: 0 }}>
            {answered + 1} of {total}</p>
          <h4 style={{ marginTop: 0 }}>{q.text}</h4>
          <QuestionAnswer q={q} busy={send.isPending}
            onAnswer={(body) => send.mutate({ q, body })} />
          <p style={{ marginBottom: 0 }}>
            <button className="link small" disabled={send.isPending}
              onClick={() => send.mutate({ q, body: { skip: true } })}>Skip this one</button>
          </p>
        </div>
      )}
    </Modal>
  );
}

function QuestionAnswer({ q, busy, onAnswer }: {
  q: BudgetQuestion; busy: boolean; onAnswer: (body: object) => void;
}) {
  const [amount, setAmount] = useState("");
  const [what, setWhat] = useState<"goal" | "planned" | "">("");
  const [name, setName] = useState("");
  const [on, setOn] = useState("");
  const cents = toCents(amount);
  const detail = q.detail;
  if (q.kind === "keep") {
    const keep = detail.proposed_cents ?? 0;
    return (
      <div className="row tight" style={{ flexWrap: "wrap" }}>
        <button className="primary" disabled={busy}
          onClick={() => onAnswer({ keep: true })}>Keep {money(keep)}</button>
        <span className="small muted">or set a target</span>
        <input aria-label="Target a month" value={amount} style={{ width: "7rem" }}
          placeholder={detail.suggested_cents ? plainDollars(detail.suggested_cents) : ""}
          onChange={(e) => setAmount(e.target.value)} />
        <button disabled={busy || cents === null}
          onClick={() => onAnswer({ amount_cents: cents })}>Set it</button>
      </div>
    );
  }
  if (q.kind === "normal") {
    return (
      <div className="row tight" style={{ flexWrap: "wrap" }}>
        {(detail.choices ?? []).map((c) => (
          <button key={c} className="primary" disabled={busy}
            onClick={() => onAnswer({ amount_cents: c })}>{money(c)} is normal</button>
        ))}
        <span className="small muted">or</span>
        <input aria-label="Another amount a month" value={amount} style={{ width: "7rem" }}
          onChange={(e) => setAmount(e.target.value)} />
        <button disabled={busy || cents === null}
          onClick={() => onAnswer({ amount_cents: cents })}>Use that</button>
      </div>
    );
  }
  if (q.kind === "yearly") {
    return (
      <>
        <p className="small muted">Spread, it is {money(detail.monthly_cents ?? 0)} a month in
          an envelope that keeps what is left, so the money is there when the bill comes.</p>
        <div className="row tight">
          <button className="primary" disabled={busy}
            onClick={() => onAnswer({ spread: true })}>Spread it monthly</button>
          <button disabled={busy} onClick={() => onAnswer({ spread: false })}>
            It isn't yearly</button>
        </div>
      </>
    );
  }
  return (
    <>
      <div className="row tight" role="group" aria-label="Which is it">
        <button className={what === "goal" ? "primary" : ""} onClick={() => setWhat("goal")}>
          Something to save for</button>
        <button className={what === "planned" ? "primary" : ""}
          onClick={() => setWhat("planned")}>A cost on a date</button>
        <button disabled={busy} onClick={() => onAnswer({ skip: true })}>Nothing</button>
      </div>
      {what && (
        <div className="row" style={{ flexWrap: "wrap", gap: "var(--s3)",
                                      marginTop: "var(--s3)" }}>
          <Field label="What"><input aria-label="What is coming" value={name}
            placeholder={what === "goal" ? "A vacation" : "New tires"}
            onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="How much"><input aria-label="How much" value={amount}
            style={{ width: "7rem" }} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Field label={what === "goal" ? "By (optional)" : "When"}>
            <input aria-label="When" type="date" value={on}
              onChange={(e) => setOn(e.target.value)} /></Field>
          <button className="primary" style={{ alignSelf: "flex-end" }}
            disabled={busy || !name.trim() || cents === null || (what === "planned" && !on)}
            onClick={() => onAnswer({ what, name, amount_cents: cents, on_date: on || null })}>
            Add it</button>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ goals

const NEW_GOAL = { name: "", target: "", target_on: "", saved: "", account: "",
                   months: "", monthly: "", emergency: false };

export function PersonalGoals() {
  const budget = useBudget();
  const refresh = useRefreshBudget();
  const accounts = useQuery<PersonalAccount[]>({
    queryKey: ["personal-accounts"],
    queryFn: () => api.get<PersonalAccount[]>("/api/personal/accounts") });
  const [form, setForm] = useState(NEW_GOAL);
  const [open, setOpen] = useState<string | null>(null);
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const body = (f: typeof NEW_GOAL) => ({
    name: f.name, target_on: f.target_on || null, saved_cents: toCents(f.saved || "0"),
    account: f.account || null,
    ...(f.emergency ? { months_of_envelopes: Number(f.months) || null }
      : { target_cents: toCents(f.target) }),
    monthly_cents: !f.target_on && f.monthly ? toCents(f.monthly) : null });
  const add = useMutation({
    mutationFn: () => api.post<PersonalGoal>("/api/personal/goals", body(form)),
    onSuccess: (g) => { setForm(NEW_GOAL); setSaid({ kind: "ok", text:
      `${g.name}: ${money(g.monthly_cents)} a month, in an envelope that keeps what is left.` });
      refresh(); },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }),
  });
  const goals = budget.data?.goals ?? [];
  const own = (accounts.data ?? []).filter((a) => a.side === "personal" && !a.closed);
  const set = (patch: Partial<typeof NEW_GOAL>) => setForm({ ...form, ...patch });
  const chosen = goals.find((g) => g.id === open);
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <Card title="Personal: goals">
        <p className="small muted" style={{ marginTop: 0 }}>A goal works out what to set aside
          each month and keeps it in an envelope that keeps what is left. With a date, its
          target is on your plans for that day.</p>
        {goals.length === 0 ? <Empty>No goals yet.</Empty> : (
          <div className="card-grid">
            {goals.map((g) => <GoalCard key={g.id} g={g} onOpen={() => setOpen(g.id)} />)}
          </div>
        )}
      </Card>
      {chosen && <GoalDetail g={chosen} accounts={own} onClose={() => setOpen(null)}
        onSaid={(s) => { setSaid(s); refresh(); }} />}
      <Card title="Add a goal">
        <label className="check small">
          <input type="checkbox" checked={form.emergency} style={{ width: "auto" }}
            onChange={(e) => set({ emergency: e.target.checked })} />{" "}
          An emergency fund: a number of months of my everyday envelopes</label>
        <div className="row" style={{ flexWrap: "wrap", gap: "var(--s3)" }}>
          <Field label="Name"><input aria-label="Goal name" value={form.name}
            placeholder={form.emergency ? "Emergency fund" : "Car repairs"}
            onChange={(e) => set({ name: e.target.value })} /></Field>
          {form.emergency ? (
            <Field label="Months"><input aria-label="Months of envelopes" value={form.months}
              type="number" min={1} max={24} style={{ width: "6rem" }}
              onChange={(e) => set({ months: e.target.value })} /></Field>
          ) : (
            <Field label="Target"><input aria-label="Target amount" value={form.target}
              style={{ width: "8rem" }} onChange={(e) => set({ target: e.target.value })} />
            </Field>
          )}
          <Field label="By (optional)"><input aria-label="Target date" type="date"
            value={form.target_on} onChange={(e) => set({ target_on: e.target.value })} />
          </Field>
          {!form.target_on && (
            <Field label="A month (optional)"><input aria-label="Amount a month"
              value={form.monthly} style={{ width: "7rem" }}
              onChange={(e) => set({ monthly: e.target.value })} /></Field>
          )}
          <Field label="Saved already"><input aria-label="Saved already" value={form.saved}
            style={{ width: "7rem" }} onChange={(e) => set({ saved: e.target.value })} />
          </Field>
          <Field label="Kept in"><select aria-label="Kept in" value={form.account}
            onChange={(e) => set({ account: e.target.value })}>
            <option value="">No account</option>
            {own.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select></Field>
        </div>
        <button className="primary" disabled={add.isPending || !form.name.trim()
          || (form.emergency ? !Number(form.months) : toCents(form.target) === null)}
          onClick={() => add.mutate()}>Add the goal</button>
      </Card>
    </>
  );
}

function GoalDetail({ g, accounts, onClose, onSaid }: {
  g: PersonalGoal; accounts: PersonalAccount[]; onClose: () => void;
  onSaid: (s: { kind: string; text: string }) => void;
}) {
  const [saved, setSaved] = useState(plainDollars(g.saved_cents));
  const update = useMutation({
    mutationFn: () => api.patch<PersonalGoal>(`/api/personal/goals/${g.id}`, {
      name: g.name, target_on: g.target_on, account: g.account?.id ?? null,
      saved_cents: toCents(saved),
      ...(g.months_of_envelopes ? { months_of_envelopes: g.months_of_envelopes }
        : { target_cents: g.target_cents }),
      monthly_cents: g.monthly_chosen ? g.monthly_cents : null }),
    onSuccess: (r) => onSaid({ kind: "ok", text: `${r.name}: ${money(r.monthly_cents)} a month `
      + "now." }),
    onError: (e: Error) => onSaid({ kind: "bad", text: e.message }),
  });
  const away = useMutation({
    mutationFn: () => api.del(`/api/personal/goals/${g.id}`),
    onSuccess: () => { onSaid({ kind: "ok", text: `${g.name} is put away.` }); onClose(); },
  });
  void accounts;
  return (
    <Card title={`Goal: ${g.name}`} actions={<button className="ghost small"
      onClick={onClose}>Close</button>}>
      <div className="meter" role="progressbar" aria-label={`${g.name}: ${g.percent}%`}
        aria-valuenow={g.percent} style={{ maxWidth: "none", marginBottom: "var(--s3)" }}>
        <span style={{ width: `${g.percent}%` }} /></div>
      <dl className="facts">
        <dt>Target</dt><dd>{money(g.target_cents)}{g.months_of_envelopes
          ? ` (${g.months_of_envelopes} months of your everyday envelopes)` : ""}</dd>
        <dt>By</dt><dd>{g.target_on ? longDate(g.target_on) : "No date"}</dd>
        <dt>Saved already</dt><dd>{money(g.saved_cents)}</dd>
        <dt>Set aside in the budget</dt><dd>{money(g.set_aside_cents)}</dd>
        <dt>So far</dt><dd>{money(g.progress_cents)}, {g.percent}%</dd>
        <dt>A month</dt><dd>{money(g.monthly_cents)}{g.target_on
          ? ", worked out from what is still to save and the months left"
          : g.monthly_chosen ? ", as you chose" : ", a year's worth until you choose"}</dd>
        <dt>Kept in</dt><dd>{g.account?.name ?? "No account"}</dd>
        <dt>On your plans</dt><dd>{g.planned ? `${money(g.planned.amount_cents)} on `
          + longDate(g.planned.on_date) : "Not dated, so not on a day"}</dd>
      </dl>
      <div className="row tight">
        <Field label="Saved already, now"><input aria-label="Saved already, now" value={saved}
          style={{ width: "8rem" }} onChange={(e) => setSaved(e.target.value)} /></Field>
        <button style={{ alignSelf: "flex-end" }} disabled={toCents(saved) === null
          || update.isPending} onClick={() => update.mutate()}>Save</button>
        <button className="danger" style={{ alignSelf: "flex-end" }}
          onClick={() => away.mutate()}>Put it away</button>
      </div>
    </Card>
  );
}

// --------------------------------------------------------- Cash flow table

function CashFlowTable({ flow }: { flow: CashFlow }) {
  if (flow.rows.length === 0) return null;
  const n = flow.months.length;
  return (
    <Card title="Cash flow by month">
      <p className="small muted" style={{ marginTop: 0 }}>Money in and out by category; moves
        between your own accounts are not in it. {flow.labels[n - 1]} is so far.</p>
      <div style={{ overflowX: "auto" }}>
        <table className="data cash-flow" aria-label="Cash flow by month">
          <thead><tr><th>Category</th>{flow.labels.map((l, i) => (
            <th key={i} className="num">{l}{i === n - 1 ? " so far" : ""}</th>))}</tr></thead>
          <tbody>
            {flow.rows.map((row) => (
              <tr key={`${row.type}-${row.name}`}>
                <td>{row.name}{row.type === "income" && <span className="muted"> (in)</span>}</td>
                {row.cents.map((c, i) => <td key={i} className="num">{c ? money(c) : "—"}</td>)}
              </tr>
            ))}
            <tr className="total"><td><strong>In</strong></td>
              {flow.in_cents.map((c, i) => <td key={i} className="num">{money(c)}</td>)}</tr>
            <tr className="total"><td><strong>Out</strong></td>
              {flow.out_cents.map((c, i) => <td key={i} className="num">{money(c)}</td>)}</tr>
            <tr className="total"><td><strong>Net</strong></td>
              {flow.net_cents.map((c, i) => (
                <td key={i} className="num" style={{ color: c < 0 ? "var(--bad)" : undefined }}>
                  <strong>{money(c)}</strong></td>))}</tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ------------------------------------------------------ Explain this budget

interface ExplainStatus { estimate_usd: string; used_today: number; cap: number;
                          refused: string }

function ExplainBudget() {
  const status = useQuery<ExplainStatus>({
    queryKey: ["personal-explain-budget"],
    queryFn: () => api.get<ExplainStatus>("/api/personal/budget/explain") });
  const [answer, setAnswer] = useState<{ text: string; cost_usd: string } | null>(null);
  const [error, setError] = useState("");
  const ask = useMutation({
    mutationFn: () => api.post<{ text: string; cost_usd: string }>(
      "/api/personal/budget/explain"),
    onSuccess: (r) => { setAnswer(r); setError(""); status.refetch(); },
    onError: (e: Error) => setError(e.message),
  });
  const s = status.data;
  return (
    <Card title="Explain this budget">
      <p className="small muted" style={{ marginTop: 0 }}>Claude reads your envelopes, goals,
        yearly bills and six months of totals by category. Never your name, an account's name
        or number, or a shop's name.</p>
      {error && <Banner kind="bad">{error}</Banner>}
      {s?.refused ? <p className="small muted">{s.refused}</p> : (
        <AiGate><button className="small" disabled={!s || ask.isPending || !!answer}
          onClick={() => ask.mutate()}>
          {ask.isPending ? "Asking Claude…" : answer ? "Explained below"
            : `Explain this budget (about $${Number(s?.estimate_usd ?? 0).toFixed(2)})`}
        </button></AiGate>
      )}
      {s && <span className="small muted"> {s.used_today} of {s.cap} used today.</span>}
      {answer && (
        <div style={{ marginTop: "var(--s3)" }}>
          {answer.text.split(/\n\s*\n/).map((p, i) => <p key={i}>{p}</p>)}
          <p className="tiny muted">Cost ${Number(answer.cost_usd).toFixed(4)}.</p>
        </div>
      )}
    </Card>
  );
}
