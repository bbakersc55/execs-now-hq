import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHead } from "../components/shell";
import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { PayConfig, PayResult, PortalInvoice, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * A client's own invoices (P4A; matrix 13.4a, the client columns). A client
 * owner and a client team member both see what their company was sent: the
 * number, the dates, the total, what is still owed, and the PDF as it was
 * emailed. Never a draft, and never another company's.
 *
 * P4 part 2: Pay, by card, for the whole balance, into the practice's own
 * NMI account. The card is typed into NMI's own fields; this app only ever
 * receives a one-time token.
 */
export function ClientInvoices() {
  const qc = useQueryClient();
  const rows = useQuery<PortalInvoice[]>({
    queryKey: ["portal-invoices"],
    queryFn: () => api.get<PortalInvoice[]>("/api/portal-invoices/") });
  const [paying, setPaying] = useState<PortalInvoice | null>(null);
  const [outcome, setOutcome] = useState<{ kind: "ok" | "warn" | "bad"; text: string } | null>(
    null);
  if (rows.isError) return <Banner kind="bad">{(rows.error as Error).message}</Banner>;
  const list = rows.data ?? [];
  const finished = (result: PayResult) => {
    setOutcome({ kind: result.status === "approved" ? "ok"
      : result.status === "unknown" ? "warn" : "bad", text: result.message });
    if (result.status !== "declined") setPaying(null);
    qc.invalidateQueries({ queryKey: ["portal-invoices"] });
  };
  return (
    <>
      <PageHead title="Invoices" sub="The invoices sent to your company, and what is still owed." />
      {outcome && <div role={outcome.kind === "ok" ? "status" : "alert"}>
        <Banner kind={outcome.kind}>{outcome.text}</Banner></div>}
      <Card>
        {!rows.data ? <p>Loading your invoices…</p> : list.length === 0
          ? <Empty>No invoices yet.</Empty> : (
            <table>
              <thead><tr><th>Number</th><th>Issued</th><th>Due</th>
                <th className="money">Total</th><th className="money">Still owed</th>
                <th>Status</th><th /></tr></thead>
              <tbody>
                {list.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.number}</strong></td>
                    <td>{longDate(row.issue_date)}</td>
                    <td>{longDate(row.due_date)}</td>
                    <td className="money">{dollars(row.total_cents)}</td>
                    <td className="money">{row.status === "void" ? "" : dollars(row.balance_cents)}</td>
                    <td>
                      <Pill kind={row.status === "paid" ? "ok" : row.status === "void" ? "" : "warn"}>
                        {row.status === "sent" ? "Open" : row.status_label}</Pill>
                      {row.overdue && <> <Pill kind="bad">Due {longDate(row.due_date)}</Pill></>}
                      {row.payment_in_progress && <> <Pill kind="warn">Payment being checked</Pill></>}
                    </td>
                    <td className="money">
                      <div className="row tight" style={{ justifyContent: "flex-end" }}>
                        {row.can_pay && (
                          <button className="primary small" aria-label={`Pay invoice ${row.number}`}
                            onClick={() => { setOutcome(null); setPaying(row); }}>
                            Pay {dollars(row.balance_cents)}</button>
                        )}
                        <a className="btn small" href={`/api/portal-invoices/${row.id}/pdf/`}
                          aria-label={`Download invoice ${row.number}`}>Download</a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
      {paying && <PayPanel invoice={paying} onDone={finished}
        onCancel={() => setPaying(null)} />}
    </>
  );
}

/** The card form for one invoice, with the practice's public key fetched
 *  when someone presses Pay. */
function PayPanel({ invoice, onDone, onCancel }: {
  invoice: PortalInvoice; onDone: (result: PayResult) => void; onCancel: () => void;
}) {
  const config = useQuery<PayConfig>({
    queryKey: ["pay-config", invoice.id],
    queryFn: () => api.get<PayConfig>(`/api/portal-invoices/${invoice.id}/pay/`),
    staleTime: 0, gcTime: 0 });

  return (
    <Card title={`Pay invoice ${invoice.number}`}
      actions={<button className="ghost" onClick={onCancel}>Cancel</button>}>
      {config.isError && <Banner kind="bad">{(config.error as Error).message}</Banner>}
      {config.data && (
        <>
          <p style={{ marginTop: 0 }}>
            <strong>{dollars(config.data.amount_cents)}</strong>, the whole balance, by card.{" "}
            {config.data.test_mode && <Pill kind="warn">Test mode</Pill>}
          </p>
          {config.data.test_mode && (
            <p className="small muted">Test mode: this practice's card account is a test
              account, so no real money moves.</p>
          )}
          <NmiCardForm publicKey={config.data.public_key} amountCents={config.data.amount_cents}
            payPath={`/api/portal-invoices/${invoice.id}/pay/`} onDone={onDone} />
        </>
      )}
    </Card>
  );
}
