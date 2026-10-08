import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";

import { CommentsPanel } from "../components/CommentsPanel";
import { Avatar, PageHead } from "../components/shell";
import { StatusPill } from "../components/StatusPill";
import { Banner, Card, Empty, Pill, when } from "../components/ui";
import {
  EngagementTimeline, GoalBlock, GoalTree, Me, Task, ValueReport, ValueReportExport,
  WorkParent, api,
} from "../lib/api";

const TENANT = ["FF", "CF", "VA"];

/** FF and an assigned CF judge; a VA administers. The server decides — this is
 *  only about which controls to draw, and a refusal still arrives as a banner. */
function mayJudge(me: Me) {
  return me.role === "FF" || me.role === "CF";
}

function isStaff(me: Me) {
  return !!me.role && TENANT.includes(me.role);
}

/**
 * Module 4B — the client value report (FR-4B.1 to FR-4B.44).
 *
 * It replaces FR-3.38's on-demand progress report, which answered *what
 * happened lately*. This answers the question a founder is paying to have
 * answered: **are we getting where we said we were going, and is it working?**
 *
 * Two rules from the spec are visible in this file and are not layout choices:
 * the **headline comes from the server** (`block.headline`), so no screen can
 * decide to lead with a percentage; and **percent-of-tasks-done is always the
 * subordinate line**, in both kinds of goal.
 *
 * **A goal opens in place** (2026-10-07). There is no separate page for one
 * goal: `/report/<goal>` is this report with that goal open, which is also what
 * clicking its title does. Closed, a goal is its headline and how much of its
 * work is done; open, it is everything, down to the tasks.
 */
export function Report({ me }: { me: Me }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const staff = isStaff(me);
  const [company, setCompany] = useState<string>("");
  const [note, setNote] = useState("");

  const companies = useQuery<{ id: string; name: string; is_client_company: boolean }[]>({
    queryKey: ["companies"],
    queryFn: () => api.get("/api/companies/"),
    enabled: staff,
  });
  const clients = (companies.data ?? []).filter((c) => c.is_client_company);
  // A link to one goal names no company, and the practice has several: the
  // goal says whose report to open. A client has one report and needs no answer.
  const linked = useQuery<GoalBlock>({
    queryKey: ["value-report-goal", id],
    queryFn: () => api.get<GoalBlock>(`/api/value-report/${id}/`),
    enabled: staff && !!id && !company,
    retry: false,
  });
  const waitingOnLink = staff && !!id && !company && linked.isLoading;
  const chosen = company || linked.data?.client_company
    || (waitingOnLink ? "" : clients[0]?.id) || "";
  const query = staff ? `?client_company=${chosen}` : "";

  const report = useQuery<ValueReport>({
    queryKey: ["value-report", chosen],
    queryFn: () => api.get<ValueReport>(`/api/value-report/${query}`),
    enabled: !staff || !!chosen,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["value-report"] });
    qc.invalidateQueries({ queryKey: ["value-report-goal"] });
    qc.invalidateQueries({ queryKey: ["goal-tree"] });
  };

  // One goal open at a time, and the address says which: a link to it opens
  // the same report with it open.
  const toggle = (goal: string) => navigate(goal === id ? "/report" : `/report/${goal}`);

  if (staff && clients.length === 0 && !companies.isLoading) {
    return <Empty>No client companies yet. The report is a client artifact.</Empty>;
  }
  if (report.isError) return <Banner kind="bad">{(report.error as Error).message}</Banner>;
  // Also covers the staff case before a company is chosen, when the query has
  // not been enabled yet and there is no data and no error to show.
  if (!report.data) return <p>Building the report…</p>;
  const data = report.data;
  const onReport = !id || [...data.current, ...data.historical].some((b) => b.id === id);

  return (
    <>
      <PageHead title={`Where we are${staff ? ` · ${data.company.name}` : ""}`}
        sub="Per goal: what we set out to change, where the measure stood when we
             started, where it stands now, and what it adds up to." />
      {note && <Banner kind="info">{note}</Banner>}
      {!onReport && (
        <Banner kind="bad">That goal is not on this report. It may have been removed,
          or it is not yours to see.</Banner>
      )}

      {staff && clients.length > 1 && (
        <Card>
          <select aria-label="Client company" value={chosen}
                  onChange={(e) => {
                    setCompany(e.target.value);
                    // The open goal belongs to the company being left.
                    if (id) navigate("/report");
                  }}>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Card>
      )}

      <TimelineCard timeline={data.timeline} />

      {staff && <ExportCard company={chosen} setNote={setNote} />}

      {data.current.length === 0 && data.historical.length === 0 && (
        <Empty>No goals are being tracked for this company yet.</Empty>
      )}
      {data.current.map((block) => (
        <GoalCard key={block.id} block={block} me={me} onChanged={refresh}
                  setNote={setNote} open={block.id === id}
                  onToggle={() => toggle(block.id)} />
      ))}
      {data.historical.length > 0 && (
        <>
          <h3 style={{ marginTop: "1.5rem" }}>Behind us</h3>
          {data.historical.map((block) => (
            <GoalCard key={block.id} block={block} me={me} onChanged={refresh}
                      setNote={setNote} open={block.id === id}
                      onToggle={() => toggle(block.id)} />
          ))}
        </>
      )}
    </>
  );
}

