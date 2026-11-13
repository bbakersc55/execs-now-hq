/**
 * The SOP studio (P10, docs/p10_sop_studio.md).
 *
 * - The practice: every SOP by client (the Operations Command Center's shelf
 *   and /sops), an SOPs card on each company page, and the editor: the
 *   working copy, publishing it as a numbered version, who has read it, and
 *   the suggestions people sent.
 * - The portal: the SOPs published to this person, each read on the page and
 *   ticked "Read and understood"; the client owner also sees who has read it.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Modal, PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { api, Me } from "../lib/api";
import {
  Attachment, Audience, Brainstorm, longDay, PackChoices, Reads, readsLine, Role, Section,
  SopFull, SopList, SopPortal, SopStatus, SopSummary, Step, STATUS_LABEL, STATUS_PILL, svgSrc,
} from "../lib/sops";

const STAFF = ["FF", "CF", "VA"];

function companyName(c: { name: string; is_practice: boolean }) {
  return c.is_practice ? "Our practice" : c.name;
}

function errorOf(e: unknown): string {
  const err = e as Error & { data?: { errors?: string[] } };
  const more = err?.data?.errors?.length ? ` ${err.data.errors.join(" ")}` : "";
  return `${err?.message ?? "Something went wrong."}${more}`;
}

export function StatusTag({ status }: { status: SopStatus }) {
  return <Pill kind={STATUS_PILL[status]}>{STATUS_LABEL[status]}</Pill>;
}

// ------------------------------------------------------------------ the list

type StatusFilter = "" | SopStatus | "all";

/** Every SOP the practice reaches, by client, with search and filters. */
export function SopListView({ compact = false }: { compact?: boolean }) {
  const q = useQuery<SopList>({ queryKey: ["sops", "all"],
    queryFn: () => api.get<SopList>("/api/sops/?status=all") });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  const [category, setCategory] = useState("");
  const [company, setCompany] = useState("");
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  if (!q.data) return <p className="small muted">Loading…</p>;
  const all = q.data.sops;
  const companies = Array.from(new Map(all.map((s) => [s.company.id, s.company])).values())
    .sort((a, b) => companyName(a).localeCompare(companyName(b)));
  const categories = Array.from(new Set(all.map((s) => s.category).filter(Boolean))).sort();
  const words = search.trim().toLowerCase();
  const shown = all.filter((s) => (status === "all" ? true : status ? s.status === status
    : s.status !== "archived"))
    .filter((s) => !category || s.category === category)
    .filter((s) => !company || s.company.id === company)
    .filter((s) => !words || `${s.title} ${s.category} ${s.company.name} ${s.owner}`
      .toLowerCase().includes(words));
  const groups = new Map<string, SopSummary[]>();
  for (const s of shown) groups.set(s.company.id, [...(groups.get(s.company.id) ?? []), s]);
  return (
    <div className="sop-list">
      <div className="sop-filters" role="search" aria-label="Find an SOP">
        <input aria-label="Search SOPs" placeholder="Search SOPs" value={search}
          onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Client" value={company} onChange={(e) => setCompany(e.target.value)}>
          <option value="">Every client</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{companyName(c)}</option>)}
        </select>
        <select aria-label="Status" value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}>
          <option value="">Drafts and published</option>
          <option value="draft">Drafts</option>
          <option value="published">Published</option>
          <option value="archived">Archived</option>
          <option value="all">Everything</option>
        </select>
        {categories.length > 0 && (
          <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Every category</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>)}
      </div>
      {all.length === 0 ? <Empty>No SOPs yet. Start one from a company's page, or with New SOP.</Empty>
        : shown.length === 0 ? <Empty>No SOP matches.</Empty> : (
          Array.from(groups.entries()).map(([id, rows]) => (
            <section key={id} className="sop-group" aria-label={`SOPs for ${companyName(rows[0].company)}`}>
              <h4>{companyName(rows[0].company)}</h4>
              <ul className="sop-rows">
                {rows.map((s) => (
                  <li key={s.id}>
                    <Link to={`/sops/${s.id}`}>{s.title}</Link>{" "}
                    <StatusTag status={s.status} />
                    {s.version > 0 && <span className="small muted"> · Version {s.version}</span>}
                    {readsLine(s.reads) && <span className="small"> · {readsLine(s.reads)}</span>}
                    {!compact && s.category && <span className="small muted"> · {s.category}</span>}
                    {s.review_date && <span className="small muted"> · Review by {longDay(s.review_date)}</span>}
                    {s.from_ai_app && <> <Pill kind="info">From an AI app</Pill></>}
                  </li>
                ))}
              </ul>
            </section>
          )))}
    </div>
  );
}

