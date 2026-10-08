import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { InvoiceLines, PriceBox, cleanLines } from "../components/InvoiceLines";
import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill, when } from "../components/ui";
import { Invoice, InvoiceEvent, InvoiceLine, Me, api } from "../lib/api";
import { dollars, lineAmount, longDate, toCents } from "../lib/money";
import { StatusPill } from "./Invoices";

/**
 * One invoice (P4A). What it shows follows its status:
 *
 * - **Draft**: everything is editable. Making it ready gives it its number.
 * - **Ready**: frozen, with its PDF and the whole email on screen, waiting for
 *   the practice owner to send it.
 * - **Sent and after**: the document as sent, the payments recorded against
 *   it by hand, and void.
 *
 * Only the practice owner sends, records a payment or voids (matrix 13.4c–d).
 */

const WHAT: Record<string, string> = {
  invoice_created: "Written", invoice_ready: "Made ready to send",
  invoice_reopened: "Sent back to draft", invoice_sent: "Sent", invoice_resent: "Sent again",
  payment_recorded: "Payment recorded", payment_removed: "Payment removed",
  invoice_voided: "Voided",
};
const METHODS: [string, string][] = [
  ["ach", "Bank transfer"], ["check", "Check"], ["card", "Card"], ["wire", "Wire"],
  ["other", "Other"],
];