/**
 * FR-4B.36 — one axis across the whole engagement, at the top of the all-goals
 * report and nowhere else. Every mark is a row that already exists.
 */
function TimelineCard({ timeline }: { timeline: EngagementTimeline }) {
  if (timeline.marks.length === 0) return null;
  // One day is not a timeline: an axis would be a single pile of dots at one
  // end. The list says the same thing and can be read.
  const oneDay = new Set(timeline.marks.map((mark) => mark.at.slice(0, 10))).size === 1;
  const list = (
    <ol style={{ listStyle: "none", padding: 0, margin: "var(--s3) 0 0" }}>
      {timeline.marks.map((mark, index) => (
        <li key={`${mark.goal}-${mark.kind}-${index}`} className="timeline-row small">
          <span className="at"><span className="mark-n">{index + 1}</span> {mark.at}</span>
          <span className="which">{mark.goal_title}</span>
          <span>
            {mark.kind === "start" && <>Started</>}
            {mark.kind === "milestone" && <>{mark.label} <Pill>{mark.detail}</Pill></>}
            {mark.kind === "reading" && <>Reading: <strong>{mark.label}</strong>
              {mark.detail && <span className="muted"> — {mark.detail}</span>}</>}
            {mark.kind === "resolution" && <><strong>{mark.label}</strong> — {mark.detail}</>}
          </span>
        </li>
      ))}
    </ol>
  );
  if (oneDay) return <Card title="The engagement, in order">{list}</Card>;
  return (
    <Card title="The engagement, in order">
      <Axis from={timeline.from} to={timeline.to}
        marks={timeline.marks.map((mark) => {
          const label = mark.kind === "start" ? mark.goal_title : mark.label;
          return {
            at: mark.at,
            label,
            // What the dot is, on hover: the mark, whose goal, and when.
            detail: [label, mark.goal_title === label ? "" : mark.goal_title, mark.at,
                     mark.detail].filter(Boolean).join(" · "),
            tone: (mark.kind === "resolution" ? "late"
              : mark.kind === "milestone" ? "hit" : "due") as "hit" | "late" | "due",
          };
        })} />
      {/* The axis shows the shape; the list is where the words are. */}
      <details>
        <summary className="small muted" style={{ cursor: "pointer" }}>
          Every mark, in words
        </summary>
        {list}
      </details>
    </Card>
  );
}

/**
 * One horizontal axis. Every mark is placed by its own date between the two
 * ends, so the gaps mean what they look like they mean.
 *
 * **Nothing overprints** (findings, 2026-09-21; again 2026-10-07, when four
 * goals started on one day and their labels and numbers landed on each other).
 *
 * - Marks that fall on the same spot — the same day, or days too close to tell
 *   apart at this scale — are one **stack**: every dot stays where its date
 *   puts it, and their numbers are stacked beside them. A stack carries no
 *   words; its labels are in the list, which the numbers tie it to.
 * - Stacks and lone marks alternate above and below the line. A lone mark
 *   keeps its label only when both of its neighbours on that side are a full
 *   label's width away; otherwise it leaves its number.
 */
