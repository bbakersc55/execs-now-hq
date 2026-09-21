import { useQuery } from "@tanstack/react-query";
import { ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  CompanyFilter, CompanyGroup, groupByCompany, inCompany, useCompanyFilter,
} from "../components/CompanyFilter";
import { PortalCreate } from "../components/PortalCreate";
import { HierarchyNote, StaffCreate } from "../components/StaffCreate";
import { StatusPill } from "../components/StatusPill";
import { Card, Empty, when } from "../components/ui";
import { Me, Task, TaskUpdateRow, WorkParent, api } from "../lib/api";
import { useRemembered } from "../lib/remembered";

const TENANT = ["FF", "CF", "VA"];

/** Goal → Project → Task, three levels and no more (FR-3.4). Goals are the
 *  practice's; a client may create projects and tasks for their own company.
 *
 *  For the practice the screen carries a second dimension: whose work it is.
 *  A fractional runs several accounts at once, and an undifferentiated list of
 *  goals asks them to remember which client each one belongs to (FR-3.39a). */
export function Work({ me }: { me: Me }) {
  const isTenant = !!me.role && TENANT.includes(me.role);
  const { clients, company, choose } = useCompanyFilter(me, "work-company");

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

  // Narrowing and grouping are the same question asked twice: which company's
  // work is this. Both go through `inCompany`, so a row can never be filtered
  // into one group and out of another.
  const mine = <T extends { client_company: string | null }>(rows: T[]) =>
    rows.filter((r) => inCompany(r, company));

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

      {/* One selector above all three lists, because it governs all three. */}
      {isTenant && (
        <Card>
          <div className="row">
            <CompanyFilter value={company} onChange={choose} companies={clients} />
          </div>
        </Card>
      )}

      <Card title="Goals">
        <Grouped rows={mine(goals.data ?? [])} headings={isTenant}
          empty={company ? "No goals for this client yet." : "No goals yet."}
          render={(g) => (
            <GoalBranch key={g.id} goal={g}
              projects={(projects.data ?? []).filter((p) => p.goal === g.id)}
              tasks={(tasks.data ?? []).filter((t) => t.goal === g.id && !t.project)}
              allTasks={tasks.data ?? []}
              collapsed={collapsed.includes(g.id)}
              onToggle={() => toggle(g.id)} />
          )} />
      </Card>

      {/* Unfiled work groups the same way — it is where work that belongs to
          nothing lives, and it belongs to a client all the same. */}
      <Card title="Projects with no goal">
        <Grouped rows={mine(orphanProjects)} headings={isTenant} empty="None."
          render={(p) => (
            <li key={p.id}>
              <Link to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
              <StatusPill status={p.status} derived={p.status_is_derived} />
              {p.created_by_client && <span className="pill">client's own</span>}
              <div className="when">{p.client_company_name || "internal"}</div>
            </li>
          )} />
      </Card>

      <Card title="Tasks filed under nothing">
        <Grouped rows={mine(unfiled.data ?? [])} headings={isTenant} empty="None."
          render={(t) => (
            <li key={t.id}>
              <Link to={`/tasks/${t.id}`}>{t.title}</Link>{" "}
              <StatusPill status={t.status} />
              <div className="when">
                {t.assignee.name ? `${t.assignee.name}` : "unassigned"}
                {t.due_date && ` · due ${t.due_date}`} · {when(t.created_at)}
              </div>
            </li>
          )} />
      </Card>
    </>
  );
}

/**
 * One list per client company, each under its own heading.
 *
 * `headings` is off in the portal: a client's rows all belong to their one
 * company, so the grouping collapses to the single flat list the portal already
 * showed and the heading would only name what they already know.
 */
function Grouped<T extends { client_company: string | null; client_company_name: string }>(
  { rows, headings, empty, render }: {
    rows: T[]; headings: boolean; empty: string; render: (row: T) => ReactNode;
  },
) {
  const groups: CompanyGroup<T>[] = groupByCompany(rows);
  if (groups.length === 0) return <Empty>{empty}</Empty>;
  return (
    <>
      {groups.map((group) => (
        <div key={group.key}>
          {headings && (
            <h4 style={{ margin: "1rem 0 .3rem" }}>{group.label}</h4>
          )}
          <ul className="work-tree">{group.rows.map(render)}</ul>
        </div>
      ))}
    </>
  );
}

/**
 * Which goals this person has collapsed, remembered across visits.
 *
 * Per user, because two people share a browser on the practice's laptop and one
 * collapsing a goal should not collapse it for the other.
 */
function useCollapsed(me: Me): [string[], (id: string) => void] {
  const [ids, setIds] = useRemembered<string[]>(`work-collapsed:${me.email || "anon"}`, []);
  const toggle = (id: string) =>
    setIds(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
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
      <ul className="work-tree">
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
