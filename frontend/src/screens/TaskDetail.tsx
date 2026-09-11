import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { Banner, Card, Empty } from "../components/ui";
import { Note, Task, api } from "../lib/api";
import { NoteRow } from "./Notes";

/** Phase 2 needs a task to show its notes (AC-2.2). Module 3 owns the real
 *  task screen; this is the least that makes a task-linked note findable. */
export function TaskDetail() {
  const { id } = useParams();
  const task = useQuery<Task>({ queryKey: ["task", id], queryFn: () => api.get<Task>(`/api/tasks/${id}/`) });
  const notes = useQuery<Note[]>({
    queryKey: ["notes", "task", id], queryFn: () => api.get<Note[]>(`/api/notes/?task=${id}`),
  });

  if (task.isLoading) return <p>Loading…</p>;
  if (task.isError) return <Banner kind="bad">That task is not available to you.</Banner>;
  const t = task.data!;
  return (
    <>
      <h2>{t.title}</h2>
      <p className="sub">
        {t.status.replace(/_/g, " ")}{t.due_date && ` · due ${t.due_date}`}
        {t.contact && <> · <Link to={`/contacts/${t.contact}`}>contact</Link></>}
      </p>
      {t.description && <Card><div style={{ whiteSpace: "pre-wrap" }}>{t.description}</div></Card>}
      <Card title="Notes">
        {(notes.data ?? []).length === 0 ? <Empty>No notes on this task.</Empty>
          : <ul className="timeline">{notes.data!.map((n) => <NoteRow key={n.id} note={n} />)}</ul>}
      </Card>
    </>
  );
}
