import { PageHead } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ExternalLink } from "lucide-react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { AiBudget, api } from "../lib/api";

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
      <PageHead title="AI usage"
        sub="Every Claude call this practice has made, and what it cost. Visible to you only —
        spend is financial."
        action={
          <a className="button" href="https://console.anthropic.com/" target="_blank"
            rel="noopener noreferrer">
            Manage your Anthropic account <ExternalLink size={14} />
          </a>
        } />

      <Credits />

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

/**
 * Credits on the account, the monthly budget, and what is probably left
 * (owner, 2026-09-28). Anthropic does not report the balance, so it is the
 * credits entered at the last top-up less what this app has logged since —
 * **an estimate**, and the screen says so every time it shows the figure.
 */
function Credits() {
  const qc = useQueryClient();
  const state = useQuery<AiBudget>({
    queryKey: ["ai-budget"], queryFn: () => api.get<AiBudget>("/api/ai-budget/"),
  });
  const [credits, setCredits] = useState("");
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [budget, setBudget] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (body: object) => api.post<AiBudget>("/api/ai-budget/", body),
    onSuccess: (data) => {
      qc.setQueryData(["ai-budget"], data);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setCredits(""); setBudget(null);
    },
  });
  const s = state.data;
  if (!s) return null;
  const budgetValue = budget ?? s.monthly_budget_usd ?? "";

  return (
    <>
      {s.warnings.map((w) => <Banner key={w.kind} kind="warn">{w.message}</Banner>)}
      <Card title="Credits and budget">
        <div className="row">
          <div>
            <div className="tile-label">Estimated balance</div>
            <div className="tile-value">
              {s.estimated_balance !== null ? `$${s.estimated_balance}` : "—"}
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              {s.estimated_balance !== null ? (
                <>An estimate: the ${s.credits_usd} you entered on {s.credits_as_of}, less
                  the ${s.spent_since_credits} this app has logged since. Calls made with
                  the same key elsewhere are not counted — the console has the real figure.</>
              ) : "Enter the credits on your account below to see an estimate."}
            </p>
          </div>
          <div>
            <div className="tile-label">This month</div>
            <div className="tile-value">${s.month_spend}</div>
            <p className="small muted" style={{ margin: 0 }}>
              {s.monthly_budget_usd ? `of a $${s.monthly_budget_usd} monthly budget`
                                    : "No monthly budget set."}
              {s.next_import && <> · the running import needs about
                ${s.next_import.cost_usd} more</>}
            </p>
          </div>
        </div>

        <form className="row" style={{ marginTop: "var(--s3)" }}
          onSubmit={(e) => { e.preventDefault();
                             save.mutate({ credits_usd: credits, credits_as_of: asOf }); }}>
          <Field label="Credits on account after topping up ($)">
            <input aria-label="Credits on account" inputMode="decimal" value={credits}
              placeholder={s.credits_usd ?? "50.00"} onChange={(e) => setCredits(e.target.value)} />
          </Field>
          <Field label="Topped up on">
            <input aria-label="Topped up on" type="date" value={asOf}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setAsOf(e.target.value)} />
          </Field>
          <div style={{ flex: "0 0 auto", alignSelf: "end" }}>
            <button type="submit" disabled={!credits.trim() || !asOf || save.isPending}>
              Save credits
            </button>
          </div>
        </form>
        <form className="row"
          onSubmit={(e) => { e.preventDefault();
                             save.mutate({ monthly_budget_usd: budgetValue || null }); }}>
          <Field label="Monthly budget ($)">
            <input aria-label="Monthly budget" inputMode="decimal" value={budgetValue}
              placeholder="None" onChange={(e) => setBudget(e.target.value)} />
          </Field>
          <div style={{ flex: "0 0 auto", alignSelf: "end" }}>
            <button type="submit" disabled={save.isPending
              || budgetValue === (s.monthly_budget_usd ?? "")}>Save budget</button>
          </div>
        </form>
        <p className="small muted">
          A warning shows here and on the dashboard at 80% of the monthly budget, and when
          the estimate is less than the running import still needs. An import or a
          Consolidate that would run past the estimate asks before it starts.
        </p>
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
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
