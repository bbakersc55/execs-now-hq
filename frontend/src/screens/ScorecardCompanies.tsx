import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty } from "../components/ui";
import { Me, api } from "../lib/api";
import { useWords } from "../lib/words";
import { usePracticeScorecard } from "./PracticeScorecard";

export interface ScorecardCompany {
  id: string; name: string; kpis: number; has_scorecard: boolean;
}

/**
 * The practice's Scorecard menu (Bryan, 2026-10-22): the clients this person
 * reaches, the practice owner every one and an associate those assigned to
 * them. One with a scorecard opens the same views as "Scorecard for this
 * client" on the company page; one without offers "Start one", which is the
 * setup on that company's page.
 */
export function ScorecardCompanies({ me }: { me?: Me }) {
  const w = useWords();
  // An assistant has My practice, not the clients' list.
  const clients = me?.role !== "VA";
  const list = useQuery<ScorecardCompany[]>({
    queryKey: ["scorecard-companies"],
    queryFn: () => api.get<ScorecardCompany[]>("/api/scorecard/companies/"),
    enabled: clients,
  });
  const rows = list.data ?? [];
  const mine = usePracticeScorecard();
  return (
    <>
      <PageHead title={w.Scorecards}
        sub={`Your practice's own ${w.scorecard}, and each client's.`} />
      {mine.data && (
        <Card title="My practice">
          <p className="small muted" style={{ marginTop: 0 }}>The practice's own numbers: leads, proposals, wins,
            introductions, invoices, cash and {w.tasks}, worked out from this app or entered by hand.</p>
          <Link className="btn small" to={`/companies/${mine.data.id}/scorecard`}
            aria-label={`Open my practice's ${w.scorecard}`}>Open</Link>
        </Card>
      )}
      {list.isError && <Banner kind="bad">{(list.error as Error).message}</Banner>}
      {clients && <Card>
        {!list.data ? <p className="muted">Loading…</p> : rows.length === 0
          ? <Empty>No clients yet.</Empty> : (
            <table aria-label="Clients">
              <thead><tr><th>Client</th><th>{w.Scorecard}</th><th /></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td>{c.has_scorecard
                      ? <Link to={`/companies/${c.id}/scorecard`}>{c.name}</Link> : c.name}</td>
                    <td className="muted">{c.has_scorecard
                      ? `${c.kpis} KPI${c.kpis === 1 ? "" : "s"}` : `No ${w.scorecard} yet`}</td>
                    <td className="money">{c.has_scorecard
                      ? <Link className="btn small" to={`/companies/${c.id}/scorecard`}
                          aria-label={`Open ${c.name}'s ${w.scorecard}`}>Open</Link>
                      : <Link className="btn small" to={`/companies/${c.id}#scorecard-setup`}
                          aria-label={`Start one for ${c.name}`}>Start one</Link>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>}
    </>
  );
}
