import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ScorecardSetup } from "../components/ScorecardSetup";
import { PageHead } from "../components/shell";
import { Banner } from "../components/ui";
import { Company, Me, api } from "../lib/api";
import { useWords } from "../lib/words";

export interface PracticeHolder { id: string; name: string }

export function usePracticeScorecard() {
  return useQuery<PracticeHolder>({
    queryKey: ["practice-scorecard"], queryFn: () => api.get<PracticeHolder>("/api/scorecard/practice/"),
  });
}

/**
 * "My practice": the practice's own scorecard set up, as a client's is on its
 * company page. Its pages are for the practice's people (everyone, the owner
 * and associates, each their own, the owner alone), and a KPI can be read
 * "From this app" (from the tile's Details).
 */
export function PracticeScorecardSetup({ me }: { me: Me }) {
  const w = useWords();
  const holder = usePracticeScorecard();
  if (holder.isError) return <Banner kind="bad">{(holder.error as Error).message}</Banner>;
  if (!holder.data) return <p className="muted">Loading…</p>;
  const company = { id: holder.data.id, name: holder.data.name, is_client_company: true } as unknown as Company;
  return (
    <>
      <PageHead title={`My practice: ${w.scorecard} setup`}
        sub={<>The practice's own numbers, on the same {w.scorecard}. <Link to={`/companies/${holder.data.id}/scorecard`}>Open
          it</Link>.</>} />
      <ScorecardSetup me={me} company={company} />
    </>
  );
}
