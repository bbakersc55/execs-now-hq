import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Pill } from "../components/ui";
import { AutopayState, PAYMENTS_PAUSED, PortalBilling, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

const ROOT = "/api/portal-billing/";
const CARD = "/api/portal-autopay/";

/**
 * 2026-11-17: automatic billing, under Invoices in the portal. Each recurring
 * invoice the practice bills automatically: its terms in short plain words,
 * the card it is charged to (saved here, in the card processor's own
 * fields), and the client owner's agreement; once agreed, "Stop automatic
 * billing" shows the dates before it is confirmed, and a notice can be
 * withdrawn before the end. A client owner's only: for anyone else the
 * server answers 403 and nothing shows.
 */
export function ClientBilling() {
  const qc = useQueryClient();
  const rows = useQuery<PortalBilling[]>({
    queryKey: ["portal-billing"], queryFn: () => api.get<PortalBilling[]>(ROOT),
    retry: false });
  const card = useQuery<AutopayState>({
    queryKey: ["portal-autopay"], queryFn: () => api.get<AutopayState>(CARD), retry: false });
  if (rows.isError || !rows.data || rows.data.length === 0) return null;
  const settle = (next: PortalBilling[]) => {
    qc.setQueryData(["portal-billing"], next);
    qc.invalidateQueries({ queryKey: ["portal-autopay"] });
  };
  return (
    <Card title="Automatic billing">
      <div id="automatic-billing" />
      {rows.data.map((row) => (
        <BillingRow key={row.id} row={row} card={card.data} onChanged={settle}
          onCard={(next) => qc.setQueryData(["portal-autopay"], next)} />
      ))}
    </Card>
  );
}

function BillingRow({ row, card, onChanged, onCard }: {
  row: PortalBilling; card?: AutopayState; onChanged: (next: PortalBilling[]) => void;
  onCard: (next: AutopayState) => void;
}) {
  const [agreed, setAgreed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api.post<PortalBilling[]>(`${ROOT}${row.id}/${path}`, body ?? {}),
    onSuccess: (next) => { setError(""); setPreview(null); setAgreed(false); onChanged(next); },
    onError: (e: Error) => setError(e.message),
  });
  const ask = useMutation({
    mutationFn: () => api.get<{ text: string }>(`${ROOT}${row.id}/stop-preview/`),
    onSuccess: (p) => { setError(""); setPreview(p.text); },
    onError: (e: Error) => setError(e.message),
  });
  const what = row.what.map((w) => `${w.description} (${dollars(w.amount_cents)})`).join("; ");
  const saved = card?.card;
  return (
    <section aria-label={`Automatic billing: ${what}`} style={{ marginBottom: "1rem" }}>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      <p style={{ marginTop: 0, marginBottom: "0.25rem" }}>
        <strong>{dollars(row.total_cents)}</strong> each time{" "}
        {row.state === "active" && <Pill kind="ok">On</Pill>}
        {row.state === "ending" && <Pill kind="warn">Ending</Pill>}
        {row.state === "ended" && <Pill>Ended</Pill>}
        {row.state === "waiting" && <Pill kind="warn">Waiting for you to agree</Pill>}
      </p>
      {/* 2026-11-17: the schedule on its own line, and how stopping works,
          said before anyone presses Stop. */}
      <p style={{ marginTop: 0 }}>{row.billed_words ?? `Billed ${row.timing_words}`}</p>
      {(row.state === "waiting" || row.state === "active") && row.stop_rule && (
        <p className="small">{row.stop_rule}</p>
      )}
      {row.pending && (
        <p className="small">From {longDate(row.pending.from)}: {dollars(row.pending.total_cents)}
          {" "}each time.</p>
      )}

      {row.state === "waiting" && (
        <>
          <p className="small" style={{ whiteSpace: "pre-wrap" }} aria-label="The terms">
            {row.words}</p>
          {card?.paused && <Banner kind="warn">{PAYMENTS_PAUSED}</Banner>}
          {saved && !adding ? (
            <p className="small">Charged to <strong>{saved.brand || "the card"} ending
              {" "}{saved.last4}</strong>, expires {saved.expires}.{" "}
              {!card?.paused && <button className="link" onClick={() => setAdding(true)}>
                Use another card</button>}</p>
          ) : !card?.paused && card?.ready ? (
            <>
              <p className="small">First, save the card it is charged to.</p>
              <NmiCardForm publicKey={card.public_key} amountCents={0} payPath={CARD + "card/"}
                buttonText="Save this card" onDone={() => undefined} form={card.card_form}
                failurePath={CARD + "form-failed/"}
                onToken={async (token) => {
                  try {
                    onCard(await api.post<AutopayState>(CARD + "card/", { payment_token: token }));
                    setAdding(false);
                    return true;
                  } catch (e) {
                    setError((e as Error).message);
                    return (e as Error).message;
                  }
                }} />
            </>
          ) : null}
          {saved && (
            <>
              <label className="row tight">
                <input type="checkbox" checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)} />
                I agree to these terms
              </label>
              <button className="primary small" disabled={!agreed || act.isPending}
                onClick={() => act.mutate({ path: "agree/", body: {
                  agree: true, version: row.version, key: row.key } })}>
                Agree and start automatic billing</button>
            </>
          )}
        </>
      )}

      {row.state === "active" && (
        <>
          <p className="small">Agreed {row.agreed_at ? longDate(row.agreed_at.slice(0, 10)) : ""}
            {row.agreed_by ? ` by ${row.agreed_by}` : ""}.
            {row.next_billing_on && <> Next billing date: {longDate(row.next_billing_on)}.</>}
            {saved && <> Charged to the card ending {saved.last4}.</>}</p>
          {preview === null ? (
            <button className="small" disabled={ask.isPending} onClick={() => ask.mutate()}>
              Stop automatic billing</button>
          ) : (
            <div role="dialog" aria-label="Stop automatic billing?">
              <Banner kind="warn">{preview}</Banner>
              <div className="row tight">
                <button className="primary small" disabled={act.isPending}
                  onClick={() => act.mutate({ path: "stop/" })}>
                  Confirm: stop automatic billing</button>
                <button className="ghost small" onClick={() => setPreview(null)}>
                  Keep it</button>
              </div>
            </div>
          )}
        </>
      )}

      {row.state === "ending" && row.ends_on && (
        <>
          <p className="small">Billing continues through {longDate(row.ends_on)}.{" "}
            {row.last_charge_on ? <>Your last charge will be on {longDate(row.last_charge_on)}.</>
              : <>There will be no further charge.</>}</p>
          {row.can_withdraw && (
            <button className="small" disabled={act.isPending}
              onClick={() => act.mutate({ path: "withdraw/" })}>
              Withdraw my notice</button>
          )}
        </>
      )}

      {row.state === "ended" && (
        <p className="small muted">Automatic billing ended
          {row.ended_on ? ` ${longDate(row.ended_on)}` : ""}. Nothing more is billed under it.</p>
      )}
    </section>
  );
}
