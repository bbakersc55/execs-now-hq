import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Pill } from "../components/ui";
import { AutopayState, PAYMENTS_PAUSED, api } from "../lib/api";
import { longDate } from "../lib/money";

const ROOT = "/api/portal-autopay/";

/**
 * P4 part 4: the company's card on file and auto-pay, under Invoices. A
 * client owner's only: for a client team member the server answers 403 and
 * nothing shows. The card is typed into NMI's own fields and saved in the
 * practice's card vault; this app keeps the brand, last four and expiry.
 *
 * 2026-11-17: beside automatic billing, auto-pay is "Auto-pay for other
 * invoices": automatic billing is charged under its own agreement and is
 * not changed here. Its offer shows only when the client asks for it, so
 * saving a card to agree to automatic billing never puts a second "I agree"
 * in front of them. "Remove the card" is off, with the reason, while
 * automatic billing is still billing (through its end date).
 */
export function ClientAutopay() {
  const qc = useQueryClient();
  const state = useQuery<AutopayState>({
    queryKey: ["portal-autopay"], queryFn: () => api.get<AutopayState>(ROOT), retry: false });
  const [adding, setAdding] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [asked, setAsked] = useState(false);
  const [error, setError] = useState("");
  const settle = (next: AutopayState) => {
    setError("");
    qc.setQueryData(["portal-autopay"], next);
  };
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api.post<AutopayState>(ROOT + path, body ?? {}),
    onSuccess: (next) => { settle(next); setAgreed(false); setAsked(false); },
    onError: (e: Error) => setError(e.message),
  });

  if (state.isError || !state.data || !state.data.ready) return null;
  const data = state.data;
  // Automatic billing waiting to be agreed, or still billing.
  const automatic = data.automatic ?? null;
  const hold = data.card_hold ?? "";
  const practice = data.practice || "the practice";

  return (
    <Card title={automatic ? "Card on file" : "Card on file and auto-pay"}>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {data.card ? (
        <p style={{ marginTop: 0 }}>
          <strong>{data.card.brand || "Card"} ending {data.card.last4}</strong>, expires{" "}
          {data.card.expires}{data.card.added_by ? `, added by ${data.card.added_by}` : ""}.{" "}
          {data.card.is_test ? <Pill kind="warn">Test card</Pill>
            : data.test_mode && <Pill kind="warn">Test mode</Pill>}
        </p>
      ) : (
        <p style={{ marginTop: 0 }}>No card on file.{" "}
          {data.test_mode && <Pill kind="warn">Test mode</Pill>}</p>
      )}
      {data.paused && <Banner kind="warn">{PAYMENTS_PAUSED}</Banner>}
      <div className="row tight">
        {!data.paused && (
          <button className="small" onClick={() => setAdding(!adding)}>
            {adding ? "Cancel" : data.card ? "Replace the card" : "Save a card"}</button>
        )}
        {data.card && (
          <button className="small ghost" disabled={!!hold || act.isPending}
            aria-describedby={hold ? "card-hold" : undefined}
            onClick={() => act.mutate({ path: "remove-card/" })}>
            Remove the card</button>
        )}
      </div>
      {data.card && hold && <p id="card-hold" className="small muted">{hold}</p>}
      {adding && !data.paused && (
        <NmiCardForm publicKey={data.public_key} amountCents={0} payPath={ROOT + "card/"}
          buttonText="Save this card" onDone={() => undefined} form={data.card_form}
          failurePath={ROOT + "form-failed/"}
          onToken={async (token) => {
            try {
              settle(await api.post<AutopayState>(ROOT + "card/", { payment_token: token }));
              setAdding(false);
              return true;
            } catch (e) {
              setError((e as Error).message);
              return (e as Error).message;
            }
          }} />
      )}

      {automatic ? (
        <OtherInvoices data={data} automatic={automatic} practice={practice} asked={asked}
          agreed={agreed} busy={act.isPending} onAsk={setAsked} onAgree={setAgreed}
          onOn={() => act.mutate({ path: "consent/",
            body: { agree: true, version: data.wording_version } })}
          onOff={() => act.mutate({ path: "revoke/" })} />
      ) : data.autopay ? (
        <>
          <p><Pill kind="ok">Auto-pay on</Pill> since {longDate(data.autopay.since.slice(0, 10))},
            turned on by {data.autopay.by}. Each invoice from {practice} is charged to the card
            on file on its due date.</p>
          <button className="small" onClick={() => act.mutate({ path: "revoke/" })}>
            Turn auto-pay off</button>
        </>
      ) : data.card ? (
        <>
          <p className="small" style={{ whiteSpace: "pre-wrap" }}>{data.wording}</p>
          <label className="row tight">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            I agree
          </label>
          <button className="primary small" disabled={!agreed || act.isPending}
            onClick={() => act.mutate({ path: "consent/",
              body: { agree: true, version: data.wording_version } })}>
            Turn auto-pay on</button>
        </>
      ) : null}
    </Card>
  );
}


/** Auto-pay beside automatic billing: for the other invoices only, said so,
 *  and offered only when asked for. */
function OtherInvoices({ data, automatic, practice, asked, agreed, busy, onAsk, onAgree, onOn,
  onOff }: {
  data: AutopayState; automatic: { billing: boolean; through: string | null };
  practice: string; asked: boolean; agreed: boolean; busy: boolean;
  onAsk: (asked: boolean) => void; onAgree: (agreed: boolean) => void;
  onOn: () => void; onOff: () => void;
}) {
  const keeps = !automatic.billing ? null : automatic.through
    ? <>Automatic billing continues through {longDate(automatic.through)}.</>
    : <>Automatic billing keeps running under its agreement; to end it, press Stop automatic
      billing above.</>;
  return (
    <section aria-label="Auto-pay for other invoices" style={{ marginTop: "1rem" }}>
      <h4 style={{ marginBottom: "0.25rem" }}>Auto-pay for other invoices</h4>
      <p className="small" style={{ marginTop: 0 }}>Automatic billing is charged under its own
        agreement, in the Automatic billing box above, and isn't changed here.</p>
      {data.autopay ? (
        <>
          <p><Pill kind="ok">Auto-pay on</Pill> since {longDate(data.autopay.since.slice(0, 10))},
            turned on by {data.autopay.by}. Other invoices from {practice} are charged to the
            card on file on their due dates.</p>
          <button className="small" disabled={busy} onClick={onOff}>
            Turn auto-pay off for other invoices</button>
          {keeps && <p className="small muted">{keeps}</p>}
        </>
      ) : !data.card ? null : !asked ? (
        <p className="small"><button className="link" onClick={() => onAsk(true)}>
          Also pay other invoices automatically?</button></p>
      ) : (
        <>
          <p className="small" style={{ whiteSpace: "pre-wrap" }}>{data.wording}</p>
          <p className="small muted">This doesn't cover automatic billing, which is charged
            under its own agreement.</p>
          <label className="row tight">
            <input type="checkbox" checked={agreed} onChange={(e) => onAgree(e.target.checked)} />
            I agree
          </label>
          <div className="row tight">
            <button className="primary small" disabled={!agreed || busy} onClick={onOn}>
              Turn auto-pay on for other invoices</button>
            <button className="ghost small" onClick={() => { onAsk(false); onAgree(false); }}>
              Not now</button>
          </div>
        </>
      )}
    </section>
  );
}
