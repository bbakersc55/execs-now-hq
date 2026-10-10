import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Field, Pill } from "../components/ui";
import {
  ExplainAnswer, ExplainStatus, FinanceCategory, MonthDetail, ReconcileCell, ReconcileGrid,
  ReconcileLine, ReconcileReport, Reconciliation, ReopenPlan, api,
} from "../lib/api";
import { FINANCE_DISCLAIMER, GUIDE_STEPS, categoryOptions } from "../lib/finance";
import { dollars, longDate } from "../lib/money";

/**
 * Finance → Reconcile (P6 M1 §1–§4; matrix 13.15, 13.12, 13.14): the practice
 * owner's, and only for a practice with the Bookkeeping module.
 *
 * Reconciling is ticking off each line of the books that the statement also
 * shows, until the two agree to the cent. Closing a month locks the books
 * through its last day. "Walk me through it" shows the steps, written here
 * and free; "Explain this step" asks Claude, and only when it is pressed.
 */

type Open = { kind: "rec"; id: string } | { kind: "start"; account: string; month: string }
  | { kind: "month"; month: string } | null;

const KEYS = ["finance-reconcile", "finance-reconciliation", "finance-month",
              "finance-settings", "finance-entries", "finance-balance", "finance-pnl"];

/** Signed, with its sign in front: a difference can be either way. */
const signed = (cents: number) => dollars(cents);

const lastDay = (month: string) => {
  const [year, m] = month.split("-").map(Number);
  return new Date(Date.UTC(year, m, 0)).toISOString().slice(0, 10);
};

export function FinanceReconcile() {
  const qc = useQueryClient();
  const [open, setOpen] = useState<Open>(null);
  const [step, setStep] = useState(1);
  const grid = useQuery<ReconcileGrid>({
    queryKey: ["finance-reconcile"],
    queryFn: () => api.get<ReconcileGrid>("/api/finance-reconcile/") });
  const refresh = () => { for (const key of KEYS) qc.invalidateQueries({ queryKey: [key] }); };
  const guide = useMutation({
    mutationFn: (on: boolean) => api.post<{ guided: boolean }>(
      "/api/finance-reconcile/guided/", { on }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["finance-reconcile"] }) });

  if (grid.isError) return <Banner kind="bad">{(grid.error as Error).message}</Banner>;
  const data = grid.data;
  if (!data) return <p>Opening the books…</p>;
  const recId = open?.kind === "rec" ? open.id : "";

  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        Your bank's statement says what the bank thinks happened. Your books say what you
        think happened. Reconciling is ticking off each line of the books that the statement
        also shows, until the two agree to the cent.
      </p>
      <div className="spread" style={{ marginBottom: "var(--s3)" }}>
        <p className="small" style={{ margin: 0 }}>
          {data.locked_through
            ? <>The books are locked through <strong>{longDate(data.locked_through)}</strong>
              {data.locked_by
                ? <>, set by closing {data.locked_by.month} ({data.locked_by.by}).</>
                : <>, a date typed before month close began.</>}</>
            : "No month is closed yet, so nothing is locked."}
        </p>
        <label className="row tight small">
          <input type="checkbox" checked={data.guided} disabled={guide.isPending}
            onChange={(e) => guide.mutate(e.target.checked)} />
          Walk me through it
        </label>
      </div>

      {data.guided && <Guide step={step} onStep={setStep} recId={recId} />}

      <Grid data={data} open={open}
        onOpen={(next) => {
          setOpen(next);
          if (next?.kind === "month") setStep(7);
          else if (next?.kind === "start") setStep(2);
          else if (next) setStep(3);
        }} />

      {open?.kind === "start" && (
        <Start data={data} account={open.account} month={open.month}
          onCancel={() => setOpen(null)}
          onStarted={(rec) => { refresh(); setOpen({ kind: "rec", id: rec.id }); setStep(3); }} />
      )}
      {open?.kind === "rec" && (
        <Working id={open.id} refresh={refresh} onClose={() => setOpen(null)}
          onStep={setStep} />
      )}
      {open?.kind === "month" && (
        <Month month={open.month} refresh={refresh} onClose={() => setOpen(null)} />
      )}
    </>
  );
}

// ---------------------------------------------------------------- the grid

