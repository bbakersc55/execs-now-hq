import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { SignatureCapture, hasSignature } from "../components/SignatureCapture";
import { Banner, Card } from "../components/ui";
import { CapturedSignature, SigningPage, api } from "../lib/api";
import { longDate } from "../lib/money";

/**
 * The signing page (e-signature, 2026-10-29). **No sign-in**: the link is
 * the whole of the authentication and reaches one document. It shows the
 * PDF, the consent line, and a typed or drawn signature; or Decline, with a
 * reason. Made for a phone first: the PDF opens full-size from its own link
 * as well as in the frame.
 */
export function SignDocument() {
  const { token } = useParams();
  const path = `/api/sign/${token}`;
  const page = useQuery<SigningPage>({
    queryKey: ["sign", token], queryFn: () => api.get<SigningPage>(path), retry: false,
    refetchOnWindowFocus: false,
  });
  const [signature, setSignature] = useState<CapturedSignature | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);
  const [problem, setProblem] = useState("");

  const sign = useMutation({
    mutationFn: (value: CapturedSignature) =>
      api.post<{ detail: string }>(path, { agreed, ...value }),
    onSuccess: (r) => { setProblem(""); setDone({ kind: "ok", text: r.detail }); },
    onError: (e: Error) => setProblem(e.message),
  });
  const decline = useMutation({
    mutationFn: () => api.post<{ detail: string }>(`${path}/decline`, { reason }),
    onSuccess: (r) => { setProblem(""); setDone({ kind: "warn", text: r.detail }); },
    onError: (e: Error) => setProblem(e.message),
  });

  if (page.isLoading) return <main className="sign-page">Opening the document…</main>;
  if (page.isError) {
    return (
      <main className="sign-page">
        <Banner kind="bad">{(page.error as Error).message}</Banner>
      </main>
    );
  }
  const data = page.data!;
  const value = signature ?? { method: "typed" as const, typed: data.signer_name, drawn: "" };
  const ready = agreed && hasSignature(value);

  return (
    <main className="sign-page">
      <p className="muted" style={{ marginBottom: 0 }}>{data.practice}</p>
      <h1>{data.title}</h1>
      <p className="small muted" style={{ marginTop: 0 }}>
        For {data.signer_name} ({data.signer_email})
        {data.expires_at && <> · the link works until {longDate(data.expires_at.slice(0, 10))}</>}
      </p>
      {done ? (
        <div role="status"><Banner kind={done.kind}>{done.text}</Banner></div>
      ) : (
        <>
          <Card>
            <iframe className="pdf-frame" title={data.title} src={`${path}/pdf`} />
            <p className="small" style={{ marginBottom: 0 }}>
              <a href={`${path}/pdf`} target="_blank" rel="noreferrer">
                Open the document full size</a>
              <span className="muted"> · SHA-256 {data.sha256.slice(0, 16)}…</span>
            </p>
          </Card>
          {problem && <div role="alert"><Banner kind="bad">{problem}</Banner></div>}
          {!declining ? (
            <Card title="Sign">
              <SignatureCapture value={value} onChange={setSignature} consent={data.consent_text}
                agreed={agreed} onAgree={setAgreed} />
              <div className="row tight" style={{ marginTop: "var(--s3)" }}>
                <button className="primary" disabled={!ready || sign.isPending}
                  onClick={() => sign.mutate(value)}>
                  {sign.isPending ? "Signing…" : "Sign"}</button>
                <button className="ghost" onClick={() => setDeclining(true)}>Decline</button>
              </div>
              {!agreed && (
                <p className="small muted">Tick the consent line above to sign.</p>
              )}
            </Card>
          ) : (
            <Card title="Decline">
              <label>Why are you declining? {data.practice} will see this.
                <textarea aria-label="Why you are declining" rows={3} value={reason}
                  onChange={(e) => setReason(e.target.value)} />
              </label>
              <div className="row tight" style={{ marginTop: "var(--s3)" }}>
                <button className="danger" disabled={!reason.trim() || decline.isPending}
                  onClick={() => decline.mutate()}>
                  {decline.isPending ? "Declining…" : "Decline to sign"}</button>
                <button className="ghost" onClick={() => setDeclining(false)}>Back</button>
              </div>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
