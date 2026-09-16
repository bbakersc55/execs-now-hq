import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Company, Contact, Me, PortalPerson, Task, WorkParent, api } from "../lib/api";
import { Banner, Card, Field } from "./ui";

const TENANT_ROLES = ["FF", "CF", "VA"];

const PRIORITIES = [
  { value: 0, label: "Low" },
  { value: 1, label: "Normal" },
  { value: 2, label: "High" },
  { value: 3, label: "Urgent" },
];

type Kind = "task" | "project" | "goal";
type Outcome = { kind: string; text: string; link: string };

/**
 * The practice's own "new" controls, with the whole form.
 *
 * The portal had these and the staff side did not. A fractional could create a
 * task only from inside a goal or project, through a box that sent a title and
 * nothing else — no assignee, due date, priority, steps, client owner or
 * visibility — while a client got a real form on their own Tasks screen. The
 * same went for projects: the client form took a description and a target date,
 * the practice's took a title. The API allowed all of it the whole time; only
 * the screens were missing, so this is a frontend fix.
 *
 * Every picker narrows to the chosen client company, because the server refuses
 * a goal, project or contact that belongs to another, and an offer the server
 * refuses is worse than no offer. With no company the work is internal:
 * internal goals and projects only, the practice's own people to assign to, no
 * client owner, and nothing visible to a client.
 */
export function StaffCreate({ me, offer = ["task", "project", "goal"] }: {
  me: Me; offer?: Kind[];
}) {
  const [open, setOpen] = useState<Kind | null>(null);
  const [done, setDone] = useState<Outcome | null>(null);

  if (!me.role || !TENANT_ROLES.includes(me.role)) return null;

  const close = (outcome: Outcome | null) => {
    setOpen(null);
    if (outcome) setDone(outcome);
  };
  const start = (kind: Kind) => { setOpen(kind); setDone(null); };

  return (
    <>
      <div className="row" style={{ marginBottom: ".8rem" }}>
        {offer.includes("task") && (
          <button className="primary" onClick={() => start("task")}>New task</button>
        )}
        {offer.includes("project") && (
          <button onClick={() => start("project")}>New project</button>
        )}
        {offer.includes("goal") && (
          <button onClick={() => start("goal")}>New goal</button>
        )}
      </div>
      {done && (
        <Banner kind={done.kind}>
          {done.text} <Link to={done.link}>Open it</Link>
        </Banner>
      )}
      {open === "task" && <NewTaskForm onClose={close} />}
      {open === "project" && <NewParentForm kind="project" onClose={close} />}
      {open === "goal" && <NewParentForm kind="goal" onClose={close} />}
    </>
  );
}

/** The lists every form picks from, each narrowed to one client company. */
function useScopedLists(company: string) {
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
  });
  const goals = useQuery<WorkParent[]>({
    queryKey: ["goals"], queryFn: () => api.get<WorkParent[]>("/api/goals/"),
  });
  const projects = useQuery<WorkParent[]>({
    queryKey: ["projects"], queryFn: () => api.get<WorkParent[]>("/api/projects/"),
  });
  const people = useQuery<PortalPerson[]>({
    queryKey: ["portal-people"], queryFn: () => api.get<PortalPerson[]>("/api/portal-people/"),
  });
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  // "" is internal: a goal or project with no client company of its own.
  const ours = (rows: WorkParent[]) => rows.filter((r) => (r.client_company ?? "") === company);
  return {
    clientCompanies: (companies.data ?? []).filter((c) => c.is_client_company),
    goals: ours(goals.data ?? []),
    projects: ours(projects.data ?? []),
    staff: (people.data ?? []).filter((p) => TENANT_ROLES.includes(p.role)),
    theirPeople: company ? (people.data ?? []).filter((p) => p.company === company) : [],
    theirContacts: company ? (contacts.data ?? []).filter((c) => c.company === company) : [],
  };
}

