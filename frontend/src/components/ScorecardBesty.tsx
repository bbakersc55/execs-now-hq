import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { ReadOpenChoice, readOpenValue } from "./ReadOpenChoice";

import { Modal } from "./shell";
import { Banner, Card } from "./ui";
import { Me, api } from "../lib/api";

interface BestyConnection {
  connected: boolean; demo: boolean; token_last4?: string;
  checked_at?: string | null; check_ok?: boolean | null; check_detail?: string;
}
type Scope = "member" | "upsell" | "responder" | "owner" | "total";
interface Measure { key: string; label: string; tool: string; kind: string; scope: Scope }
interface Choice { id: string; name: string }
interface Options {
  measures: Measure[]; members: (Choice & { state?: string })[]; owners: Choice[];
  upsell_types: Choice[]; responders: Choice[]; error: string;
}
interface BestyFeedState {
  kpi: { id: string; name: string; kind: string; per_person: boolean; read_open_default?: boolean };
  connected: boolean;
  feed: { measure: string; label: string; member_id: string; member_name: string; owner_id: string;
    owner_name: string; param: string; text: string; last_success_at: string | null; last_error: string;
    read_open?: boolean } | null;
}

const GROUPS: [string, string[]][] = [
  ["Ops tasks", ["export_ops_tasks"]], ["Upsells", ["export_upsell_events"]],
  ["Guests", ["compute_response_time", "export_reviews"]], ["Owners", ["export_messages"]],
  ["Calls", ["export_calls"]],
];

/**
 * M5 part 6: a client company's Besty account, on the company page. The
 * practice owner pastes the account's read-only MCP token; it is stored
 * encrypted and never shown again. "Test connection" connects and lists
 * Besty's tools, and reads nothing else.
 */
