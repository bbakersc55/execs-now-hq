import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Banner, Card, Pill } from "../components/ui";
import { Me, StrategySection, StrategySessionRow, api } from "../lib/api";

interface Template {
  id: string; name: string; discipline: string; version: number; is_default: boolean;
  sections: StrategySection[];
}

type Edit = { prompt?: string; ask_when?: "precall" | "live"; must_ask?: boolean };

/**
 * Matrix 10.1 — the template, editable by the founder fractional only, and in
 * Beta only in the three ways a live practice actually needs mid-engagement:
 * **the wording, whether it goes on the form or is asked in the call, and
 * whether it is a must-ask.** Reordering, adding and deleting questions come
 * with V1's multi-discipline work.
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
  const template = templates.data?.[0];
  const pending = Object.keys(edits).length;

  return (
    <>
      <h1>The session template</h1>
      {note && <Banner kind="ok">{note}</Banner>}
      {!template ? <p>Loading the template…</p> : (
        <>
          <Card>
            <p className="small muted">
              <strong>{template.name}</strong> · {template.discipline} · v{template.version}
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
          </Card>

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
                      {question.is_financial && <> <Pill kind="bad">financial</Pill></>}
                    </label>
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
