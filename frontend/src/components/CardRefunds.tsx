import { useState } from "react";

import { CardRefundRow } from "../lib/api";
import { dollars, longDate } from "../lib/money";
import { PriceBox } from "./InvoiceLines";
import { Field, Pill } from "./ui";

export interface RefundBody { amount_cents: number; reason: string; void_invoice: boolean }

/**
 * "Refund or cancel this payment" (2026-11-16). The amount (all that is left,
 * unless changed) and a required reason. The card processor is asked first:
 * a payment not yet settled, given back in full, is cancelled, so nothing
 * reaches the card statement; anything else is refunded. "And void the
 * invoice" is offered only with a full refund that leaves nothing paid.
 */
export function RefundForm({ refundable, canVoidInvoice, busy, onSubmit, onCancel,
                             noun = "payment" }: {
  refundable: number; canVoidInvoice: boolean; busy: boolean;
  onSubmit: (body: RefundBody) => void; onCancel: () => void;
  noun?: "payment" | "charge";
}) {
  const [cents, setCents] = useState(refundable);
  const [reason, setReason] = useState("");
  const [voidIt, setVoidIt] = useState(false);
  const full = cents === refundable;
  const tooMuch = cents > refundable;
  return (
    <form className="refund-form" aria-label={`Refund or cancel this ${noun}`}
      onSubmit={(e) => {
        e.preventDefault();
        if (cents > 0 && !tooMuch && reason.trim()) {
          onSubmit({ amount_cents: cents, reason: reason.trim(),
                     void_invoice: canVoidInvoice && full && voidIt });
        }
      }}>
      <div className="row" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
        <Field label="Amount to give back">
          <PriceBox label="Amount to give back" cents={cents} onChange={setCents}
            disabled={busy} />
        </Field>
        <Field label="Why">
          <input aria-label="Why the money is given back" value={reason} maxLength={1000}
            disabled={busy} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      {tooMuch && <p className="tiny" style={{ color: "var(--bad)" }}>
        That is more than the {dollars(refundable)} that can still be given back.</p>}
      {canVoidInvoice && full && (
        <label className="check small">
          <input type="checkbox" checked={voidIt} disabled={busy}
            onChange={(e) => setVoidIt(e.target.checked)} /> and void the invoice
        </label>
      )}
      <p className="tiny muted">
        The card processor is asked first. A {noun} not yet settled, given back in full, is
        cancelled, so nothing reaches the card statement; otherwise it is refunded, which
        usually reaches the card in 5 to 10 business days. Nothing is tried twice.
      </p>
      <div className="row tight">
        <button className="primary" type="submit"
          disabled={busy || cents <= 0 || tooMuch || !reason.trim()}>
          {busy ? "Asking the card processor…" : `Give back ${dollars(cents)}`}</button>
        <button className="ghost" type="button" disabled={busy} onClick={onCancel}>
          Cancel</button>
      </div>
    </form>
  );
}

/** What was given back: cancelled or refunded, by whom, why, and its state. */
export function RefundsList({ refunds }: { refunds?: CardRefundRow[] }) {
  if (!refunds || refunds.length === 0) return null;
  return (
    <div aria-label="Given back">
      <strong className="small">Given back</strong>
      <table>
        <thead><tr><th>When</th><th className="money">Amount</th><th>What</th>
          <th>Why</th><th>By</th></tr></thead>
        <tbody>
          {refunds.map((r) => (
            <tr key={r.id} style={r.cleared || r.status === "failed"
              ? { textDecoration: "line-through" } : undefined}>
              <td>{longDate(r.at.slice(0, 10))}</td>
              <td className="money">{dollars(r.amount_cents)}</td>
              <td>
                {r.kind_label}
                {r.status !== "done" && <> <Pill kind={r.status === "failed" ? "bad" : "warn"}>
                  {r.status_label}</Pill></>}
                {r.is_test && <> <Pill kind="warn">Test</Pill></>}
                {r.source === "portal" && <span className="tiny muted"> · in the processor's
                  portal</span>}
                {r.response_text && <div className="tiny muted">{r.response_text}</div>}
                {r.problem && <div className="tiny" style={{ color: "var(--bad)" }}>
                  {r.problem}</div>}
              </td>
              <td>{r.reason}</td><td>{r.by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
