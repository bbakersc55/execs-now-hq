import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Banner, Card, Field, Pill } from "../components/ui";
import { Me, StrategySessionRow, StrategyTemplateRow as Template, api } from "../lib/api";

type Edit = { prompt?: string; ask_when?: "precall" | "live"; must_ask?: boolean;
              ask_if_time?: boolean };

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
  // Kept past the prefill, which clears the URL: Save goes back to the session
  // the prep came from, where the send controls are (dry run, 2026-09-26).
  const [returnTo] = useState(params.get("prefill") ? fromSession : null);
  const navigate = useNavigate();
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
  // Section time budgets, saved with the wording (owner, 2026-09-26).
  const [budgets, setBudgets] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (id: string) => api.patch<{ changed: string[] }>(
      `/api/strategy-templates/${id}/`,
      { questions: Object.entries(edits).map(([key, edit]) => ({ key, ...edit })),
        sections: Object.entries(budgets).map(([code, minutes]) => ({
          code, time_budget_minutes: minutes === "" ? null : Number(minutes) })) }),
    onSuccess: (result) => {
      const budgetCount = Object.keys(budgets).length;
      setNote(`Saved ${result.changed.length} question${result.changed.length === 1 ? "" : "s"}`
        + (budgetCount ? ` and ${budgetCount} time budget${budgetCount === 1 ? "" : "s"}` : "")
        + ". Sessions already under way are untouched.");
      setEdits({});
      setBudgets({});
      qc.invalidateQueries({ queryKey: ["strategy-templates"] });
      if (returnTo) navigate(`/strategy/${returnTo}`, { state: { templateUpdated: true } });
    },
    onError: (e: Error) => setNote(e.message),
  });
  // Add, remove, reorder: each its own call, each immediate and audited.
  const shape = useMutation({
    mutationFn: ({ suffix, body }: { suffix: string; body: object }) =>
      api.post<Template>(`/api/strategy-templates/${template!.id}/${suffix}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy-templates"] }),
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
  const pending = Object.keys(edits).length + Object.keys(budgets).length;
  const refresh = (picked?: Template, message?: string) => {
    if (picked) setPickedId(picked.id);
    if (message) setNote(message);
    qc.invalidateQueries({ queryKey: ["strategy-templates"] });
  };

  return (
    <>
      <h1>The session templates</h1>
      {returnTo && (
        <p className="small">
          <Link to={`/strategy/${returnTo}`}>Back to the session</Link> — Save takes
          you back there too.
        </p>
      )}
      {note && <Banner kind="ok">{note}</Banner>}
      {!template ? <p>Loading the template…</p> : (
        <>
          <Card>
            <div className="row">
              <Field label="Template">
                <select aria-label="Template" value={template.id} disabled={pending > 0}
                  onChange={(e) => { setPickedId(e.target.value); setEdits({}); setBudgets({}); }}>
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
              Change the wording, move a question between the pre-call form and the
              call, mark it must-ask or ask-if-time, add, remove and reorder, and set
              each section's time. A session already under way keeps the questions
              it started with — it renders from its own copy, so nothing here can
              move under you mid-call.
            </p>
            <button className="primary" disabled={!pending || save.isPending}
              onClick={() => save.mutate(template.id)}>
              Save {pending || ""} change{pending === 1 ? "" : "s"}
            </button>
            {pending > 0 && (
              <button className="ghost" onClick={() => { setEdits({}); setBudgets({}); }}>
                Discard</button>
            )}
          </Card>

          <Manage template={template} onDone={refresh} />

          {template.sections.map((section) => (
            <Card key={section.code} title={section.title}
              actions={
                <label className="small inline">
                  <input type="number" min={0} max={240} style={{ width: "4.5rem" }}
                    aria-label={`Minutes for ${section.title}`}
                    value={budgets[section.code]
                      ?? (section.time_budget_minutes === null ? ""
                        : String(section.time_budget_minutes))}
                    onChange={(e) => setBudgets({ ...budgets,
                                                  [section.code]: e.target.value })} />
                  {" "}min
                </label>
              }>
              {section.questions.length === 0 && (
                <p className="small muted">
                  No questions here — this section's content lives on the session itself.
                </p>
              )}
              {section.questions.map((question, index) => {
                const edit = edits[question.key] ?? {};
                const askWhen = edit.ask_when ?? question.ask_when;
                const mustAsk = edit.must_ask ?? question.must_ask;
                const ifTime = edit.ask_if_time ?? !!question.ask_if_time;
                const keys = section.questions.map((q) => q.key);
                const move = (to: number) => {
                  const next = keys.filter((k) => k !== question.key);
                  next.splice(to, 0, question.key);
                  shape.mutate({ suffix: "reorder/",
                                 body: { section: section.code, keys: next } });
                };
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
                      <label className="small"
                        style={{ display: "inline-flex", gap: ".4rem" }}>
                        <input type="checkbox" style={{ width: "auto" }} checked={ifTime}
                          aria-label={`Ask ${question.key} only if time`}
                          onChange={(e) => setEdits({ ...edits, [question.key]: {
                            ...edit, ask_if_time: e.target.checked } })} />
                        If time
                      </label>
                      <button className="ghost small" disabled={index === 0 || shape.isPending}
                        aria-label={`Move ${question.key} up`}
                        onClick={() => move(index - 1)}>↑</button>
                      <button className="ghost small"
                        disabled={index === keys.length - 1 || shape.isPending}
                        aria-label={`Move ${question.key} down`}
                        onClick={() => move(index + 1)}>↓</button>
                      <button className="ghost small" disabled={shape.isPending}
                        aria-label={`Remove ${question.key}`}
                        onClick={() => {
                          if (!confirm("Remove this question from the template? It is "
                            + "archived, not deleted: sessions that asked it keep it.")) return;
                          shape.mutate({ suffix: "remove-question/",
                                         body: { key: question.key } });
                        }}>Remove</button>
                    </div>
                  </div>
                );
              })}
              <AddQuestion section={section.code} title={section.title}
                busy={shape.isPending}
                onAdd={(body, added) => shape.mutate(
                  { suffix: "questions/", body: { section: section.code, ...body } },
                  { onSuccess: added })} />
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
  const [variant, setVariant] = useState("");
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
        <Field label="Cut">
          <select aria-label="Which cut of the seed" value={variant}
            onChange={(e) => {
              setVariant(e.target.value);
              setSeedName(e.target.value === "sixty" ? "60-minute Operations"
                : "Operations — generic");
            }}>
            <option value="">The full seed (about 75 minutes)</option>
            <option value="sixty">60 minutes — ★ kept, the rest if time</option>
          </select>
        </Field>
        <button disabled={run.isPending || !seedName.trim()}
          onClick={() => act("/api/strategy-templates/restore-from-seed/",
            (t) => `Made “${t.name}” from the seed. You are editing it now.`,
            { name: seedName.trim(), variant })}>
          Restore from seed
        </button>
      </div>
    </Card>
  );
}

const SCHEMAS = Object.keys(SCHEMA_LABELS);

/** A new question in one section. The server holds it to the same rewording
 *  guard as any wording — a new rating is a lead-in to a number. */
function AddQuestion({ section, title, busy, onAdd }: {
  section: string; title: string; busy: boolean;
  /** `added` runs only once the server has accepted it: a refused wording
   *  stays in the box to be fixed. */
  onAdd: (body: Record<string, unknown>, added: () => void) => void;
}) {
  const [open, setOpen] = useState(false);
  const blank = { prompt: "", response_schema: "free_text", ask_when: "live", area: "",
                  must_ask: false, is_financial: false, has_fractional_note: false,
                  ask_if_time: false };
  const [form, setForm] = useState(blank);
  if (!open) {
    return <button className="ghost small" onClick={() => setOpen(true)}>
      Add a question to {title}</button>;
  }
  const flag = (name: keyof typeof blank, label: string) => (
    <label className="small" style={{ display: "inline-flex", gap: ".4rem" }}>
      <input type="checkbox" style={{ width: "auto" }} checked={!!form[name]}
        aria-label={`${label} (new question in ${section})`}
        onChange={(e) => setForm({ ...form, [name]: e.target.checked })} />
      {label}
    </label>
  );
  return (
    <div className="card">
      <Field label="Wording">
        <textarea rows={2} aria-label={`Wording of the new question in ${section}`}
          value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} />
      </Field>
      <div className="row">
        <select aria-label={`Kind of answer (new question in ${section})`}
          value={form.response_schema}
          onChange={(e) => setForm({ ...form, response_schema: e.target.value })}>
          {SCHEMAS.map((k) => <option key={k} value={k}>{SCHEMA_LABELS[k]}</option>)}
        </select>
        <select aria-label={`When to ask (new question in ${section})`} value={form.ask_when}
          onChange={(e) => setForm({ ...form, ask_when: e.target.value })}>
          <option value="precall">On the pre-call form</option>
          <option value="live">In the call</option>
        </select>
        <input aria-label={`Area (new question in ${section})`} placeholder="Area (optional)"
          value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} />
      </div>
      <div className="row">
        {flag("must_ask", "Must ask")}
        {flag("ask_if_time", "If time")}
        {flag("has_fractional_note", "Fractional note")}
        {flag("is_financial", "Financial")}
      </div>
      <div className="row">
        <button className="primary" disabled={busy || !form.prompt.trim()}
          onClick={() => onAdd(form, () => { setForm(blank); setOpen(false); })}>
          Add the question</button>
        <button className="ghost" onClick={() => { setForm(blank); setOpen(false); }}>
          Cancel</button>
      </div>
    </div>
  );
}