const LABEL_GAP = 15;     // percent of the axis a label needs to itself
const STACK_WITHIN = 3;   // marks closer than this share one stack of numbers

type AxisMark = { at: string; label: string; detail: string; tone: "hit" | "late" | "due" };

/** Where each mark sits and what it shows. Exported for the tests: jsdom lays
 *  nothing out, so "does not overprint" is asserted on these positions. */
export function layAxis(from: string, to: string, marks: AxisMark[]) {
  const start = Date.parse(from);
  const span = Math.max(Date.parse(to) - start, 1);
  const placed = marks
    .map((mark, index) => ({
      ...mark,
      n: index + 1,
      left: Math.min(98, Math.max(2, 100 * (Date.parse(mark.at) - start) / span)),
    }))
    .sort((a, b) => a.left - b.left || a.n - b.n);

  const groups: (typeof placed)[] = [];
  for (const mark of placed) {
    const open = groups.at(-1);
    if (open && mark.left - open[0].left < STACK_WITHIN) open.push(mark);
    else groups.push([mark]);
  }
  return groups.map((members, index) => {
    // The same side of the line is every other group: those are the neighbours
    // a label could land on.
    const clear = [groups[index - 2], groups[index + 2]].every((other) =>
      !other || Math.abs(other[0].left - members[0].left) >= LABEL_GAP);
    return {
      members,
      lane: index % 2 === 0 ? "above" as const : "below" as const,
      left: (members[0].left + members.at(-1)!.left) / 2,
      showLabel: members.length === 1 && clear,
    };
  });
}

/** A label at either end grows inwards from its dot, so it stays on the card
 *  instead of hanging half off the edge. */
function edge(left: number) {
  return left < 8 ? " at-start" : left > 92 ? " at-end" : "";
}

