import { PageHead } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { Pipeline, Stage, StaffMember, api } from "../lib/api";
import { useWords } from "../lib/words";

type Trigger = "enters" | "idle" | "won" | "lost" | "sent" | "signed";
type Action = "create_task" | "draft_email" | "move_stage" | "enroll_touches" | "notify" | "start_follow_up"
  | "calendar_event" | "send_signature";
type For = "contact_owner" | "practice_owner" | "member";

export interface Rule {
  id: string; pipeline: string; trigger: Trigger; from_stage: string | null; to_stage: string | null;
  idle_days: number | null; action_type: Action;
  task_title_template: string; task_due_offset_days: number | null; task_client_visible: boolean;
  task_for: For; task_assignee: string | null;
  email_template: string | null; send_by_offset_days: number; move_to_stage: string | null;
  document_template?: string | null;
  touch_cadence: string; notice_text: string; is_active: boolean; position: number;
  summary: string;
}
interface Template { id: string; name: string; subject: string; kind: string; }
interface Example { key: string; summary: string; added: boolean; kind?: "rule" | "follow_up" }
interface FollowUpStep { position: number; template: string; template_name: string; days_after: number }
interface FollowUp { id: string; stage: string; is_active: boolean; running: number; steps: FollowUpStep[] }
type StaffWithUser = StaffMember & { user?: string };

const MERGE = "{FirstName} {LastName} {Company} {Stage} {Pipeline} {DaysInStage} {Owner}";

/**
 * What "Client can see this task" starts as. Internal, unless the rule is
 * about the sale itself: a won stage's (or a won rule's) task is for the new
 * client. The FF still decides; the server applies the same default.
 */
function visibleByDefault(trigger: Trigger, stage: Stage | undefined, pipeline: Pipeline | undefined) {
  return pipeline?.kind === "sales" && (trigger === "won" || stage?.semantic === "won");
}

/**
 * Stage rules, part 2 (owner, 2026-10-24): one card per stage of each
 * pipeline. The practice owner renames, reorders, adds and removes stages
 * here, and each card holds the rules that start in it: entering it (from any
 * stage or a named one), or sitting in it N days with no activity. Won and
 * lost are the pipeline's own card. A rule makes a task, drafts an email for
 * approval, moves the contact, puts them on referral touches, or sends a
 * notice to Home and the day's email. A rule's own move runs the next stage's
 * rules, but not their moves.
 */
