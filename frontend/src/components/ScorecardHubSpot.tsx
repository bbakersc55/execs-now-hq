import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { Modal } from "./shell";
import { Banner, Card } from "./ui";
import { Me, api } from "../lib/api";

interface HubSpotConnection {
  connected: boolean; demo: boolean; token_last4?: string; scopes: string[];
  checked_at?: string | null; check_ok?: boolean | null; check_detail?: string;
}
interface Measure { key: string; label: string; object: string; kind: string; snapshot: boolean }
interface Options { measures: Measure[]; owners: { id: string; name: string; email: string }[];
  stages: { id: string; name: string }[]; error: string }
interface HubSpotFeedState {
  kpi: { id: string; name: string; kind: string; per_person: boolean }; connected: boolean;
  feed: { measure: string; label: string; owner_id: string; owner_name: string; stage_id: string;
    stage_name: string; text: string; last_success_at: string | null; last_error: string } | null;
}

const GROUPS: [string, string[]][] = [
  ["Deals", ["deals"]], ["Contacts", ["contacts"]], ["Activity logged", ["calls", "emails", "meetings"]],
];

/**
 * M5 part 5: a client company's HubSpot account, on the company page. The
 * practice owner pastes a private app's access token; it is stored encrypted
 * and never shown again. "Test connection" makes one read-only call.
 */
