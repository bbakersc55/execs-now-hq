import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PortalCreate } from "../components/PortalCreate";
import { StaffCreate } from "../components/StaffCreate";
import { ClientFacingLinePrompt } from "../components/StatusChange";
import { STATUSES, STATUS_LABELS, StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Me, Task, WorkStatus, WorkParent, api } from "../lib/api";

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
  const isTenant = !(me.role === "FCC" || me.role === "ECC");
  const board = useBoardDrag({ isTenant, tasks: rows });

  return (
    <>
      <h2>Tasks</h2>
      <p className="sub">
        {me.role === "FCC" || me.role === "ECC"
          ? "Everything your company can see, and everything you have added."
          : "Everything across your goals and projects, filed or not."}
      </p>

      {(me.role === "FCC" || me.role === "ECC")
        ? <PortalCreate me={me} offer={["task"]} />
        : <StaffCreate me={me} offer={["task"]} />}

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
        <>
          {board.error && <Banner kind="bad">{board.error}</Banner>}
          {board.pending && (
            <ClientFacingLinePrompt to={board.pending.to} what={board.pending.task.title}
              onSave={board.confirm} onCancel={board.cancel} />
          )}
          <p className="small muted">
            Drag a card to another column to change its status, or open it — both ask the
            same question and write the same history.
          </p>
          <div className="work-columns" aria-label="Board">
            {STATUSES.map((s) => (
              <div className="col" key={s}
                aria-label={`${STATUS_LABELS[s]} column`}
                onDragOver={board.overColumn(s)}
                onDrop={board.dropOn(s)}
                style={board.hovering === s
                  ? { outline: "2px dashed var(--orange, #F58220)" } : undefined}>
                <h4>{STATUS_LABELS[s]}</h4>
                {rows.filter((t) => t.status === s).map((t) => (
                  <div key={t.id} className="comment"
                    draggable={t.may_edit !== false}
                    onDragStart={board.pickUp(t)} onDragEnd={board.drop}>
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
        </>
      )}
      <p className="small muted">Showing {rows.length} · {when(new Date().toISOString())}</p>
    </>
  );
}

/**
 * Dragging a card between STATUS columns — and nothing else.
 *
 * Not goal, not assignee: those are decisions with more behind them than a
 * column tells you, and a drag is too cheap a gesture to make them with.
 *
 * **A drop goes down exactly the path the task detail page uses**: the same
 * `PATCH /api/tasks/:id/`, the same prompt for the client-facing line, the same
 * skip. That is the point of the feature rather than an implementation detail —
 * a drag that wrote a bare status change would put changelog rows into client
 * digests, which is the failure FR-3.16's prompt exists to prevent. Opening the
 * card stays the alternative path, and the two are now the same path.
 *
 * A client user is not asked for a line (the line is the practice's, FR-3.16),
 * so their drop saves immediately — the same rule `StatusChange` already
 * applies with `askForLine={false}`.
 */
function useBoardDrag({ isTenant, tasks }: { isTenant: boolean; tasks: Task[] }) {
  const qc = useQueryClient();
  const [dragging, setDragging] = useState<Task | null>(null);
  const [hovering, setHovering] = useState<WorkStatus | null>(null);
  const [pending, setPending] = useState<{ task: Task; to: WorkStatus } | null>(null);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: ({ task, to, line }: { task: Task; to: WorkStatus; line: string }) =>
      api.patch<Task>(`/api/tasks/${task.id}/`,
                      { status: to, ...(line ? { client_facing_line: line } : {}) }),
    onSuccess: (_updated, { task }) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["task", task.id] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const clear = () => { setDragging(null); setHovering(null); };

  return {
    hovering, pending, error,
    pickUp: (task: Task) => (event: React.DragEvent) => {
      setError("");
      setDragging(task);
      // Firefox will not start a drag without data on the transfer.
      event.dataTransfer.setData("text/plain", task.id);
      event.dataTransfer.effectAllowed = "move";
    },
    drop: clear,
    overColumn: (status: WorkStatus) => (event: React.DragEvent) => {
      if (!dragging || dragging.status === status) return;
      event.preventDefault();          // Without this the drop never fires.
      event.dataTransfer.dropEffect = "move";
      setHovering(status);
    },
    dropOn: (status: WorkStatus) => (event: React.DragEvent) => {
      event.preventDefault();
      const task = dragging
        ?? tasks.find((t) => t.id === event.dataTransfer.getData("text/plain"));
      clear();
      if (!task || task.status === status) return;   // A drop back home is a no-op.
      if (task.may_edit === false) {
        setError("That task is not yours to change.");
        return;
      }
      if (!isTenant) { save.mutate({ task, to: status, line: "" }); return; }
      setPending({ task, to: status });
    },
    confirm: (line: string) => {
      if (pending) save.mutate({ ...pending, line });
      setPending(null);
    },
    cancel: () => setPending(null),
  };
}
