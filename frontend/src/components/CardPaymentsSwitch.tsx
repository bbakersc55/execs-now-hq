import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CardPaymentsSwitch as SwitchState, WorkerState, api } from "../lib/api";
import { ClearTestPayments, GatewayModeBanner } from "./TestMode";
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
  // 2026-11-16: the platform account's own Test Mode, read again on demand,
  // and its test subscription charges cleared once it reads live.
  const read = useMutation({
    mutationFn: () => api.post<SwitchState>(`${URL}read-test-mode/`, {}),
    onSuccess: (next) => qc.setQueryData(["card-payments-switch"], next),
  });
  const clear = useMutation({
    mutationFn: (invoices: "reopen" | "void") =>
      api.post<SwitchState>(`${URL}clear-test-payments/`, { invoices }),
    onSuccess: (next) => {
      qc.setQueryData(["card-payments-switch"], next);
      qc.invalidateQueries({ queryKey: ["platform-practices"] });
    },
  });
  const s = state.data;
  return (
    <>
    <WorkerWarning worker={s?.worker} />
    <GatewayModeBanner mode={s?.gateway_mode}
      again="Turned it off at the processor? Read it again under Card payments." />
    <ClearTestPayments summary={s?.test_payments} busy={clear.isPending}
      onClear={(invoices) => clear.mutate(invoices)} />
    {clear.isError && <Banner kind="bad">{(clear.error as Error).message}</Banner>}
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
          <div className="row tight">
            <button className={s.held ? "primary" : ""} disabled={flip.isPending}
              onClick={() => flip.mutate(!s.held)}>
              {s.held ? "Resume card payments" : "Pause card payments"}</button>
            <button className="ghost" disabled={read.isPending} onClick={() => read.mutate()}>
              {read.isPending ? "Reading…" : "Read Test Mode now"}</button>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Refunds and cancels still go while payments are paused. Test Mode:{" "}
            {s.gateway_mode?.test_mode === true ? "on" : s.gateway_mode?.test_mode === false
              ? "off" : "not read yet"}
            {s.gateway_mode?.unknown && <> ({s.gateway_mode.unknown})</>}.
          </p>
        </>
      )}
    </Card>
    </>
  );
}

/**
 * 2026-11-17: in production, red when the worker (which runs every scheduled
 * card job: auto-pay, automatic billing, subscriptions, lookups, the
 * read-back) can't reach the card processor, when web and the worker
 * disagree, or when the worker has stopped reporting; with what each said
 * and today's refused jobs. Nothing here changes a setting.
 */
export function WorkerWarning({ worker }: { worker?: WorkerState }) {
  if (!worker?.warning) return null;
  const said = (row?: WorkerState["worker"]) => !row ? "has not reported"
    : `real calls ${row.live_calls ? "on" : "OFF"}, ${row.minutes_ago} min ago`;
  return (
    <div role="alert">
      <Banner kind="bad">
        <strong>{worker.warning}</strong>
        <div className="small">Web: {worker.web_live_calls ? "real calls on" : "real calls OFF"}
          {" "}· Worker: {said(worker.worker)}</div>
        {(worker.refused_today ?? []).length > 0 && (
          <ul className="small" aria-label="Refused today">
            {(worker.refused_today ?? []).map((row) => (
              <li key={row.job}>Refused today: {row.label}, {row.runs} run
                {row.runs === 1 ? "" : "s"} for {row.practices} practice
                {row.practices === 1 ? "" : "s"}</li>
            ))}
          </ul>
        )}
      </Banner>
    </div>
  );
}
