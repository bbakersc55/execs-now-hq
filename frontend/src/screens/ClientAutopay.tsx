import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Pill } from "../components/ui";
import { AutopayState, api } from "../lib/api";
import { longDate } from "../lib/money";

const ROOT = "/api/portal-autopay/";

/**
 * P4 part 4: the company's card on file and auto-pay, under Invoices. A
 * client owner's only: for a client team member the server answers 403 and
 * nothing shows. The card is typed into NMI's own fields and saved in the
 * practice's card vault; this app keeps the brand, last four and expiry.
 */
export function ClientAutopay() {
  const qc = useQueryClient();
  const state = useQuery<AutopayState>({
    queryKey: ["portal-autopay"], queryFn: () => api.get<AutopayState>(ROOT), retry: false });
  const [adding, setAdding] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const settle = (next: AutopayState) => {
    setError("");
    qc.setQueryData(["portal-autopay"], next);
  };
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api.post<AutopayState>(ROOT + path, body ?? {}),
    onSuccess: (next) => { settle(next); setAgreed(false); },
    onError: (e: Error) => setError(e.message),
  });

  if (state.isError || !state.data || !state.data.ready) return null;
  const data = state.data;

  return (
    <Card title="Card on file and auto-pay">
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {data.card ? (
        <p style={{ marginTop: 0 }}>
          <strong>{data.card.brand || "Card"} ending {data.card.last4}</strong>, expires{" "}
          {data.card.expires}{data.card.added_by ? `, added by ${data.card.added_by}` : ""}.{" "}
          {data.test_mode && <Pill kind="warn">Test mode</Pill>}
        </p>
      ) : (
        <p style={{ marginTop: 0 }}>No card on file.{" "}
          {data.test_mode && <Pill kind="warn">Test mode</Pill>}</p>
      )}
      <div className="row tight">
        <button className="small" onClick={() => setAdding(!adding)}>
          {adding ? "Cancel" : data.card ? "Replace the card" : "Save a card"}</button>
        {data.card && (
          <button className="small ghost" onClick={() => act.mutate({ path: "remove-card/" })}>
            Remove the card</button>
        )}
      </div>
      {adding && (
        <NmiCardForm publicKey={data.public_key} amountCents={0} payPath={ROOT + "card/"}
          buttonText="Save this card" onDone={() => undefined}
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

      {data.autopay ? (
        <>
          <p><Pill kind="ok">Auto-pay on</Pill> since {longDate(data.autopay.since.slice(0, 10))},
            turned on by {data.autopay.by}. Each invoice is charged to the card on file on
            its due date.</p>
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
