import { PageHead } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { Pipeline, Stage, api } from "../lib/api";
import { useWords } from "../lib/words";

interface Rule {
  id: string; pipeline: string; from_stage: string | null; to_stage: string; action_type: string;
  task_title_template: string; task_due_offset_days: number | null;
  task_client_visible: boolean;
  email_template: string | null; send_by_offset_days: number; is_active: boolean;
  summary: string;
}
interface Template { id: string; name: string; subject: string; kind: string; }

/**
 * What "Client can see this task" starts as for a stage. Internal, unless the
 * stage is the sale itself: a won stage's task is for the new client. The FF
 * still decides — this is only where the box starts, and the server applies
 * the same default when a rule arrives without one.
 */
function visibleByDefault(stage: Stage | undefined, pipeline: Pipeline | undefined) {
  return !!stage && stage.semantic === "won" && pipeline?.kind === "sales";
}

export function StageRules() {
  const qc = useQueryClient();
  const w = useWords();
  const [note, setNote] = useState("");
  const [pipelineId, setPipelineId] = useState("");
  const [draft, setDraft] = useState({
    to_stage: "", action_type: "create_task", task_title_template: "",
    task_due_offset_days: 3, task_client_visible: false, email_template: "",
    send_by_offset_days: 7,
  });

  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const current = pipelineId || pipelines.data?.[0]?.id || "";
  const pipeline = pipelines.data?.find((p) => p.id === current);
  const stagesOf = pipeline?.stages ?? [];
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
      task_client_visible: draft.action_type === "create_task" && draft.task_client_visible,
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

  const setVisible = useMutation({
    mutationFn: ({ id, visible }: { id: string; visible: boolean }) =>
      api.patch(`/api/stage-automations/${id}/`, { task_client_visible: visible }),
    onSuccess: () => {
      setNote(`Rule saved. ${w.Tasks} it has already made keep their own setting.`);
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/stage-automations/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });

  return (
    <>
      <PageHead title="Stage automations"
        sub={<>What happens when a contact changes stage. {w.ATask} is created immediately;
        an email is only ever <strong>drafted into the Outbox</strong> for approval.</>} />

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

      <p className="small muted">
        A <strong>draft an email</strong> rule uses one of the practice's{" "}
        <Link to="/settings/templates">email templates</Link>, merged for each person and
        signed by you.
      </p>

      <Card title="Add a rule">
        <div className="row">
          <Field label="When a contact becomes">
            <select value={draft.to_stage} aria-label="When a contact becomes"
              onChange={(e) => setDraft({
                ...draft, to_stage: e.target.value,
                task_client_visible: visibleByDefault(
                  stagesOf.find((s) => s.id === e.target.value), pipeline),
              })}>
              <option value="">Choose a stage…</option>
              {stagesOf.slice().sort((a, b) => a.position - b.position)
                .map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Then">
            <select value={draft.action_type}
              onChange={(e) => setDraft({ ...draft, action_type: e.target.value })}>
              <option value="create_task">Create {w.aTask}</option>
              <option value="draft_email">Draft an email for approval</option>
            </select>
          </Field>
          {draft.action_type === "create_task" ? (
            <>
              <Field label={`${w.Task} title`}>
                <input value={draft.task_title_template}
                  placeholder="Book strategy session"
                  onChange={(e) => setDraft({ ...draft, task_title_template: e.target.value })} />
              </Field>
              <Field label="Due in (days)">
                <input type="number" value={draft.task_due_offset_days}
                  onChange={(e) => setDraft({ ...draft, task_due_offset_days: Number(e.target.value) })} />
              </Field>
              <Field label="Visibility">
                <label className="inline small">
                  <input type="checkbox" style={{ width: "auto" }}
                    checked={draft.task_client_visible}
                    onChange={(e) => setDraft({ ...draft, task_client_visible: e.target.checked })} />
                  Client can see this {w.task}
                </label>
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
                    No templates yet: write one under <Link to="/settings/templates">Email
                    templates</Link>.
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
            <button className="primary"
              disabled={!draft.to_stage || create.isPending}
              onClick={() => create.mutate()}>Add rule</button>
          </div>
        </div>
        {draft.action_type === "create_task" && (
          <p className="muted small" style={{ marginBottom: 0 }}>
            The {w.task} is filed under the contact's company when that company is a client.
            Unticked, it stays internal: the client never sees it in the portal or in a
            digest. A won stage starts ticked, because that {w.task} is for the new client.
          </p>
        )}
      </Card>

      <Card title="Active rules">
        {(rules.data ?? []).length === 0 ? <Empty>No rules yet.</Empty> : (
          <table>
            <thead><tr><th>Rule</th><th>Type</th><th>Client can see the {w.task}</th><th></th></tr></thead>
            <tbody>
              {rules.data!.map((r) => (
                <tr key={r.id}>
                  <td>{r.summary}</td>
                  <td><Pill kind={r.action_type === "create_task" ? "ok" : "warn"}>
                    {r.action_type === "create_task" ? "fires immediately" : "queues for approval"}
                  </Pill></td>
                  <td>
                    {r.action_type === "create_task" && (
                      <input type="checkbox" style={{ width: "auto" }}
                        aria-label={`Client can see the ${w.task}: ${r.summary}`}
                        checked={r.task_client_visible} disabled={setVisible.isPending}
                        onChange={(e) => setVisible.mutate({ id: r.id, visible: e.target.checked })} />
                    )}
                  </td>
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