function NewSopModal({ companyId, onClose }: { companyId?: string; onClose: () => void }) {
  const navigate = useNavigate();
  const plans = useQuery<{ plans: { id: string; name: string; is_practice: boolean }[] }>({
    queryKey: ["plans"], queryFn: () => api.get("/api/plans/"), enabled: !companyId });
  const [company, setCompany] = useState(companyId ?? "");
  const [title, setTitle] = useState("");
  const go = useMutation({
    mutationFn: () => api.post<SopFull>("/api/sops/", { company, title }),
    onSuccess: (s) => navigate(`/sops/${s.id}`),
  });
  return (
    <Modal label="New SOP" title="New SOP" onClose={onClose}>
      {go.isError && <Banner kind="bad">{errorOf(go.error)}</Banner>}
      <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)}
        placeholder="For example: Receiving and checking an order" /></label>
      {!companyId && (
        <label>For<select value={company} onChange={(e) => setCompany(e.target.value)}>
          <option value="">Choose a company</option>
          {(plans.data?.plans ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.is_practice ? "Our practice" : p.name}</option>))}
        </select></label>)}
      <p className="small muted">It starts as a draft from the SOP template. Nobody is asked to
        read it until it is published.</p>
      <div className="row tight">
        <button className="primary" disabled={!company || !title.trim() || go.isPending}
          onClick={() => go.mutate()}>Make the draft</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function StaffSops() {
  const [making, setMaking] = useState(false);
  return (
    <div className="sop-page">
      <PageHead title="SOPs" sub="Every standard operating procedure, by client: drafts, what is published, and who has read it."
        action={<button className="primary" onClick={() => setMaking(true)}>New SOP</button>} />
      <Card><SopListView /></Card>
      {making && <NewSopModal onClose={() => setMaking(false)} />}
    </div>
  );
}

