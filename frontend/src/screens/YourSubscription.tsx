import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { SubscriptionState, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

const ROOT = "/api/subscription/";
const STATUS_KIND: Record<string, string> = {
  active: "ok", past_due: "bad", needs_card: "warn", canceled: "", not_billed: "" };

/**
 * Settings → Billing, "Your subscription" (P4 part 5): what the practice pays
 * Execs NOW HQ. The practice owner's card goes into the platform's card vault
 * through NMI's own fields; it is charged on the 1st of each month; every
 * charge has its own invoice and PDF; Pay now pays what is open.
 */
export function YourSubscription() {
  const qc = useQueryClient();
  const state = useQuery<SubscriptionState>({
    queryKey: ["subscription"], queryFn: () => api.get<SubscriptionState>(ROOT) });
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const settle = (next: SubscriptionState) => {
    qc.setQueryData(["subscription"], next);
    setNote(next.message ? { kind: next.open_cents ? "bad" : "ok", text: next.message } : null);
    if (!next.suspended) qc.invalidateQueries({ queryKey: ["me"] });
  };
  const payNow = useMutation({
    mutationFn: () => api.post<SubscriptionState>(ROOT + "pay-now/"),
    onSuccess: settle,
    onError: (e: Error) => setNote({ kind: "bad", text: e.message }),
  });

  if (state.isError) return <Banner kind="bad">{(state.error as Error).message}</Banner>;
  const s = state.data;
  if (!s) return <p>Loading your subscription…</p>;
  if (s.not_billed) {
    return (
      <Card title="Your subscription">
        <p style={{ margin: 0 }}>Your practice is not billed.</p>
      </Card>
    );
  }

  return (
    <Card title="Your subscription">
      {note && <div role={note.kind === "ok" ? "status" : "alert"}>
        <Banner kind={note.kind}>{note.text}</Banner></div>}
      <p style={{ marginTop: 0 }}>
        <strong>{s.plan}</strong>: {dollars(s.amount_cents)} a month.{" "}
        <Pill kind={STATUS_KIND[s.status] ?? ""}>{s.status_label}</Pill>{" "}
        {s.test_mode && <Pill kind="warn">Test mode</Pill>}
      </p>
      <p className="small muted">
        Charged on the 1st of each month to the card on file, with a receipt and the invoice
        by email{s.billing_email ? ` to ${s.billing_email}` : ""}. There is no part-month: a
        card added part-way through a month is first charged on the next 1st, and a change of
        amount applies from the next month.
      </p>
      <p>
        {s.card ? <>Card on file: <strong>{s.card.brand || "Card"} ending {s.card.last4}</strong>,
          expires {s.card.expires}.</> : "No card on file."}
        {s.next_charge_on && <> Next charge: {longDate(s.next_charge_on)}.</>}
      </p>
      <div className="row tight">
        <button className="small" onClick={() => setAdding(!adding)}>
          {adding ? "Cancel" : s.card ? "Replace the card" : "Add a card"}</button>
        {s.open_cents > 0 && s.card && (
          <button className="primary small" disabled={payNow.isPending}
            onClick={() => payNow.mutate()}>
            {payNow.isPending ? "Paying…" : `Pay now ${dollars(s.open_cents)}`}</button>
        )}
      </div>
      {adding && s.public_key && (
        <NmiCardForm publicKey={s.public_key} amountCents={0} payPath={ROOT + "card/"}
          buttonText="Save this card" onDone={() => undefined}
          onToken={async (token) => {
            try {
              settle(await api.post<SubscriptionState>(ROOT + "card/",
                { payment_token: token }));
              setAdding(false);
              return true;
            } catch (e) {
              setNote({ kind: "bad", text: (e as Error).message });
              return (e as Error).message;
            }
          }} />
      )}

      <h3>Invoices</h3>
      {s.invoices.length === 0 ? <Empty>No invoices yet.</Empty> : (
        <table>
          <thead><tr><th>Number</th><th>Month</th><th className="money">Total</th>
            <th>Status</th><th /></tr></thead>
          <tbody>
            {s.invoices.map((invoice) => (
              <tr key={invoice.id}>
                <td>{invoice.number}</td>
                <td>{longDate(invoice.period_start).replace(/ 1,/, "")}</td>
                <td className="money">{dollars(invoice.total_cents)}</td>
                <td>
                  <Pill kind={invoice.status === "paid" ? "ok" : "bad"}>
                    {invoice.checking ? "Being checked" : invoice.status_label}</Pill>
                  {invoice.last_charge_text && (
                    <span className="small muted"> {invoice.last_charge_text}</span>)}
                </td>
                <td className="money">
                  <a className="btn small" href={`${ROOT}${invoice.id}/pdf/`}
                    aria-label={`Download invoice ${invoice.number}`}>PDF</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
