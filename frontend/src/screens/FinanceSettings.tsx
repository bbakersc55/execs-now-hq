import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { FinanceCategories } from "../components/FinanceCategories";
import { FinanceDisclaimer } from "../components/FinanceDisclaimer";
import { PriceBox } from "../components/InvoiceLines";
import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill } from "../components/ui";
import { FinanceAccount, FinanceCategory, FinanceRule, Me, api } from "../lib/api";
import { categoryOptions } from "../lib/finance";
import { dollars, longDate } from "../lib/money";

/**
 * Settings → Finance (P5; matrix 13.7): the practice owner's. The accounts
 * money moves through, the categories entries sit in, where a paid invoice is
 * entered, and the lock that keeps a period as the CPA was given it.
 */

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
  // P6 M1: the tools that reshape the chart are the Bookkeeping module's.
  const me = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const bookkeeping = (me.data?.modules ?? []).includes("bookkeeping");
  const send = useMutation({
    mutationFn: ({ url, body, method }: { url: string; body: object;
                                          method?: "patch" | "delete" }) =>
      method === "patch" ? api.patch<unknown>(url, body)
        : method === "delete" ? api.del<unknown>(url) : api.post<unknown>(url, body),
    onSuccess: () => {
      setSaid("");
      for (const key of ["finance-accounts", "finance-categories", "finance-settings",
                         "finance-pnl", "finance-balance", "finance-starting-chart"]) {
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

      <FinanceCategories categories={cats} bookkeeping={bookkeeping} busy={busy}
        paidInvoicesId={settings.data?.invoice_income_category ?? ""}
        send={(call, after) => send.mutate(call, after ? { onSuccess: after } : undefined)} />

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
            {categoryOptions(cats.filter((c) => c.type === "income" && !c.archived), cats)
              .map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </Field>
      </Card>

      <Rules />

      <Lock lockedThrough={settings.data?.locked_through ?? null} busy={busy}
        onSet={(locked_through) => send.mutate({ url: "/api/finance-settings/",
                                                 body: { locked_through } })} />
      <FinanceDisclaimer />
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
