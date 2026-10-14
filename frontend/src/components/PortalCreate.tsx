import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ClientTeamName, Me, PortalPerson, Task, WorkParent, api } from "../lib/api";
import { usePracticeName } from "../lib/branding";
import { Banner, Card, Field } from "./ui";

type Outcome = { kind: string; text: string; link: string };

/**
 * FR-3.35 / FR-3.35a — the portal's own "new" controls.
 *
 * The API always let a client create tasks and projects; the portal never
 * offered a way to, so Our work and Tasks were lists that could only be read.
 * Everything here is the client's own company: the server scopes the project
 * and people lists, and these forms filter them again so a stale or wider
 * response still cannot offer what FR-3.9a.2 would refuse.
 *
 * P7 phase 4: "New" offers only what this person may create (§3), asks which
 * team when they may put work on more than one (§1.2), and offers as the
 * assignee only someone the task's team may be handed to.
 */
type Kind = "task" | "project" | "goal";

export function PortalCreate({ me, offer = ["task", "project"] }: {
  me: Me; offer?: Kind[];
}) {
  const [open, setOpen] = useState<Kind | null>(null);
  const [done, setDone] = useState<Outcome | null>(null);
  const close = (outcome: Outcome | null) => {
    setOpen(null);
    if (outcome) setDone(outcome);
  };

  // Without the server's word (an older answer), tasks and projects as before.
  const may = me.portal?.may_create ?? { task: true, project: true, goal: false };
  offer = offer.filter((kind) => may[kind]);
  if (offer.length === 0 && !done) return null;

  return (
    <>
      <div className="row" style={{ marginBottom: ".8rem" }}>
        {offer.includes("task") && (
          <button className="primary" onClick={() => { setOpen("task"); setDone(null); }}>
            New task
          </button>
        )}
        {offer.includes("project") && (
          <button onClick={() => { setOpen("project"); setDone(null); }}>New project</button>
        )}
        {offer.includes("goal") && (
          <button onClick={() => { setOpen("goal"); setDone(null); }}>New goal</button>
        )}
      </div>
      {done && (
        <Banner kind={done.kind}>
          {done.text} <Link to={done.link}>Open it</Link>
        </Banner>
      )}
      {open === "task" && <NewTaskForm me={me} onClose={close} />}
      {open === "project" && <NewProjectForm me={me} onClose={close} />}
      {open === "goal" && <NewGoalForm onClose={close} />}
    </>
  );
}

/** The teams this person may put new work on, and the one it lands on when
 *  they name none: the default team if they are on it, else the first. */
function useTeams(me: Me) {
  const teams: ClientTeamName[] = me.portal?.teams ?? [];
  const home = teams.find((t) => t.is_default)?.id ?? teams[0]?.id ?? "";
  return { teams, home };
}

function TeamPicker({ teams, value, onChange, label }: {
  teams: ClientTeamName[]; value: string; onChange: (team: string) => void; label: string;
}) {
  if (teams.length < 2) return null;
  return (
    <Field label="Team">
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
    </Field>
  );
}

/** Who a task on this team may be handed to (the server's answer). */
export function usePeopleFor(team: string | null | undefined, enabled = true) {
  return useQuery<PortalPerson[]>({
    queryKey: ["portal-people", team || ""],
    queryFn: () => api.get<PortalPerson[]>(
      `/api/portal-people/${team ? `?team=${team}` : ""}`),
    enabled,
  });
}

