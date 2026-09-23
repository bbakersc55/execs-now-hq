import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { FileText } from "lucide-react";

import { PageHead, SearchField } from "../components/shell";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Me, Note, NotesSettings, api } from "../lib/api";
import { LinkChips, NoteDetail } from "./NoteDetail";

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

/**
 * Notes (design brief, Tier 2): **list on the left, note on the right.**
 *
 * A note is read in the context of the others — what did I write about this
 * client, in what order — and the old full-page-per-note layout made that a
 * round trip through a list each time. The panel keeps the list in view while
 * a note is open, and every note is still its own URL, so a link into one
 * still works and still opens it here.
 *
 * Stacks and notebooks are a data-model change and stay on the roadmap; this
 * is layout only.
 */
export function Notes({ me }: { me: Me }) {
  const { id } = useParams();
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setActive(term.trim()), 250);
    return () => clearTimeout(timer);
  }, [term]);

  const notes = useQuery<Note[]>({
    queryKey: ["notes", active],
    queryFn: () => api.get<Note[]>(active ? `/api/notes/?q=${encodeURIComponent(active)}` : "/api/notes/"),
  });
  const rows = notes.data ?? [];

  return (
    <>
      <PageHead title="Notes"
        sub={<>Press <span className="mono">n</span> anywhere to write one. Search
          covers titles, text and accepted summaries; a locked note is found by
          its title only.</>} />

      <div className="panel-split">
        <div className="panel-list">
          <SearchField label="Search notes" value={term} onChange={setTerm}
            placeholder="Search notes…" />
          {rows.length === 0 ? (
            <Empty>{active ? "No notes match that search." : "No notes yet."}</Empty>
          ) : (
            <ul className="notelist">
              {rows.map((note) => (
                <li key={note.id}>
                  <NavLink to={`/notes/${note.id}`}
                    className={({ isActive }) => isActive ? "on" : ""}>
                    <span className="notetitle">
                      {note.is_locked && "🔒 "}{note.title}
                    </span>
                    <span className="tiny muted">{when(note.created_at)}</span>
                    <LinkChips note={note} />
                  </NavLink>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="panel-body">
          {id ? <NoteDetail me={me} inPanel /> : (
            <Empty>
              <FileText size={14} /> Choose a note to read it here, or press{" "}
              <span className="mono">n</span> to write one.
            </Empty>
          )}
        </div>
      </div>

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
