import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PortalCreate } from "../components/PortalCreate";
import { HierarchyNote, StaffCreate } from "../components/StaffCreate";
import { StatusPill } from "../components/StatusPill";
import { Card, Empty, when } from "../components/ui";
import { Me, Task, TaskUpdateRow, WorkParent, api } from "../lib/api";

const TENANT = ["FF", "CF", "VA"];

/** Goal → Project → Task, three levels and no more (FR-3.4). Goals are the
 *  practice's; a client may create projects and tasks for their own company. */
export function Work({ me }: { me: Me }) {
  const isTenant = !!me.role && TENANT.includes(me.role);

  const goals = useQuery<WorkParent[]>({
    queryKey: ["goals"], queryFn: () => api.get<WorkParent[]>("/api/goals/"),
  });
  const projects = useQuery<WorkParent[]>({
    queryKey: ["projects"], queryFn: () => api.get<WorkParent[]>("/api/projects/"),
  });
  const unfiled = useQuery<Task[]>({
    queryKey: ["tasks", "unfiled"], queryFn: () => api.get<Task[]>("/api/tasks/?unfiled=1"),
  });
  // The whole list, so the tree is built here rather than by a children call
  // per goal. One request either way, and the rows are already cached.
  const tasks = useQuery<Task[]>({
    queryKey: ["tasks", "all"], queryFn: () => api.get<Task[]>("/api/tasks/"),
  });
  const orphanProjects = (projects.data ?? []).filter((p) => !p.goal);
  const [collapsed, toggle] = useCollapsed(me);

  return (
    <>
      <h2>Work</h2>
      {/* The practice needs the vocabulary; a client already lives in their own
          company's work and is never offered a goal to create. */}
      {isTenant ? (
        <>
          <HierarchyNote />
          <p className="sub">
            A goal's status is derived from the work underneath it unless someone sets it.
          </p>
        </>
      ) : (
        <p className="sub">
          Goals hold projects, projects hold tasks — and a task can stand on its own.
        </p>
      )}

      {isTenant && <StaffCreate me={me} />}
      {isTenant && <ClientActivity />}
      {/* FR-3.35 / 3.35a — a client creates tasks and projects, never goals. */}
      {!isTenant && <PortalCreate me={me} />}

      <Card title="Goals">
        {(goals.data ?? []).length === 0 ? <Empty>No goals yet.</Empty> : (
          <ul className="timeline">
            {goals.data!.map((g) => (
              <GoalBranch key={g.id} goal={g}
                projects={(projects.data ?? []).filter((p) => p.goal === g.id)}
                tasks={(tasks.data ?? []).filter((t) => t.goal === g.id && !t.project)}
                allTasks={tasks.data ?? []}
                collapsed={collapsed.includes(g.id)}
                onToggle={() => toggle(g.id)} />
            ))}
          </ul>
        )}
      </Card>

      <Card title="Projects with no goal">
        {orphanProjects.length === 0 ? <Empty>None.</Empty> : (
          <ul className="timeline">
            {orphanProjects.map((p) => (
              <li key={p.id}>
                <Link to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
                <StatusPill status={p.status} derived={p.status_is_derived} />
                {p.created_by_client && <span className="pill">client's own</span>}
                <div className="when">{p.client_company_name || "internal"}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Tasks filed under nothing">
        {(unfiled.data ?? []).length === 0 ? <Empty>None.</Empty> : (
          <ul className="timeline">
            {unfiled.data!.map((t) => (
              <li key={t.id}>
                <Link to={`/tasks/${t.id}`}>{t.title}</Link>{" "}
                <StatusPill status={t.status} />
                <div className="when">
                  {t.assignee.name ? `${t.assignee.name}` : "unassigned"}
                  {t.due_date && ` · due ${t.due_date}`} · {when(t.created_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

/**
 * Which goals this person has collapsed, remembered across visits.
 *
 * Per user, because two people share a browser on the practice's laptop and one
 * collapsing a goal should not collapse it for the other. `localStorage` only:
 * it is a per-viewer convenience, not state the server should carry, and it is
 * wrapped because a private window or blocked site data makes it throw.
 */
function useCollapsed(me: Me): [string[], (id: string) => void] {
  const key = `work-collapsed:${me.email || "anon"}`;
  const [ids, setIds] = useState<string[]>(() => {
    try {
      const saved = window.localStorage.getItem(key);
      return saved ? (JSON.parse(saved) as string[]) : [];
    } catch {
      return [];   // Expanded by default is the right fallback, and the point.
    }
  });
  const toggle = (id: string) => {
    const next = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
    setIds(next);
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* The tree still works; only the memory of it is lost. */
    }
  };
  return [ids, toggle];
}

/** A goal with its projects beneath it and each project's tasks beneath those —
 *  three levels visible at once (FR-3.4's cap is also the display's depth).
 *
 *  Expanded by default: a founder opening "Our work" to check progress should
 *  see the work, not three headings to click through. */
function GoalBranch({ goal, projects, tasks, allTasks, collapsed, onToggle }: {
  goal: WorkParent; projects: WorkParent[]; tasks: Task[]; allTasks: Task[];
  collapsed: boolean; onToggle: () => void;
}) {
  const count = projects.length + tasks.length;
  return (
    <li>
      <button className="ghost small" aria-expanded={!collapsed}
        aria-label={`${collapsed ? "Expand" : "Collapse"} ${goal.title}`}
        onClick={onToggle}>{collapsed ? "▸" : "▾"}</button>{" "}
      <Link to={`/work/goals/${goal.id}`}>{goal.title}</Link>{" "}
      <StatusPill status={goal.status} derived={goal.status_is_derived} />
      <div className="when">
        {goal.client_company_name || "internal"}
        {goal.target_date && ` · target ${goal.target_date}`}
        {collapsed && count > 0 && ` · ${count} item${count === 1 ? "" : "s"} hidden`}
      </div>

      {!collapsed && (count === 0 ? (
        <p className="small muted" style={{ margin: ".3rem 0 .3rem 1.2rem" }}>
          Nothing under this goal yet.
        </p>
      ) : (
        <ul className="timeline" style={{ marginLeft: "1.2rem" }}>
          {projects.map((p) => (
            <li key={p.id}>
              <Link to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
              <StatusPill status={p.status} derived={p.status_is_derived} />
              {p.created_by_client && <span className="pill">client's own</span>}
              <TaskLeaves tasks={allTasks.filter((t) => t.project === p.id)} />
            </li>
          ))}
          {/* Tasks filed on the goal itself, beside the projects rather than
              under one — the third arrangement FR-3.5 allows. */}
          <TaskLeaves tasks={tasks} bare />
        </ul>
      ))}
    </li>
  );
}

function TaskLeaves({ tasks, bare = false }: { tasks: Task[]; bare?: boolean }) {
  if (tasks.length === 0) return null;
  const rows = tasks.map((t) => (
    <li key={t.id}>
      <Link to={`/tasks/${t.id}`}>{t.title}</Link>{" "}
      <StatusPill status={t.status} />
      <div className="when">
        {t.assignee.name || "unassigned"}
        {t.due_date && ` · due ${t.due_date}`}
      </div>
    </li>
  ));
  // `bare` rows already sit in the goal's own list; a project's need their own.
  return bare ? <>{rows}</>
    : <ul className="timeline" style={{ marginLeft: "1.2rem" }}>{rows}</ul>;
}

interface ActivityRow extends TaskUpdateRow { task: string; task_title: string }

/** FR-3.40's in-app half: what clients have done lately, from the same update
 *  rows the digests are built from. The email half is batched separately. */
function ClientActivity() {
  const rows = useQuery<ActivityRow[]>({
    queryKey: ["client-activity"],
    queryFn: () => api.get<ActivityRow[]>("/api/client-activity/"),
  });
  const items = rows.data ?? [];
  if (items.length === 0) return null;

  const said: Record<string, string> = {
    comment_added: "commented on", created: "created",
    status_changed: "changed the status of", completed: "completed",
  };

  return (
    <Card title="What your clients have done">
      <ul className="timeline">
        {items.slice(0, 10).map((row) => (
          <li key={row.id}>
            <div>
              {row.actor.name || "A client user"}{" "}
              {said[row.kind] ?? row.kind.replace(/_/g, " ")}{" "}
              <Link to={`/tasks/${row.task}`}>{row.task_title}</Link>
            </div>
            <div className="when">{when(row.created_at)}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
