import { useQuery } from "@tanstack/react-query";
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  CompanyFilter, CompanyGroup, groupByCompany, inCompany, useCompanyFilter,
} from "../components/CompanyFilter";
import { PortalCreate } from "../components/PortalCreate";
import { HierarchyNote, StaffCreate } from "../components/StaffCreate";
import { StatusPill } from "../components/StatusPill";
import { Avatar, PageHead } from "../components/shell";
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
      <PageHead title={isTenant ? "Work" : "Our work"}
        sub={isTenant
          ? "A goal's status is derived from the work underneath it unless someone sets it."
          : "Goals hold projects, projects hold tasks — and a task can stand on its own."} />
      {/* The practice needs the vocabulary; a client already lives in their
          own company's work and is never offered a goal to create. */}
      {isTenant && <HierarchyNote />}

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
  const own = allTasks.filter((t) => t.goal === goal.id
    || projects.some((p) => p.id === t.project));
  const done = own.filter((t) => t.status === "done").length;

  return (
    <li>
      <div className="card goal-card">
        <div className="head" onClick={onToggle} role="button" tabIndex={0}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? "Expand" : "Collapse"} ${goal.title}`}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onToggle(); }}>
          {collapsed ? <ChevronRight size={18} strokeWidth={1.75} />
            : <ChevronDown size={18} strokeWidth={1.75} />}
          <div className="grow">
            <h3><Link to={`/work/goals/${goal.id}`}
              onClick={(e) => e.stopPropagation()}>{goal.title}</Link></h3>
            {/* The measure leads when there is one — the report's rule, on the
                screen the practice reads (FR-4B.18). */}
            {goal.measurable_kind === "numeric" && goal.baseline_value !== null && (
              <p className="measure-line">
                {goal.baseline_value}<span className="to">→</span>
                {goal.target_value ?? "—"}
                {goal.measurable_unit && <span className="unit">{goal.measurable_unit}</span>}
              </p>
            )}
            {goal.measurable && goal.measurable_kind === "numeric" && (
              <p className="tiny muted" style={{ margin: 0 }}>{goal.measurable}</p>
            )}
            {/* Completion is present and subordinate, never the headline. */}
            {collapsed && count > 0 && (
              <p className="tiny muted" style={{ margin: "var(--s1) 0 0" }}>
                {count} item{count === 1 ? "" : "s"} hidden
              </p>
            )}
            {own.length > 0 && (
              <div className="inline tiny muted" style={{ marginTop: "var(--s2)" }}>
                <span className="meter" style={{ width: 160 }}>
                  <span style={{ width: `${Math.round(100 * done / own.length)}%` }} />
                </span>
                {done} of {own.length} done
              </div>
            )}
          </div>
          <div className="right">
            <StatusPill status={goal.status} derived={goal.status_is_derived} />
            {goal.horizon_days && <span className="pill">{goal.horizon_days} days</span>}
            {goal.target_date && <span className="pill">{goal.target_date}</span>}
            <Avatar name={goal.client_owner_contact?.name || goal.owner?.name} />
          </div>
        </div>

        {!collapsed && (count === 0 ? (
          <p className="empty-state">
            Nothing under this goal yet — add a project or a task to start it moving.
          </p>
        ) : (
          <div style={{ marginTop: "var(--s3)" }}>
            {projects.map((p) => {
              const its = allTasks.filter((t) => t.project === p.id);
              const its_done = its.filter((t) => t.status === "done").length;
              return (
                // The project and its tasks are one block, so "which project
                // does this task belong to" is in the markup and not only in
                // the indentation.
                <div key={p.id} className="project-block">
                  <div className="subrow">
                    <span className="grow">
                      <Link to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
                      {p.created_by_client && <span className="pill">client's own</span>}
                    </span>
                    {its.length > 0 && (
                      <span className="meter tiny" style={{ width: 120 }}>
                        <span style={{ width: `${Math.round(100 * its_done / its.length)}%` }} />
                      </span>
                    )}
                    <StatusPill status={p.status} derived={p.status_is_derived} />
                  </div>
                  <TaskLeaves tasks={its} />
                </div>
              );
            })}
            {/* Tasks filed on the goal itself, beside the projects rather than
                under one — the third arrangement FR-3.5 allows. */}
            <TaskLeaves tasks={tasks} />
          </div>
        ))}
      </div>
    </li>
  );
}

function TaskLeaves({ tasks }: { tasks: Task[] }) {
  if (tasks.length === 0) return null;
  return (
    <>
      {tasks.map((t) => (
        <div className="subrow" key={t.id} style={{ paddingLeft: "var(--s6)" }}>
          <span className={`dot status-${t.status}`} aria-hidden="true" />
          <span className="grow"><Link to={`/tasks/${t.id}`}>{t.title}</Link></span>
          {t.due_date && <span className="tiny muted">{t.due_date}</span>}
          <Avatar name={t.assignee.name} />
        </div>
      ))}
    </>
  );
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
