import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import {
  EngagementTimeline, GoalBlock, Me, ValueReport, ValueReportExport, api,
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
 */
export function Report({ me }: { me: Me }) {
  const { id } = useParams();
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
  const chosen = company || clients[0]?.id || "";
  const query = staff ? `?client_company=${chosen}` : "";

  const report = useQuery<ValueReport>({
    queryKey: ["value-report", chosen],
    queryFn: () => api.get<ValueReport>(`/api/value-report/${query}`),
    enabled: !staff || !!chosen,
  });
  const single = useQuery<GoalBlock>({
    queryKey: ["value-report-goal", id],
    queryFn: () => api.get<GoalBlock>(`/api/value-report/${id}/`),
    enabled: !!id,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["value-report"] });
    qc.invalidateQueries({ queryKey: ["value-report-goal"] });
  };

  if (id) {
    if (single.isError) return <Banner kind="bad">{(single.error as Error).message}</Banner>;
    if (!single.data) return <p>Opening the goal…</p>;
    return (
      <>
        <h2>{single.data.title}</h2>
        {note && <Banner kind="info">{note}</Banner>}
        <GoalCard block={single.data} me={me} onChanged={refresh} setNote={setNote} />
      </>
    );
  }

  if (staff && clients.length === 0 && !companies.isLoading) {
    return <Empty>No client companies yet. The report is a client artifact.</Empty>;
  }
  if (report.isError) return <Banner kind="bad">{(report.error as Error).message}</Banner>;
  // Also covers the staff case before a company is chosen, when the query has
  // not been enabled yet and there is no data and no error to show.
  if (!report.data) return <p>Building the report…</p>;
  const data = report.data;

  return (
    <>
      <h2>Where we are{staff ? ` · ${data.company.name}` : ""}</h2>
      <p className="sub">
        Per goal: what we set out to change, where the measure stood when we started,
        where it stands now, and what it adds up to. Opening this sends nothing.
      </p>
      {note && <Banner kind="info">{note}</Banner>}

      {staff && clients.length > 1 && (
        <Card>
          <select aria-label="Client company" value={chosen}
                  onChange={(e) => setCompany(e.target.value)}>
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
                  setNote={setNote} />
      ))}
      {data.historical.length > 0 && (
        <>
          <h3 style={{ marginTop: "1.5rem" }}>Behind us</h3>
          {data.historical.map((block) => (
            <GoalCard key={block.id} block={block} me={me} onChanged={refresh}
                      setNote={setNote} />
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
  return (
    <Card title="The engagement, in order">
      <p className="small muted">{timeline.from} to {timeline.to}</p>
      <ol className="timeline" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {timeline.marks.map((mark, index) => (
          <li key={`${mark.goal}-${mark.kind}-${index}`}
              style={{ display: "flex", gap: ".6rem", padding: ".25rem 0",
                       borderBottom: "1px solid var(--line, #eee)" }}>
            <span className="small muted" style={{ minWidth: "6.5rem" }}>{mark.at}</span>
            <span className="small" style={{ minWidth: "10rem", color: "var(--blue)" }}>
              {mark.goal_title}
            </span>
            <span className="small">
              {mark.kind === "start" && <>Started</>}
              {mark.kind === "milestone" && <>{mark.label} <Pill>{mark.detail}</Pill></>}
              {mark.kind === "reading" && <>Reading: <strong>{mark.label}</strong>
                {mark.detail && <span className="muted"> — {mark.detail}</span>}</>}
              {mark.kind === "resolution" && <><strong>{mark.label}</strong> — {mark.detail}</>}
            </span>
          </li>
        ))}
      </ol>
    </Card>
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
      <p style={{ fontSize: "1.3rem", margin: ".2rem 0" }}>
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

function GoalCard({ block, me, onChanged, setNote }: {
  block: GoalBlock; me: Me; onChanged: () => void; setNote: (s: string) => void;
}) {
  const staff = isStaff(me);
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
    <Card title={<a href={`/report/${block.id}`}>{block.title}</a>}
          actions={block.is_historical ? <Pill>{block.resolution?.resolution}</Pill> : null}>
      {/* The headline is the server's decision, not this screen's. */}
      <p style={{ fontSize: "1.05rem", margin: 0, color: "var(--blue)" }}>
        {block.headline.text}
      </p>
      {block.measure.kind_is_undecided && staff && (
        <Banner kind="info">
          Nobody has said how we will know this worked. Choose a number, a sentence,
          or "not measurable" — it is not the same as leaving it blank.
        </Banner>
      )}

      <Measure block={block} />

      {block.narrative?.body && <p className="narrative">{block.narrative.body}</p>}

      {block.milestones.length > 0 && (
        <ul className="small" style={{ margin: ".4rem 0" }}>
          {block.milestones.map((stone) => (
            <li key={stone.id}>
              <span className="muted">{stone.occurred_at ?? stone.due_date ?? "—"} · </span>
              {stone.title} <Pill kind={stone.state === "late" ? "warn" : ""}>{stone.state}</Pill>
            </li>
          ))}
        </ul>
      )}

      {block.resolutions.map((row) => (
        <p key={row.id} className="small" style={{ borderLeft: "2px solid var(--orange)",
                                                   paddingLeft: ".5rem" }}>
          <strong>{row.resolution}</strong> — {row.reason}
          <span className="muted"> · {when(row.at)}{row.by ? ` · ${row.by}` : ""}</span>
        </p>
      ))}

      {/* Present, and subordinate. Never the headline (FR-4B.21). */}
      {block.completion.of > 0 && (
        <p className="small muted">
          Work completed: {block.completion.done} of {block.completion.of}
        </p>
      )}

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
    </Card>
  );
}
