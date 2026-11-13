import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { SopList } from "../lib/sops";

/** On a KPI's Details (P10): the SOPs meant to move this number. Nothing
 *  shows when there are none, or when the practice has no SOP studio. */
export function SopsForKpi({ kpiId }: { kpiId: string }) {
  const q = useQuery<SopList>({ queryKey: ["sops", "kpi", kpiId],
    queryFn: () => api.get<SopList>(`/api/sops/?kpi=${kpiId}`), retry: false });
  const rows = q.data?.sops ?? [];
  if (!rows.length) return null;
  return (
    <div className="sc-back-sops" role="group" aria-label="SOPs for this number">
      <strong>SOPs for this number.</strong>{" "}
      {rows.map((s, i) => <span key={s.id}>{i > 0 && " · "}<Link to={`/sops/${s.id}`}>{s.title}</Link></span>)}
    </div>
  );
}
