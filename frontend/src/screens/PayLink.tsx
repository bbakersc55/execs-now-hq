import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { NmiCardForm } from "../components/NmiCardForm";
import { Banner, Card, Pill } from "../components/ui";
import { PayLinkPage, PayResult, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * The signed pay link (P4 part 3). **No sign-in, and no role**: the token in
 * the link is the whole of the authentication and reaches one invoice. The
 * page shows the practice, the invoice's number, the amount due, the due
 * date, its PDF and the card form, and nothing else.
 */
export function PayLink() {
  const { token } = useParams();
  const qc = useQueryClient();
  const path = `/api/pay/${token}`;
  const [outcome, setOutcome] = useState<{ kind: "ok" | "warn" | "bad"; text: string } | null>(
    null);
  const page = useQuery<PayLinkPage>({
    queryKey: ["pay-link", token], queryFn: () => api.get<PayLinkPage>(path), retry: false });

  if (page.isLoading) return <main style={{ padding: "2rem" }}>Opening the invoice…</main>;
  if (page.isError) {
    return (
      <main style={{ padding: "2rem", maxWidth: "34rem" }}>
        <Banner kind="bad">{(page.error as Error).message}</Banner>
      </main>
    );
  }
  const data = page.data!;
  const finished = (result: PayResult) => {
    setOutcome({ kind: result.status === "approved" ? "ok"
      : result.status === "unknown" ? "warn" : "bad", text: result.message });
    if (result.status !== "declined") qc.invalidateQueries({ queryKey: ["pay-link", token] });
  };

  return (
    <main style={{ padding: "2rem 1rem", maxWidth: "34rem", margin: "0 auto" }}>
      <p className="muted" style={{ marginBottom: ".25rem" }}>{data.practice}</p>
      <h1 style={{ marginTop: 0 }}>
        Invoice {data.number}{" "}
        {data.paid ? <Pill kind="ok">Paid</Pill>
          : data.test_mode && <Pill kind="warn">Test mode</Pill>}
      </h1>
      {outcome && <div role={outcome.kind === "ok" ? "status" : "alert"}>
        <Banner kind={outcome.kind}>{outcome.text}</Banner></div>}
      <Card>
        <dl className="facts">
          <dt>Amount due</dt><dd><strong>{dollars(data.amount_due_cents)}</strong></dd>
          <dt>Due</dt><dd>{longDate(data.due_date)}</dd>
        </dl>
        <a className="btn small" href={`${path}/pdf`}
          aria-label={`Download invoice ${data.number}`}>Download the invoice (PDF)</a>
      </Card>
      {data.paid ? null : data.public_key ? (
        <Card title="Pay by card">
          {data.test_mode && (
            <p className="small muted" style={{ marginTop: 0 }}>Test mode: this practice's
              card account is a test account, so no real money moves.</p>
          )}
          <NmiCardForm publicKey={data.public_key} amountCents={data.amount_due_cents}
            payPath={path} onDone={finished} />
        </Card>
      ) : data.notice && !outcome ? <Banner kind="warn">{data.notice}</Banner> : null}
    </main>
  );
}
