import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CommentsPanel } from "../components/CommentsPanel";
import { StakeholdersPanel } from "../components/StakeholdersPanel";
import { STATUSES, STATUS_LABELS, StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Me, Task, WorkParent, api } from "../lib/api";

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
    mutationFn: () => api.post<Task>("/api/tasks/", {
      title: newTask, [kind]: id,
      ...(entity.data?.client_company ? { client_company: entity.data.client_company } : {}),
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