export function InvoiceDetail({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const path = `/api/invoices/${id}/`;
  const owner = me.role === "FF";
  const [said, setSaid] = useState("");
  const invoice = useQuery<Invoice>({
    queryKey: ["invoice", id], queryFn: () => api.get<Invoice>(path) });
  const history = useQuery<InvoiceEvent[]>({
    queryKey: ["invoice-history", id],
    queryFn: () => api.get<InvoiceEvent[]>(`${path}history/`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["invoice", id] });
    qc.invalidateQueries({ queryKey: ["invoice-history", id] });
    qc.invalidateQueries({ queryKey: ["invoices"] });
  };
  const act = useMutation({
    mutationFn: ({ suffix, body }: { suffix: string; body?: object }) =>
      api.post<Invoice>(`${path}${suffix}`, body ?? {}),
    onSuccess: () => { setSaid(""); refresh(); },
    onError: (e: Error) => setSaid(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.del<void>(path),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["invoices"] }); navigate("/invoices"); },
    onError: (e: Error) => setSaid(e.message),
  });

  if (invoice.isLoading) return <p>Opening the invoice…</p>;
  if (invoice.isError) {
    return (
      <>
        <Banner kind="bad">{(invoice.error as Error).message}</Banner>
        <p><Link to="/invoices">Back to the invoices</Link></p>
      </>
    );
  }
  const i = invoice.data!;
  const busy = act.isPending || remove.isPending;
  const who = i.client_company?.name ?? i.contact.name;

  return (
    <>
      <PageHead title={i.number ? `Invoice ${i.number}` : "Draft invoice"}
        crumbs={[{ to: "/invoices", label: "Invoices" }]}
        sub={<>{who}{i.client_company && <> · to {i.contact.name}</>} ·{" "}
          <StatusPill row={i} />{i.kind === "contact"
            && <> <Pill>not a client: email only</Pill></>}</>} />
      {said && <Banner kind="bad">{said}</Banner>}

      {i.status === "draft" && (
        <Draft invoice={i} busy={busy} onSaved={refresh} onError={setSaid}
          onReady={() => act.mutate({ suffix: "make-ready/" })}
          onDelete={i.number ? undefined : () => {
            if (confirm("Throw this draft away? It has no number, so nothing is lost "
              + "from the sequence.")) remove.mutate();
          }} />
      )}

      {i.status !== "draft" && (
        <>
          <Card title="The invoice"
            actions={i.has_pdf && <a className="btn small" href={`${path}pdf/`}>
              Download the PDF</a>}>
            <Summary invoice={i} />
          </Card>

          {i.status === "ready" && (
            <Card title="Ready to send">
              {i.send_state === "sent_back" && (
                <Banner kind="warn">The email was sent back from the Sending queue.
                  Nothing has gone to {i.contact.name}.</Banner>
              )}
              <p className="small muted" style={{ marginTop: 0 }}>
                This is the whole email, with the PDF above attached. Nothing has been
                sent. {owner ? "Sending it is your approval."
                  : "It goes when the practice owner approves it, here or in the Sending queue."}
              </p>
              <Email invoice={i} />
              <div className="row tight">
                {owner && (
                  <button className="primary" disabled={busy}
                    onClick={() => act.mutate({ suffix: "send/" })}>
                    {act.isPending ? "Sending…" : `Send to ${i.email_to}`}</button>
                )}
                {!owner && i.send_state === "sent_back" && (
                  <button disabled={busy}
                    onClick={() => act.mutate({ suffix: "queue-again/" })}>
                    Ask again for it to be sent</button>
                )}
                <button disabled={busy} onClick={() => act.mutate({ suffix: "back-to-draft/" })}>
                  Back to draft</button>
              </div>
              <p className="tiny muted">Back to draft keeps the number {i.number} and
                withdraws the waiting email.</p>
            </Card>
          )}

          {i.status !== "ready" && (
            <Payments invoice={i} owner={owner} busy={busy}
              onPay={(body) => act.mutate({ suffix: "payments/", body })}
              onRemove={(payment, reason) =>
                act.mutate({ suffix: "remove-payment/", body: { payment, reason } })} />
          )}

          {owner && i.status !== "void" && (
            <Card title="Send again, or void">
              {i.status !== "ready" && <Resend invoice={i} busy={busy}
                onSend={(to_address) => act.mutate({ suffix: "send/", body: { to_address } })} />}
              <Void invoice={i} busy={busy}
                onVoid={(reason) => act.mutate({ suffix: "void/", body: { reason } })} />
            </Card>
          )}
          {i.status === "void" && (
            <Banner kind="info">Void since {i.voided_at ? when(i.voided_at) : ""}:{" "}
              {i.void_reason} Its number is kept and is not used again.</Banner>
          )}
        </>
      )}

      <Card title="History">
        {(history.data ?? []).length === 0 ? <p className="small muted">Nothing yet.</p> : (
          <ol className="small" aria-label="History of this invoice">
            {(history.data ?? []).map((event, index) => (
              <li key={index}>
                <strong>{WHAT[event.what] ?? event.what}</strong>
                {event.amount_cents ? ` · ${dollars(event.amount_cents)}` : ""}
                {event.to ? ` · to ${event.to}` : ""} · {event.by} · {when(event.at)}
                {event.reason && <div className="muted">Reason: {event.reason}</div>}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}

/** The figures and words of an invoice that can no longer be edited. */
function Summary({ invoice: i }: { invoice: Invoice }) {
  return (
    <>
      <p className="small">
        <strong>{i.bill_to.company || i.bill_to.name}</strong>
        {i.bill_to.company && <> · {i.bill_to.name}</>}
        {i.bill_to.address && <span style={{ whiteSpace: "pre-line" }}><br />{i.bill_to.address}</span>}
        <br />Issued {longDate(i.issue_date)} · due <strong>{longDate(i.due_date)}</strong>
      </p>
      <table className="invoice-lines">
        <thead><tr><th>Description</th><th className="num">Quantity</th>
          <th className="num">Price</th><th className="num">Amount</th></tr></thead>
        <tbody>
          {i.lines.map((line) => (
            <tr key={line.id}>
              <td style={{ whiteSpace: "pre-line" }}>{line.description}</td>
              <td className="num">{Number(line.quantity)}</td>
              <td className="num">{dollars(line.unit_price_cents)}</td>
              <td className="num amount">{dollars(line.amount_cents ?? 0)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={3} className="num">Subtotal</td>
            <td className="num">{dollars(i.subtotal_cents)}</td></tr>
          {i.tax_cents > 0 && <tr><td colSpan={3} className="num">Tax</td>
            <td className="num">{dollars(i.tax_cents)}</td></tr>}
          <tr><td colSpan={3} className="num"><strong>Total</strong></td>
            <td className="num amount">{dollars(i.total_cents)}</td></tr>
          {i.paid_cents > 0 && <tr><td colSpan={3} className="num">Paid</td>
            <td className="num">{dollars(i.paid_cents)}</td></tr>}
          {i.status !== "void" && <tr><td colSpan={3} className="num"><strong>Balance</strong></td>
            <td className="num amount">{dollars(i.balance_cents)}</td></tr>}
        </tfoot>
      </table>
      <p className="small muted" style={{ whiteSpace: "pre-line" }}>
        <strong>How to pay:</strong> {i.pay_instructions}</p>
    </>
  );
}

function Email({ invoice: i }: { invoice: Invoice }) {
  return (
    <div className="card" aria-label="The email as it will be sent">
      <p className="small" style={{ margin: 0 }}>To <strong>{i.email_to}</strong></p>
      <p className="small" style={{ margin: 0 }}>Subject <strong>{i.email_subject}</strong></p>
      <p className="small" style={{ whiteSpace: "pre-line" }}>{i.email_body}</p>
      <p className="tiny muted" style={{ margin: 0 }}>Attached: Invoice-{i.number}.pdf</p>
    </div>
  );
}

function Draft({ invoice: i, busy, onSaved, onError, onReady, onDelete }: {
  invoice: Invoice; busy: boolean; onSaved: () => void; onError: (text: string) => void;
  onReady: () => void; onDelete?: () => void;
}) {
  const start = () => ({
    issue_date: i.issue_date, due_date: i.due_date, tax_cents: i.tax_cents,
    notes: i.notes, terms: i.terms, pay_instructions: i.pay_instructions,
    email_to: i.email_to, email_subject: i.email_subject, email_body: i.email_body,
    bill_to_address: i.bill_to.address ?? "" });
  const [form, setForm] = useState(start);
  const [lines, setLines] = useState<InvoiceLine[]>(i.lines.length ? i.lines
    : [{ description: "", quantity: "1", unit_price_cents: 0 }]);
  const [dirty, setDirty] = useState(false);
  // What the server holds, after a save or when another invoice is opened.
  useEffect(() => {
    setForm(start());
    setLines(i.lines.length ? i.lines : [{ description: "", quantity: "1", unit_price_cents: 0 }]);
    setDirty(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i.id, i.total_cents, i.lines.length]);
  const change = (patch: Partial<ReturnType<typeof start>>) => {
    setForm({ ...form, ...patch }); setDirty(true); };
  const save = useMutation({
    mutationFn: () => api.patch<Invoice>(`/api/invoices/${i.id}/`,
                                         { ...form, lines: cleanLines(lines) }),
    onSuccess: () => { onError(""); onSaved(); },
    onError: (e: Error) => onError(e.message),
  });
  const subtotal = lines.reduce(
    (sum, line) => sum + lineAmount(line.quantity, line.unit_price_cents), 0);
  const badQuantity = lines.some((line) => line.description.trim()
    && toCents(line.quantity) === null);
  const text = (label: string, field: "notes" | "terms" | "pay_instructions" | "email_body"
                | "bill_to_address", rows = 2) => (
    <Field label={label}>
      <textarea rows={rows} aria-label={label} value={form[field]} disabled={busy}
        onChange={(e) => change({ [field]: e.target.value })} />
    </Field>
  );
  return (
    <>
      <Card title="What you are billing">
        {i.number && <Banner kind="info">This draft keeps its number, {i.number}.</Banner>}
        <div className="row">
          <Field label="Issue date">
            <input type="date" aria-label="Issue date" value={form.issue_date} disabled={busy}
              onChange={(e) => change({ issue_date: e.target.value })} />
          </Field>
          <Field label="Due date">
            <input type="date" aria-label="Due date" value={form.due_date} disabled={busy}
              onChange={(e) => change({ due_date: e.target.value })} />
          </Field>
        </div>
        <InvoiceLines lines={lines} disabled={busy}
          onChange={(next) => { setLines(next); setDirty(true); }} />
        {badQuantity && <p className="tiny" style={{ color: "var(--bad)" }}>
          A quantity is a number, such as 1 or 2.5.</p>}
        <div className="row tight" style={{ marginTop: "var(--s3)", alignItems: "center" }}>
          <label className="small inline">Tax (optional, an amount you type)
            <PriceBox label="Tax" cents={form.tax_cents} disabled={busy}
              onChange={(tax_cents) => change({ tax_cents })} /></label>
          <strong>Total {dollars(subtotal + form.tax_cents)}</strong>
        </div>
      </Card>
      <Card title="What prints on it">
        {text("Billing address (optional)", "bill_to_address")}
        {text("How to pay", "pay_instructions", 3)}
        {text("Notes", "notes")}
        {text("Terms", "terms")}
      </Card>
      <Card title="The email it goes in">
        <p className="small muted" style={{ marginTop: 0 }}>
          You can use {i.merge_fields.map((f) => `{${f}}`).join(", ")}. They are filled in
          when the invoice is made ready.
        </p>
        <div className="row">
          <Field label="To (empty uses their main address)">
            <input aria-label="Send to" type="email" value={form.email_to} disabled={busy}
              onChange={(e) => change({ email_to: e.target.value })} />
          </Field>
          <Field label="Subject">
            <input aria-label="Email subject" value={form.email_subject} disabled={busy}
              maxLength={200} onChange={(e) => change({ email_subject: e.target.value })} />
          </Field>
        </div>
        {text("Message", "email_body", 6)}
      </Card>
      <Card>
        <div className="row tight">
          <button className="primary" disabled={busy || save.isPending || !dirty || badQuantity}
            onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save the draft"}</button>
          <a className="btn" href={`/api/invoices/${i.id}/preview/`} target="_blank"
            rel="noreferrer">Preview the PDF</a>
          <button disabled={busy || dirty || i.lines.length === 0} onClick={onReady}
            title={dirty ? "Save your changes first." : ""}>
            Make it ready to send</button>
          {onDelete && <button className="ghost" disabled={busy} onClick={onDelete}>
            Throw the draft away</button>}
        </div>
        <p className="tiny muted" style={{ marginBottom: 0 }}>
          Making it ready gives the invoice its number, fixes its wording and puts its email
          in the Sending queue. It sends nothing. {dirty && "You have unsaved changes."}
        </p>
      </Card>
    </>
  );
}

function Payments({ invoice: i, owner, busy, onPay, onRemove }: {
  invoice: Invoice; owner: boolean; busy: boolean;
  onPay: (body: object) => void; onRemove: (payment: string, reason: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [cents, setCents] = useState(i.balance_cents);
  const [paidOn, setPaidOn] = useState(today);
  const [method, setMethod] = useState("ach");
  const [reference, setReference] = useState("");
  useEffect(() => { setCents(i.balance_cents); setReference(""); }, [i.balance_cents]);
  const open = i.status === "sent" || i.status === "partially_paid";
  return (
    <Card title="Payments">
      {i.payments.length === 0 && <p className="small muted" style={{ marginTop: 0 }}>
        No payment recorded.</p>}
      {i.payments.length > 0 && (
        <table>
          <thead><tr><th>Paid on</th><th className="money">Amount</th><th>How</th>
            <th>Reference</th><th>Recorded by</th><th /></tr></thead>
          <tbody>
            {i.payments.map((p) => (
              <tr key={p.id} style={p.removed ? { textDecoration: "line-through" } : undefined}>
                <td>{longDate(p.paid_on)}</td>
                <td className="money">{dollars(p.amount_cents)}</td>
                <td>{p.method_label}</td><td>{p.reference}</td><td>{p.recorded_by}</td>
                <td className="money">
                  {p.removed ? <span className="tiny muted" style={{ textDecoration: "none" }}>
                    removed: {p.remove_reason}</span>
                    : owner && i.status !== "void" && (
                      <button className="ghost small" disabled={busy}
                        aria-label={`Remove the payment of ${dollars(p.amount_cents)}`}
                        onClick={() => {
                          const reason = prompt("Why is this payment being removed? It is "
                            + "kept in the history, and stops counting.");
                          if (reason && reason.trim()) onRemove(p.id, reason.trim());
                        }}>Remove</button>
                    )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {owner && open && (
        <div className="row" style={{ marginTop: "var(--s3)" }}>
          <Field label="Amount received">
            <PriceBox label="Amount received" cents={cents} onChange={setCents} disabled={busy} />
          </Field>
          <Field label="Paid on">
            <input type="date" aria-label="Paid on" value={paidOn} max={today} disabled={busy}
              onChange={(e) => setPaidOn(e.target.value)} />
          </Field>
          <Field label="How">
            <select aria-label="How it was paid" value={method} disabled={busy}
              onChange={(e) => setMethod(e.target.value)}>
              {METHODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field label="Reference (optional)">
            <input aria-label="Payment reference" value={reference} maxLength={120}
              disabled={busy} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <button className="primary" disabled={busy || cents <= 0 || cents > i.balance_cents}
            onClick={() => onPay({ amount_cents: cents, paid_on: paidOn, method, reference })}>
            Record the payment</button>
        </div>
      )}
      {owner && open && cents > i.balance_cents && (
        <p className="tiny" style={{ color: "var(--bad)" }}>
          That is more than the {dollars(i.balance_cents)} still owed.</p>
      )}
      {!owner && open && <p className="small muted">The practice owner records payments.</p>}
    </Card>
  );
}

function Resend({ invoice: i, busy, onSend }: {
  invoice: Invoice; busy: boolean; onSend: (to: string) => void;
}) {
  const [to, setTo] = useState(i.email_to);
  return (
    <div className="row">
      <Field label="Send the same PDF again to">
        <input type="email" aria-label="Send again to" value={to}
          onChange={(e) => setTo(e.target.value)} />
      </Field>
      <button disabled={busy || !to.trim()} onClick={() => onSend(to.trim())}>Send again</button>
    </div>
  );
}

function Void({ invoice: i, busy, onVoid }: {
  invoice: Invoice; busy: boolean; onVoid: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const paid = i.paid_cents > 0;
  return (
    <>
      <div className="row">
        <Field label="Void it, because">
          <input aria-label="Why the invoice is being voided" value={reason} disabled={paid}
            onChange={(e) => setReason(e.target.value)} />
        </Field>
        <button className="danger" disabled={busy || paid || !reason.trim()}
          onClick={() => {
            if (confirm(`Void invoice ${i.number}? It stays on the list, marked void, and `
              + "its number is not used again.")) onVoid(reason.trim());
          }}>Void the invoice</button>
      </div>
      <p className="tiny muted" style={{ marginBottom: 0 }}>
        {paid ? `It has ${dollars(i.paid_cents)} recorded against it. Remove the payment `
          + "first if it was recorded in error."
          : "A sent invoice is never edited. To correct one, void it and write a new one."}
      </p>
    </>
  );
}
