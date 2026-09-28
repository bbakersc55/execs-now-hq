import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Search } from "lucide-react";

import { CompanyFilter, INTERNAL, inCompany, useCompanyFilter } from "../components/CompanyFilter";
import { PortalCreate } from "../components/PortalCreate";
import { StaffCreate } from "../components/StaffCreate";
import { ClientFacingLinePrompt } from "../components/StatusChange";
import { STATUSES, STATUS_LABELS, StatusPill } from "../components/StatusPill";
import { Avatar, Chip, FilterBar, PageHead, useRemembered } from "../components/shell";
import { Banner, when } from "../components/ui";
import { TaskSheet } from "./TaskDetail";
import { Me, PortalPerson, Task, WorkStatus, WorkParent, api } from "../lib/api";

const TENANT = ["FF", "CF", "VA"];

/** FR-3.39 — list and board, both filterable by client, project, assignee and
 *  status. The client filter is the same dimension the Work screen groups by,
 *  and it narrows the two filters below it for the same reason the New task
 *  form does: an option that cannot match anything is worse than no option. */
export function Tasks({ me }: { me: Me }) {
  // Board is the default (design brief, Tier 1), and the choice is remembered
  // in this browser like the company filter beside it.
  const [boardView, setBoardView] = useRemembered("enhq.tasks.board", true);
  const view = boardView ? "board" : "list";
  const { id: openTaskId } = useParams();
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("");
  const [collapsedCols, setCollapsedCols] = useState<string[]>([]);
  const [project, setProject] = useState("");
  const [assignee, setAssignee] = useState("");
  const [status, setStatus] = useState("");
  const { isTenant: staff, clients, company, choose } = useCompanyFilter(me, "tasks-company");

  const query = new URLSearchParams();
  // Filtered by the server, like the three beside it, so the list is never
  // longer than LIST_LIMIT of the wrong company's work.
  if (company) query.set("client_company", company);
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
  const people = useQuery<PortalPerson[]>({
    queryKey: ["portal-people"], queryFn: () => api.get<PortalPerson[]>("/api/portal-people/"),
  });

  // With a client chosen, the pickers below hold only what belongs to them —
  // their projects, and the practice's people plus their own. Internal work
  // offers the practice's people alone, because nobody else can be assigned it.
  const projectOptions = (projects.data ?? []).filter((p) => inCompany(p, company));
  const peopleOptions = (people.data ?? []).filter((p) => !company
    || TENANT.includes(p.role)
    || (company !== INTERNAL && p.company === company));

  // A project or a person belonging to the company just left would otherwise
  // stay set and silently filter the list to nothing.
  const chooseCompany = (next: string) => {
    choose(next);
    setProject("");
    setAssignee("");
  };

  const term = search.trim().toLowerCase();
  const rows = (tasks.data ?? [])
    .filter((t) => !priority || String(t.priority) === priority)
    .filter((t) => !term || t.title.toLowerCase().includes(term));
  const isTenant = !(me.role === "FCC" || me.role === "ECC");
  const anyFilter = !!(company || project || assignee || status || priority || search);
  const board = useBoardDrag({ isTenant, tasks: rows });

  return (
    <>
      <PageHead title="Tasks"
        sub={me.role === "FCC" || me.role === "ECC"
          ? "Everything your company can see, and everything you have added."
          : "Everything across your goals and projects, filed or not."}
        action={(me.role === "FCC" || me.role === "ECC")
          ? <PortalCreate me={me} offer={["task"]} />
          : <StaffCreate me={me} offer={["task"]} />} />

      {/* Chips, not bare dropdowns: what is set reads back as a sentence, and
          each one clears on its own. */}
      <FilterBar onClearAll={anyFilter ? () => {
        chooseCompany(""); setStatus(""); setPriority(""); setSearch("");
      } : undefined}>
        <span className="search">
          <Search size={16} strokeWidth={1.75} />
          <input aria-label="Search tasks" placeholder="Search tasks"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </span>
        {staff && (
          <CompanyFilter value={company} onChange={chooseCompany} companies={clients}
            asChip />
        )}
        <select aria-label="Filter by project" value={project}
          style={{ width: "auto", minWidth: 150 }}
          onChange={(e) => setProject(e.target.value)}>
          <option value="">Any project</option>
          {projectOptions.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
        <select aria-label="Filter by assignee" value={assignee}
          style={{ width: "auto", minWidth: 150 }}
          onChange={(e) => setAssignee(e.target.value)}>
          <option value="">Anyone</option>
          {peopleOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select aria-label="Filter by status" value={status}
          style={{ width: "auto", minWidth: 150 }}
          onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          {STATUSES.map((st) => <option key={st} value={st}>{STATUS_LABELS[st]}</option>)}
        </select>
        <select aria-label="Filter by priority" value={priority}
          style={{ width: "auto", minWidth: 130 }}
          onChange={(e) => setPriority(e.target.value)}>
          <option value="">Any priority</option>
          <option value="3">Urgent</option>
          <option value="2">High</option>
          <option value="1">Normal</option>
          <option value="0">Low</option>
        </select>
        {project && <Chip label={`Project: ${projectOptions.find((p) => p.id === project)?.title ?? "—"}`}
          onClear={() => setProject("")} />}
        {assignee && <Chip label={`Assignee: ${peopleOptions.find((p) => p.id === assignee)?.name ?? "—"}`}
          onClear={() => setAssignee("")} />}
        {status && <Chip label={`Status: ${STATUS_LABELS[status as WorkStatus]}`}
          onClear={() => setStatus("")} />}
        <span style={{ marginLeft: "auto" }} className="row tight">
          <button className={view === "board" ? "small primary" : "small"}
            aria-pressed={view === "board"} onClick={() => setBoardView(true)}>Board</button>
          <button className={view === "list" ? "small primary" : "small"}
            aria-pressed={view === "list"} onClick={() => setBoardView(false)}>List</button>
        </span>
      </FilterBar>

      {board.error && <Banner kind="bad">{board.error}</Banner>}
      {board.pending && (
        <ClientFacingLinePrompt to={board.pending.to} what={board.pending.task.title}
          onSave={board.confirm} onCancel={board.cancel} />
      )}

      {rows.length === 0 ? (
        <div className="empty-state">
          {anyFilter
            ? <>Nothing matches these filters. <button className="link"
                onClick={() => { chooseCompany(""); setStatus(""); setPriority("");
                                 setSearch(""); }}>Clear them</button> to see everything.</>
            : "No tasks yet. Add the first one from the button above."}
        </div>
      ) : view === "board" ? (
        <div className="board" aria-label="Board">
          {STATUSES.map((st) => {
            const inColumn = rows.filter((t) => t.status === st);
            const shut = collapsedCols.includes(st);
            return (
              <div className={shut ? "col collapsed" : "col"} key={st}
                aria-label={`${STATUS_LABELS[st]} column`}
                onDragOver={board.overColumn(st)}
                onDrop={board.dropOn(st)}
                style={board.hovering === st
                  ? { outline: "2px dashed var(--orange)", outlineOffset: 4 } : undefined}>
                <div className="col-head">
                  <button className="icon-button" style={{ minHeight: 24, width: 24 }}
                    aria-label={`${shut ? "Expand" : "Collapse"} ${STATUS_LABELS[st]}`}
                    onClick={() => setCollapsedCols(shut
                      ? collapsedCols.filter((c) => c !== st) : [...collapsedCols, st])}>
                    {shut ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                  </button>
                  <span className={`dot status-${st}`} aria-hidden="true" />
                  <h4 style={{ flex: 1 }}>{STATUS_LABELS[st]}</h4>
                  <span className="count">{inColumn.length}</span>
                </div>
                {!shut && inColumn.map((t) => (
                  <TaskCard key={t.id} task={t} board={board} />
                ))}
                {!shut && inColumn.length === 0 && (
                  <p className="tiny muted" style={{ padding: "var(--s2)" }}>Nothing here.</p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <ListView rows={rows} />
      )}

      {/* The editor is a panel over whatever you were looking at, and it has a
          URL, so a task can be linked and deep-opened (design brief, Tier 1). */}
      {openTaskId && <TaskSheet me={me} id={openTaskId} />}

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


/**
 * A card on the board, Asana-style: a status stripe in the status colour, the
 * title, the chips that are not the default, and who it belongs to. **Nothing
 * else** — the brief is explicit, and a card that carries everything carries
 * nothing.
 */
function TaskCard({ task, board }: { task: Task; board: ReturnType<typeof useBoardDrag> }) {
  const overdue = !!task.due_date && task.due_date < new Date().toISOString().slice(0, 10)
    && task.status !== "done" && task.status !== "cancelled";
  return (
    <div className={`task-card status-${task.status}`}
      draggable={task.may_edit !== false}
      onDragStart={board.pickUp(task)} onDragEnd={board.drop}>
      <Link className="title" to={`/tasks/${task.id}`}>{task.title}</Link>
      {(task.priority > 1 || task.project_title || task.due_date) && (
        <div className="chips">
          {task.priority > 1 && (
            <span className={`pill ${task.priority > 2 ? "prio-urgent" : "prio-high"}`}>
              {task.priority_label}
            </span>
          )}
          {task.project_title && <span className="pill">{task.project_title}</span>}
          {task.due_date && (
            <span className={`pill${overdue ? " bad" : ""}`}>
              {overdue ? "overdue " : "due "}{task.due_date}
            </span>
          )}
        </div>
      )}
      <div className="foot">
        <span className="marks">
          {task.client_owner_contact?.name && (
            <span className="tiny">{task.client_owner_contact.name}</span>
          )}
        </span>
        <Avatar name={task.assignee.name} />
      </div>
    </div>
  );
}

/** The list view: grouped by project, collapsible, sortable. */
function ListView({ rows }: { rows: Task[] }) {
  const [sort, setSort] = useState<"title" | "due_date" | "status">("due_date");
  const groups = new Map<string, Task[]>();
  for (const task of rows) {
    const key = task.project_title || task.goal_title || "Filed under nothing";
    groups.set(key, [...(groups.get(key) ?? []), task]);
  }
  const sorted = (list: Task[]) => [...list].sort((a, b) => {
    if (sort === "title") return a.title.localeCompare(b.title);
    if (sort === "status") return a.status.localeCompare(b.status);
    return (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999");
  });
  const header = (label: string, key: typeof sort) => (
    <th className="sortable" aria-sort={sort === key ? "ascending" : "none"}
      onClick={() => setSort(key)}>{label}{sort === key ? " ↑" : ""}</th>
  );

  return (
    <>
      {[...groups.entries()].map(([name, list]) => (
        <details className="list-group" key={name} open>
          <summary>
            <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />
            {name}
            <span className="count">{list.length}</span>
          </summary>
          <table>
            <thead>
              <tr>
                {header("Task", "title")}
                {header("Status", "status")}
                <th>Assignee</th>
                {header("Due", "due_date")}
                <th>Priority</th>
              </tr>
            </thead>
            <tbody>
              {sorted(list).map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/tasks/${t.id}`}>{t.title}</Link></td>
                  <td><StatusPill status={t.status} /></td>
                  <td><span className="inline"><Avatar name={t.assignee.name} />
                    <span className="muted">{t.assignee.name || "—"}</span></span></td>
                  <td className="muted">{t.due_date ?? "—"}</td>
                  <td>{t.priority > 1
                    ? <span className={`pill ${t.priority > 2 ? "prio-urgent" : "prio-high"}`}>
                        {t.priority_label}</span>
                    : <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </>
  );
}
