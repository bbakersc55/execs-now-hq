import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api } from "../lib/api";

interface Call {
  id: string; purpose: string; model: string; input_tokens: number;
  output_tokens: number; cost_usd: string; trigger: string;
  succeeded: boolean; error: string; created_at: string;
}
interface Summary {
  by_purpose: { purpose: string; calls: number; cost: string | null;
                input_tokens: number; output_tokens: number }[];
  total: { cost: string | null; calls: number };
}

export function AiUsage() {
  const summary = useQuery<Summary>({
    queryKey: ["ai-summary"], queryFn: () => api.get<Summary>("/api/ai-usage/summary/"),
  });
  const calls = useQuery<Call[]>({
    queryKey: ["ai-calls"], queryFn: () => api.get<Call[]>("/api/ai-usage/"),
  });

  const money = (v: string | null) => `$${Number(v ?? 0).toFixed(4)}`;

  return (
    <>
      <h2>AI usage</h2>
      <p className="sub">
        Every Claude call this practice has made, and what it cost. Visible to you only —
        spend is financial.
      </p>

      <AnthropicKey />

      <Card title="Total">
        <p style={{ fontSize: "1.6rem", margin: 0 }}>
          {money(summary.data?.total.cost ?? null)}
          <span className="muted small"> across {summary.data?.total.calls ?? 0} calls</span>
        </p>
      </Card>

      <Card title="By purpose">
        {(summary.data?.by_purpose ?? []).length === 0 ? <Empty>No calls yet.</Empty> : (
          <table>
            <thead><tr><th>Purpose</th><th>Calls</th><th>In</th><th>Out</th><th className="right">Cost</th></tr></thead>
            <tbody>
              {summary.data!.by_purpose.map((r) => (
                <tr key={r.purpose}>
                  <td>{r.purpose.replace(/_/g, " ")}</td>
                  <td>{r.calls}</td>
                  <td className="muted">{r.input_tokens}</td>
                  <td className="muted">{r.output_tokens}</td>
                  <td className="right mono">{money(r.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Recent calls">
        {(calls.data ?? []).length === 0 ? <Empty>No calls yet.</Empty> : (
          <table>
            <thead><tr><th>When</th><th>Purpose</th><th>Model</th><th>Trigger</th><th>Status</th><th className="right">Cost</th></tr></thead>
            <tbody>
              {calls.data!.slice(0, 50).map((c) => (
                <tr key={c.id}>
                  <td className="muted small">{when(c.created_at)}</td>
                  <td>{c.purpose.replace(/_/g, " ")}</td>
                  <td className="mono small">{c.model}</td>
                  <td><Pill>{c.trigger}</Pill></td>
                  <td>{c.succeeded ? <Pill kind="ok">ok</Pill> : <Pill kind="bad">failed</Pill>}</td>
                  <td className="right mono">{money(c.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

interface KeyStatus {
  source: "tenant" | "env" | null; last4: string;
  verified_at: string | null; rotated_at: string | null; model: string;
}

/** Assumption E1 — write-only. The key is never shown back, only its last
 *  four characters; a new key is checked before it replaces the old one. */
function AnthropicKey() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const status = useQuery<KeyStatus>({ queryKey: ["ai-key"], queryFn: () => api.get<KeyStatus>("/api/ai-key/") });
  const save = useMutation({
    mutationFn: () => api.post<KeyStatus>("/api/ai-key/", { key }),
    onSuccess: () => { setKey(""); qc.invalidateQueries({ queryKey: ["ai-key"] }); },
  });
  const s = status.data;

  return (
    <Card title="Anthropic API key">
      {s?.source === "tenant" && (
        <p>In use: <span className="mono">sk-ant-…{s.last4}</span>{" "}
          <span className="muted small">checked {when(s.verified_at)} · model {s.model}</span></p>
      )}
      {s?.source === "env" && (
        <Banner kind="warn">No practice key is stored. Calls use the development fallback from
          <span className="mono"> .env</span>, which is refused once the app is off this laptop.</Banner>
      )}
      {s?.source === null && (
        <Banner kind="bad">No key is set, so Claude cannot draft summaries. Recordings still
          transcribe; their summaries wait until a key is added.</Banner>
      )}
      <form className="row" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <input aria-label="New Anthropic API key" type="password" autoComplete="off"
          placeholder="sk-ant-…" value={key} onChange={(e) => setKey(e.target.value)} />
        <button className="primary" type="submit" disabled={!key.trim() || save.isPending}>
          {save.isPending ? "Checking…" : s?.source === "tenant" ? "Replace key" : "Save key"}
        </button>
      </form>
      <p className="small muted">The key is checked with Anthropic before it is saved. If the check
        fails, nothing changes. It is stored encrypted and never shown again.</p>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
    </Card>
  );
}
