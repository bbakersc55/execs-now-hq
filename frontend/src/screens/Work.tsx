import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { PortalCreate } from "../components/PortalCreate";
import { StaffCreate } from "../components/StaffCreate";
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
  const orphanProjects = (projects.data ?? []).filter((p) => !p.goal);

  return (
    <>
      <h2>Work</h2>
      <p className="sub">
        Goals hold projects, projects hold tasks — and a task can stand on its own.
        A goal's status is derived from the work underneath it unless someone sets it.
      </p>

      {isTenant && <StaffCreate me={me} />}
      {isTenant && <ClientActivity />}
      {/* FR-3.35 / 3.35a — a client creates tasks and projects, never goals. */}
      {!isTenant && <PortalCreate me={me} />}

      <Card title="Goals">
        {(goals.data ?? []).length === 0 ? <Empty>No goals yet.</Empty> : (
          <ul className="timeline">
            {goals.data!.map((g) => (
              <li key={g.id}>
                <Link to={`/work/goals/${g.id}`}>{g.title}</Link>{" "}
                <StatusPill status={g.status} derived={g.status_is_derived} />
                <div className="when">
                  {g.client_company_name || "internal"}
                  {g.target_date && ` · target ${g.target_date}`}
                </div>
              </li>
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
