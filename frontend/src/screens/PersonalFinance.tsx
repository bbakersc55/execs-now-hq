import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  FinanceCategory, PersonalAccount, PersonalLine, PersonalLines, api,
} from "../lib/api";
import { categoryOptions } from "../lib/finance";
import { dollars, longDate } from "../lib/money";
import { PERSONAL_DISCLAIMER, personalOptions, usePersonalChart } from "../lib/personal";

/**
 * Personal finance (P6 M4 stop 1, `docs/p6_m4_personal_finance.md`): the
 * owner's household money, on its own side of Finance. Theirs alone: the
 * server answers nobody else, in this practice or any other.
 *
 * Stop 1 is sides: Entries (with To sort), Accounts and Categories. The
 * budget, goals, forecast, debts and taxes come in the later stops.
 */
export type PersonalTab = "entries" | "accounts" | "categories";

export function PersonalFinance({ tab }: { tab: PersonalTab }) {
  return (
    <div className="personal-side">
      {tab === "entries" && <PersonalEntries />}
      {tab === "accounts" && <PersonalAccounts />}
      {tab === "categories" && <PersonalCategories />}
      <p className="tiny muted" role="note" style={{ marginTop: "var(--s4)" }}>
        {PERSONAL_DISCLAIMER}</p>
    </div>
  );
}

function usePersonalRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["personal-lines", "personal-accounts", "personal-categories",
                       "personal-ledger", "finance-entries", "finance-pnl", "finance-rules"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

// --------------------------------------------------------------- Entries

function PersonalEntries() {
  const [only, setOnly] = useState<"all" | "to_sort">("all");
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const [learn, setLearn] = useState(true);
  const [picked, setPicked] = useState<string[]>([]);
  const [bulkTo, setBulkTo] = useState("");
  const refresh = usePersonalRefresh();
  const chart = usePersonalChart();
  const books = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  const list = useQuery<PersonalLines>({
    queryKey: ["personal-lines", only],
    queryFn: () => api.get<PersonalLines>(
      `/api/personal/lines${only === "to_sort" ? "?to_sort=1" : ""}`) });
  const done = (text: string) => { setSaid({ kind: "ok", text }); refresh(); };
  const fail = (e: Error) => setSaid({ kind: "bad", text: e.message });
  const memo = (line: PersonalLine) => (learn
    ? { remember: line.description.split(/\s+/).slice(0, 2).join(" ") } : {});
  const recategorize = useMutation({
    mutationFn: ({ line, category }: { line: PersonalLine; category: string }) =>
      api.patch(`/api/personal/lines/${line.id}`, { category: category || null,
                                                     ...(category ? memo(line) : {}) }),
    onSuccess: () => done("Saved."), onError: fail,
  });
  const sort = useMutation({
    mutationFn: (body: { line: PersonalLine; side: string; category?: string;
                         personal_category?: string }) =>
      api.post("/api/personal/sort", { entry: body.line.id, side: body.side,
                                       category: body.category || null,
                                       personal_category: body.personal_category || null,
                                       ...memo(body.line) }),
    onSuccess: () => done("Sorted."), onError: fail,
  });
  const bulk = useMutation({
    mutationFn: () => api.post<{ updated: number }>("/api/personal/lines/bulk",
                                                     { lines: picked, category: bulkTo }),
    onSuccess: (r) => { setPicked([]); done(`${r.updated} line(s) moved.`); },
    onError: fail,
  });
  const cats = chart.data?.categories ?? [];
  const options = personalOptions(cats);
  const data = list.data;
  const busy = recategorize.isPending || sort.isPending || bulk.isPending;
  const businessFor = (line: PersonalLine) => categoryOptions(
    (books.data ?? []).filter((c) => !c.archived
      && c.type === (line.direction === "out" ? "expense" : "income")), books.data ?? []);

  return (
    <Card title={only === "to_sort" ? "Personal: to sort" : "Personal: entries"}
      actions={<div className="row tight" role="group" aria-label="Which lines">
        <button className={only === "all" ? "small primary" : "small"}
          aria-pressed={only === "all"} onClick={() => setOnly("all")}>All</button>
        <button className={only === "to_sort" ? "small primary" : "small"}
          aria-pressed={only === "to_sort"} onClick={() => setOnly("to_sort")}>
          To sort{data ? ` (${data.to_sort})` : ""}</button>
      </div>}>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        The household's spending and income: from your personal accounts, and the personal
        side of lines in a Mixed account (in the books, those are owner draws). A line with
        no rule under {data ? dollars(data.threshold_cents) : "the threshold"} goes to
        Everything else without asking; larger ones wait in To sort.
      </p>
      <label className="small" style={{ display: "inline-flex", gap: 6 }}>
        <input type="checkbox" checked={learn} style={{ width: "auto" }}
          aria-label="Remember my choices for lines like these"
          onChange={(e) => setLearn(e.target.checked)} />
        Remember each choice for lines like it (a rule, by the line's first words)
      </label>
      {!data ? <p>Loading…</p> : data.lines.length === 0 ? (
        <Empty>{only === "to_sort" ? "Nothing to sort." : "No personal lines yet. Mark a "
          + "card Mixed under Settings → Finance and import it, or add a personal account."}
        </Empty>
      ) : (
        <>
          <table>
            <thead><tr><th /><th>Date</th><th>Line</th><th>Account</th>
              <th className="money">Amount</th><th>Category</th></tr></thead>
            <tbody>
              {data.lines.map((line) => (
                <tr key={`${line.kind}-${line.id}`}>
                  <td>{line.kind === "line" && (
                    <input type="checkbox" style={{ width: "auto" }}
                      aria-label={`Choose ${line.description}`}
                      checked={picked.includes(line.id)}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, line.id] : picked.filter((id) => id !== line.id))} />)}
                  </td>
                  <td>{longDate(line.on_date)}</td>
                  <td>{line.description}
                    {line.category?.tax_group && <> <Pill>tax-deductible</Pill></>}</td>
                  <td>{line.account?.name ?? ""}
                    {line.from_books && <span className="muted"> · Mixed</span>}</td>
                  <td className="money">{line.direction === "out" ? "−" : "+"}
                    {dollars(line.amount_cents)}</td>
                  <td>{line.kind === "entry" ? (
                    <WaitingSide line={line} busy={busy} options={options}
                      business={businessFor(line)}
                      onSort={(body) => sort.mutate({ line, ...body })} />
                  ) : (
                    <select aria-label={`Category for ${line.description}`}
                      value={line.category?.id ?? ""} disabled={busy}
                      style={{ width: "auto", maxWidth: "18rem" }}
                      onChange={(e) => recategorize.mutate({ line, category: e.target.value })}>
                      <option value="">To sort</option>
                      {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
                    </select>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {picked.length > 0 && (
            <div className="row tight" style={{ marginTop: "var(--s3)" }}>
              <span className="small">{picked.length} chosen. Move them to</span>
              <select aria-label="Move the chosen lines to" value={bulkTo}
                style={{ width: "auto" }} onChange={(e) => setBulkTo(e.target.value)}>
                <option value="">Choose a category</option>
                {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
              <button className="primary small" disabled={!bulkTo || busy}
                onClick={() => bulk.mutate()}>Move</button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** A Mixed account's line no rule placed: which side, and where on it. */
function WaitingSide({ line, busy, options, business, onSort }: {
  line: PersonalLine; busy: boolean; options: [string, string][];
  business: [string, string][];
  onSort: (body: { side: string; category?: string; personal_category?: string }) => void;
}) {
  const [side, setSide] = useState<"" | "personal" | "business">("");
  return (
    <span className="small" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      <select aria-label={`Side of ${line.description}`} value={side} disabled={busy}
        style={{ width: "auto" }}
        onChange={(e) => setSide(e.target.value as "" | "personal" | "business")}>
        <option value="">Which side?</option>
        <option value="personal">Personal</option>
        <option value="business">Business</option>
      </select>
      {side === "personal" && (
        <select aria-label={`Personal category for ${line.description}`} disabled={busy}
          defaultValue="" style={{ width: "auto", maxWidth: "16rem" }}
          onChange={(e) => e.target.value
            && onSort({ side: "personal", personal_category: e.target.value })}>
          <option value="">Choose a category</option>
          {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      )}
      {side === "business" && (
        <select aria-label={`Business category for ${line.description}`} disabled={busy}
          defaultValue="" style={{ width: "auto", maxWidth: "16rem" }}
          onChange={(e) => e.target.value
            && onSort({ side: "business", category: e.target.value })}>
          <option value="">Choose a category</option>
          {business.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      )}
    </span>
  );
}

// -------------------------------------------------------------- Accounts

function PersonalAccounts() {
  const refresh = usePersonalRefresh();
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const [form, setForm] = useState({ name: "", kind: "bank", last4: "",
                                     opening: "", opening_on: "" });
  const list = useQuery<PersonalAccount[]>({
    queryKey: ["personal-accounts"],
    queryFn: () => api.get<PersonalAccount[]>("/api/personal/accounts") });
  const add = useMutation({
    mutationFn: () => api.post("/api/personal/accounts", {
      name: form.name, kind: form.kind, last4: form.last4,
      opening_balance_cents: Math.round(Number(form.opening || 0) * 100),
      ...(form.opening_on ? { opening_on: form.opening_on } : {}) }),
    onSuccess: () => {
      setForm({ name: "", kind: "bank", last4: "", opening: "", opening_on: "" });
      setSaid({ kind: "ok", text: "Added." }); refresh();
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }),
  });
  const rows = list.data ?? [];
  return (
    <Card title="Personal: accounts">
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        The household's own accounts, and beside them the practice's accounts you marked
        Mixed: one card for everything, imported once, each line sorted to a side. Only the
        last four digits are kept. Importing a statement into a personal account comes in
        the next round.
      </p>
      {rows.length === 0 ? <Empty>No personal accounts yet.</Empty> : (
        <table>
          <thead><tr><th>Account</th><th>Kind</th><th>Side</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.side}-${row.id}`}>
                <td>{row.name}{row.last4 && <span className="muted"> ·· {row.last4}</span>}
                  {row.closed && <> <Pill>closed</Pill></>}</td>
                <td>{row.kind_label}</td>
                <td>{row.side === "mixed"
                  ? <Pill>Mixed, in the practice's books</Pill> : "Personal"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row" style={{ marginTop: "var(--s3)" }}>
        <Field label="Name">
          <input aria-label="Personal account name" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Kind">
          <select aria-label="Personal account kind" value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="bank">Bank account</option>
            <option value="card">Credit card</option>
            <option value="cash">Cash</option>
          </select>
        </Field>
        <Field label="Last four digits">
          <input aria-label="Personal account last four" value={form.last4} maxLength={4}
            style={{ width: "6rem" }} onChange={(e) => setForm({ ...form, last4: e.target.value })} />
        </Field>
        <Field label="Opening balance">
          <input aria-label="Personal account opening balance" value={form.opening}
            inputMode="decimal" style={{ width: "8rem" }}
            onChange={(e) => setForm({ ...form, opening: e.target.value })} />
        </Field>
        <Field label="On">
          <input type="date" aria-label="Personal account opening date" value={form.opening_on}
            onChange={(e) => setForm({ ...form, opening_on: e.target.value })} />
        </Field>
        <button className="primary" disabled={!form.name.trim() || add.isPending}
          onClick={() => add.mutate()}>Add the account</button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------ Categories

function PersonalCategories() {
  const qc = useQueryClient();
  const chart = usePersonalChart();
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const [adding, setAdding] = useState({ name: "", parent: "" });
  const ledger = useQuery<{ to_sort_threshold_cents: number }>({
    queryKey: ["personal-ledger"],
    queryFn: () => api.get("/api/personal/ledger") });
  const [threshold, setThreshold] = useState("");
  const after = (text: string) => {
    setSaid({ kind: "ok", text });
    qc.invalidateQueries({ queryKey: ["personal-categories"] });
    qc.invalidateQueries({ queryKey: ["personal-ledger"] });
  };
  const fail = (e: Error) => setSaid({ kind: "bad", text: e.message });
  const change = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api.patch(`/api/personal/categories/${id}`, body),
    onSuccess: () => after("Saved."), onError: fail,
  });
  const add = useMutation({
    mutationFn: () => api.post("/api/personal/categories", {
      name: adding.name, ...(adding.parent ? { parent: adding.parent } : {}) }),
    onSuccess: () => { setAdding({ name: "", parent: "" }); after("Added."); },
    onError: fail,
  });
  const setLimit = useMutation({
    mutationFn: () => api.patch("/api/personal/ledger", {
      to_sort_threshold_cents: Math.round(Number(threshold) * 100) }),
    onSuccess: () => { setThreshold(""); after("Saved."); }, onError: fail,
  });
  const cats = chart.data?.categories ?? [];
  const groups = chart.data?.tax_groups ?? [];
  const tops = cats.filter((c) => !c.parent);
  const busy = change.isPending || add.isPending;
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <Card title="Personal: sorting">
        <p className="small" style={{ marginTop: 0 }}>
          A line with no rule under{" "}
          <strong>{ledger.data ? dollars(ledger.data.to_sort_threshold_cents) : "…"}</strong>
          {" "}goes to Everything else without asking; at or over it, it waits in To sort.
        </p>
        <div className="row tight">
          <input aria-label="Threshold in dollars" inputMode="decimal" placeholder="25.00"
            value={threshold} style={{ width: "8rem" }}
            onChange={(e) => setThreshold(e.target.value)} />
          <button className="small" disabled={!threshold || setLimit.isPending}
            onClick={() => setLimit.mutate()}>Set the threshold</button>
        </div>
      </Card>
      <Card title="Personal: categories">
        <p className="small muted" style={{ marginTop: 0 }}>
          Separate from the practice's chart. A category marked tax-deductible names its
          group on your CPA's Itemized Deduction Worksheet, so year-end itemizing is a
          filter. Whether an item is deductible is your CPA's call.
        </p>
        <table>
          <thead><tr><th>Category</th><th>Tax-deductible</th><th /></tr></thead>
          <tbody>
            {tops.flatMap((top) => [top, ...cats.filter((c) => c.parent === top.id)]).map(
              (row) => (
                <tr key={row.id}>
                  <td style={{ paddingLeft: row.parent ? "2rem" : undefined }}>
                    {row.parent ? row.name : <strong>{row.name}</strong>}
                    {row.type !== "expense" && !row.parent
                      && <span className="muted"> · {row.type === "income" ? "income"
                        : "not spending"}</span>}</td>
                  <td>{row.type === "expense" && (
                    <select aria-label={`Tax-deductible group for ${row.name}`}
                      value={row.tax_group} disabled={busy} style={{ width: "auto" }}
                      onChange={(e) => change.mutate({ id: row.id,
                                                       body: { tax_group: e.target.value } })}>
                      <option value="">Not marked</option>
                      {groups.map((g) => <option key={g.code} value={g.code}>{g.label}</option>)}
                    </select>)}</td>
                  <td className="money">{!row.system && (
                    <button className="ghost small" disabled={busy}
                      aria-label={`Archive ${row.name}`}
                      onClick={() => change.mutate({ id: row.id, body: { archived: true } })}>
                      Archive</button>)}</td>
                </tr>
              ))}
          </tbody>
        </table>
        <div className="row tight" style={{ marginTop: "var(--s3)" }}>
          <input aria-label="New personal category" placeholder="A new category"
            value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
          <select aria-label="Under" value={adding.parent} style={{ width: "auto" }}
            onChange={(e) => setAdding({ ...adding, parent: e.target.value })}>
            <option value="">At the top</option>
            {tops.map((t) => <option key={t.id} value={t.id}>Under {t.name}</option>)}
          </select>
          <button className="small" disabled={!adding.name.trim() || busy}
            onClick={() => add.mutate()}>Add</button>
        </div>
      </Card>
    </>
  );
}