export function BestyConnectionCard({ me, companyId }: { me: Me; companyId: string }) {
  const qc = useQueryClient();
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const state = useQuery<BestyConnection>({
    queryKey: ["besty-connection", companyId],
    queryFn: () => api.get<BestyConnection>(`/api/scorecard/besty/connection/?company=${companyId}`),
  });
  const done = () => { qc.invalidateQueries({ queryKey: ["besty-connection", companyId] }); };
  const save = useMutation({
    mutationFn: () => api.put("/api/scorecard/besty/connection/", { company: companyId, token }),
    onSuccess: () => { setEditing(false); setToken(""); setError(""); done(); },
    onError: (e: Error) => setError(e.message),
  });
  const test = useMutation({
    mutationFn: () => api.post("/api/scorecard/besty/connection/test/", { company: companyId }),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/scorecard/besty/connection/?company=${companyId}`),
    onSuccess: done, onError: (e: Error) => setError(e.message),
  });
  const s = state.data;
  if (!s) return null;
  const owner = me.role === "FF";
  return (
    <Card title="Besty">
      <p className="small muted" style={{ marginTop: 0 }}>
        Feeds ops tasks, upsell revenue, guest response time, reviews, messages to owners and calls answered
        into this company's scorecard. The client gives a read-only Besty MCP token for the account; it is
        stored encrypted, and nobody at the practice sees it again.</p>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {s.demo && !s.connected && <p className="small">This is the demo. It never connects to a Besty account.</p>}
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
        ? <button className="small" onClick={() => setEditing(true)}>Connect Besty</button>
        : <p className="small muted">The practice owner connects the company's Besty account.</p>)}
      {editing && owner && (
        <form className="track-form" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <p className="small" style={{ margin: 0 }}>Ask Besty for a long-lived, read-only MCP token for this
            company's account, and paste it here.</p>
          <label htmlFor={`${id}-t`} className="small">MCP token</label>
          <input id={`${id}-t`} type="password" value={token} autoComplete="off"
            onChange={(e) => setToken(e.target.value)} />
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

/** M5 part 6: a KPI's Besty measure, from a fixed menu, for the total or one
 *  team member; an upsell type; who a response time is for; one owner. */
export function BestyFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<BestyFeedState>({
    queryKey: ["besty-feed", companyId, kpiId],
    queryFn: () => api.get<BestyFeedState>(`/api/scorecard/besty/feed/?company=${companyId}&kpi=${kpiId}`),
  });
  const options = useQuery<Options>({
    queryKey: ["besty-options", companyId],
    queryFn: () => api.get<Options>(`/api/scorecard/besty/options/?company=${companyId}`),
    enabled: !!state.data?.connected,
  });
  const f = state.data?.feed;
  const [measure, setMeasure] = useState<string | null>(null);
  const [member, setMember] = useState<string | null>(null);
  const [owner, setOwner] = useState<string | null>(null);
  const [param, setParam] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [readOpen, setReadOpen] = useState<boolean | null>(null);
  const readsOpen = readOpenValue(readOpen, f?.read_open, state.data?.kpi.read_open_default);
  const chosen = measure ?? f?.measure ?? "";
  const def = options.data?.measures.find((m) => m.key === chosen);
  const scope = def?.scope;
  const memberValue = scope === "member" || scope === "owner" || scope === "responder"
    ? (member ?? f?.member_id ?? "") : "";
  const ownerValue = scope === "owner" ? (owner ?? f?.owner_id ?? "") : "";
  const paramValue = scope === "upsell" || scope === "responder" ? (param ?? f?.param ?? "") : "";
  // A response time is for everyone, people, autopilot, or one team member.
  const whoValue = memberValue ? `member:${memberValue}` : paramValue;
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; error?: string } }>("/api/scorecard/besty/feed/", {
      company: companyId, kpi: kpiId, measure: chosen, read_open: readsOpen,
      member_id: memberValue, member_name: options.data?.members.find((m) => m.id === memberValue)?.name ?? "",
      owner_id: ownerValue, owner_name: options.data?.owners.find((o) => o.id === ownerValue)?.name ?? "",
      param: paramValue }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["besty-feed", companyId, kpiId] });
      const name = state.data?.kpi.name ?? "The KPI";
      onSaved(!r.run.ok ? `${name}'s Besty measure is saved, but the first read failed: ${r.run.error}`
        : `${name} now reads from Besty: ${r.run.new ?? 0} reading${r.run.new === 1 ? "" : "s"} for past periods.`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/besty/feed/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => onSaved("Entered by hand again. Its readings are kept."),
  });
  const s = state.data;
  const title = s ? `Feed ${s.kpi.name} from Besty` : "Besty measure";
  const groups = GROUPS.map(([label, tools]) =>
    [label, (options.data?.measures ?? []).filter((m) => tools.includes(m.tool))] as const);
  const members = options.data?.members ?? [];
  return (
    <Modal label={title} title={title} onClose={onClose}>
      {!s ? <p>Loading…</p> : !s.connected ? (
        <p>This company has no Besty connection yet. The practice owner adds it on the company page, under Besty.</p>
      ) : (
        <div className="track-feed">
          {f && <p className="small muted" style={{ marginTop: 0 }}>{f.text}.{f.last_error && <> <strong>Last read failed:</strong> {f.last_error}</>}</p>}
          {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
          {options.data?.error && <Banner kind="warn">{options.data.error}</Banner>}
          <label htmlFor="besty-measure" className="small">Measure</label>
          <select id="besty-measure" value={chosen} onChange={(e) => { setMeasure(e.target.value); setError(""); }}>
            <option value="">Choose a measure…</option>
            {groups.map(([label, list]) => (
              <optgroup key={label} label={label}>
                {list.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </optgroup>
            ))}
          </select>
          {(scope === "member" || scope === "owner") && (
            <>
              <label htmlFor="besty-member" className="small">Team member</label>
              <select id="besty-member" value={memberValue} onChange={(e) => setMember(e.target.value)}>
                <option value="">The whole team (total)</option>
                {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </>
          )}
          {scope === "owner" && (
            <>
              <label htmlFor="besty-owner" className="small">Owner</label>
              <select id="besty-owner" value={ownerValue} onChange={(e) => setOwner(e.target.value)}>
                <option value="">Every owner (total)</option>
                {(options.data?.owners ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            </>
          )}
          {scope === "upsell" && (
            <>
              <label htmlFor="besty-type" className="small">Upsell type</label>
              <select id="besty-type" value={paramValue} onChange={(e) => setParam(e.target.value)}>
                <option value="">Every type (total)</option>
                {(options.data?.upsell_types ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </>
          )}
          {scope === "responder" && (
            <>
              <label htmlFor="besty-who" className="small">Whose replies</label>
              <select id="besty-who" value={whoValue} onChange={(e) => {
                const v = e.target.value;
                if (v.startsWith("member:")) { setMember(v.slice(7)); setParam(""); }
                else { setMember(""); setParam(v); }
              }}>
                {(options.data?.responders ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                {members.length > 0 && (
                  <optgroup label="One team member">
                    {members.map((m) => <option key={m.id} value={`member:${m.id}`}>{m.name}</option>)}
                  </optgroup>
                )}
              </select>
            </>
          )}
          {chosen === "tasks_days_to_close" && (
            <p className="small muted" style={{ margin: 0 }}>Besty gives this only for tasks a person made: a task an
              automation made can show as made after it was done.</p>
          )}
          <p className="small muted">Worked out for each closed period once a day, at the practice's midnight, by
            Besty's own figures. A reading typed by hand is never replaced, and none is ever deleted. Nothing else
            Besty answers is kept.</p>
          <ReadOpenChoice id="besty-read-open" checked={readsOpen}
            byDefault={!!s.kpi.read_open_default} onChange={setReadOpen} />
          <div className="row">
            <button className="primary" style={{ flex: "0 0 auto" }} disabled={!chosen || save.isPending}
              onClick={() => save.mutate()}>{save.isPending ? "Reading Besty…" : "Save the measure"}</button>
            <button className="ghost" style={{ flex: "0 0 auto" }} onClick={onClose}>Cancel</button>
            {f && <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => stop.mutate()}>Stop the feed</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
