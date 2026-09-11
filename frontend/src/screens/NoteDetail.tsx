import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { LinkPicker, Links } from "../components/LinkPicker";
import { PinDialog } from "../components/PinDialog";
import { clock } from "../components/Recorder";
import { Banner, Card, Pill, when } from "../components/ui";
import { Me, Note, NoteFull, NoteStub, NotesSettings, api } from "../lib/api";
import { retry as retryUpload } from "../lib/pendingUploads";

export function LinkChips({ note }: { note: NoteStub | NoteFull }) {
  const chips = [
    note.contact && <Link key="c" to={`/contacts/${note.contact}`}>{note.contact_name || "Contact"}</Link>,
    note.company && <Link key="co" to={`/companies/${note.company}`}>{note.company_name || "Company"}</Link>,
    note.task && <Link key="t" to={`/tasks/${note.task}`}>Task: {note.task_title}</Link>,
  ].filter(Boolean);
  return chips.length
    ? <span className="small">{chips.map((c, i) => <span key={i}>{i > 0 && " · "}{c}</span>)}</span>
    : <span className="small muted">Not linked to anything</span>;
}

export function NoteDetail(_props: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const note = useQuery<Note>({
    queryKey: ["note", id],
    queryFn: () => api.get<Note>(`/api/notes/${id}/`),
    // Transcription and drafting happen in the background; check back.
    refetchInterval: (q) => {
      const n = q.state.data;
      return n && !n.stub && (n.transcription_state === "transcribing" || n.summary_state === "drafting")
        ? 15_000 : false;
    },
  });
  const refresh = (updated?: Note) => {
    if (updated) qc.setQueryData(["note", id], updated);
    qc.invalidateQueries({ queryKey: ["note", id] });
    qc.invalidateQueries({ queryKey: ["notes"] });
  };

  if (note.isLoading) return <p>Loading…</p>;
  if (note.isError || !note.data) return <Banner kind="bad">That note is not available to you.</Banner>;
  const n = note.data;

  return (
    <>
      <p className="small"><Link to="/notes">← Notes</Link></p>
      <h2>{n.is_locked && "🔒 "}{n.title}</h2>
      <p className="sub"><LinkChips note={n} /> · {when(n.created_at)}</p>
      {n.stub ? <LockedNote note={n} onUnlocked={refresh} /> : <OpenNote note={n} onChange={refresh} />}
    </>
  );
}

function LockedNote({ note, onUnlocked }: { note: NoteStub; onUnlocked: (n: Note) => void }) {
  const [pin, setPin] = useState("");
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);
  const unlock = useMutation({
    mutationFn: () => api.post<Note>(`/api/notes/${note.id}/unlock/`, { pin }),
    onSuccess: (n) => { setPin(""); onUnlocked(n); },
    onError: (e: Error) => { setPin(""); setMessage({ kind: "bad", text: e.message }); },
  });
  const reset = useMutation({
    mutationFn: () => api.post<{ detail: string }>(`/api/notes/${note.id}/pin-reset/`),
    onSuccess: (r) => setMessage({ kind: "ok", text: r.detail }),
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });

  return (
    <Card title="This note is locked">
      <p className="small">Enter its PIN to read it. It stays open in this browser for 30 minutes.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); unlock.mutate(); }}>
        <input aria-label="PIN" type="password" inputMode="numeric" autoComplete="off"
          value={pin} onChange={(e) => setPin(e.target.value)} style={{ maxWidth: "10rem" }} />
        <button className="primary" type="submit" disabled={!pin || unlock.isPending}>Unlock</button>
      </form>
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      {note.can_reset_pin && (
        <p className="small">
          Forgotten the PIN?{" "}
          <button className="ghost small" onClick={() => reset.mutate()} disabled={reset.isPending}>
            Email me a link that clears it
          </button>
          <br />
          <span className="muted">The link removes the PIN; it never shows what the PIN was.</span>
        </p>
      )}
    </Card>
  );
}

function OpenNote({ note, onChange }: { note: NoteFull; onChange: (n?: Note) => void }) {
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(note.title_is_auto ? "" : note.title);
  const [body, setBody] = useState(note.body);
  const [links, setLinks] = useState<Links>({
    contact: note.contact, contactName: note.contact_name, company: note.company, task: note.task,
  });
  const [pinDialog, setPinDialog] = useState(false);
  const [error, setError] = useState("");
  // A VA may not read settings (matrix 3.1); the banner then says "configured".
  const settings = useQuery<NotesSettings>({
    queryKey: ["notes-settings"], queryFn: () => api.get<NotesSettings>("/api/notes/settings/"),
    retry: false,
  });

  const act = useMutation({
    mutationFn: ({ path, data, method = "post" }: { path: string; data?: object; method?: "post" | "del" | "patch" }) =>
      method === "del" ? api.del<Note>(`/api/notes/${note.id}/${path}`)
        : method === "patch" ? api.patch<Note>(`/api/notes/${note.id}/${path}`, data)
        : api.post<Note>(`/api/notes/${note.id}/${path}`, data),
    onSuccess: (n) => { setError(""); onChange(n); },
    onError: (e: Error) => setError(e.message),
  });

  async function saveEdits() {
    await act.mutateAsync({
      path: "", method: "patch",
      data: { title: title.trim(), body, contact: links.contact, company: links.company, task: links.task },
    }).then(() => setEditing(false)).catch(() => undefined);
  }

  async function remove() {
    await api.del(`/api/notes/${note.id}/`);
    onChange();
    navigate("/notes");
  }

  if (pinDialog) {
    return <PinDialog note={note} onCancel={() => setPinDialog(false)}
      onDone={(n) => { setPinDialog(false); onChange(n); }} />;
  }

  return (
    <>
      {error && <Banner kind="bad">{error}</Banner>}
      <Card title="Note" actions={
        <div className="row">
          {!editing && <button className="ghost small" onClick={() => setEditing(true)}>Edit</button>}
          {!note.is_locked && <button className="ghost small" onClick={() => setPinDialog(true)}>Set a PIN</button>}
          {note.is_locked && <>
            <button className="ghost small" onClick={() => act.mutate({ path: "lock/" })}>Lock now</button>
            <button className="ghost small" onClick={() => setPinDialog(true)}>Change PIN</button>
            <button className="ghost small" onClick={() => act.mutate({ path: "pin/", method: "del" })}>Remove PIN</button>
          </>}
        </div>
      }>
        {note.is_locked && <p className="small"><Pill kind="warn">Unlocked in this browser</Pill></p>}
        {editing ? (
          <>
            <input aria-label="Title" value={title} placeholder="Title (blank uses the first line)"
              onChange={(e) => setTitle(e.target.value)} />
            <textarea aria-label="Body" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
            <LinkPicker value={links} onChange={setLinks} />
            <div className="row">
              <button className="primary" onClick={saveEdits}>Save</button>
              <button className="ghost" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </>
        ) : (
          <div style={{ whiteSpace: "pre-wrap" }}>{note.body || <span className="muted">No typed notes.</span>}</div>
        )}
        <p className="small muted">
          {note.created_by_name && <>By {note.created_by_name}. </>}
          <button className="ghost small" onClick={remove}>Delete note</button>
        </p>
      </Card>

      {note.source === "recording" || note.transcription_state !== "none"
        ? <RecordingPanel note={note} retention={settings.data?.audio_retention_days} act={act.mutate} />
        : null}
    </>
  );
}

