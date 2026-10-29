import { useQuery } from "@tanstack/react-query";

import { PageHead } from "../components/shell";
import { Card, Empty, Pill } from "../components/ui";
import { DocumentState, SignDocument, api } from "../lib/api";
import { longDate } from "../lib/money";

const PILL: Record<DocumentState, "" | "ok" | "warn" | "bad"> = {
  draft: "", sent: "warn", viewed: "warn", signed: "", declined: "bad", countersigned: "ok",
  complete: "ok", void: "bad", expired: "bad",
};

function day(iso: string | null) {
  return iso ? longDate(iso.slice(0, 10)) : "";
}

/**
 * The portal's Documents (e-signature, 2026-10-29): the documents sent to
 * your company for signature, from the day they were sent, and the signed
 * copy once both sides have signed. Signing is from the emailed link.
 */
export function PortalDocuments() {
  const list = useQuery<SignDocument[]>({
    queryKey: ["portal-documents"],
    queryFn: () => api.get<SignDocument[]>("/api/portal-documents/"),
  });
  const rows = list.data ?? [];
  return (
    <>
      <PageHead title="Documents"
        sub="Proposals, letters and agreements sent to your company to sign. Each is signed
             from the link in its email." />
      <Card>
        {rows.length === 0 ? <Empty>{list.isLoading ? "Loading…" : "Nothing sent to sign yet."}</Empty> : (
          <table className="cards-on-phone">
            <thead><tr><th>Document</th><th>For</th><th>Where it is</th><th /></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  <td data-label="Document"><strong>{d.title}</strong>
                    {d.sent_at && <div className="small muted">Sent {day(d.sent_at)}</div>}</td>
                  <td data-label="For">{d.signer.name}</td>
                  <td data-label="Where it is"><Pill kind={PILL[d.state]}>{d.state_label}</Pill>
                    {d.completed_at && <div className="small muted">Complete {day(d.completed_at)}</div>}
                    {(d.state === "sent" || d.state === "viewed") && d.expires_at && (
                      <div className="small muted">Sign by {day(d.expires_at)}</div>)}</td>
                  <td data-label="">{d.has_pdf && (
                    <a className="btn small ghost" href={`/api/portal-documents/${d.id}/pdf/`}
                      target="_blank" rel="noreferrer">
                      {d.state === "complete" ? "Signed copy" : "PDF"}</a>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
