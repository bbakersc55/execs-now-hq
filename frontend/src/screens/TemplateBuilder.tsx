import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill } from "../components/ui";
import {
  BuilderSection, BuilderSettings, BuilderTemplate, Me, PasteResult, SectionKind,
  StrategyQuestion, StrategySessionRow, api,
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
  custom: {
    hint: "A section of your own. Its answers are kept with the session and shown on "
      + "the call. Claude does not read it, and it is not on the document unless you "
      + "say so below.",
    item: "question", add: "Add a question" },
};

/** The kinds of answer a question in a section of your own can take. */
const ANSWER_KINDS: Record<string, string> = {
  free_text: "A written answer",
  diagnostic_triple: "Said / cause / tried",
  agreed_note: "Agreed, with a note",
};
const CUSTOM_MOST = 8;

type Problem = { where: string; text: string } | null;

/** The note on a template made from an example stays until it is dismissed,
 *  on this device: nothing about it is stored with the template. */
const noteKey = (id: string) => `execsnowhq.example-note.${id}`;
function noteDismissed(id: string) {
  try { return window.localStorage.getItem(noteKey(id)) === "1"; } catch { return false; }
}

/** Quiet, beside a line still worded exactly as the example has it. */
function FromExample() {
  return <span className="tiny muted" style={{ fontStyle: "italic" }}>from the example</span>;
}

