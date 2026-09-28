import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { RichText } from "../components/RichText";
import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import {
  Campaign, CampaignCandidate, ContactType, MERGE_FIELDS, Pipeline, api,
} from "../lib/api";

/**
 * Campaigns (owner, 2026-09-28). Write one marketing email, choose who gets
 * it, and "Enrol and queue": one Outbox row per person, merged for them,
 * waiting for approval. Nothing on this screen sends — except a test to you.
 */
export function Campaigns() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const list = useQuery<Campaign[]>({
    queryKey: ["campaigns"], queryFn: () => api.get<Campaign[]>("/api/campaigns/"),
  });
  const create = useMutation({
    mutationFn: () => api.post<Campaign>("/api/campaigns/", { name }),
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
             waits in the sending queue for approval." />
      <Card title="New campaign">
        <form className="row" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label="Name (only you see this)">
            <input aria-label="Campaign name" value={name} placeholder="Autumn check-in"
              onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="field-action">
            <button className="primary" type="submit"
              disabled={!name.trim() || create.isPending}>Create</button>
          </div>
        </form>
        {create.isError && <Banner kind="bad">{(create.error as Error).message}</Banner>}
      </Card>
      <Card title="Campaigns">
        {rows.length === 0 ? <Empty>No campaigns yet.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Subject</th><th className="right">Recipients</th>
              <th className="right">Queued</th><th className="right">Sent</th>
              <th className="right">Unsubscribed</th><th>Created</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/campaigns/${c.id}`}>{c.name}</Link></td>
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

/** Insert a merge field where the cursor is, in the editor or the HTML box. */
function insertAtCursor(token: string) {
  // Both the rich editor and a textarea take insertText at the caret.
  document.execCommand("insertText", false, token);
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
            <button disabled={testSend.isPending || dirty}
              title={dirty ? "Save first" : undefined}
              onClick={() => testSend.mutate()}>Send me a test</button>
            <button className="primary" disabled={!dirty || save.isPending}
              onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save"}</button>
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
                onMouseDown={(e) => { e.preventDefault(); insertAtCursor(field); }}>
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

      <Recipients campaign={c} dirty={dirty} setNote={setNote} />
    </>
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

function Recipients({ campaign, dirty, setNote }: {
  campaign: Campaign; dirty: boolean; setNote: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [filters, setFilters] = useState({ type: "", stage: "", tag: "", enrolled: "" });
  const [dropped, setDropped] = useState<string[]>([]);
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
  const chosen = sendable.filter((r) => !dropped.includes(r.id));
  const queue = useMutation({
    mutationFn: () => api.post<{ queued_count: number; skipped: { name: string; detail: string }[] }>(
      `/api/campaigns/${campaign.id}/queue/`, { ids: chosen.map((r) => r.id) }),
    onSuccess: (r) => {
      const skipped = r.skipped.length
        ? ` ${r.skipped.length} skipped: ${r.skipped.map((s) => `${s.name} (${s.detail})`).join(", ")}.`
        : "";
      setNote(`${r.queued_count} queued in the sending queue, each waiting for approval.${skipped}`);
      setDropped([]);
      qc.invalidateQueries({ queryKey: ["campaign", campaign.id] });
      qc.invalidateQueries({ queryKey: ["campaign-candidates", campaign.id] });
    },
    onError: (e: Error) => setNote(e.message),
  });
  const setFilter = (key: keyof typeof filters, value: string) => {
    setFilters({ ...filters, [key]: value }); setDropped([]);
  };

  return (
    <Card title="Recipients">
      <div className="row">
        <Field label="Type">
          <select aria-label="Filter by type" value={filters.type}
            onChange={(e) => setFilter("type", e.target.value)}>
            <option value="">Any</option>
            {(types.data ?? []).map((t) => <option key={t.id} value={t.code}>{t.label}</option>)}
          </select>
        </Field>
        <Field label="Pipeline stage">
          <select aria-label="Filter by stage" value={filters.stage}
            onChange={(e) => setFilter("stage", e.target.value)}>
            <option value="">Any</option>
            {(pipelines.data ?? []).map((p) => (
              <optgroup key={p.id} label={p.name}>
                {p.stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </optgroup>
            ))}
          </select>
        </Field>
        <Field label="Tag">
          <input aria-label="Filter by tag" value={filters.tag}
            onChange={(e) => setFilter("tag", e.target.value.trim())} />
        </Field>
        <Field label="Enrolment">
          <select aria-label="Filter by enrolment" value={filters.enrolled}
            onChange={(e) => setFilter("enrolled", e.target.value)}>
            <option value="">Any</option>
            <option value="referral_touches">On referral touches</option>
            <option value="digest">On a progress digest</option>
            <option value="none">Not enrolled in anything</option>
          </select>
        </Field>
      </div>

      <div className="spread" style={{ margin: "var(--s3) 0" }}>
        <span className="small">
          <strong>{chosen.length}</strong> of {sendable.length} chosen
          {rows.length > sendable.length && <> · {rows.length - sendable.length} cannot be sent to</>}
          {" · "}
          <button className="link" onClick={() => setDropped([])}>Select all</button>
          {" · "}
          <button className="link" onClick={() => setDropped(sendable.map((r) => r.id))}>
            Select none</button>
        </span>
        <button className="primary" disabled={!chosen.length || queue.isPending || dirty}
          title={dirty ? "Save the email first" : undefined}
          onClick={() => queue.mutate()}>
          Enrol and queue {chosen.length || ""}
        </button>
      </div>

      {rows.length === 0 ? <Empty>No one matches these filters.</Empty> : (
        <table>
          <thead><tr><th></th><th>Name</th><th>Email</th><th>Company</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.unsendable ? "muted" : ""}>
                <td>
                  <input type="checkbox" aria-label={`Include ${r.name}`}
                    disabled={!!r.unsendable}
                    checked={!r.unsendable && !dropped.includes(r.id)}
                    onChange={(e) => setDropped(e.target.checked
                      ? dropped.filter((x) => x !== r.id) : [...dropped, r.id])} />
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
