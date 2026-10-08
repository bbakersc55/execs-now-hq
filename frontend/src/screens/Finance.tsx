import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  BalanceView, EntryKind, FinanceAccount, FinanceCategory, FinanceEntry, FinanceEntryList,
  PayeeReport, Pnl, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";
import { FinanceImport } from "./FinanceImport";
import { FinancePayees } from "./FinancePayees";

/**
 * The practice's books (P5; matrix 13.1, 13.6–13.10). The practice owner's
 * only: it is in nobody else's navigation, and the server refuses every other
 * role on every route.
 *
 * Cash basis: income counts when the money arrives and an expense when it
 * leaves. A paid invoice arrives here by itself; everything else is typed in
 * (and, in the next round, imported from a bank or card export).
 */

type Tab = "entries" | "import" | "pnl" | "balance" | "payees" | "export";
const TABS: [Tab, string, string][] = [
  ["entries", "/finance", "Entries"], ["import", "/finance/import", "Import"],
  ["pnl", "/finance/pnl", "Profit and loss"],
  ["balance", "/finance/balance", "Balance view"],
  ["payees", "/finance/1099", "1099 payees"], ["export", "/finance/export", "For your CPA"],
];
const KINDS: [EntryKind, string][] = [
  ["expense", "Expense"], ["income", "Income"], ["transfer", "Transfer between accounts"],
  ["owner", "Owner money in or out"], ["held", "Tax held or paid over"],
];
const TYPE_FOR: Record<EntryKind, string> = {
  income: "income", expense: "expense", owner: "owner", held: "held", transfer: "" };

function useBooks() {
  const accounts = useQuery<FinanceAccount[]>({
    queryKey: ["finance-accounts"],
    queryFn: () => api.get<FinanceAccount[]>("/api/finance-accounts/") });
  const categories = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  return { accounts: accounts.data ?? [], categories: categories.data ?? [],
           ready: !!accounts.data && !!categories.data };
}

export function Finance({ tab }: { tab: Tab }) {
  return (
    <>
      <PageHead title="Finance"
        sub={<>Your practice's books, on a cash basis: income when it arrives, an expense
          when it leaves. Only you see this.{" "}
          <Link to="/settings/finance">Accounts and categories</Link></>} />
      <nav className="row tight" aria-label="Finance" style={{ marginBottom: "var(--s4)" }}>
        {TABS.map(([key, to, label]) => (
          <NavLink key={key} to={to} end
            className={({ isActive }) => (isActive ? "btn primary small" : "btn small")}>
            {label}</NavLink>
        ))}
      </nav>
      {tab === "entries" && <Entries />}
      {tab === "import" && <Importing />}
      {tab === "payees" && <FinancePayees />}
      {tab === "pnl" && <ProfitAndLoss />}
      {tab === "balance" && <Balance />}
      {tab === "export" && <ForTheCpa />}
    </>
  );
}

function Importing() {
  const { accounts, categories, ready } = useBooks();
  return ready ? <FinanceImport accounts={accounts} categories={categories} />
    : <p>Opening the books…</p>;
}

// ------------------------------------------------------------------- entries

type Draft = { kind: EntryKind; direction: "in" | "out"; on_date: string; amount_cents: number;
               category: string; account: string; to_account: string; description: string;
               counterparty: string; payee_contact: string };

const today = () => new Date().toISOString().slice(0, 10);
const blank = (): Draft => ({ kind: "expense", direction: "out", on_date: today(),
                              amount_cents: 0, category: "", account: "", to_account: "",
                              description: "", counterparty: "", payee_contact: "" });

