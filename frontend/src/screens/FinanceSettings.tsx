import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PriceBox } from "../components/InvoiceLines";
import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill } from "../components/ui";
import { FinanceAccount, FinanceCategory, FinanceRule, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * Settings → Finance (P5; matrix 13.7): the practice owner's. The accounts
 * money moves through, the categories entries sit in, where a paid invoice is
 * entered, and the lock that keeps a period as the CPA was given it.
 */

const TYPES: [FinanceCategory["type"], string, string][] = [
  ["income", "Income", "What the practice earns."],
  ["expense", "Expenses", "What it costs to run."],
  ["owner", "Owner", "Your own money, in or out. Not income and not a cost."],
  ["held", "Held", "Collected for someone else, such as sales tax, until it is paid over."],
];

export function FinanceSettings() {
  const qc = useQueryClient();
  const [said, setSaid] = useState("");
  const accounts = useQuery<FinanceAccount[]>({
    queryKey: ["finance-accounts"],
    queryFn: () => api.get<FinanceAccount[]>("/api/finance-accounts/") });
  const categories = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  const settings = useQuery<{ locked_through: string | null; invoice_income_category: string }>({
    queryKey: ["finance-settings"], queryFn: () => api.get("/api/finance-settings/") });
  const send = useMutation({
    mutationFn: ({ url, body, method }: { url: string; body: object; method?: "patch" }) =>
      method === "patch" ? api.patch<unknown>(url, body) : api.post<unknown>(url, body),
    onSuccess: () => {
      setSaid("");
      for (const key of ["finance-accounts", "finance-categories", "finance-settings",
                         "finance-pnl", "finance-balance"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (e: Error) => setSaid(e.message),
  });
  const busy = send.isPending;
  const cats = categories.data ?? [];

  return (
    <>
      <PageHead title="Finance"
        sub="The accounts your money moves through, the categories your entries sit in, and
             the lock that keeps a period as your CPA was given it." />
      {said && <Banner kind="bad">{said}</Banner>}

      <Card title="Accounts">
        <p className="small muted" style={{ marginTop: 0 }}>
          Each bank account, card or cash float, with what it held (or, for a card, what
          was owed) on the day you start from. An account with entries is closed, never
          deleted.
        </p>
        {(accounts.data ?? []).length > 0 && (
          <table>
            <thead><tr><th>Account</th><th>Kind</th><th>Started</th>
              <th className="money">Opening</th><th /></tr></thead>
            <tbody>
              {(accounts.data ?? []).map((row) => (
                <tr key={row.id}>
                  <td>{row.name}{row.last4 && <span className="muted"> ·· {row.last4}</span>}
                    {row.closed && <> <Pill>closed</Pill></>}</td>
                  <td>{row.kind_label}</td>
                  <td>{longDate(row.opening_on)}</td>
                  <td className="money">{dollars(row.opening_balance_cents)}</td>
                  <td className="money">
                    <button className="ghost small" disabled={busy}
                      aria-label={`${row.closed ? "Reopen" : "Close"} ${row.name}`}
                      onClick={() => send.mutate({ url: `/api/finance-accounts/${row.id}/`,
                                                   body: { closed: !row.closed },
                                                   method: "patch" })}>
                      {row.closed ? "Reopen" : "Close"}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <NewAccount busy={busy} onAdd={(body, added) => send.mutate(
          { url: "/api/finance-accounts/", body }, { onSuccess: added })} />
      </Card>

      <Card title="Categories">
        <p className="small muted" style={{ marginTop: 0 }}>
          The chart you start with is a consulting practice's; change it freely. A category
          with entries is archived, not deleted, and keeps its type. The CPA code is yours
          to fill in if your CPA asks for one; it goes into the export.
        </p>
        {TYPES.map(([type, title, hint]) => (
          <div key={type} style={{ marginBottom: "var(--s4)" }}>
            <h4 style={{ margin: "0 0 2px" }}>{title}</h4>
            <p className="tiny muted" style={{ margin: "0 0 var(--s2)" }}>{hint}</p>
            {cats.filter((c) => c.type === type).map((category) => (
              <CategoryRow key={category.id} category={category} busy={busy}
                paidInvoices={settings.data?.invoice_income_category === category.id}
                onSave={(body) => send.mutate({
                  url: `/api/finance-categories/${category.id}/`, body, method: "patch" })} />
            ))}
            <NewCategory type={type} busy={busy} onAdd={(name, added) => send.mutate(
              { url: "/api/finance-categories/", body: { name, type } },
              { onSuccess: added })} />
          </div>
        ))}
      </Card>

      <Card title="Paid invoices">
        <p className="small muted" style={{ marginTop: 0 }}>
          When you record a payment on an invoice, it is entered as income here. Nothing is
          income before it is paid.
        </p>
        <Field label="Enter them under">
          <select aria-label="Category for paid invoices" disabled={busy}
            value={settings.data?.invoice_income_category ?? ""}
            onChange={(e) => send.mutate({ url: "/api/finance-settings/",
                                           body: { invoice_income_category: e.target.value } })}>
            {cats.filter((c) => c.type === "income" && !c.archived).map(
              (c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
      </Card>

      <Rules />

      <Lock lockedThrough={settings.data?.locked_through ?? null} busy={busy}
        onSet={(locked_through) => send.mutate({ url: "/api/finance-settings/",
                                                 body: { locked_through } })} />
    </>
  );
}

/** The rules remembered from your own choices in an import (§4.4). */
function Rules() {
  const qc = useQueryClient();
  const rules = useQuery<FinanceRule[]>({
    queryKey: ["finance-rules"], queryFn: () => api.get<FinanceRule[]>("/api/finance-rules/") });
  const done = () => qc.invalidateQueries({ queryKey: ["finance-rules"] });
  const toggle = useMutation({
    mutationFn: (rule: FinanceRule) => api.patch<FinanceRule>(
      `/api/finance-rules/${rule.id}/`, { is_active: !rule.is_active }),
    onSuccess: done });
  const remove = useMutation({
    mutationFn: (rule: FinanceRule) => api.del<void>(`/api/finance-rules/${rule.id}/`),
    onSuccess: done });
  const list = rules.data ?? [];
  const busy = toggle.isPending || remove.isPending;
  return (
    <Card title="Import rules">
      <p className="small muted" style={{ marginTop: 0 }}>
        Remembered from your own choices when you import: a line whose description
        contains the text is given the category, marked as a transfer, or ignored. Each is
        shown beside the line it decides, and you can change that line. Nothing here is
        decided by AI.
      </p>
      {list.length === 0 ? <p className="small muted">None yet. Tick "remember" beside a
        line in an import and it appears here.</p> : (
        <table>
          <thead><tr><th>A line containing</th><th>Is</th><th>In</th><th /></tr></thead>
          <tbody>
            {list.map((rule) => (
              <tr key={rule.id}>
                <td>“{rule.contains}”{!rule.is_active && <> <Pill>off</Pill></>}</td>
                <td>{rule.treat_as === "ignore" ? "ignored"
                  : rule.treat_as === "transfer" ? `a transfer, ${rule.other_account?.name}`
                    : rule.category?.name}</td>
                <td>{rule.account?.name ?? "any account"}</td>
                <td className="money">
                  <button className="ghost small" disabled={busy}
                    aria-label={`Turn ${rule.is_active ? "off" : "on"} the rule for ${rule.contains}`}
                    onClick={() => toggle.mutate(rule)}>
                    {rule.is_active ? "Turn off" : "Turn on"}</button>{" "}
                  <button className="ghost small" disabled={busy}
                    aria-label={`Delete the rule for ${rule.contains}`}
                    onClick={() => remove.mutate(rule)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function CategoryRow({ category, busy, paidInvoices, onSave }: {
  category: FinanceCategory; busy: boolean; paidInvoices: boolean;
  onSave: (body: object) => void;
}) {
  const [name, setName] = useState(category.name);
  const [code, setCode] = useState(category.cpa_code);
  useEffect(() => { setName(category.name); setCode(category.cpa_code); },
            [category.name, category.cpa_code]);
  const dirty = name !== category.name || code !== category.cpa_code;
  return (
    <div className="row-actions" style={{ marginBottom: "var(--s1)" }}>
      <div className="row-actions-flags">
        <input aria-label={`Name of ${category.name}`} value={name} maxLength={120}
          disabled={busy || category.archived} style={{ minWidth: "16rem" }}
          onChange={(e) => setName(e.target.value)} />
        <input aria-label={`CPA code of ${category.name}`} value={code} maxLength={40}
          placeholder="CPA code" disabled={busy || category.archived} style={{ width: "8rem" }}
          onChange={(e) => setCode(e.target.value)} />
        {dirty && <button className="primary small" disabled={busy || !name.trim()}
          aria-label={`Save ${category.name}`}
          onClick={() => onSave({ name: name.trim(), cpa_code: code.trim() })}>Save</button>}
        {category.archived && <Pill>archived</Pill>}
        {paidInvoices && <Pill kind="ok">paid invoices go here</Pill>}
      </div>
      <div className="row-actions-cell" /><div className="row-actions-cell" />
      <div className="row-actions-cell">
        {!(category.system && category.type === "held") && !paidInvoices && (
          <button className="ghost small" disabled={busy}
            aria-label={`${category.archived ? "Restore" : "Archive"} ${category.name}`}
            onClick={() => onSave({ archived: !category.archived })}>
            {category.archived ? "Restore" : "Archive"}</button>
        )}
      </div>
    </div>
  );
}

function NewCategory({ type, busy, onAdd }: {
  type: string; busy: boolean; onAdd: (name: string, added: () => void) => void;
}) {
  const [name, setName] = useState("");
  return (
    <div className="row tight" style={{ marginTop: "var(--s2)" }}>
      <input aria-label={`New ${type} category`} value={name} maxLength={120}
        placeholder="Another category" style={{ width: "16rem" }}
        onChange={(e) => setName(e.target.value)} />
      <button className="small" disabled={busy || !name.trim()}
        onClick={() => onAdd(name.trim(), () => setName(""))}>Add</button>
    </div>
  );
}

function NewAccount({ busy, onAdd }: {
  busy: boolean; onAdd: (body: object, added: () => void) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("bank");
  const [last4, setLast4] = useState("");
  const [cents, setCents] = useState(0);
  const [on, setOn] = useState(`${new Date().getFullYear()}-01-01`);
  return (
    <div className="row" style={{ marginTop: "var(--s3)" }}>
      <Field label="Name">
        <input aria-label="Name of the new account" value={name} maxLength={120}
          placeholder="Business checking" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Kind">
        <select aria-label="Kind of the new account" value={kind}
          onChange={(e) => setKind(e.target.value)}>
          <option value="bank">Bank account</option>
          <option value="card">Credit card</option>
          <option value="cash">Cash</option>
        </select>
      </Field>
      <Field label="Last four digits">
        <input aria-label="Last four digits of the new account" value={last4} maxLength={4}
          inputMode="numeric" style={{ width: "6rem" }}
          onChange={(e) => setLast4(e.target.value)} />
      </Field>
      <Field label={kind === "card" ? "Owed on that day" : "Balance on that day"}>
        <PriceBox label="Opening balance of the new account" cents={cents} onChange={setCents} />
      </Field>
      <Field label="Starting from">
        <input type="date" aria-label="Opening date of the new account" value={on}
          onChange={(e) => setOn(e.target.value)} />
      </Field>
      <button disabled={busy || !name.trim()}
        onClick={() => onAdd({ name: name.trim(), kind, last4, opening_balance_cents: cents,
                               opening_on: on },
                             () => { setName(""); setLast4(""); setCents(0); })}>
        Add the account</button>
    </div>
  );
}

function Lock({ lockedThrough, busy, onSet }: {
  lockedThrough: string | null; busy: boolean; onSet: (value: string | null) => void;
}) {
  const [date, setDate] = useState(lockedThrough ?? "");
  useEffect(() => { setDate(lockedThrough ?? ""); }, [lockedThrough]);
  return (
    <Card title="Lock the books">
      <p className="small muted" style={{ marginTop: 0 }}>
        Once a period has gone to your CPA, lock it: nothing dated on or before the lock
        can be added, changed or removed, so the books go on saying what you sent. Moving
        the lock back is recorded.
      </p>
      <p className="small">{lockedThrough
        ? <>The books are locked through <strong>{longDate(lockedThrough)}</strong>.</>
        : "The books are not locked."}</p>
      <div className="row tight">
        <input type="date" aria-label="Lock the books through" value={date}
          max={new Date().toISOString().slice(0, 10)} style={{ width: "auto" }}
          onChange={(e) => setDate(e.target.value)} />
        <button disabled={busy || !date || date === lockedThrough}
          onClick={() => onSet(date)}>Lock through this date</button>
        {lockedThrough && <button className="ghost" disabled={busy}
          onClick={() => {
            if (confirm("Unlock the books? Entries in the locked period can then be "
              + "changed again.")) onSet(null);
          }}>Unlock</button>}
      </div>
    </Card>
  );
}