export function StageRules() {
  const qc = useQueryClient();
  const w = useWords();
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const [pipelineId, setPipelineId] = useState("");

  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const current = pipelineId || pipelines.data?.[0]?.id || "";
  const pipeline = pipelines.data?.find((p) => p.id === current);
  const stages = (pipeline?.stages ?? []).slice().sort((a, b) => a.position - b.position);
  const rules = useQuery<Rule[]>({
    queryKey: ["rules", current],
    queryFn: () => api.get<Rule[]>(`/api/stage-automations/?pipeline=${current}`),
    enabled: !!current,
  });
  const examples = useQuery<Example[]>({
    queryKey: ["rule-examples", current],
    queryFn: () => api.get<Example[]>(`/api/stage-automations/examples/?pipeline=${current}`),
    enabled: !!current,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["rules"] });
    qc.invalidateQueries({ queryKey: ["rule-examples"] });
    qc.invalidateQueries({ queryKey: ["pipelines"] });
  };
  const fail = (e: Error) => setNote({ kind: "bad", text: e.message });

  const addExample = useMutation({
    mutationFn: (key: string) => api.post("/api/stage-automations/examples/", { pipeline: current, key }),
    onSuccess: () => { setNote({ kind: "ok", text: "Rule added. Change or delete it on its stage's card." }); refresh(); },
    onError: fail,
  });
  const order = useMutation({
    mutationFn: (ids: string[]) => api.post("/api/pipeline-stages/order/", { pipeline: current, ids }),
    onSuccess: refresh, onError: fail,
  });
  const move = (i: number, by: number) => {
    const ids = stages.map((s) => s.id);
    const j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    order.mutate(ids);
  };
  const [newStage, setNewStage] = useState("");
  const addStage = useMutation({
    mutationFn: () => api.post("/api/pipeline-stages/", { pipeline: current, label: newStage.trim(), semantic: "working" }),
    onSuccess: () => { setNewStage(""); setNote({ kind: "ok", text: "Stage added at the end. Move it where it belongs." }); refresh(); },
    onError: fail,
  });

  const byStage = (id: string) => (rules.data ?? []).filter((r) => r.to_stage === id && (r.trigger === "enters" || r.trigger === "idle"));
  const pipelineWide = (rules.data ?? []).filter((r) => ["won", "lost", "sent", "signed"]
    .includes(r.trigger));
  const offered = (examples.data ?? []).filter((e) => !e.added);

  return (
    <>
      <PageHead title="Stage rules"
        sub={<>Each pipeline's stages, and what happens as people move through them. Rename, reorder,
          add or remove a stage here. An email is only ever <strong>drafted into the Outbox</strong> for
          approval.</>} />

      <div className="row" style={{ marginBottom: "1rem" }}>
        {(pipelines.data ?? []).map((p) => (
          <button key={p.id} style={{ flex: "0 0 auto" }}
            className={p.id === current ? "primary" : "ghost"}
            onClick={() => { setPipelineId(p.id); setNote(null); }}>{p.name}</button>
        ))}
      </div>

      {note && <div role={note.kind === "ok" ? "status" : "alert"}><Banner kind={note.kind}>{note.text}</Banner></div>}

      {offered.length > 0 && (
        <Card title="Starter rules">
          <p className="small muted" style={{ marginTop: 0 }}>Common rules for this pipeline. Each is added with one
            click and can be changed or deleted on its stage's card.</p>
          <ul className="rule-examples">
            {offered.map((e) => (
              <li key={e.key}>
                <span>{e.summary}</span>
                <button className="small" disabled={addExample.isPending}
                  aria-label={`Add: ${e.summary}`} onClick={() => addExample.mutate(e.key)}>Add</button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="stage-cards">
        {stages.map((s, i) => (
          <StageCard key={s.id} stage={s} pipeline={pipeline!} stages={stages} rules={byStage(s.id)}
            first={i === 0} last={i === stages.length - 1} onUp={() => move(i, -1)} onDown={() => move(i, 1)}
            onChanged={refresh} onNote={setNote} />
        ))}
      </div>

      <Card title="Add a stage">
        <div className="row">
          <input aria-label="New stage name" value={newStage} placeholder="Discovery call booked"
            onChange={(e) => setNewStage(e.target.value)} />
          <button className="primary" style={{ flex: "0 0 auto" }} disabled={!newStage.trim() || addStage.isPending}
            onClick={() => addStage.mutate()}>Add stage</button>
        </div>
      </Card>

      {pipeline && (
        <Card title={`When someone is won or lost, or a document goes out or comes back, in ${pipeline.name}`}>
          <RuleList rules={pipelineWide} onChanged={refresh} onNote={setNote} />
          <RuleForm pipeline={pipeline} stages={stages} stage={null} onSaved={refresh} onNote={setNote} />
        </Card>
      )}

      <p className="small muted">
        A <strong>draft an email</strong> rule uses one of the practice's{" "}
        <Link to="/settings/templates">email templates</Link>. A rule that sits waiting counts days from the
        later of entering the stage and the last activity: an email either way, a note, a meeting, a finished{" "}
        {w.task} or a stage move. It fires once each time someone enters the stage.
      </p>
    </>
  );
}

function StageCard({ stage, pipeline, stages, rules, first, last, onUp, onDown, onChanged, onNote }: {
  stage: Stage & { contacts?: number }; pipeline: Pipeline; stages: Stage[]; rules: Rule[];
  first: boolean; last: boolean; onUp: () => void; onDown: () => void; onChanged: () => void;
  onNote: (n: { kind: string; text: string } | null) => void;
}) {
  const [label, setLabel] = useState(stage.label);
  const [removing, setRemoving] = useState(false);
  // A refusal shows on the card, beside its Remove: the page's banner is
  // out of sight from a card lower down.
  const [refusal, setRefusal] = useState("");
  const rename = useMutation({
    mutationFn: () => api.patch(`/api/pipeline-stages/${stage.id}/`, { label: label.trim() }),
    onSuccess: () => { onNote({ kind: "ok", text: `Renamed to ${label.trim()}.` }); onChanged(); },
    onError: (e: Error) => { setLabel(stage.label); onNote({ kind: "bad", text: e.message }); },
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/pipeline-stages/${stage.id}/`),
    onSuccess: () => { onNote({ kind: "ok", text: `${stage.label} is removed, with its rules.` }); onChanged(); },
    onError: (e: Error) => { setRemoving(false); setRefusal(e.message); },
  });
  const askRemove = () => {
    const held = stage.contacts ?? 0;
    if (held > 0) {
      setRefusal(`${stage.label} still holds ${held} ${held === 1 ? "contact" : "contacts"}. Move them to another stage first.`);
      return;
    }
    setRefusal(""); setRemoving(true);
  };
  const save = () => { if (label.trim() && label.trim() !== stage.label) rename.mutate(); };
  const meaning = { won: "Won", lost: "Lost", parked: "Parked", entry: "Where people start" } as Record<string, string>;
  return (
    <section className="card stage-card" aria-label={`Stage ${stage.label}`}>
      <div className="stage-card-head">
        <input className="stage-name" aria-label={`Name of ${stage.label}`} value={label}
          onChange={(e) => setLabel(e.target.value)} onBlur={save}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        {meaning[stage.semantic] && <Pill kind={stage.semantic === "won" ? "ok" : ""}>{meaning[stage.semantic]}</Pill>}
        <span className="small muted">{stage.contacts ?? 0} {stage.contacts === 1 ? "contact" : "contacts"}</span>
        <span className="stage-card-tools">
          <button className="ghost small" aria-label={`Move ${stage.label} up`} disabled={first} onClick={onUp}>↑</button>
          <button className="ghost small" aria-label={`Move ${stage.label} down`} disabled={last} onClick={onDown}>↓</button>
          {removing ? (
            <>
              <span className="small">Remove {stage.label} and its rules?</span>
              <button className="danger small" disabled={remove.isPending} onClick={() => remove.mutate()}>Remove</button>
              <button className="ghost small" onClick={() => setRemoving(false)}>Keep</button>
            </>
          ) : (
            <button className="ghost small" aria-label={`Remove ${stage.label}`} onClick={askRemove}>Remove</button>
          )}
        </span>
      </div>
      {refusal && <div role="alert"><Banner kind="bad">{refusal}</Banner></div>}
      <RuleList rules={rules} onChanged={onChanged} onNote={onNote} />
      <RuleForm pipeline={pipeline} stages={stages} stage={stage} onSaved={onChanged} onNote={onNote} />
      <FollowUpCard stage={stage} onNote={onNote} />
    </section>
  );
}

/**
 * Pipeline part 3: the stage's one follow-up, two or three emails from the
 * template library, each N days after the previous one was sent. Moving
 * someone into the stage asks whether to start it (default No); a rule can
 * start it without asking. Each step waits in the Outbox for approval.
 */
function FollowUpCard({ stage, onNote }: {
  stage: Stage; onNote: (n: { kind: string; text: string } | null) => void;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<{ template: string; days_after: number }[]>([]);
  const current = useQuery<{ follow_up: FollowUp | null }>({
    queryKey: ["follow-up", stage.id],
    queryFn: () => api.get<{ follow_up: FollowUp | null }>(`/api/pipeline-stages/${stage.id}/follow-up/`),
  });
  const templates = useQuery<Template[]>({
    queryKey: ["templates"], queryFn: () => api.get<Template[]>("/api/email-templates/"), enabled: editing,
  });
  const done = (text: string) => {
    setEditing(false); onNote({ kind: "ok", text });
    qc.invalidateQueries({ queryKey: ["follow-up", stage.id] });
    qc.invalidateQueries({ queryKey: ["rule-examples"] });
  };
  const save = useMutation({
    mutationFn: () => api.put(`/api/pipeline-stages/${stage.id}/follow-up/`, { steps: rows, is_active: true }),
    onSuccess: () => done(`${stage.label}'s follow-up is saved. Moving someone in will ask whether to start it.`),
    onError: (e: Error) => onNote({ kind: "bad", text: e.message }),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/pipeline-stages/${stage.id}/follow-up/`),
    onSuccess: () => done(`${stage.label}'s follow-up is removed; any running were stopped.`),
    onError: (e: Error) => onNote({ kind: "bad", text: e.message }),
  });
  const f = current.data?.follow_up ?? null;
  const open = () => {
    setRows(f ? f.steps.map((s) => ({ template: s.template, days_after: s.days_after }))
      : [{ template: "", days_after: 0 }, { template: "", days_after: 7 }]);
    setEditing(true);
  };
  return (
    <div className="follow-up" role="group" aria-label={`Follow-up for ${stage.label}`}>
      <div className="follow-up-head">
        <strong>Follow-up</strong>
        {f ? (
          <span className="small muted">{f.steps.length} emails{f.running ? ` · ${f.running} running` : ""}</span>
        ) : <span className="small muted">None. Moving someone in asks nothing.</span>}
        {!editing && <button className="ghost small" aria-label={`${f ? "Change" : "Set up"} the ${stage.label} follow-up`}
          onClick={open}>{f ? "Change" : "Set up"}</button>}
      </div>
      {f && !editing && (
        <ol className="follow-up-steps">
          {f.steps.map((s) => (
            <li key={s.position}>“{s.template_name}”, {s.position === 1 ? "drafted when it starts" : `${s.days_after} days after the one before is sent`}</li>
          ))}
        </ol>
      )}
      {editing && (
        <div className="follow-up-form">
          {rows.map((r, i) => (
            <div key={i} className="row wrap">
              <span className="small">Step {i + 1}</span>
              <select aria-label={`Step ${i + 1} template`} value={r.template}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, template: e.target.value } : x)))}>
                <option value="">Choose a template…</option>
                {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              {i === 0 ? <span className="small muted">drafted into the Outbox when it starts</span> : <>
                <input type="number" min={1} aria-label={`Step ${i + 1} days after`} value={r.days_after}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, days_after: Number(e.target.value) } : x)))} />
                <span className="small muted">days after step {i} is sent</span>
              </>}
              {rows.length > 2 && <button className="ghost small" aria-label={`Remove step ${i + 1}`}
                onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button>}
            </div>
          ))}
          <div className="row">
            {rows.length < 3 && <button className="ghost small" onClick={() => setRows([...rows, { template: "", days_after: 14 }])}>+ A third step</button>}
            <button className="primary small" disabled={save.isPending || rows.some((r) => !r.template)}
              onClick={() => save.mutate()}>Save follow-up</button>
            <button className="ghost small" onClick={() => setEditing(false)}>Cancel</button>
            {f && <button className="danger small" disabled={remove.isPending} onClick={() => remove.mutate()}>Remove follow-up</button>}
          </div>
        </div>
      )}
    </div>
  );
}