function NewTaskForm({ me, onClose }: { me: Me; onClose: (o: Outcome | null) => void }) {
  const qc = useQueryClient();
  const practice = usePracticeName();
  const { teams, home } = useTeams(me);
  const [form, setForm] = useState({ title: "", project: "", assignee: "", due_date: "",
                                     team: home });
  const [steps, setSteps] = useState<string[]>([]);
  const [step, setStep] = useState("");
  const [error, setError] = useState("");

  const projects = useQuery<WorkParent[]>({
    queryKey: ["projects"], queryFn: () => api.get<WorkParent[]>("/api/projects/"),
  });
  const ourProjects = (projects.data ?? []).filter((p) => p.client_company === me.client_company);
  // In a project the task is on the project's team; otherwise on the one chosen.
  const team = form.project
    ? ourProjects.find((p) => p.id === form.project)?.client_team ?? ""
    : form.team;
  const people = usePeopleFor(team);
  const colleagues = (people.data ?? []).filter((p) => p.company === me.client_company);

  const create = useMutation({
    mutationFn: async () => {
      const task = await api.post<Task>("/api/tasks/", {
        title: form.title.trim(),
        ...(form.project ? { project: form.project } : {}),
        ...(!form.project && form.team ? { client_team: form.team } : {}),
        ...(form.assignee ? { assignee: form.assignee } : {}),
        ...(form.due_date ? { due_date: form.due_date } : {}),
      });
      // Steps are added to the task once it exists. A step that fails does not
      // undo the task; it is named, so nobody believes it was saved.
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
      qc.invalidateQueries({ queryKey: ["projects"] });
      if (task.project) qc.invalidateQueries({ queryKey: ["project", task.project] });
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
        <div className="row">
          <Field label="Project">
            <select aria-label="Project for the new task" value={form.project}
              onChange={(e) => setForm({ ...form, project: e.target.value, assignee: "" })}>
              <option value="">No project</option>
              {ourProjects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </Field>
          {!form.project && (
            <TeamPicker teams={teams} value={form.team} label="Team for the new task"
              onChange={(next) => setForm({ ...form, team: next, assignee: "" })} />
          )}
          <Field label="Assign to">
            <select aria-label="Assign the new task to" value={form.assignee}
              onChange={(e) => setForm({ ...form, assignee: e.target.value })}>
              <option value="">Unassigned</option>
              {colleagues.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="Due">
            <input aria-label="Due date for the new task" type="date" value={form.due_date}
              onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
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

        <p className="small muted">
          You can assign it to anyone on its team. It is shown to {practice} straight away.
        </p>
        <button className="primary" type="submit" disabled={!form.title.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create task"}
        </button>
      </form>
    </Card>
  );
}

function NewProjectForm({ me, onClose }: { me: Me; onClose: (o: Outcome | null) => void }) {
  const qc = useQueryClient();
  const practice = usePracticeName();
  const { teams, home } = useTeams(me);
  const [form, setForm] = useState({ title: "", description: "", target_date: "", team: home });
  const [error, setError] = useState("");

  const create = useMutation({
    // FR-3.35a — never under a goal: there is no goal field to send.
    mutationFn: () => api.post<WorkParent>("/api/projects/", {
      title: form.title.trim(),
      ...(form.description.trim() ? { description: form.description.trim() } : {}),
      ...(form.target_date ? { target_date: form.target_date } : {}),
      ...(form.team ? { client_team: form.team } : {}),
    }),
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      onClose({ kind: "ok", text: `“${project.title}” created.`, link: `/work/projects/${project.id}` });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card title="New project" actions={<button onClick={() => onClose(null)}>Cancel</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      <form onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Field label="Title">
          <input aria-label="New project title" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label="New project description" rows={2} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <div className="row">
          <Field label="Target date">
            <input aria-label="Target date for the new project" type="date"
              value={form.target_date}
              onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
          </Field>
          <TeamPicker teams={teams} value={form.team} label="Team for the new project"
            onChange={(next) => setForm({ ...form, team: next })} />
        </div>
        <p className="small muted">
          A project groups your company's own tasks. Goals are set with {practice}, so a
          project you add stands on its own rather than under a goal.
        </p>
        <button className="primary" type="submit" disabled={!form.title.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create project"}
        </button>
      </form>
    </Card>
  );
}


/** P7-7: a client user given "Goals too" adds a goal for their company. It is
 *  live at once, marked as theirs, and the practice is told. Its measure and
 *  its outcome stay the practice's to set. */
function NewGoalForm({ onClose }: { onClose: (o: Outcome | null) => void }) {
  const qc = useQueryClient();
  const practice = usePracticeName();
  const [form, setForm] = useState({ title: "", description: "", target_date: "" });
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: () => api.post<WorkParent>("/api/goals/", {
      title: form.title.trim(),
      ...(form.description.trim() ? { description: form.description.trim() } : {}),
      ...(form.target_date ? { target_date: form.target_date } : {}),
    }),
    onSuccess: (goal) => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      onClose({ kind: "ok", text: `“${goal.title}” added.`, link: `/work/goals/${goal.id}` });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card title="New goal" actions={<button onClick={() => onClose(null)}>Cancel</button>}>
      {error && <Banner kind="bad">{error}</Banner>}
      <form onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Field label="Title">
          <input aria-label="New goal title" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label="New goal description" rows={2} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label="Target date">
          <input aria-label="Target date for the new goal" type="date" value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
        </Field>
        <p className="small muted">
          It is your company's goal straight away, marked as added by you, and {practice} is
          told. How it is measured is set with {practice}.
        </p>
        <button className="primary" type="submit" disabled={!form.title.trim() || create.isPending}>
          {create.isPending ? "Adding…" : "Add the goal"}
        </button>
      </form>
    </Card>
  );
}
