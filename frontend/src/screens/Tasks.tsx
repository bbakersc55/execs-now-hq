import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { STATUSES, STATUS_LABELS, StatusPill } from "../components/StatusPill";
import { Card, Empty, Field, when } from "../components/ui";
import { Me, Task, WorkParent, api } from "../lib/api";

/** FR-3.39 — list and board, both filterable by project, assignee and status. */
export function Tasks({ me }: { me: Me }) {
  const [view, setView] = useState<"list" | "board">("list");
  const [project, setProject] = useState("");
  const [assignee, setAssignee] = useState("");
  const [status, setStatus] = useState("");

  const query = new URLSearchParams();
  if (project) query.set("project", project);
  if (assignee) query.set("assignee", assignee);
  if (status) query.set("status", status);

  const tasks = useQuery<Task[]>({
    queryKey: ["tasks", query.toString()],
    queryFn: () => api.get<Task[]>(`/api/tasks/?${query.toString()}`),
  });
  const projects = useQuery<WorkParent[]>({
    queryKey: ["projects"], queryFn: () => api.get<WorkParent[]>("/api/projects/"),
  });
  const people = useQuery<{ id: string; name: string }[]>({
    queryKey: ["portal-people"], queryFn: () => api.get("/api/portal-people/"),
  });

  const rows = tasks.data ?? [];

  return (
    <>
      <h2>Tasks</h2>
      <p className="sub">
        {me.role === "FCC" || me.role === "ECC"
          ? "Everything your company can see, and everything you have added."
          : "Everything across your goals and projects, filed or not."}
      </p>

      <Card>
        <div className="row">
          <Field label="View">
            <select aria-label="View" value={view}
              onChange={(e) => setView(e.target.value as "list" | "board")}>
              <option value="list">List</option>
              <option value="board">Board</option>
            </select>
          </Field>
          <Field label="Project">
            <select aria-label="Filter by project" value={project}
              onChange={(e) => setProject(e.target.value)}>
              <option value="">Any project</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Assignee">
            <select aria-label="Filter by assignee" value={assignee}
              onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Anyone</option>
              {(people.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Status">
            <select aria-label="Filter by status" value={status}
              onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option>
              {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </Field>
        </div>
      </Card>

      {rows.length === 0 ? <Empty>No tasks match.</Empty> : view === "list" ? (
        <Card>
          <table>
            <thead>
              <tr><th>Task</th><th>Status</th><th>Assignee</th><th>Due</th><th>Where</th></tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/tasks/${t.id}`}>{t.title}</Link></td>
                  <td><StatusPill status={t.status} /></td>
                  <td className="muted">{t.assignee.name || "—"}</td>
                  <td className="muted">{t.due_date ?? "—"}</td>
                  <td className="small muted">
                    {t.project_title || t.goal_title || "unfiled"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        <div className="work-columns" aria-label="Board">
          {STATUSES.map((s) => (
            <div className="col" key={s}>
              <h4>{STATUS_LABELS[s]}</h4>
              {rows.filter((t) => t.status === s).map((t) => (
                <div key={t.id} className="comment">
                  <Link to={`/tasks/${t.id}`}>{t.title}</Link>
                  <div className="when">
                    {t.assignee.name || "unassigned"}
                    {t.due_date && ` · due ${t.due_date}`}
                  </div>
                </div>
              ))}
              {rows.filter((t) => t.status === s).length === 0 && (
                <p className="small muted">—</p>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="small muted">Showing {rows.length} · {when(new Date().toISOString())}</p>
    </>
  );
}
