import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { ReadOpenChoice, readOpenValue } from "./ReadOpenChoice";

import { Modal } from "./shell";
import { Banner, Card } from "./ui";
import { Me, api } from "../lib/api";

interface TrackConnection {
  connected: boolean; demo: boolean; domain?: string; key_last4?: string;
  checked_at?: string | null; check_ok?: boolean | null; check_detail?: string;
}
interface Measure { key: string; label: string; stream: string; kind: string; scope: "property" | "assignee" }
interface Options { measures: Measure[]; units: { id: string; name: string }[];
  assignees: { id: string; name: string; work_orders: number }[]; error: string }
interface TrackFeedState {
  kpi: { id: string; name: string; kind: string; per_person: boolean; read_open_default?: boolean };
  connected: boolean;
  feed: { measure: string; label: string; unit_id: string; unit_name: string; assignee_id: string;
    text: string; last_success_at: string | null; last_error: string;
    read_open?: boolean } | null;
}

const STREAMS: Record<string, string> = {
  reservations: "Stays and revenue", reviews: "Reviews", maintenance: "Maintenance",
  housekeeping: "Housekeeping",
};

/**
 * M5 part 4: a client company's Track PMS account, on the company page. The
 * practice owner enters the Track address, API key and secret; they are
 * stored encrypted and never shown again. "Test connection" makes one
 * read-only call.
 */
