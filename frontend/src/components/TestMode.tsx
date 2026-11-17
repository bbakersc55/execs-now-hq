import { useId, useState } from "react";

import { GatewayMode, TestPayments } from "../lib/api";
import { dollars } from "../lib/money";
import { Banner, Card } from "./ui";

/**
 * The card processor's own Test Mode (2026-11-16). While it is on, every
 * payment, refund and saved card is a test: no money moves, so the owner is
 * told plainly, on Billing and Invoices (the practice owner) and on Practices
 * (the platform owner). `again` says how to read it again once it is off.
 * If it could not be read, card payments behave as before and `showUnknown`
 * says so (Billing).
 */
export function GatewayModeBanner({ mode, again, showUnknown = false }: {
  mode?: GatewayMode; again: string; showUnknown?: boolean;
}) {
  if (mode?.banner) {
    return (
      <div role="alert">
        <Banner kind="warn"><strong>{mode.banner}</strong> Every payment, refund and card
          saved now is a test, kept out of the books. {again}</Banner>
      </div>
    );
  }
  if (showUnknown && mode?.unknown) return <Banner kind="info">{mode.unknown}</Banner>;
  return null;
}

/**
 * "N test payments" and its one action, once the processor reads live again:
 * the test payments come off their invoices (reopened or voided, as chosen),
 * and test cards are deleted from the vault. Nothing is in the books to take
 * out: a test payment never went in.
 */
export function ClearTestPayments({ summary, busy, onClear, what = "payments" }: {
  summary?: TestPayments; busy: boolean;
  onClear: (invoices: "reopen" | "void") => void;
  /** "payments" for a practice's clients; "charges" for subscriptions. */
  what?: "payments" | "charges";
}) {
  // No default (2026-11-17, INV-0005): a press with nothing chosen sent
  // "reopen". Clear waits until one is chosen.
  const [choice, setChoice] = useState<"reopen" | "void" | "">("");
  // Its own group, so a second panel on a page never shares its radios.
  const group = `clear-choice-${useId()}`;
  if (!summary?.can_clear) return null;
  const n = summary.payments;
  const noun = what === "charges" ? (n === 1 ? "test charge" : "test charges")
    : (n === 1 ? "test payment" : "test payments");
  return (
    <Card title={`${n} ${noun}`}>
      <p style={{ marginTop: 0 }}>
        {n > 0 && <>{n} {noun} ({dollars(summary.amount_cents)}) {n === 1 ? "was" : "were"} made
          while the card processor was in Test Mode. No money moved. </>}
        {summary.cards > 0 && <>{summary.cards} test card{summary.cards === 1 ? " was" : "s were"}
          {" "}saved then. </>}
        The processor is back in live mode, so they can be cleared.
      </p>
      <p id={`${group}-ask`} style={{ marginBottom: "0.25rem" }}>
        <strong>Reopen their invoices, or void them?</strong> Choose one.</p>
      <fieldset className="row tight" aria-labelledby={`${group}-ask`}>
        <label className="check">
          <input type="radio" name={group} checked={choice === "reopen"}
            onChange={() => setChoice("reopen")} /> Reopen their invoices
        </label>
        <label className="check">
          <input type="radio" name={group} checked={choice === "void"}
            onChange={() => setChoice("void")} /> Void their invoices
        </label>
      </fieldset>
      <p className="small muted">
        An invoice that also has real money on it is reopened, never voided.
        {what === "payments" && <> One dated after its automatic billing ended is voided
          either way.</>} Test cards are deleted from the vault, which turns their auto-pay off.
      </p>
      <button className="primary" disabled={busy || !choice}
        onClick={() => { if (choice) onClear(choice); }}>
        {busy ? "Clearing…" : "Clear test payments"}</button>
    </Card>
  );
}