const CELL: Record<ReconcileCell["state"], string> = {
  not_started: "Not started", open: "In progress", finished: "Reconciled",
  not_needed: "Not needed", before: "Before reconciling began" };
const MONTH_STATE = { open: "Open", closed: "Closed",
                      locked_before: "Locked before month close began" };

function Grid({ data, open, onOpen }: {
  data: ReconcileGrid; open: Open; onOpen: (next: Open) => void;
}) {
  return (
    <Card title="Accounts and months">
      {data.accounts.length === 0 ? (
        <p className="small muted">Add a bank account or a card
          under <Link to="/settings/finance">Accounts and categories</Link> first.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table aria-label="Reconciliations by account and month">
            <thead><tr><th>Account</th>
              {data.months.map((m) => <th key={m.month}>{m.label}</th>)}</tr></thead>
            <tbody>
              {data.accounts.map((account) => (
                <tr key={account.id}>
                  <th scope="row" style={{ textAlign: "left", whiteSpace: "nowrap" }}>
                    {account.name}
                    {account.last4 && <span className="muted"> ·· {account.last4}</span>}
                  </th>
                  {data.months.map((m) => {
                    const cell = account.cells[m.month];
                    const what = `${account.name}, ${m.label}`;
                    const mine = open?.kind === "rec" && open.id === cell.id;
                    if (cell.id) {
                      return (
                        <td key={m.month}>
                          <button className={mine ? "small primary" : "ghost small"}
                            aria-label={`${what}: ${CELL[cell.state]}`}
                            onClick={() => onOpen({ kind: "rec", id: cell.id! })}>
                            {cell.state === "finished"
                              ? <>Reconciled{cell.finished_at
                                && <span className="muted"> {longDate(
                                  cell.finished_at.slice(0, 10))}</span>}</>
                              : <>In progress, {signed(cell.difference_cents ?? 0)} off</>}
                          </button>
                        </td>
                      );
                    }
                    // An account's first reconciliation may be any month; after
                    // that, the next month is the one that can be started.
                    const startable = cell.state !== "before"
                      && (account.next_month === null || account.next_month === m.month);
                    return (
                      <td key={m.month} className="muted small">
                        {startable ? (
                          <button className="ghost small" aria-label={`${what}: start`}
                            onClick={() => onOpen({ kind: "start", account: account.id,
                                                    month: m.month })}>
                            {cell.state === "not_needed" ? "Not needed" : "Start"}</button>
                        ) : CELL[cell.state]}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr>
                <th scope="row" style={{ textAlign: "left" }}>The month</th>
                {data.months.map((m) => (
                  <td key={m.month}>
                    <button className={open?.kind === "month" && open.month === m.month
                      ? "small primary" : "ghost small"}
                      aria-label={`${m.label}: ${MONTH_STATE[m.state]}`}
                      onClick={() => onOpen({ kind: "month", month: m.month })}>
                      {m.state === "closed" ? <Pill kind="ok">Closed</Pill>
                        : m.state === "locked_before" ? <Pill>Locked before</Pill>
                          : data.next_to_close === m.month ? "Close…" : "Open"}
                    </button>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------ start one

function Start({ data, account, month, onCancel, onStarted }: {
  data: ReconcileGrid; account: string; month: string; onCancel: () => void;
  onStarted: (rec: Reconciliation) => void;
}) {
  const row = data.accounts.find((a) => a.id === account)!;
  const label = data.months.find((m) => m.month === month)?.label ?? month;
  const end = lastDay(month) > data.today ? data.today : lastDay(month);
  const said = row.bank_said && row.bank_said.on.slice(0, 7) === month ? row.bank_said : null;
  const [on, setOn] = useState(said?.on ?? end);
  const [cents, setCents] = useState(said?.cents ?? 0);
  // Only an account's first reconciliation can begin later than the account did.
  const first = row.next_month === null;
  const later = first && month > row.opening_on.slice(0, 7);
  const [typed, setTyped] = useState(false);
  const [startCents, setStartCents] = useState(0);
  const [error, setError] = useState("");
  const start = useMutation({
    mutationFn: () => api.post<Reconciliation>("/api/finance-reconcile/", {
      account, statement_on: on, statement_balance_cents: cents,
      ...(later && typed ? { starting_balance_cents: startCents,
                             starting_on: `${month}-01` } : {}) }),
    onSuccess: onStarted, onError: (e: Error) => setError(e.message) });
  const card = row.kind === "card";
  return (
    <Card title={`${row.name}, ${label}`} tone="current">
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row">
        <Field label={row.kind === "cash" ? "Counted on" : "Statement ending date"}>
          <input type="date" aria-label="Statement ending date" value={on}
            min={`${month}-01`} max={end} onChange={(e) => setOn(e.target.value)} />
        </Field>
        <Field label={card ? "Balance owed on the statement" : row.kind === "cash"
          ? "What you counted" : "Statement ending balance"}>
          <PriceBox label="Statement ending balance" cents={cents} onChange={setCents} />
        </Field>
      </div>
      {said && <p className="small muted">Your bank's file ended at {dollars(said.cents)} on{" "}
        {longDate(said.on)}. Check it against the statement.</p>}
      {later && (
        <>
          <label className="row tight small">
            <input type="checkbox" checked={typed}
              onChange={(e) => setTyped(e.target.checked)} />
            Begin reconciling with this statement
          </label>
          <p className="small muted" style={{ marginTop: "var(--s1)" }}>
            {typed
              ? "Type the statement's own starting balance. Entries before this month are "
                + "then never asked about."
              : `Otherwise it starts from the opening balance of ${dollars(
                row.opening_balance_cents)} on ${longDate(row.opening_on)}, and asks about `
                + "every entry since."}
          </p>
          {typed && (
            <Field label="Statement starting balance">
              <PriceBox label="Statement starting balance" cents={startCents}
                onChange={setStartCents} />
            </Field>
          )}
        </>
      )}
      <div className="row tight" style={{ marginTop: "var(--s3)" }}>
        <button disabled={start.isPending || !on} onClick={() => start.mutate()}>
          Start reconciling</button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------- work through one

function Lines({ title, rows, busy, onTick }: {
  title: string; rows: ReconcileLine[]; busy: boolean;
  onTick: (ids: string[], cleared: boolean) => void;
}) {
  // A list holds ticked lines or unticked ones, never both.
  const ticked = rows.length > 0 && rows.every((line) => line.cleared);
  return (
    <div style={{ flex: "1 1 22rem", minWidth: 0 }}>
      <div className="row tight" style={{ marginBottom: "var(--s2)" }}>
        <h4 style={{ margin: 0 }}>{title}</h4>
        {/* All of what this list shows, with the count before it acts. */}
        {rows.length > 1 && (
          <button className="ghost small" disabled={busy}
            aria-label={`${ticked ? "Untick" : "Tick"} all ${rows.length} shown in ${title}`}
            onClick={() => onTick(rows.map((line) => line.id), !ticked)}>
            {ticked ? "Untick" : "Tick"} all {rows.length} shown</button>
        )}
      </div>
      {rows.length === 0 ? <p className="small muted">Nothing here.</p> : (
        <table aria-label={title}>
          <tbody>
            {rows.map((line) => (
              <tr key={line.id}>
                <td style={{ width: "2rem" }}>
                  <input type="checkbox" checked={line.cleared} disabled={busy}
                    aria-label={`${line.cleared ? "Untick" : "Tick"} ${
                      line.description || line.kind_label}, ${dollars(line.amount_cents)}`}
                    onChange={(e) => onTick([line.id], e.target.checked)} />
                </td>
                <td style={{ whiteSpace: "nowrap" }}>{longDate(line.on_date)}</td>
                <td>{line.description || line.kind_label}
                  {line.counterparty && <span className="muted"> · {line.counterparty}</span>}
                  {line.from_bank && <> <Pill>from the bank</Pill></>}</td>
                <td className="money">{dollars(line.amount_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Working({ id, refresh, onClose, onStep }: {
  id: string; refresh: () => void; onClose: () => void; onStep: (step: number) => void;
}) {
  const qc = useQueryClient();
  const rec = useQuery<Reconciliation>({
    queryKey: ["finance-reconciliation", id],
    queryFn: () => api.get<Reconciliation>(`/api/finance-reconcile/${id}/`) });
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const act = useMutation<Reconciliation | null, Error,
                          { path: string; body?: object; method?: "patch" | "delete" }>({
    mutationFn: ({ path, body, method }) =>
      method === "patch" ? api.patch<Reconciliation>(`/api/finance-reconcile/${id}/`, body)
        : method === "delete"
          ? api.del<void>(`/api/finance-reconcile/${id}/`).then(() => null)
          : api.post<Reconciliation>(`/api/finance-reconcile/${id}/${path}`, body ?? {}),
    onSuccess: (data, sent) => {
      setError("");
      if (data) qc.setQueryData(["finance-reconciliation", id], data);
      refresh();
      if (sent.method === "delete") onClose();
      if (sent.path === "finish/") onStep(6);
    },
    onError: (e: Error) => setError(e.message) });
  const data = rec.data;
  const [on, setOn] = useState("");
  const [cents, setCents] = useState(0);
  useEffect(() => {
    if (data) { setOn(data.statement_on); setCents(data.statement_balance_cents); }
  }, [data?.statement_on, data?.statement_balance_cents]);  // eslint-disable-line

  if (rec.isError) return <Banner kind="bad">{(rec.error as Error).message}</Banner>;
  if (!data) return <p>Opening the statement…</p>;
  if (data.state === "finished") {
    return <Report rec={data} busy={act.isPending} error={error} onClose={onClose}
      onReopen={(reason) => act.mutate({ path: "reopen/", body: { reason } })} />;
  }
  const busy = act.isPending;
  const tick = (entries: string[], cleared: boolean) =>
    act.mutate({ path: "tick/", body: { entries, cleared } });
  const card = data.account.kind === "card";
  const left = data.lines.filter((line) => !line.cleared);
  const carried = left.filter((line) => line.carried);
  const fresh = left.filter((line) => !line.carried);
  const cleared = data.lines.filter((line) => line.cleared);
  const zero = data.difference_cents === 0;
  const changed = on !== data.statement_on || cents !== data.statement_balance_cents;
  // What money in and money out are called on a card, where the balance is owed.
  const inWord = card ? "payments and credits" : "money in";
  const outWord = card ? "charges" : "money out";

  return (
    <Card title={`${data.account.name}, ${data.month_label}`} tone="current"
      actions={<button className="ghost small" onClick={onClose}>Close this</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      {data.reopened_at && (
        <p className="small muted" style={{ marginTop: 0 }}>
          Reopened by {data.reopened_by} on {longDate(data.reopened_at.slice(0, 10))}:{" "}
          {data.reopen_reason}</p>
      )}
      <div className="row">
        <Field label="Statement ending date">
          <input type="date" aria-label="Statement ending date" value={on} disabled={busy}
            onChange={(e) => setOn(e.target.value)} />
        </Field>
        <Field label={card ? "Balance owed on the statement" : "Statement ending balance"}>
          <PriceBox label="Statement ending balance" cents={cents} onChange={setCents}
            disabled={busy} />
        </Field>
        {changed && (
          <button className="small" disabled={busy}
            onClick={() => act.mutate({ path: "", method: "patch", body: {
              statement_on: on, statement_balance_cents: cents } })}>
            Save the statement</button>
        )}
      </div>

      <div role="status" aria-label="The difference"
        className={`banner ${zero ? "ok" : "warn"}`} style={{ margin: "var(--s3) 0" }}>
        Statement balance {dollars(data.statement_balance_cents)} − ({card
          ? "owed at the start" : "starting balance"} {dollars(data.starting_balance_cents)}{" "}
        + cleared {card ? outWord : inWord}{" "}
        {dollars(card ? data.cleared_out_cents : data.cleared_in_cents)} − cleared{" "}
        {card ? inWord : outWord}{" "}
        {dollars(card ? data.cleared_in_cents : data.cleared_out_cents)}) = difference{" "}
        <strong>{signed(data.difference_cents)}</strong>
      </div>

      {!zero && data.hints.length > 0 && (
        <div style={{ marginBottom: "var(--s3)" }}>
          <p className="small" style={{ margin: 0 }}><strong>What it usually is</strong></p>
          <ul className="small" style={{ margin: "var(--s1) 0 0" }}>
            {data.hints.map((hint) => {
              const line = data.lines.find((row) => row.id === hint.entry);
              return (
                <li key={hint.kind}>{hint.text}
                  {line && <> <em>{line.description || line.kind_label},{" "}
                    {dollars(line.amount_cents)}, {longDate(line.on_date)}.</em></>}
                  {hint.kind === "untick" && line && <>{" "}
                    <button className="ghost small" disabled={busy}
                      onClick={() => tick([line.id], true)}>Tick this one?</button></>}
                  {hint.kind === "missing" && <>{" "}
                    <button className="ghost small" onClick={() => setAdding(true)}>
                      Add an entry</button></>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
        <button className="ghost small" disabled={busy || left.length === 0}
          onClick={() => act.mutate({ path: "tick/", body: { all: true, cleared: true } })}>
          Tick all {left.length} through the statement date</button>
        <button className="ghost small" disabled={busy || cleared.length === 0}
          onClick={() => act.mutate({ path: "tick/", body: { all: true, cleared: false } })}>
          Untick all {cleared.length}</button>
        <button className="ghost small" onClick={() => setAdding(!adding)}>
          {adding ? "Cancel the new entry" : "Add an entry"}</button>
      </div>
      {adding && <AddEntry account={data.account.id} on={data.statement_on}
        onDone={() => { setAdding(false); rec.refetch(); refresh(); }} />}

      {carried.length > 0 && (
        <div style={{ marginBottom: "var(--s3)" }}>
          <Lines title="From earlier statements" rows={carried} busy={busy} onTick={tick} />
          <p className="small muted">Left unticked before: a check not yet cashed, a charge
            not yet posted. Tick each one this statement shows.</p>
        </div>
      )}
      <div className="row" style={{ alignItems: "flex-start" }}>
        <Lines title={card ? "Payments and credits" : "Money in"} busy={busy} onTick={tick}
          rows={fresh.filter((line) => line.way === "in")} />
        <Lines title={card ? "Charges" : "Money out"} busy={busy} onTick={tick}
          rows={fresh.filter((line) => line.way === "out")} />
      </div>

      <details style={{ marginTop: "var(--s3)" }}>
        <summary>Cleared ({cleared.length})</summary>
        <Lines title="Cleared" rows={cleared} busy={busy} onTick={tick} />
      </details>

      {data.unplaced.length > 0 && (
        <div style={{ marginTop: "var(--s3)" }}>
          <h4 style={{ margin: "0 0 var(--s2)" }}>Received, not yet placed</h4>
          <p className="small muted" style={{ marginTop: 0 }}>Invoice payments that are in
            no account yet, so they cannot be ticked.</p>
          <table aria-label="Received, not yet placed"><tbody>
            {data.unplaced.map((row) => (
              <tr key={row.id}>
                <td>{longDate(row.on_date)}</td>
                <td>{row.description}
                  {row.counterparty && <span className="muted"> · {row.counterparty}</span>}</td>
                <td className="money">{dollars(row.amount_cents)}</td>
                <td className="money">
                  <button className="ghost small" disabled={busy}
                    aria-label={`Place ${row.description} here`}
                    onClick={() => act.mutate({ path: "place/", body: { entry: row.id } })}>
                    Place it here</button></td>
              </tr>
            ))}
          </tbody></table>
        </div>
      )}

      <div className="row tight" style={{ marginTop: "var(--s4)" }}>
        <button disabled={busy || !zero || changed}
          onClick={() => act.mutate({ path: "finish/" })}>Finish</button>
        {!zero && <span className="small muted">Finish is offered at a difference of
          exactly zero.</span>}
        {data.can_discard && (
          <button className="ghost" disabled={busy}
            onClick={() => {
              if (confirm("Discard this reconciliation? What you ticked is forgotten; the "
                + "entries themselves are untouched.")) {
                act.mutate({ path: "", method: "delete" });
              }
            }}>Discard</button>
        )}
      </div>
    </Card>
  );
}

/** "Add an entry", without leaving the statement (§1.4). */
function AddEntry({ account, on, onDone }: { account: string; on: string; onDone: () => void }) {
  const categories = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [date, setDate] = useState(on);
  const [cents, setCents] = useState(0);
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const all = categories.data ?? [];
  const save = useMutation({
    mutationFn: () => api.post<unknown>("/api/finance-entries/", {
      kind, on_date: date, amount_cents: cents, account, category: category || null,
      description }),
    onSuccess: onDone, onError: (e: Error) => setError(e.message) });
  return (
    <div className="card" style={{ marginBottom: "var(--s3)" }}>
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row">
        <Field label="It is">
          <select aria-label="Kind of the new entry" value={kind}
            onChange={(e) => { setKind(e.target.value as "expense" | "income");
                               setCategory(""); }}>
            <option value="expense">An expense</option>
            <option value="income">Income</option>
          </select>
        </Field>
        <Field label="Date">
          <input type="date" aria-label="Date of the new entry" value={date} max={on}
            onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Amount">
          <PriceBox label="Amount of the new entry" cents={cents} onChange={setCents} />
        </Field>
        <Field label="Category">
          <select aria-label="Category of the new entry" value={category}
            onChange={(e) => setCategory(e.target.value)}>
            <option value="">Choose…</option>
            {categoryOptions(all.filter((c) => c.type === kind && !c.archived), all)
              .map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </Field>
        <Field label="What it is">
          <input aria-label="Description of the new entry" value={description}
            maxLength={255} placeholder="As the statement shows it"
            onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <button disabled={save.isPending || cents <= 0} onClick={() => save.mutate()}>
          Add it</button>
      </div>
    </div>
  );
}

// --------------------------------------------------------- a finished one

function Report({ rec, busy, error, onReopen, onClose }: {
  rec: Reconciliation; busy: boolean; error: string; onReopen: (reason: string) => void;
  onClose: () => void;
}) {
  const report = useQuery<ReconcileReport>({
    queryKey: ["finance-reconciliation", rec.id, "report"],
    queryFn: () => api.get<ReconcileReport>(`/api/finance-reconcile/${rec.id}/report/`) });
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  const data = report.data;
  const card = rec.account.kind === "card";
  return (
    <Card title={`${rec.account.name}, ${rec.month_label}: reconciled`} tone="current"
      actions={<span className="row tight">
        <button className="ghost small" onClick={() => window.print()}>Print</button>
        <button className="ghost small" onClick={onClose}>Close this</button></span>}>
      {error && <Banner kind="bad">{error}</Banner>}
      {!data ? <p>Opening the report…</p> : (
        <section aria-label="Reconciliation report">
          <p className="small" style={{ marginTop: 0 }}>
            {data.practice} · {data.account.name} · statement ending{" "}
            {longDate(data.statement_on)}. Finished by {data.finished_by}
            {data.finished_at && <> on {longDate(data.finished_at.slice(0, 10))}</>}.
          </p>
          <table aria-label="Reconciliation summary" style={{ maxWidth: "32rem" }}>
            <tbody>
              <tr><td>{card ? "Owed at the start" : "Starting balance"}</td>
                <td className="money">{dollars(data.starting_balance_cents)}</td></tr>
              <tr><td>Cleared {card ? "payments and credits" : "money in"}</td>
                <td className="money">{dollars(data.cleared_in_cents)}</td></tr>
              <tr><td>Cleared {card ? "charges" : "money out"}</td>
                <td className="money">{dollars(data.cleared_out_cents)}</td></tr>
              <tr><td><strong>{card ? "Statement balance owed" : "Statement balance"}</strong>
              </td><td className="money"><strong>
                {dollars(data.statement_balance_cents)}</strong></td></tr>
              <tr><td>Difference</td>
                <td className="money">{dollars(data.difference_cents)}</td></tr>
            </tbody>
          </table>
          <h4>Still outstanding ({data.outstanding.length})</h4>
          {data.outstanding.length === 0
            ? <p className="small muted">Nothing: every entry through the statement date
              was on it.</p> : (
              <table aria-label="Still outstanding"><tbody>
                {data.outstanding.map((line) => (
                  <tr key={line.id}>
                    <td>{longDate(line.on_date)}</td>
                    <td>{line.description || line.kind_label}</td>
                    <td>{line.way === "in" ? "in" : "out"}</td>
                    <td className="money">{dollars(line.amount_cents)}</td>
                  </tr>
                ))}
              </tbody></table>
            )}
          <details>
            <summary>Cleared ({data.cleared.length})</summary>
            <table aria-label="Cleared on this statement"><tbody>
              {data.cleared.map((line) => (
                <tr key={line.id}>
                  <td>{longDate(line.on_date)}</td>
                  <td>{line.description || line.kind_label}</td>
                  <td>{line.way === "in" ? "in" : "out"}</td>
                  <td className="money">{dollars(line.amount_cents)}</td>
                </tr>
              ))}
            </tbody></table>
          </details>
          <p className="tiny muted" role="note" aria-label="Report disclaimer">
            {data.disclaimer}</p>
        </section>
      )}
      <div style={{ marginTop: "var(--s4)" }}>
        {rec.cannot_reopen ? <p className="small muted">{rec.cannot_reopen}</p>
          : !asking ? (
            <button className="ghost" onClick={() => setAsking(true)}>Reopen…</button>
          ) : (
            <>
              <Field label="Why it is being reopened">
                <input aria-label="Why the reconciliation is being reopened" value={reason}
                  onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div className="row tight">
                <button disabled={busy || !reason.trim()}
                  onClick={() => onReopen(reason.trim())}>Reopen it</button>
                <button className="ghost" onClick={() => setAsking(false)}>Cancel</button>
              </div>
            </>
          )}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------- one month

function Month({ month, refresh, onClose }: {
  month: string; refresh: () => void; onClose: () => void;
}) {
  const qc = useQueryClient();
  const detail = useQuery<MonthDetail>({
    queryKey: ["finance-month", month],
    queryFn: () => api.get<MonthDetail>(`/api/finance-months/${month}/`) });
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<ReopenPlan | null>(null);
  const [reason, setReason] = useState("");
  useEffect(() => { setPlan(null); setReason(""); setError(""); }, [month]);
  const done = (data: MonthDetail) => {
    setError(""); setPlan(null); setReason("");
    qc.setQueryData(["finance-month", month], data);
    refresh();
  };
  const close = useMutation({
    mutationFn: () => api.post<MonthDetail>(`/api/finance-months/${month}/close/`),
    onSuccess: done, onError: (e: Error) => setError(e.message) });
  const preview = useMutation({
    mutationFn: () => api.post<ReopenPlan>(`/api/finance-months/${month}/reopen/`,
                                           { preview: true }),
    onSuccess: (data) => { setError(""); setPlan(data); },
    onError: (e: Error) => setError(e.message) });
  const reopen = useMutation({
    mutationFn: () => api.post<MonthDetail>(`/api/finance-months/${month}/reopen/`,
                                            { reason: reason.trim() }),
    onSuccess: done, onError: (e: Error) => setError(e.message) });
  const data = detail.data;
  if (detail.isError) return <Banner kind="bad">{(detail.error as Error).message}</Banner>;
  if (!data) return <p>Opening the month…</p>;
  const busy = close.isPending || reopen.isPending || preview.isPending;
  const locked = data.state !== "open";

  return (
    <Card title={`${data.label}: ${MONTH_STATE[data.state].toLowerCase()}`} tone="current"
      actions={<button className="ghost small" onClick={onClose}>Close this</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      {data.state === "locked_before" && (
        <p className="small muted" style={{ marginTop: 0 }}>
          This month was locked by a date, before closing a month existed. It is locked,
          not reconciled. You can leave it, or reopen back through it and close it properly.
        </p>
      )}
      <table aria-label={`Close checklist for ${data.label}`}>
        <tbody>
          {data.checklist.map((line) => (
            <tr key={line.code}>
              <td style={{ width: "5.5rem" }}>
                {line.ok ? <Pill kind="ok">Done</Pill>
                  : line.blocks ? <Pill kind="bad">To do</Pill>
                    : <Pill kind="warn">Warning</Pill>}</td>
              <td>{line.label}
                {line.detail && <div className="small muted">{line.detail}</div>}</td>
              <td className="money">
                {!line.ok && <Link to={line.link}>Show me</Link>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {data.state === "open" && (
        <div style={{ marginTop: "var(--s3)" }}>
          <p className="small muted">Closing locks the books through the last day of{" "}
            {data.label}: nothing dated on or before it can be added, changed, removed,
            imported or rolled back.</p>
          <div className="row tight">
            <button disabled={busy || !!data.cannot_close} onClick={() => close.mutate()}>
              Close {data.label}</button>
            {data.cannot_close && <span className="small muted">{data.cannot_close}</span>}
          </div>
        </div>
      )}

      {data.history.length > 0 && (
        <>
          <h4>What happened to this month</h4>
          <ul className="small">
            {data.history.map((row) => (
              <li key={row.closed_at}>
                Closed by {row.closed_by} on {longDate(row.closed_at.slice(0, 10))}
                {row.warnings.length > 0 && <> with a warning showing:{" "}
                  {row.warnings.map((w) => `${w.label.toLowerCase()} (${w.count})`)
                    .join(", ")}</>}.
                {row.reopened_at && <> Reopened by {row.reopened_by} on{" "}
                  {longDate(row.reopened_at.slice(0, 10))}: {row.reopen_reason}</>}
              </li>
            ))}
          </ul>
        </>
      )}

      {locked && (
        <div style={{ marginTop: "var(--s3)" }}>
          {!plan ? (
            <button className="ghost" disabled={busy} onClick={() => preview.mutate()}>
              Reopen…</button>
          ) : (
            <>
              <Banner kind="warn">{plan.note}</Banner>
              <p className="small">
                {plan.also.length > 0
                  ? <>Reopening {plan.label} also reopens <strong>
                    {plan.also.join(", ")}</strong>. Their reconciliations stay finished.</>
                  : <>No later month is closed, so only {plan.label} reopens.</>}
              </p>
              <Field label="Why it is being reopened">
                <input aria-label="Why the month is being reopened" value={reason}
                  onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div className="row tight">
                <button disabled={busy || !reason.trim()} onClick={() => reopen.mutate()}>
                  Reopen {plan.label}</button>
                <button className="ghost" onClick={() => setPlan(null)}>Cancel</button>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------ guided mode

/** The same step with the same numbers is answered once per session, from the
 *  browser's own copy (§4.3). Nothing is stored anywhere else. */
const answered = new Map<string, ExplainAnswer>();

function Guide({ step, onStep, recId }: {
  step: number; onStep: (step: number) => void; recId: string;
}) {
  const qc = useQueryClient();
  // What a press costs and how many are left today. Asks Claude nothing.
  const status = useQuery<ExplainStatus>({
    queryKey: ["finance-explain"],
    queryFn: () => api.get<ExplainStatus>("/api/finance-reconcile/explain/") });
  const rec = qc.getQueryData<Reconciliation>(["finance-reconciliation", recId]);
  const key = [step, recId, rec?.statement_on, rec?.statement_balance_cents,
               rec?.cleared_in_cents, rec?.cleared_out_cents,
               rec?.lines.filter((line) => !line.cleared).length].join("|");
  const [answer, setAnswer] = useState<ExplainAnswer | null>(answered.get(key) ?? null);
  const [error, setError] = useState("");
  useEffect(() => { setAnswer(answered.get(key) ?? null); setError(""); }, [key]);
  const ask = useMutation({
    mutationFn: () => api.post<ExplainAnswer>("/api/finance-reconcile/explain/", {
      step, ...(recId ? { reconciliation: recId } : {}) }),
    onSuccess: (data) => {
      answered.set(key, data); setAnswer(data); setError("");
      qc.invalidateQueries({ queryKey: ["finance-explain"] });
    },
    onError: (e: Error) => setError(e.message) });
  const price = status.data;
  return (
    <Card title="Walk me through it">
      <ol aria-label="The steps" style={{ margin: 0, paddingLeft: "1.25rem" }}>
        {GUIDE_STEPS.map(([title, text], index) => {
          const number = index + 1;
          const here = number === step;
          return (
            <li key={title} style={{ marginBottom: "var(--s2)" }}>
              <button className="ghost small" aria-expanded={here}
                style={{ fontWeight: here ? 600 : 400 }} onClick={() => onStep(number)}>
                {title}</button>
              {here && (
                <div>
                  <p className="small" style={{ margin: "var(--s1) 0" }}>{text}</p>
                  {price?.refused ? <p className="small muted">{price.refused}</p> : (
                    <button className="ghost small"
                      disabled={ask.isPending || !price || !!answer}
                      onClick={() => ask.mutate()}>
                      {ask.isPending ? "Asking Claude…" : answer ? "Explained below"
                        : `Explain this step (about $${Number(price?.estimate_usd ?? 0)
                          .toFixed(2)})`}</button>
                  )}
                  {error && <Banner kind="bad">{error}</Banner>}
                  {answer && (
                    <div className="banner info" role="note" aria-label="Explanation"
                      style={{ marginTop: "var(--s2)", display: "block" }}>
                      <p className="small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                        {answer.text}</p>
                      <p className="tiny muted" style={{ margin: "var(--s2) 0 0" }}>
                        This cost ${Number(answer.cost_usd).toFixed(4)}.{" "}
                        {answer.used_today} of {answer.cap} used today.{" "}
                        {FINANCE_DISCLAIMER}</p>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
