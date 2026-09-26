import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Banner, Card, Field, Pill } from "../components/ui";
import { Me, StrategySessionRow, StrategyTemplateRow as Template, api } from "../lib/api";

type Edit = { prompt?: string; ask_when?: "precall" | "live"; must_ask?: boolean };

/** What each shape is, in the words a person uses for it. */
const SCHEMA_LABELS: Record<string, string> = {
  rating_1_10: "rated 1–10",
  free_text: "written answer",
  diagnostic_triple: "said / cause / tried",
  value_pair: "value and why",
  agreed_note: "agreed, with a note",
  path_reaction: "reaction to a path",
};

/**
 * Matrix 10.1 — the templates, managed by the founder fractional only.
 *
 * More than one (owner, 2026-09-26): pick one to edit, and rename, duplicate,
 * make it the practice default or archive it; or restore a clean one from the
 * seed. **Nothing overwrites** — Restore from seed and Duplicate both make a
 * new template, and the one somebody has been editing stays theirs.
 *
 * Editing here cannot reach a session already under way: each session renders
 * from the snapshot it took when it started (FR-4.5).
 */
export function SessionTemplate({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [note, setNote] = useState("");

  // Arrived here from a session's prep with a suggested rewording (owner,
  // 2026-09-21). It fills the box and counts as a pending change — **it is
  // never saved for you**, which is the whole point of copying rather than
  // applying.
  const [params, setParams] = useSearchParams();
  const fromSession = params.get("session");
  // One key, or several: applying a selection is one trip, not one per
  // question (owner, 2026-09-21).
  const prefillKeys = (params.get("prefill") ?? "").split(",").filter(Boolean);
  const prefillKey = prefillKeys.join(",");
  const session = useQuery<StrategySessionRow>({
    queryKey: ["strategy-session", fromSession],
    queryFn: () => api.get<StrategySessionRow>(`/api/strategy-sessions/${fromSession}/`),
    enabled: !!fromSession && !!prefillKey,
  });
  useEffect(() => {
    if (!prefillKey || !session.data?.prep) return;
    const wanted = prefillKey.split(",");
    const rows = session.data.prep.rewordings.filter((r) => wanted.includes(r.key));
    if (rows.length === 0) return;
    setEdits((current) => ({
      ...current,
      ...Object.fromEntries(rows.map((row) => [row.key, { prompt: row.suggested }])),
    }));
    setNote(`Filled in ${rows.length} question${rows.length === 1 ? "" : "s"} from your `
      + `prep for ${session.data?.contact?.name ?? "the session"}. `
      + "Nothing is saved until you press Save.");
    setParams({}, { replace: true });
  }, [prefillKey, session.data, setParams]);

  const templates = useQuery<Template[]>({
    queryKey: ["strategy-templates"],
    queryFn: () => api.get<Template[]>("/api/strategy-templates/"),
  });
  // Which one is open: the one asked for (Apply from prep names it), else the
  // practice default. Held in state so managing one does not lose the place.
  const [pickedId, setPickedId] = useState<string>(params.get("template") ?? "");
  const all = templates.data ?? [];
  const template = all.find((t) => t.id === pickedId)
    ?? all.find((t) => t.is_default) ?? all[0];
  const save = useMutation({
    mutationFn: (id: string) => api.patch<{ changed: string[] }>(
      `/api/strategy-templates/${id}/`,
      { questions: Object.entries(edits).map(([key, edit]) => ({ key, ...edit })) }),
    onSuccess: (result) => {
      setNote(`Saved ${result.changed.length} question${result.changed.length === 1 ? "" : "s"}. `
        + "Sessions already under way are untouched.");
      setEdits({});
      qc.invalidateQueries({ queryKey: ["strategy-templates"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  if (me.role !== "FF") {
    return (
      <Banner kind="info">
        The template is the founder fractional's to edit. You can read every
        question on a session itself.
      </Banner>
    );
  }
  const pending = Object.keys(edits).length;
  const refresh = (picked?: Template, message?: string) => {
    if (picked) setPickedId(picked.id);
    if (message) setNote(message);
    qc.invalidateQueries({ queryKey: ["strategy-templates"] });
  };

  return (
    <>
      <h1>The session template</h1>
      {note && <Banner kind="ok">{note}</Banner>}
      {!template ? <p>Loading the template…</p> : (
        <>
          <Card>
            <div className="row">
              <Field label="Template">
                <select aria-label="Template" value={template.id} disabled={pending > 0}
                  onChange={(e) => { setPickedId(e.target.value); setEdits({}); }}>
                  {all.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}{t.is_default ? " — practice default" : ""}
                      {t.archived_at ? " (archived)" : ""}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {pending > 0 && (
              <p className="tiny muted">Save or discard your changes before switching.</p>
            )}
            <p className="small muted">
              <strong>{template.name}</strong> · {template.discipline} · v{template.version}
              {template.is_default && <> · <Pill kind="ok">practice default</Pill></>}
              {template.archived_at && <> · <Pill kind="warn">archived</Pill></>}
              {" "}· {template.sessions} session{template.sessions === 1 ? "" : "s"} started
              from it
            </p>
            <p className="small muted">
              You can change the wording, move a question between the pre-call form
              and the call, and set whether it is a must-ask. A session already
              under way keeps the questions it started with — it renders from its own
              copy, so nothing here can move under you mid-call.
            </p>
            <button className="primary" disabled={!pending || save.isPending}
              onClick={() => save.mutate(template.id)}>
              Save {pending || ""} change{pending === 1 ? "" : "s"}
            </button>
            {pending > 0 && (
              <button className="ghost" onClick={() => setEdits({})}>Discard</button>
            )}
          </Card>

          <Manage template={template} onDone={refresh} />

          {template.sections.map((section) => (
            <Card key={section.code} title={section.title}
              actions={section.time_budget_minutes
                ? <Pill>{section.time_budget_minutes} min</Pill> : undefined}>
              {section.questions.length === 0 && (
                <p className="small muted">
                  No questions here — this section's content lives on the session itself.
                </p>
              )}
              {section.questions.map((question) => {
                const edit = edits[question.key] ?? {};
                const askWhen = edit.ask_when ?? question.ask_when;
                const mustAsk = edit.must_ask ?? question.must_ask;
                return (
                  <div key={question.key} className="field" style={{ marginBottom: "1rem" }}>
                    <label htmlFor={`prompt-${question.key}`}>
                      {question.key}
                      {question.area ? ` · ${question.area}` : ""}
                      {/* What kind of question this is, beside the box that
                          rewords it. Six ratings were reworded into essay
                          questions on 22 September because nothing on this
                          screen said they were ratings. */}
                      {" "}<Pill kind={question.response_schema === "rating_1_10"
                        ? "ai" : ""}>{SCHEMA_LABELS[question.response_schema]
                          ?? question.response_schema}</Pill>
                      {question.is_financial && <> <Pill kind="bad">financial</Pill></>}
                    </label>
                    {question.response_schema === "rating_1_10" && (
                      <p className="tiny muted" style={{ margin: "0 0 4px" }}>
                        Rated 1–10. Reword the lead-in if you like, but start with
                        the component's name and ask something a score answers.
                      </p>
                    )}
                    <textarea id={`prompt-${question.key}`} rows={2}
                      aria-label={`Wording of ${question.key}`}
                      value={edit.prompt ?? question.prompt_template ?? question.prompt}
                      onChange={(e) => setEdits({ ...edits,
                        [question.key]: { ...edit, prompt: e.target.value } })} />
                    <div className="row">
                      <select aria-label={`When to ask ${question.key}`} value={askWhen}
                        onChange={(e) => setEdits({ ...edits, [question.key]: {
                          ...edit, ask_when: e.target.value as "precall" | "live" } })}>
                        <option value="precall">On the pre-call form</option>
                        <option value="live">In the call</option>
                      </select>
                      <label className="small"
                        style={{ display: "inline-flex", gap: ".4rem" }}>
                        <input type="checkbox" style={{ width: "auto" }} checked={mustAsk}
                          aria-label={`Must ask ${question.key}`}
                          onChange={(e) => setEdits({ ...edits, [question.key]: {
                            ...edit, must_ask: e.target.checked } })} />
                        Must ask
                      </label>
                    </div>
                  </div>
                );
              })}
            </Card>
          ))}
        </>
      )}
    </>
  );
}

/** Rename, duplicate, default, archive — and Restore from seed, which makes a
 *  new template rather than touching this one. Every one of them is audited
 *  server-side, and none of them reaches a session already started. */
function Manage({ template, onDone }: {
  template: Template; onDone: (picked?: Template, message?: string) => void;
}) {
  const [name, setName] = useState(template.name);
  const [copyName, setCopyName] = useState("");
  const [seedName, setSeedName] = useState("Operations — generic");
  const [error, setError] = useState("");
  useEffect(() => { setName(template.name); setError(""); }, [template.id, template.name]);

  const run = useMutation({
    mutationFn: ({ url, body, method }: { url: string; body?: object;
                                         method?: "post" | "patch" }) =>
      method === "patch" ? api.patch<{ template: Template }>(url, body ?? {})
        .then((r) => r.template)
        : api.post<Template>(url, body ?? {}),
    onError: (e: Error) => setError(e.message),
  });
  const base = `/api/strategy-templates/${template.id}/`;
  const act = (url: string, message: (t: Template) => string, body?: object,
               method?: "post" | "patch") => {
    setError("");
    run.mutate({ url, body, method }, {
      onSuccess: (t) => onDone(t, message(t)),
    });
  };

  return (
    <Card title="Manage templates">
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row">
        <Field label="Name">
          <input aria-label="Template name" value={name}
            onChange={(e) => setName(e.target.value)} />
        </Field>
        <button disabled={run.isPending || !name.trim() || name.trim() === template.name}
          onClick={() => act(base, (t) => `Renamed to “${t.name}”.`, { name }, "patch")}>
          Rename
        </button>
      </div>
      <div className="row">
        <Field label="Duplicate as">
          <input aria-label="Name for the copy" value={copyName}
            placeholder={`${template.name} (copy)`}
            onChange={(e) => setCopyName(e.target.value)} />
        </Field>
        <button disabled={run.isPending}
          onClick={() => act(`${base}duplicate/`,
            (t) => `Made “${t.name}”, a full copy. You are editing the copy now.`,
            copyName.trim() ? { name: copyName.trim() } : {})}>
          Duplicate
        </button>
      </div>
      <div className="row">
        {!template.is_default && !template.archived_at && (
          <button disabled={run.isPending}
            onClick={() => act(`${base}set-default/`,
              (t) => `“${t.name}” is now the practice default for new sessions.`)}>
            Make this the practice default
          </button>
        )}
        {template.archived_at ? (
          <button disabled={run.isPending}
            onClick={() => act(`${base}unarchive/`, (t) => `“${t.name}” is back in the picker.`)}>
            Restore from archive
          </button>
        ) : (
          <button className="ghost" disabled={run.isPending || template.is_default}
            title={template.is_default
              ? "The practice default cannot be archived. Make another the default first."
              : ""}
            onClick={() => act(`${base}archive/`,
              (t) => `“${t.name}” is archived. Sessions started from it are unchanged.`)}>
            Archive
          </button>
        )}
      </div>
      <hr />
      <p className="small muted">
        <strong>Restore from seed</strong> makes a new template exactly as the
        Operations seed ships it. It never overwrites a template you have edited.
      </p>
      <div className="row">
        <Field label="New template's name">
          <input aria-label="Name for the template from the seed" value={seedName}
            onChange={(e) => setSeedName(e.target.value)} />
        </Field>
        <button disabled={run.isPending || !seedName.trim()}
          onClick={() => act("/api/strategy-templates/restore-from-seed/",
            (t) => `Made “${t.name}” from the seed. You are editing it now.`,
            { name: seedName.trim() })}>
          Restore from seed
        </button>
      </div>
    </Card>
  );
}