function EntryForm({ start, entry, onDone, onCancel }: {
  start: Draft; entry?: FinanceEntry; onDone: () => void; onCancel?: () => void;
}) {
  const { accounts, categories } = useBooks();
  const payees = useQuery<PayeeReport>({
    queryKey: ["finance-payees", "list"],
    queryFn: () => api.get<PayeeReport>("/api/finance-payees/") });
  const flagged = (payees.data?.payees ?? []).filter((p) => p.is_payee);
  const [form, setForm] = useState<Draft>(start);
  const [said, setSaid] = useState("");
  const set = (patch: Partial<Draft>) => setForm({ ...form, ...patch });
  // An entry made from an invoice payment keeps the payment's amount and date.
  const fromInvoice = entry?.source === "invoice";
  const open = accounts.filter((a) => !a.closed || a.id === form.account
    || a.id === form.to_account);
  const fitting = categories.filter((c) => c.type === TYPE_FOR[form.kind]
    && (!c.archived || c.id === form.category));
  const save = useMutation({
    mutationFn: () => {
      const body = fromInvoice
        ? { category: form.category || null, account: form.account || null,
            description: form.description }
        : { kind: form.kind, on_date: form.on_date, amount_cents: form.amount_cents,
            category: form.kind === "transfer" ? null : form.category || null,
            account: form.account || null,
            to_account: form.kind === "transfer" ? form.to_account || null : null,
            ...(form.kind === "owner" || form.kind === "held"
              ? { direction: form.direction } : {}),
            description: form.description, counterparty: form.counterparty,
            payee_contact: form.kind === "expense" ? form.payee_contact || null : null };
      return entry ? api.patch<FinanceEntry>(`/api/finance-entries/${entry.id}/`, body)
        : api.post<FinanceEntry>("/api/finance-entries/", body);
    },
    onSuccess: () => { setSaid(""); if (!entry) setForm(blank()); onDone(); },
    onError: (e: Error) => setSaid(e.message),
  });
  const label = entry ? "this entry" : "the new entry";
  return (
    <>
      {said && <Banner kind="bad">{said}</Banner>}
      {fromInvoice && (
        <p className="small muted" style={{ marginTop: 0 }}>
          This is a payment on invoice {entry?.invoice?.number}. Its amount and date are
          changed on the invoice; here you can say where it landed and what to call it.
        </p>
      )}
      <div className="row">
        {!fromInvoice && (
          <>
            <Field label="What">
              <select aria-label={`Kind of ${label}`} value={form.kind}
                onChange={(e) => set({ kind: e.target.value as EntryKind, category: "" })}>
                {KINDS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select>
            </Field>
            <Field label="Date">
              <input type="date" aria-label={`Date of ${label}`} value={form.on_date}
                max={today()} onChange={(e) => set({ on_date: e.target.value })} />
            </Field>
            <Field label="Amount">
              <PriceBox label={`Amount of ${label}`} cents={form.amount_cents}
                onChange={(amount_cents) => set({ amount_cents })} />
            </Field>
          </>
        )}
        {(form.kind === "owner" || form.kind === "held") && !fromInvoice && (
          <Field label="Which way">
            <select aria-label={`Direction of ${label}`} value={form.direction}
              onChange={(e) => set({ direction: e.target.value as "in" | "out" })}>
              <option value="out">Money out</option>
              <option value="in">Money in</option>
            </select>
          </Field>
        )}
        {form.kind !== "transfer" && (
          <Field label="Category">
            <select aria-label={`Category of ${label}`} value={form.category}
              onChange={(e) => set({ category: e.target.value })}>
              <option value="">{form.kind === "income" || form.kind === "expense"
                ? "No category yet" : "Choose a category"}</option>
              {fitting.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <Field label={form.kind === "transfer" ? "From" : "Account"}>
          <select aria-label={`Account of ${label}`} value={form.account}
            onChange={(e) => set({ account: e.target.value })}>
            <option value="">{fromInvoice ? "Not placed yet" : "Choose an account"}</option>
            {open.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        {form.kind === "transfer" && (
          <Field label="To">
            <select aria-label={`Account ${label} goes to`} value={form.to_account}
              onChange={(e) => set({ to_account: e.target.value })}>
              <option value="">Choose an account</option>
              {open.filter((a) => a.id !== form.account).map(
                (a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        )}
      </div>
      <div className="row">
        <Field label="Description">
          <input aria-label={`Description of ${label}`} value={form.description} maxLength={255}
            onChange={(e) => set({ description: e.target.value })} />
        </Field>
        {!fromInvoice && (
          <Field label={form.kind === "income" ? "Paid by" : "Paid to"}>
            <input aria-label={`Payee or payer of ${label}`} value={form.counterparty}
              maxLength={160} onChange={(e) => set({ counterparty: e.target.value })} />
          </Field>
        )}
        {form.kind === "expense" && !fromInvoice && flagged.length > 0 && (
          <Field label="1099 payee">
            <select aria-label={`1099 payee of ${label}`} value={form.payee_contact}
              onChange={(e) => set({ payee_contact: e.target.value })}>
              <option value="">Not a 1099 payee</option>
              {flagged.map((p) => <option key={p.contact} value={p.contact}>{p.name}</option>)}
            </select>
          </Field>
        )}
        <button className="primary" disabled={save.isPending
          || (!fromInvoice && (form.amount_cents <= 0 || !form.account))}
          onClick={() => save.mutate()}>
          {entry ? "Save the entry" : "Add the entry"}</button>
        {onCancel && <button className="ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </>
  );
}

function Entries() {
  const qc = useQueryClient();
  const { accounts, categories, ready } = useBooks();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(["from", "to", "kind", "category", "account", "q"]
    .map((name) => [name, params.get(name) ?? ""]));
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    setParams(next, { replace: true });
  };
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value)).toString();
  const list = useQuery<FinanceEntryList>({
    queryKey: ["finance-entries", query],
    queryFn: () => api.get<FinanceEntryList>(`/api/finance-entries/${query ? `?${query}` : ""}`),
  });
  const [editing, setEditing] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [said, setSaid] = useState("");
  const refresh = () => {
    setEditing(""); setPicked([]);
    for (const key of ["finance-entries", "finance-pnl", "finance-balance", "dashboard"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const act = useMutation({
    mutationFn: ({ url, body }: { url: string; body: object }) => api.post<unknown>(url, body),
    onSuccess: () => { setSaid(""); refresh(); },
    onError: (e: Error) => setSaid(e.message),
  });
  const data = list.data;
  if (list.isError) return <Banner kind="bad">{(list.error as Error).message}</Banner>;
  const signed = (entry: FinanceEntry) => entry.kind === "transfer"
    ? dollars(entry.amount_cents)
    : `${entry.direction === "out" ? "−" : ""}${dollars(entry.amount_cents)}`;
  return (
    <>
      {ready && accounts.length === 0 ? (
        <Banner kind="info">Add the bank account or card your money moves through first, in{" "}
          <Link to="/settings/finance">Accounts and categories</Link>. An entry says which
          account it went through.</Banner>
      ) : (
        <Card title="Add an entry"><EntryForm start={blank()} onDone={refresh} /></Card>
      )}
      {said && <Banner kind="bad">{said}</Banner>}
      <Card>
        <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
          <label className="small inline">From
            <input type="date" aria-label="From" value={filters.from} style={{ width: "auto" }}
              onChange={(e) => set("from", e.target.value)} /></label>
          <label className="small inline">to
            <input type="date" aria-label="To" value={filters.to} style={{ width: "auto" }}
              onChange={(e) => set("to", e.target.value)} /></label>
          <select aria-label="Kind" value={filters.kind} style={{ width: "auto" }}
            onChange={(e) => set("kind", e.target.value)}>
            <option value="">Every kind</option>
            {KINDS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
          <select aria-label="Category" value={filters.category} style={{ width: "auto" }}
            onChange={(e) => set("category", e.target.value)}>
            <option value="">Every category</option>
            <option value="none">No category yet</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select aria-label="Account" value={filters.account} style={{ width: "auto" }}
            onChange={(e) => set("account", e.target.value)}>
            <option value="">Every account</option>
            <option value="none">Not placed in an account</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <input aria-label="Search entries" placeholder="Description or payee"
            value={filters.q} style={{ width: "14rem" }}
            onChange={(e) => set("q", e.target.value)} />
        </div>
        {data && (
          <p className="small" aria-label="Totals for what is listed">
            Income <strong>{dollars(data.totals.income_cents)}</strong> · expenses{" "}
            <strong>{dollars(data.totals.expenses_cents)}</strong> · net{" "}
            <strong>{dollars(data.totals.net_cents)}</strong>
            {data.count > data.entries.length
              && <> · showing the newest {data.entries.length} of {data.count}</>}
          </p>
        )}
        {picked.length > 0 && (
          <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
            <span className="small">{picked.length} chosen:</span>
            <select aria-label="Category for the chosen entries" value={target}
              style={{ width: "auto" }} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Move them to…</option>
              {categories.filter((c) => !c.archived).map(
                (c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button disabled={!target || act.isPending}
              onClick={() => act.mutate({ url: "/api/finance-entries/recategorize/",
                                          body: { entries: picked, category: target } })}>
              Change the category</button>
          </div>
        )}
        {!data ? <p>Loading the entries…</p> : data.entries.length === 0
          ? <Empty>{query ? "No entry matches." : "No entries yet."}</Empty> : (
            <table>
              <thead><tr><th /><th>Date</th><th>Description</th><th>Category</th>
                <th>Account</th><th className="money">Amount</th><th /></tr></thead>
              <tbody>
                {data.entries.map((entry) => editing === entry.id ? (
                  <tr key={entry.id}><td colSpan={7}>
                    <EntryForm entry={entry} onDone={refresh} onCancel={() => setEditing("")}
                      start={{ kind: entry.kind, direction: entry.direction,
                               on_date: entry.on_date, amount_cents: entry.amount_cents,
                               category: entry.category?.id ?? "",
                               account: entry.account?.id ?? "",
                               to_account: entry.to_account?.id ?? "",
                               description: entry.description,
                               counterparty: entry.counterparty,
                               payee_contact: entry.payee_contact ?? "" }} />
                  </td></tr>
                ) : (
                  <tr key={entry.id}>
                    <td>{entry.kind !== "transfer" && (
                      <input type="checkbox" checked={picked.includes(entry.id)}
                        aria-label={`Choose the entry of ${longDate(entry.on_date)}, ${dollars(entry.amount_cents)}`}
                        onChange={(e) => setPicked(e.target.checked
                          ? [...picked, entry.id] : picked.filter((id) => id !== entry.id))} />
                    )}</td>
                    <td>{longDate(entry.on_date)}</td>
                    <td>{entry.description || entry.counterparty || <span className="muted">—</span>}
                      {entry.description && entry.counterparty
                        && <span className="muted"> · {entry.counterparty}</span>}
                      {entry.invoice && <> · <Link to={`/invoices/${entry.invoice.id}`}>
                        invoice {entry.invoice.number}</Link></>}</td>
                    <td>{entry.kind === "transfer" ? <Pill>transfer</Pill>
                      : entry.category?.name ?? <Pill kind="warn">no category yet</Pill>}
                      {(entry.kind === "owner" || entry.kind === "held")
                        && <> <Pill>not in the P&amp;L</Pill></>}</td>
                    <td>{entry.account?.name ?? <Pill kind="warn">not placed yet</Pill>}
                      {entry.to_account && <> → {entry.to_account.name}</>}</td>
                    <td className="money">{signed(entry)}</td>
                    <td className="money">
                      <button className="ghost small" aria-label={`Edit the entry of ${longDate(entry.on_date)}, ${dollars(entry.amount_cents)}`}
                        onClick={() => setEditing(entry.id)}>Edit</button>{" "}
                      {entry.source !== "invoice" && (
                        <button className="ghost small" disabled={act.isPending}
                          aria-label={`Remove the entry of ${longDate(entry.on_date)}, ${dollars(entry.amount_cents)}`}
                          onClick={() => {
                            const reason = prompt("Why is this entry being removed? It is "
                              + "kept in the history and leaves every figure.");
                            if (reason && reason.trim()) {
                              act.mutate({ url: `/api/finance-entries/${entry.id}/remove/`,
                                           body: { reason: reason.trim() } });
                            }
                          }}>Remove</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
    </>
  );
}

// ----------------------------------------------------------------------- P&L

function ProfitAndLoss() {
  const [params, setParams] = useSearchParams();
  const year = params.get("year") ?? String(new Date().getFullYear());
  const by = params.get("by") === "quarter" ? "quarter" : "month";
  const report = useQuery<Pnl>({
    queryKey: ["finance-pnl", year, by],
    queryFn: () => api.get<Pnl>(`/api/finance-reports/pnl/?year=${year}&by=${by}`) });
  if (report.isError) return <Banner kind="bad">{(report.error as Error).message}</Banner>;
  if (!report.data) return <p>Adding up the year…</p>;
  const r = report.data;
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params); next.set(name, value);
    setParams(next, { replace: true });
  };
  // The entries behind one figure: that category, in that month or quarter.
  const behind = (category: string, period: number) => {
    const first = by === "month" ? period + 1 : period * 3 + 1;
    const last = by === "month" ? period + 1 : period * 3 + 3;
    const pad = (n: number) => String(n).padStart(2, "0");
    const end = new Date(Date.UTC(r.year, last, 0)).getUTCDate();
    return `/finance?category=${category}&from=${r.year}-${pad(first)}-01`
      + `&to=${r.year}-${pad(last)}-${pad(end)}`;
  };
  const section = (title: string, data: Pnl["income"]) => (
    <>
      <tr><th colSpan={r.periods.length + 2}>{title}</th></tr>
      {data.rows.map((row) => (
        <tr key={row.id}>
          <td>{row.name}</td>
          {row.amounts.map((cents, i) => (
            <td key={i} className="money">{cents === 0 ? <span className="muted">—</span>
              : <Link to={behind(row.id, i)}
                aria-label={`${row.name}, ${r.periods[i]}: ${dollars(cents)}`}>
                {dollars(cents)}</Link>}</td>
          ))}
          <td className="money"><strong>{dollars(row.total)}</strong></td>
        </tr>
      ))}
      <tr>
        <td><strong>Total {title.toLowerCase()}</strong></td>
        {data.totals.map((cents, i) => <td key={i} className="money"><strong>{dollars(cents)}</strong></td>)}
        <td className="money"><strong>{dollars(data.total)}</strong></td>
      </tr>
    </>
  );
  return (
    <Card title={`Profit and loss, ${r.year}`}
      actions={<a className="btn small"
        href={`/api/finance-reports/pnl/?year=${r.year}&by=${by}&download=1`}>
        Download as CSV</a>}>
      <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
        <select aria-label="Year" value={String(r.year)} style={{ width: "auto" }}
          onChange={(e) => set("year", e.target.value)}>
          {r.years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select aria-label="By month or quarter" value={by} style={{ width: "auto" }}
          onChange={(e) => set("by", e.target.value)}>
          <option value="month">By month</option>
          <option value="quarter">By quarter</option>
        </select>
        <span className="small muted">Cash basis. Transfers, your own money in or out and
          tax held are not income or costs, and are not here.</span>
      </div>
      {r.uncategorized.count > 0 && (
        <Banner kind="warn">
          {r.uncategorized.count} {r.uncategorized.count === 1 ? "entry" : "entries"},{" "}
          {dollars(r.uncategorized.amount_cents)}, {r.uncategorized.count === 1 ? "has" : "have"}
          {" "}no category and {r.uncategorized.count === 1 ? "is" : "are"} not in these
          figures. <Link to="/finance?category=none">Give them one</Link>
        </Banner>
      )}
      <div style={{ overflowX: "auto" }}>
        <table className="pnl">
          <thead><tr><th />{r.periods.map((p) => (
            <th key={p} className="money">{by === "month" ? p.slice(0, 3) : p}</th>))}
            <th className="money">Total</th></tr></thead>
          <tbody>
            {section("Income", r.income)}
            {section("Expenses", r.expenses)}
            <tr aria-label="Net">
              <td><strong>Net</strong></td>
              {r.net.map((cents, i) => <td key={i} className="money"><strong>{dollars(cents)}</strong></td>)}
              <td className="money"><strong>{dollars(r.net_total)}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------ the balance view

function Balance() {
  const [asOf, setAsOf] = useState(today());
  const view = useQuery<BalanceView>({
    queryKey: ["finance-balance", asOf],
    queryFn: () => api.get<BalanceView>(`/api/finance-reports/balance/?as_of=${asOf}`) });
  if (view.isError) return <Banner kind="bad">{(view.error as Error).message}</Banner>;
  const v = view.data;
  const line = (label: React.ReactNode, cents: number, strong = false) => (
    <tr><td>{strong ? <strong>{label}</strong> : label}</td>
      <td className="money">{strong ? <strong>{dollars(cents)}</strong> : dollars(cents)}</td></tr>
  );
  return (
    <Card title="Balance view"
      actions={<label className="small inline">As of
        <input type="date" aria-label="As of" value={asOf} max={today()}
          style={{ width: "auto" }} onChange={(e) => setAsOf(e.target.value)} /></label>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Your cash, what you owe on cards, and tax you are holding. It is not a balance
        sheet: it has no equipment, no loans and no retained earnings.
      </p>
      {!v ? <p>Adding it up…</p> : (
        <table aria-label="Balance view" style={{ maxWidth: 560 }}>
          <tbody>
            {v.cash.map((row) => <tr key={row.id}><td>{row.name}
              {row.last4 && <span className="muted"> ·· {row.last4}</span>}
              {row.bank_said && (
                <div className="tiny muted">Your bank said {dollars(row.bank_said.cents)} on{" "}
                  {longDate(row.bank_said.on)}; the books say{" "}
                  {dollars(row.bank_said.books_cents)}
                  {row.bank_said.difference_cents === 0 ? ", the same."
                    : `, ${dollars(Math.abs(row.bank_said.difference_cents))} `
                      + `${row.bank_said.difference_cents > 0 ? "more" : "less"}.`}</div>
              )}</td>
              <td className="money">{dollars(row.amount_cents)}</td></tr>)}
            {v.unplaced_count > 0 && line(<>Received on invoices, not yet placed in an
              account ({v.unplaced_count})</>, v.unplaced_cents)}
            {line("Cash", v.cash_total_cents, true)}
            {v.cards.map((row) => <tr key={row.id}><td>{row.name}, owed</td>
              <td className="money">{dollars(row.amount_cents)}</td></tr>)}
            {v.tax_held_cents !== 0 && line("Sales tax collected, not yet paid over",
                                           v.tax_held_cents)}
            {line("Owed", v.owed_total_cents, true)}
            {line("Net", v.net_cents, true)}
          </tbody>
        </table>
      )}
      {v && (
        <p className="small">Beside it, not in it: your clients owe you{" "}
          <strong>{dollars(v.owed_to_you_cents)}</strong> on{" "}
          <Link to="/invoices">invoices</Link>. On a cash basis that counts when it is paid.</p>
      )}
    </Card>
  );
}

// -------------------------------------------------------------- the CPA export

function ForTheCpa() {
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year}-01-01`);
  const [to, setTo] = useState(today());
  const [bad, setBad] = useState(false);
  useEffect(() => { setBad(!!from && !!to && to < from); }, [from, to]);
  const span = `?from=${from}&to=${to}`;
  return (
    <Card title="For your CPA">
      <p className="small muted" style={{ marginTop: 0 }}>
        Two files for a range of dates: every entry, and a summary by category with the
        CPA codes you set. Removed entries are left out. Each download is recorded.
      </p>
      <div className="row">
        <Field label="From">
          <input type="date" aria-label="Export from" value={from}
            onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <input type="date" aria-label="Export to" value={to}
            onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      {bad ? <Banner kind="bad">The last date cannot be before the first.</Banner> : (
        <div className="row tight">
          <a className="btn primary" href={`/api/finance-reports/export-entries/${span}`}>
            Download the entries</a>
          <a className="btn" href={`/api/finance-reports/export-summary/${span}`}>
            Download the summary by category</a>
        </div>
      )}
      <p className="tiny muted">Lock the books through the last date once you have sent
        them, in <Link to="/settings/finance">Accounts and categories</Link>, so what your
        CPA has stays what the books say.</p>
    </Card>
  );
}
