/**
 * Brainstorm mode (P10): a saved conversation with Claude about one process,
 * with its sources, the price before every send, and what Claude proposes
 * waiting for a person to accept, edit or discard.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Modal, PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { api } from "../lib/api";
import { about } from "../lib/plans";
import { Brainstorm, DraftPayload, Price, Proposal, ProposalKind, svgSrc } from "../lib/sops";
import { useMapPreview } from "./Sops";

const ACTIONS: { kind: ProposalKind; label: string }[] = [
  { kind: "draft", label: "Draft the SOP" }, { kind: "map", label: "Draw the process map" },
  { kind: "checklist", label: "Make the checklist" }, { kind: "measures", label: "Suggest measures" },
];

function errorOf(e: unknown) { return (e as Error)?.message ?? "Something went wrong."; }

function money(v: string | null | undefined) { return `$${Number(v ?? 0).toFixed(2)}`; }

export function SopBrainstormScreen() {
  const { id = "" } = useParams();
  const q = useQuery<Brainstorm>({ queryKey: ["sop-brainstorm", id],
    queryFn: () => api.get<Brainstorm>(`/api/sops/brainstorms/${id}/`) });
  if (q.isError) return <Banner kind="bad">That brainstorm is not available to you.</Banner>;
  if (!q.data) return <p>Loading…</p>;
  return <BrainstormPage b={q.data} />;
}

function usePrice(b: Brainstorm, kind: string, message = "") {
  const [price, setPrice] = useState<Price | null>(kind === "chat" && !message ? b.price : null);
  const key = `${b.id}|${b.updated_at}|${b.sources.length}|${b.tier}|${kind}|${message}`;
  useEffect(() => {
    const timer = setTimeout(() => {
      api.post<Price>(`/api/sops/brainstorms/${b.id}/price/`, { kind, message })
        .then(setPrice).catch(() => undefined);
    }, message ? 500 : 0);
    return () => clearTimeout(timer);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return price;
}

function BrainstormPage({ b }: { b: Brainstorm }) {
  const qc = useQueryClient();
  const set = (next: Brainstorm) => qc.setQueryData(["sop-brainstorm", b.id], next);
  const [title, setTitle] = useState(b.title);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const chat = usePrice(b, "chat", message);
  const patch = useMutation({
    mutationFn: (data: object) => api.patch<Brainstorm>(`/api/sops/brainstorms/${b.id}/`, data),
    onSuccess: set, onError: (e) => setError(errorOf(e)),
  });
  const send = useMutation({
    mutationFn: () => api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/send/`, { text: message }),
    onSuccess: (next) => { setMessage(""); setError(""); set(next); },
    onError: (e) => setError(errorOf(e)),
  });
  const waiting = b.proposals.filter((p) => p.state === "proposed");
  const decided = b.proposals.filter((p) => p.state !== "proposed");
  return (
    <div className="sop-page sop-brainstorm">
      <PageHead title={b.title}
        crumbs={[{ to: "/sops", label: "SOPs" }, ...(b.company.is_practice ? []
          : [{ to: `/companies/${b.company.id}`, label: b.company.name }])]}
        sub={<span>A brainstorm with Claude for {b.company.is_practice ? "our practice" : b.company.name}
          {b.sop && <> · The SOP: <Link to={`/sops/${b.sop.id}`}>{b.sop.title}</Link></>}</span>} />
      <div className="sop-brainstorm-bar">
        <label className="sop-title-edit">Title<input aria-label="Brainstorm title" value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim() && title !== b.title && patch.mutate({ title })} /></label>
        <div className="sop-tier" role="radiogroup" aria-label="Model">
          {(["standard", "deep"] as const).map((t) => (
            <label key={t} className="check"><input type="radio" name={`tier-${b.id}`} checked={b.tier === t}
              onChange={() => patch.mutate({ tier: t })} /> {t === "standard" ? "Standard" : "Deep"}</label>))}
        </div>
        <span className="sop-spent" aria-label="Spent so far">Spent so far {money(b.spent_usd)}</span>
      </div>
      {b.refused && <Banner kind="warn">{b.refused}</Banner>}
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="sop-brainstorm-cols">
        <div className="sop-brainstorm-main">
          <section className="card" aria-label="Conversation">
            <h3 style={{ marginTop: 0 }}>Conversation</h3>
            {b.messages.length === 0 ? <Empty>Say what the process is, who does it, and where it
              goes wrong. Add sources on the right: pasted text, screenshots, PDFs, a recording.</Empty> : (
              <ol className="sop-messages">
                {b.messages.map((m) => (
                  <li key={m.id} className={m.role === "claude" ? "sop-msg claude" : "sop-msg person"}>
                    <div className="small muted">{m.role === "claude" ? "Claude" : m.by || "You"}
                      {m.cost_usd && <> · {money(m.cost_usd)}</>}</div>
                    <div className="sop-msg-text">{m.text}</div>
                  </li>))}
              </ol>)}
            <textarea aria-label="Your message" rows={3} value={message}
              placeholder="Describe the process, or ask Claude something about it"
              onChange={(e) => setMessage(e.target.value)} />
            <button className="primary" disabled={!message.trim() || send.isPending || !!b.refused}
              onClick={() => send.mutate()}>
              {send.isPending ? "Asking Claude…" : `Send (${about(chat?.estimate_usd)})`}</button>
          </section>
          <Actions b={b} onDone={set} onError={setError} />
          {waiting.length > 0 && (
            <section aria-label="Waiting for you" className="sop-proposals">
              <h3>Waiting for you</h3>
              {waiting.map((p) => <ProposalCard key={p.id} b={b} p={p} onDone={set} />)}
            </section>)}
          {decided.length > 0 && (
            <Card title="Decided">
              <ul className="sop-rows">
                {decided.map((p) => (
                  <li key={p.id}>{p.label}: <Pill kind={p.state === "accepted" ? "ok" : ""}>
                    {p.state === "accepted" ? "Accepted" : "Discarded"}</Pill>
                    {p.decided_by && <span className="small muted"> by {p.decided_by}</span>}</li>))}
              </ul>
            </Card>)}
        </div>
        <Sources b={b} onDone={set} />
      </div>
    </div>
  );
}

function Actions({ b, onDone, onError }: { b: Brainstorm; onDone: (b: Brainstorm) => void;
  onError: (s: string) => void }) {
  const prices = {
    draft: usePrice(b, "draft"), map: usePrice(b, "map"),
    checklist: usePrice(b, "checklist"), measures: usePrice(b, "measures"),
  };
  const act = useMutation({
    mutationFn: (kind: ProposalKind) => api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/act/${kind}/`),
    onSuccess: (next) => { onError(""); onDone(next); },
    onError: (e) => onError(errorOf(e)),
  });
  return (
    <section className="card" aria-label="Ask Claude to">
      <h3 style={{ marginTop: 0 }}>Ask Claude to</h3>
      <div className="row tight sop-act-buttons">
        {ACTIONS.map((a) => (
          <button key={a.kind} disabled={act.isPending || !!b.refused || !prices[a.kind]}
            onClick={() => act.mutate(a.kind)}>
            {act.isPending && act.variables === a.kind ? "Asking Claude…"
              : `${a.label} (${prices[a.kind] ? about(prices[a.kind]!.estimate_usd) : "…"})`}</button>))}
      </div>
      <p className="small muted">Nothing changes until you accept it. Each price is shown before
        anything is spent, on the {b.tier === "deep" ? "Deep" : "Standard"} model.</p>
    </section>
  );
}

// ------------------------------------------------------------------ proposals

function DraftBody({ p, edit, setEdit, editing }: {
  p: Proposal; edit: DraftPayload; setEdit: (d: DraftPayload) => void; editing: boolean;
}) {
  const payload = p.payload as unknown as DraftPayload;
  const fields = p.diff?.fields ?? {};
  const steps = p.diff?.steps ?? [];
  const hasDiff = Object.keys(fields).length > 0 || steps.length > 0;
  if (editing) {
    return (
      <div className="sop-draft-edit">
        <label>Title<input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></label>
        <label>Purpose<textarea rows={3} value={edit.purpose} onChange={(e) => setEdit({ ...edit, purpose: e.target.value })} /></label>
        <label>When it applies<textarea rows={2} value={edit.applies_when} onChange={(e) => setEdit({ ...edit, applies_when: e.target.value })} /></label>
        <ol>
          {edit.steps.map((s, i) => (
            <li key={i}><textarea aria-label={`Proposed step ${i + 1}`} rows={2} value={s.text}
              onChange={(e) => setEdit({ ...edit, steps: edit.steps.map((x, j) => j === i ? { ...x, text: e.target.value } : x) })} />
              <button className="ghost small" onClick={() => setEdit({ ...edit, steps: edit.steps.filter((_, j) => j !== i) })}>Remove</button></li>))}
        </ol>
      </div>
    );
  }
  if (hasDiff) {
    return (
      <div className="sop-diff" aria-label="What would change">
        {Object.entries(fields).map(([key, change]) => (
          <div key={key} className="sop-diff-field">
            <div className="small muted">{key.replace("_", " ")}</div>
            {change.from && <div className="sop-del">− {change.from}</div>}
            <div className="sop-add">+ {change.to}</div>
          </div>))}
        {steps.length > 0 && <ol className="sop-diff-steps">
          {steps.map((s, i) => (
            <li key={i} className={s.change === "added" ? "sop-add" : s.change === "removed" ? "sop-del" : ""}>
              {s.change === "added" ? "+ " : s.change === "removed" ? "− " : ""}{s.text}</li>))}
        </ol>}
      </div>
    );
  }
  return (
    <div className="sop-draft-view">
      <p><strong>{payload.title}</strong></p>
      {payload.purpose && <p><span className="small muted">Purpose:</span> {payload.purpose}</p>}
      {payload.applies_when && <p><span className="small muted">When it applies:</span> {payload.applies_when}</p>}
      {payload.roles?.length > 0 && <p><span className="small muted">Roles:</span> {payload.roles.map((r) => r.name).join(", ")}</p>}
      <ol>{payload.steps.map((s, i) => <li key={i}>{s.text}{s.role && <span className="small muted"> ({s.role})</span>}
        {s.warning && <div className="sop-warn">{s.warning}</div>}</li>)}</ol>
    </div>
  );
}

function MapBody({ text, setText }: { text: string; setText: (t: string) => void }) {
  const preview = useMapPreview(text, null);
  const [first, setFirst] = useState<string | null>(null);
  useEffect(() => {
    api.post<{ svg: string | null }>("/api/sops/map/", { text }).then((r) => setFirst(r.svg)).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const svg = preview.svg ?? first;
  return (
    <div className="sop-map-edit">
      <textarea aria-label="Map text" rows={8} className="mono" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="sop-map" aria-label="Proposed map">
        {preview.errors.length > 0 ? <Banner kind="bad">{preview.errors.join(" ")}</Banner>
          : svg ? <img src={svgSrc(svg)} alt="Proposed process map" /> : <p className="small muted">Drawing…</p>}
      </div>
    </div>
  );
}

function ProposalCard({ b, p, onDone }: { b: Brainstorm; p: Proposal; onDone: (b: Brainstorm) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DraftPayload>(() => ({ ...(p.payload as unknown as DraftPayload) }));
  const [map, setMap] = useState(String(p.payload.map ?? ""));
  const tasks = (p.payload.tasks as { title: string; due_in_days: number | null }[] | undefined) ?? [];
  const kpis = (p.payload.kpis as { ref: string; name: string; where: string; why: string }[] | undefined) ?? [];
  const [chosen, setChosen] = useState<number[]>(() =>
    (p.kind === "checklist" ? tasks : kpis).map((_, i) => i));
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [home, setHome] = useState("");
  const decide = useMutation({
    mutationFn: ({ decision, edits }: { decision: "accept" | "discard"; edits?: object }) =>
      api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/proposals/${p.id}/${decision}/`, { edits }),
    onSuccess: onDone,
  });
  const toggle = (i: number) => setChosen(chosen.includes(i) ? chosen.filter((x) => x !== i) : [...chosen, i]);
  function accept() {
    let edits: object | undefined;
    if (p.kind === "draft" && editing) edits = draft;
    if (p.kind === "map") edits = { map };
    if (p.kind === "checklist") {
      const [kind, ident] = home.split(":");
      edits = { chosen, titles, [kind]: ident };
    }
    if (p.kind === "measures") edits = { chosen };
    decide.mutate({ decision: "accept", edits });
  }
  return (
    <section className="card sop-proposal" aria-label={`${p.label} proposed`}>
      <div className="spread"><h4 style={{ margin: 0 }}>{p.label}</h4>
        {p.cost_usd && <span className="small muted">{money(p.cost_usd)}</span>}</div>
      {p.why && <p className="small muted">{p.why}</p>}
      {decide.isError && <Banner kind="bad">{errorOf(decide.error)}</Banner>}
      {p.kind === "draft" && <DraftBody p={p} edit={draft} setEdit={setDraft} editing={editing} />}
      {p.kind === "map" && <MapBody text={map} setText={setMap} />}
      {p.kind === "checklist" && (
        <div className="sop-checklist">
          <ul className="sop-checks">
            {tasks.map((t, i) => (
              <li key={i}><input type="checkbox" aria-label={`Make: ${t.title}`} checked={chosen.includes(i)}
                onChange={() => toggle(i)} />{" "}
                <input aria-label={`Task ${i + 1} title`} value={titles[String(i)] ?? t.title}
                  onChange={(e) => setTitles({ ...titles, [String(i)]: e.target.value })} />
                {t.due_in_days ? <span className="small muted"> due in {t.due_in_days} days</span> : null}</li>))}
          </ul>
          <label>Under<select aria-label="Under which goal or project" value={home} onChange={(e) => setHome(e.target.value)}>
            <option value="">Choose a goal or project</option>
            {b.homes.goals.length > 0 && <optgroup label="Goals">
              {b.homes.goals.map((g) => <option key={g.id} value={`goal:${g.id}`}>{g.name}</option>)}</optgroup>}
            {b.homes.projects.length > 0 && <optgroup label="Projects">
              {b.homes.projects.map((pr) => <option key={pr.id} value={`project:${pr.id}`}>{pr.name}</option>)}</optgroup>}
          </select></label>
        </div>)}
      {p.kind === "measures" && (
        <ul className="sop-checks">
          {kpis.map((k, i) => (
            <li key={k.ref}><label className="check"><input type="checkbox" checked={chosen.includes(i)}
              onChange={() => toggle(i)} /> <strong>{k.name}</strong> <span className="small muted">({k.where})</span></label>
              {k.why && <div className="small">{k.why}</div>}</li>))}
        </ul>)}
      <div className="row tight">
        <button className="primary" disabled={decide.isPending || (p.kind === "checklist" && (!home || !chosen.length))
          || (p.kind === "measures" && !chosen.length)} onClick={accept}>Accept</button>
        {p.kind === "draft" && <button onClick={() => setEditing(!editing)}>{editing ? "Back to the proposal" : "Edit"}</button>}
        <button className="ghost" disabled={decide.isPending} onClick={() => decide.mutate({ decision: "discard" })}>Discard</button>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ sources

function mediaSeconds(file: File): Promise<number> {
  return new Promise((resolve) => {
    const tag = document.createElement(file.type.startsWith("video/") ? "video" : "audio");
    const url = URL.createObjectURL(file);
    const done = (n: number) => { URL.revokeObjectURL(url); resolve(n); };
    tag.preload = "metadata";
    tag.onloadedmetadata = () => done(Number.isFinite(tag.duration) ? Math.round(tag.duration) : 0);
    tag.onerror = () => done(0);
    tag.src = url;
  });
}

function Sources({ b, onDone }: { b: Brainstorm; onDone: (b: Brainstorm) => void }) {
  const [pasting, setPasting] = useState<{ title: string; text: string } | null>(null);
  const [media, setMedia] = useState(false);
  const [error, setError] = useState("");
  const add = useMutation({
    mutationFn: (body: object | FormData) => api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/sources/`, body),
    onSuccess: (next) => { setError(""); setPasting(null); onDone(next); },
    onError: (e) => setError(errorOf(e)),
  });
  const remove = useMutation({
    mutationFn: (sid: string) => api.del(`/api/sops/brainstorms/${b.id}/sources/${sid}/`),
    onSuccess: () => api.get<Brainstorm>(`/api/sops/brainstorms/${b.id}/`).then(onDone),
  });
  const reading = b.sources.filter((s) => s.state === "reading").map((s) => s.id);
  const readingKey = reading.join(",");
  const latest = useRef(onDone);
  latest.current = onDone;
  useEffect(() => {
    if (!reading.length) return undefined;
    const timer = setInterval(() => {
      for (const sid of reading) {
        api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/sources/${sid}/read/`)
          .then((next) => latest.current(next)).catch(() => undefined);
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [readingKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <aside className="sop-brainstorm-side">
      <section className="card" aria-label="Sources">
        <h3 style={{ marginTop: 0 }}>Sources</h3>
        {error && <Banner kind="bad">{error}</Banner>}
        {b.sources.length === 0 ? <p className="small muted">None yet.</p> : (
          <ul className="sop-sources">
            {b.sources.map((s) => (
              <li key={s.id}>
                <div><strong>{s.title}</strong> <span className="small muted">{s.label}</span>{" "}
                  {s.state === "reading" && <Pill kind="info">Being read</Pill>}
                  {s.state === "failed" && <Pill kind="bad">Couldn't be read</Pill>}
                  {s.kept && <Pill>File kept</Pill>}</div>
                {s.error && <div className="small sop-error">{s.error}</div>}
                {s.preview && <div className="small muted sop-preview">{s.preview}</div>}
                <button className="ghost small" aria-label={`Remove ${s.title}`} onClick={() => remove.mutate(s.id)}>Remove</button>
              </li>))}
          </ul>)}
        <div className="row tight">
          <button className="small" onClick={() => setPasting({ title: "", text: "" })}>Paste text</button>
          <label className="btn small sop-file">Add an image or PDF
            <input type="file" accept="image/*,application/pdf" aria-label="Add an image or PDF"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                const form = new FormData();
                form.append("file", file);
                add.mutate(form);
              }} /></label>
          <button className="small" onClick={() => setMedia(true)}>Add video or audio</button>
        </div>
        {add.isPending && <p className="small muted">Adding…</p>}
      </section>
      {pasting && (
        <Modal label="Paste text" title="Paste text" wide onClose={() => setPasting(null)}>
          <label>Title<input aria-label="Source title" value={pasting.title}
            placeholder="For example: Notebook summary, or Call transcript"
            onChange={(e) => setPasting({ ...pasting, title: e.target.value })} /></label>
          <label>The text<textarea aria-label="Text to add" rows={10} value={pasting.text}
            onChange={(e) => setPasting({ ...pasting, text: e.target.value })} /></label>
          <div className="row tight">
            <button className="primary" disabled={!pasting.text.trim() || add.isPending}
              onClick={() => add.mutate({ kind: "pasted", ...pasting })}>Add the text</button>
            <button onClick={() => setPasting(null)}>Cancel</button>
          </div>
        </Modal>)}
      {media && <MediaModal b={b} onClose={() => setMedia(false)} onDone={onDone}
        onPaste={() => { setMedia(false); setPasting({ title: "Transcript", text: "" }); }} />}
    </aside>
  );
}

function MediaModal({ b, onClose, onDone, onPaste }: {
  b: Brainstorm; onClose: () => void; onDone: (b: Brainstorm) => void; onPaste: () => void;
}) {
  const m = b.media;
  const [file, setFile] = useState<File | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [keep, setKeep] = useState(false);
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file as File);
      form.append("seconds", String(seconds));
      form.append("keep", keep ? "true" : "false");
      return api.post<Brainstorm>(`/api/sops/brainstorms/${b.id}/media/`, form);
    },
    onSuccess: (next) => { onDone(next); onClose(); },
  });
  const kind = file?.type.startsWith("video/") ? "video" : "audio";
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  const price = Number(m.about_per_minute[kind] ?? 0) * minutes;
  return (
    <Modal label="Add video or audio" title="Add video or audio" onClose={onClose}>
      {!m.set ? (
        <>
          <Banner kind="warn">{m.refused}</Banner>
          <div className="row tight">
            <button className="primary" onClick={onPaste}>Paste a transcript instead</button>
            <button onClick={onClose}>Close</button>
          </div>
        </>
      ) : (
        <>
          <p className="small" style={{ marginTop: 0 }}>Gemini reads it into a transcript and its steps,
            which become a source here. Audio up to {m.limits.audio.minutes} minutes and {m.limits.audio.mb} MB;
            video up to {m.limits.video.minutes} minutes and {m.limits.video.mb} MB.</p>
          <p className="small muted">{m.notice}</p>
          {upload.isError && <Banner kind="bad">{errorOf(upload.error)}</Banner>}
          <input type="file" accept="audio/*,video/*" aria-label="Video or audio file"
            onChange={async (e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setSeconds(f ? await mediaSeconds(f) : 0);
            }} />
          {file && (seconds > 0 ? (
            <p className="sop-media-price">{Math.round(seconds / 60 * 10) / 10} minutes of {kind}: {about(price)} to read with Gemini.</p>
          ) : <p className="small sop-error">The file's length couldn't be read, so it can't be priced. Try another file.</p>)}
          <label className="check"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />{" "}
            Keep the file (otherwise it is not kept once it is read)</label>
          <div className="row tight">
            <button className="primary" disabled={!file || !seconds || upload.isPending}
              onClick={() => upload.mutate()}>{upload.isPending ? "Sending…" : `Read it (${about(price)})`}</button>
            <button onClick={onClose}>Cancel</button>
          </div>
        </>
      )}
    </Modal>
  );
}
