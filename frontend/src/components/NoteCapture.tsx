import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { NoteFull, api } from "../lib/api";
import { saveAndUpload } from "../lib/pendingUploads";
import { LinkPicker, Links } from "./LinkPicker";
import { Recorder } from "./Recorder";
import { Banner } from "./ui";

/** True when a keystroke belongs to something the user is typing into. */
function typing(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

/**
 * FR-2.1 — capture in one action from anywhere: the sidebar button, or "n"
 * when focus is not in a field. Body only; title and links are optional.
 *
 * Docked in the app shell, not a route and not a modal, so it survives
 * navigating mid-call. It cannot be closed while recording: closing would
 * destroy the recorder and the audio with it.
 */
export function NoteCapture({ defaults }: { defaults?: Partial<Links> }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [links, setLinks] = useState<Links>({ contact: null, company: null, task: null });
  const [recording, setRecording] = useState(false);
  const [result, setResult] = useState<{
    kind: "ok" | "warn" | "bad"; text: string; id?: string; downloadUrl?: string;
  } | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  function show() {
    setOpen(true);
    setResult(null);
    setLinks({ contact: null, company: null, task: null, ...defaults });
    setTimeout(() => bodyRef.current?.focus(), 0);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "n" && !e.metaKey && !e.ctrlKey && !e.altKey && !typing(e.target)) {
        e.preventDefault();
        show();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const payload = (extra: object = {}) => ({
    body, title: title.trim() || undefined,
    contact: links.contact, company: links.company, task: links.task, ...extra,
  });

  function reset() { setBody(""); setTitle(""); }

  const save = useMutation({
    mutationFn: () => api.post<NoteFull>("/api/notes/", payload()),
    onSuccess: (note) => {
      reset();
      setResult({ kind: "ok", text: "Note saved.", id: note.id });
      qc.invalidateQueries({ queryKey: ["notes"] });
      qc.invalidateQueries({ queryKey: ["timeline"] });
    },
    onError: (e: Error) => setResult({ kind: "bad", text: e.message }),
  });

  async function recorded(blob: Blob, seconds: number, capped: boolean) {
    let note: NoteFull;
    try {
      note = await api.post<NoteFull>("/api/notes/", payload({ source: "recording" }));
    } catch (e) {
      // Not even the note could be created, so there is no id to keep the
      // audio under. Offer the audio itself rather than lose it.
      setResult({ kind: "bad", downloadUrl: URL.createObjectURL(blob),
        text: `Could not save the note (${(e as Error).message}). Download the recording so it is not lost.` });
      return;
    }
    const upload = await saveAndUpload(note.id, blob, seconds);
    reset();
    qc.invalidateQueries({ queryKey: ["notes"] });
    qc.invalidateQueries({ queryKey: ["pending-uploads"] });
    const cap = capped ? " Recording stopped at the 120-minute limit; everything up to then is kept." : "";
    setResult(upload.ok
      ? { kind: "ok", text: `Recording saved and transcribing.${cap}`, id: note.id }
      : { kind: "warn", id: note.id, text: `The upload did not go through (${upload.reason}). ` +
          `The recording is kept in this browser and will be retried — nothing is lost.${cap}` });
  }

  if (!open) {
    return <button className="primary" style={{ margin: "0 1.25rem 1rem", width: "calc(100% - 2.5rem)" }}
      onClick={show} title="New note (n)">+ New note</button>;
  }

  return (
    <div className="capture card" role="dialog" aria-label="New note">
      <div className="spread">
        <h3 style={{ margin: 0 }}>New note</h3>
        <button className="ghost small" disabled={recording} aria-label="Close"
          title={recording ? "Stop recording first" : "Close"} onClick={() => setOpen(false)}>✕</button>
      </div>
      {result && (
        <Banner kind={result.kind}>
          {result.text} {result.id && <Link to={`/notes/${result.id}`} onClick={() => setOpen(false)}>Open note</Link>}
          {result.downloadUrl && <a href={result.downloadUrl} download="recording.webm">Download recording</a>}
        </Banner>
      )}
      <textarea ref={bodyRef} aria-label="Note" rows={5} placeholder="Write it down…"
        value={body} onChange={(e) => setBody(e.target.value)} />
      <input aria-label="Title (optional)" placeholder="Title (optional — the first line is used if blank)"
        value={title} onChange={(e) => setTitle(e.target.value)} />
      <LinkPicker value={links} onChange={setLinks} />
      <div className="spread">
        <button className="primary" disabled={!body.trim() || save.isPending || recording}
          onClick={() => save.mutate()}>Save note</button>
        <Recorder onActiveChange={setRecording} onComplete={recorded} />
      </div>
    </div>
  );
}