function RuleList({ rules, onChanged, onNote }: {
  rules: Rule[]; onChanged: () => void; onNote: (n: { kind: string; text: string } | null) => void;
}) {
  const w = useWords();
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Rule> }) => api.patch(`/api/stage-automations/${id}/`, body),
    onSuccess: () => { onNote({ kind: "ok", text: `Rule saved. ${w.Tasks} it has already made keep their own setting.` }); onChanged(); },
    onError: (e: Error) => onNote({ kind: "bad", text: e.message }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/stage-automations/${id}/`),
    onSuccess: onChanged,
  });
  if (rules.length === 0) return <Empty>No rules yet.</Empty>;
  return (
    <ul className="rule-list">
      {rules.map((r) => (
        <li key={r.id} className={r.is_active ? "" : "off"}>
          <span className="rule-summary">{r.summary}</span>
          <span className="rule-tools">
            <Pill kind={r.action_type === "draft_email" ? "warn" : "ok"}>
              {r.action_type === "draft_email" || r.action_type === "send_signature" ? "queues for approval" : r.trigger === "idle" ? "checked daily" : "fires at once"}</Pill>
            {r.action_type === "create_task" && (
              <label className="inline small">
                <input type="checkbox" style={{ width: "auto" }}
                  aria-label={`Client can see the ${w.task}: ${r.summary}`}
                  checked={r.task_client_visible} disabled={patch.isPending}
                  onChange={(e) => patch.mutate({ id: r.id, body: { task_client_visible: e.target.checked } })} />
                Client sees it
              </label>
            )}
            <label className="inline small">
              <input type="checkbox" style={{ width: "auto" }} aria-label={`On: ${r.summary}`}
                checked={r.is_active} disabled={patch.isPending}
                onChange={(e) => patch.mutate({ id: r.id, body: { is_active: e.target.checked } })} />
              On
            </label>
            <button className="danger small" aria-label={`Delete: ${r.summary}`} onClick={() => remove.mutate(r.id)}>Delete</button>
          </span>
        </li>
      ))}
    </ul>
  );
}

function RuleForm({ pipeline, stages, stage, onSaved, onNote }: {
  pipeline: Pipeline; stages: Stage[]; stage: Stage | null; onSaved: () => void;
  onNote: (n: { kind: string; text: string } | null) => void;
}) {
  const w = useWords();
  const [open, setOpen] = useState(false);
  const blank = {
    trigger: (stage ? "enters" : "won") as Trigger, from_stage: "", idle_days: 14,
    action_type: "create_task" as Action, task_title_template: "", task_due_offset_days: 3,
    task_client_visible: visibleByDefault(stage ? "enters" : "won", stage ?? undefined, pipeline),
    task_for: "contact_owner" as For, task_assignee: "", email_template: "", send_by_offset_days: 7,
    move_to_stage: "", touch_cadence: "monthly", notice_text: "", event_minutes: 30,
    document_template: "",
  };
  const [d, setD] = useState(blank);
  const set = (patch: Partial<typeof d>) => setD({ ...d, ...patch });
  const templates = useQuery<Template[]>({
    queryKey: ["templates"], queryFn: () => api.get<Template[]>("/api/email-templates/"), enabled: open,
  });
  const documentTemplates = useQuery<{ id: string; name: string }[]>({
    queryKey: ["document-templates"],
    queryFn: () => api.get<{ id: string; name: string }[]>("/api/document-templates/"),
    enabled: open,
  });
  const staff = useQuery<StaffWithUser[]>({
    queryKey: ["staff"], queryFn: () => api.get<StaffWithUser[]>("/api/staff/"), enabled: open,
  });
  const create = useMutation({
    mutationFn: () => api.post("/api/stage-automations/", {
      pipeline: pipeline.id, trigger: d.trigger, to_stage: stage?.id ?? null,
      from_stage: d.trigger === "enters" && d.from_stage ? d.from_stage : null,
      idle_days: d.trigger === "idle" ? d.idle_days : null,
      action_type: d.action_type,
      task_title_template: d.action_type === "create_task" || d.action_type === "calendar_event"
        ? d.task_title_template : "",
      task_due_offset_days: d.action_type === "create_task" || d.action_type === "calendar_event"
        ? d.task_due_offset_days : null,
      event_minutes: d.action_type === "calendar_event" ? d.event_minutes : null,
      task_client_visible: d.action_type === "create_task" && d.task_client_visible,
      task_for: d.task_for, task_assignee: d.task_for === "member" ? d.task_assignee || null : null,
      email_template: d.action_type === "draft_email" ? d.email_template || null : null,
      send_by_offset_days: d.send_by_offset_days,
      move_to_stage: d.action_type === "move_stage" ? d.move_to_stage || null : null,
      touch_cadence: d.action_type === "enroll_touches" ? d.touch_cadence : "",
      notice_text: d.action_type === "notify" ? d.notice_text : "",
      document_template: d.action_type === "send_signature" ? d.document_template || null : null,
      is_active: true,
    }),
    onSuccess: () => { setD(blank); setOpen(false); onNote({ kind: "ok", text: "Rule saved." }); onSaved(); },
    onError: (e: Error) => onNote({ kind: "bad", text: e.message }),
  });
  const where = stage ? stage.label : pipeline.name;
  if (!open) {
    return <button className="ghost small" aria-label={`Add a rule to ${where}`} onClick={() => setOpen(true)}>+ Add a rule</button>;
  }
  const others = stages.filter((s) => s.id !== stage?.id);
  const forField = (
    <Field label="For">
      <div className="row">
        <select aria-label="For" value={d.task_for} onChange={(e) => set({ task_for: e.target.value as For })}>
          <option value="contact_owner">The contact's owner</option>
          <option value="practice_owner">The practice owner</option>
          <option value="member">A team member…</option>
        </select>
        {d.task_for === "member" && (
          <select aria-label="Team member" value={d.task_assignee} onChange={(e) => set({ task_assignee: e.target.value })}>
            <option value="">Choose…</option>
            {(staff.data ?? []).filter((m) => m.is_active && m.user).map((m) => (
              <option key={m.id} value={m.user}>{m.full_name || m.email}</option>))}
          </select>
        )}
      </div>
    </Field>
  );
  return (
    <div className="rule-form" role="group" aria-label={`New rule for ${where}`}>
      <div className="row wrap">
        <Field label="When">
          {stage ? (
            <select aria-label="When" value={d.trigger} onChange={(e) => set({ trigger: e.target.value as Trigger })}>
              <option value="enters">A contact enters {stage.label}</option>
              <option value="idle">A contact has sat here with no activity</option>
            </select>
          ) : (
            <select aria-label="When" value={d.trigger} onChange={(e) => {
              const trigger = e.target.value as Trigger;
              set({ trigger, task_client_visible: visibleByDefault(trigger, undefined, pipeline) });
            }}>
              <option value="won">A contact is won</option>
              <option value="lost">A contact is lost</option>
              <option value="sent">A contact is sent a document to sign</option>
              <option value="signed">A contact signs a document</option>
            </select>
          )}
        </Field>
        {d.trigger === "enters" && (
          <Field label="Coming from">
            <select aria-label="Coming from" value={d.from_stage} onChange={(e) => set({ from_stage: e.target.value })}>
              <option value="">Any stage</option>
              {others.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
        )}
        {d.trigger === "idle" && (
          <Field label="For (days)">
            <input type="number" min={1} aria-label="Days with no activity" value={d.idle_days}
              onChange={(e) => set({ idle_days: Number(e.target.value) })} />
          </Field>
        )}
        <Field label="Then">
          <select aria-label="Then" value={d.action_type} onChange={(e) => set({ action_type: e.target.value as Action })}>
            <option value="create_task">Create {w.aTask}</option>
            <option value="draft_email">Draft an email for approval</option>
            <option value="move_stage">Move them to another stage</option>
            <option value="enroll_touches">Put them on referral touches</option>
            <option value="notify">Send a notice</option>
            <option value="start_follow_up">Start the stage's follow-up, without asking</option>
            {d.trigger === "enters" && (
              <option value="calendar_event">Offer a calendar event, at a time I pick</option>)}
            {d.trigger !== "sent" && (
              <option value="send_signature">Send a document for signature, for approval</option>)}
          </select>
        </Field>
      </div>
      <div className="row wrap">
        {d.action_type === "create_task" && (
          <>
            <Field label={`${w.Task} title`}>
              <input aria-label={`${w.Task} title`} value={d.task_title_template} placeholder="Call {FirstName} at {Company}"
                onChange={(e) => set({ task_title_template: e.target.value })} />
            </Field>
            <Field label="Due in (days)">
              <input type="number" aria-label="Due in (days)" value={d.task_due_offset_days}
                onChange={(e) => set({ task_due_offset_days: Number(e.target.value) })} />
            </Field>
            {forField}
            <Field label="Visibility">
              <label className="inline small">
                <input type="checkbox" style={{ width: "auto" }} checked={d.task_client_visible}
                  onChange={(e) => set({ task_client_visible: e.target.checked })} />
                Client can see this {w.task}
              </label>
            </Field>
          </>
        )}
        {d.action_type === "send_signature" && (
          <Field label="Document template">
            <select aria-label="Document template" value={d.document_template}
              onChange={(e) => set({ document_template: e.target.value })}>
              <option value="">Choose…</option>
              {(documentTemplates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
        )}
        {d.action_type === "draft_email" && (
          <>
            <Field label="Email template">
              <select aria-label="Email template" value={d.email_template} onChange={(e) => set({ email_template: e.target.value })}>
                <option value="">Choose…</option>
                {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
            <Field label="Draft expires after (days)">
              <input type="number" value={d.send_by_offset_days}
                onChange={(e) => set({ send_by_offset_days: Number(e.target.value) })} />
            </Field>
          </>
        )}
        {d.action_type === "move_stage" && (
          <Field label="Move to">
            <select aria-label="Move to" value={d.move_to_stage} onChange={(e) => set({ move_to_stage: e.target.value })}>
              <option value="">Choose…</option>
              {others.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
        )}
        {d.action_type === "enroll_touches" && (
          <Field label="How often">
            <select aria-label="How often" value={d.touch_cadence} onChange={(e) => set({ touch_cadence: e.target.value })}>
              <option value="monthly">Monthly</option>
              <option value="bimonthly">Every two months</option>
              <option value="quarterly">Quarterly</option>
            </select>
          </Field>
        )}
        {d.action_type === "calendar_event" && (
          <>
            <Field label="Event title">
              <input aria-label="Event title" value={d.task_title_template}
                placeholder="Follow up with {FirstName} at {Company}"
                onChange={(e) => set({ task_title_template: e.target.value })} />
            </Field>
            <Field label="Suggested in (days)">
              <input type="number" min={0} aria-label="Suggested in (days)" value={d.task_due_offset_days}
                onChange={(e) => set({ task_due_offset_days: Number(e.target.value) })} />
            </Field>
            <Field label="Length">
              <select aria-label="Length" value={d.event_minutes}
                onChange={(e) => set({ event_minutes: Number(e.target.value) })}>
                {[15, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </select>
            </Field>
          </>
        )}
        {d.action_type === "notify" && (
          <>
            <Field label="The notice">
              <input aria-label="The notice" value={d.notice_text}
                placeholder="{FirstName} {LastName} has been in {Stage} {DaysInStage} days"
                onChange={(e) => set({ notice_text: e.target.value })} />
            </Field>
            {forField}
          </>
        )}
      </div>
      {(d.action_type === "create_task" || d.action_type === "notify"
        || d.action_type === "calendar_event") && (
        <p className="small muted" style={{ margin: 0 }}>Merge fields: {MERGE}</p>)}
      {d.action_type === "calendar_event" && (
        <p className="small muted" style={{ margin: 0 }}>Asked when someone moves a card here
          on the board: they pick the day and time, and it goes on their own calendar. A move by
          an import or another rule asks nobody, so nothing is added.</p>)}
      {d.action_type === "enroll_touches" && (
        <p className="small muted" style={{ margin: 0 }}>Only referral partners are put on touches; anyone already on
          them keeps their cadence.</p>)}
      {d.action_type === "move_stage" && (
        <p className="small muted" style={{ margin: 0 }}>The stage they are moved to runs its own rules, except its
          moves, so two rules can never bounce someone back and forth.</p>)}
      <div className="row">
        <button className="primary" style={{ flex: "0 0 auto" }} disabled={create.isPending} onClick={() => create.mutate()}>Save rule</button>
        <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => { setD(blank); setOpen(false); }}>Cancel</button>
      </div>
    </div>
  );
}
