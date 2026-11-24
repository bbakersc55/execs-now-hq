import { useQuery } from "@tanstack/react-query";
import { agreements } from "../lib/agreements";
import { Card } from "./ui";

/** Final owner agreements in a company's Documents (owner, 2026-11-23): shown
 *  only to people ticked for owner agreements or signed PDFs, the practice
 *  owner and the Client owner; the server sends nobody else any. */
export function OwnerAgreementDocs({ companyId }: { companyId: string | null }) {
  const { data } = useQuery({ queryKey: ["agreement-docs", companyId],
    queryFn: () => agreements.documents(companyId ?? ""), enabled: !!companyId });
  const rows = data?.documents ?? [];
  if (!rows.length) return null;
  return (
    <Card title="Owner agreements">
      <ul className="plain">
        {rows.map((d) => (
          <li key={d.id} className="spread wrap" style={{ gap: ".5rem", padding: ".35rem 0" }}>
            <span><strong>{d.title}</strong> · {d.owner}
              <span className="small muted"> · {d.property}{d.date ? ` · dated ${d.date}` : ""}
              </span></span>
            <a className="btn small ghost" href={d.pdf} target="_blank" rel="noreferrer">
              Signed copy</a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
