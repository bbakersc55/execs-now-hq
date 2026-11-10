import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useState } from "react";

import { api } from "../lib/api";
import { Banner, Card, Empty, Pill, when } from "./ui";

/**
 * AI apps over MCP, and where each AI action runs (P7, docs/p7_mcp.md).
 *
 * - `ConnectedAiApps`: Profile, the person's own connected apps.
 * - `AiAppsCard`: Settings → AI, the connector URL with paste-in steps, and
 *   the practice's connected apps (all of them for the practice owner).
 * - `AiActionsCard`: Settings → AI, every AI action's "Runs in" and tier.
 * - `DoInYourAi`: wraps an in-app AI button; when the action is set to run
 *   in the person's AI app, shows "Do this in your AI" and the prompt instead.
 * - `ModelTiersCard`: the platform owner's tier table (Practices area).
 */

export interface AiConnection {
  id: string; app: string; connected_at: string; last_used_at: string | null;
  person: string; role: string;
}
export interface AiActionRow {
  key: string; label: string; where: string; started: "user" | "both" | "unattended";
  fixed: boolean; fixed_why: string; runs_in: "app" | "ai_app";
  tier: "fast" | "standard" | "deep"; default_tier: string; prompt: string;
}
interface ActionsPayload {
  actions: AiActionRow[]; may_change: boolean;
  tiers: { code: string; label: string; model: string }[];
}
interface AppsPayload { connector_url: string; everyone: boolean; connections: AiConnection[] }

const TIER_LABEL: Record<string, string> = { fast: "Fast", standard: "Standard", deep: "Deep" };

function useActions() {
  return useQuery<ActionsPayload>({
    queryKey: ["ai-actions"], queryFn: () => api.get<ActionsPayload>("/api/ai/actions/"),
    staleTime: 60_000,
  });
}

