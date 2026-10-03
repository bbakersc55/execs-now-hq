import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill } from "../components/ui";
import {
  BuilderSection, BuilderSettings, BuilderTemplate, Me, SectionKind, StrategyQuestion,
  StrategySessionRow, api,
} from "../lib/api";

/**
 * The template builder (P3; matrix 10.1a, 10.1b).
 *
 * One page, the eight parts of a session in order. The practice owner writes
 * the questions, names what is rated, sets the words on the prospect's
 * document and decides whether "What they value" is in it. Each part takes one
 * kind of question, which the builder sets — the practice writes the words.
 *
 * **Nothing here reaches a session already created**: each session keeps the
 * template as it was on the day it was started.
 */

/** What each part is for, in a sentence, and what its questions are called. */
const PARTS: Record<SectionKind, { hint: string; item: string; add: string }> = {
  precall: {
    hint: "Sent to the prospect before the call, as a form or in an email. About a "
      + "dozen works well. Each takes a written answer.",
    item: "question", add: "Add a question" },
  ratings: {
    hint: "Taken on the call. Each one is a statement the prospect scores from 1 to 10 "
      + "for how true it is, so write a statement, not an open question. The label is "
      + "what the chart calls it.",
    item: "rated item", add: "Add a rated item" },
  diagnostic: {
    hint: "Before the call, Claude proposes questions from what the prospect wrote, and "
      + "you accept the ones you want. The questions below are asked only when "
      + "nothing proposed is accepted.",
    item: "fixed question", add: "Add a fixed question" },
  mirror: {
    hint: "Asked first, then read back: where they said they want to go, and what "
      + "unlocks it. Claude drafts the mirror from these answers and the diagnostic, "
      + "for you to accept or rewrite.",
    item: "question", add: "Add a question" },
  map: {
    hint: "Claude proposes rows from the conversation; you accept, edit or discard "
      + "each one. The map holds five. There is nothing to write here but the time.",
    item: "question", add: "" },
  values: {
    hint: "What matters to them, in their words, and why.",
    item: "value", add: "Add a value" },
  paths: {
    hint: "Always two: carrying on themselves, or working with you. Reword them; "
      + "they cannot be added to or removed.",
    item: "path", add: "" },
  scope: {
    hint: "What you agree before the call ends. Mark an item as money to keep it from "
      + "assistants and off the document unless you choose to include it.",
    item: "item", add: "Add an item" },
};

type Problem = { where: string; text: string } | null;

