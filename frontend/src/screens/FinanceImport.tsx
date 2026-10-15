import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import {
  FinanceAccount, FinanceCategory, BankImportBatch, ImportDetected, ImportMapping, BankImportRow,
  PayeeReport, StatementFacts, api, Me, PersonalCategory,
} from "../lib/api";
import { categoryOptions } from "../lib/finance";
import { dollars, longDate } from "../lib/money";
import { hasPersonal, personalOptions, usePersonalChart } from "../lib/personal";

/**
 * Importing a bank or card export (P5 §4; matrix 13.8), in the contact
 * import's three steps: map the columns, a dry run, commit.
 *
 * **The dry run writes nothing to the books.** Each line is shown with what
 * will happen to it; the owner gives it a category, marks a transfer, or
 * accepts or declines a proposed match. A committed import can be rolled back.
 */

/** A CSV, or a bank's own OFX file under any of its three names. */
const ACCEPTS = ".csv,text/csv,.ofx,.qfx,.qbo,application/x-ofx,application/vnd.intu.qfx,"
  + "application/vnd.intu.qbo,.pdf,application/pdf";

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
  // P6 M4: with Personal finance, each line can be put on a side.
  const me = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const chart = usePersonalChart(hasPersonal(me.data));
  const personal = hasPersonal(me.data) ? chart.data?.categories ?? [] : null;
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
            Download a file from your bank or card's website and choose the account it is
            for: a CSV, or the bank's own OFX, QFX (Quicken) or QBO (QuickBooks) file. A PDF
            statement works too: Claude reads it, which costs a little and is priced before
            it is read. Downloading an overlapping range each month is fine: lines already
            in the books are recognized and left out.
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
              <Field label="The file from your bank">
                <input type="file" accept={ACCEPTS} aria-label="The file from your bank"
                  onChange={(e) => { setFile(e.target.files?.[0] ?? null); setDetected(null); }} />
              </Field>
              <button disabled={!account || !file || detect.isPending}
                onClick={() => detect.mutate()}>Read the file</button>
            </div>
          )}
          {detected && detected.kind === "pdf" && (
            <div role="group" aria-label="The PDF statement">
              <p className="small">
                A PDF statement, {detected.pages} page{detected.pages === 1 ? "" : "s"}.
                Claude reads it and copies out its lines, its period and its beginning and
                ending balance, for about <strong>${Number(detected.estimate_usd).toFixed(2)}
                </strong> of your AI budget. You then see every line before anything is
                written, as for any import.
              </p>
              <p className="small muted">
                The statement is sent to Anthropic as it is, to be read. From it only the
                lines, the period and the two balances are kept: never the account number,
                a name or an address. The PDF itself is kept with the import and shown on
                the Reconcile screen for its month.
              </p>
              {detected.refused && <Banner kind="bad">{detected.refused}</Banner>}
              <p><button className="primary" disabled={dryRun.isPending || !!detected.refused}
                onClick={() => dryRun.mutate()}>
                {dryRun.isPending ? "Claude is reading the statement…"
                  : `Read it with Claude, about $${Number(detected.estimate_usd).toFixed(2)}`}
              </button></p>
            </div>
          )}
          {detected && mapping && detected.kind !== "pdf" && (
            <>
              <p className="small">{detected.lines} lines.{" "}
                {detected.fixed
                  ? "This is your bank's own file format, which says which value is which: "
                    + "there are no columns to choose."
                  : detected.from_saved
                    ? "Using the columns you chose last time for this account."
                    : "This is a first guess from the column names: check it."}</p>
              {!detected.fixed && <><div className="row">
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
              </div></>}
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
        <DryRun personal={personal} batch={batch} accounts={open} categories={categories}
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
                    <td>{b.filename}
                      {b.statement && <> <a href={b.statement.pdf} target="_blank"
                        rel="noreferrer" aria-label={`Open the statement ${b.filename}`}>
                        PDF</a></>}</td><td>{b.account.name}</td>
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

/** What was read from a PDF statement, set against itself: the lines Claude
 *  copied out, added up here, beside the ending balance the statement prints.
 *  A difference means a line was misread or missed, and is said before
 *  anything is written. */
function StatementRead({ facts: s }: { facts: StatementFacts }) {
  const sum = s.adds_up;
  return (
    <div role="group" aria-label="What was read from the statement" className="small">
      <p style={{ margin: 0 }}>
        Read from the PDF by Claude
        {s.cost_usd !== null && <> for ${Number(s.cost_usd).toFixed(4)}</>}.{" "}
        {s.period_start && s.period_end
          && <>The statement runs {longDate(s.period_start)} to {longDate(s.period_end)}. </>}
        {s.opening_balance_cents !== null
          && <>Beginning balance {dollars(s.opening_balance_cents)}. </>}
        {s.closing_balance_cents !== null
          && <>Ending balance {dollars(s.closing_balance_cents)}. </>}
        <a href={s.pdf} target="_blank" rel="noreferrer">Open the statement</a>
      </p>
      {sum === null && (
        <p className="muted">The statement printed no beginning or ending balance to check
          the lines against: check them against the PDF yourself.</p>
      )}
      {sum && sum.difference_cents === 0 && (
        <p>The lines read add up to the statement's ending balance.</p>
      )}
      {sum && sum.difference_cents !== 0 && (
        <Banner kind="bad">
          The lines read come to {dollars(sum.expected_cents)}, which is{" "}
          {dollars(Math.abs(sum.difference_cents))}{" "}
          {sum.difference_cents > 0 ? "less" : "more"} than the statement's ending balance. A
          line was misread or missed: check them against the PDF before writing anything.
        </Banner>
      )}
    </div>
  );
}

function DryRun({ batch, accounts, categories, payees, busy, onDecide, onCommit, onCancel,
                  personal }: {
  batch: BankImportBatch; accounts: FinanceAccount[]; categories: FinanceCategory[];
  payees: PayeeReport["payees"]; busy: boolean; personal: PersonalCategory[] | null;
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
      {batch.statement && <StatementRead facts={batch.statement} />}
      <p className="small" aria-label="What the import would do">
        <strong>{writes}</strong> new {writes === 1 ? "entry" : "entries"}
        {(c.needs_category ?? 0) > 0 && <> ({c.needs_category} with no category yet)</>}
        {" · "}<strong>{c.duplicate ?? 0}</strong> already in the books
        {" · "}<strong>{c.invoice_payment ?? 0}</strong> matched to an invoice payment
        {" · "}<strong>{c.transfer_match ?? 0}</strong> the other side of a transfer
        {" · "}<strong>{c.ignore ?? 0}</strong> ignored
        {" · "}<strong>{c.error ?? 0}</strong> that cannot be read
        {personal && ((c.personal ?? 0) > 0 || (c.to_sort ?? 0) > 0) && <>
          {" · "}<strong>{c.personal ?? 0}</strong> personal (an owner draw in the books,
          the spend in your personal ledger)
          {" · "}<strong>{c.to_sort ?? 0}</strong> to sort</>}
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
              <td>
                {personal && row.outcome === "new" && (
                  <SideChoice row={row} personal={personal} busy={busy}
                    onDecide={(body) => onDecide(row, body)} />)}
                {(!personal || row.outcome !== "new" || !row.side || row.side === "split") && (
                  <RowDecision row={row} others={others} categories={categories}
                    payees={payees} busy={busy}
                    onDecide={(body) => onDecide(row, row.side === "split"
                      ? { ...body, side: "split", split_business_cents: row.split_business_cents,
                          personal_category: row.personal_category?.id ?? null }
                      : body)} />)}
              </td>
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

/**
 * P6 M4 decision 2: which side a line is. Business keeps the choices below;
 * Personal is an owner draw in the books and the spend in the owner's ledger,
 * under a personal category; To sort leaves it for Personal → To sort. A split
 * comes from a rule and is shown as one.
 */
function SideChoice({ row, personal, busy, onDecide }: {
  row: BankImportRow; personal: PersonalCategory[]; busy: boolean;
  onDecide: (body: object) => void;
}) {
  const line = `line ${row.row_number}`;
  const side = row.side || "business";
  return (
    <span className="small" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap",
                                     marginRight: 6 }}>
      <select aria-label={`Side of ${line}`} value={side} disabled={busy}
        style={{ width: "auto" }}
        onChange={(e) => onDecide({ decision: "entry", side: e.target.value,
                                    category: null })}>
        <option value="business">Business</option>
        <option value="personal">Personal</option>
        <option value="to_sort">To sort later</option>
        {side === "split" && <option value="split">Split</option>}
      </select>
      {side === "personal" && (
        <select aria-label={`Personal category for ${line}`} disabled={busy}
          value={row.personal_category?.id ?? ""} style={{ width: "auto", maxWidth: "16rem" }}
          onChange={(e) => onDecide({ decision: "entry", side: "personal",
                                      personal_category: e.target.value || null })}>
          <option value="">No category yet (To sort)</option>
          {personalOptions(personal, row.direction === "out" ? "expense" : undefined).map(
            ([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      )}
      {side === "split" && row.split_business_cents != null && row.amount_cents != null && (
        <Pill>{dollars(row.split_business_cents)} business,{" "}
          {dollars(row.amount_cents - row.split_business_cents)} personal
          {row.personal_category ? ` (${row.personal_category.name})` : ""}</Pill>
      )}
      {side === "to_sort" && <Pill>waits in Personal → To sort</Pill>}
      {side === "personal" && row.rule && <Pill>your rule: contains “{row.rule.contains}”</Pill>}
    </span>
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
      {categoryOptions(categories.filter((cat) => cat.type === type && !cat.archived),
                       categories).map(
        ([id, name]) => <option key={id} value={`category:${id}`}>{name}</option>)}
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
