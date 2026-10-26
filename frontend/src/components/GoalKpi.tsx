import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { StatusPill } from "./ScorecardTiles";
import { Banner, Card } from "./ui";
import { GoalKpi, Me, WorkParent, api } from "../lib/api";
import { SetupState, Status } from "../lib/scorecard";
import { useWords } from "../lib/words";

/** M5 ties: a goal's KPI, its latest reading and status, on the goal's card
 *  and in the portal. The server sends it only to someone who may see that
 *  KPI, and on a per-person KPI says whose number it is. */
export function GoalKpiLine({ kpi }: { kpi?: GoalKpi | null }) {
  if (!kpi) return null;
  const name = kpi.whose ? `${kpi.name} (${kpi.whose})` : kpi.name;
  return (
    <p className="goal-kpi" aria-label={`KPI: ${name}`}>
      <span className="goal-kpi-name">{name}</span>
      {kpi.value_text ? <>
        <strong className="goal-kpi-value">{kpi.value_text}</strong>
        {kpi.target_text && <span className="muted">{kpi.target_text}</span>}
        {kpi.status && <StatusPill status={kpi.status as Status} />}
        <span className="muted">{kpi.period}</span>
      </> : <span className="muted">no reading yet</span>}
    </p>
  );
}

/** The goal page's KPI card: the practice owner and associates choose which of
 *  the company's KPIs the goal shows. */
export function GoalKpiCard({ me, goal }: { me: Me; goal: WorkParent }) {
  const w = useWords();
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const sets = me.role === "FF" || me.role === "CF";
  const company = goal.client_company;
  const setup = useQuery<SetupState>({
    queryKey: ["scorecard-setup", company],
    queryFn: () => api.get<SetupState>(`/api/scorecard/setup/?company=${company}`),
    enabled: sets && !!company,
  });
  const save = useMutation({
    mutationFn: (kpi: string | null) => api.patch<WorkParent>(`/api/goals/${goal.id}/`, { kpi }),
    onSuccess: () => { setError(""); qc.invalidateQueries({ queryKey: ["goal", goal.id] }); },
    onError: (e: Error) => setError(e.message),
  });
  if (!company || (!sets && !goal.kpi)) return null;
  const kpis = (setup.data?.kpis ?? []).filter((k) => !k.archived);
  return (
    <Card title={w.Kpi}>
      {error && <Banner kind="bad">{error}</Banner>}
      {goal.kpi ? <GoalKpiLine kpi={goal.kpi} /> : (
        <p className="small muted" style={{ marginTop: 0 }}>
          No {w.kpi} linked. Link one and this {w.goal}'s card shows its latest reading and status, here and in
          the portal, to whoever may see that {w.kpi}.</p>
      )}
      {sets && (
        <div className="row tight">
          <label htmlFor="goal-kpi" className="small">{w.Kpi} it shows</label>
          <select id="goal-kpi" value={goal.kpi?.kpi ?? ""} disabled={save.isPending || !setup.data}
            onChange={(e) => save.mutate(e.target.value || null)}>
            <option value="">None</option>
            {kpis.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
          {setup.data && kpis.length === 0 && (
            <span className="small muted">This company's {w.scorecard} has no {w.kpis} yet:{" "}
              <Link to={`/companies/${company}#scorecard-setup`}>set it up</Link>.</span>
          )}
        </div>
      )}
    </Card>
  );
}
