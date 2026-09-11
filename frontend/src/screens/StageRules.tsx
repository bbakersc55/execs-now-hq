import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { Pipeline, api } from "../lib/api";

interface Rule {
  id: string; pipeline: string; from_stage: string | null; to_stage: string; action_type: string;
  task_title_template: string; task_due_offset_days: number | null;
  email_template: string | null; send_by_offset_days: number; is_active: boolean;
  summary: string;
}
interface Template { id: string; name: string; subject: string; kind: string; }

export function StageRules() {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [pipelineId, setPipelineId] = useState("");
  const [newTemplate, setNewTemplate] = useState({ name: "", subject: "", body: "" });
  const [draft, setDraft] = useState({
    to_stage: "", action_type: "create_task", task_title_template: "",
    task_due_offset_days: 3, email_template: "", send_by_offset_days: 7,
  });

  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const current = pipelineId || pipelines.data?.[0]?.id || "";
  const stagesOf = pipelines.data?.find((p) => p.id === current)?.stages ?? [];
  const rules = useQuery<Rule[]>({
    queryKey: ["rules", current],
    queryFn: () => api.get<Rule[]>(`/api/stage-automations/?pipeline=${current}`),
    enabled: !!current,
  });
  const templates = useQuery<Template[]>({
    queryKey: ["templates"], queryFn: () => api.get<Template[]>("/api/email-templates/"),
  });

  const create = useMutation({
    mutationFn: () => api.post("/api/stage-automations/", {
      pipeline: current,
      to_stage: draft.to_stage,
      action_type: draft.action_type,
      task_title_template: draft.action_type === "create_task" ? draft.task_title_template : "",
      task_due_offset_days: draft.action_type === "create_task" ? draft.task_due_offset_days : null,
      email_template: draft.action_type === "draft_email" ? draft.email_template || null : null,
      send_by_offset_days: draft.send_by_offset_days,
      is_active: true,
    }),
    onSuccess: () => {
      setNote("Rule saved.");
      qc.invalidateQueries({ queryKey: ["rules"] });
      setDraft({ ...draft, task_title_template: "", to_stage: "" });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const createTemplate = useMutation({
    mutationFn: () => api.post<Template>("/api/email-templates/", {
      ...newTemplate, kind: "stage",
    }),
    onSuccess: (t) => {
      setNote(`Template “${t.name}” created. You can now add a draft-email rule.`);
      setNewTemplate({ name: "", subject: "", body: "" });
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/stage-automations/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });

  return (
    <>
      <h2>Stage automations</h2>
      <p className="sub">
        What happens when a contact changes stage. A task is created immediately;
        an email is only ever <strong>drafted into the Outbox</strong> for approval.
      </p>

      <p className="sub">
        <strong>Rules belong to one pipeline.</strong> A “becomes Qualified” rule on Sales
        does not fire for the referral pipeline's own Qualified stage.
      </p>

      <div className="row" style={{ marginBottom: "1rem" }}>
        {(pipelines.data ?? []).map((p) => (
          <button key={p.id} style={{ flex: "0 0 auto" }}
            className={p.id === current ? "primary" : "ghost"}
            onClick={() => { setPipelineId(p.id); setDraft({ ...draft, to_stage: "" }); }}>
            {p.name}
          </button>
        ))}
      </div>

      {note && <Banner kind="ok">{note}</Banner>}

      <Card title="Email templates">
        <p className="muted small">
          A <strong>draft an email</strong> rule needs a template to render. Without one
          the rule cannot be created, which is why this sits above.
        </p>
        <div className="row">
          <Field label="Name">
            <input value={newTemplate.name} aria-label="Template name"
              placeholder="Qualified follow-up"
              onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })} />
          </Field>
          <Field label="Subject">
            <input value={newTemplate.subject} aria-label="Template subject"
              onChange={(e) => setNewTemplate({ ...newTemplate, subject: e.target.value })} />
          </Field>
        </div>
        <Field label="Body">
          <textarea rows={4} value={newTemplate.body} aria-label="Template body"
            onChange={(e) => setNewTemplate({ ...newTemplate, body: e.target.value })} />
        </Field>
        <button disabled={!newTemplate.name || !newTemplate.subject || createTemplate.isPending}
          onClick={() => createTemplate.mutate()}>
          Create template
        </button>
        {(templates.data ?? []).length > 0 && (
          <p className="muted small" style={{ marginTop: ".6rem", marginBottom: 0 }}>
            Existing: {templates.data!.map((t) => t.name).join(", ")}
          </p>
        )}
      </Card>

      <Card title="Add a rule">
        <div className="row">
          <Field label="When a contact becomes">
            <select value={draft.to_stage} onChange={(e) => setDraft({ ...draft, to_stage: e.target.value })}>
              <option value="">Choose a stage…</option>
              {stagesOf.slice().sort((a, b) => a.position - b.position)
                .map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Then">
            <select value={draft.action_type}
              onChange={(e) => setDraft({ ...draft, action_type: e.target.value })}>
              <option value="create_task">Create a task</option>
              <option value="draft_email">Draft an email for approval</option>
            </select>
          </Field>
          {draft.action_type === "create_task" ? (
            <>
              <Field label="Task title">
                <input value={draft.task_title_template}
                  placeholder="Book strategy session"
                  onChange={(e) => setDraft({ ...draft, task_title_template: e.target.value })} />
              </Field>
              <Field label="Due in (days)">
                <input type="number" value={draft.task_due_offset_days}
                  onChange={(e) => setDraft({ ...draft, task_due_offset_days: Number(e.target.value) })} />
              </Field>
            </>
          ) : (
            <>
              <Field label="Email template">
                <select value={draft.email_template}
                  onChange={(e) => setDraft({ ...draft, email_template: e.target.value })}>
                  <option value="">Choose…</option>
                  {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
                {(templates.data ?? []).length === 0 && (
                  <p className="muted small" style={{ marginBottom: 0 }}>
                    No templates yet — create one below first.
                  </p>
                )}
              </Field>
              <Field label="Draft expires after (days)">
                <input type="number" value={draft.send_by_offset_days}
                  onChange={(e) => setDraft({ ...draft, send_by_offset_days: Number(e.target.value) })} />
              </Field>
            </>
          )}
          <div style={{ flex: "0 0 auto" }}>
            <button className="primary" disabled={!draft.to_stage || create.isPending}
              onClick={() => create.mutate()}>Add rule</button>
          </div>
        </div>
      </Card>

      <Card title="Active rules">
        {(rules.data ?? []).length === 0 ? <Empty>No rules yet.</Empty> : (
          <table>
            <thead><tr><th>Rule</th><th>Type</th><th></th></tr></thead>
            <tbody>
              {rules.data!.map((r) => (
                <tr key={r.id}>
                  <td>{r.summary}</td>
                  <td><Pill kind={r.action_type === "create_task" ? "ok" : "warn"}>
                    {r.action_type === "create_task" ? "fires immediately" : "queues for approval"}
                  </Pill></td>
                  <td className="right">
                    <button className="danger" onClick={() => remove.mutate(r.id)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