export function TemplateBuilder({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const path = `/api/strategy-template-builder/${id}/`;
  const mayEdit = me.role === "FF";
  const [problem, setProblem] = useState<Problem>(null);
  const [note, setNote] = useState("");
  const [dismissed, setDismissed] = useState(() => noteDismissed(id ?? ""));

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
  // The sections asked on the call, in order: these are the ones that move.
  const onCall = t.sections.filter((s) => s.included && s.kind !== "precall")
    .map((s) => s.code);
  const own = t.sections.filter((s) => s.included && s.kind === "custom").length;
  // Made from an example (P3 §9): the role it gave Claude, while unchanged.
  const exampleRole = !!t.example?.unchanged_settings.includes("advisor_role");

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
      {t.example && !dismissed && (
        <Banner kind="info">
          Made from the Operations example. Read it through once as if you were the
          prospect: change what does not sound like you.{" "}
          <button className="ghost small" onClick={() => {
            try { window.localStorage.setItem(noteKey(t.id), "1"); } catch { /* not kept */ }
            setDismissed(true);
          }}>Dismiss</button>
        </Banner>
      )}

      <Card title="This template"
        actions={t.ready ? <Pill kind="ok">Ready to run</Pill>
          : <Pill kind="warn">Not ready to run</Pill>}>
        {!t.ready && (
          <ul aria-label="What this template still needs" className="small">
            {t.missing.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
        {/* Advice, never a block: the template runs as it is. */}
        {exampleRole && (
          <p className="small" aria-label="Worth a look">
            Wording for Claude still says <em>{t.settings.advisor_role}</em>. Change it
            below if that is not what you are.
          </p>
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
          {mayEdit && t.ready && !t.archived_at && (
            <Link className="btn" to={`/strategy?template=${t.id}`}>
              Start a session from this template</Link>
          )}
        </div>
      </Card>

      {t.sections.map((section) => (
        <Part key={section.code} section={section} template={t} mayEdit={mayEdit} busy={busy}
          place={onCall.indexOf(section.code)} last={onCall.length - 1}
          chips={chips} suggested={suggested} problem={said(section.code)}
          pasteUrl={`${path}paste/`}
          onPasted={() => {
            qc.invalidateQueries({ queryKey: ["template-builder", id] });
            qc.invalidateQueries({ queryKey: ["strategy-templates"] });
          }}
          change={(suffix, body, then) => change(suffix, body, section.code, then)}
          setting={(changes) => setting(changes, section.code)} />
      ))}

      {mayEdit && (own < CUSTOM_MOST ? (
        <AddSection sections={t.sections.filter((s) => s.included)} busy={busy}
          problem={said("sections")}
          onAdd={(body, added) => change("sections/", body, "sections", added)} />
      ) : (
        <p className="small muted">
          A template holds {CUSTOM_MOST} sections of your own at most.
        </p>
      ))}

      <Card title="Wording for Claude">
        <p className="small muted">
          How Claude should describe you when it drafts for a session from this
          template, as in "questions for a business consultant to ask". Everything
          Claude drafts still waits for you to accept it.
        </p>
        {said("claude")}
        {exampleRole && <p style={{ margin: "0 0 4px" }}><FromExample /></p>}
        <Saved label="You are" ariaLabel="How Claude describes the practice"
          value={t.settings.advisor_role} disabled={!mayEdit || busy} maxLength={80}
          onSave={(advisor_role) => setting({ advisor_role }, "claude")} />
      </Card>
    </>
  );
}

/** One part of the session: its title and time, what it holds, and what the
 *  practice can change about it. */
function Part({ section, template, mayEdit, busy, chips, suggested, problem, change, setting,
                pasteUrl, onPasted, place, last }: {
  /** Where it is among the sections on the call, and the last such place. */
  place: number; last: number;
  section: BuilderSection; template: BuilderTemplate; mayEdit: boolean; busy: boolean;
  chips: number; suggested: Record<string, string>; problem: React.ReactNode;
  pasteUrl: string; onPasted: () => void;
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
            onClick={() => change("include/", section.custom
              ? { code: section.code, included: true }
              : { kind: section.kind, included: true })}>
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
      {mayEdit && section.kind !== "precall" && (
        <p className="small" style={{ marginTop: 0 }}>
          <button className="ghost small" disabled={busy || place <= 0}
            aria-label={`Move section up: ${section.title}`}
            onClick={() => change("move-section/", { code: section.code, by: -1 })}>
            ↑ Earlier in the call</button>{" "}
          <button className="ghost small" disabled={busy || place >= last}
            aria-label={`Move section down: ${section.title}`}
            onClick={() => change("move-section/", { code: section.code, by: 1 })}>
            ↓ Later in the call</button>
        </p>
      )}
      <Saved label="Section title" ariaLabel={`Title of ${section.title}`} value={section.title}
        disabled={off} maxLength={255}
        onSave={(title) => change("section/", { code: section.code, title })} />

      {section.custom && (
        <label className="small" style={{ display: "flex", gap: ".4rem", margin: ".5rem 0" }}
          title={section.questions.length > 4
            ? "The document has room for four questions from a section." : ""}>
          <input type="checkbox" style={{ width: "auto" }} checked={!!section.show_in_pdf}
            disabled={off} aria-label={`Print this section on the document: ${section.title}`}
            onChange={(e) => change("section/", { code: section.code,
                                                  show_in_pdf: e.target.checked })} />
          Print this section on the document (written answers and agreed items only;
          two sections of up to four questions fit)
        </label>
      )}
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
      {mayEdit && part.add && section.questions.length < section.most && (
        <PasteSeveral section={section} item={part.item} url={pasteUrl} busy={busy}
          onPasted={onPasted} />
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
              change("include/", section.custom
                ? { code: section.code, included: false }
                : { kind: section.kind, included: false });
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
      {section.custom && (
        <p className="tiny muted" style={{ margin: "0 0 4px" }}>
          {ANSWER_KINDS[question.response_schema] ?? question.response_schema}
        </p>
      )}
      {(question.is_fractional_observation || (question.from_example && !dirty)) && (
        <p style={{ margin: "0 0 4px" }}>
          {/* Yours to notice on the call, never put to the prospect (FR-4.17). */}
          {question.is_fractional_observation && <><Pill>not asked aloud</Pill>{" "}</>}
          {question.from_example && !dirty && <FromExample />}
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
        {(kind === "diagnostic" || kind === "mirror" || kind === "values" || kind === "scope"
          || kind === "custom") && check("must_ask", "Must ask", question.must_ask)}
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
  const [answer, setAnswer] = useState("free_text");
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
      {section.schemas && (
        <select aria-label={`Kind of answer for the new one in ${section.title}`}
          value={answer} onChange={(e) => setAnswer(e.target.value)}>
          {section.schemas.map((schema) => (
            <option key={schema} value={schema}>{ANSWER_KINDS[schema] ?? schema}</option>
          ))}
        </select>
      )}{" "}
      <button disabled={busy || !prompt.trim() || (rated && !name.trim())}
        onClick={() => onAdd({ prompt: prompt.trim(),
                               ...(hasLabel ? { label: name.trim() } : {}),
                               ...(section.schemas ? { response_schema: answer } : {}) },
                             () => { setPrompt(""); setName(""); })}>
        {label}
      </button>
    </div>
  );
}

/** A section of the practice's own (P3 part two §3): a title, its minutes,
 *  and where on the call it goes. It starts empty and off the document. */
function AddSection({ sections, busy, problem, onAdd }: {
  sections: BuilderSection[]; busy: boolean; problem: React.ReactNode;
  onAdd: (body: Record<string, unknown>, added: () => void) => void;
}) {
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState("");
  const [after, setAfter] = useState("");
  return (
    <Card title="Add a section">
      <p className="small muted" style={{ marginTop: 0 }}>
        A section of your own, asked on the call. You write its questions, and each
        takes a written answer, said / cause / tried, or agreed with a note.
      </p>
      {problem}
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Title">
          <input aria-label="Title of the new section" value={title} maxLength={255}
            onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Minutes">
          <input aria-label="Minutes for the new section" type="number" min={0}
            style={{ width: "4.5rem" }} value={minutes}
            onChange={(e) => setMinutes(e.target.value)} />
        </Field>
        <Field label="Where">
          <select aria-label="Where the new section goes" value={after}
            onChange={(e) => setAfter(e.target.value)}>
            <option value="">Last on the call</option>
            {sections.map((section) => (
              <option key={section.code} value={section.code}>After “{section.title}”</option>
            ))}
          </select>
        </Field>
        <button disabled={busy || !title.trim()}
          onClick={() => onAdd({ title: title.trim(),
                                 ...(minutes === "" ? {} : { time_budget_minutes: Number(minutes) }),
                                 ...(after ? { after } : {}) },
                               () => { setTitle(""); setMinutes(""); setAfter(""); })}>
          Add a section
        </button>
      </div>
    </Card>
  );
}

/** Several at once, from the document a practice arrives with (P3 §9.5): one
 *  to a line. The list is shown back first, with every line that would be
 *  refused marked and explained, and **nothing is added until it is
 *  confirmed**. */
function PasteSeveral({ section, item, url, busy, onPasted }: {
  section: BuilderSection; item: string; url: string; busy: boolean; onPasted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [shown, setShown] = useState<PasteResult | null>(null);
  const [said, setSaid] = useState("");
  const rated = section.kind === "ratings";
  const close = () => { setOpen(false); setText(""); setShown(null); setSaid(""); };
  const send = useMutation({
    mutationFn: (confirmed?: string[]) => api.post<PasteResult>(
      url, { section: section.code, text, ...(confirmed ? { confirmed } : {}) }),
    onSuccess: (result, confirmed) => {
      setSaid("");
      if (confirmed) { close(); onPasted(); } else setShown(result);
    },
    onError: (e: Error & { status?: number; data?: PasteResult }) => {
      // Shown, and the template has changed since: here is the list as it
      // stands now. Nothing was added.
      if (e.status === 409 && e.data?.lines) {
        setShown(e.data);
        setSaid("The template changed after this list was shown, so nothing was "
          + "added. Here is the list as it stands now.");
      } else setSaid(e.message);
    },
  });
  if (!open) {
    return (
      <p style={{ marginBottom: 0 }}>
        <button className="ghost small" disabled={busy}
          aria-label={`Paste several into ${section.title}`}
          onClick={() => setOpen(true)}>Paste several</button>
      </p>
    );
  }
  const fine = shown ? shown.lines.filter((line) => line.ok) : [];
  const count = (n: number) => `${n} ${item}${n === 1 ? "" : "s"}`;
  return (
    <div className="card">
      <p className="small" style={{ marginTop: 0 }}><strong>Paste several</strong></p>
      {said && <Banner kind="bad">{said}</Banner>}
      {!shown ? (
        <>
          <p className="small muted">
            One {item} to a line, in the order you want them. Numbers and bullets at
            the start of a line are taken off.
            {rated && " Start each line with its label, as in “Plan — Our plan is "
              + "written down.”"}
            {" "}You see the list before anything is added.
          </p>
          <textarea rows={6} aria-label={`Lines to paste into ${section.title}`}
            value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button className="primary" disabled={!text.trim() || send.isPending}
              onClick={() => send.mutate(undefined)}>
              {send.isPending ? "Reading…" : "Show the list"}
            </button>
            <button className="ghost" onClick={close}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <p className="small muted">
            {fine.length === shown.lines.length
              ? `All ${count(fine.length)} can be added.`
              : `${count(fine.length)} of ${shown.lines.length} can be added. The `
                + "others are left out, each for the reason beside it."}
            {" "}Nothing has been added yet.
          </p>
          <ol aria-label={`What would be added to ${section.title}`} className="small">
            {shown.lines.map((line, index) => (
              <li key={index} style={{ marginBottom: ".35rem" }}>
                {line.ok ? <Pill kind="ok">will be added</Pill>
                  : <Pill kind="warn">left out</Pill>}{" "}
                {rated && line.label && <><strong>{line.label}</strong> · </>}
                {line.prompt}
                {!line.ok && <div className="tiny muted">{line.why}</div>}
              </li>
            ))}
          </ol>
          <div className="row">
            <button className="primary" disabled={fine.length === 0 || send.isPending}
              onClick={() => send.mutate(fine.map((line) => line.prompt))}>
              {send.isPending ? "Adding…" : `Add ${count(fine.length)}`}
            </button>
            <button onClick={() => { setShown(null); setSaid(""); }}>Change the list</button>
            <button className="ghost" onClick={close}>Cancel</button>
          </div>
        </>
      )}
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
