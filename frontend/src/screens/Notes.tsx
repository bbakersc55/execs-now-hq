import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Me, Note, NotesSettings, api } from "../lib/api";
import { LinkChips } from "./NoteDetail";

export function NoteRow({ note }: { note: Note }) {
  return (
    <li>
      <Link to={`/notes/${note.id}`}>{note.is_locked && "🔒 "}{note.title}</Link>{" "}
      <span className="muted small">{when(note.created_at)}</span>
      <br />
      <LinkChips note={note} />
    </li>
  );
}

export function Notes({ me }: { me: Me }) {
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");
  const notes = useQuery<Note[]>({
    queryKey: ["notes", active],
    queryFn: () => api.get<Note[]>(active ? `/api/notes/?q=${encodeURIComponent(active)}` : "/api/notes/"),
  });

  return (
    <>
      <h2>Notes</h2>
      <p className="sub">
        Press <span className="mono">n</span> anywhere to write one. Search covers titles, text,
        and accepted summaries; a locked note is found by its title only.
      </p>
      <Card>
        <form className="row" onSubmit={(e) => { e.preventDefault(); setActive(term.trim()); }}>
          <input aria-label="Search notes" placeholder="Search notes…" value={term}
            onChange={(e) => setTerm(e.target.value)} />
          <button className="primary" type="submit">Search</button>
          {active && <button className="ghost" type="button" onClick={() => { setTerm(""); setActive(""); }}>Clear</button>}
        </form>
        {(notes.data ?? []).length === 0
          ? <Empty>{active ? "No notes match that search." : "No notes yet."}</Empty>
          : <ul className="timeline">{notes.data!.map((n) => <NoteRow key={n.id} note={n} />)}</ul>}
      </Card>
      {me.role === "FF" && <RecordingSettings />}
    </>
  );
}

function RecordingSettings() {
  const qc = useQueryClient();
  const settings = useQuery<NotesSettings>({
    queryKey: ["notes-settings"], queryFn: () => api.get<NotesSettings>("/api/notes/settings/"),
  });
  const [days, setDays] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.patch<NotesSettings>("/api/notes/settings/", { audio_retention_days: Number(days) }),
    onSuccess: () => { setDays(null); qc.invalidateQueries({ queryKey: ["notes-settings"] }); },
  });
  const value = days ?? String(settings.data?.audio_retention_days ?? "");

  return (
    <Card title="Recording audio retention">
      <p className="small">
        Transcripts and summaries are kept indefinitely. The audio itself is deleted this many
        days after recording — but only once it has been transcribed. Audio that never
        transcribed is kept, and flagged on its note, until someone retries or discards it.
      </p>
      <Field label="Keep audio for (days)">
        <input aria-label="Keep audio for (days)" type="number" min={0} value={value}
          onChange={(e) => setDays(e.target.value)} style={{ maxWidth: "8rem" }} />
      </Field>
      {value === "0" && (
        <Banner kind="warn">
          At 0, audio is deleted as soon as its transcript is made. <strong>A recording can then
          never be transcribed again</strong> — if the transcript is poor, there is nothing to retry.
        </Banner>
      )}
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <button className="primary" disabled={days === null || save.isPending} onClick={() => save.mutate()}>Save</button>
    </Card>
  );
}