export function TrackConnectionCard({ me, companyId }: { me: Me; companyId: string }) {
  const qc = useQueryClient();
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [domain, setDomain] = useState("");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const state = useQuery<TrackConnection>({
    queryKey: ["track-connection", companyId],
    queryFn: () => api.get<TrackConnection>(`/api/scorecard/track/connection/?company=${companyId}`),
  });
  const done = () => { qc.invalidateQueries({ queryKey: ["track-connection", companyId] }); };
  const save = useMutation({
    mutationFn: () => api.put("/api/scorecard/track/connection/", { company: companyId, domain, key, secret }),
    onSuccess: () => { setEditing(false); setKey(""); setSecret(""); setError(""); done(); },
    onError: (e: Error) => setError(e.message),
  });
  const test = useMutation({
    mutationFn: () => api.post("/api/scorecard/track/connection/test/", { company: companyId }),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/scorecard/track/connection/?company=${companyId}`),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const s = state.data;
  if (!s) return null;
  const owner = me.role === "FF";
  return (
    <Card title="Track PMS">
      <p className="small muted" style={{ marginTop: 0 }}>
        Feeds occupancy, revenue, reviews and work orders into this company's scorecard. The client creates an API
        key and secret in Track; they are stored encrypted, and nobody at the practice sees them again.</p>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {s.demo && !s.connected && <p className="small">This is the demo. It never connects to a Track account.</p>}
      {s.connected && !editing && (
        <div className="track-state">
          <div><strong>{s.domain}</strong> <span className="small muted">key ending {s.key_last4}</span></div>
          <div className="small">{s.checked_at
            ? (s.check_ok ? `✓ ${s.check_detail}` : `Last test failed: ${s.check_detail}`)
            : "Not tested yet."}</div>
          {owner && (
            <div className="row">
              <button className="small" style={{ flex: "0 0 auto" }} disabled={test.isPending}
                onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test connection"}</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }} onClick={() => {
                setDomain(s.domain ?? ""); setEditing(true); }}>Change</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }} disabled={remove.isPending}
                onClick={() => remove.mutate()}>Disconnect</button>
            </div>
          )}
        </div>
      )}
      {!s.connected && !editing && !s.demo && (owner
        ? <button className="small" onClick={() => setEditing(true)}>Connect Track</button>
        : <p className="small muted">The practice owner connects the company's Track account.</p>)}
      {editing && owner && (
        <form className="track-form" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <label htmlFor={`${id}-d`} className="small">Track address</label>
          <input id={`${id}-d`} value={domain} placeholder="acme.trackhs.com" onChange={(e) => setDomain(e.target.value)} />
          <label htmlFor={`${id}-k`} className="small">API key{s.connected ? " (leave blank to keep)" : ""}</label>
          <input id={`${id}-k`} value={key} autoComplete="off" onChange={(e) => setKey(e.target.value)} />
          <label htmlFor={`${id}-s`} className="small">API secret{s.connected ? " (leave blank to keep)" : ""}</label>
          <input id={`${id}-s`} type="password" value={secret} autoComplete="new-password" onChange={(e) => setSecret(e.target.value)} />
          <div className="row">
            <button className="primary small" style={{ flex: "0 0 auto" }} type="submit" disabled={save.isPending}>Save</button>
            <button className="ghost small" style={{ flex: "0 0 auto" }} type="button" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>
      )}
    </Card>
  );
}

/** M5 part 4: a KPI's Track measure, from a fixed menu, for the company's
 *  total, one property or one Track user. */
export function TrackFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<TrackFeedState>({
    queryKey: ["track-feed", companyId, kpiId],
    queryFn: () => api.get<TrackFeedState>(`/api/scorecard/track/feed/?company=${companyId}&kpi=${kpiId}`),
  });
  const options = useQuery<Options>({
    queryKey: ["track-options", companyId],
    queryFn: () => api.get<Options>(`/api/scorecard/track/options/?company=${companyId}`),
    enabled: !!state.data?.connected,
  });
  const f = state.data?.feed;
  const [measure, setMeasure] = useState<string | null>(null);
  const [scope, setScope] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [readOpen, setReadOpen] = useState<boolean | null>(null);
  const readsOpen = readOpenValue(readOpen, f?.read_open, state.data?.kpi.read_open_default);
  const chosen = measure ?? f?.measure ?? "";
  const def = options.data?.measures.find((m) => m.key === chosen);
  const scopeValue = scope ?? (def?.scope === "assignee" ? f?.assignee_id : f?.unit_id) ?? "";
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; error?: string } }>("/api/scorecard/track/feed/", {
      company: companyId, kpi: kpiId, measure: chosen, read_open: readsOpen,
      unit_id: def?.scope === "property" ? scopeValue : "",
      unit_name: options.data?.units.find((u) => u.id === scopeValue)?.name ?? "",
      assignee_id: def?.scope === "assignee" ? scopeValue : "" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["track-feed", companyId, kpiId] });
      const name = state.data?.kpi.name ?? "The KPI";
      onSaved(r.run.ok ? `${name} now reads from Track: ${r.run.new ?? 0} reading${r.run.new === 1 ? "" : "s"} for past periods.`
        : `${name}'s Track measure is saved, but the first read failed: ${r.run.error}`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/track/feed/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => onSaved("Entered by hand again. Its readings are kept."),
  });
  const s = state.data;
  const title = s ? `Feed ${s.kpi.name} from Track` : "Track measure";
  const groups = Object.entries(STREAMS).map(([k, label]) =>
    [label, (options.data?.measures ?? []).filter((m) => m.stream === k)] as const);
  return (
    <Modal label={title} title={title} onClose={onClose}>
      {!s ? <p>Loading…</p> : !s.connected ? (
        <p>This company has no Track connection yet. The practice owner adds it on the company page, under Track PMS.</p>
      ) : (
        <div className="track-feed">
          {f && <p className="small muted" style={{ marginTop: 0 }}>{f.text}.{f.last_error && <> <strong>Last read failed:</strong> {f.last_error}</>}</p>}
          {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
          {options.data?.error && <Banner kind="warn">{options.data.error}</Banner>}
          <label htmlFor="track-measure" className="small">Measure</label>
          <select id="track-measure" value={chosen} onChange={(e) => { setMeasure(e.target.value); setScope(""); setError(""); }}>
            <option value="">Choose a measure…</option>
            {groups.map(([label, list]) => (
              <optgroup key={label} label={label}>
                {list.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </optgroup>
            ))}
          </select>
          {def && (
            <>
              <label htmlFor="track-scope" className="small">{def.scope === "property" ? "For" : "Assigned to"}</label>
              <select id="track-scope" value={scopeValue} onChange={(e) => setScope(e.target.value)}>
                <option value="">{def.scope === "property" ? "All properties (total)" : "Everyone (total)"}</option>
                {def.scope === "property"
                  ? (options.data?.units ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)
                  : (options.data?.assignees ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.work_orders} work orders)</option>)}
              </select>
              {def.scope === "assignee" && <p className="small muted" style={{ margin: 0 }}>Track's people are shown by their
                Track user number: its API lists no names.</p>}
            </>
          )}
          <p className="small muted">Worked out for each closed period once a day. A reading typed by hand is never
            replaced, and none is ever deleted.</p>
          <ReadOpenChoice id="track-read-open" checked={readsOpen}
            byDefault={!!s.kpi.read_open_default} onChange={setReadOpen} />
          <div className="row">
            <button className="primary" style={{ flex: "0 0 auto" }} disabled={!chosen || save.isPending}
              onClick={() => save.mutate()}>{save.isPending ? "Reading Track…" : "Save the measure"}</button>
            <button className="ghost" style={{ flex: "0 0 auto" }} onClick={onClose}>Cancel</button>
            {f && <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => stop.mutate()}>Stop the feed</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
