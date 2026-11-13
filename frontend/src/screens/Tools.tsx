import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { Modal, PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { api, Me } from "../lib/api";
import { about } from "../lib/plans";
import {
  CalendarPreview, Evaluation, FIELD_TYPE_LABEL, FieldType, FORMATS, INPUT_TYPES, RowValues,
  RunFull, RunSummary, RunValues, Shelf, ToolDefinition, ToolField, ToolFull,
} from "../lib/tools";

const STAFF = ["FF", "CF", "VA"];
const HORIZONS: [string, string][] = [["quarter", "This quarter"], ["month", "This month"],
  ["year", "This year"], ["week", "This week"], ["picture", "Three-year picture"]];

function when(d: string) {
  return new Date(`${d}T12:00:00`).toLocaleDateString("en-US",
    { month: "long", day: "numeric", year: "numeric" });
}

/** Ask the server to work the values out, a moment after the last change. */
function useEvaluation(definition: ToolDefinition | null, values: RunValues, initial?: Evaluation) {
  const [evaluation, setEvaluation] = useState<Evaluation | undefined>(initial);
  const key = JSON.stringify([definition, values]);
  const first = useRef(true);
  useEffect(() => {
    if (!definition) return undefined;
    if (first.current && initial) { first.current = false; return undefined; }
    const timer = setTimeout(() => {
      api.post<Evaluation>("/api/tools/evaluate/", { definition, values })
        .then(setEvaluation).catch(() => undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return evaluation;
}

// ------------------------------------------------------------------ the form

function Input({ field, value, onChange, label }: {
  field: ToolField; value: unknown; onChange?: (v: unknown) => void; people?: string[];
  label: string;
}) {
  const read = !onChange;
  const text = Array.isArray(value) ? value.join(", ") : value === null || value === undefined
    ? "" : String(value);
  if (read) return <span className="tl-read">{text || "–"}</span>;
  const set = (v: unknown) => onChange!(v);
  switch (field.type) {
    case "long_text":
      return <textarea aria-label={label} rows={field.max_lines ? Math.min(field.max_lines, 5) : 3}
        value={text} onChange={(e) => set(e.target.value)} />;
    case "number": case "money": case "percent":
      return <input className="tl-num" aria-label={label} inputMode="decimal" value={text}
        onChange={(e) => set(e.target.value)} />;
    case "date":
      return <input aria-label={label} type="date" value={text} onChange={(e) => set(e.target.value)} />;
    case "choice":
      return (
        <select aria-label={label} value={text} onChange={(e) => set(e.target.value)}>
          <option value="">–</option>
          {(field.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case "person":
      return <input aria-label={label} list="tl-people" value={text}
        onChange={(e) => set(e.target.value)} />;
    case "people":
      return <input aria-label={label} list="tl-people" value={text} placeholder="Names, with commas"
        onChange={(e) => set(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />;
    default:
      return <input aria-label={label} value={text} onChange={(e) => set(e.target.value)} />;
  }
}

function TableField({ field, rows, cells, onChange, people }: {
  field: ToolField; rows: RowValues[]; cells: Evaluation["tables"][string] | undefined;
  onChange?: (rows: RowValues[]) => void; people: string[];
}) {
  const columns = field.columns ?? [];
  const setCell = (i: number, key: string, v: unknown) =>
    onChange!(rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)));
  return (
    <div className="tl-table-box">
      <table className="tl-table" aria-label={field.label}>
        <thead><tr>
          {onChange && <th title="Flag a row to make a task of it">Flag</th>}
          {columns.map((c) => <th key={c.key} className={c.type === "computed" ? "tl-computed" : ""}>{c.label}</th>)}
          {onChange && <th />}
        </tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={row._flag ? "tl-flagged" : ""}>
              {onChange && <td><input type="checkbox" aria-label={`Flag row ${i + 1} of ${field.label}`}
                checked={!!row._flag} onChange={(e) => setCell(i, "_flag", e.target.checked)} /></td>}
              {columns.map((c) => {
                if (c.type === "computed") {
                  const cell = cells?.[i]?.[c.key];
                  return <td key={c.key} className="tl-computed" title={cell?.error || ""}>
                    {cell?.error ? <span className="tl-error">{cell.error}</span> : cell?.text ?? "–"}</td>;
                }
                return <td key={c.key}><Input field={c} value={row[c.key]} people={people}
                  label={`${c.label}, row ${i + 1}`}
                  onChange={onChange ? (v) => setCell(i, c.key, v) : undefined} /></td>;
              })}
              {onChange && <td><button className="small ghost" aria-label={`Remove row ${i + 1}`}
                onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button></td>}
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={columns.length + 2} className="muted small">No rows yet.</td></tr>}
        </tbody>
      </table>
      {onChange && <button className="small" onClick={() => onChange([...rows, {}])}>Add a row</button>}
    </div>
  );
}

function OrgChart({ rows, name, parent, person }: {
  rows: RowValues[]; name: string; parent: string; person: string;
}) {
  const names = new Set(rows.map((r) => String(r[name] ?? "").trim()).filter(Boolean));
  const kids = (p: string) => rows.filter((r) => String(r[parent] ?? "").trim() === p
    && String(r[name] ?? "").trim());
  const roots = rows.filter((r) => String(r[name] ?? "").trim()
    && !names.has(String(r[parent] ?? "").trim()));
  const node = (r: RowValues, depth: number): ReactNode => {
    const seat = String(r[name] ?? "").trim();
    const who = String(r[person] ?? "").trim();
    const no = ["knows", "wants", "has_time"].some((k) => r[k] === "No");
    return (
      <li key={`${seat}-${depth}`}>
        <div className={`tl-seat${who ? "" : " open"}${no ? " no" : ""}`}>
          <strong>{seat}</strong><span>{who || "Open"}</span>
          {no && <span className="tl-no">A no</span>}
        </div>
        {depth < 8 && kids(seat).length > 0 && <ul>{kids(seat).map((k) => node(k, depth + 1))}</ul>}
      </li>
    );
  };
  return (
    <section className="tl-org" aria-label="The chart">
      <h3>The chart</h3>
      <ul className="tl-tree">{roots.map((r) => node(r, 0))}</ul>
    </section>
  );
}

function Cadence({ rows, agenda }: { rows: RowValues[]; agenda: RowValues[] }) {
  return (
    <section className="tl-cadence" aria-label="The cadence on one page">
      <h3>The cadence</h3>
      <div className="tl-cadence-grid">
        {rows.filter((m) => m.name).map((m, i) => {
          const sections = agenda.filter((a) => String(a.meeting ?? "").trim().toLowerCase()
            === String(m.name).trim().toLowerCase());
          return (
            <div key={i} className="tl-meeting">
              <strong>{String(m.name)}</strong>
              <div className="small muted">{String(m.cadence ?? "")} · {String(m.day ?? "")} {String(m.time ?? "")}
                {" "}· {String(m.minutes ?? "")} min</div>
              {Array.isArray(m.attendees) && m.attendees.length > 0 && (
                <div className="small">{(m.attendees as string[]).join(", ")}</div>)}
              <ol className="small">{sections.map((s, j) => (
                <li key={j}>{String(s.section ?? "")} <span className="muted">({String(s.minutes ?? 0)} min)</span></li>))}</ol>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** A run's worksheet: results first, its views, then its sections. Read
 *  only when `onChange` is not given. */
export function RunForm({ definition, values, evaluation, onChange, people = [] }: {
  definition: ToolDefinition; values: RunValues; evaluation?: Evaluation;
  onChange?: (values: RunValues) => void; people?: string[];
}) {
  const rowsOf = (key: string) => (Array.isArray(values[key]) ? values[key] as RowValues[] : []);
  return (
    <div className="tl-form">
      <datalist id="tl-people">{people.map((p) => <option key={p} value={p} />)}</datalist>
      {(definition.results ?? []).length > 0 && (
        <section className="tl-results" aria-label="Results">
          {(evaluation?.results ?? []).map((r) => (
            <div key={r.key || r.label} className="tl-result">
              <div className="tl-result-label">{r.label}</div>
              <div className="tl-result-value">{r.error ? <span className="tl-error">{r.error}</span> : r.text}</div>
              {r.note && <div className="small muted">{r.note}</div>}
            </div>
          ))}
        </section>
      )}
      {(definition.views ?? []).map((v, i) => v.type === "org_chart" && v.table ? (
        <OrgChart key={i} rows={rowsOf(v.table)} name={v.name ?? "seat"} parent={v.parent ?? "reports_to"}
          person={v.person ?? "person"} />
      ) : v.type === "cadence" && v.table ? (
        <Cadence key={i} rows={rowsOf(v.table)} agenda={rowsOf(v.agenda ?? "agenda")} />
      ) : null)}
      {definition.sections.map((s, si) => (
        <section key={si} className="tl-section" aria-label={s.title}>
          <h3>{s.title}</h3>
          {s.fields.map((f) => f.type === "table" ? (
            <div key={f.key} className="tl-field">
              <div className="tl-label">{f.label}</div>
              <TableField field={f} rows={rowsOf(f.key)} cells={evaluation?.tables[f.key]} people={people}
                onChange={onChange ? (rows) => onChange({ ...values, [f.key]: rows }) : undefined} />
            </div>
          ) : f.type === "computed" ? (
            <div key={f.key} className="tl-field tl-computed-field">
              <span className="tl-label">{f.label}</span>
              {evaluation?.computed[f.key]?.error
                ? <span className="tl-error">{evaluation.computed[f.key].error}</span>
                : <strong>{evaluation?.computed[f.key]?.text ?? "–"}</strong>}
            </div>
          ) : (
            <label key={f.key} className="tl-field">
              <span className="tl-label">{f.label}</span>
              <Input field={f} value={values[f.key]} people={people} label={f.label}
                onChange={onChange ? (v) => onChange({ ...values, [f.key]: v }) : undefined} />
            </label>
          ))}
        </section>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ a run

export function ToolRunScreen({ me }: { me: Me }) {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery<RunFull>({ queryKey: ["tool-run", id],
    queryFn: () => api.get<RunFull>(`/api/tool-runs/${id}/`) });
  const [values, setValues] = useState<RunValues | null>(null);
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const [panel, setPanel] = useState<null | "reading" | "propose" | "import" | "calendar">(null);
  const run = q.data;
  useEffect(() => { if (run && values === null) setValues(run.values); }, [run, values]);
  const evaluation = useEvaluation(run && run.may_edit ? run.definition : null, values ?? {},
    run?.evaluation);
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<RunFull>(`/api/tool-runs/${id}/`, body),
    onSuccess: (r) => { qc.setQueryData(["tool-run", id], r); setNote({ kind: "ok", text: "Saved." }); },
    onError: (e: Error) => setNote({ kind: "bad", text: e.message }),
  });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api.post<Record<string, unknown>>(`/api/tool-runs/${id}/${path}/`, body ?? {}),
  });
  const navigate = useNavigate();
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  if (!run || values === null) return <p>Loading…</p>;
  const edit = run.may_edit;
  const staff = STAFF.includes(me.role ?? "");
  const companyLink = run.company.is_practice ? "/plans/practice" : `/companies/${run.company.id}`;
  const dirty = JSON.stringify(values) !== JSON.stringify(run.values);
  const done = (text: string) => setNote({ kind: "ok", text });
  const failed = (e: unknown) => setNote({ kind: "bad", text: (e as Error).message });
  const file = (kind: string) => `/api/tool-runs/${id}/files/${kind}/`;
  const actions = run.definition.actions ?? [];
  return (
    <div className="tl-page">
      <PageHead title={run.name} crumbs={staff ? [{ to: "/tools", label: "Tools" }] : [{ to: "/tools", label: "Shared with you" }]}
        sub={<>{run.tool_name} · <Link to={staff ? companyLink : "/work"}>{run.company.name}</Link> · {when(run.run_date)}
          {run.shared_with_client && staff && <> · <Pill kind="info">Shared with the client</Pill></>}</>}
        action={edit ? <button className="primary" disabled={!dirty || save.isPending}
          onClick={() => save.mutate({ values })}>{dirty ? "Save" : "Saved"}</button> : undefined} />
      {note && <Banner kind={note.kind}>{note.text}</Banner>}
      <div className="tl-actions row tight" aria-label="What to do with this run">
        <a className="btn small" href={file("pdf")}>PDF</a>
        <a className="btn small" href={file("docx")}>Word</a>
        {edit && <>
          <button className="small" onClick={() => act.mutateAsync({ path: "duplicate" })
            .then((r) => navigate(`/tool-runs/${String(r.id)}`)).catch(failed)}>Duplicate</button>
          <label className="check small"><input type="checkbox" checked={run.shared_with_client}
            onChange={(e) => save.mutate({ shared_with_client: e.target.checked })} /> Show to the
            client owner and senior leadership</label>
          <button className="small" onClick={() => act.mutateAsync({ path: "tasks" }).then((r) =>
            done(`${String(r.made)} tasks made from the flagged rows.`)).catch(failed)}>Tasks from flagged rows</button>
          <button className="small" onClick={() => setPanel("reading")}>Send a result to a KPI</button>
          {!run.company.is_practice && <button className="small" onClick={() => setPanel("propose")}>Propose to the plan</button>}
          <button className="small" onClick={() => act.mutateAsync({ path: "sop-brainstorm" }).then((r) =>
            navigate(`/notes/${String(r.note)}`)).catch(failed)}>Start an SOP brainstorm</button>
          {actions.includes("import_sop") && <button className="small" onClick={() => setPanel("import")}>Import steps from an SOP</button>}
          {actions.includes("calendar") && <button className="small" onClick={() => setPanel("calendar")}>Calendar events</button>}
          {actions.includes("calendar") && <a className="btn small" href={file("agenda")}>Agenda document</a>}
        </>}
      </div>
      <RunForm definition={run.definition} values={values} evaluation={evaluation ?? run.evaluation}
        people={run.choices?.people ?? []} onChange={edit ? setValues : undefined} />
      {panel === "reading" && run.choices && (
        <ReadingPanel run={run} evaluation={evaluation ?? run.evaluation} onClose={() => setPanel(null)}
          onDone={(t) => { setPanel(null); done(t); }} />)}
      {panel === "propose" && <ProposePanel run={run} onClose={() => setPanel(null)}
        onDone={(t) => { setPanel(null); done(t); }} />}
      {panel === "import" && run.choices && <ImportPanel run={run} onClose={() => setPanel(null)}
        onDone={(r, t) => { setPanel(null); setValues(r.values); qc.setQueryData(["tool-run", id], r); done(t); }} />}
      {panel === "calendar" && <CalendarPanel run={run} dirty={dirty} onClose={() => setPanel(null)}
        onDone={(t) => { setPanel(null); done(t); }} />}
    </div>
  );
}

function ReadingPanel({ run, evaluation, onClose, onDone }: {
  run: RunFull; evaluation: Evaluation; onClose: () => void; onDone: (t: string) => void;
}) {
  const numbers = evaluation.results.filter((r) => r.numeric && !r.error);
  const [result, setResult] = useState(numbers[0]?.key ?? "");
  const [kpi, setKpi] = useState(run.choices?.kpis[0]?.id ?? "");
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const send = useMutation({
    mutationFn: () => api.post<{ value: string }>(`/api/tool-runs/${run.id}/reading/`, { result, kpi, day }),
    onSuccess: (r) => onDone(`Sent ${r.value} to the KPI, marked "From a tool".`),
  });
  return (
    <Modal label="Send a result to a KPI" title="Send a result to a KPI" onClose={onClose}>
      {send.isError && <Banner kind="bad">{(send.error as Error).message}</Banner>}
      {numbers.length === 0 || !run.choices?.kpis.length ? <Empty>{numbers.length === 0
        ? "No result here is a number yet." : "This company's scorecard has no KPI to send it to."}</Empty> : (
        <div className="tl-form-grid">
          <label>Result<select value={result} onChange={(e) => setResult(e.target.value)}>
            {numbers.map((r) => <option key={r.key} value={r.key}>{r.label}: {r.text}</option>)}</select></label>
          <label>KPI<select value={kpi} onChange={(e) => setKpi(e.target.value)}>
            {run.choices.kpis.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}</select></label>
          <label>For the period that includes<input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
        </div>)}
      <div className="row tight">
        <button className="primary" disabled={!result || !kpi || send.isPending} onClick={() => send.mutate()}>Send it</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function ProposePanel({ run, onClose, onDone }: { run: RunFull; onClose: () => void; onDone: (t: string) => void }) {
  const [horizon, setHorizon] = useState("quarter");
  const [title, setTitle] = useState("");
  const [doneMeans, setDoneMeans] = useState("");
  const send = useMutation({
    mutationFn: () => api.post(`/api/tool-runs/${run.id}/propose/`, { horizon, title, done_means: doneMeans }),
    onSuccess: () => onDone("Proposed to the plan: it waits in that horizon's tray."),
  });
  return (
    <Modal label="Propose to the plan" title="Propose to the plan" onClose={onClose}>
      {send.isError && <Banner kind="bad">{(send.error as Error).message}</Banner>}
      <div className="tl-form-grid">
        <label>Horizon<select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
          {HORIZONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>Done means<input value={doneMeans} onChange={(e) => setDoneMeans(e.target.value)} /></label>
      </div>
      <div className="row tight">
        <button className="primary" disabled={!title.trim() || send.isPending} onClick={() => send.mutate()}>Propose it</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function ImportPanel({ run, onClose, onDone }: {
  run: RunFull; onClose: () => void; onDone: (r: RunFull, t: string) => void;
}) {
  const sources = run.choices?.sop_sources ?? [];
  const [source, setSource] = useState(sources[0]?.id ?? "");
  const go = useMutation({
    mutationFn: () => api.post<{ imported: number; run: RunFull }>(`/api/tool-runs/${run.id}/import-sop/`, { source }),
    onSuccess: (r) => onDone(r.run, `${r.imported} steps added from the SOP.`),
  });
  return (
    <Modal label="Import steps from an SOP" title="Import steps from an SOP" onClose={onClose}>
      {go.isError && <Banner kind="bad">{(go.error as Error).message}</Banner>}
      {sources.length === 0 ? <Empty>This company has no SOP yet.</Empty> : (
        <label>SOP<select value={source} onChange={(e) => setSource(e.target.value)}>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>)}
      <div className="row tight">
        <button className="primary" disabled={!source || go.isPending} onClick={() => go.mutate()}>Add its steps</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function CalendarPanel({ run, dirty, onClose, onDone }: {
  run: RunFull; dirty: boolean; onClose: () => void; onDone: (t: string) => void;
}) {
  const q = useQuery<CalendarPreview>({ queryKey: ["tool-run-calendar", run.id, run.updated_at],
    queryFn: () => api.get<CalendarPreview>(`/api/tool-runs/${run.id}/files/calendar/`) });
  const make = useMutation({
    mutationFn: () => api.post<{ made: number }>(`/api/tool-runs/${run.id}/calendar/`),
    onSuccess: (r) => onDone(`${r.made} recurring events added to your calendar.`),
  });
  const d = q.data;
  return (
    <Modal label="Calendar events" title="Calendar events" wide onClose={onClose}>
      {dirty && <Banner kind="warn">Save the run first: these are worked out from what is saved.</Banner>}
      {make.isError && <Banner kind="bad">{(make.error as Error).message}</Banner>}
      {d?.demo && <Banner>This is the demo: it never writes to a calendar. These are the events it would make.</Banner>}
      {d && (d.events.length === 0 ? <Empty>No meeting has a day, a time, a length and a first date yet.</Empty> : (
        <table className="tl-table" aria-label="Events it would make">
          <thead><tr><th>Meeting</th><th>Repeats</th><th>First</th><th>Time</th><th>Length</th><th>Who</th></tr></thead>
          <tbody>{d.events.map((e) => (
            <tr key={e.name}><td>{e.name}</td><td>{e.cadence}, {e.day}</td><td>{e.first}</td><td>{e.time}</td>
              <td>{e.minutes} min</td><td className="small">{e.attendees.join(", ")}</td></tr>))}</tbody>
        </table>))}
      <p className="small muted">The app invites nobody: each event names its attendees in its notes.</p>
      <div className="row tight">
        {d && !d.demo && d.connected && <button className="primary" disabled={make.isPending || dirty}
          onClick={() => make.mutate()}>Add them to my calendar</button>}
        <a className="btn" href={`/api/tool-runs/${run.id}/files/ics/`}>Download a calendar file</a>
        <button onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ the shelf

export function ToolsScreen({ me }: { me: Me }) {
  if (!STAFF.includes(me.role ?? "")) return <PortalTools />;
  return <StaffTools />;
}

function StartRun({ tool, onClose }: { tool: { ref: string; name: string }; onClose: () => void }) {
  const navigate = useNavigate();
  const plans = useQuery<{ plans: { id: string; name: string; is_practice: boolean }[] }>({
    queryKey: ["plans"], queryFn: () => api.get("/api/plans/") });
  const { search } = useLocation();
  const preset = new URLSearchParams(search).get("company") ?? "";
  const [company, setCompany] = useState(preset);
  const go = useMutation({
    mutationFn: () => api.post<RunFull>("/api/tool-runs/", { company, tool: tool.ref }),
    onSuccess: (r) => navigate(`/tool-runs/${r.id}`),
  });
  const list = plans.data?.plans ?? [];
  return (
    <Modal label={`Run ${tool.name}`} title={`Run ${tool.name}`} onClose={onClose}>
      {go.isError && <Banner kind="bad">{(go.error as Error).message}</Banner>}
      <label>For<select value={company} onChange={(e) => setCompany(e.target.value)}>
        <option value="">Choose a company</option>
        {list.map((p) => <option key={p.id} value={p.id}>{p.is_practice ? "Our practice" : p.name}</option>)}
      </select></label>
      <div className="row tight">
        <button className="primary" disabled={!company || go.isPending} onClick={() => go.mutate()}>Start the run</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function StaffTools() {
  const q = useQuery<Shelf>({ queryKey: ["tools"], queryFn: () => api.get<Shelf>("/api/tools/") });
  const [running, setRunning] = useState<{ ref: string; name: string } | null>(null);
  const [building, setBuilding] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const dup = useMutation({
    mutationFn: (ref: string) => api.post<ToolFull>(`/api/tools/${ref}/duplicate/`),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["tools"] }); navigate(`/tools/${t.id}/edit`); },
  });
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  const d = q.data;
  if (!d) return <p>Loading…</p>;
  return (
    <div className="tl-page">
      <PageHead title="Tools" sub="Worksheets for a client's operations: run one for a company, save it, share it, act on it."
        action={d.may_build ? <button className="primary" onClick={() => setBuilding(true)}>New tool</button> : undefined} />
      {dup.isError && <Banner kind="bad">{(dup.error as Error).message}</Banner>}
      <div className="tl-shelf">
        {d.tools.map((t) => (
          <div key={t.ref} className="tl-tool-card">
            <strong>{t.name}</strong>
            <p className="small muted">{t.description}</p>
            <div className="row tight">
              <button className="small primary" onClick={() => setRunning(t)}>Run it</button>
              {d.may_build && (t.shipped
                ? <button className="small" onClick={() => dup.mutate(t.ref)}>Duplicate to edit</button>
                : <Link className="btn small" to={`/tools/${t.ref}/edit`}>Edit</Link>)}
              {!t.shipped && <Pill>Our own</Pill>}
            </div>
          </div>
        ))}
      </div>
      <Card title="Recent runs">
        {d.recent.length === 0 ? <Empty>No runs yet.</Empty> : <RunList runs={d.recent} withCompany />}
      </Card>
      {running && <StartRun tool={running} onClose={() => setRunning(null)} />}
      {building && <BuilderModal onClose={() => setBuilding(false)} />}
    </div>
  );
}

export function RunList({ runs, withCompany = false }: { runs: RunSummary[]; withCompany?: boolean }) {
  return (
    <ul className="tl-runs">
      {runs.map((r) => (
        <li key={r.id}><Link to={`/tool-runs/${r.id}`}>{r.name}</Link>
          <span className="small muted"> · {r.tool_name}{withCompany ? ` · ${r.company.is_practice ? "Our practice" : r.company.name}` : ""}
            {" "}· {when(r.run_date)}</span>
          {r.shared_with_client && <> <Pill kind="info">Shared</Pill></>}</li>
      ))}
    </ul>
  );
}

function PortalTools() {
  const q = useQuery<{ runs: RunSummary[] }>({ queryKey: ["tool-runs", "mine"],
    queryFn: () => api.get("/api/tool-runs/?company=mine") });
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  return (
    <div className="tl-page">
      <PageHead title="Shared with you" sub="Worksheets your practice has shared, to read." />
      {!q.data ? <p>Loading…</p> : q.data.runs.length === 0 ? <Empty>Nothing is shared yet.</Empty>
        : <Card><RunList runs={q.data.runs} /></Card>}
    </div>
  );
}

/** The company page's Tools card: its runs, and a run to start. */
export function CompanyToolsCard({ companyId }: { companyId: string }) {
  const q = useQuery<{ runs: RunSummary[]; may_start: boolean }>({ queryKey: ["tool-runs", companyId],
    queryFn: () => api.get(`/api/tool-runs/?company=${companyId}`) });
  const shelf = useQuery<Shelf>({ queryKey: ["tools"], queryFn: () => api.get<Shelf>("/api/tools/") });
  const navigate = useNavigate();
  const [tool, setTool] = useState("");
  const go = useMutation({
    mutationFn: () => api.post<RunFull>("/api/tool-runs/", { company: companyId, tool }),
    onSuccess: (r) => navigate(`/tool-runs/${r.id}`),
  });
  if (q.isError || !q.data) return null;
  return (
    <Card title="Tools">
      {go.isError && <Banner kind="bad">{(go.error as Error).message}</Banner>}
      {q.data.runs.length === 0 ? <p className="small muted">No runs for this company yet.</p>
        : <RunList runs={q.data.runs} />}
      {q.data.may_start && shelf.data && (
        <div className="row tight">
          <select aria-label="Tool to run" value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">Run a tool…</option>
            {shelf.data.tools.map((t) => <option key={t.ref} value={t.ref}>{t.name}</option>)}
          </select>
          <button className="small primary" disabled={!tool || go.isPending} onClick={() => go.mutate()}>Start</button>
        </div>
      )}
    </Card>
  );
}

/** The Operations Command Center's Tools shelf: the tools and recent runs. */
export function ToolsShelfCard() {
  const q = useQuery<Shelf>({ queryKey: ["tools"], queryFn: () => api.get<Shelf>("/api/tools/") });
  if (!q.data) return <Card title="Tools"><p className="small muted">Loading…</p></Card>;
  return (
    <Card title="Tools">
      <ul className="shelf">{q.data.tools.map((t) => <li key={t.ref}>{t.name}{!t.shipped && <span className="muted"> (our own)</span>}</li>)}</ul>
      {q.data.recent.length > 0 && <>
        <div className="small muted">Recent runs</div>
        <RunList runs={q.data.recent.slice(0, 4)} withCompany />
      </>}
      <div className="row tight"><Link className="btn small" to="/tools">Open the tools</Link></div>
    </Card>
  );
}

// ------------------------------------------------------------------ the builder and editor

function BuilderModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const status = useQuery<{ estimate_usd: string; refused: string; used_today: number; cap: number }>({
    queryKey: ["tool-builder"], queryFn: () => api.get("/api/tools/builder/") });
  const [description, setDescription] = useState("");
  const propose = useMutation({
    mutationFn: () => api.post<{ name: string; description: string; definition: ToolDefinition;
      errors: unknown[] }>("/api/tools/builder/", { description }),
    onSuccess: (p) => navigate("/tools/new/edit", { state: { proposal: p } }),
  });
  const s = status.data;
  return (
    <Modal label="New tool" title="New tool" wide onClose={onClose}>
      {propose.isError && <Banner kind="bad">{(propose.error as Error).message}</Banner>}
      <p className="small muted">Say what the worksheet is for: what goes in, what it works out.
        Claude proposes the sections, fields and formulas; you see it with sample values and
        edit everything before it is saved as your practice's own tool.</p>
      <label>The worksheet<textarea rows={5} value={description} onChange={(e) => setDescription(e.target.value)}
        placeholder="For example: track quotes asked for and sent each week by estimator, the share sent within two days, and who is slowest." /></label>
      <div className="row tight">
        {s?.refused ? <Banner kind="warn">{s.refused}</Banner> : (
          <button className="primary" disabled={!s || propose.isPending || description.trim().length < 12}
            onClick={() => propose.mutate()}>{propose.isPending ? "Asking Claude…" : `Propose it with Claude (${about(s?.estimate_usd)})`}</button>)}
        <Link className="btn" to="/tools/new/edit">Start from a blank tool</Link>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

const BLANK: ToolDefinition = { sections: [{ title: "Inputs", fields: [
  { key: "amount", label: "Amount", type: "number" }] }], results: [] };

function useValidation(definition: ToolDefinition) {
  const [errors, setErrors] = useState<{ where: string; message: string }[]>([]);
  const key = JSON.stringify(definition);
  useEffect(() => {
    const timer = setTimeout(() => {
      api.post<{ errors: { where: string; message: string }[] }>("/api/tools/validate/", { definition })
        .then((r) => setErrors(r.errors)).catch(() => undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return errors;
}

function FieldEditor({ field, where, errors, onChange, onRemove, inTable = false }: {
  field: ToolField; where: string; errors: { where: string; message: string }[];
  onChange: (f: ToolField) => void; onRemove: () => void; inTable?: boolean;
}) {
  const mine = errors.filter((e) => e.where === where);
  const types: FieldType[] = inTable ? [...INPUT_TYPES, "computed"] : [...INPUT_TYPES, "table", "computed"];
  const set = (patch: Partial<ToolField>) => onChange({ ...field, ...patch });
  return (
    <div className={`tl-field-editor${mine.length ? " bad" : ""}`}>
      <div className="tl-field-row">
        <label>Label<input value={field.label} onChange={(e) => set({ label: e.target.value })} /></label>
        <label>Key<input value={field.key} onChange={(e) => set({ key: e.target.value })} /></label>
        <label>Type<select value={field.type} onChange={(e) => set({ type: e.target.value as FieldType,
          ...(e.target.value === "table" && !field.columns ? { columns: [{ key: "item", label: "Item", type: "text" }] } : {}) })}>
          {types.map((t) => <option key={t} value={t}>{FIELD_TYPE_LABEL[t]}</option>)}</select></label>
        {field.type === "computed" && <label>Shown as<select value={field.format ?? "number"}
          onChange={(e) => set({ format: e.target.value as ToolField["format"] })}>
          {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>}
        <button className="small ghost" onClick={onRemove} aria-label={`Remove ${field.label || "field"}`}>Remove</button>
      </div>
      {field.type === "choice" && <label>Choices, with commas<input value={(field.options ?? []).join(", ")}
        onChange={(e) => set({ options: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></label>}
      {field.type === "computed" && <label>Formula<input className="tl-formula" aria-label={`Formula for ${field.label}`}
        value={field.formula ?? ""} onChange={(e) => set({ formula: e.target.value })} /></label>}
      {mine.map((e, i) => <div key={i} className="tl-error small">{e.message}</div>)}
      {field.type === "table" && (
        <div className="tl-columns">
          <div className="small muted">Columns</div>
          {(field.columns ?? []).map((c, ci) => (
            <FieldEditor key={ci} field={c} where={`${where}.columns.${ci}`} errors={errors} inTable
              onChange={(nc) => set({ columns: (field.columns ?? []).map((x, j) => (j === ci ? nc : x)) })}
              onRemove={() => set({ columns: (field.columns ?? []).filter((_, j) => j !== ci) })} />
          ))}
          <button className="small" onClick={() => set({ columns: [...(field.columns ?? []),
            { key: `col${(field.columns ?? []).length + 1}`, label: "New column", type: "number" }] })}>Add a column</button>
        </div>
      )}
    </div>
  );
}

export function ToolEditorScreen() {
  const { ref } = useParams<{ ref: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const proposal = (location.state as { proposal?: { name: string; description: string;
    definition: ToolDefinition } } | null)?.proposal;
  const isNew = !ref || ref === "new";
  const q = useQuery<ToolFull>({ queryKey: ["tool", ref], enabled: !isNew,
    queryFn: () => api.get<ToolFull>(`/api/tools/${ref}/`) });
  const [name, setName] = useState(proposal?.name ?? "");
  const [description, setDescription] = useState(proposal?.description ?? "");
  const [definition, setDefinition] = useState<ToolDefinition | null>(isNew ? (proposal?.definition ?? BLANK) : null);
  const [sample, setSample] = useState<RunValues>({});
  useEffect(() => {
    if (q.data && definition === null) {
      setDefinition(q.data.definition); setName(q.data.name); setDescription(q.data.description);
    }
  }, [q.data, definition]);
  const errors = useValidation(definition ?? BLANK);
  const evaluation = useEvaluation(errors.length === 0 ? definition : null, sample);
  const save = useMutation({
    mutationFn: () => isNew
      ? api.post<ToolFull>("/api/tools/", { name, description, definition, from_ai: !!proposal })
      : api.patch<ToolFull>(`/api/tools/${ref}/`, { name, description, definition }),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["tools"] }); navigate(`/tools/${t.id}/edit`, { replace: true }); },
  });
  const def = definition;
  const preview = useMemo(() => def, [def]);
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  if (!def) return <p>Loading…</p>;
  const setSection = (si: number, patch: Partial<ToolDefinition["sections"][number]>) =>
    setDefinition({ ...def, sections: def.sections.map((s, j) => (j === si ? { ...s, ...patch } : s)) });
  const results = def.results ?? [];
  return (
    <div className="tl-page">
      <PageHead title={isNew ? "New tool" : `Edit: ${name}`} crumbs={[{ to: "/tools", label: "Tools" }]}
        sub="Sections and fields, formulas checked as you type, and a preview with sample values."
        action={<button className="primary" disabled={errors.length > 0 || !name.trim() || save.isPending}
          onClick={() => save.mutate()}>Save as our tool</button>} />
      {proposal && <Banner>Claude's proposal. Nothing is saved until you save it.</Banner>}
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {errors.length > 0 && <Banner kind="warn">{errors.length} {errors.length === 1 ? "thing needs" : "things need"} fixing before it saves.</Banner>}
      <div className="tl-editor">
        <div className="tl-editor-form">
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>What it is for<textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          {def.sections.map((s, si) => (
            <fieldset key={si} className="tl-fieldset">
              <legend><input aria-label={`Section ${si + 1} title`} value={s.title}
                onChange={(e) => setSection(si, { title: e.target.value })} /></legend>
              {s.fields.map((f, fi) => (
                <FieldEditor key={fi} field={f} where={`sections.${si}.fields.${fi}`} errors={errors}
                  onChange={(nf) => setSection(si, { fields: s.fields.map((x, j) => (j === fi ? nf : x)) })}
                  onRemove={() => setSection(si, { fields: s.fields.filter((_, j) => j !== fi) })} />
              ))}
              <div className="row tight">
                <button className="small" onClick={() => setSection(si, { fields: [...s.fields,
                  { key: `field${s.fields.length + 1}`, label: "New field", type: "number" }] })}>Add a field</button>
                {def.sections.length > 1 && <button className="small ghost" onClick={() =>
                  setDefinition({ ...def, sections: def.sections.filter((_, j) => j !== si) })}>Remove the section</button>}
              </div>
            </fieldset>
          ))}
          <button className="small" onClick={() => setDefinition({ ...def, sections: [...def.sections,
            { title: "New section", fields: [] }] })}>Add a section</button>
          <fieldset className="tl-fieldset">
            <legend>Result cards</legend>
            {results.map((r, ri) => {
              const mine = errors.filter((e) => e.where === `results.${ri}`);
              const setR = (patch: Partial<typeof r>) => setDefinition({ ...def,
                results: results.map((x, j) => (j === ri ? { ...x, ...patch } : x)) });
              return (
                <div key={ri} className={`tl-field-editor${mine.length ? " bad" : ""}`}>
                  <div className="tl-field-row">
                    <label>Label<input value={r.label} onChange={(e) => setR({ label: e.target.value })} /></label>
                    <label>Key<input value={r.key} onChange={(e) => setR({ key: e.target.value })} /></label>
                    <label>Shown as<select value={r.format ?? "number"} onChange={(e) => setR({ format: e.target.value as typeof r.format })}>
                      {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
                    <button className="small ghost" onClick={() => setDefinition({ ...def,
                      results: results.filter((_, j) => j !== ri) })}>Remove</button>
                  </div>
                  <label>Formula<input className="tl-formula" aria-label={`Formula for ${r.label}`} value={r.formula}
                    onChange={(e) => setR({ formula: e.target.value })} /></label>
                  {mine.map((e, i) => <div key={i} className="tl-error small">{e.message}</div>)}
                </div>
              );
            })}
            <button className="small" onClick={() => setDefinition({ ...def, results: [...results,
              { key: `result${results.length + 1}`, label: "New result", formula: "0" }] })}>Add a result card</button>
          </fieldset>
          {errors.filter((e) => !e.where.startsWith("sections.") || e.where.split(".").length < 4)
            .filter((e) => !e.where.startsWith("results.")).map((e, i) => <div key={i} className="tl-error small">{e.message}</div>)}
          <p className="small muted">Formulas: + - * / ^, comparisons, and, or, not; a field's key; a
            table's column as table.column; sum, average, min, max, count, if, round, abs, sumif,
            countif, argmax, argmin, filter.</p>
        </div>
        <div className="tl-editor-preview" aria-label="Preview with sample values">
          <h3>Preview</h3>
          <p className="small muted">Type sample values to see it work. They are not saved.</p>
          {errors.length === 0 && preview
            ? <RunForm definition={preview} values={sample} evaluation={evaluation} onChange={setSample} />
            : <Empty>Fix what is marked to see the preview.</Empty>}
        </div>
      </div>
    </div>
  );
}
