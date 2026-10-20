import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Plus, Save, Search, Send, UserPlus } from "lucide-react";

import { RichText, insertMergeField } from "../components/RichText";
import { Chip, FilterBar, PageHead, useRowLink } from "../components/shell";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import {
  Campaign, CampaignCandidate, ContactType, MERGE_FIELDS, Pipeline, api,
} from "../lib/api";

/**
 * Campaigns (owner, 2026-09-28). Write one marketing email, choose who gets
 * it, and "Enroll and queue": one Outbox row per person, merged for them,
 * waiting for approval. Nothing on this screen sends — except a test to you.
 */
export function Campaigns() {
  const rowLink = useRowLink();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery<Campaign[]>({
    queryKey: ["campaigns"], queryFn: () => api.get<Campaign[]>("/api/campaigns/"),
  });
  const create = useMutation({
    mutationFn: () => api.post<Campaign>("/api/campaigns/", { name: "Untitled campaign" }),
    onSuccess: (made) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      navigate(`/campaigns/${made.id}`);
    },
  });
  const rows = list.data ?? [];

  return (
    <>
      <PageHead title="Campaigns"
        sub="One marketing email, written once, queued for each person you choose. Every copy
             waits in the sending queue for approval."
        action={
          <button className="primary" disabled={create.isPending} onClick={() => create.mutate()}>
            <Plus size={16} /> New campaign
          </button>
        } />
      {create.isError && <Banner kind="bad">{(create.error as Error).message}</Banner>}
      <Card>
        {rows.length === 0 ? <Empty>No campaigns yet.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Subject</th><th className="right">Recipients</th>
              <th className="right">Queued</th><th className="right">Sent</th>
              <th className="right">Unsubscribed</th><th>Created</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} {...rowLink(`/campaigns/${c.id}`)}>
                  <td><Link className="rowname" to={`/campaigns/${c.id}`}>{c.name}</Link></td>
                  <td className="muted">{c.subject || "—"}</td>
                  <td className="right tabular">{c.stats.recipients}</td>
                  <td className="right tabular">{c.stats.queued}</td>
                  <td className="right tabular">{c.stats.sent}</td>
                  <td className="right tabular">{c.stats.unsubscribed}</td>
                  <td className="small muted">{when(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}


export function CampaignDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const path = `/api/campaigns/${id}/`;
  const campaign = useQuery<Campaign>({
    queryKey: ["campaign", id], queryFn: () => api.get<Campaign>(path),
  });
  const [draft, setDraft] = useState<Partial<Campaign>>({});
  const [note, setNote] = useState("");
  // The recipients' choice lives here so "Enroll and queue" can be the page's
  // one primary action, top right, as the brief puts it.
  const [chosen, setChosen] = useState<string[]>([]);
  const queue = useMutation({
    mutationFn: () => api.post<{ queued_count: number; skipped: { name: string; detail: string }[] }>(
      `${path}queue/`, { ids: chosen }),
    onSuccess: (r) => {
      const skipped = r.skipped.length
        ? ` ${r.skipped.length} skipped: ${r.skipped.map((s) => `${s.name} (${s.detail})`).join(", ")}.`
        : "";
      setNote(`${r.queued_count} queued in the sending queue, each waiting for approval.${skipped}`);
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["campaign-candidates", id] });
    },
    onError: (e: Error) => setNote(e.message),
  });
  const c = campaign.data ? { ...campaign.data, ...draft } : null;
  const dirty = Object.keys(draft).length > 0;

  const save = useMutation({
    mutationFn: () => api.patch<Campaign>(path, draft),
    onSuccess: (saved) => {
      qc.setQueryData(["campaign", id], saved);
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setDraft({}); setNote("Saved.");
    },
    onError: (e: Error) => setNote(e.message),
  });
  const testSend = useMutation({
    mutationFn: () => api.post<{ to: string }>(`${path}test-send/`),
    onSuccess: (r) => setNote(`Test sent to ${r.to}. Check it looks right before queueing.`),
    onError: (e: Error) => setNote(e.message),
  });

  if (!c) return <p className="muted">Loading…</p>;
  const set = (patch: Partial<Campaign>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <PageHead title={c.name} crumbs={[{ to: "/campaigns", label: "Campaigns" }]}
        sub={`Created by ${c.created_by_name || "someone"} · ${when(c.created_at)}`}
        action={
          <span className="inline">
            <button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              <Save size={16} /> {save.isPending ? "Saving…" : dirty ? "Save" : "Saved"}
            </button>
            <button disabled={testSend.isPending || dirty}
              title={dirty ? "Save first" : undefined}
              onClick={() => testSend.mutate()}><Send size={16} /> Send me a test</button>
            <button className="primary" disabled={!chosen.length || queue.isPending || dirty}
              title={dirty ? "Save the email first" : undefined}
              onClick={() => queue.mutate()}>
              <UserPlus size={16} /> Enroll and queue {chosen.length || ""}
            </button>
          </span>
        } />
      {note && <Banner kind="info">{note}</Banner>}

      <div className="stat-row">
        {([["Recipients", c.stats.recipients], ["Queued", c.stats.queued],
           ["Sent", c.stats.sent], ["Unsubscribed", c.stats.unsubscribed],
           ["Not sent", c.stats.not_sent]] as const).map(([label, value]) => (
          <div key={label} className="stat"><span className="tile-label">{label}</span>
            <span className="tile-value">{value}</span></div>
        ))}
      </div>

      <div className="compose">
        <Card title="The email">
          <div className="row">
            <Field label="Name">
              <input aria-label="Name" value={c.name} onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="From">
              <select aria-label="From" value={c.sender || "alias"}
                onChange={(e) => set({ sender: e.target.value })}>
                <option value="alias">The practice's address</option>
                <option value="self">My own address</option>
              </select>
            </Field>
          </div>
          <Field label="Subject">
            <input aria-label="Subject" value={c.subject}
              onChange={(e) => set({ subject: e.target.value })} />
          </Field>
          <div className="merge-fields" aria-label="Merge fields">
            <span className="small muted">Insert at the cursor:</span>
            {MERGE_FIELDS.map((field) => (
              <button key={field} type="button" className="small ghost"
                onMouseDown={(e) => { e.preventDefault(); insertMergeField(field); }}>
                {field}
              </button>
            ))}
          </div>
          <div className="tabs" role="tablist" aria-label="How to write it">
            {(["rich", "html"] as const).map((mode) => (
              <button key={mode} role="tab" aria-selected={c.body_mode === mode}
                className={c.body_mode === mode ? "tab on" : "tab"}
                onClick={() => set({ body_mode: mode,
                                     ...(mode === "rich" ? { send_as_is: false } : {}) })}>
                {mode === "rich" ? "Write" : "HTML"}
              </button>
            ))}
          </div>
          {c.body_mode === "rich" ? (
            <RichText label="Email body" value={c.body_html}
              onChange={(html) => set({ body_html: html })} />
          ) : (
            <>
              <textarea aria-label="Email HTML" className="mono code" rows={16}
                value={c.body_html} spellCheck={false}
                onChange={(e) => set({ body_html: e.target.value })} />
              <label className="inline small">
                <input type="checkbox" style={{ width: "auto" }} checked={c.send_as_is}
                  onChange={(e) => set({ send_as_is: e.target.checked })} />
                Send as-is — no branded layout around it
              </label>
              <p className="small muted">
                The unsubscribe link is added either way: every marketing email carries one.
              </p>
            </>
          )}
        </Card>
        <Preview campaign={c} />
      </div>

      <FollowThrough campaign={c} set={set} onNote={setNote} />
      <Recipients campaign={c} onChosen={setChosen} />
    </>
  );
}

