import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Company, Me, Task, WorkParent, api } from "../lib/api";

const TENANT = ["FF", "CF", "VA"];

/** Goal → Project → Task, three levels and no more (FR-3.4). Goals are the
 *  practice's; a client may create projects and tasks for their own company. */
export function Work({ me }: { me: Me }) {
  const qc = useQueryClient();
  const isTenant = !!me.role && TENANT.includes(me.role);
  const [note, setNote] = useState("");

  const goals = useQuery<WorkParent[]>({
    queryKey: ["goals"], queryFn: () => api.get<WorkParent[]>("/api/goals/"),
  });
  const projects = useQuery<WorkParent[]>({
    queryKey: ["projects"], queryFn: () => api.get<WorkParent[]>("/api/projects/"),
  });
  const unfiled = useQuery<Task[]>({
    queryKey: ["tasks", "unfiled"], queryFn: () => api.get<Task[]>("/api/tasks/?unfiled=1"),
  });
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
    enabled: isTenant,
  });

  const create = useMutation({
    mutationFn: ({ kind, title, company }: { kind: string; title: string; company: string }) =>
      api.post(`/api/${kind}/`, { title, ...(company ? { client_company: company } : {}) }),
    onSuccess: (_d, v) => {
      setNote(`${v.kind === "goals" ? "Goal" : v.kind === "projects" ? "Project" : "Task"} created.`);
      qc.invalidateQueries({ queryKey: [v.kind === "goals" ? "goals" : v.kind === "projects" ? "projects" : "tasks"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const orphanProjects = (projects.data ?? []).filter((p) => !p.goal);

  return (
    <>
      <h2>Work</h2>
      <p className="sub">
        Goals hold projects, projects hold tasks — and a task can stand on its own.
        A goal's status is derived from the work underneath it unless someone sets it.
      </p>
      {note && <Banner kind="info">{note}</Banner>}

      {isTenant && <NewItem companies={companies.data ?? []} onCreate={create.mutate} />}

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

function NewItem({ companies, onCreate }: {
  companies: Company[];
  onCreate: (v: { kind: string; title: string; company: string }) => void;
}) {
  const [kind, setKind] = useState("goals");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");

  return (
    <Card title="Add">
      <div className="row">
        <Field label="What">
          <select aria-label="What to add" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="goals">A goal</option>
            <option value="projects">A project</option>
            <option value="tasks">A task</option>
          </select>
        </Field>
        <Field label="Title">
          <input aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Client company (optional)">
          <select aria-label="Client company" value={company}
            onChange={(e) => setCompany(e.target.value)}>
            <option value="">Internal</option>
            {companies.filter((c) => c.is_client_company).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <button className="primary" disabled={!title.trim()}
          onClick={() => { onCreate({ kind, title: title.trim(), company }); setTitle(""); }}>
          Add
        </button>
      </div>
      <p className="small muted">
        A task with a client company is shown to that client by default; an internal one is not.
      </p>
    </Card>
  );
}