export function HubSpotConnectionCard({ me, companyId }: { me: Me; companyId: string }) {
  const qc = useQueryClient();
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const state = useQuery<HubSpotConnection>({
    queryKey: ["hubspot-connection", companyId],
    queryFn: () => api.get<HubSpotConnection>(`/api/scorecard/hubspot/connection/?company=${companyId}`),
  });
  const done = () => { qc.invalidateQueries({ queryKey: ["hubspot-connection", companyId] }); };
  const save = useMutation({
    mutationFn: () => api.put("/api/scorecard/hubspot/connection/", { company: companyId, token }),
    onSuccess: () => { setEditing(false); setToken(""); setError(""); done(); },
    onError: (e: Error) => setError(e.message),
  });
  const test = useMutation({
    mutationFn: () => api.post("/api/scorecard/hubspot/connection/test/", { company: companyId }),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/scorecard/hubspot/connection/?company=${companyId}`),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const s = state.data;
  if (!s) return null;
  const owner = me.role === "FF";
  return (
    <Card title="HubSpot">
      <p className="small muted" style={{ marginTop: 0 }}>
        Feeds deals, win rate, pipeline value, new contacts and logged activity into this company's scorecard.
        The client creates a private app in HubSpot and copies its access token; it is stored encrypted, and
        nobody at the practice sees it again.</p>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {s.demo && !s.connected && <p className="small">This is the demo. It never connects to a HubSpot account.</p>}
      {s.connected && !editing && (
        <div className="track-state">
          <div><strong>Connected</strong> <span className="small muted">token ending {s.token_last4}</span></div>
          <div className="small">{s.checked_at
            ? (s.check_ok ? `✓ ${s.check_detail}` : `Last test failed: ${s.check_detail}`)
            : "Not tested yet."}</div>
          {owner && (
            <div className="row">
              <button className="small" style={{ flex: "0 0 auto" }} disabled={test.isPending}
                onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test connection"}</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }} onClick={() => setEditing(true)}>
                Replace the token</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }} disabled={remove.isPending}
                onClick={() => remove.mutate()}>Disconnect</button>
            </div>
          )}
        </div>
      )}
      {!s.connected && !editing && !s.demo && (owner
        ? <button className="small" onClick={() => setEditing(true)}>Connect HubSpot</button>
        : <p className="small muted">The practice owner connects the company's HubSpot account.</p>)}
      {editing && owner && (
        <form className="track-form" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <p className="small" style={{ margin: 0 }}>In HubSpot: Settings, Integrations, Private apps, Create a
            private app. On its Scopes tab, tick these read scopes, nothing else:</p>
          <ul className="small hubspot-scopes">{s.scopes.map((x) => <li key={x}><code>{x}</code></li>)}</ul>
          <label htmlFor={`${id}-t`} className="small">Access token</label>
          <input id={`${id}-t`} type="password" value={token} autoComplete="off"
            placeholder="pat-…" onChange={(e) => setToken(e.target.value)} />
          <div className="row">
            <button className="primary small" style={{ flex: "0 0 auto" }} type="submit"
              disabled={save.isPending || !token.trim()}>Save</button>
            <button className="ghost small" style={{ flex: "0 0 auto" }} type="button"
              onClick={() => { setEditing(false); setToken(""); }}>Cancel</button>
          </div>
        </form>
      )}
    </Card>
  );
}

/** M5 part 5: a KPI's HubSpot measure, from a fixed menu, for the total or
 *  one owner; pipeline value for every open stage or one. */
export function HubSpotFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<HubSpotFeedState>({
    queryKey: ["hubspot-feed", companyId, kpiId],
    queryFn: () => api.get<HubSpotFeedState>(`/api/scorecard/hubspot/feed/?company=${companyId}&kpi=${kpiId}`),
  });
  const options = useQuery<Options>({
    queryKey: ["hubspot-options", companyId],
    queryFn: () => api.get<Options>(`/api/scorecard/hubspot/options/?company=${companyId}`),
    enabled: !!state.data?.connected,
  });
  const f = state.data?.feed;
  const [measure, setMeasure] = useState<string | null>(null);
  const [owner, setOwner] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState("");
  const chosen = measure ?? f?.measure ?? "";
  const def = options.data?.measures.find((m) => m.key === chosen);
  const ownerValue = owner ?? f?.owner_id ?? "";
  const stageValue = chosen === "pipeline_value" ? (stage ?? f?.stage_id ?? "") : "";
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; error?: string } }>("/api/scorecard/hubspot/feed/", {
      company: companyId, kpi: kpiId, measure: chosen,
      owner_id: ownerValue, owner_name: options.data?.owners.find((o) => o.id === ownerValue)?.name ?? "",
      stage_id: stageValue, stage_name: options.data?.stages.find((x) => x.id === stageValue)?.name ?? "" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["hubspot-feed", companyId, kpiId] });
      const name = state.data?.kpi.name ?? "The KPI";
      onSaved(!r.run.ok ? `${name}'s HubSpot measure is saved, but the first read failed: ${r.run.error}`
        : def?.snapshot && !r.run.new ? `${name} now reads from HubSpot. Its first reading comes when this period closes.`
        : `${name} now reads from HubSpot: ${r.run.new ?? 0} reading${r.run.new === 1 ? "" : "s"} for past periods.`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/hubspot/feed/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => onSaved("Entered by hand again. Its readings are kept."),
  });
  const s = state.data;
  const title = s ? `Feed ${s.kpi.name} from HubSpot` : "HubSpot measure";
  const groups = GROUPS.map(([label, objects]) =>
    [label, (options.data?.measures ?? []).filter((m) => objects.includes(m.object))] as const);
  return (
    <Modal label={title} title={title} onClose={onClose}>
      {!s ? <p>Loading…</p> : !s.connected ? (
        <p>This company has no HubSpot connection yet. The practice owner adds it on the company page, under HubSpot.</p>
      ) : (
        <div className="track-feed">
          {f && <p className="small muted" style={{ marginTop: 0 }}>{f.text}.{f.last_error && <> <strong>Last read failed:</strong> {f.last_error}</>}</p>}
          {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
          {options.data?.error && <Banner kind="warn">{options.data.error}</Banner>}
          <label htmlFor="hubspot-measure" className="small">Measure</label>
          <select id="hubspot-measure" value={chosen} onChange={(e) => { setMeasure(e.target.value); setError(""); }}>
            <option value="">Choose a measure…</option>
            {groups.map(([label, list]) => (
              <optgroup key={label} label={label}>
                {list.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </optgroup>
            ))}
          </select>
          {def && (
            <>
              <label htmlFor="hubspot-owner" className="small">Owner</label>
              <select id="hubspot-owner" value={ownerValue} onChange={(e) => setOwner(e.target.value)}>
                <option value="">Every owner (total)</option>
                {(options.data?.owners ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            </>
          )}
          {def?.key === "pipeline_value" && (
            <>
              <label htmlFor="hubspot-stage" className="small">Stage</label>
              <select id="hubspot-stage" value={stageValue} onChange={(e) => setStage(e.target.value)}>
                <option value="">Every open stage (total)</option>
                {(options.data?.stages ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select>
              <p className="small muted" style={{ margin: 0 }}>HubSpot can't say what the pipeline held on an earlier
                day, so pipeline value is read as each period closes and kept. There are no readings for periods
                already past.</p>
            </>
          )}
          <p className="small muted">Worked out for each closed period once a day, at the practice's midnight. A
            reading typed by hand is never replaced, and none is ever deleted.</p>
          <div className="row">
            <button className="primary" style={{ flex: "0 0 auto" }} disabled={!chosen || save.isPending}
              onClick={() => save.mutate()}>{save.isPending ? "Reading HubSpot…" : "Save the measure"}</button>
            <button className="ghost" style={{ flex: "0 0 auto" }} onClick={onClose}>Cancel</button>
            {f && <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => stop.mutate()}>Stop the feed</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
