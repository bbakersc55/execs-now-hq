import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "./shell";
import { Banner } from "./ui";
import { api } from "../lib/api";

interface AppFeedState {
  kpi: { id: string; name: string; kind: string; per_person: boolean };
  measures: { key: string; label: string; kind: string; money: boolean; param: string }[];
  stages: { id: string; label: string }[];
  feed: { measure: string; param: string; param_label: string; text: string; last_error: string;
    last_success_at: string | null } | null;
}

/** "My practice": a KPI read "From this app", one measure of the practice's
 *  own data, per closed period, once a day. The money measures are listed
 *  for the practice owner only. */
export function AppFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<AppFeedState>({
    queryKey: ["app-feed", companyId, kpiId],
    queryFn: () => api.get<AppFeedState>(`/api/scorecard/app-feed/?company=${companyId}&kpi=${kpiId}`),
  });
  const [measure, setMeasure] = useState<string | null>(null);
  const [param, setParam] = useState<string | null>(null);
  const [error, setError] = useState("");
  const s = state.data;
  const chosen = measure ?? s?.feed?.measure ?? "";
  const def = s?.measures.find((m) => m.key === chosen);
  const stage = param ?? s?.feed?.param ?? "";
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; error?: string } }>("/api/scorecard/app-feed/",
      { company: companyId, kpi: kpiId, measure: chosen, param: def?.param === "stage" ? stage : "" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["app-feed", companyId, kpiId] });
      onSaved(r.run.ok ? `${s?.kpi.name} now comes from this app: ${r.run.new ?? 0} reading${r.run.new === 1 ? "" : "s"} for past periods.`
        : `${s?.kpi.name}'s measure is saved, but the first reading failed: ${r.run.error}`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/app-feed/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => onSaved("Entered by hand again. Its readings are kept."),
    onError: (e: Error) => setError(e.message),
  });
  const title = s ? `${s.kpi.name} from this app` : "From this app";
  return (
    <Modal label={title} title={title} onClose={onClose}>
      {!s ? <p>Loading…</p> : (
        <div className="track-feed">
          {s.feed && <p className="small muted" style={{ marginTop: 0 }}>{s.feed.text}.
            {s.feed.last_error && <> <strong>Last reading failed:</strong> {s.feed.last_error}</>}</p>}
          {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
          <label htmlFor="app-measure" className="small">Measure</label>
          <select id="app-measure" value={chosen} onChange={(e) => { setMeasure(e.target.value); setError(""); }}>
            <option value="">Choose a measure…</option>
            <optgroup label="The practice's work">
              {s.measures.filter((m) => !m.money).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </optgroup>
            {s.measures.some((m) => m.money) && (
              <optgroup label="Money (the practice owner sees these)">
                {s.measures.filter((m) => m.money).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </optgroup>
            )}
          </select>
          {def?.param === "stage" && (
            <>
              <label htmlFor="app-stage" className="small">Stage</label>
              <select id="app-stage" value={stage} onChange={(e) => setParam(e.target.value)}>
                <option value="">Choose a stage…</option>
                {s.stages.map((st) => <option key={st.id} value={st.id}>{st.label}</option>)}
              </select>
            </>
          )}
          {def?.money && <p className="small muted" style={{ margin: 0 }}>Only the practice owner sees this {""}
            KPI, whatever its page's audience.</p>}
          <p className="small muted">Worked out for each closed period once a day. A reading typed by hand is never
            replaced, and none is ever deleted.</p>
          <div className="row">
            <button className="primary" style={{ flex: "0 0 auto" }}
              disabled={!chosen || (def?.param === "stage" && !stage) || save.isPending}
              onClick={() => save.mutate()}>Save the measure</button>
            <button className="ghost" style={{ flex: "0 0 auto" }} onClick={onClose}>Cancel</button>
            {s.feed && <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => stop.mutate()}>Stop the feed</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