const CADENCES: [string, string][] = [
  ["", "No"], ["monthly", "Monthly"], ["bimonthly", "Every other month"],
  ["quarterly", "Quarterly"],
];

/**
 * Owner, 2026-10-19: the campaign's files (up to three, copied onto every
 * draft it makes), and what happens to each person when their copy is
 * approved and sent: a stage to move them to, referral touches at a cadence.
 * Nothing happens at enrolment, nor for a copy refused or deleted.
 */
function FollowThrough({ campaign, set, onNote }: {
  campaign: Campaign; set: (patch: Partial<Campaign>) => void;
  onNote: (text: string) => void;
}) {
  const qc = useQueryClient();
  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const [pipeline, setPipeline] = useState(campaign.on_sent_pipeline ?? "");
  useEffect(() => { setPipeline(campaign.on_sent_pipeline ?? ""); },
            [campaign.on_sent_pipeline]);
  const files = campaign.attachments ?? [];
  const path = `/api/campaigns/${campaign.id}/attachments/`;
  const done = (saved: Campaign) => {
    qc.setQueryData(["campaign", campaign.id],
                    (now: Campaign | undefined) => ({ ...(now ?? saved), attachments: saved.attachments }));
  };
  const add = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.post<Campaign>(path, form);
    },
    onSuccess: done, onError: (e: Error) => onNote(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del<Campaign>(`${path}${id}/`),
    onSuccess: done, onError: (e: Error) => onNote(e.message),
  });
  const stages = (pipelines.data ?? []).find((p) => p.id === pipeline)?.stages ?? [];
  return (
    <Card title="Files and follow-through">
      <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 18rem" }}>
          <h4 style={{ marginTop: 0 }}>Files</h4>
          <p className="small muted">Up to three, each up to 10 MB, on every copy queued
            from now on. A copy already queued keeps what it had.</p>
          {files.length === 0 ? <p className="small muted">No files.</p> : (
            <ul className="plain" aria-label="Campaign files">
              {files.map((f) => (
                <li key={f.id} className="row tight">
                  <span>{f.filename}</span>
                  <span className="small muted">{Math.max(1, Math.round(f.byte_size / 1024))} KB</span>
                  <button className="ghost small" aria-label={`Remove ${f.filename}`}
                    disabled={remove.isPending} onClick={() => remove.mutate(f.id)}>Remove</button>
                </li>
              ))}
            </ul>
          )}
          {files.length < 3 && (
            <input type="file" aria-label="Add a file" disabled={add.isPending}
              onChange={(e) => { const file = e.target.files?.[0];
                                 if (file) add.mutate(file); e.target.value = ""; }} />
          )}
        </div>
        <div style={{ flex: "1 1 22rem" }}>
          <h4 style={{ marginTop: 0 }}>When this campaign is sent</h4>
          <p className="small muted">For each person, when their copy is approved and
            sent. Nothing happens for a copy refused or deleted, or for anyone who has
            unsubscribed. Save to keep a change.</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <Field label="Move them to">
              <select aria-label="Pipeline to move them in" value={pipeline}
                onChange={(e) => { setPipeline(e.target.value);
                                   set({ on_sent_stage: null }); }}>
                <option value="">No move</option>
                {(pipelines.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </Field>
            {pipeline && (
              <Field label="Stage">
                <select aria-label="Stage to move them to"
                  value={campaign.on_sent_stage ?? ""}
                  onChange={(e) => set({ on_sent_stage: e.target.value || null })}>
                  <option value="">Choose a stage…</option>
                  {stages.map((st) => <option key={st.id} value={st.id}>{st.label}</option>)}
                </select>
              </Field>
            )}
            <Field label="Put them on referral touches">
              <select aria-label="Referral touches cadence"
                value={campaign.on_sent_cadence ?? ""}
                onChange={(e) => set({ on_sent_cadence: e.target.value as Campaign["on_sent_cadence"] })}>
                {CADENCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
          </div>
          {campaign.on_sent_cadence && (
            <p className="tiny muted">Only referral partners are put on referral touches;
              anyone else is left off, and their history says so. Someone already on them
              keeps their own cadence.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * The email exactly as it lands — layout, merge fields and unsubscribe link —
 * following the unsaved edits, so what is typed is what is checked.
 */
function Preview({ campaign }: { campaign: Campaign }) {
  const [shown, setShown] = useState<{ subject: string; html: string } | null>(null);
  const body = useMemo(() => ({
    subject: campaign.subject, body_html: campaign.body_html,
    body_mode: campaign.body_mode, send_as_is: campaign.send_as_is, sender: campaign.sender,
  }), [campaign.subject, campaign.body_html, campaign.body_mode, campaign.send_as_is,
       campaign.sender]);
  const render = useMutation({
    mutationFn: () => api.post<{ subject: string; html: string }>(
      `/api/campaigns/${campaign.id}/preview/`, body),
    onSuccess: setShown,
  });
  useEffect(() => {
    const timer = setTimeout(() => render.mutate(), 400);
    return () => clearTimeout(timer);
  }, [body]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card title="Preview">
      <p className="small muted">As it lands, for a sample person. Subject:{" "}
        <strong>{shown?.subject || "—"}</strong></p>
      <iframe title="Email preview" className="email-preview" sandbox=""
        srcDoc={shown?.html ?? ""} />
    </Card>
  );
}

function Recipients({ campaign, onChosen }: {
  campaign: Campaign; onChosen: (ids: string[]) => void;
}) {
  const [filters, setFilters] = useState({ type: "", stage: "", tag: "", enrolled: "" });
  // Nobody is chosen until someone chooses: an empty filter matches every
  // contact, and one click should not queue a hundred emails by default.
  const [picked, setPicked] = useState<string[]>([]);
  const types = useQuery<ContactType[]>({
    queryKey: ["contact-types"], queryFn: () => api.get<ContactType[]>("/api/contact-types/"),
  });
  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
  const found = useQuery<CampaignCandidate[]>({
    queryKey: ["campaign-candidates", campaign.id, query.toString()],
    queryFn: () => api.get<CampaignCandidate[]>(
      `/api/campaigns/${campaign.id}/candidates/?${query}`),
  });
  const rows = found.data ?? [];
  const sendable = rows.filter((r) => !r.unsendable);
  const chosen = sendable.filter((r) => picked.includes(r.id));
  const chosenKey = chosen.map((r) => r.id).join(",");
  useEffect(() => { onChosen(chosen.map((r) => r.id)); }, [chosenKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const setFilter = (key: keyof typeof filters, value: string) => {
    setFilters({ ...filters, [key]: value }); setPicked([]);
  };
  const stages = (pipelines.data ?? []).flatMap((p) => p.stages.map((s) => ({ ...s, pipeline: p.name })));
  const typeLabel = (types.data ?? []).find((t) => t.code === filters.type)?.label;
  const stageLabel = stages.find((s) => s.id === filters.stage);
  const ENROLMENT: Record<string, string> = {
    referral_touches: "On referral touches", digest: "On a progress digest",
    none: "Not enrolled in anything",
  };
  const any = Object.values(filters).some(Boolean);

  return (
    <Card title="Recipients">
      {/* The brief's filter bar: compact controls, then a chip for each filter
          that is set, each clearing on its own. */}
      <FilterBar onClearAll={any ? () => { setFilters({ type: "", stage: "", tag: "", enrolled: "" });
                                           setPicked([]); } : undefined}>
        <span className="search">
          <Search size={16} strokeWidth={1.75} />
          <input aria-label="Filter by tag" placeholder="Tag"
            value={filters.tag} onChange={(e) => setFilter("tag", e.target.value.trim())} />
        </span>
        <select aria-label="Filter by type" value={filters.type} className="filter-select"
          onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">Any type</option>
          {(types.data ?? []).map((t) => <option key={t.id} value={t.code}>{t.label}</option>)}
        </select>
        <select aria-label="Filter by stage" value={filters.stage} className="filter-select"
          onChange={(e) => setFilter("stage", e.target.value)}>
          <option value="">Any stage</option>
          {(pipelines.data ?? []).map((p) => (
            <optgroup key={p.id} label={p.name}>
              {p.stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </optgroup>
          ))}
        </select>
        <select aria-label="Filter by enrollment" value={filters.enrolled} className="filter-select"
          onChange={(e) => setFilter("enrolled", e.target.value)}>
          <option value="">Any enrollment</option>
          {Object.entries(ENROLMENT).map(([value, label]) =>
            <option key={value} value={value}>{label}</option>)}
        </select>
        {filters.type && <Chip label={`Type: ${typeLabel ?? filters.type}`}
          onClear={() => setFilter("type", "")} />}
        {filters.stage && <Chip label={`Stage: ${stageLabel ? `${stageLabel.pipeline} · ${stageLabel.label}` : "—"}`}
          onClear={() => setFilter("stage", "")} />}
        {filters.tag && <Chip label={`Tag: ${filters.tag}`} onClear={() => setFilter("tag", "")} />}
        {filters.enrolled && <Chip label={ENROLMENT[filters.enrolled]}
          onClear={() => setFilter("enrolled", "")} />}
      </FilterBar>

      <p className="small recipients-count" aria-label="How many">
        <strong className="tabular">{rows.length}</strong>
        {rows.length >= 1000 ? " shown (the first 1,000; narrow the filters)" : " shown"}
        {" · "}<strong className="tabular">{chosen.length}</strong> of {sendable.length} chosen
        {rows.length > sendable.length && <> · {rows.length - sendable.length} cannot be sent to</>}
        {" · "}
        <button className="link" disabled={sendable.length === 0}
          onClick={() => setPicked(sendable.map((r) => r.id))}>
          Select all shown ({sendable.length})</button>
        {" · "}
        <button className="link" onClick={() => setPicked([])}>Select none</button>
      </p>

      {rows.length === 0 ? <Empty>No one matches these filters.</Empty> : (
        <table>
          <thead><tr><th></th><th>Name</th><th>Email</th><th>Company</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.unsendable ? "muted" : ""}>
                <td>
                  <input type="checkbox" aria-label={`Include ${r.name}`}
                    disabled={!!r.unsendable}
                    checked={!r.unsendable && picked.includes(r.id)}
                    onChange={(e) => setPicked(e.target.checked
                      ? [...picked, r.id] : picked.filter((x) => x !== r.id))} />
                </td>
                <td>{r.name}</td>
                <td className="small">{r.email || "—"}</td>
                <td className="small muted">{r.company || "—"}</td>
                <td className="small muted">{r.unsendable}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