export function TemplateBuilder({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const path = `/api/strategy-template-builder/${id}/`;
  const mayEdit = me.role === "FF";
  const [problem, setProblem] = useState<Problem>(null);
  const [note, setNote] = useState("");

  const template = useQuery<BuilderTemplate>({
    queryKey: ["template-builder", id], queryFn: () => api.get<BuilderTemplate>(path),
  });
  const send = useMutation({
    mutationFn: ({ url, body, method }: { url: string; body: object; where: string;
                                         method?: "post" | "patch" }) =>
      method === "patch" ? api.patch<unknown>(url, body) : api.post<unknown>(url, body),
    onSuccess: () => {
      setProblem(null);
      qc.invalidateQueries({ queryKey: ["template-builder", id] });
      qc.invalidateQueries({ queryKey: ["strategy-templates"] });
    },
    onError: (e: Error, { where }) => setProblem({ where, text: e.message }),
  });
  /** One change, with where on the page to say so if it is refused. `then`
   *  runs only once the server has taken it. */
  const change = (suffix: string, body: object, where: string, then?: () => void) =>
    send.mutate({ url: `${path}${suffix}`, body, where }, { onSuccess: then });
  const manage = (suffix: string, body: object, where: string,
                  method: "post" | "patch" = "post") =>
    send.mutate({ url: `/api/strategy-templates/${id}/${suffix}`, body, where, method });

  // Arrived from a session's prep with suggested wordings: they fill the
  // boxes, unsaved. Nothing is saved until Save is pressed beside each.
  const [params, setParams] = useSearchParams();
  const fromSession = params.get("session");
  const prefillKeys = params.get("prefill") ?? "";
  const [returnTo] = useState(prefillKeys ? fromSession : null);
  const [suggested, setSuggested] = useState<Record<string, string>>({});
  const session = useQuery<StrategySessionRow>({
    queryKey: ["strategy-session", fromSession],
    queryFn: () => api.get<StrategySessionRow>(`/api/strategy-sessions/${fromSession}/`),
    enabled: !!fromSession && !!prefillKeys,
  });
  useEffect(() => {
    if (!prefillKeys || !session.data?.prep) return;
    const wanted = prefillKeys.split(",");
    const rows = session.data.prep.rewordings.filter((r) => wanted.includes(r.key));
    if (rows.length === 0) return;
    setSuggested(Object.fromEntries(rows.map((row) => [row.key, row.suggested])));
    setNote(`Filled in ${rows.length} question${rows.length === 1 ? "" : "s"} from your `
      + "prep. Nothing is saved until you press Save beside each one.");
    setParams({}, { replace: true });
  }, [prefillKeys, session.data, setParams]);

  if (template.isLoading) return <p>Opening the template…</p>;
  if (template.isError) {
    return (
      <>
        <Banner kind="bad">{(template.error as Error).message}</Banner>
        <p><Link to="/strategy/template">Back to the templates</Link></p>
      </>
    );
  }
  const t = template.data!;
  const busy = send.isPending;
  const said = (where: string) => problem?.where === where
    ? <Banner kind="bad">{problem.text}</Banner> : null;
  const setting = (changes: Partial<BuilderSettings>, where: string) =>
    change("settings/", { settings: changes }, where);
  const chips = t.sections.flatMap((s) => s.questions).filter((q) => q.pdf_chip).length;

  return (
    <>
      <PageHead title={t.name}
        sub={<>A template you built. <Link to="/strategy/template">All templates</Link>
          {returnTo && <> · <Link to={`/strategy/${returnTo}`}>Back to the session</Link></>}
        </>} />
      {!mayEdit && (
        <Banner kind="info">
          The template is the practice owner's to edit. You can read it here.
        </Banner>
      )}
      {note && <Banner kind="ok">{note}</Banner>}

      <Card title="This template"
        actions={t.ready ? <Pill kind="ok">Ready to run</Pill>
          : <Pill kind="warn">Not ready to run</Pill>}>
        {!t.ready && (
          <ul aria-label="What this template still needs" className="small">
            {t.missing.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
        <p className="small muted">
          Editing this template never changes a session already created: each session
          keeps the questions it was started with.
          {t.archived_at && <> <Pill kind="warn">archived</Pill></>}
        </p>
        {said("template")}
        <div className="row">
          <Saved label="Name" ariaLabel="Template name" value={t.name} disabled={!mayEdit || busy}
            onSave={(name) => manage("", { name }, "template", "patch")} />
          {t.is_default ? <Pill kind="ok">practice default</Pill> : mayEdit && !t.archived_at && (
            <button disabled={busy || !t.ready}
              title={t.ready ? "" : "A template has to be ready to run to be the default."}
              onClick={() => manage("set-default/", {}, "template")}>
              Make this the practice default
            </button>
          )}
        </div>
      </Card>

      {t.sections.map((section) => (
        <Part key={section.code} section={section} template={t} mayEdit={mayEdit} busy={busy}
          chips={chips} suggested={suggested} problem={said(section.code)}
          change={(suffix, body, then) => change(suffix, body, section.code, then)}
          setting={(changes) => setting(changes, section.code)} />
      ))}

      <Card title="Wording for Claude">
        <p className="small muted">
          How Claude should describe you when it drafts for a session from this
          template, as in "questions for a business consultant to ask". Everything
          Claude drafts still waits for you to accept it.
        </p>
        {said("claude")}
        <Saved label="You are" ariaLabel="How Claude describes the practice"
          value={t.settings.advisor_role} disabled={!mayEdit || busy} maxLength={80}
          onSave={(advisor_role) => setting({ advisor_role }, "claude")} />
      </Card>
    </>
  );
}

/** One part of the session: its title and time, what it holds, and what the
 *  practice can change about it. */
function Part({ section, template, mayEdit, busy, chips, suggested, problem, change, setting }: {
  section: BuilderSection; template: BuilderTemplate; mayEdit: boolean; busy: boolean;
  chips: number; suggested: Record<string, string>; problem: React.ReactNode;
  change: (suffix: string, body: object, then?: () => void) => void;
  setting: (changes: Partial<BuilderSettings>) => void;
}) {
  const part = PARTS[section.kind];
  const off = !mayEdit || busy;
  const keys = section.questions.map((q) => q.key);
  const move = (key: string, to: number) => {
    const next = keys.filter((k) => k !== key);
    next.splice(to, 0, key);
    change("reorder/", { section: section.code, keys: next });
  };
  const s = template.settings;

  if (!section.included) {
    return (
      <Card title={section.title} actions={<Pill>not in this template</Pill>}>
        <p className="small muted">
          Sessions started from this template skip this part. Its questions are kept,
          and come back if you put it back.
        </p>
        {problem}
        {mayEdit && (
          <button disabled={busy}
            onClick={() => change("include/", { kind: section.kind, included: true })}>
            Put “{section.title}” back in
          </button>
        )}
      </Card>
    );
  }

  return (
    <Card title={section.title}
      actions={section.kind !== "precall" && (
        <Saved compact label="minutes" ariaLabel={`Minutes for ${section.title}`}
          type="number" value={section.time_budget_minutes === null ? ""
            : String(section.time_budget_minutes)} disabled={off}
          onSave={(minutes) => change("section/", {
            code: section.code, time_budget_minutes: minutes === "" ? null : Number(minutes) })} />
      )}>
      <p className="small muted" style={{ marginTop: 0 }}>{part.hint}</p>
      {problem}
      <Saved label="Section title" ariaLabel={`Title of ${section.title}`} value={section.title}
        disabled={off} maxLength={255}
        onSave={(title) => change("section/", { code: section.code, title })} />

      {section.kind === "ratings" && (
        <Saved label="Scale line (shown above the ratings and under the chart)"
          ariaLabel="Rating scale line" value={s.rating_scale} disabled={off} maxLength={160}
          onSave={(rating_scale) => setting({ rating_scale })} />
      )}
      {section.kind === "diagnostic" && (
        <Saved label="Diagnostic questions per session (1 to 8)" type="number"
          ariaLabel="Diagnostic questions per session" value={String(s.diagnostic_size)}
          disabled={off}
          onSave={(size) => setting({ diagnostic_size: Number(size) })} />
      )}
      {section.kind === "paths" && (["a", "b"] as const).map((side) => (
        <div key={side} className="card" style={{ marginBottom: ".5rem" }}>
          <p className="small" style={{ margin: 0 }}>
            <strong>Path {side.toUpperCase()} on the document</strong>
          </p>
          <Saved label="Title" ariaLabel={`Path ${side.toUpperCase()} title on the document`}
            value={s[`path_${side}_title`]} disabled={off} maxLength={80}
            onSave={(title) => setting({ [`path_${side}_title`]: title })} />
          {[0, 1].map((line) => (
            <Saved key={line} label={`Line ${line + 1}`} maxLength={160} disabled={off}
              ariaLabel={`Path ${side.toUpperCase()} line ${line + 1} on the document`}
              value={s[`path_${side}_points`][line]}
              onSave={(text) => setting({ [`path_${side}_points`]:
                s[`path_${side}_points`].map((was, i) => (i === line ? text : was)) })} />
          ))}
        </div>
      ))}

      {section.questions.length === 0 && part.add && (
        <p className="small muted">No {part.item}s yet.</p>
      )}
      {section.questions.map((question, index) => (
        <QuestionEditor key={question.key} question={question} section={section}
          suggested={suggested[question.key]} off={off} mayEdit={mayEdit} chips={chips}
          isFirst={index === 0} isLast={index === keys.length - 1}
          onSave={(changes) => change("question/", { key: question.key, ...changes })}
          onMove={(by) => move(question.key, index + by)}
          onRemove={() => {
            if (!confirm(`Remove this ${part.item} from the template? Sessions that `
              + "already asked it keep it.")) return;
            change("remove-question/", { key: question.key });
          }} />
      ))}

      {mayEdit && part.add && section.questions.length < section.most && (
        <AddQuestion section={section} label={part.add} busy={busy}
          onAdd={(body, added) =>
            change("questions/", { section: section.code, ...body }, added)} />
      )}
      {part.add && section.questions.length >= section.most && (
        <p className="tiny muted">This part holds {section.most} at most.</p>
      )}

      {mayEdit && section.optional && (
        <p style={{ marginBottom: 0 }}>
          <button className="ghost small" disabled={busy}
            onClick={() => {
              if (!confirm(`Take “${section.title}” out of this template? Sessions started `
                + "from it will skip this part. Sessions already created keep it.")) return;
              change("include/", { kind: section.kind, included: false });
            }}>
            Take “{section.title}” out of this template
          </button>
        </p>
      )}
    </Card>
  );
}

/** One question: its wording, its label where it has one, and its marks. */
function QuestionEditor({ question, section, suggested, off, mayEdit, chips, isFirst, isLast,
                          onSave, onMove, onRemove }: {
  question: StrategyQuestion; section: BuilderSection; suggested?: string; off: boolean;
  mayEdit: boolean; chips: number; isFirst: boolean; isLast: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onMove: (by: number) => void; onRemove: () => void;
}) {
  const saved = question.prompt_template ?? question.prompt;
  const [prompt, setPrompt] = useState(suggested ?? saved);
  const [label, setLabel] = useState(question.label ?? "");
  useEffect(() => { setPrompt(suggested ?? saved); }, [saved, suggested]);
  useEffect(() => { setLabel(question.label ?? ""); }, [question.label]);
  const kind = section.kind;
  const hasLabel = kind === "ratings" || kind === "precall";
  const dirty = prompt !== saved || (hasLabel && label !== (question.label ?? ""));
  const name = question.label || saved;
  const check = (field: string, text: string, checked: boolean, disabled = false,
                 title = "") => (
    <label className="small" style={{ display: "inline-flex", gap: ".4rem" }} title={title}>
      <input type="checkbox" style={{ width: "auto" }} checked={checked}
        disabled={off || disabled} aria-label={`${text}: ${name}`}
        onChange={(e) => onSave({ [field]: e.target.checked })} />
      {text}
    </label>
  );
  return (
    <div className="field" style={{ marginBottom: "1rem" }}>
      {suggested !== undefined && suggested !== saved && (
        <p className="tiny" style={{ margin: "0 0 4px" }}>
          <Pill kind="ai">from your prep</Pill> Not saved yet.
        </p>
      )}
      <div className="row" style={{ alignItems: "flex-start" }}>
        {hasLabel && (
          <input aria-label={`Label of: ${saved}`} value={label} maxLength={60}
            placeholder={kind === "ratings" ? "Label" : "Label (optional)"}
            style={{ width: "11rem" }} disabled={off}
            onChange={(e) => setLabel(e.target.value)} />
        )}
        <textarea rows={2} aria-label={`Wording of: ${saved}`} value={prompt}
          style={{ flex: 1 }} disabled={off} onChange={(e) => setPrompt(e.target.value)} />
      </div>
      <div className="row">
        {dirty && (
          <>
            <button className="primary small" disabled={off || !prompt.trim()}
              aria-label={`Save: ${saved}`}
              onClick={() => onSave({
                ...(prompt !== saved ? { prompt } : {}),
                ...(hasLabel && label !== (question.label ?? "") ? { label } : {}) })}>
              Save
            </button>
            <button className="ghost small" onClick={() => {
              setPrompt(saved); setLabel(question.label ?? ""); }}>Discard</button>
          </>
        )}
        {kind === "precall" && check("pdf_chip", "Show in the PDF header",
          !!question.pdf_chip, !question.pdf_chip && (chips >= 3 || !question.label),
          !question.label ? "Give it a label first."
            : chips >= 3 && !question.pdf_chip ? "The header shows three at most." : "")}
        {kind === "scope" && check("is_financial", "Money", question.is_financial)}
        {(kind === "diagnostic" || kind === "mirror" || kind === "values" || kind === "scope")
          && check("must_ask", "Must ask", question.must_ask)}
        {mayEdit && !section.fixed_count && (
          <>
            <button className="ghost small" disabled={off || isFirst}
              aria-label={`Move up: ${name}`} onClick={() => onMove(-1)}>↑</button>
            <button className="ghost small" disabled={off || isLast}
              aria-label={`Move down: ${name}`} onClick={() => onMove(1)}>↓</button>
            <button className="ghost small" disabled={off} aria-label={`Remove: ${name}`}
              onClick={onRemove}>Remove</button>
          </>
        )}
      </div>
    </div>
  );
}

/** A new question in one part. The part decides what kind of answer it takes. */
function AddQuestion({ section, label, busy, onAdd }: {
  section: BuilderSection; label: string; busy: boolean;
  /** `added` runs only once the server has accepted it: a refused wording
   *  stays in the box to be fixed. */
  onAdd: (body: Record<string, unknown>, added: () => void) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const rated = section.kind === "ratings";
  const hasLabel = rated || section.kind === "precall";
  return (
    <div className="card">
      <div className="row" style={{ alignItems: "flex-start" }}>
        {hasLabel && (
          <input aria-label={`Label of the new one in ${section.title}`} value={name}
            maxLength={60} placeholder={rated ? "Label" : "Label (optional)"}
            style={{ width: "11rem" }} onChange={(e) => setName(e.target.value)} />
        )}
        <textarea rows={2} aria-label={`Wording of the new one in ${section.title}`}
          value={prompt} style={{ flex: 1 }}
          placeholder={rated ? "Plan — Our plan is written down and shared."
            : "The wording, as you would say it"}
          onChange={(e) => setPrompt(e.target.value)} />
      </div>
      <button disabled={busy || !prompt.trim() || (rated && !name.trim())}
        onClick={() => onAdd({ prompt: prompt.trim(), ...(hasLabel ? { label: name.trim() } : {}) },
                             () => { setPrompt(""); setName(""); })}>
        {label}
      </button>
    </div>
  );
}

/** A field with its own Save, shown only once it differs from what is stored. */
function Saved({ label, ariaLabel, value, onSave, disabled, maxLength, type, compact }: {
  label: string; ariaLabel: string; value: string; onSave: (value: string) => void;
  disabled?: boolean; maxLength?: number; type?: "number"; compact?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  const dirty = draft !== value;
  const input = (
    <input aria-label={ariaLabel} value={draft} disabled={disabled} maxLength={maxLength}
      type={type} min={type === "number" ? 0 : undefined}
      style={compact || type === "number" ? { width: "4.5rem" } : undefined}
      onChange={(e) => setDraft(e.target.value)} />
  );
  const save = dirty && (
    <button className="primary small" disabled={disabled || (!type && !draft.trim())}
      aria-label={`Save ${ariaLabel}`} onClick={() => onSave(draft.trim())}>Save</button>
  );
  if (compact) {
    return <span className="small inline">{input} {label} {save}</span>;
  }
  return (
    <div className="row" style={{ alignItems: "flex-end" }}>
      <Field label={label}>{input}</Field>
      {save}
    </div>
  );
}
