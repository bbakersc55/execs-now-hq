import { useQuery } from "@tanstack/react-query";

import { Card, Empty, Pill, when } from "../components/ui";
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
