import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import { Banner, Card, Field, Pill } from "./ui";

/**
 * The notes of the call, attached to its session as context for Claude's
 * drafts (owner, 2026-10-08).
 *
 * Three ways in: a file the meeting queue has read for the day of the call, a
 * Drive document by its link, or pasted text. Once attached, "Draft rows",
 * "Consolidate" and the pros-and-cons draft read the notes beside the answers.
 *
 * **Yours only.** Shown to the practice owner, and to an associate on their
 * own prospect. Never on the form, in an email, on the document, or to an
 * assistant: the server does not send them to anyone else.
 */

export interface AttachedCallNotes {
  source: string; source_label: string; title: string; characters: number; text: string;
  added_by: string; added_at: string;
}
type Offered = { attached: AttachedCallNotes | null; day: string;
                 candidates: { id: string; name: string; state: string; characters: number }[] };

export function SessionCallNotes({ path, attached, onChanged }: {
  path: string; attached: AttachedCallNotes | null; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [showing, setShowing] = useState(false);
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [said, setSaid] = useState("");
  const offered = useQuery<Offered>({
    queryKey: ["session-call-notes", path],
    queryFn: () => api.get<Offered>(`${path}call-notes/`), enabled: open });
  const done = () => { setSaid(""); setOpen(false); setLink(""); setText(""); onChanged(); };
  const attach = useMutation({
    mutationFn: (body: object) => api.post(`${path}call-notes/`, body),
    onSuccess: done, onError: (e: Error) => setSaid(e.message) });
  const remove = useMutation({
    mutationFn: () => api.del(`${path}call-notes/`),
    onSuccess: done, onError: (e: Error) => setSaid(e.message) });
  const busy = attach.isPending || remove.isPending;

  return (
    <Card title="The call notes"
      actions={attached ? <Pill kind="ok">attached</Pill> : <Pill>none attached</Pill>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Attach the notes of this call and Claude reads them, beside your answers, when it
        drafts rows, consolidates, and drafts the pros and cons. They are yours: never on
        the document, never sent to the prospect, and not shown to an assistant.
      </p>
      {said && <Banner kind="bad">{said}</Banner>}
      {attached && (
        <>
          <p className="small">
            <strong>{attached.title}</strong> · {attached.source_label.toLowerCase()} ·{" "}
            {attached.characters.toLocaleString("en-US")} characters · attached by{" "}
            {attached.added_by}
          </p>
          {showing && (
            <pre className="small" aria-label="The attached call notes"
              style={{ whiteSpace: "pre-wrap", maxHeight: "18rem", overflowY: "auto" }}>
              {attached.text}</pre>
          )}
        </>
      )}
      {!open && (
        <div className="row tight">
          <button disabled={busy} onClick={() => setOpen(true)}>
            {attached ? "Replace the call notes" : "Add the call notes"}</button>
          {attached && (
            <>
              <button className="ghost" onClick={() => setShowing(!showing)}>
                {showing ? "Hide them" : "Read them"}</button>
              <button className="ghost" disabled={busy} onClick={() => {
                if (confirm("Take the call notes off this session? Rows already drafted "
                  + "from them stay as they are.")) remove.mutate();
              }}>Remove</button>
            </>
          )}
        </div>
      )}
      {open && (
        <div className="card">
          <p className="small" style={{ marginTop: 0 }}><strong>From the meeting queue</strong>
            {offered.data && <span className="muted"> · files read for {offered.data.day}</span>}
          </p>
          {offered.isLoading && <p className="small muted">Looking…</p>}
          {offered.data && offered.data.candidates.length === 0 && (
            <p className="small muted">The meeting queue has read no file for that day.</p>
          )}
          {(offered.data?.candidates ?? []).map((file) => (
            <p key={file.id} className="small" style={{ margin: "0 0 var(--s1)" }}>
              <button className="small" disabled={busy}
                aria-label={`Attach ${file.name}`}
                onClick={() => attach.mutate({ source: "meeting_file", source_file: file.id })}>
                Attach</button>{" "}
              {file.name} <span className="muted">· {file.state.toLowerCase()} ·{" "}
                {file.characters.toLocaleString("en-US")} characters</span>
            </p>
          ))}
          <div className="row" style={{ marginTop: "var(--s3)" }}>
            <Field label="Or a Drive document, by its link">
              <input aria-label="Link to the Drive document" value={link}
                placeholder="https://docs.google.com/document/d/…"
                onChange={(e) => setLink(e.target.value)} />
            </Field>
            <button disabled={busy || !link.trim()}
              onClick={() => attach.mutate({ source: "drive", link: link.trim() })}>
              Attach the document</button>
          </div>
          <Field label="Or paste the notes">
            <textarea rows={6} aria-label="Pasted call notes" value={text}
              onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="row tight">
            <button disabled={busy || !text.trim()}
              onClick={() => attach.mutate({ source: "pasted", text })}>
              Attach what I pasted</button>
            <button className="ghost" onClick={() => { setOpen(false); setSaid(""); }}>
              Cancel</button>
          </div>
        </div>
      )}
    </Card>
  );
}