function CompanyField({ value, onChange, companies }: {
  value: string; onChange: (v: string) => void; companies: Company[];
}) {
  return (
    <Field label="Client company (optional)">
      <select aria-label="Client company for the new item" value={value}
        onChange={(e) => onChange(e.target.value)}>
        <option value="">Internal</option>
        {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </Field>
  );
}

function ClientOwnerField({ value, onChange, contacts, company }: {
  value: string; onChange: (v: string) => void; contacts: Contact[]; company: string;
}) {
  return (
    <Field label="Client owner">
      <select aria-label="Client owner for the new item" value={value} disabled={!company}
        onChange={(e) => onChange(e.target.value)}>
        <option value="">{company ? "Nobody yet" : "Pick a company first"}</option>
        {contacts.map((c) => (
          <option key={c.id} value={c.id}>{c.first_name} {c.last_name}</option>
        ))}
      </select>
    </Field>
  );
}

function NewTaskForm({ onClose }: { onClose: (o: Outcome | null) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    title: "", description: "", company: "", goal: "", project: "",
    assignee: "", client_owner_contact: "", due_date: "", priority: 1,
  });
  const [visible, setVisible] = useState(true);
  const [steps, setSteps] = useState<string[]>([]);
  const [step, setStep] = useState("");
  const [error, setError] = useState("");
  const lists = useScopedLists(form.company);
  const projects = lists.projects.filter((p) => !form.goal || p.goal === form.goal);

  // Changing the company invalidates every choice scoped to the old one.
  const setCompany = (company: string) => {
    setForm({ ...form, company, goal: "", project: "", assignee: "", client_owner_contact: "" });
    setVisible(!!company);
  };

  const create = useMutation({
    mutationFn: async () => {
      const task = await api.post<Task>("/api/tasks/", {
        title: form.title.trim(),
        ...(form.description.trim() ? { description: form.description.trim() } : {}),
        ...(form.company ? { client_company: form.company } : {}),
        ...(form.goal ? { goal: form.goal } : {}),
        ...(form.project ? { project: form.project } : {}),
        ...(form.assignee ? { assignee: form.assignee } : {}),
        ...(form.client_owner_contact
          ? { client_owner_contact: form.client_owner_contact } : {}),
        ...(form.due_date ? { due_date: form.due_date } : {}),
        priority: form.priority,
        is_client_visible: !!form.company && visible,
      });
      // Steps go on once the task exists. A step that fails does not undo the
      // task; it is named, so nobody believes it was saved.
      const failed: string[] = [];
      for (const text of steps) {
        try {
          await api.post(`/api/tasks/${task.id}/checklist/`, { text });
        } catch (e) {
          failed.push(`“${text}” (${(e as Error).message})`);
        }
      }
      return { task, failed };
    },
    onSuccess: ({ task, failed }) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      if (task.project) qc.invalidateQueries({ queryKey: ["project", task.project] });
      if (task.goal) qc.invalidateQueries({ queryKey: ["goal", task.goal] });
      const link = `/tasks/${task.id}`;
      onClose(failed.length === 0
        ? { kind: "ok", text: `“${task.title}” created.`, link }
        : { kind: "bad", link,
            text: `“${task.title}” was created, but ${failed.length} step(s) were not added: `
              + `${failed.join("; ")}. Add them on the task.` });
    },
    onError: (e: Error) => setError(e.message),
  });

  const addStep = () => {
    if (!step.trim()) return;
    setSteps([...steps, step.trim()]);
    setStep("");
  };

  return (
    <Card title="New task" actions={<button onClick={() => onClose(null)}>Cancel</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      <form onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Field label="Title">
          <input aria-label="New task title" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label="New task description" rows={2} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>

        <div className="row">
          <CompanyField value={form.company} onChange={setCompany}
            companies={lists.clientCompanies} />
          <Field label="Goal">
            <select aria-label="Goal for the new task" value={form.goal}
              onChange={(e) => setForm({ ...form, goal: e.target.value, project: "" })}>
              <option value="">No goal</option>
              {lists.goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
            </select>
          </Field>
          <Field label="Project">
            <select aria-label="Project for the new task" value={form.project}
              onChange={(e) => setForm({ ...form, project: e.target.value })}>
              <option value="">No project</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </Field>
        </div>

        <div className="row">
          <Field label="Assign to">
            <select aria-label="Assign the new task to" value={form.assignee}
              onChange={(e) => setForm({ ...form, assignee: e.target.value })}>
              <option value="">Unassigned</option>
              <optgroup label="The practice">
                {lists.staff.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </optgroup>
              {lists.theirPeople.length > 0 && (
                <optgroup label="The client">
                  {lists.theirPeople.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              )}
            </select>
          </Field>
          <ClientOwnerField value={form.client_owner_contact} company={form.company}
            contacts={lists.theirContacts}
            onChange={(v) => setForm({ ...form, client_owner_contact: v })} />
          <Field label="Due">
            <input aria-label="Due date for the new task" type="date" value={form.due_date}
              onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
          </Field>
          <Field label="Priority">
            <select aria-label="Priority for the new task" value={form.priority}
              onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}>
              {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
        </div>

        <Field label="Steps">
          {steps.length > 0 && (
            <ul className="small" style={{ paddingLeft: "1.1rem" }}>
              {steps.map((s, i) => (
                <li key={`${i}-${s}`}>
                  {s}{" "}
                  <button type="button" className="ghost small" aria-label={`Remove step ${s}`}
                    onClick={() => setSteps(steps.filter((_, j) => j !== i))}>Remove</button>
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <input aria-label="Add a step to the new task" value={step} placeholder="Add a step…"
              onChange={(e) => setStep(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addStep(); } }} />
            <button type="button" disabled={!step.trim()} onClick={addStep}>Add step</button>
          </div>
        </Field>

        <p className="small">
          <label style={{ display: "inline-flex", gap: ".45rem", alignItems: "center" }}>
            <input type="checkbox" aria-label="Show this task to the client"
              style={{ width: "auto" }} checked={!!form.company && visible}
              disabled={!form.company} onChange={(e) => setVisible(e.target.checked)} />
            Show this task to the client
          </label>
        </p>
        <p className="small muted">
          {form.company
            ? "A task for a client company is shown to them unless you untick that."
            : "An internal task is the practice's own: no client sees it, and only the "
              + "practice's people can be assigned."}
        </p>

        <button className="primary" type="submit" disabled={!form.title.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create task"}
        </button>
      </form>
    </Card>
  );
}

/** Goals and projects differ by two fields, so they share one form: a project
 *  may sit under a goal and carries a start date; a goal does neither. */
function NewParentForm({ kind, onClose }: {
  kind: "goal" | "project"; onClose: (o: Outcome | null) => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    title: "", description: "", company: "", goal: "", client_owner_contact: "",
    start_date: "", target_date: "",
  });
  const [error, setError] = useState("");
  const lists = useScopedLists(form.company);
  const plural = kind === "goal" ? "goals" : "projects";

  const setCompany = (company: string) =>
    setForm({ ...form, company, goal: "", client_owner_contact: "" });

  const create = useMutation({
    mutationFn: () => api.post<WorkParent>(`/api/${plural}/`, {
      title: form.title.trim(),
      ...(form.description.trim() ? { description: form.description.trim() } : {}),
      ...(form.company ? { client_company: form.company } : {}),
      ...(form.client_owner_contact
        ? { client_owner_contact: form.client_owner_contact } : {}),
      ...(form.target_date ? { target_date: form.target_date } : {}),
      ...(kind === "project" && form.goal ? { goal: form.goal } : {}),
      ...(kind === "project" && form.start_date ? { start_date: form.start_date } : {}),
    }),
    onSuccess: (entity) => {
      qc.invalidateQueries({ queryKey: [plural] });
      if (entity.goal) qc.invalidateQueries({ queryKey: ["goal", entity.goal, "children"] });
      onClose({ kind: "ok", text: `“${entity.title}” created.`,
                link: `/work/${plural}/${entity.id}` });
    },
    onError: (e: Error) => setError(e.message),
  });

  const label = kind === "goal" ? "goal" : "project";

  return (
    <Card title={`New ${label}`}
      actions={<button onClick={() => onClose(null)}>Cancel</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      <form onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Field label="Title">
          <input aria-label={`New ${label} title`} value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label={`New ${label} description`} rows={2} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <div className="row">
          <CompanyField value={form.company} onChange={setCompany}
            companies={lists.clientCompanies} />
          {kind === "project" && (
            <Field label="Goal">
              <select aria-label="Goal for the new project" value={form.goal}
                onChange={(e) => setForm({ ...form, goal: e.target.value })}>
                <option value="">No goal</option>
                {lists.goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
              </select>
            </Field>
          )}
          <ClientOwnerField value={form.client_owner_contact} company={form.company}
            contacts={lists.theirContacts}
            onChange={(v) => setForm({ ...form, client_owner_contact: v })} />
          {kind === "project" && (
            <Field label="Start">
              <input aria-label="Start date for the new project" type="date"
                value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            </Field>
          )}
          <Field label="Target date">
            <input aria-label={`Target date for the new ${label}`} type="date"
              value={form.target_date}
              onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
          </Field>
        </div>
        <p className="small muted">
          {kind === "goal"
            ? "A goal holds projects and tasks. Its status is worked out from them unless "
              + "someone sets it by hand."
            : "A project groups tasks, under a goal or on its own."}
        </p>
        <button className="primary" type="submit" disabled={!form.title.trim() || create.isPending}>
          {create.isPending ? "Creating…" : `Create ${label}`}
        </button>
      </form>
    </Card>
  );
}
