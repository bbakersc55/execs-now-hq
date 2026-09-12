import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CommentsPanel } from "../components/CommentsPanel";
import { StakeholdersPanel } from "../components/StakeholdersPanel";
import { StatusChange } from "../components/StatusChange";
import { StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { ChecklistItem, Me, Note, Task, TaskUpdateRow, WorkStatus, api } from "../lib/api";
import { NoteRow } from "./Notes";

const TENANT = ["FF", "CF", "VA"];

const KIND_LABELS: Record<string, string> = {
  created: "created", status_changed: "status", assignee_changed: "assignee",
  due_changed: "due date", comment_added: "comment", checklist_completed: "step done",
  completed: "completed", narrative: "note for the client",
};

export function TaskDetail({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const isTenant = !!me.role && TENANT.includes(me.role);

  const task = useQuery<Task>({
    queryKey: ["task", id], queryFn: () => api.get<Task>(`/api/tasks/${id}/`),
  });
  const updates = useQuery<TaskUpdateRow[]>({
    queryKey: ["task-updates", id],
    queryFn: () => api.get<TaskUpdateRow[]>(`/api/tasks/${id}/updates/`),
  });
  const checklist = useQuery<ChecklistItem[]>({
    queryKey: ["checklist", id],
    queryFn: () => api.get<ChecklistItem[]>(`/api/tasks/${id}/checklist/`),
  });
  const notes = useQuery<Note[]>({
    queryKey: ["notes", "task", id], queryFn: () => api.get<Note[]>(`/api/notes/?task=${id}`),
    enabled: isTenant,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["task", id] });
    qc.invalidateQueries({ queryKey: ["task-updates", id] });
    qc.invalidateQueries({ queryKey: ["tasks"] });
  };

  const save = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.patch<Task>(`/api/tasks/${id}/`, patch),
    onSuccess: () => { setMessage(""); refresh(); },
    onError: (e: Error) => setMessage(e.message),
  });

  const addStep = useMutation({
    mutationFn: (text: string) => api.post(`/api/tasks/${id}/checklist/`, { text }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checklist", id] }),
  });
  const toggleStep = useMutation({
    mutationFn: (item: ChecklistItem) =>
      api.patch(`/api/checklist-items/${item.id}/`, { is_done: !item.is_done }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checklist", id] });
      qc.invalidateQueries({ queryKey: ["task-updates", id] });
    },
  });

  const [step, setStep] = useState("");
  const [narrative, setNarrative] = useState("");
  const addNarrative = useMutation({
    mutationFn: () => api.post(`/api/tasks/${id}/narrative/`, { client_facing_line: narrative }),
    onSuccess: () => { setNarrative(""); refresh(); },
    onError: (e: Error) => setMessage(e.message),
  });

  if (task.isLoading) return <p>Loading…</p>;
  if (task.isError) return <Banner kind="bad">That task is not available to you.</Banner>;
  const t = task.data!;

  return (
    <>
      <p className="small">
        {t.goal && <><Link to={`/work/goals/${t.goal}`}>{t.goal_title}</Link> · </>}
        {t.project && <><Link to={`/work/projects/${t.project}`}>{t.project_title}</Link> · </>}
        <Link to="/work">Work</Link>
      </p>
      <h2>{t.title}</h2>
      <p className="sub">
        <StatusPill status={t.status} />{" "}
        {t.client_company_name
          ? <Link to={`/companies/${t.client_company}`}>{t.client_company_name}</Link>
          : "internal"}
        {t.created_by_client && <> · <span className="pill">created by the client</span></>}
        {t.client_company && !t.is_client_visible && <> · <span className="pill bad">hidden from the client</span></>}
      </p>
      {message && <Banner kind="bad">{message}</Banner>}
      {!t.may_edit && (
        <Banner kind="info">
          This task is the practice's to change. Add a comment below and they will see it.
        </Banner>
      )}

      <Card title="Status and detail">
        <div className="row">
          <Field label="Status">
            <StatusChange status={t.status} disabled={!t.may_edit} askForLine={isTenant}
              onChange={(status: WorkStatus, line: string) =>
                save.mutate({ status, ...(line ? { client_facing_line: line } : {}) })} />
          </Field>
          <Field label="Due">
            <input aria-label="Due date" type="date" value={t.due_date ?? ""} disabled={!t.may_edit}
              onChange={(e) => save.mutate({ due_date: e.target.value || null })} />
          </Field>
          <Field label="Priority">
            <select aria-label="Priority" value={t.priority} disabled={!t.may_edit}
              onChange={(e) => save.mutate({ priority: Number(e.target.value) })}>
              <option value={0}>Low</option>
              <option value={1}>Normal</option>
              <option value={2}>High</option>
              <option value={3}>Urgent</option>
            </select>
          </Field>
        </div>
        <p className="small muted">
          Assignee: {t.assignee.name || "unassigned"} · Owner: {t.owner.name || "—"} ·
          Client owner: {t.client_owner_contact.name || "—"} · updated {when(t.updated_at)}
        </p>
        {t.description && <div style={{ whiteSpace: "pre-wrap" }}>{t.description}</div>}
        {t.may_set_visibility && t.client_company && (
          <p className="small">
            <label style={{ display: "inline-flex", gap: ".4rem", alignItems: "center" }}>
              <input type="checkbox" checked={t.is_client_visible} style={{ width: "auto" }}
                aria-label="Visible to the client"
                onChange={(e) => {
                  if (e.target.checked && !t.is_client_visible
                      && !confirm("Making this visible also shows the client everything already "
                                  + "recorded on it, including past shared comments. Continue?")) return;
                  save.mutate({ is_client_visible: e.target.checked });
                }} />
              Visible to the client
            </label>
          </p>
        )}
      </Card>

      {isTenant && (
        <Card title="A line for the client, without changing status">
          <textarea aria-label="Client-facing line" rows={2} value={narrative}
            placeholder="What would you want them to read in Friday's report?"
            onChange={(e) => setNarrative(e.target.value)} />
          <button className="primary" disabled={!narrative.trim() || addNarrative.isPending}
            onClick={() => addNarrative.mutate()}>Add it</button>
        </Card>
      )}

      <Card title="Steps">
        {(checklist.data ?? []).length === 0 ? <Empty>No steps.</Empty> : (
          <ul style={{ listStyle: "none", paddingLeft: 0 }}>
            {checklist.data!.map((item) => (
              <li key={item.id}>
                <label style={{ display: "inline-flex", gap: ".45rem", alignItems: "center" }}>
                  <input type="checkbox" checked={item.is_done} disabled={!t.may_edit}
                    aria-label={item.text} style={{ width: "auto" }}
                    onChange={() => toggleStep.mutate(item)} />
                  <span style={{ textDecoration: item.is_done ? "line-through" : "none" }}>
                    {item.text}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {t.may_edit && (
          <div className="row">
            <input aria-label="New step" value={step} placeholder="Add a step…"
              onChange={(e) => setStep(e.target.value)} />
            <button disabled={!step.trim()}
              onClick={() => { addStep.mutate(step.trim()); setStep(""); }}>Add step</button>
          </div>
        )}
        <p className="small muted">
          Steps are a flat list on purpose: a task cannot hold another task, which is what
          keeps three levels from becoming unlimited.
        </p>
      </Card>

      <StakeholdersPanel me={me} target="task" id={id!} />

      <CommentsPanel me={me} target="task" id={id!} />

      <Card title="History">
        {(updates.data ?? []).length === 0 ? <Empty>Nothing yet.</Empty> : (
          <ul className="timeline">
            {updates.data!.map((u) => (
              <li key={u.id}>
                <div>
                  <strong>{KIND_LABELS[u.kind] ?? u.kind}</strong>
                  {u.from_value && u.to_value && <> — {u.from_value} → {u.to_value}</>}
                  {!u.from_value && u.to_value && u.kind !== "comment_added" && <> — {u.to_value}</>}
                </div>
                {u.client_facing_line && (
                  <div className="small" style={{ color: "var(--blue)" }}>
                    For the client: “{u.client_facing_line}”
                  </div>
                )}
                <div className="when">
                  {u.actor.name || u.source.replace(/_/g, " ")} · {when(u.created_at)}
                  {u.is_client_actor && " · by the client"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {isTenant && (
        <Card title="Notes on this task">
          {(notes.data ?? []).length === 0 ? <Empty>No notes linked to this task.</Empty> : (
            <ul className="timeline">{notes.data!.map((n) => <NoteRow key={n.id} note={n} />)}</ul>
          )}
        </Card>
      )}

      {t.may_delete && (
        <Card title="Delete">
          <button className="danger" onClick={async () => {
            await api.del(`/api/tasks/${id}/`);
            qc.invalidateQueries({ queryKey: ["tasks"] });
            navigate("/work");
          }}>Delete this task</button>
        </Card>
      )}
    </>
  );
}