function Axis({ from, to, marks, legend = false }: {
  from: string; to: string; marks: AxisMark[];
  /** List under the axis whatever is shown only as a number. For an axis that
   *  has no list of its own; the engagement timeline has one. */
  legend?: boolean;
}) {
  const groups = layAxis(from, to, marks);
  const numbered = groups.filter((g) => !g.showLabel).flatMap((g) => g.members)
    .sort((a, b) => a.n - b.n);

  return (
    <>
      <div className="axis" role="img"
        aria-label={`${marks.length} marks between ${from} and ${to}`}>
        <span className="line" />
        {groups.map((group) => group.members.length === 1
          ? group.members.map((mark) => (
            <span key={mark.n} className={`mark ${mark.tone} ${group.lane}${edge(mark.left)}`}
              style={{ left: `${mark.left}%` }} title={`${mark.n}. ${mark.detail}`}>
              <span className={group.showLabel ? "lbl" : "lbl n"}>
                {group.showLabel ? mark.label : mark.n}
              </span>
              <i />
            </span>
          ))
          : (
            <span key={`pile-${group.members[0].n}`} style={{ display: "contents" }}>
              {group.members.map((mark) => (
                <span key={mark.n} className={`mark ${mark.tone} ${group.lane}`}
                  style={{ left: `${mark.left}%` }} title={`${mark.n}. ${mark.detail}`}>
                  <i />
                </span>
              ))}
              <span className={`pile ${group.lane}`}
                style={{ left: `${group.left}%`,
                         gridTemplateRows: `repeat(${Math.min(3, group.members.length)}, 14px)` }}>
                {group.members.map((mark) => (
                  <span key={mark.n} className="lbl n" title={mark.detail}>{mark.n}</span>
                ))}
              </span>
            </span>
          ))}
      </div>
      {legend && numbered.length > 0 && (
        <ol className="axis-legend small">
          {numbered.map((mark) => (
            <li key={mark.n}>
              <span className="mark-n">{mark.n}</span> {mark.detail}
              <span className="at muted"> · {mark.at}</span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function ExportCard({ company, setNote }: { company: string; setNote: (s: string) => void }) {
  const qc = useQueryClient();
  const exports = useQuery<ValueReportExport[]>({
    queryKey: ["value-report-exports", company],
    queryFn: () => api.get<ValueReportExport[]>(
      `/api/value-report-exports/?client_company=${company}`),
    enabled: !!company,
  });
  const make = useMutation({
    mutationFn: () => api.post("/api/value-report-exports/", { client_company: company }),
    onSuccess: () => {
      setNote("Exported. It is kept as it reads today — sending it is a separate act.");
      qc.invalidateQueries({ queryKey: ["value-report-exports"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <Card title="The quarterly PDF">
      <p className="small muted">
        A snapshot as it reads today, kept on the goal and the company. Exporting is
        not sending: it reaches a client only as an attachment you approve.
      </p>
      <div className="row">
        <a className="btn ghost" target="_blank" rel="noreferrer"
           href={`/api/value-report/pdf/?client_company=${company}`}>Preview it</a>
        <button className="primary" disabled={make.isPending || !company}
                onClick={() => make.mutate()}>Export and keep it</button>
      </div>
      {(exports.data ?? []).length > 0 && (
        <ul className="small" style={{ marginTop: ".6rem" }}>
          {(exports.data ?? []).slice(0, 8).map((row) => (
            <li key={row.id}>
              <a href={`/api/value-report-exports/${row.id}/file/`} target="_blank"
                 rel="noreferrer">
                {row.scope === "goal" ? row.goal_title : "Every goal"}
              </a>{" "}
              <span className="muted">· {when(row.exported_at)} · {row.exported_by.name}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Measure({ block }: { block: GoalBlock }) {
  const m = block.measure;
  // The headline is already the measurable's name on a numeric goal; repeating
  // it under the figures says the same thing twice.
  const repeats = block.headline.text === m.measurable;
  if (m.kind !== "numeric" || !m.current) {
    return m.how_we_will_know
      ? <p className="small"><span className="muted">How we will know · </span>
          {m.how_we_will_know}</p>
      : null;
  }
  return (
    <div className="measure">
      <p className="figures" style={{ margin: ".2rem 0" }}>
        <span className="muted">{m.baseline.value ?? "—"}</span>
        <span className="muted"> → </span>
        <strong>{m.current.value}</strong>
        {m.target && <><span className="muted"> → </span>{m.target}</>}
        {m.unit && <span className="small muted"> {m.unit}</span>}
        {m.movement && <> <Pill kind={m.movement === "worse" ? "warn" : ""}>
          {m.movement}</Pill></>}
      </p>
      {!repeats && <p className="small muted">{m.measurable}</p>}
      {m.show_chart ? <Sparkline block={block} />
        : <p className="small muted">
            {m.reading_count} of 3 readings — a chart over two points is decoration,
            so this stays as figures until there are three.
          </p>}
      {m.current.note && <p className="small">{m.current.note}</p>}
    </div>
  );
}

/** Inline SVG rather than a charting dependency for one picture. */
function Sparkline({ block }: { block: GoalBlock }) {
  const series = block.measure.series;
  const values = series.map((p) => Number(p.value));
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  const width = 320;
  const height = 60;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - low) / span) * height;
    return { x, y, is_baseline: series[index].is_baseline };
  });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
         role="img" aria-label={`${block.measure.measurable}, ${values.length} readings`}
         style={{ margin: ".3rem 0" }}>
      <polyline fill="none" stroke="var(--blue, #0A3A65)" strokeWidth="2"
                points={points.map((p) => `${p.x},${p.y}`).join(" ")} />
      {points.map((p, index) => (
        <circle key={index} cx={p.x} cy={p.y} r="3"
                fill={p.is_baseline ? "var(--orange, #F58220)" : "var(--blue, #0A3A65)"} />
      ))}
    </svg>
  );
}

/**
 * One goal. Closed: the headline and how much of the work is done. Open:
 * the measure, the milestones, the narrative the practice accepted, how the
 * goal has been resolved, and the projects and tasks under it, where anyone
 * who can see the goal can add a task and comment.
 *
 * Recording a reading and resolving the goal stay the practice's, open or not.
 */
function GoalCard({ block, me, onChanged, setNote, open, onToggle }: {
  block: GoalBlock; me: Me; onChanged: () => void; setNote: (s: string) => void;
  open: boolean; onToggle: () => void;
}) {
  const staff = isStaff(me);
  const card = useRef<HTMLDivElement>(null);
  // A link to this goal lands on it, not at the top of a long report.
  useEffect(() => {
    if (open) card.current?.scrollIntoView({ block: "nearest" });
    // Only when it opens: a refetch must not move the page.
  }, [open]);
  const path = `/api/value-report/${block.id}/`;
  const [value, setValue] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [resolution, setResolution] = useState("achieved");

  const record = useMutation({
    mutationFn: () => api.post("/api/goal-measurements/",
                               { goal: block.id, value }),
    onSuccess: () => { setValue(""); setNote("Reading recorded."); onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });
  const draft = useMutation({
    mutationFn: () => api.post(`${path}draft-narrative/`),
    onSuccess: () => { setNote("Claude drafted it. Nothing is published until you accept.");
                       onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });
  const accept = useMutation({
    mutationFn: () => api.post(`${path}accept-narrative/`, { body }),
    onSuccess: () => { setNote("Published, and kept as a dated version."); onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });
  const resolve = useMutation({
    mutationFn: () => api.post("/api/goal-resolutions/",
                               { goal: block.id, resolution, reason }),
    onSuccess: () => { setReason(""); setNote("Recorded — and it appends, never erases.");
                       onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <div ref={card} id={`goal-${block.id}`}>
    <Card title={
            <button type="button" className="goal-toggle" aria-expanded={open}
                    aria-controls={`goal-${block.id}-body`} onClick={onToggle}>
              {open ? <ChevronDown size={18} aria-hidden="true" />
                    : <ChevronRight size={18} aria-hidden="true" />}
              {block.title}
            </button>
          }
          actions={
            <span className="inline">
              {block.is_historical && <Pill>{block.resolution?.resolution.replace("_", " ")}</Pill>}
              {block.client_owner_contact && <Avatar name={block.client_owner_contact} />}
            </span>
          }>
      {/* The headline is the server's decision, not this screen's — including
          the decision that there is nothing to say, which is what a goal
          converted from a map row starts out as. */}
      {block.headline.text && (
        <p className="headline" style={{ margin: 0 }}>{block.headline.text}</p>
      )}
      {/* Staff only, and the server decides that too: a client is shown the
          goal, not the practice's unfinished admin. */}
      {(block.awaiting ?? []).length > 0 && (
        <p className="small muted" style={{ margin: "var(--s1) 0 0" }}>
          {block.awaiting!.join(" · ")}
        </p>
      )}
      {block.measure.kind_is_undecided && staff && (
        <Banner kind="info">
          Nobody has said how we will know this worked. Choose a number, a sentence,
          or "not measurable" — it is not the same as leaving it blank.
        </Banner>
      )}

      {/* Present, and subordinate. Never the headline (FR-4B.21), and never a
          percentage in words: the bar shows the share, the line says the count. */}
      {block.completion.of > 0 && (
        <div className="goal-progress">
          <div className="meter" role="progressbar" aria-label="Work completed"
               aria-valuemin={0} aria-valuemax={block.completion.of}
               aria-valuenow={block.completion.done}
               aria-valuetext={`${block.completion.done} of ${block.completion.of}`}>
            <span style={{ width: `${100 * block.completion.done / block.completion.of}%` }} />
          </div>
          <span className="small muted">
            Work completed: {block.completion.done} of {block.completion.of}
          </span>
        </div>
      )}

      {open && (
      <div id={`goal-${block.id}-body`}>
      <Measure block={block} />

      {block.narrative?.body && <p className="narrative">{block.narrative.body}</p>}

      {block.milestones.length > 0 && (
        <Axis
          from={block.milestones.map((m) => m.occurred_at ?? m.due_date ?? "")
            .filter(Boolean).sort()[0] ?? ""}
          to={block.milestones.map((m) => m.occurred_at ?? m.due_date ?? "")
            .filter(Boolean).sort().at(-1) ?? ""}
          marks={block.milestones
            .filter((m) => m.occurred_at || m.due_date)
            .map((stone) => ({
              at: (stone.occurred_at ?? stone.due_date)!,
              label: stone.title,
              detail: `${stone.title} · ${stone.state_label}`,
              tone: stone.state === "late" ? "late"
                : stone.state === "due" ? "due" : "hit",
            }))} legend />
      )}

      {block.resolutions.length > 0 && (
        <ul className="timeline" style={{ marginTop: "var(--s3)" }}>
          {block.resolutions.map((row) => (
            <li key={row.id}>
              <strong>{row.label}</strong> — {row.reason}
              <div className="when">{when(row.at)}{row.by ? ` · ${row.by}` : ""}</div>
            </li>
          ))}
        </ul>
      )}

      <GoalWork block={block} me={me} onChanged={onChanged} />

      {staff && (
        <div className="row" style={{ marginTop: ".6rem", gap: ".4rem", flexWrap: "wrap" }}>
          {block.measure.kind === "numeric" && (
            <>
              <input aria-label={`Reading for ${block.title}`} type="number" step="any"
                     placeholder="Today's reading" value={value}
                     onChange={(e) => setValue(e.target.value)} />
              <button disabled={!value || record.isPending}
                      onClick={() => record.mutate()}>Record it</button>
            </>
          )}
          <button className="ghost" disabled={draft.isPending}
                  onClick={() => draft.mutate()}>Draft the narrative with Claude</button>
        </div>
      )}

      {staff && block.narrative?.proposed_body && (
        <div style={{ marginTop: ".5rem" }}>
          <p className="small muted">Claude's draft, not published:</p>
          <p className="small">{block.narrative.proposed_body}</p>
          {mayJudge(me) && (
            <>
              <textarea aria-label={`Narrative for ${block.title}`} rows={3}
                        value={body || block.narrative.proposed_body}
                        onChange={(e) => setBody(e.target.value)} />
              <button className="primary" disabled={accept.isPending}
                      onClick={() => accept.mutate()}>Publish it to the client</button>
            </>
          )}
        </div>
      )}

      {staff && mayJudge(me) && (
        <details style={{ marginTop: ".5rem" }}>
          <summary className="small">Resolve this goal</summary>
          <div className="row" style={{ gap: ".4rem", marginTop: ".4rem" }}>
            <select aria-label={`Resolution for ${block.title}`} value={resolution}
                    onChange={(e) => setResolution(e.target.value)}>
              <option value="achieved">Achieved</option>
              <option value="changed_course">Changed course</option>
              <option value="paused">Paused</option>
              <option value="retired">Retired</option>
              <option value="resumed">Resumed</option>
            </select>
            <input aria-label={`Reason for ${block.title}`} value={reason}
                   placeholder="Why, in one line — the client reads this"
                   onChange={(e) => setReason(e.target.value)} />
            <button disabled={!reason.trim() || resolve.isPending}
                    onClick={() => resolve.mutate()}>Record the resolution</button>
          </div>
        </details>
      )}

      <div style={{ marginTop: "var(--s4)" }}>
        <CommentsPanel me={me} target="goal" id={block.id} />
      </div>
      </div>
      )}
    </Card>
    </div>
  );
}

function TaskLine({ task }: { task: Task }) {
  return (
    <li>
      <Link className="rowname" to={`/tasks/${task.id}`}>{task.title}</Link>{" "}
      <StatusPill status={task.status} />
      <span className="when">
        {" "}{task.assignee.name || "unassigned"}{task.due_date && ` · due ${task.due_date}`}
      </span>
    </li>
  );
}

/**
 * The projects and tasks under a goal, with their status, and two boxes: add
 * a task (on the goal itself or under one of its projects) and add a project. Asked for only when
 * the goal is opened, so a long report does not fetch every goal's work.
 */
function GoalWork({ block, me, onChanged }: {
  block: GoalBlock; me: Me; onChanged: () => void;
}) {
  const qc = useQueryClient();
  const staff = isStaff(me);
  const [title, setTitle] = useState("");
  const [under, setUnder] = useState("");
  const [project, setProject] = useState("");
  const [error, setError] = useState("");

  const tree = useQuery<GoalTree>({
    queryKey: ["goal-tree", block.id],
    queryFn: () => api.get<GoalTree>(`/api/goals/${block.id}/tree/`),
  });
  // The server sets a client's company itself, so only the practice sends one.
  const company = staff && block.client_company ? { client_company: block.client_company } : {};
  const added = () => {
    setError("");
    qc.invalidateQueries({ queryKey: ["goal-tree", block.id] });
    qc.invalidateQueries({ queryKey: ["tasks"] });
    qc.invalidateQueries({ queryKey: ["projects"] });
    onChanged();
  };
  const addTask = useMutation({
    mutationFn: () => api.post<Task>("/api/tasks/", {
      title: title.trim(), ...(under ? { project: under } : { goal: block.id }), ...company,
    }),
    onSuccess: () => { setTitle(""); added(); },
    onError: (e: Error) => setError(e.message),
  });
  const addProject = useMutation({
    mutationFn: () => api.post<WorkParent>("/api/projects/", {
      title: project.trim(), goal: block.id, ...company,
    }),
    onSuccess: () => { setProject(""); added(); },
    onError: (e: Error) => setError(e.message),
  });

  const projects = tree.data?.projects ?? [];
  const direct = tree.data?.tasks ?? [];
  return (
    <section className="goal-work" aria-label={`Work under ${block.title}`}>
      <h4>The work under this goal</h4>
      {error && <Banner kind="bad">{error}</Banner>}
      {tree.isError && <Banner kind="bad">{(tree.error as Error).message}</Banner>}
      {tree.isLoading && <p className="small muted">Loading the work…</p>}
      {tree.data && projects.length === 0 && direct.length === 0 && (
        <Empty>Nothing has been filed under this goal yet.</Empty>
      )}
      {projects.map((p) => (
        <div key={p.id} className="goal-project">
          <p style={{ margin: 0 }}>
            <Link className="rowname" to={`/work/projects/${p.id}`}>{p.title}</Link>{" "}
            <StatusPill status={p.status} derived={p.status_is_derived} />
          </p>
          {p.tasks.length === 0
            ? <p className="small muted" style={{ margin: 0 }}>No tasks yet.</p>
            : <ul>{p.tasks.map((t) => <TaskLine key={t.id} task={t} />)}</ul>}
        </div>
      ))}
      {direct.length > 0 && (
        <div className="goal-project">
          {projects.length > 0 && <p className="small muted" style={{ margin: 0 }}>
            Filed straight on the goal</p>}
          <ul>{direct.map((t) => <TaskLine key={t.id} task={t} />)}</ul>
        </div>
      )}

      <form className="row tight" style={{ marginTop: "var(--s3)", flexWrap: "wrap" }}
            onSubmit={(e) => { e.preventDefault(); if (title.trim()) addTask.mutate(); }}>
        <input aria-label={`New task under ${block.title}`} placeholder="Add a task"
               style={{ flex: "1 1 240px", width: "auto" }}
               value={title} onChange={(e) => setTitle(e.target.value)} />
        {projects.length > 0 && (
          <select aria-label="File the task under" value={under} style={{ width: "auto" }}
                  onChange={(e) => setUnder(e.target.value)}>
            <option value="">On the goal itself</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        )}
        <button type="submit" disabled={!title.trim() || addTask.isPending}>Add task</button>
      </form>
      {/* A client too (owner, 2026-10-07): a project under a goal of their own
          company. Goals themselves stay the practice's. */}
      <form className="row tight" style={{ marginTop: "var(--s2)" }}
            onSubmit={(e) => { e.preventDefault(); if (project.trim()) addProject.mutate(); }}>
        <input aria-label={`New project under ${block.title}`} placeholder="Add a project"
               style={{ flex: "1 1 240px", width: "auto" }} value={project}
               onChange={(e) => setProject(e.target.value)} />
        <button type="submit" disabled={!project.trim() || addProject.isPending}>
          Add project</button>
      </form>
    </section>
  );
}