function Connections({ rows, onRevoke, busy, showPerson }: {
  rows: AiConnection[]; onRevoke: (id: string) => void; busy: boolean; showPerson: boolean;
}) {
  if (rows.length === 0) return <Empty>No AI apps are connected.</Empty>;
  return (
    <table>
      <thead><tr>
        <th>AI app</th>{showPerson && <th>Person</th>}<th>Connected</th><th>Last used</th><th />
      </tr></thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.id}>
            <td>{c.app}</td>
            {showPerson && <td>{c.person} <span className="muted small">· {c.role}</span></td>}
            <td className="small">{when(c.connected_at)}</td>
            <td className="small">{c.last_used_at ? when(c.last_used_at) : "Not yet"}</td>
            <td style={{ textAlign: "right" }}>
              <button className="ghost small" disabled={busy}
                aria-label={`Revoke ${c.app}`} onClick={() => onRevoke(c.id)}>Revoke</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function useRevoke(keys: string[][]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/api/ai/connections/${id}/revoke`, {}),
    onSuccess: () => keys.forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}

/** Profile: the person's own connected AI apps. */
export function ConnectedAiApps() {
  const rows = useQuery<AiConnection[]>({
    queryKey: ["ai-connections"], queryFn: () => api.get<AiConnection[]>("/api/ai/connections/"),
  });
  // The address too: a demo visitor has no Settings → AI to find it in.
  const apps = useQuery<AppsPayload>({
    queryKey: ["ai-apps"], queryFn: () => api.get<AppsPayload>("/api/ai/apps/"),
  });
  const revoke = useRevoke([["ai-connections"], ["ai-apps"]]);
  return (
    <Card title="Connected AI apps">
      <p className="small muted" style={{ marginTop: 0 }}>
        AI apps you signed in to this practice, such as Claude or ChatGPT. Each acts as you, with
        your role, and its provider receives the data you choose to work with there. Revoke one
        and it stops at once. To connect one, add this address as a custom connector in the AI
        app (Settings → AI has the steps):
      </p>
      {apps.data?.connector_url && <CopyLine value={apps.data.connector_url} label="Connector URL" />}
      {rows.isLoading ? <p className="muted">Loading…</p>
        : <Connections rows={rows.data ?? []} busy={revoke.isPending} showPerson={false}
          onRevoke={(id) => revoke.mutate(id)} />}
      {revoke.isError && <Banner kind="bad">{(revoke.error as Error).message}</Banner>}
    </Card>
  );
}

function CopyLine({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="row tight" style={{ alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
      <code className="connector-url" aria-label={label}>{value}</code>
      <button className="small" onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => setCopied(true), () => undefined);
      }}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

/** Settings → AI, "AI apps". */
export function AiAppsCard() {
  const apps = useQuery<AppsPayload>({
    queryKey: ["ai-apps"], queryFn: () => api.get<AppsPayload>("/api/ai/apps/"),
  });
  const revoke = useRevoke([["ai-apps"], ["ai-connections"]]);
  const url = apps.data?.connector_url ?? "";
  return (
    <Card title="AI apps">
      <p className="small muted" style={{ marginTop: 0 }}>
        Work with this practice from your own Claude or ChatGPT, on your own subscription. The AI
        app signs in as you, sees what your role sees, and can only draft: tasks, notes, emails in
        the Sending queue, map rows, KPI readings and digests, each for a person to approve.
        Its provider receives the data you choose to work with there.
      </p>
      {url && <CopyLine value={url} label="Connector URL" />}
      <div className="ai-app-steps">
        <div>
          <h4>Claude</h4>
          <ol className="small">
            <li>In Claude, open Settings → Connectors, then Add custom connector.</li>
            <li>Name it Execs NOW HQ and paste the connector URL above. Add.</li>
            <li>Click Connect. Sign in here, check the practice and role shown, and Allow.</li>
          </ol>
        </div>
        <div>
          <h4>ChatGPT</h4>
          <ol className="small">
            <li>In ChatGPT, open Settings → Apps &amp; Connectors. Custom connectors may need
              developer mode turned on under Advanced settings.</li>
            <li>Create a connector named Execs NOW HQ with the connector URL above, and OAuth
              for authentication.</li>
            <li>Sign in here when asked, check the practice and role shown, and Allow.</li>
          </ol>
        </div>
      </div>
      <h4 style={{ marginBottom: "0.4rem" }}>
        {apps.data?.everyone ? "Connected in this practice" : "Your connected apps"}</h4>
      {apps.isLoading ? <p className="muted">Loading…</p>
        : <Connections rows={apps.data?.connections ?? []} busy={revoke.isPending}
          showPerson={!!apps.data?.everyone} onRevoke={(id) => revoke.mutate(id)} />}
    </Card>
  );
}

/** Settings → AI, "Actions". */
export function AiActionsCard() {
  const qc = useQueryClient();
  const actions = useActions();
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const change = useMutation({
    mutationFn: (body: { action: string; runs_in?: string; tier?: string }) =>
      api.patch<AiActionRow>("/api/ai/actions/", body),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ["ai-actions"] });
      setNote({ kind: "ok", text: `${row.label}: saved.` });
    },
    onError: (e: Error) => setNote({ kind: "bad", text: e.message }),
  });
  const data = actions.data;
  const may = !!data?.may_change;
  const models = Object.fromEntries((data?.tiers ?? []).map((t) => [t.code, t.model]));
  return (
    <Card title="Actions">
      <p className="small muted" style={{ marginTop: 0 }}>
        Every AI action in the app. <strong>Runs in</strong>: in the app on your Claude key, or in
        your AI app, where the button becomes "Do this in your AI" with a prompt to paste.
        Scheduled and rule-fired actions always run in the app. <strong>Model tier</strong>: Fast,
        Standard or Deep; the price is shown before every click, as now.
      </p>
      {note && <div role={note.kind === "ok" ? "status" : "alert"}><Banner kind={note.kind}>{note.text}</Banner></div>}
      {actions.isLoading ? <p className="muted">Loading…</p> : (
        <div className="table-scroll">
          <table className="ai-actions">
            <thead><tr><th>Action</th><th>Runs in</th><th>Model tier</th></tr></thead>
            <tbody>
              {(data?.actions ?? []).map((a) => (
                <tr key={a.key}>
                  <td>{a.label}<div className="small muted">{a.where}</div></td>
                  <td>
                    {a.fixed ? (
                      <span title={a.fixed_why}>In the app <span className="small muted">· fixed</span></span>
                    ) : (
                      <select aria-label={`Runs in for ${a.label}`} value={a.runs_in}
                        disabled={!may || change.isPending}
                        onChange={(e) => change.mutate({ action: a.key, runs_in: e.target.value })}>
                        <option value="app">In the app with my key</option>
                        <option value="ai_app">In my AI app</option>
                      </select>
                    )}
                  </td>
                  <td>
                    <select aria-label={`Model tier for ${a.label}`} value={a.tier}
                      disabled={!may || change.isPending}
                      onChange={(e) => change.mutate({ action: a.key, tier: e.target.value })}>
                      {["fast", "standard", "deep"].map((t) => (
                        <option key={t} value={t}>{TIER_LABEL[t]}{t === a.default_tier ? " (default)" : ""}</option>
                      ))}
                    </select>
                    <div className="small muted">{models[a.tier] ?? ""}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/**
 * An in-app AI button, or — when the practice runs this action in the
 * person's AI app — "Do this in your AI" and the prompt to paste, naming the
 * record. `record` is how the prompt names it ("Alder Fasteners, this week").
 */
/** The record a page is about, as "Do this in your AI" names it in its prompt
 * ("Alder Fasteners (company id …)"); set once by the page. */
export const AiRecord = createContext("");

export function DoInYourAi({ action, record, children }: {
  action: string; record?: string; children: ReactNode;
}) {
  const fromPage = useContext(AiRecord);
  record = record || fromPage || "this record";
  const actions = useActions();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const row = actions.data?.actions.find((a) => a.key === action);
  if (!row || row.runs_in !== "ai_app") return <>{children}</>;
  const prompt = row.prompt.replace("{record}", record);
  return (
    <span className="do-in-your-ai">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        Do this in your AI
      </button>
      {open && (
        <div className="do-in-your-ai-panel" role="region" aria-label="Prompt for your AI app">
          <p className="small muted" style={{ margin: "0 0 0.4rem" }}>
            Paste this into your AI app connected to Execs NOW HQ:</p>
          <textarea readOnly value={prompt} rows={4} aria-label="Prompt" />
          <button type="button" className="small" onClick={() => {
            void navigator.clipboard?.writeText(prompt).then(() => setCopied(true), () => undefined);
          }}>{copied ? "Copied" : "Copy the prompt"}</button>
        </div>
      )}
    </span>
  );
}

interface TierRow {
  code: string; label: string; model: string; input_usd_per_mtok: string;
  output_usd_per_mtok: string; server_fallback: boolean; updated_at: string | null;
}

/** The platform owner's tier table: each tier's model id and price. */
export function ModelTiersCard() {
  const qc = useQueryClient();
  const tiers = useQuery<TierRow[]>({
    queryKey: ["model-tiers"], queryFn: () => api.get<TierRow[]>("/api/platform/model-tiers"),
  });
  const [edits, setEdits] = useState<Record<string, Partial<TierRow>>>({});
  const save = useMutation({
    mutationFn: (row: TierRow) => api.patch<TierRow>("/api/platform/model-tiers", row),
    onSuccess: (row) => {
      setEdits((e) => { const next = { ...e }; delete next[row.code]; return next; });
      qc.invalidateQueries({ queryKey: ["model-tiers"] });
    },
  });
  return (
    <Card title="AI model tiers">
      <p className="small muted" style={{ marginTop: 0 }}>
        Every practice's AI actions run on one of these three. Change a model id or price here when
        Anthropic releases a new one; no code change is needed. Prices are USD per million tokens.
      </p>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <div className="table-scroll">
        <table>
          <thead><tr><th>Tier</th><th>Model</th><th>In</th><th>Out</th><th>Fallback</th><th /></tr></thead>
          <tbody>
            {(tiers.data ?? []).map((t) => {
              const row = { ...t, ...edits[t.code] } as TierRow;
              const set = (k: keyof TierRow, v: string | boolean) =>
                setEdits((e) => ({ ...e, [t.code]: { ...e[t.code], [k]: v } }));
              return (
                <tr key={t.code}>
                  <td>{t.label}</td>
                  <td><input aria-label={`${t.label} model`} value={row.model}
                    onChange={(e) => set("model", e.target.value)} /></td>
                  <td><input aria-label={`${t.label} input price`} value={row.input_usd_per_mtok}
                    inputMode="decimal" style={{ width: "6rem" }}
                    onChange={(e) => set("input_usd_per_mtok", e.target.value)} /></td>
                  <td><input aria-label={`${t.label} output price`} value={row.output_usd_per_mtok}
                    inputMode="decimal" style={{ width: "6rem" }}
                    onChange={(e) => set("output_usd_per_mtok", e.target.value)} /></td>
                  <td><input type="checkbox" aria-label={`${t.label} server fallback`}
                    checked={row.server_fallback}
                    onChange={(e) => set("server_fallback", e.target.checked)} /></td>
                  <td>{edits[t.code] && (
                    <button className="primary small" disabled={save.isPending}
                      onClick={() => save.mutate(row)}>Save</button>)}
                    {!edits[t.code] && t.updated_at && <Pill>saved</Pill>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
