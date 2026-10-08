import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import {
  FinanceAccount, FinanceCategory, BankImportBatch, ImportDetected, ImportMapping, BankImportRow,
  PayeeReport, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * Importing a bank or card export (P5 §4; matrix 13.8), in the contact
 * import's three steps: map the columns, a dry run, commit.
 *
 * **The dry run writes nothing to the books.** Each line is shown with what
 * will happen to it; the owner gives it a category, marks a transfer, or
 * accepts or declines a proposed match. A committed import can be rolled back.
 */

const SOURCES: [keyof ImportMapping, string, boolean][] = [
  ["date", "Date", true], ["description", "Description", true],
  ["amount", "Amount (one column)", false], ["debit", "Money out (its own column)", false],
  ["credit", "Money in (its own column)", false], ["balance", "Running balance", false],
  ["reference", "Check or reference number", false],
  ["bank_id", "The bank's own id for the line", false],
];

export function FinanceImport({ accounts, categories }: {
  accounts: FinanceAccount[]; categories: FinanceCategory[];
}) {
  const qc = useQueryClient();
  const [account, setAccount] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [detected, setDetected] = useState<ImportDetected | null>(null);
  const [mapping, setMapping] = useState<ImportMapping | null>(null);
  const [batch, setBatch] = useState<BankImportBatch | null>(null);
  const [said, setSaid] = useState("");
  const [done, setDone] = useState("");
  const history = useQuery<BankImportBatch[]>({
    queryKey: ["finance-imports"],
    queryFn: () => api.get<BankImportBatch[]>("/api/finance-imports/") });
  const payees = useQuery<PayeeReport>({
    queryKey: ["finance-payees", "list"],
    queryFn: () => api.get<PayeeReport>("/api/finance-payees/") });
  const open = accounts.filter((a) => !a.closed);
  const refreshBooks = () => {
    for (const key of ["finance-imports", "finance-entries", "finance-pnl",
                       "finance-balance", "finance-rules", "finance-payees"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const form = (extra: Record<string, string> = {}) => {
    const body = new FormData();
    body.append("file", file as File);
    body.append("account", account);
    for (const [key, value] of Object.entries(extra)) body.append(key, value);
    return body;
  };
  const fail = (e: Error) => setSaid(e.message);
  const detect = useMutation({
    mutationFn: () => api.post<ImportDetected>("/api/finance-imports/detect/", form()),
    onSuccess: (found) => { setSaid(""); setDetected(found); setMapping(found.mapping); },
    onError: fail,
  });
  const dryRun = useMutation({
    mutationFn: () => api.post<BankImportBatch>("/api/finance-imports/dry-run/",
                                            form({ mapping: JSON.stringify(mapping) })),
    onSuccess: (made) => { setSaid(""); setBatch(made); },
    onError: fail,
  });
  const decide = useMutation({
    mutationFn: ({ row, body }: { row: BankImportRow; body: object }) => api.post<BankImportBatch>(
      `/api/finance-imports/${batch!.id}/rows/${row.id}/`, body),
    onSuccess: (made) => { setSaid(""); setBatch(made); },
    onError: fail,
  });
  const commit = useMutation({
    mutationFn: () => api.post<BankImportBatch>(`/api/finance-imports/${batch!.id}/commit/`, {}),
    onSuccess: (made) => {
      setSaid("");
      setDone(`Imported ${made.filename} into ${made.account.name}.`);
      setBatch(null); setDetected(null); setMapping(null); setFile(null);
      refreshBooks();
    },
    onError: fail,
  });
  const rollback = useMutation({
    mutationFn: (id: string) => api.post<BankImportBatch>(`/api/finance-imports/${id}/rollback/`, {}),
    onSuccess: (made) => {
      const r = made.rolled_back;
      setSaid("");
      setDone(`Rolled back ${made.filename}: ${r?.removed ?? 0} entries removed`
        + (r && r.unmatched ? `, ${r.unmatched} invoice payments unplaced again` : "")
        + (r && r.kept.length ? `. ${r.kept.length} you had edited since `
          + `${r.kept.length === 1 ? "was" : "were"} kept: `
          + r.kept.map((k) => `${k.description} (${dollars(k.amount_cents)})`).join(", ") : "")
        + ".");
      refreshBooks();
    },
    onError: fail,
  });

  return (
    <>
      {said && <Banner kind="bad">{said}</Banner>}
      {done && <Banner kind="ok">{done}</Banner>}

      {!batch && (
        <Card title="1. The file, and which column is which">
          <p className="small muted" style={{ marginTop: 0 }}>
            Download a CSV from your bank or card's website and choose the account it is
            for. Downloading an overlapping range each month is fine: lines already in the
            books are recognized and left out.
          </p>
          {open.length === 0 ? <Empty>Add the account this file is for first, in Accounts
            and categories.</Empty> : (
            <div className="row">
              <Field label="Account">
                <select aria-label="Account to import into" value={account}
                  onChange={(e) => { setAccount(e.target.value); setDetected(null); }}>
                  <option value="">Choose an account</option>
                  {open.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </Field>
              <Field label="The CSV file">
                <input type="file" accept=".csv,text/csv" aria-label="The CSV file"
                  onChange={(e) => { setFile(e.target.files?.[0] ?? null); setDetected(null); }} />
              </Field>
              <button disabled={!account || !file || detect.isPending}
                onClick={() => detect.mutate()}>Read the file</button>
            </div>
          )}
          {detected && mapping && (
            <>
              <p className="small">{detected.lines} lines.{" "}
                {detected.from_saved ? "Using the columns you chose last time for this account."
                  : "This is a first guess from the column names: check it."}</p>
              <div className="row">
                {SOURCES.map(([key, label, required]) => (
                  <Field key={key} label={label}>
                    <select aria-label={`Column for: ${label}`} value={mapping[key]}
                      onChange={(e) => setMapping({ ...mapping, [key]: e.target.value })}>
                      <option value="">{required ? "Choose a column" : "None"}</option>
                      {detected.header.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                  </Field>
                ))}
              </div>
              <div className="row">
                <Field label="How the dates are written">
                  <select aria-label="Date format" value={mapping.date_format}
                    onChange={(e) => setMapping({ ...mapping, date_format: e.target.value })}>
                    {detected.date_formats.map((f) => (
                      <option key={f.value} value={f.value}>{f.label}</option>))}
                  </select>
                </Field>
                {mapping.amount && (
                  <Field label="In the amount column">
                    <select aria-label="Sign of the amount" value={mapping.sign}
                      onChange={(e) => setMapping({ ...mapping, sign: e.target.value })}>
                      <option value="negative_is_out">A negative number is money out</option>
                      <option value="positive_is_out">A positive number is money out
                        (most card files)</option>
                    </select>
                  </Field>
                )}
              </div>
              <table aria-label="The first lines of the file">
                <thead><tr>{detected.header.map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{detected.sample.map((line, i) => (
                  <tr key={i}>{detected.header.map((h) => <td key={h}>{line[h]}</td>)}</tr>
                ))}</tbody>
              </table>
              <p><button className="primary" disabled={dryRun.isPending
                || !mapping.date || !mapping.description
                || !(mapping.amount || mapping.debit || mapping.credit)}
                onClick={() => dryRun.mutate()}>
                {dryRun.isPending ? "Reading every line…" : "Show me what would happen"}
              </button></p>
            </>
          )}
        </Card>
      )}

      {batch && (
        <DryRun batch={batch} accounts={open} categories={categories}
          payees={(payees.data?.payees ?? []).filter((p) => p.is_payee)}
          busy={decide.isPending || commit.isPending}
          onDecide={(row, body) => decide.mutate({ row, body })}
          onCommit={() => commit.mutate()}
          onCancel={() => { setBatch(null); setSaid(""); }} />
      )}

      <Card title="Earlier imports">
        {(history.data ?? []).filter((b) => b.status !== "dry_run").length === 0
          ? <Empty>Nothing imported yet.</Empty> : (
            <table>
              <thead><tr><th>File</th><th>Account</th><th>When</th><th>Entries made</th>
                <th /></tr></thead>
              <tbody>
                {(history.data ?? []).filter((b) => b.status !== "dry_run").map((b) => (
                  <tr key={b.id}>
                    <td>{b.filename}</td><td>{b.account.name}</td>
                    <td>{b.committed_at ? when(b.committed_at) : ""}</td>
                    <td>{(b.counts.new ?? 0) + (b.counts.transfer ?? 0)}
                      {b.status === "rolled_back" && <> <Pill>rolled back</Pill></>}</td>
                    <td className="money">{b.status === "committed" && (
                      <button className="ghost small" disabled={rollback.isPending}
                        aria-label={`Roll back the import of ${b.filename}`}
                        onClick={() => {
                          if (confirm(`Roll back ${b.filename}? Every entry it made that you `
                            + "have not edited since is removed, and its matches are undone.")) {
                            rollback.mutate(b.id);
                          }
                        }}>Roll back</button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
    </>
  );
}

function DryRun({ batch, accounts, categories, payees, busy, onDecide, onCommit, onCancel }: {
  batch: BankImportBatch; accounts: FinanceAccount[]; categories: FinanceCategory[];
  payees: PayeeReport["payees"]; busy: boolean;
  onDecide: (row: BankImportRow, body: object) => void; onCommit: () => void;
  onCancel: () => void;
}) {
  const rows = batch.rows ?? [];
  const c = batch.counts;
  const writes = (c.new ?? 0) + (c.transfer ?? 0);
  const others = accounts.filter((a) => a.id !== batch.account.id);
  return (
    <Card title={`2. What would happen: ${batch.filename} into ${batch.account.name}`}>
      <Banner kind="info">Nothing has been written to the books. This is the dry run.</Banner>
      <p className="small" aria-label="What the import would do">
        <strong>{writes}</strong> new {writes === 1 ? "entry" : "entries"}
        {(c.needs_category ?? 0) > 0 && <> ({c.needs_category} with no category yet)</>}
        {" · "}<strong>{c.duplicate ?? 0}</strong> already in the books
        {" · "}<strong>{c.invoice_payment ?? 0}</strong> matched to an invoice payment
        {" · "}<strong>{c.transfer_match ?? 0}</strong> the other side of a transfer
        {" · "}<strong>{c.ignore ?? 0}</strong> ignored
        {" · "}<strong>{c.error ?? 0}</strong> that cannot be read
      </p>
      <table>
        <thead><tr><th>Date</th><th>Line</th><th className="money">Amount</th>
          <th>What it is</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.on_date ? longDate(row.on_date) : `Line ${row.row_number}`}</td>
              <td>{row.description || (row.raw ? Object.values(row.raw).join(" · ") : "")}</td>
              <td className="money">{row.amount_cents === null ? ""
                : `${row.direction === "out" ? "−" : "+"}${dollars(row.amount_cents)}`}</td>
              <td><RowDecision row={row} others={others} categories={categories}
                payees={payees} busy={busy} onDecide={(body) => onDecide(row, body)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row tight" style={{ marginTop: "var(--s3)" }}>
        <button className="primary" disabled={busy} onClick={onCommit}>
          3. Write {writes} {writes === 1 ? "entry" : "entries"} to the books</button>
        <button className="ghost" disabled={busy} onClick={onCancel}>Not now</button>
      </div>
      {(c.needs_category ?? 0) > 0 && (
        <p className="tiny muted">Lines left with no category are still entered. They are
          listed under "No category yet" and stay out of the profit and loss until they
          have one.</p>
      )}
    </Card>
  );
}

function RowDecision({ row, others, categories, payees, busy, onDecide }: {
  row: BankImportRow; others: FinanceAccount[]; categories: FinanceCategory[];
  payees: PayeeReport["payees"]; busy: boolean; onDecide: (body: object) => void;
}) {
  const [remember, setRemember] = useState(false);
  const [text, setText] = useState(row.description.split(/\s+/).slice(0, 2).join(" "));
  const line = `line ${row.row_number}`;
  if (row.outcome === "error") return <span className="small"><Pill kind="bad">cannot be
    read</Pill> {row.error}</span>;
  if (row.outcome === "duplicate") return <Pill>already in the books</Pill>;
  if (row.outcome === "invoice_payment" || row.outcome === "transfer_match") {
    return (
      <span className="small">
        <Pill kind="ok">{row.outcome === "invoice_payment" ? "an invoice payment"
          : "the other side of a transfer"}</Pill>{" "}
        {row.matched && <>{row.matched.description}
          {row.matched.counterparty && `, ${row.matched.counterparty}`},{" "}
          {longDate(row.matched.on_date)}. No new entry is made. </>}
        <button className="link" disabled={busy} aria-label={`Not a match: ${line}`}
          onClick={() => onDecide({ decision: "not_a_match" })}>It is something else</button>
      </span>
    );
  }
  const value = row.outcome === "ignore" ? "ignore"
    : row.outcome === "transfer" ? `transfer:${row.other_account?.id ?? ""}`
      : row.category ? `category:${row.category.id}` : "";
  const choose = (choice: string) => {
    const memo = remember && text.trim().length >= 3 ? { remember: text.trim() } : {};
    if (choice === "ignore") onDecide({ decision: "ignore", ...memo });
    else if (choice.startsWith("transfer:")) {
      onDecide({ decision: "transfer", other_account: choice.slice(9), ...memo });
    } else {
      onDecide({ decision: "entry", category: choice.slice(9) || null,
                 payee_contact: row.payee_contact || null, ...(choice ? memo : {}) });
    }
  };
  const group = (type: string, label: string) => (
    <optgroup label={label}>
      {categories.filter((cat) => cat.type === type && !cat.archived).map(
        (cat) => <option key={cat.id} value={`category:${cat.id}`}>{cat.name}</option>)}
    </optgroup>
  );
  return (
    <span className="small">
      <select aria-label={`What is ${line}`} value={value} disabled={busy}
        style={{ width: "auto", maxWidth: "16rem" }} onChange={(e) => choose(e.target.value)}>
        <option value="">No category yet</option>
        {group(row.direction === "out" ? "expense" : "income",
               row.direction === "out" ? "Expense" : "Income")}
        {group(row.direction === "out" ? "income" : "expense",
               row.direction === "out" ? "Income (a refund you gave)" : "Expense (a refund)")}
        {group("owner", "Your own money")}
        {group("held", "Held")}
        {others.length > 0 && (
          <optgroup label={row.direction === "out" ? "A transfer to" : "A transfer from"}>
            {others.map((a) => <option key={a.id} value={`transfer:${a.id}`}>{a.name}</option>)}
          </optgroup>
        )}
        <option value="ignore">Ignore this line</option>
      </select>
      {row.outcome === "new" && row.direction === "out" && payees.length > 0 && (
        <select aria-label={`1099 payee for ${line}`} value={row.payee_contact} disabled={busy}
          style={{ width: "auto", marginLeft: 6 }}
          onChange={(e) => onDecide({ decision: "entry", category: row.category?.id ?? null,
                                      payee_contact: e.target.value || null })}>
          <option value="">Not a 1099 payee</option>
          {payees.map((p) => <option key={p.contact} value={p.contact}>{p.name}</option>)}
        </select>
      )}
      {row.rule ? <> <Pill>your rule: contains “{row.rule.contains}”</Pill></> : (
        <label className="tiny" style={{ display: "inline-flex", gap: 4, marginLeft: 6 }}>
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