/** The portal's list: what is published to this person, and whether they have read it. */
function PortalSops() {
  const q = useQuery<SopList>({ queryKey: ["sops", "mine"], queryFn: () => api.get<SopList>("/api/sops/") });
  const rows = q.data?.sops ?? [];
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  return (
    <div className="sop-page">
      <PageHead title="SOPs" sub="How the work is done here, step by step. Read each one and tick “Read and understood”." />
      {!q.data ? <p>Loading…</p> : rows.length === 0 ? <Empty>Nothing is published to you yet.</Empty> : (
        <Card>
          <ul className="sop-rows sop-portal-rows">
            {rows.map((s) => {
              const v = s.mine;
              return (
                <li key={s.id}>
                  <Link to={`/sops/${s.id}`}>{s.title}</Link>
                  <span className="small muted"> · Version {s.version}</span>{" "}
                  {v && (v.read ? <Pill kind="ok">Read ✓ {longDay(v.read_at)}</Pill>
                    : v.asked ? <Pill kind="warn">To read</Pill> : null)}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function SopsScreen({ me }: { me: Me }) {
  return STAFF.includes(me.role ?? "") ? <StaffSops /> : <PortalSops />;
}

export function SopScreen({ me }: { me: Me }) {
  return STAFF.includes(me.role ?? "") ? <SopEditor /> : <SopReader />;
}

// ------------------------------------------------------------------ cards elsewhere

/** The Operations Command Center's SOPs shelf. */
export function SopsShelfCard() {
  const [making, setMaking] = useState(false);
  return (
    <Card title="SOPs" actions={<div className="row tight">
      <button className="small" onClick={() => setMaking(true)}>New SOP</button>
      <Link className="btn small" to="/sops">All SOPs</Link></div>}>
      <SopListView compact />
      {making && <NewSopModal onClose={() => setMaking(false)} />}
    </Card>
  );
}

/** A company page's SOPs card: its SOPs, a new one, a brainstorm, the Notebook pack. */
export function CompanySopsCard({ me, companyId, isClient }: {
  me: Me; companyId: string; isClient: boolean;
}) {
  const navigate = useNavigate();
  const q = useQuery<SopList>({ queryKey: ["sops", "company", companyId],
    queryFn: () => api.get<SopList>(`/api/sops/?company=${companyId}`) });
  const [making, setMaking] = useState(false);
  const [packing, setPacking] = useState(false);
  const brainstorm = useMutation({
    mutationFn: () => api.post<Brainstorm>("/api/sops/brainstorms/", { company: companyId }),
    onSuccess: (b) => navigate(`/sop-brainstorms/${b.id}`),
  });
  if (q.isError) return null;
  const rows = q.data?.sops ?? [];
  const packs = isClient && (me.role === "FF" || me.role === "CF");
  return (
    <div id="sops">
      <Card title="SOPs" actions={<div className="row tight">
        <button className="small" onClick={() => setMaking(true)}>New SOP</button>
        <button className="small" disabled={brainstorm.isPending} onClick={() => brainstorm.mutate()}>
          Brainstorm a process</button>
        {packs && <button className="small" onClick={() => setPacking(true)}>Notebook pack</button>}
      </div>}>
        {brainstorm.isError && <Banner kind="bad">{errorOf(brainstorm.error)}</Banner>}
        {!q.data ? <p className="small muted">Loading…</p> : rows.length === 0
          ? <p className="small muted">No SOPs for this company yet.</p> : (
            <ul className="sop-rows">
              {rows.map((s) => (
                <li key={s.id}><Link to={`/sops/${s.id}`}>{s.title}</Link>{" "}
                  <StatusTag status={s.status} />
                  {s.version > 0 && <span className="small muted"> · Version {s.version}</span>}
                  {readsLine(s.reads) && <span className="small"> · {readsLine(s.reads)}</span>}</li>))}
            </ul>)}
      </Card>
      {making && <NewSopModal companyId={companyId} onClose={() => setMaking(false)} />}
      {packing && <NotebookPackModal companyId={companyId} onClose={() => setPacking(false)} />}
    </div>
  );
}

function NotebookPackModal({ companyId, onClose }: { companyId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery<PackChoices>({ queryKey: ["sop-pack", companyId],
    queryFn: () => api.get<PackChoices>(`/api/sops/pack/?company=${companyId}`) });
  const [runs, setRuns] = useState<string[]>([]);
  const [documents, setDocuments] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ title: string; prompt: string }[] | null>(null);
  const [done, setDone] = useState("");
  const build = useMutation({
    mutationFn: () => api.blob("/api/sops/pack/", { company: companyId, runs, documents }),
    onSuccess: (zip) => {
      const url = URL.createObjectURL(zip);
      const a = document.createElement("a");
      a.href = url;
      a.download = "notebook-pack.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setDone("The pack is downloaded. Open its README to make the notebook.");
    },
  });
  const savePrompts = useMutation({
    mutationFn: () => api.put<{ prompts: PackChoices["prompts"] }>("/api/sops/pack/prompts/",
      { prompts: editing }),
    onSuccess: () => { setEditing(null); qc.invalidateQueries({ queryKey: ["sop-pack", companyId] }); },
  });
  const reset = useMutation({
    mutationFn: () => api.del<{ prompts: PackChoices["prompts"] }>("/api/sops/pack/prompts/"),
    onSuccess: () => { setEditing(null); qc.invalidateQueries({ queryKey: ["sop-pack", companyId] }); },
  });
  const toggle = (list: string[], set: (v: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const c = q.data;
  return (
    <Modal label="Notebook pack" title="Notebook pack" wide onClose={onClose}>
      <p className="small muted" style={{ marginTop: 0 }}>A zip for your own Gemini Notebook: the
        files in reading order, the prompts to paste, and a README on making the notebook and
        bringing its answers back into a brainstorm.</p>
      {q.isError && <Banner kind="bad">{(q.error as Error).message}</Banner>}
      {build.isError && <Banner kind="bad">{errorOf(build.error)}</Banner>}
      {done && <Banner kind="ok">{done}</Banner>}
      {!c ? <p>Loading…</p> : <>
        <p className="small"><strong>Always in it:</strong> {c.always.join(", ")}.</p>
        <p className="small muted">{c.never}</p>
        <fieldset className="sop-pack-pick" aria-label="Tool runs">
          <legend>Tool runs</legend>
          {c.runs.length === 0 ? <p className="small muted">No tool runs.</p> : c.runs.map((r) => (
            <label key={r.id} className="check"><input type="checkbox" checked={runs.includes(r.id)}
              onChange={() => toggle(runs, setRuns, r.id)} /> {r.name} <span className="small muted">({r.tool}, {longDay(r.date)})</span></label>))}
        </fieldset>
        <fieldset className="sop-pack-pick" aria-label="Documents">
          <legend>Documents</legend>
          {c.documents.length === 0 ? <p className="small muted">No documents with a PDF.</p> : c.documents.map((d) => (
            <label key={d.id} className="check"><input type="checkbox" checked={documents.includes(d.id)}
              onChange={() => toggle(documents, setDocuments, d.id)} /> {d.title} <span className="small muted">({d.state})</span></label>))}
        </fieldset>
        <section aria-label="The prompts">
          <h4>The prompts</h4>
          {editing ? (
            <div className="sop-prompts-edit">
              {editing.map((p, i) => (
                <div key={i} className="sop-prompt-row">
                  <input aria-label={`Prompt ${i + 1} title`} value={p.title}
                    onChange={(e) => setEditing(editing.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
                  <textarea aria-label={`Prompt ${i + 1}`} rows={3} value={p.prompt}
                    onChange={(e) => setEditing(editing.map((x, j) => j === i ? { ...x, prompt: e.target.value } : x))} />
                  <button className="ghost small" onClick={() => setEditing(editing.filter((_, j) => j !== i))}>Remove</button>
                </div>))}
              {savePrompts.isError && <Banner kind="bad">{errorOf(savePrompts.error)}</Banner>}
              <div className="row tight">
                <button className="small" onClick={() => setEditing([...editing, { title: "", prompt: "" }])}>Add a prompt</button>
                <button className="small primary" disabled={savePrompts.isPending} onClick={() => savePrompts.mutate()}>Save the prompts</button>
                <button className="small ghost" disabled={reset.isPending} onClick={() => reset.mutate()}>Back to the Command Center's prompts</button>
                <button className="small ghost" onClick={() => setEditing(null)}>Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <ol className="small">{c.prompts.map((p) => <li key={p.title}>{p.title}</li>)}</ol>
              {c.may_edit_prompts && <button className="small" onClick={() => setEditing(c.prompts.map((p) => ({ ...p })))}>Edit the prompts</button>}
            </>
          )}
        </section>
        <div className="row tight">
          <button className="primary" disabled={build.isPending} onClick={() => build.mutate()}>
            {build.isPending ? "Building…" : "Build the pack"}</button>
          <button onClick={onClose}>Close</button>
        </div>
      </>}
    </Modal>
  );
}

// ------------------------------------------------------------------ who has read it

export function ReadsPanel({ sopId, reads, mayRemind, staff }: {
  sopId: string; reads: Reads; mayRemind: boolean; staff: boolean;
}) {
  const [said, setSaid] = useState("");
  const remind = useMutation({
    mutationFn: () => api.post<{ drafted: number; skipped: number }>(`/api/sops/${sopId}/remind/`),
    onSuccess: (r) => setSaid(`${r.drafted} ${r.drafted === 1 ? "reminder" : "reminders"} drafted, waiting in the Sending queue`
      + (r.skipped ? ` (${r.skipped} already had one waiting)` : "") + "."),
  });
  return (
    <section className="card sop-reads" aria-label="Who has read it">
      <div className="sop-reads-count">{reads.read} of {reads.asked} read</div>
      <p className="small muted" style={{ marginTop: 0 }}>Version {reads.number} asked them to read it
        {reads.read_by ? `, by ${longDay(reads.read_by)}` : ""}.</p>
      {reads.outstanding.length > 0 && (
        <p className="small"><strong>Not read yet:</strong> {reads.outstanding.map((o) => o.name).join(", ")}</p>)}
      {reads.readers.length > 0 && (
        <ul className="sop-readers small">
          {reads.readers.map((r) => (
            <li key={r.membership}>{r.name} · {longDay(r.at)} · version {r.version}
              {r.late && <> <Pill kind="warn">late</Pill></>}</li>))}
        </ul>)}
      {remind.isError && <Banner kind="bad">{errorOf(remind.error)}</Banner>}
      {said && <Banner kind="ok">{said}{staff && <> <Link to="/sending-queue">Open the Sending queue</Link></>}</Banner>}
      {mayRemind && reads.outstanding.length > 0 && !said && (
        <button className="small" disabled={remind.isPending} onClick={() => remind.mutate()}>
          Remind the {reads.outstanding.length} who haven't read it</button>)}
    </section>
  );
}

// ------------------------------------------------------------------ the editor

interface Working {
  title: string; purpose: string; applies_when: string; roles: Role[]; steps: Step[];
  sections: Section[]; owner: string; category: string; review_date: string;
  process_map: string; audience: Audience; teams: string[]; people: string[]; kpis: string[];
}

function working(s: SopFull): Working {
  return {
    title: s.title, purpose: s.purpose, applies_when: s.applies_when,
    roles: s.roles.map((r) => ({ ...r })), steps: s.steps.map((x) => ({ ...x, images: [...x.images] })),
    sections: s.sections.map((x) => ({ ...x })), owner: s.owner_id ?? "", category: s.category,
    review_date: s.review_date ?? "", process_map: s.process_map, audience: s.audience,
    teams: [...s.teams], people: [...s.people], kpis: s.kpis.map((k) => k.id),
  };
}

/** The process map's picture, drawn by the server a moment after the text changes. */
export function useMapPreview(text: string, initial: string | null) {
  const [svg, setSvg] = useState<string | null>(initial);
  const [errors, setErrors] = useState<string[]>([]);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return undefined; }
    if (!text.trim()) { setSvg(null); setErrors([]); return undefined; }
    const timer = setTimeout(() => {
      api.post<{ svg: string | null; errors: string[] }>("/api/sops/map/", { text })
        .then((r) => { setSvg(r.svg); setErrors(r.errors); }).catch(() => undefined);
    }, 400);
    return () => clearTimeout(timer);
  }, [text]);
  return { svg, errors };
}

function PublishModal({ sop, dirty, save, onClose }: {
  sop: SopFull; dirty: boolean; save: () => Promise<unknown>; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [minor, setMinor] = useState(false);
  const first = sop.version === 0;
  const go = useMutation({
    mutationFn: async () => {
      if (dirty) await save();
      return api.post<SopFull>(`/api/sops/${sop.id}/publish/`, { change_note: note, minor });
    },
    onSuccess: (s) => { qc.setQueryData(["sop", sop.id], s); qc.invalidateQueries({ queryKey: ["sops"] }); onClose(); },
  });
  return (
    <Modal label="Publish" title={first ? "Publish version 1" : `Publish version ${sop.version + 1}`} onClose={onClose}>
      {go.isError && <Banner kind="bad">{errorOf(go.error)}</Banner>}
      {first ? <p>Everyone in the audience sees it in the portal and is asked to read it and tick
        “Read and understood”.</p> : <>
        <label>What changed<textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder="One line: what is different in this version" /></label>
        <label className="check"><input type="checkbox" checked={minor} onChange={(e) => setMinor(e.target.checked)} />{" "}
          Minor change (doesn't ask people to read again)</label>
      </>}
      {dirty && <p className="small muted">Your unsaved changes are saved first.</p>}
      <div className="row tight">
        <button className="primary" disabled={go.isPending || (!first && !note.trim())}
          onClick={() => go.mutate()}>{dirty ? "Save and publish" : "Publish"}</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function SopEditor() {
  const { id = "" } = useParams();
  const q = useQuery<SopFull>({ queryKey: ["sop", id], queryFn: () => api.get<SopFull>(`/api/sops/${id}/`) });
  if (q.isError) return <Banner kind="bad">That SOP is not available to you.</Banner>;
  if (!q.data) return <p>Loading…</p>;
  return <Editor key={q.data.id} sop={q.data} />;
}

function Editor({ sop }: { sop: SopFull }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [w, setW] = useState<Working>(() => working(sop));
  const [attachments, setAttachments] = useState<Attachment[]>(sop.attachments);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const dirty = JSON.stringify(w) !== JSON.stringify(working(sop));
  const preview = useMapPreview(w.process_map, sop.map_svg);
  const editable = !!sop.may.edit;
  const set = <K extends keyof Working>(key: K, value: Working[K]) => { setW({ ...w, [key]: value }); setSaved(""); };
  const byId = useMemo(() => new Map(attachments.map((a) => [a.id, a])), [attachments]);

  const save = useMutation({
    mutationFn: () => api.patch<SopFull>(`/api/sops/${sop.id}/`, {
      title: w.title, purpose: w.purpose, applies_when: w.applies_when, roles: w.roles,
      steps: w.steps, sections: w.sections, owner: w.owner || null, category: w.category,
      review_date: w.review_date || null, process_map: w.process_map, audience: w.audience,
      teams: w.teams, people: w.people, kpis: w.kpis }),
    onSuccess: (s) => {
      setError(""); setSaved("Saved."); setW(working(s)); setAttachments(s.attachments);
      qc.setQueryData(["sop", sop.id], s); qc.invalidateQueries({ queryKey: ["sops"] });
    },
    onError: (e) => setError(errorOf(e)),
  });
  const act = useMutation({
    mutationFn: (action: string) => api.post<SopFull>(`/api/sops/${sop.id}/${action}/`),
    onSuccess: (s) => { qc.setQueryData(["sop", sop.id], s); qc.invalidateQueries({ queryKey: ["sops"] }); },
    onError: (e) => setError(errorOf(e)),
  });
  const resolve = useMutation({
    mutationFn: (cid: string) => api.post<SopFull>(`/api/sops/${sop.id}/comments/${cid}/resolve/`),
    onSuccess: (s) => qc.setQueryData(["sop", sop.id], s),
  });
  const brainstorm = useMutation({
    mutationFn: () => api.post<Brainstorm>("/api/sops/brainstorms/", { sop: sop.id }),
    onSuccess: (b) => navigate(`/sop-brainstorms/${b.id}`),
    onError: (e) => setError(errorOf(e)),
  });
  const fromSteps = useMutation({
    mutationFn: () => api.post<{ text: string }>("/api/sops/map/", { steps: w.steps }),
    onSuccess: (r) => set("process_map", r.text),
  });

  async function upload(file: File): Promise<Attachment | null> {
    const form = new FormData();
    form.append("file", file);
    try {
      const a = await api.post<Attachment>(`/api/sops/${sop.id}/attachments/`, form);
      setAttachments((list) => [...list, a]);
      return a;
    } catch (e) { setError(errorOf(e)); return null; }
  }
  async function removeAttachment(aid: string) {
    try {
      await api.del(`/api/sops/${sop.id}/attachments/${aid}/`);
      setAttachments((list) => list.filter((a) => a.id !== aid));
      setW({ ...w, steps: w.steps.map((s) => ({ ...s, images: s.images.filter((i) => i !== aid) })) });
    } catch (e) { setError(errorOf(e)); }
  }

  const step = (i: number, patch: Partial<Step>) =>
    set("steps", w.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, by: number) => {
    const next = [...w.steps];
    const [row] = next.splice(i, 1);
    next.splice(i + by, 0, row);
    set("steps", next);
  };
  const roleNames = w.roles.map((r) => r.name).filter(Boolean);
  const c = sop.choices;
  const pdfs = attachments.filter((a) => a.kind === "pdf");

  return (
    <div className="sop-page sop-editor">
      <PageHead title={sop.title}
        crumbs={[{ to: "/sops", label: "SOPs" }, ...(sop.company.is_practice ? []
          : [{ to: `/companies/${sop.company.id}`, label: sop.company.name }])]}
        sub={<span><StatusTag status={sop.status} />{" "}
          {sop.version > 0 ? `Version ${sop.version}` : "Not published yet"} · {companyName(sop.company)}
          {sop.from_ai_app && <> · <Pill kind="info">Drafted by an AI app</Pill></>}</span>}
        action={<div className="row tight sop-actions">
          {editable && <button className="primary" disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save"}</button>}
          {sop.may.publish && <button onClick={() => setPublishing(true)}>Publish</button>}
        </div>} />
      {error && <Banner kind="bad">{error}</Banner>}
      {saved && !dirty && <Banner kind="ok">{saved}</Banner>}
      {sop.status === "archived" && <Banner kind="warn">Archived: nobody sees it in the portal.</Banner>}
      {sop.version > 0 && sop.unpublished_changes && sop.status !== "archived" && (
        <Banner kind="warn">Changes not published yet. The portal shows version {sop.version} until
          you publish again.</Banner>)}
      <div className="row tight sop-tools">
        <a className="btn small" href={`/api/sops/${sop.id}/files/pdf/`}>PDF</a>
        <a className="btn small" href={`/api/sops/${sop.id}/files/docx/`}>Word</a>
        <button className="small" disabled={brainstorm.isPending} onClick={() => brainstorm.mutate()}>
          Brainstorm with Claude</button>
        {sop.brainstorms.map((b) => <Link key={b.id} className="btn small ghost" to={`/sop-brainstorms/${b.id}`}>
          Open the brainstorm: {b.title}</Link>)}
        {sop.may.publishes && (sop.status === "archived"
          ? <button className="small ghost" onClick={() => act.mutate("restore")}>Restore</button>
          : <button className="small ghost" onClick={() => act.mutate("archive")}>Archive</button>)}
      </div>

      {sop.reads && sop.version > 0 && (
        <ReadsPanel sopId={sop.id} reads={sop.reads} mayRemind={sop.may.reminds && sop.status === "published"} staff />)}

      <fieldset className="sop-fields" disabled={!editable}>
        <Card title="The SOP">
          <label>Title<input value={w.title} onChange={(e) => set("title", e.target.value)} /></label>
          <label>Purpose<textarea rows={3} value={w.purpose} placeholder={sop.hints.purpose ?? ""}
            onChange={(e) => set("purpose", e.target.value)} /></label>
          <label>When it applies<textarea rows={2} value={w.applies_when} placeholder={sop.hints.applies_when ?? "What starts it, and where it ends."}
            onChange={(e) => set("applies_when", e.target.value)} /></label>
          <div className="sop-grid">
            <label>Owner<select value={w.owner} onChange={(e) => set("owner", e.target.value)}>
              <option value="">Nobody yet</option>
              {(c?.owners ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}{o.side === "client" ? "" : " (practice)"}</option>)}
            </select></label>
            <label>Category<input value={w.category} onChange={(e) => set("category", e.target.value)}
              placeholder="Shipping, Safety, Hiring…" /></label>
            <label>Review by<input type="date" value={w.review_date} onChange={(e) => set("review_date", e.target.value)} /></label>
          </div>
          {sop.hints.review_date && <p className="small muted">{sop.hints.review_date}</p>}
        </Card>

        <Card title="Roles">
          {sop.hints.roles && w.roles.length === 0 && <p className="small muted">{sop.hints.roles}</p>}
          {w.roles.map((r, i) => (
            <div key={i} className="sop-role-row">
              <input aria-label={`Role ${i + 1} name`} placeholder="Role" value={r.name}
                onChange={(e) => set("roles", w.roles.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <input aria-label={`What role ${i + 1} does`} placeholder="What they do" value={r.does}
                onChange={(e) => set("roles", w.roles.map((x, j) => j === i ? { ...x, does: e.target.value } : x))} />
              <button className="ghost small" aria-label={`Remove role ${i + 1}`}
                onClick={() => set("roles", w.roles.filter((_, j) => j !== i))}>Remove</button>
            </div>))}
          <button className="small" onClick={() => set("roles", [...w.roles, { name: "", does: "" }])}>Add a role</button>
        </Card>

        <Card title="Steps">
          {sop.hints.steps && w.steps.length === 0 && <p className="small muted">{sop.hints.steps}</p>}
          <ol className="sop-steps-edit">
            {w.steps.map((s, i) => (
              <li key={i} className="sop-step-edit">
                <textarea aria-label={`Step ${i + 1}`} rows={2} value={s.text}
                  onChange={(e) => step(i, { text: e.target.value })} />
                <div className="sop-step-meta">
                  <input aria-label={`Who does step ${i + 1}`} list={`sop-roles-${sop.id}`} placeholder="Who does it"
                    value={s.role} onChange={(e) => step(i, { role: e.target.value })} />
                  <input aria-label={`Warning for step ${i + 1}`} placeholder="A warning (optional)"
                    value={s.warning} onChange={(e) => step(i, { warning: e.target.value })} />
                </div>
                {s.images.length > 0 && (
                  <div className="sop-thumbs">
                    {s.images.map((img) => byId.get(img) && (
                      <span key={img} className="sop-thumb">
                        <img src={byId.get(img)!.url} alt={byId.get(img)!.name} />
                        <button className="ghost small" aria-label={`Take the picture off step ${i + 1}`}
                          onClick={() => step(i, { images: s.images.filter((x) => x !== img) })}>×</button>
                      </span>))}
                  </div>)}
                <div className="row tight">
                  <label className="btn small ghost sop-file">Add a picture
                    <input type="file" accept="image/png,image/jpeg,image/gif,image/webp"
                      aria-label={`Add a picture to step ${i + 1}`}
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        const a = await upload(file);
                        if (a) step(i, { images: [...s.images, a.id] });
                      }} /></label>
                  <button className="ghost small" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                  <button className="ghost small" aria-label={`Move step ${i + 1} down`} disabled={i === w.steps.length - 1} onClick={() => move(i, 1)}>↓</button>
                  <button className="ghost small" aria-label={`Remove step ${i + 1}`}
                    onClick={() => set("steps", w.steps.filter((_, j) => j !== i))}>Remove</button>
                </div>
              </li>))}
          </ol>
          <datalist id={`sop-roles-${sop.id}`}>{roleNames.map((n) => <option key={n} value={n} />)}</datalist>
          <button className="small" onClick={() => set("steps", [...w.steps, { text: "", role: "", warning: "", images: [] }])}>Add a step</button>
        </Card>

        <Card title="Process map">
          <p className="small muted" style={{ marginTop: 0 }}>A flowchart as text: a step is
            <code> id[text]</code>, a decision <code>id{"{text?}"}</code>, a start or end
            <code> id([text])</code>, an arrow <code>a --&gt; b</code> or <code>a --&gt;|Yes| b</code>.</p>
          <div className="sop-map-edit">
            <textarea aria-label="Process map text" rows={10} className="mono" value={w.process_map}
              onChange={(e) => set("process_map", e.target.value)} placeholder="flowchart TD" />
            <div className="sop-map" aria-label="Process map preview">
              {preview.errors.length > 0 ? <Banner kind="bad">{preview.errors.join(" ")}</Banner>
                : preview.svg ? <img src={svgSrc(preview.svg)} alt="Process map" />
                : <p className="small muted">No map yet.</p>}
            </div>
          </div>
          <button className="small" disabled={w.steps.length === 0 || fromSteps.isPending}
            onClick={() => fromSteps.mutate()}>Start from the steps</button>
        </Card>

        <Card title="Measures">
          <p className="small muted" style={{ marginTop: 0 }}>{sop.hints.kpis || "The company KPIs this SOP should move."}</p>
          {(c?.kpis ?? []).length === 0 ? <p className="small muted">This company has no KPIs yet.</p> : (
            <div className="sop-checks">
              {(c?.kpis ?? []).map((k) => (
                <label key={k.id} className="check"><input type="checkbox" checked={w.kpis.includes(k.id)}
                  onChange={() => set("kpis", w.kpis.includes(k.id) ? w.kpis.filter((x) => x !== k.id) : [...w.kpis, k.id])} /> {k.name}</label>))}
            </div>)}
        </Card>

        <Card title="Who it is published to">
          <div className="sop-audience" role="radiogroup" aria-label="Audience">
            {([["company", "The whole company"], ["teams", "Chosen teams"], ["people", "Named people"]] as [Audience, string][]).map(([key, label]) => (
              <label key={key} className="check"><input type="radio" name={`audience-${sop.id}`} checked={w.audience === key}
                onChange={() => set("audience", key)} /> {label}</label>))}
          </div>
          {w.audience === "teams" && (
            <div className="sop-checks">{(c?.teams ?? []).length === 0 ? <p className="small muted">This company has no teams yet.</p>
              : (c?.teams ?? []).map((t) => (
                <label key={t.id} className="check"><input type="checkbox" checked={w.teams.includes(t.id)}
                  onChange={() => set("teams", w.teams.includes(t.id) ? w.teams.filter((x) => x !== t.id) : [...w.teams, t.id])} /> {t.name}</label>))}</div>)}
          {w.audience === "people" && (
            <div className="sop-checks">{(c?.people ?? []).length === 0 ? <p className="small muted">Nobody at this company has the portal yet.</p>
              : (c?.people ?? []).map((p) => (
                <label key={p.id} className="check"><input type="checkbox" checked={w.people.includes(p.id)}
                  onChange={() => set("people", w.people.includes(p.id) ? w.people.filter((x) => x !== p.id) : [...w.people, p.id])} /> {p.name}</label>))}</div>)}
        </Card>

        {w.sections.length > 0 && (
          <Card title="More sections">
            {w.sections.map((s, i) => (
              <label key={i}>{s.title}<textarea rows={3} aria-label={s.title} value={s.body}
                onChange={(e) => set("sections", w.sections.map((x, j) => j === i ? { ...x, body: e.target.value } : x))} /></label>))}
          </Card>)}

        <Card title="Attachments">
          {pdfs.length === 0 ? <p className="small muted">No PDFs attached.</p> : (
            <ul className="sop-rows">{pdfs.map((a) => (
              <li key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.name}</a>{" "}
                <button className="ghost small" aria-label={`Remove ${a.name}`} onClick={() => removeAttachment(a.id)}>Remove</button></li>))}</ul>)}
          <label className="btn small ghost sop-file">Attach a PDF
            <input type="file" accept="application/pdf" aria-label="Attach a PDF"
              onChange={async (e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) await upload(f); }} /></label>
        </Card>
      </fieldset>

      {editable && dirty && (
        <div className="sop-savebar">
          <span className="small">Unsaved changes.</span>
          <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button>
        </div>)}

      {sop.comments.length > 0 && (
        <Card title="Suggested changes">
          <ul className="sop-comments">
            {sop.comments.map((cm) => (
              <li key={cm.id} className={cm.resolved ? "muted" : ""}>
                <strong>{cm.by}</strong> <span className="small muted">({longDay(cm.at)}, on version {cm.version})</span>
                <div>{cm.text}</div>
                {cm.resolved ? <Pill>Resolved</Pill> : sop.may.drafts && (
                  <button className="small ghost" onClick={() => resolve.mutate(cm.id)}>Resolve</button>)}
              </li>))}
          </ul>
        </Card>)}

      {sop.versions.length > 0 && (
        <Card title="Versions">
          <ul className="sop-versions">
            {sop.versions.map((v) => (
              <li key={v.number}>
                <strong>Version {v.number}</strong> · {longDay(v.published_at)}{v.published_by && ` · ${v.published_by}`}
                {v.minor && <> <Pill>Minor change</Pill></>}
                <div className="small">{v.change_note}</div>
                <a className="small" href={`/api/sops/${sop.id}/files/pdf/?version=${v.number}`}>PDF of version {v.number}</a>
              </li>))}
          </ul>
        </Card>)}

      {publishing && <PublishModal sop={sop} dirty={dirty} save={() => save.mutateAsync()}
        onClose={() => setPublishing(false)} />}
    </div>
  );
}

// ------------------------------------------------------------------ the portal's reader

function Block({ title, children }: { title: string; children: ReactNode }) {
  return <section className="sop-block" aria-label={title}><h3>{title}</h3>{children}</section>;
}

function SopReader() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const q = useQuery<SopPortal>({ queryKey: ["sop", id], queryFn: () => api.get<SopPortal>(`/api/sops/${id}/`) });
  const [suggestion, setSuggestion] = useState("");
  const [thanked, setThanked] = useState(false);
  const ack = useMutation({
    mutationFn: () => api.post<{ sop: SopPortal }>(`/api/sops/${id}/ack/`),
    onSuccess: (r) => { qc.setQueryData(["sop", id], r.sop); qc.invalidateQueries({ queryKey: ["sops"] }); },
  });
  const suggest = useMutation({
    mutationFn: () => api.post(`/api/sops/${id}/suggest/`, { text: suggestion }),
    onSuccess: () => { setSuggestion(""); setThanked(true); },
  });
  if (q.isError) return <Banner kind="bad">That SOP is not available to you.</Banner>;
  const s = q.data;
  if (!s) return <p>Loading…</p>;
  const reread = s.asked && !s.read && s.read_version !== null && s.read_version < s.version;
  return (
    <article className="sop-page sop-reader">
      <PageHead title={s.title} crumbs={[{ to: "/sops", label: "SOPs" }]}
        sub={`Version ${s.version} · published ${longDay(s.published_at)}`} />
      {s.version > 1 && s.change_note && <p className="sop-changed"><strong>What changed:</strong> {s.change_note}</p>}
      {reread && <Banner kind="warn">Version {s.version} changed how this is done. Please read it again.</Banner>}
      <div className="row tight sop-tools">
        <a className="btn small" href={`/api/sops/${s.id}/files/pdf/`}>PDF</a>
        {s.owner && <span className="small muted">Owner: {s.owner}</span>}
        {s.review_date && <span className="small muted">Review by {longDay(s.review_date)}</span>}
      </div>
      {s.purpose && <Block title="Purpose"><p>{s.purpose}</p></Block>}
      {s.applies_when && <Block title="When it applies"><p>{s.applies_when}</p></Block>}
      {s.roles.length > 0 && (
        <Block title="Roles">
          <ul className="sop-roles">{s.roles.map((r) => <li key={r.name}><strong>{r.name}</strong>{r.does && <> — {r.does}</>}</li>)}</ul>
        </Block>)}
      {s.map_svg && (
        <Block title="Process map">
          <div className="sop-map"><img src={svgSrc(s.map_svg)} alt={`Process map of ${s.title}`} /></div>
        </Block>)}
      <Block title="Steps">
        <ol className="sop-steps">
          {s.steps.map((st, i) => (
            <li key={i}>
              <div>{st.text}</div>
              {st.role && <div className="small muted">{st.role}</div>}
              {st.warning && <div className="sop-warn" role="note">{st.warning}</div>}
              {st.images.length > 0 && (
                <div className="sop-step-images">
                  {st.images.map((img) => {
                    const a = s.attachments.find((x) => x.id === img);
                    return a ? <img key={img} src={a.url} alt={a.name} /> : null;
                  })}
                </div>)}
            </li>))}
        </ol>
      </Block>
      {s.kpis.length > 0 && (
        <Block title="The numbers it should move">
          <ul>{s.kpis.map((k) => <li key={k.id}>{k.name}</li>)}</ul>
        </Block>)}
      {s.sections.filter((x) => x.body).map((x) => (
        <Block key={x.title} title={x.title}><p>{x.body}</p></Block>))}
      {s.attachments.filter((a) => a.kind === "pdf").length > 0 && (
        <Block title="Attached">
          <ul>{s.attachments.filter((a) => a.kind === "pdf").map((a) => (
            <li key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.name}</a></li>))}</ul>
        </Block>)}

      <section className="card sop-ack" aria-label="Read and understood">
        {ack.isError && <Banner kind="bad">{errorOf(ack.error)}</Banner>}
        {s.read ? (
          <p className="sop-ack-done">✓ Read and understood on {longDay(s.read_at)}, version {s.read_version}.</p>
        ) : s.asked ? (
          <>
            <p style={{ marginTop: 0 }}>When you have read it all, tick it here.
              {s.read_by && <span className="small muted"> Please by {longDay(s.read_by)}.</span>}</p>
            <button className="primary sop-ack-button" disabled={ack.isPending} onClick={() => ack.mutate()}>
              Read and understood</button>
          </>
        ) : <p className="small muted" style={{ margin: 0 }}>You can read it; it isn't published to you to tick.</p>}
      </section>

      <section className="card" aria-label="Suggest a change">
        <h3 style={{ marginTop: 0 }}>Suggest a change</h3>
        {thanked ? <p>Thanks. The practice sees your suggestion with this SOP.</p> : <>
          <textarea aria-label="Suggest a change" rows={3} value={suggestion}
            placeholder="What doesn't match how the work is really done?"
            onChange={(e) => setSuggestion(e.target.value)} />
          {suggest.isError && <Banner kind="bad">{errorOf(suggest.error)}</Banner>}
          <button className="small" disabled={suggestion.trim().length < 3 || suggest.isPending}
            onClick={() => suggest.mutate()}>Send the suggestion</button>
        </>}
      </section>

      {s.may.sees_reads && s.reads && (
        <ReadsPanel sopId={s.id} reads={s.reads} mayRemind={s.may.reminds} staff={false} />)}
    </article>
  );
}
