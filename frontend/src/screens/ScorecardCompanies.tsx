import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty } from "../components/ui";
import { api } from "../lib/api";
import { useWords } from "../lib/words";

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
export function ScorecardCompanies() {
  const w = useWords();
  const list = useQuery<ScorecardCompany[]>({
    queryKey: ["scorecard-companies"],
    queryFn: () => api.get<ScorecardCompany[]>("/api/scorecard/companies/"),
  });
  const rows = list.data ?? [];
  return (
    <>
      <PageHead title={w.Scorecards}
        sub={`Choose a client to open their ${w.scorecard}.`} />
      {list.isError && <Banner kind="bad">{(list.error as Error).message}</Banner>}
      <Card>
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
      </Card>
    </>
  );
}