function RecordingPanel({ note, retention, act }: {
  note: NoteFull; retention?: number;
  act: (a: { path: string; data?: object }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.proposed_summary ?? "");
  const [uploadMessage, setUploadMessage] = useState("");
  const duration = note.audio_duration_seconds ? clock(note.audio_duration_seconds) : "";

  return (
    <>
      <Card title={`Recording${duration ? ` · ${duration}` : ""}`}>
        {note.transcription_state === "uploading" && (
          <>
            <Banner kind="warn">
              Waiting for the audio to upload from the browser that recorded it. If that was
              this browser, it is held here and retried automatically.
            </Banner>
            <button onClick={async () => {
              const r = await retryUpload(note.id);
              setUploadMessage(r.ok ? "Uploaded." : `Not yet: ${r.reason}`);
            }}>Retry upload from this browser</button>
            {uploadMessage && <p className="small">{uploadMessage}</p>}
          </>
        )}
        {note.transcription_state === "transcribing" && (
          <p>Transcribing… a long call can take a while. This page checks back on its own.</p>
        )}
        {note.transcription_state === "failed" && (
          <Banner kind="bad">
            {note.transcription_error || "Transcription failed."}{" "}
            {note.has_audio ? "The audio is kept." : ""}
          </Banner>
        )}
        {note.retention_overdue && (
          <Banner kind="warn">
            This audio is older than the practice's {retention ?? "configured"}-day retention. It
            is being kept only because it was never transcribed — it is the only record of the
            call. Retry the transcription, or discard the audio.
          </Banner>
        )}
        <div className="row">
          {note.has_audio && note.transcription_state === "failed" && (
            <button onClick={() => act({ path: "retry-transcription/" })}>Retry transcription</button>
          )}
          {note.has_audio && note.transcription_state !== "transcribing" && (
            <button className="ghost small" onClick={() => act({ path: "discard-audio/" })}>Discard audio</button>
          )}
          {!note.has_audio && note.transcription_state === "done" && (
            <span className="small muted">Audio deleted under the retention setting; the transcript is kept.</span>
          )}
        </div>
      </Card>

      {note.transcript && (
        <div className="board" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Card title="Transcript">
            <div className="small" style={{ whiteSpace: "pre-wrap", maxHeight: "32rem", overflowY: "auto" }}>
              {note.transcript}
            </div>
          </Card>
          <Card title="Summary">
            {note.summary_state === "drafting" && <p className="muted">Claude is drafting a summary…</p>}
            {note.summary_state === "proposed" && (
              <>
                <p className="small"><Pill kind="ai">Proposed by Claude — not attached until you accept it</Pill></p>
                {editing
                  ? <textarea aria-label="Edit summary" rows={12} value={draft} onChange={(e) => setDraft(e.target.value)} />
                  : <div style={{ whiteSpace: "pre-wrap" }}>{note.proposed_summary}</div>}
                {note.can_review_summary ? (
                  <div className="row">
                    <button className="primary" onClick={() => act({
                      path: "summary/accept/", data: editing ? { text: draft } : {},
                    })}>{editing ? "Accept edited summary" : "Accept"}</button>
                    {!editing && <button onClick={() => { setDraft(note.proposed_summary ?? ""); setEditing(true); }}>Edit summary</button>}
                    <button className="ghost" onClick={() => act({ path: "summary/discard/" })}>Discard</button>
                  </div>
                ) : <p className="small muted">Waiting for the note's author to review it.</p>}
              </>
            )}
            {note.summary_state === "accepted" && <div style={{ whiteSpace: "pre-wrap" }}>{note.summary}</div>}
            {(note.summary_state === "failed" || note.summary_state === "discarded") && (
              <>
                <p className="small muted">
                  {note.summary_state === "failed"
                    ? "Claude could not draft a summary. The transcript is kept."
                    : "Summary discarded. The transcript is kept."}
                </p>
                {note.can_review_summary && (
                  <button onClick={() => act({ path: "summary/redraft/" })}>Draft another summary</button>
                )}
              </>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
