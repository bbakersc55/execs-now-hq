import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import { about } from "../lib/plans";
import { Modal } from "./shell";
import { Banner } from "./ui";

/**
 * P13, the connector rails: any system feeds a KPI without a connector built
 * for it. A webhook (an address of the KPI's own, shown once), any MCP server
 * (Claude proposes the tool, a live preview, a person confirms; the nightly
 * read uses no AI), or any API (a GET or POST with period placeholders).
 */
export type RailKind = "webhook" | "mcp" | "api";
export const RAIL_LABEL: Record<RailKind, string> = {
  webhook: "Webhook", mcp: "Any MCP server", api: "Any API" };

interface Delivery { at: string; ok: boolean; what: string; received: string; kpi: string }
interface FeedState { active: boolean; last_run_at: string | null; last_error: string;
  last_success_at: string | null }
interface Connection { id: string; name: string; url?: string; base_url?: string; tools?: string[];
  auth_kind?: string; auth_name?: string; secret_hint: string; check_ok: boolean | null;
  check_detail: string; checked_at: string | null }
interface Preview { period: string; value: string | null; answer: string; error?: string }

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit" }) : "never";
}

function Copyable({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rl-copy">
      <div className="small muted">{label}</div>
      <code>{text}</code>
      <button type="button" className="small" onClick={() => {
        navigator.clipboard?.writeText(text).then(() => setCopied(true)).catch(() => undefined);
      }}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

function Deliveries({ rows }: { rows: Delivery[] }) {
  if (rows.length === 0) return <p className="small muted">Nothing has been posted yet.</p>;
  return (
    <table className="rl-table" aria-label="Last deliveries">
      <thead><tr><th>When</th><th>What was done</th><th>What was received</th></tr></thead>
      <tbody>{rows.map((d, i) => (
        <tr key={i} className={d.ok ? "" : "rl-bad"}><td className="small">{when(d.at)}</td>
          <td>{d.kpi && <strong>{d.kpi}: </strong>}{d.what}</td>
          <td><code className="small">{d.received}</code></td></tr>))}</tbody>
    </table>
  );
}

function StopFeed({ companyId, kpiId, kind, queryKey }: {
  companyId: string; kpiId: string; kind: "webhook" | "mcp-feed" | "api-feed"; queryKey: unknown[];
}) {
  const qc = useQueryClient();
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/rails/${kind}/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey }); qc.invalidateQueries({ queryKey: ["scorecard", companyId] }); },
  });
  if (stop.isSuccess) return <span className="small muted">Stopped: entered by hand again. Its readings are kept.</span>;
  return <button className="ghost small" disabled={stop.isPending} onClick={() => stop.mutate()}>Stop this feed</button>;
}

// ------------------------------------------------------------------ webhook

