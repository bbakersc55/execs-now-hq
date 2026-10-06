import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Company, Me, api } from "../lib/api";
import { Banner, Card } from "./ui";

/** How a company becomes a client, in the one wording used wherever only
 *  client companies are offered (beta feedback, 2026-10-05, item D). */
export const HOW_A_COMPANY_BECOMES_A_CLIENT =
  "A company becomes a client when one of its contacts reaches Closed Won on the "
  + "Pipeline, or when the practice owner marks it as a client on the company's page.";

interface Status { id: string; is_client_company: boolean; undo_blockers: string[] }

/**
 * Whether this company is a client, why that matters, and the practice
 * owner's way to say so by hand: a client who comes from a referral should
 * not have to be pushed through the sales pipeline first.
 *
 * Marking sets the company's client flag and nothing else. Undoing is for a
 * mistake, so it is offered only while nothing has been built on the mark,
 * and says what is in the way when something has.
 */
export function ClientStatus({ me, company }: { me: Me; company: Company }) {
  const qc = useQueryClient();
  const owner = me.role === "FF";
  const [asking, setAsking] = useState<"mark" | "unmark" | null>(null);
  const [problem, setProblem] = useState("");
  const status = useQuery<Status>({
    queryKey: ["company-client-status", company.id],
    queryFn: () => api.get<Status>(`/api/companies/${company.id}/client-status/`),
  });

  const change = useMutation({
    mutationFn: (action: "mark" | "unmark") =>
      api.post<Status>(`/api/companies/${company.id}/${action}-client/`),
    onSuccess: (next) => {
      qc.setQueryData(["company-client-status", company.id], next);
      // Everything that offers client companies reads these.
      qc.invalidateQueries({ queryKey: ["company", company.id] });
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["portal-candidates", company.id] });
      setAsking(null);
      setProblem("");
    },
    onError: (e: Error & { data?: Status }) => {
      if (e.data?.undo_blockers) qc.setQueryData(["company-client-status", company.id], e.data);
      setAsking(null);
      setProblem(e.message);
    },
  });

  const isClient = status.data?.is_client_company ?? company.is_client_company;
  const blockers = status.data?.undo_blockers ?? [];

  return (
    <Card title={isClient ? "Client company" : "Not a client company"}>
      {problem && <Banner kind="bad">{problem}</Banner>}
      {isClient ? (
        <p className="small" style={{ marginTop: 0 }}>
          This company can be chosen for goals, projects and tasks, and its people can be
          given portal access.
        </p>
      ) : (
        <p className="small" style={{ marginTop: 0 }}>
          Goals, projects, tasks and portal access are for client companies only, so this
          company is not offered for them yet. {HOW_A_COMPANY_BECOMES_A_CLIENT}{" "}
          <Link to="/pipeline">Open the Pipeline</Link>
        </p>
      )}

      {owner && !isClient && asking !== "mark" && (
        <button onClick={() => setAsking("mark")}>Mark as a client</button>
      )}
      {owner && asking === "mark" && (
        <div role="group" aria-label="Mark as a client">
          <p className="small"><strong>Mark {company.name} as a client?</strong></p>
          <ul className="small">
            <li><strong>It sets one thing:</strong> {company.name} becomes a client company,
              so it can be chosen for goals, projects and tasks and its people can be given
              portal access.</li>
            <li><strong>Unlike reaching Closed Won, it does not</strong> move anyone on the
              Pipeline, give any contact the client type, or run any stage automation: no
              task is created and no email is drafted.</li>
            <li>It is recorded, with your name, in the audit trail.</li>
          </ul>
          <div className="row tight">
            <button className="primary" disabled={change.isPending}
              onClick={() => change.mutate("mark")}>
              {change.isPending ? "Marking…" : "Yes, mark as a client"}
            </button>
            <button onClick={() => setAsking(null)}>Cancel</button>
          </div>
        </div>
      )}

      {owner && isClient && status.isSuccess && (
        <details className="small">
          <summary>Marked as a client by mistake?</summary>
          {blockers.length > 0 ? (
            <>
              <p>It cannot be undone while:</p>
              <ul>{blockers.map((line) => <li key={line}>{line}</li>)}</ul>
            </>
          ) : asking === "unmark" ? (
            <>
              <p>
                {company.name} will stop being offered for goals, projects, tasks and portal
                access. Nothing is deleted, and it is recorded in the audit trail.
              </p>
              <div className="row tight">
                <button className="danger" disabled={change.isPending}
                  onClick={() => change.mutate("unmark")}>
                  {change.isPending ? "Undoing…" : "Yes, it is not a client"}
                </button>
                <button onClick={() => setAsking(null)}>Cancel</button>
              </div>
            </>
          ) : (
            <>
              <p>Nothing has been built on it yet, so it can be undone.</p>
              <button onClick={() => setAsking("unmark")}>Not a client after all</button>
            </>
          )}
        </details>
      )}
    </Card>
  );
}
