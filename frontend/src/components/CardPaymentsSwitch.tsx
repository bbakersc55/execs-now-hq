import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CardPaymentsSwitch as SwitchState, api } from "../lib/api";
import { Banner, Card, Pill } from "./ui";

const URL = "/api/platform/card-payments/";

/**
 * The Practices area's "Card payments" card (2026-11-10): the platform
 * owner's "Pause card payments" switch, for every practice and the
 * platform's own account. Paused, pay buttons and pay links say "Card
 * payments are paused" and nothing is charged or saved; lookups and the
 * read-back go on. Also says what answers card payments on this server.
 */
export function CardPaymentsSwitchCard() {
  const qc = useQueryClient();
  const state = useQuery<SwitchState>({ queryKey: ["card-payments-switch"],
    queryFn: () => api.get<SwitchState>(URL) });
  const flip = useMutation({
    mutationFn: (paused: boolean) => api.post<SwitchState>(URL, { paused }),
    onSuccess: (next) => qc.setQueryData(["card-payments-switch"], next),
  });
  const s = state.data;
  return (
    <Card title="Card payments">
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      {flip.isError && <Banner kind="bad">{(flip.error as Error).message}</Banner>}
      {s && (
        <>
          <p style={{ marginTop: 0 }}>
            {s.paused === "" ? <Pill kind="ok">Taking card payments</Pill>
              : <Pill kind="warn">Card payments are paused</Pill>}{" "}
            <span className="small muted">
              {s.live_calls ? "Real calls on" : "Real calls off"} · {s.environment} ·{" "}
              <span className="mono">{s.api_host}</span> ·{" "}
              {s.card_form === "collect" ? "Collect.js" : "NMI Payment Component"}
            </span>
          </p>
          {s.paused === "off" && (
            <p className="small">Paused because real calls to the card processor are off on
              this server (NMI_LIVE_CALLS). The switch below can't resume them.</p>
          )}
          <p className="small muted">
            Paused, every practice's pay buttons and pay links say "Card payments are paused",
            no card is charged or saved, and practice subscriptions wait. Lookups of earlier
            payments and the daily read-back go on.
            {s.held && s.changed_by && <> Paused by {s.changed_by}.</>}
          </p>
          <button className={s.held ? "primary" : ""} disabled={flip.isPending}
            onClick={() => flip.mutate(!s.held)}>
            {s.held ? "Resume card payments" : "Pause card payments"}</button>
        </>
      )}
    </Card>
  );
}
