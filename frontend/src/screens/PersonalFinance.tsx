import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import {
  FinanceCategory, PersonalAccount, PersonalCategory, PersonalImport, PersonalImportRow,
  PersonalLine, PersonalLines, PersonalReconciliation, SortProposal, SortProposals,
  SortWithClaudeStatus, api,
} from "../lib/api";
import { categoryOptions } from "../lib/finance";
import { dollars, longDate } from "../lib/money";
import { PERSONAL_DISCLAIMER, personalOptions, usePersonalChart } from "../lib/personal";
import { ImportFileStep, StatementRead } from "./FinanceImport";
import { AiGate } from "../components/DemoVisitor";
import { PersonalGoals, PersonalOverview } from "./PersonalBudget";

/**
 * Personal finance (P6 M4 stop 1, `docs/p6_m4_personal_finance.md`): the
 * owner's household money, on its own side of Finance. Theirs alone: the
 * server answers nobody else, in this practice or any other.
 *
 * Stop 1 is sides: Entries (with To sort and Sort these with Claude),
 * Import, Accounts (with an optional reconcile) and Categories. The budget,
 * goals, forecast, debts and taxes come in the later stops.
 */
export type PersonalTab = "overview" | "goals" | "entries" | "import" | "accounts"
  | "categories";

export function PersonalFinance({ tab }: { tab: PersonalTab }) {
  return (
    <div className="personal-side">
      {/* Stop 2: the Overview is the first page of the Personal side. */}
      {tab === "overview" && <PersonalOverview />}
      {tab === "goals" && <PersonalGoals />}
      {tab === "entries" && <PersonalEntries />}
      {tab === "import" && <PersonalImports />}
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
                       "personal-ledger", "personal-imports", "personal-sort-claude",
                       "finance-entries", "finance-pnl", "finance-rules"]) {
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
      api.post("/api/personal/sort", { [body.line.kind]: body.line.id, side: body.side,
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
      {only === "to_sort" && data && data.to_sort > 0 && (
        <SortWithClaude personal={cats} business={books.data ?? []}
          onDone={(text) => done(text)} onError={(text) => setSaid({ kind: "bad", text })} />
      )}
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
                    !line.paid_for && <input type="checkbox" style={{ width: "auto" }}
                      aria-label={`Choose ${line.description}`}
                      checked={picked.includes(line.id)}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, line.id] : picked.filter((id) => id !== line.id))} />)}
                  </td>
                  <td>{longDate(line.on_date)}</td>
                  <td>{line.description}
                    {line.category?.tax_group && <> <Pill>tax-deductible</Pill></>}
                    {line.transfer && <> <Pill>transfer</Pill></>}</td>
                  <td>{line.account?.name ?? ""}
                    {line.from_books && <span className="muted"> · Mixed</span>}</td>
                  <td className="money">{line.direction === "out" ? "−" : "+"}
                    {dollars(line.amount_cents)}</td>
                  <td>{line.kind === "entry" || (line.to_sort && !line.from_books) ? (
                    <WaitingSide line={line} busy={busy} options={options}
                      business={businessFor(line)}
                      onSort={(body) => sort.mutate({ line, ...body })} />
                  ) : line.paid_for ? (
                    <span className="small">
                      <Pill>the practice's: {line.paid_for.category}, paid personally</Pill>{" "}
                      <select aria-label={`Make ${line.description} personal`} value=""
                        disabled={busy} style={{ width: "auto", maxWidth: "14rem" }}
                        onChange={(e) => e.target.value && sort.mutate({
                          line, side: "personal", personal_category: e.target.value })}>
                        <option value="">It was personal…</option>
                        {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
                      </select>
                    </span>
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
  const [reconciling, setReconciling] = useState<PersonalAccount | null>(null);
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
    <>
    {reconciling && <PersonalReconcile account={reconciling}
      onClose={() => setReconciling(null)} />}
    <Card title="Personal: accounts">
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        The household's own accounts, and beside them the practice's accounts you marked
        Mixed: one card for everything, imported once, each line sorted to a side, and
        reconciled with the business month. Only the last four digits are kept.
        Reconciling a personal account is optional.
      </p>
      {rows.length === 0 ? <Empty>No personal accounts yet.</Empty> : (
        <table>
          <thead><tr><th>Account</th><th>Kind</th><th>Side</th>
            <th className="money">Balance</th><th>Reconciled</th><th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.side}-${row.id}`}>
                <td>{row.name}{row.last4 && <span className="muted"> ·· {row.last4}</span>}
                  {row.closed && <> <Pill>closed</Pill></>}</td>
                <td>{row.kind_label}</td>
                <td>{row.side === "mixed"
                  ? <Pill>Mixed, in the practice's books</Pill> : "Personal"}</td>
                <td className="money">{row.balance_cents != null
                  ? `${dollars(row.balance_cents)}${row.kind === "card" ? " owed" : ""}` : ""}</td>
                <td>{row.side === "mixed" ? <span className="muted">with the business month</span>
                  : row.reconciled_through ? `through ${longDate(row.reconciled_through)}`
                    : <span className="muted">not yet</span>}</td>
                <td className="money">{row.side === "personal" && !row.closed && (
                  <button className="ghost small" aria-label={`Reconcile ${row.name}`}
                    onClick={() => setReconciling(row)}>Reconcile</button>)}</td>
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
    </>
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

// ------------------------------------------------- Sort these with Claude

/**
 * Decision 6: one button on To sort, priced before it is pressed. Claude
 * proposes a side and a category for each waiting line; the owner accepts
 * them all or edits first, and each accepted one becomes a rule.
 */
function SortWithClaude({ personal, business, onDone, onError }: {
  personal: PersonalCategory[]; business: FinanceCategory[];
  onDone: (text: string) => void; onError: (text: string) => void;
}) {
  const price = useQuery<SortWithClaudeStatus>({
    queryKey: ["personal-sort-claude"],
    queryFn: () => api.get<SortWithClaudeStatus>("/api/personal/sort-with-claude") });
  const [answer, setAnswer] = useState<SortProposals | null>(null);
  const [rows, setRows] = useState<(SortProposal & { take: boolean })[]>([]);
  const ask = useMutation({
    mutationFn: () => api.post<SortProposals>("/api/personal/sort-with-claude", {}),
    onSuccess: (made) => {
      setAnswer(made);
      setRows(made.proposals.map((p) => ({ ...p, take: true })));
    },
    onError: (e: Error) => onError(e.message),
  });
  const accept = useMutation({
    mutationFn: async () => {
      let n = 0;
      for (const row of rows.filter((r) => r.take)) {
        await api.post("/api/personal/sort", {
          [row.kind]: row.id, side: row.side,
          ...(row.side === "business" ? { category: row.category.id }
            : { personal_category: row.category.id }),
          remember: row.match });
        n += 1;
      }
      return n;
    },
    onSuccess: (n) => {
      setAnswer(null); setRows([]);
      onDone(`${n} line${n === 1 ? "" : "s"} sorted, each remembered as a rule.`);
    },
    onError: (e: Error) => onError(e.message),
  });
  const s = price.data;
  const own = personalOptions(personal);
  const books = categoryOptions(business.filter((c) => !c.archived
    && (c.type === "income" || c.type === "expense")), business);
  const change = (i: number, more: Partial<SortProposal & { take: boolean }>) =>
    setRows(rows.map((row, j) => (j === i ? { ...row, ...more } : row)));
  return (
    <div role="group" aria-label="Sort these with Claude"
      style={{ margin: "var(--s3) 0", padding: "var(--s3)", border: "1px solid var(--line)",
               borderRadius: 8 }}>
      {!answer && s && (
        <>
          <p className="small" style={{ marginTop: 0 }}>
            Claude can propose a side and a category for {s.lines === 1 ? "the line"
              : `the ${Math.min(s.lines, s.most)} lines`} waiting, for about{" "}
            <strong>${Number(s.estimate_usd).toFixed(2)}</strong> of your AI budget. You see
            every proposal before anything changes.
          </p>
          <p className="tiny muted">
            Sent to Anthropic: each line's description as the bank printed it (the
            merchant's name), its amount and which way it went, and the names of your
            categories. Never an account's name or number, a balance, or your name.
            Today: {s.used_today} of {s.cap} Finance AI presses.
          </p>
          {s.refused && <Banner kind="bad">{s.refused}</Banner>}
          <AiGate><button className="primary small" disabled={!!s.refused || ask.isPending}
            onClick={() => ask.mutate()}>
            {ask.isPending ? "Claude is sorting…"
              : `Sort these with Claude, about $${Number(s.estimate_usd).toFixed(2)}`}</button>
          </AiGate>
        </>
      )}
      {answer && (
        <>
          <p className="small" style={{ marginTop: 0 }}>
            Claude proposed {rows.length} of them, for ${Number(answer.cost_usd).toFixed(4)}.
            Untick any you want to sort yourself, change any side or category, then accept.
          </p>
          {rows.length > 0 && (
            <table aria-label="Claude's proposals">
              <thead><tr><th /><th>Line</th><th className="money">Amount</th><th>Side</th>
                <th>Category</th><th>Why</th></tr></thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={`${row.kind}-${row.id}`}>
                    <td><input type="checkbox" checked={row.take} style={{ width: "auto" }}
                      aria-label={`Accept the proposal for ${row.description}`}
                      onChange={(e) => change(i, { take: e.target.checked })} /></td>
                    <td>{row.description}
                      <div className="tiny muted">remembered as “{row.match}”</div></td>
                    <td className="money">{row.direction === "out" ? "−" : "+"}
                      {dollars(row.amount_cents)}</td>
                    <td><select aria-label={`Side proposed for ${row.description}`}
                      value={row.side} style={{ width: "auto" }}
                      onChange={(e) => {
                        const side = e.target.value as "personal" | "business";
                        const first = (side === "personal" ? own : books)[0];
                        change(i, { side, category: { id: first?.[0] ?? "",
                                                      name: first?.[1] ?? "" } });
                      }}>
                      <option value="personal">Personal</option>
                      <option value="business">Business</option>
                    </select></td>
                    <td><select aria-label={`Category proposed for ${row.description}`}
                      value={row.category.id} style={{ width: "auto", maxWidth: "16rem" }}
                      onChange={(e) => change(i, { category: {
                        id: e.target.value,
                        name: e.target.selectedOptions[0]?.text ?? "" } })}>
                      {(row.side === "personal" ? own : books).map(
                        ([id, name]) => <option key={id} value={id}>{name}</option>)}
                    </select></td>
                    <td className="small muted">{row.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row tight" style={{ marginTop: "var(--s2)" }}>
            <button className="primary small"
              disabled={accept.isPending || !rows.some((r) => r.take)}
              onClick={() => accept.mutate()}>
              Accept {rows.filter((r) => r.take).length === rows.length ? "all"
                : rows.filter((r) => r.take).length}</button>
            <button className="ghost small" disabled={accept.isPending}
              onClick={() => { setAnswer(null); setRows([]); }}>Not now</button>
          </div>
          <p className="tiny muted">{answer.disclaimer}</p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Import

/** Decision 3 and the books' three steps, for the household's own accounts. */
function PersonalImports() {
  const refresh = usePersonalRefresh();
  const [batch, setBatch] = useState<PersonalImport | null>(null);
  const [round, setRound] = useState(0);
  const [said, setSaid] = useState<{ kind: string; text: string } | null>(null);
  const accounts = useQuery<PersonalAccount[]>({
    queryKey: ["personal-accounts"],
    queryFn: () => api.get<PersonalAccount[]>("/api/personal/accounts") });
  const history = useQuery<PersonalImport[]>({
    queryKey: ["personal-imports"],
    queryFn: () => api.get<PersonalImport[]>("/api/personal/imports") });
  const fail = (e: Error) => setSaid({ kind: "bad", text: e.message });
  const decide = useMutation({
    mutationFn: ({ row, body }: { row: PersonalImportRow; body: object }) =>
      api.post<PersonalImport>(`/api/personal/imports/${batch!.id}/rows/${row.id}`, body),
    onSuccess: (made) => { setSaid(null); setBatch(made); }, onError: fail,
  });
  const commit = useMutation({
    mutationFn: () => api.post<PersonalImport>(`/api/personal/imports/${batch!.id}/commit`, {}),
    onSuccess: (made) => {
      setSaid({ kind: "ok", text: `Imported ${made.filename} into ${made.account.name}.` });
      setBatch(null); setRound(round + 1); refresh();
    },
    onError: fail,
  });
  const rollback = useMutation({
    mutationFn: (id: string) => api.post<PersonalImport>(
      `/api/personal/imports/${id}/rollback`, {}),
    onSuccess: (made) => {
      const r = made.rolled_back;
      setSaid({ kind: "ok", text: `Rolled back ${made.filename}: ${r?.removed ?? 0} lines `
        + "removed" + (r && r.kept.length ? `. ${r.kept.length} entr${r.kept.length === 1
          ? "y" : "ies"} you had edited in the books since ${r.kept.length === 1 ? "was"
          : "were"} kept: ${r.kept.map((k) => k.description).join(", ")}` : "") + "." });
      refresh();
    },
    onError: fail,
  });
  const own = (accounts.data ?? []).filter((a) => a.side === "personal" && !a.closed);
  const done = (history.data ?? []).filter((b) => b.status !== "dry_run");
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      {!batch && (
        <ImportFileStep<PersonalImport> key={round} accounts={own} pdfKept={false}
          title="Personal: import a statement"
          intro={<>A statement of one of the household's own accounts: a CSV, the bank's
            OFX, QFX or QBO file, or a PDF (read by Claude, priced before it is read). Every
            line is yours unless a rule or you say it was the practice's: then it is in the
            books as paid personally, and stays in this account as "Paid for the practice".
            Lines already in are recognized and left out. A Mixed card is imported on the
            business side, under Finance → Import.</>}
          detectUrl="/api/personal/imports/detect" dryRunUrl="/api/personal/imports/dry-run"
          empty="Add the account first, under Personal → Accounts."
          onBatch={(made) => { setSaid(null); setBatch(made); }}
          onError={(text) => setSaid(text ? { kind: "bad", text } : null)} />
      )}
      {batch && (
        <PersonalDryRun batch={batch} busy={decide.isPending || commit.isPending}
          onDecide={(row, body) => decide.mutate({ row, body })}
          onCommit={() => commit.mutate()} onCancel={() => setBatch(null)} />
      )}
      <Card title="Personal: earlier imports">
        {done.length === 0 ? <Empty>Nothing imported yet.</Empty> : (
          <table>
            <thead><tr><th>File</th><th>Account</th><th>When</th><th>Lines</th><th /></tr></thead>
            <tbody>
              {done.map((b) => (
                <tr key={b.id}>
                  <td>{b.filename}</td><td>{b.account.name}</td>
                  <td>{b.committed_at ? when(b.committed_at) : ""}</td>
                  <td>{(b.counts.new ?? 0) + (b.counts.transfer_match ?? 0)}
                    {b.status === "rolled_back" && <> <Pill>rolled back</Pill></>}</td>
                  <td className="money">{b.status === "committed" && (
                    <button className="ghost small" disabled={rollback.isPending}
                      aria-label={`Roll back the import of ${b.filename}`}
                      onClick={() => {
                        if (confirm(`Roll back ${b.filename}? Its lines leave your ledger, `
                          + "what it put in the books leaves the books, and its transfers "
                          + "are unpaired.")) rollback.mutate(b.id);
                      }}>Roll back</button>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

function PersonalDryRun({ batch, busy, onDecide, onCommit, onCancel }: {
  batch: PersonalImport; busy: boolean;
  onDecide: (row: PersonalImportRow, body: object) => void;
  onCommit: () => void; onCancel: () => void;
}) {
  const chart = usePersonalChart();
  const books = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  const c = batch.counts;
  const writes = (c.new ?? 0) + (c.transfer_match ?? 0);
  return (
    <Card title={`What would happen: ${batch.filename} into ${batch.account.name}`}>
      <Banner kind="info">Nothing has been written to your ledger or the books. This is the
        dry run.</Banner>
      {batch.statement && <StatementRead facts={batch.statement} />}
      <p className="small" aria-label="What the import would do">
        <strong>{writes}</strong> new {writes === 1 ? "line" : "lines"}
        {" · "}<strong>{c.personal ?? 0}</strong> personal
        {" · "}<strong>{(c.business ?? 0) + (c.split ?? 0)}</strong> the practice's, paid
        personally{(c.split ?? 0) > 0 && <> ({c.split} split)</>}
        {" · "}<strong>{c.to_sort ?? 0}</strong> to sort
        {" · "}<strong>{c.transfer_match ?? 0}</strong> the other side of a transfer
        {" · "}<strong>{c.duplicate ?? 0}</strong> already in
        {" · "}<strong>{c.ignore ?? 0}</strong> ignored
        {" · "}<strong>{c.error ?? 0}</strong> that cannot be read
      </p>
      <table>
        <thead><tr><th>Date</th><th>Line</th><th className="money">Amount</th>
          <th>What it is</th></tr></thead>
        <tbody>
          {(batch.rows ?? []).map((row) => (
            <tr key={row.id}>
              <td>{row.on_date ? longDate(row.on_date) : `Line ${row.row_number}`}</td>
              <td>{row.description || (row.raw ? Object.values(row.raw).join(" · ") : "")}</td>
              <td className="money">{row.amount_cents === null ? ""
                : `${row.direction === "out" ? "−" : "+"}${dollars(row.amount_cents)}`}</td>
              <td><PersonalRowChoice row={row} busy={busy}
                personal={chart.data?.categories ?? []} business={books.data ?? []}
                onDecide={(body) => onDecide(row, body)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row tight" style={{ marginTop: "var(--s3)" }}>
        <button className="primary" disabled={busy} onClick={onCommit}>
          Write {writes} {writes === 1 ? "line" : "lines"}</button>
        <button className="ghost" disabled={busy} onClick={onCancel}>Not now</button>
      </div>
    </Card>
  );
}

/** One line of a personal account's statement: personal (in a category, or
 *  To sort), the practice's (paid personally, in a business category), a
 *  split of the two in dollars, a transfer already matched, or ignored. */
function PersonalRowChoice({ row, busy, personal, business, onDecide }: {
  row: PersonalImportRow; busy: boolean; personal: PersonalCategory[];
  business: FinanceCategory[]; onDecide: (body: object) => void;
}) {
  const line = `line ${row.row_number}`;
  const [remember, setRemember] = useState(false);
  const [text, setText] = useState(row.description.split(/\s+/).slice(0, 2).join(" "));
  // A side chosen and waiting for what it needs: a category, or the split.
  const [pending, setPending] = useState<"business" | "split" | null>(null);
  const [biz, setBiz] = useState(row.business_category?.id ?? "");
  const [part, setPart] = useState(row.split_business_cents != null
    ? (row.split_business_cents / 100).toFixed(2) : ((row.amount_cents ?? 0) / 200).toFixed(2));
  const memo = () => (remember && text.trim().length >= 3 ? { remember: text.trim() } : {});
  if (row.outcome === "error") return <span className="small"><Pill kind="bad">cannot be
    read</Pill> {row.error}</span>;
  if (row.outcome === "duplicate") return <Pill>already in</Pill>;
  if (row.outcome === "transfer_match") {
    return (
      <span className="small">
        <Pill kind="ok">the other side of a transfer</Pill>{" "}
        {row.matched && <>{row.matched.description}, {row.matched.account},{" "}
          {longDate(row.matched.on_date)}. Both become Transfers, never spending. </>}
        <button className="link" disabled={busy} aria-label={`Not a match: ${line}`}
          onClick={() => onDecide({ decision: "not_a_match" })}>It is something else</button>
      </span>
    );
  }
  const own = personalOptions(personal, row.direction === "out" ? "expense" : undefined)
    .concat(personalOptions(personal, "transfer"));
  const books = categoryOptions(business.filter((c) => !c.archived
    && c.type === (row.direction === "out" ? "expense" : "income")), business);
  const side = pending ?? (row.outcome === "ignore" ? "ignore" : row.side);
  const cents = Math.round(Number(part) * 100);
  return (
    <span className="small" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      <select aria-label={`Side of ${line}`} value={side} disabled={busy}
        style={{ width: "auto" }}
        onChange={(e) => {
          const to = e.target.value;
          if (to === "business" || to === "split") { setPending(to); return; }
          setPending(null);
          onDecide(to === "ignore" ? { decision: "ignore" } : { decision: "line", side: to });
        }}>
        <option value="personal">Personal</option>
        <option value="business">The practice's</option>
        <option value="split">Split</option>
        <option value="to_sort">To sort later</option>
        <option value="ignore">Ignore this line</option>
      </select>
      {(side === "business" || side === "split") && (
        <select aria-label={`The practice's category for ${line}`} disabled={busy}
          value={biz} style={{ width: "auto", maxWidth: "16rem" }}
          onChange={(e) => {
            setBiz(e.target.value);
            if (e.target.value && side === "business") {
              setPending(null);
              onDecide({ decision: "line", side: "business",
                         business_category: e.target.value, ...memo() });
            } else if (e.target.value && row.side === "split" && pending === null) {
              onDecide({ decision: "line", side: "split", business_category: e.target.value,
                         category: row.category?.id ?? null,
                         split_business_cents: row.split_business_cents });
            }
          }}>
          <option value="">Choose a category</option>
          {books.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      )}
      {pending === "split" && (
        <span role="group" aria-label={`Split ${line}`}
          style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input aria-label={`The practice's part of ${line}, in dollars`} inputMode="decimal"
            value={part} style={{ width: "6rem" }} onChange={(e) => setPart(e.target.value)} />
          <button className="small primary"
            disabled={busy || !biz || !(cents > 0 && cents < (row.amount_cents ?? 0))}
            onClick={() => {
              setPending(null);
              onDecide({ decision: "line", side: "split", split_business_cents: cents,
                         business_category: biz, category: row.category?.id ?? null,
                         ...memo() });
            }}>Split it</button>
        </span>
      )}
      {(side === "personal" || (side === "split" && pending === null)) && (
        <select aria-label={`Personal category for ${line}`} disabled={busy}
          value={row.category?.id ?? ""} style={{ width: "auto", maxWidth: "16rem" }}
          onChange={(e) => onDecide({
            decision: "line", side: row.side === "split" ? "split" : "personal",
            category: e.target.value || null,
            business_category: row.business_category?.id ?? null,
            split_business_cents: row.split_business_cents,
            ...(e.target.value ? memo() : {}) })}>
          <option value="">No category yet (To sort)</option>
          {own.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      )}
      {side === "business" && pending === null && <Pill>in the books as paid personally</Pill>}
      {row.side === "split" && pending === null && row.split_business_cents != null
        && row.amount_cents != null && (
        <Pill>{dollars(row.split_business_cents)} the practice's,{" "}
          {dollars(row.amount_cents - row.split_business_cents)} yours</Pill>)}
      {side === "to_sort" && <Pill>waits in Personal → To sort</Pill>}
      {row.rule ? <Pill>your rule: contains “{row.rule.contains}”</Pill> : side !== "ignore" && (
        <label className="tiny" style={{ display: "inline-flex", gap: 4 }}>
          <input type="checkbox" checked={remember} aria-label={`Remember for ${line}`}
            onChange={(e) => setRemember(e.target.checked)} />
          remember for lines containing
          {remember && <input aria-label={`Text to remember for ${line}`} value={text}
            style={{ width: "10rem" }} onChange={(e) => setText(e.target.value)} />}
        </label>
      )}
    </span>
  );
}

// ------------------------------------------------------------- Reconcile

/** Decision 8: optional on a personal account, and no month close. */
function PersonalReconcile({ account, onClose }: {
  account: PersonalAccount; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [said, setSaid] = useState("");
  const [form, setForm] = useState({ on: "", balance: "" });
  const list = useQuery<PersonalReconciliation[]>({
    queryKey: ["personal-reconciliations", account.id],
    queryFn: () => api.get<PersonalReconciliation[]>(
      `/api/personal/accounts/${account.id}/reconciliations`) });
  const going = (list.data ?? []).find((r) => r.state === "open");
  const detail = useQuery<PersonalReconciliation>({
    queryKey: ["personal-reconciliation", going?.id], enabled: !!going,
    queryFn: () => api.get<PersonalReconciliation>(`/api/personal/reconciliations/${going!.id}`) });
  const after = () => {
    setSaid("");
    for (const key of ["personal-reconciliations", "personal-reconciliation",
                       "personal-accounts"]) qc.invalidateQueries({ queryKey: [key] });
  };
  const fail = (e: Error) => setSaid(e.message);
  const start = useMutation({
    mutationFn: () => api.post(`/api/personal/accounts/${account.id}/reconciliations`, {
      statement_on: form.on, statement_balance_cents: Math.round(Number(form.balance) * 100) }),
    onSuccess: after, onError: fail });
  const step = useMutation({
    mutationFn: ({ url, body }: { url: string; body: object }) => api.post(url, body),
    onSuccess: after, onError: fail });
  const discard = useMutation({
    mutationFn: (id: string) => api.del(`/api/personal/reconciliations/${id}`),
    onSuccess: after, onError: fail });
  const rec = detail.data;
  const finished = (list.data ?? []).filter((r) => r.state === "finished");
  return (
    <Card title={`Personal: reconcile ${account.name}`}
      actions={<button className="ghost small" onClick={onClose}>Close</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Optional, and there is no month close on the personal side: tick each line the
        statement shows until the difference is zero, and the balance the forecast starts
        from is the bank's.
      </p>
      {said && <Banner kind="bad">{said}</Banner>}
      {!going && (
        <div className="row">
          <Field label="Statement ending date">
            <input type="date" aria-label="Statement ending date" value={form.on}
              onChange={(e) => setForm({ ...form, on: e.target.value })} />
          </Field>
          <Field label={account.kind === "card" ? "What the statement says is owed"
            : "Statement ending balance"}>
            <input aria-label="Statement ending balance" inputMode="decimal" value={form.balance}
              style={{ width: "9rem" }} onChange={(e) => setForm({ ...form, balance: e.target.value })} />
          </Field>
          <button className="primary" disabled={!form.on || form.balance === "" || start.isPending}
            onClick={() => start.mutate()}>Start</button>
        </div>
      )}
      {rec && (
        <>
          <p className="small" aria-label="Where the statement stands">
            Statement of {longDate(rec.statement_on)}: {dollars(rec.statement_balance_cents)}.
            Starting balance {dollars(rec.starting_balance_cents)}, ticked in{" "}
            {dollars(rec.cleared_in_cents)}, ticked out {dollars(rec.cleared_out_cents)}.{" "}
            <strong>Difference {dollars(rec.difference_cents)}</strong>
          </p>
          <table>
            <thead><tr><th /><th>Date</th><th>Line</th><th className="money">Amount</th></tr></thead>
            <tbody>
              {(rec.lines ?? []).map((line) => (
                <tr key={line.id}>
                  <td><input type="checkbox" checked={line.cleared} style={{ width: "auto" }}
                    aria-label={`Ticked: ${line.description}, ${longDate(line.on_date)}`}
                    disabled={step.isPending}
                    onChange={(e) => step.mutate({
                      url: `/api/personal/reconciliations/${rec.id}/tick`,
                      body: { lines: [line.id], cleared: e.target.checked } })} /></td>
                  <td>{longDate(line.on_date)}</td><td>{line.description}</td>
                  <td className="money">{line.direction === "out" ? "−" : "+"}
                    {dollars(line.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row tight" style={{ marginTop: "var(--s3)" }}>
            <button className="small" disabled={step.isPending}
              onClick={() => step.mutate({ url: `/api/personal/reconciliations/${rec.id}/tick`,
                body: { lines: (rec.lines ?? []).map((l) => l.id), cleared: true } })}>
              Tick them all</button>
            <button className="primary small" disabled={rec.difference_cents !== 0
              || step.isPending}
              onClick={() => step.mutate({ url: `/api/personal/reconciliations/${rec.id}/finish`,
                                           body: {} })}>Finish</button>
            <button className="ghost small" disabled={discard.isPending}
              onClick={() => discard.mutate(rec.id)}>Throw this one away</button>
          </div>
        </>
      )}
      {finished.length > 0 && (
        <p className="small muted">Reconciled: {finished.map((r) => longDate(r.statement_on))
          .join(", ")}.{" "}
          <button className="link" disabled={step.isPending || !!going}
            onClick={() => step.mutate({
              url: `/api/personal/reconciliations/${finished[0].id}/reopen`, body: {} })}>
            Reopen the last one</button></p>
      )}
    </Card>
  );
}
