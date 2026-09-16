import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CommentsPanel } from "../components/CommentsPanel";
import { StakeholdersPanel } from "../components/StakeholdersPanel";
import { STATUSES, STATUS_LABELS, StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Contact, Me, Task, WorkParent, api } from "../lib/api";

const TENANT = ["FF", "CF", "VA"];

/** One screen for both levels above a task: /work/goals/:id and
 *  /work/projects/:id. A goal shows its projects and its direct tasks; a
 *  project shows its tasks. */
export function WorkParentDetail({ me, kind }: { me: Me; kind: "goal" | "project" }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [newTask, setNewTask] = useState("");
  const [editing, setEditing] = useState(false);
  const isTenant = !!me.role && TENANT.includes(me.role);
  const plural = kind === "goal" ? "goals" : "projects";

  const entity = useQuery<WorkParent>({
    queryKey: [kind, id], queryFn: () => api.get<WorkParent>(`/api/${plural}/${id}/`),
  });
  const children = useQuery<{ projects: WorkParent[]; tasks: Task[] }>({
    queryKey: [kind, id, "children"],
    queryFn: () => api.get(`/api/${plural}/${id}/children/`),
  });

  const save = useMutation({
    mutationFn: (patch: Partial<WorkParent>) =>
      api.patch<WorkParent>(`/api/${plural}/${id}/`, patch),
    onSuccess: () => { setMessage(""); qc.invalidateQueries({ queryKey: [kind, id] }); },
    onError: (e: Error) => setMessage(e.message),
  });

  const addTask = useMutation({
    // A client may file a task straight onto a goal or project they can see. The
    // server sets a client's company itself, so only the practice sends one.
    mutationFn: () => api.post<Task>("/api/tasks/", {
      title: newTask, [kind]: id,
      ...(isTenant && entity.data?.client_company
        ? { client_company: entity.data.client_company } : {}),
    }),
    onSuccess: () => {
      setNewTask("");
      qc.invalidateQueries({ queryKey: [kind, id, "children"] });
      qc.invalidateQueries({ queryKey: [kind, id] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: () => api.del<{ detached: Record<string, number> }>(`/api/${plural}/${id}/`),
    onSuccess: (r) => {
      const counts = Object.entries(r.detached).map(([k, v]) => `${v} ${k}`).join(", ");
      qc.invalidateQueries({ queryKey: [plural] });
      navigate("/work", { state: { detached: counts } });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  if (entity.isLoading) return <p>Loading…</p>;
  if (entity.isError) return <Banner kind="bad">That is not available to you.</Banner>;
  const e = entity.data!;

  return (
    <>
      <p className="small"><Link to="/work">← Work</Link></p>
      <h2>{e.title}</h2>
      <p className="sub">
        {kind === "goal" ? "Goal" : "Project"} ·{" "}
        {e.client_company_name
          ? <Link to={`/companies/${e.client_company}`}>{e.client_company_name}</Link>
          : "internal"}
        {e.goal && <> · under <Link to={`/work/goals/${e.goal}`}>{e.goal_title}</Link></>}
        {" · "}<StatusPill status={e.status} derived={e.status_is_derived} />
      </p>
      {message && <Banner kind="bad">{message}</Banner>}

      <Card title="Status" actions={isTenant ? (
        <div className="row">
          <select aria-label="Status override" value={e.status_override ?? ""}
            onChange={(ev) => save.mutate({
              status_override: (ev.target.value || null) as WorkParent["status_override"],
            })}>
            <option value="">Derived from the work underneath</option>
            {STATUSES.map((s) => <option key={s} value={s}>Set to {STATUS_LABELS[s]}</option>)}
          </select>
        </div>
      ) : undefined}>
        <p className="small">
          {e.status_is_derived
            ? "Rolled up from the work underneath. Nothing is stored, so it cannot drift."
            : "Set by hand. Choosing “derived” returns it to the rollup."}
        </p>
        {e.description && <div style={{ whiteSpace: "pre-wrap" }}>{e.description}</div>}
        <p className="small muted">
          Owner: {e.owner.name || "—"} · Client owner: {e.client_owner_contact.name || "—"}
          {e.target_date && ` · target ${e.target_date}`} · created {when(e.created_at)}
        </p>
      </Card>

      {isTenant && (editing
        ? <EditDetails entity={e} kind={kind} onClose={() => setEditing(false)}
            onSaved={() => {
              setEditing(false);
              qc.invalidateQueries({ queryKey: [kind, id] });
              qc.invalidateQueries({ queryKey: [plural] });
            }} />
        : (
          <Card title="Details" actions={
            <button onClick={() => setEditing(true)}>Edit details</button>
          }>
            <p className="small muted">
              Title, description, dates and the client owner. A client never edits these.
            </p>
          </Card>
        ))}

      {kind === "goal" && (
        <Card title="Projects">
          {(children.data?.projects ?? []).length === 0 ? <Empty>No projects yet.</Empty> : (
            <ul className="timeline">
              {children.data!.projects.map((p) => (
                <li key={p.id}>
                  <Link to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
                  <StatusPill status={p.status} derived={p.status_is_derived} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Card title={kind === "goal" ? "Tasks filed straight on this goal" : "Tasks"}>
        {(children.data?.tasks ?? []).length === 0 ? <Empty>No tasks yet.</Empty> : (
          <ul className="timeline">
            {children.data!.tasks.map((t) => (
              <li key={t.id}>
                <Link to={`/tasks/${t.id}`}>{t.title}</Link>{" "}
                <StatusPill status={t.status} />
                {!t.is_client_visible && <span className="pill">internal</span>}
                <div className="when">
                  {t.assignee.name || "unassigned"}{t.due_date && ` · due ${t.due_date}`}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="row">
          <Field label="Add a task here">
            <input aria-label="New task title" value={newTask}
              onChange={(ev) => setNewTask(ev.target.value)} />
          </Field>
          <button className="primary" disabled={!newTask.trim() || addTask.isPending}
            onClick={() => addTask.mutate()}>Add task</button>
        </div>
      </Card>

      <StakeholdersPanel me={me} target={kind} id={id!} />

      <CommentsPanel me={me} target={kind} id={id!} />

      {isTenant && (
        <Card title="Delete">
          <p className="small">
            Deleting a {kind} does not delete its work: the projects and tasks under it are
            detached and reported, and stay where you can find them.
          </p>
          <button className="danger" onClick={() => remove.mutate()}>Delete this {kind}</button>
        </Card>
      )}
    </>
  );
}


/**
 * The practice edits what a goal or project actually says.
 *
 * The API accepted these fields the whole time; no screen ever sent them, so a
 * title typed in haste, a missing description or a date that moved could not be
 * corrected anywhere — the record was write-once in practice. Clients never see
 * this: goals are the practice's (matrix 7.2), and a project of the practice's
 * is refused to them by the server as well.
 */
function EditDetails({ entity, kind, onClose, onSaved }: {
  entity: WorkParent; kind: "goal" | "project"; onClose: () => void; onSaved: () => void;
}) {
  const plural = kind === "goal" ? "goals" : "projects";
  const [form, setForm] = useState({
    title: entity.title,
    description: entity.description ?? "",
    target_date: entity.target_date ?? "",
    start_date: entity.start_date ?? "",
    client_owner_contact: entity.client_owner_contact.id ?? "",
  });
  const [error, setError] = useState("");

  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
    enabled: !!entity.client_company,
  });
  const theirs = (contacts.data ?? []).filter((c) => c.company === entity.client_company);

  const save = useMutation({
    mutationFn: () => api.patch<WorkParent>(`/api/${plural}/${entity.id}/`, {
      title: form.title.trim(),
      description: form.description.trim(),
      target_date: form.target_date || null,
      ...(kind === "project" ? { start_date: form.start_date || null } : {}),
      client_owner_contact: form.client_owner_contact || null,
    }),
    onSuccess: onSaved,
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card title="Details" actions={<button onClick={onClose}>Cancel</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      <form onSubmit={(ev) => { ev.preventDefault(); setError(""); save.mutate(); }}>
        <Field label="Title">
          <input aria-label={`${kind === "goal" ? "Goal" : "Project"} title`} value={form.title}
            onChange={(ev) => setForm({ ...form, title: ev.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label={`${kind === "goal" ? "Goal" : "Project"} description`} rows={3}
            value={form.description}
            onChange={(ev) => setForm({ ...form, description: ev.target.value })} />
        </Field>
        <div className="row">
          {kind === "project" && (
            <Field label="Start">
              <input aria-label="Start date" type="date" value={form.start_date}
                onChange={(ev) => setForm({ ...form, start_date: ev.target.value })} />
            </Field>
          )}
          <Field label="Target date">
            <input aria-label="Target date" type="date" value={form.target_date}
              onChange={(ev) => setForm({ ...form, target_date: ev.target.value })} />
          </Field>
          <Field label="Client owner">
            <select aria-label="Client owner" value={form.client_owner_contact}
              disabled={!entity.client_company}
              onChange={(ev) => setForm({ ...form, client_owner_contact: ev.target.value })}>
              <option value="">
                {entity.client_company ? "Nobody" : "Internal work has no client owner"}
              </option>
              {theirs.map((c) => (
                <option key={c.id} value={c.id}>{c.first_name} {c.last_name}</option>
              ))}
            </select>
          </Field>
        </div>
        <button className="primary" type="submit" disabled={!form.title.trim() || save.isPending}>
          {save.isPending ? "Saving…" : "Save details"}
        </button>
      </form>
    </Card>
  );
}