function WebhookPanel({ companyId, kpiId }: { companyId: string; kpiId: string }) {
  const qc = useQueryClient();
  const key = ["rail-webhook", companyId, kpiId];
  const q = useQuery<{ feed: (FeedState & { mode: string; value_path: string; date_path: string;
    hint: string; last_received_at: string | null; deliveries: Delivery[] }) | null;
    test: { example: string; zapier: string[]; make: string[] }; key: string }>({
    queryKey: key, queryFn: () => api.get(`/api/scorecard/rails/webhook/?company=${companyId}&kpi=${kpiId}`) });
  const [mode, setMode] = useState<string | null>(null);
  const [valuePath, setValuePath] = useState<string | null>(null);
  const [datePath, setDatePath] = useState<string | null>(null);
  const [shown, setShown] = useState<{ token: string; address: string; example: string } | null>(null);
  const company = useQuery<{ exists: boolean; hint: string; keys: { kpi: string; key: string }[];
    deliveries: Delivery[] }>({ queryKey: ["rail-company-webhook", companyId],
    queryFn: () => api.get(`/api/scorecard/rails/company-webhook/?company=${companyId}`) });
  const [companyShown, setCompanyShown] = useState<{ address: string; example: string } | null>(null);
  const save = useMutation({
    mutationFn: () => api.put<{ token?: string; test?: { address: string; example: string } }>(
      "/api/scorecard/rails/webhook/", { company: companyId, kpi: kpiId,
        mode: mode ?? q.data?.feed?.mode ?? "replace",
        value_path: valuePath ?? q.data?.feed?.value_path ?? "",
        date_path: datePath ?? q.data?.feed?.date_path ?? "" }),
    onSuccess: (r) => {
      if (r.token && r.test) setShown({ token: r.token, address: r.test.address, example: r.test.example });
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
    },
  });
  const rotate = useMutation({
    mutationFn: () => api.post<{ token: string; test: { address: string; example: string } }>(
      "/api/scorecard/rails/webhook/rotate/", { company: companyId, kpi: kpiId }),
    onSuccess: (r) => { setShown({ token: r.token, address: r.test.address, example: r.test.example });
      qc.invalidateQueries({ queryKey: key }); },
  });
  const makeCompany = useMutation({
    mutationFn: () => api.post<{ address: string; example: string }>(
      "/api/scorecard/rails/company-webhook/", { company: companyId }),
    onSuccess: (r) => { setCompanyShown(r); qc.invalidateQueries({ queryKey: ["rail-company-webhook", companyId] }); },
  });
  const d = q.data;
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  if (!d) return <p>Loading…</p>;
  const feed = d.feed;
  return (
    <div className="rl-panel">
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {shown && (
        <Banner kind="ok">This address is shown once. Copy it now; it is stored only as a hash.
          <Copyable label="The KPI's address" text={shown.address} />
          <Copyable label="A test post" text={shown.example} /></Banner>
      )}
      <p className="small muted">Any system that can send a POST feeds this KPI: a value, and
        optionally a date (YYYY-MM-DD) and a note, as JSON, form fields or query parameters.
        Readings are marked "From a webhook". A reading typed by hand is never replaced.</p>
      <div className="rl-form">
        <label>Each post<select value={mode ?? feed?.mode ?? "replace"} onChange={(e) => setMode(e.target.value)}>
          <option value="replace">Replaces the period's reading</option>
          <option value="add">Adds to the period's reading (one event at a time)</option></select></label>
        <label>Path to the value (for another system's own payload)<input placeholder="value"
          value={valuePath ?? feed?.value_path ?? ""} onChange={(e) => setValuePath(e.target.value)} /></label>
        <label>Path to the date (optional)<input placeholder="date"
          value={datePath ?? feed?.date_path ?? ""} onChange={(e) => setDatePath(e.target.value)} /></label>
      </div>
      <div className="row tight">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          {feed ? "Save" : "Make the address"}</button>
        {feed && <button disabled={rotate.isPending} onClick={() => rotate.mutate()}>Rotate the address</button>}
        {feed?.active && <StopFeed companyId={companyId} kpiId={kpiId} kind="webhook" queryKey={key} />}
        {feed && <span className="small muted">Address ending …{feed.hint} · last post {when(feed.last_received_at)}</span>}
      </div>
      <details className="rl-test" open={!feed}>
        <summary>Test panel</summary>
        <Copyable label="A ready-to-copy test (put in your address)" text={d.test.example} />
        <div className="rl-steps">
          <div><strong>Zapier</strong><ol className="small">{d.test.zapier.map((s) => <li key={s}>{s}</li>)}</ol></div>
          <div><strong>Make</strong><ol className="small">{d.test.make.map((s) => <li key={s}>{s}</li>)}</ol></div>
        </div>
      </details>
      {feed && <><h4>Last 20 deliveries</h4><Deliveries rows={feed.deliveries} /></>}
      <details className="rl-test">
        <summary>The company's address (one for all its webhook KPIs)</summary>
        {companyShown && <Banner kind="ok">Shown once:
          <Copyable label="The company's address" text={companyShown.address} />
          <Copyable label="A test post" text={companyShown.example} /></Banner>}
        <p className="small muted">Post <code>{"{\"kpi\": \"<key>\", \"value\": 12}"}</code>. This KPI's key
          is <code>{d.key}</code>.</p>
        <button className="small" disabled={makeCompany.isPending} onClick={() => makeCompany.mutate()}>
          {company.data?.exists ? `Rotate it (ends …${company.data.hint})` : "Make the company's address"}</button>
        {company.data?.exists && <Deliveries rows={company.data.deliveries} />}
      </details>
    </div>
  );
}

// ------------------------------------------------------------------ connections

function Connections({ companyId, kind, chosen, onChoose, owner }: {
  companyId: string; kind: "mcp" | "api"; chosen: string; onChoose: (id: string) => void;
  owner: boolean;
}) {
  const qc = useQueryClient();
  const key = ["rail-connections", kind, companyId];
  const q = useQuery<{ connections: Connection[]; demo: boolean }>({ queryKey: key,
    queryFn: () => api.get(`/api/scorecard/rails/${kind}/?company=${companyId}`) });
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", url: "", token: "", headers: "", base_url: "",
    auth_kind: "header", auth_name: "", secret: "" });
  const [tools, setTools] = useState<{ name: string; description: string }[] | null>(null);
  const add = useMutation({
    mutationFn: () => {
      if (kind === "mcp") {
        let headers = {};
        if (f.headers.trim()) headers = JSON.parse(f.headers);
        return api.post<Connection>("/api/scorecard/rails/mcp/", { company: companyId, name: f.name,
          url: f.url, token: f.token, headers });
      }
      return api.post<Connection>("/api/scorecard/rails/api/", { company: companyId, name: f.name,
        base_url: f.base_url, auth_kind: f.auth_kind, auth_name: f.auth_name, secret: f.secret });
    },
    onSuccess: (c) => { setAdding(false); onChoose(c.id); qc.invalidateQueries({ queryKey: key }); },
  });
  const test = useMutation({
    mutationFn: (id: string) => api.post<Connection & { tool_list: { name: string; description: string }[] }>(
      `/api/scorecard/rails/mcp/${id}/test/`),
    onSuccess: (r) => { setTools(r.tool_list); qc.invalidateQueries({ queryKey: key }); },
    onError: () => qc.invalidateQueries({ queryKey: key }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/scorecard/rails/${kind}/${id}/`),
    onSuccess: () => { onChoose(""); qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] }); },
  });
  const list = q.data?.connections ?? [];
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch });
  return (
    <div className="rl-connections">
      {q.data?.demo && <Banner>This is the demo: it never connects to another system. The example
        connection shows how one looks.</Banner>}
      {list.length === 0 ? <p className="small muted">No connection yet.</p> : (
        <label>Connection<select value={chosen} onChange={(e) => onChoose(e.target.value)}>
          <option value="">Choose one</option>
          {list.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.url ?? c.base_url}</option>)}
        </select></label>
      )}
      {chosen && (() => {
        const c = list.find((x) => x.id === chosen);
        if (!c) return null;
        return (
          <div className="small muted">Secret ending …{c.secret_hint || "none"}
            {c.checked_at && <> · <span className={c.check_ok ? "" : "rl-bad-text"}>{c.check_detail}</span></>}
            {kind === "mcp" && <> · <button className="small ghost" disabled={test.isPending}
              onClick={() => test.mutate(c.id)}>Test connection</button></>}
            {owner && <> · <button className="small ghost" disabled={remove.isPending}
              aria-label={`Remove the connection ${c.name}`}
              onClick={() => remove.mutate(c.id)}>Remove</button></>}</div>
        );
      })()}
      {test.isError && <Banner kind="bad">{(test.error as Error).message}</Banner>}
      {tools && <ul className="small rl-tools" aria-label="The server's tools">{tools.map((t) => (
        <li key={t.name}><code>{t.name}</code> {t.description}</li>))}</ul>}
      {remove.isError && <Banner kind="bad">{(remove.error as Error).message}</Banner>}
      {!owner ? <p className="small muted">The practice owner adds connections to other systems.</p>
        : !adding ? <button className="small" onClick={() => setAdding(true)}>Add a connection</button> : (
        <div className="rl-form">
          {add.isError && <Banner kind="bad">{(add.error as Error).message}</Banner>}
          <label>Name<input value={f.name} onChange={(e) => set({ name: e.target.value })} /></label>
          {kind === "mcp" ? <>
            <label>Server address (https, Streamable HTTP)<input placeholder="https://mcp.vendor.com/mcp"
              value={f.url} onChange={(e) => set({ url: e.target.value })} /></label>
            <label>Token (sent as Bearer)<input type="password" value={f.token} onChange={(e) => set({ token: e.target.value })} /></label>
            <label>Or headers, as JSON<input placeholder='{"X-Api-Key": "…"}' value={f.headers}
              onChange={(e) => set({ headers: e.target.value })} /></label>
          </> : <>
            <label>Base address (https)<input placeholder="https://api.vendor.com/v1" value={f.base_url}
              onChange={(e) => set({ base_url: e.target.value })} /></label>
            <label>The secret goes<select value={f.auth_kind} onChange={(e) => set({ auth_kind: e.target.value })}>
              <option value="header">In a header</option><option value="basic">As basic sign-in (user:password)</option>
              <option value="query">As a query key</option></select></label>
            {f.auth_kind !== "basic" && <label>{f.auth_kind === "header" ? "Header name" : "Query key name"}
              <input placeholder={f.auth_kind === "header" ? "Authorization" : "api_key"} value={f.auth_name}
                onChange={(e) => set({ auth_name: e.target.value })} /></label>}
            <label>Secret<input type="password" value={f.secret} onChange={(e) => set({ secret: e.target.value })} /></label>
          </>}
          <p className="small muted">The secret is stored encrypted and never shown again.</p>
          <div className="row tight">
            <button className="primary small" disabled={add.isPending || !f.name.trim()} onClick={() => add.mutate()}>Save the connection</button>
            <button className="small" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

function PreviewBox({ p }: { p: Preview | null }) {
  if (!p) return null;
  if (p.error) return <Banner kind="bad">{p.error}</Banner>;
  return (
    <div className="rl-preview" aria-label="Live preview">
      <div><strong>{p.period}:</strong> {p.value === null ? <span className="rl-bad-text">no number at that path</span>
        : <span className="rl-value">{p.value}</span>}</div>
      <details><summary className="small">What the server answered</summary><pre className="small">{p.answer}</pre></details>
    </div>
  );
}

// ------------------------------------------------------------------ MCP

function McpPanel({ companyId, kpiId, owner }: { companyId: string; kpiId: string; owner: boolean }) {
  const qc = useQueryClient();
  const q = useQuery<{ feed: (FeedState & { connection: string; tool: string; arguments: object;
    value_path: string }) | null; ai: { estimate_usd: string; refused: string } ; placeholders: string[] }>({
    queryKey: ["rail-mcp-feed", companyId, kpiId],
    queryFn: () => api.get(`/api/scorecard/rails/mcp-feed/?company=${companyId}&kpi=${kpiId}`) });
  const feed = q.data?.feed;
  const [connection, setConnection] = useState("");
  const [description, setDescription] = useState("");
  const [tool, setTool] = useState<string | null>(null);
  const [args, setArgs] = useState<string | null>(null);
  const [path, setPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fromAi, setFromAi] = useState(false);
  const [why, setWhy] = useState("");
  const conn = connection || feed?.connection || "";
  const body = () => ({ company: companyId, kpi: kpiId, connection: conn,
    tool: tool ?? feed?.tool ?? "", arguments: args ?? JSON.stringify(feed?.arguments ?? {}),
    value_path: path ?? feed?.value_path ?? "", from_ai: fromAi });
  const propose = useMutation({
    mutationFn: () => api.post<{ proposal: { tool: string; arguments: object; path: string; why: string };
      preview: Preview | null }>("/api/scorecard/rails/mcp-feed/propose/",
      { company: companyId, kpi: kpiId, connection: conn, description }),
    onSuccess: (r) => {
      setTool(r.proposal.tool); setArgs(JSON.stringify(r.proposal.arguments, null, 1));
      setPath(r.proposal.path); setPreview(r.preview); setFromAi(true); setWhy(r.proposal.why);
    },
  });
  const run = useMutation({
    mutationFn: () => api.post<Preview>("/api/scorecard/rails/mcp-feed/preview/", body()),
    onSuccess: setPreview,
  });
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; error?: string } }>("/api/scorecard/rails/mcp-feed/", body()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rail-mcp-feed", companyId, kpiId] });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] }); },
  });
  const ai = q.data?.ai;
  return (
    <div className="rl-panel">
      <p className="small muted">A connection to another vendor's MCP server. Describe the number;
        Claude proposes the tool, its arguments and where the number is in the answer; you see a live
        preview and confirm. After that it is read once a day with no AI. Or set it by hand.</p>
      <Connections companyId={companyId} kind="mcp" chosen={conn} onChoose={setConnection} owner={owner} />
      {feed?.active && <p className="small">Reading now: <code>{feed.tool}</code> → <code>{feed.value_path}</code> ·
        last read {when(feed.last_run_at)}{feed.last_error && <span className="rl-bad-text"> · {feed.last_error}</span>}
        {" "}<StopFeed companyId={companyId} kpiId={kpiId} kind="mcp-feed" queryKey={["rail-mcp-feed", companyId, kpiId]} /></p>}
      {conn && <>
        <label>The number you want<input value={description} placeholder="Tickets still open at the end of each week"
          onChange={(e) => setDescription(e.target.value)} /></label>
        <div className="row tight">
          {ai?.refused ? <Banner kind="warn">{ai.refused}</Banner> : (
            <button disabled={!ai || propose.isPending || description.trim().length < 6}
              onClick={() => propose.mutate()}>{propose.isPending ? "Asking Claude…"
                : `Propose it with Claude (${about(ai?.estimate_usd)})`}</button>)}
        </div>
        {propose.isError && <Banner kind="bad">{(propose.error as Error).message}</Banner>}
        {why && <p className="small"><strong>Claude:</strong> {why}{propose.data?.proposal.tool ? "" : " Set it by hand below."}</p>}
        <div className="rl-form">
          <label>Tool<input value={tool ?? feed?.tool ?? ""} onChange={(e) => { setTool(e.target.value); setFromAi(false); }} /></label>
          <label>Arguments (JSON, with {(q.data?.placeholders ?? []).join(", ")})<textarea rows={3}
            value={args ?? JSON.stringify(feed?.arguments ?? {})} onChange={(e) => setArgs(e.target.value)} /></label>
          <label>Path to the number<input placeholder="data.total" value={path ?? feed?.value_path ?? ""}
            onChange={(e) => setPath(e.target.value)} /></label>
        </div>
        <div className="row tight">
          <button disabled={run.isPending} onClick={() => run.mutate()}>Preview it</button>
          <button className="primary" disabled={save.isPending || !preview || preview.value === null}
            onClick={() => save.mutate()}>Confirm and read it</button>
        </div>
        {run.isError && <Banner kind="bad">{(run.error as Error).message}</Banner>}
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
        {save.isSuccess && <Banner kind="ok">Saved; read once a day from now on.</Banner>}
        <PreviewBox p={preview} />
      </>}
    </div>
  );
}

// ------------------------------------------------------------------ any API

function ApiPanel({ companyId, kpiId, owner }: { companyId: string; kpiId: string; owner: boolean }) {
  const qc = useQueryClient();
  const q = useQuery<{ feed: (FeedState & { connection: string; method: string; path: string;
    query: object; body: unknown; value_path: string }) | null; placeholders: string[] }>({
    queryKey: ["rail-api-feed", companyId, kpiId],
    queryFn: () => api.get(`/api/scorecard/rails/api-feed/?company=${companyId}&kpi=${kpiId}`) });
  const feed = q.data?.feed;
  const [connection, setConnection] = useState("");
  const [f, setF] = useState<{ method: string; path: string; query: string; body: string; value_path: string } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const form = f ?? { method: feed?.method ?? "GET", path: feed?.path ?? "",
    query: JSON.stringify(feed?.query ?? {}), body: feed?.body ? JSON.stringify(feed.body) : "",
    value_path: feed?.value_path ?? "" };
  const conn = connection || feed?.connection || "";
  const body = () => ({ company: companyId, kpi: kpiId, connection: conn, ...form });
  const run = useMutation({
    mutationFn: () => api.post<Preview>("/api/scorecard/rails/api-feed/preview/", body()),
    onSuccess: setPreview,
  });
  const save = useMutation({
    mutationFn: () => api.put("/api/scorecard/rails/api-feed/", body()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rail-api-feed", companyId, kpiId] });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] }); },
  });
  const set = (patch: Partial<typeof form>) => setF({ ...form, ...patch });
  return (
    <div className="rl-panel">
      <p className="small muted">A GET or POST to an API, with the period in the path, query or body,
        and the path to the value in its JSON answer. Read once a day with the other feeds.</p>
      <Connections companyId={companyId} kind="api" chosen={conn} onChoose={setConnection} owner={owner} />
      {feed?.active && <p className="small">Reading now: {feed.method} <code>{feed.path}</code> → <code>{feed.value_path}</code> ·
        last read {when(feed.last_run_at)}{feed.last_error && <span className="rl-bad-text"> · {feed.last_error}</span>}
        {" "}<StopFeed companyId={companyId} kpiId={kpiId} kind="api-feed" queryKey={["rail-api-feed", companyId, kpiId]} /></p>}
      {conn && <>
        <div className="rl-form">
          <label>Method<select value={form.method} onChange={(e) => set({ method: e.target.value })}>
            <option>GET</option><option>POST</option></select></label>
          <label>Path (after the base address)<input placeholder="/reports/{year}-{month}" value={form.path}
            onChange={(e) => set({ path: e.target.value })} /></label>
          <label>Query (JSON)<input placeholder='{"from": "{period_start}", "to": "{period_end}"}' value={form.query}
            onChange={(e) => set({ query: e.target.value })} /></label>
          {form.method === "POST" && <label>Body (JSON)<textarea rows={3} value={form.body}
            onChange={(e) => set({ body: e.target.value })} /></label>}
          <label>Path to the value<input placeholder="data.total" value={form.value_path}
            onChange={(e) => set({ value_path: e.target.value })} /></label>
        </div>
        <p className="small muted">Placeholders: {(q.data?.placeholders ?? []).join(", ")}</p>
        <div className="row tight">
          <button disabled={run.isPending} onClick={() => run.mutate()}>Preview it</button>
          <button className="primary" disabled={save.isPending || !preview || preview.value === null}
            onClick={() => save.mutate()}>Save and read it</button>
        </div>
        {run.isError && <Banner kind="bad">{(run.error as Error).message}</Banner>}
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
        {save.isSuccess && <Banner kind="ok">Saved; read once a day from now on.</Banner>}
        <PreviewBox p={preview} />
      </>}
    </div>
  );
}

export function RailFeedModal({ companyId, kpiId, kpiName, kind, owner, onClose }: {
  companyId: string; kpiId: string; kpiName: string; kind: RailKind;
  /** The practice owner makes and removes connections (as with Besty). */
  owner: boolean; onClose: () => void;
}) {
  const [tab, setTab] = useState<RailKind>(kind);
  return (
    <Modal label={`Connect anything to ${kpiName}`} title={`${kpiName}: connect anything`} wide onClose={onClose}>
      <div className="pl-tabs" role="tablist" aria-label="Rails">
        {(["webhook", "mcp", "api"] as RailKind[]).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`pl-tab${tab === k ? " on" : ""}`}
            onClick={() => setTab(k)}>{RAIL_LABEL[k]}</button>))}
      </div>
      {tab === "webhook" && <WebhookPanel companyId={companyId} kpiId={kpiId} />}
      {tab === "mcp" && <McpPanel companyId={companyId} kpiId={kpiId} owner={owner} />}
      {tab === "api" && <ApiPanel companyId={companyId} kpiId={kpiId} owner={owner} />}
    </Modal>
  );
}

export function ConnectorRequestModal({ clientName, onClose }: { clientName: string; onClose: () => void }) {
  const [f, setF] = useState({ system: "", numbers: "", client: clientName });
  const send = useMutation({
    mutationFn: () => api.post("/api/scorecard/rails/request/", { ...f, page_url: window.location.pathname }),
  });
  return (
    <Modal label="Request a connector" title="Request a connector" onClose={onClose}>
      {send.isError && <Banner kind="bad">{(send.error as Error).message}</Banner>}
      {send.isSuccess ? <Banner kind="ok">Sent. It lands with the platform owner as a connector request.</Banner> : <>
        <label>The system<input value={f.system} onChange={(e) => setF({ ...f, system: e.target.value })} /></label>
        <label>Which numbers you want from it<textarea rows={3} value={f.numbers}
          onChange={(e) => setF({ ...f, numbers: e.target.value })} /></label>
        <label>For which client<input value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} /></label>
      </>}
      <div className="row tight">
        {!send.isSuccess && <button className="primary" disabled={!f.system.trim() || !f.numbers.trim() || send.isPending}
          onClick={() => send.mutate()}>Send the request</button>}
        <button onClick={onClose}>{send.isSuccess ? "Done" : "Cancel"}</button>
      </div>
    </Modal>
  );
}

