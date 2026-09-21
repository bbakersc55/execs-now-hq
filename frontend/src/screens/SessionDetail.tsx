import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { Banner, Card, Field, Pill, when } from "../components/ui";
import {
  AnswerValue, ConversionRow, MapRow, Me, StrategyQuestion, StrategySessionRow, api,
} from "../lib/api";

const CAN_RUN = ["FF", "CF"];

/** Minutes since a moment, on a clock that moves. Returns null when there is
 *  no moment to count from. */
function useMinutesSince(from: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!from) return;
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, [from]);
  if (!from) return null;
  return Math.max(0, Math.floor((now - Date.parse(from)) / 60_000));
}

/** Minutes since the call actually began — FR-4.15's pacing, on a clock that
 *  moves. Scheduled is when it was meant to start; `started_at` is when it did,
 *  so a call that began late does not open twenty minutes over budget. */
function useElapsed(startedAt: string | null) {
  return useMinutesSince(startedAt);
}

// The seed's own worked example, kept as copy rather than as a row: a map row
// needs a session, and a fake session would show up in every list forever.
// Owner's ruling, 2026-09-18.
const EXAMPLE = "Supervisor overload → 1 supervisor covering 14 sites → Add area lead "
  + "per 8 sites; move inspections to app → Integrator → 60 days → Inspections per "
  + "site per month";

const FLAG_LABEL: Record<string, string> = {
  fractional_notes: "Your private notes",
  diagnostic_observations: "Your diagnostic observations",
  alignment_observation: "The alignment observation (§3.4)",
  mechanics: "Notes / mechanics from experience",
  investment: "§9 — scope and investment",
};

/**
 * The live session view (FR-4.15–4.20). It renders entirely from the session's
 * **own snapshot**, which is why editing the template mid-engagement cannot
 * move anything under the fractional's feet mid-call.
 */
export function SessionDetail({ me }: { me: Me }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const path = `/api/strategy-sessions/${id}/`;
  const [note, setNote] = useState("");
  const mayRun = !!me.role && CAN_RUN.includes(me.role);

  const session = useQuery<StrategySessionRow>({
    queryKey: ["strategy-session", id], queryFn: () => api.get<StrategySessionRow>(path),
  });
  const elapsed = useElapsed(session.data?.started_at ?? null);
  // FR-4.15 — pacing. Clicking a section header says "we are here now", and the
  // section's own clock starts. Nothing else is kept: no per-section ledger.
  const onSection = useMinutesSince(session.data?.current_section_at ?? null);
  const setSection = useMutation({
    mutationFn: (code: string) => api.patch(path, { current_section: code }),
    onSuccess: () => refresh(),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["strategy-session", id] });

  const answer = useMutation({
    mutationFn: (body: { question_key: string; value: AnswerValue;
                         fractional_note?: string }) =>
      api.post(`${path}answers/`, body),
    onSuccess: () => refresh(),
    onError: (e: Error) => setNote(e.message),
  });
  const act = useMutation({
    mutationFn: ({ suffix, body }: { suffix: string; body?: object }) =>
      api.post(`${path}${suffix}`, body),
    onSuccess: () => { refresh(); },
    onError: (e: Error) => setNote(e.message),
  });
  const invite = useMutation({
    mutationFn: () => api.post(`${path}send-invite/`),
    onSuccess: () => { setNote("The form is on its way."); refresh(); },
    onError: (e: Error) => setNote(e.message),
  });

  if (session.isLoading) return <p>Opening the session…</p>;
  if (session.isError) return <Banner kind="bad">{(session.error as Error).message}</Banner>;
  const data = session.data!;
  const answers = Object.fromEntries((data.answers ?? []).map((a) => [a.question_key, a]));
  const tray = (data.map_rows ?? []).filter((r) => r.state === "proposed");
  const map = (data.map_rows ?? []).filter((r) => r.state === "accepted");

  return (
    <>
      <h1>{data.contact?.name}{data.company ? ` · ${data.company.name}` : ""}</h1>
      <p className="small muted">
        {data.scheduled_at ? when(data.scheduled_at) : "Not scheduled"} · {data.owner}
        {data.must_ask && <> · <strong>{data.must_ask.answered} of {data.must_ask.of}</strong> must-asks answered</>}
        {elapsed !== null && (
          <> · <strong>{elapsed} min</strong> of the template's {data.budget_minutes}</>
        )}
      </p>
      {note && <Banner kind="info">{note}</Banner>}
      {!mayRun && (
        <Banner kind="info">
          You can read the session and send the pre-call form. Running the call,
          drafting, sending the map and converting are the fractional's.
        </Banner>
      )}

      <Card title="The pre-call form">
        <p className="small muted">
          {data.precall_sent
            ? `Sent · the link works until ${when(data.precall_expires_at)}`
            : "Not sent yet."}
        </p>
        <button onClick={() => invite.mutate()} disabled={invite.isPending}>
          {data.precall_sent ? "Send it again" : "Send the form"}
        </button>
        {data.precall_sent && (
          <p className="small muted">
            Sending again issues a new link and retires the old one.
          </p>
        )}
      </Card>

      {data.six_key_components && data.six_key_components.of > 0 && (
        <SixKey summary={data.six_key_components} sections={data.sections ?? []} />
      )}

      {(data.sections ?? []).map((section) => {
        const here = data.current_section === section.code;
        const over = here && onSection !== null && section.time_budget_minutes !== null
          && onSection > section.time_budget_minutes;
        return (
        <Card key={section.code}
          title={
            <button className="ghost" style={{ font: "inherit", padding: 0 }}
              aria-label={`Start ${section.title}`}
              onClick={() => setSection.mutate(here ? "" : section.code)}>
              {here ? "▶ " : ""}{section.title}
            </button>
          }
          actions={section.time_budget_minutes ? (
            <Pill kind={over ? "warn" : here ? "ai" : ""}>
              {here && onSection !== null
                ? `${onSection} of ${section.time_budget_minutes} min`
                : `${section.time_budget_minutes} min`}
            </Pill>
          ) : undefined}>
          {section.code === "mirror" && (
            <Mirror data={data} mayRun={mayRun}
              onDraft={() => act.mutate({ suffix: "draft-mirror/" })}
              onAccept={(goal, unlocks) =>
                api.patch(path, { mirror_goal: goal, mirror_unlocks: unlocks })
                  .then(refresh)} />
          )}
          {section.code === "strategy_map" && (
            <MapSection tray={tray} map={map} mayRun={mayRun}
              onDraft={() => act.mutate({ suffix: "draft-rows/" })} onChanged={refresh} />
          )}
          {section.questions.map((question) => (
            <QuestionRow key={question.key} question={question}
              saved={answers[question.key]?.value ?? null}
              savedNote={answers[question.key]?.fractional_note ?? ""}
              answeredBy={answers[question.key]?.answered_by}
              disabled={!mayRun}
              onSave={(value, fractional_note) =>
                answer.mutate({ question_key: question.key, value, fractional_note })} />
          ))}
          {section.questions.length === 0 && section.code !== "mirror"
            && section.code !== "strategy_map" && (
            <p className="small muted">Nothing to capture here.</p>
          )}
        </Card>
        );
      })}

      {mayRun && <PdfCard data={data} path={path} onChanged={refresh} setNote={setNote} />}
      {mayRun && <ConvertCard id={id!} path={path} data={data} onChanged={refresh}
                              setNote={setNote} />}
    </>
  );
}

function SixKey({ summary, sections }: {
  summary: NonNullable<StrategySessionRow["six_key_components"]>;
  sections: StrategySessionRow["sections"];
}) {
  const labels = Object.fromEntries((sections ?? [])
    .flatMap((s) => s.questions).map((q) => [q.key, q.prompt]));
  return (
    <Card title="Six Key Components">
      <p className="small muted">
        {summary.answered} of {summary.of} rated
        {summary.average !== null && <> · average <strong>{summary.average}</strong></>}
      </p>
      <ul style={{ listStyle: "none", paddingLeft: 0 }}>
        {summary.scores.map((score) => (
          <li key={score.key} style={{ marginBottom: ".35rem" }}>
            <span className="row" style={{ gap: ".5rem" }}>
              <span style={{ width: "8rem" }}>{labels[score.key] ?? score.key}</span>
              <strong>{score.rating}</strong>
              {summary.lowest === score.key && <Pill kind="warn">Look here first</Pill>}
            </span>
            {/* The comment beside the number is usually where the signal is. */}
            {score.comment && (
              <p className="small muted" style={{ margin: ".1rem 0 0 8.5rem" }}>
                “{score.comment}”
              </p>
            )}
          </li>
        ))}
      </ul>
      {!summary.complete && (
        <p className="small muted">
          The lowest score is named once all six are in — with three blank it would
          only look like an answer.
        </p>
      )}
    </Card>
  );
}

function Mirror({ data, mayRun, onDraft, onAccept }: {
  data: StrategySessionRow; mayRun: boolean;
  onDraft: () => void; onAccept: (goal: string, unlocks: string) => void;
}) {
  const [goal, setGoal] = useState(data.mirror.goal);
  const [unlocks, setUnlocks] = useState(data.mirror.unlocks);
  const draft = data.proposed_mirror;

  return (
    <>
      {(draft.goal || draft.unlocks) && (
        <Banner kind="info">
          <strong>Claude's draft, not saved.</strong>
          <p style={{ margin: ".4rem 0 0" }}>{draft.goal}</p>
          <p style={{ margin: ".2rem 0 0" }}>{draft.unlocks}</p>
          {mayRun && (
            <button className="ghost" onClick={() => {
              setGoal(draft.goal); setUnlocks(draft.unlocks);
            }}>Use this as a starting point</button>
          )}
        </Banner>
      )}
      <Field label="Their goal, in their words">
        <textarea aria-label="Their goal" rows={2} value={goal} disabled={!mayRun}
          onChange={(e) => setGoal(e.target.value)} />
      </Field>
      <Field label="What unlocks it">
        <textarea aria-label="What unlocks it" rows={2} value={unlocks} disabled={!mayRun}
          onChange={(e) => setUnlocks(e.target.value)} />
      </Field>
      {mayRun && (
        <div className="row">
          <button className="primary" onClick={() => onAccept(goal, unlocks)}>
            Save the mirror
          </button>
          <button onClick={onDraft}>Draft it with Claude</button>
        </div>
      )}
    </>
  );
}

function MapSection({ tray, map, mayRun, onDraft, onChanged }: {
  tray: MapRow[]; map: MapRow[]; mayRun: boolean;
  onDraft: () => void; onChanged: () => void;
}) {
  const act = useMutation({
    mutationFn: ({ row, suffix }: { row: string; suffix: string }) =>
      api.post(`/api/strategy-map-rows/${row}/${suffix}`),
    onSuccess: onChanged,
  });
  const edit = useMutation({
    mutationFn: ({ row, body }: { row: string; body: Partial<MapRow> }) =>
      api.patch(`/api/strategy-map-rows/${row}/`, body),
    onSuccess: onChanged,
  });
  const reorder = useMutation({
    mutationFn: (order: string[]) =>
      api.post("/api/strategy-map-rows/reorder/", { order }),
    onSuccess: onChanged,
  });

  const move = (index: number, by: number) => {
    const next = [...map];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row);
    reorder.mutate(next.map((r) => r.id));
  };

  return (
    <>
      {mayRun && (
        <div className="row">
          <button onClick={onDraft}>Draft rows with Claude</button>
          <span className="small muted">
            Drafts land in the tray below. Nothing reaches the map until you accept it.
          </span>
        </div>
      )}

      {tray.length > 0 && (
        <>
          <h3 style={{ marginBottom: ".25rem" }}>Tray — {tray.length} proposed</h3>
          {tray.map((row) => (
            <div key={row.id} className="card" style={{ marginBottom: ".5rem" }}>
              <strong>{row.bottleneck}</strong>
              <p className="small muted" style={{ margin: ".2rem 0" }}>
                {row.root_cause}{row.the_fix ? ` → ${row.the_fix}` : ""}
                {row.horizon ? ` · ${row.horizon} days` : ""}
                {row.measurable ? ` · ${row.measurable}` : ""}
              </p>
              {mayRun && (
                <div className="row">
                  <button className="primary"
                    onClick={() => act.mutate({ row: row.id, suffix: "accept/" })}>
                    Accept
                  </button>
                  <button className="danger"
                    onClick={() => act.mutate({ row: row.id, suffix: "discard/" })}>
                    Discard
                  </button>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      <h3 style={{ marginBottom: ".25rem" }}>The map — {map.length} rows</h3>
      {map.length === 0 && (
        <p className="small muted">
          Empty until you accept a row. A worked example of the shape:<br />
          <em>{EXAMPLE}</em>
        </p>
      )}
      {map.map((row, index) => (
        <div key={row.id} className="card" style={{ marginBottom: ".5rem" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{index + 1}. {row.bottleneck}</strong>
            {mayRun && (
              <span className="row">
                <button className="ghost small" disabled={index === 0}
                  onClick={() => move(index, -1)} aria-label={`Move ${row.bottleneck} up`}>
                  ↑
                </button>
                <button className="ghost small" disabled={index === map.length - 1}
                  onClick={() => move(index, 1)} aria-label={`Move ${row.bottleneck} down`}>
                  ↓
                </button>
              </span>
            )}
          </div>
          {mayRun ? (
            <div className="row">
              <input aria-label={`Measurable for ${row.bottleneck}`}
                defaultValue={row.measurable} placeholder="Measurable"
                onBlur={(e) => e.target.value !== row.measurable
                  && edit.mutate({ row: row.id, body: { measurable: e.target.value } })} />
              <input aria-label={`Owner for ${row.bottleneck}`} defaultValue={row.owner_text}
                placeholder="Owner"
                onBlur={(e) => e.target.value !== row.owner_text
                  && edit.mutate({ row: row.id, body: { owner_text: e.target.value } })} />
              <select aria-label={`Horizon for ${row.bottleneck}`}
                defaultValue={row.horizon ?? ""}
                onChange={(e) => edit.mutate({ row: row.id,
                  body: { horizon: Number(e.target.value) } })}>
                <option value="">—</option>
                <option value={30}>30</option>
                <option value={60}>60</option>
                <option value={90}>90</option>
              </select>
            </div>
          ) : (
            <p className="small muted">{row.measurable} · {row.horizon} days</p>
          )}
        </div>
      ))}
    </>
  );
}

function QuestionRow({ question, saved, savedNote, answeredBy, disabled, onSave }: {
  question: StrategyQuestion; saved: AnswerValue | null; savedNote: string;
  answeredBy?: "prospect" | "fractional";
  disabled: boolean; onSave: (value: AnswerValue, note?: string) => void;
}) {
  const value = saved ?? {};
  const [said, setSaid] = useState(String(value.said ?? ""));
  const [cause, setCause] = useState(String(value.cause ?? ""));
  const [tried, setTried] = useState(String(value.tried ?? ""));
  // A rating's answer is `{rating, comment}`, and reading it as `text` is what
  // made a fully answered self-rating render as six empty dropdowns in the
  // 2026-09-19 dry run — the prospect's work, invisible on the screen that
  // matters most.
  const [text, setText] = useState(
    String(value.rating ?? value.text ?? value.value ?? ""));
  const [why, setWhy] = useState(String(value.why ?? ""));
  const [notes, setNotes] = useState(String(value.notes ?? ""));
  const [comment, setComment] = useState(String(value.comment ?? ""));
  const [agreed, setAgreed] = useState(Boolean(value.agreed));
  const [note, setNote] = useState(savedNote);
  const schema = question.response_schema;

  const label = (
    <label htmlFor={question.key}>
      {question.prompt}
      {question.must_ask && <> <Pill kind="warn">must ask</Pill></>}
      {question.is_fractional_observation && <> <Pill>not asked aloud</Pill></>}
      {question.is_financial && <> <Pill kind="bad">financial</Pill></>}
      {/* Whose answer this is. A prospect's answer is theirs until the
          fractional changes it, and the screen should say so. */}
      {answeredBy === "prospect" && <> <Pill kind="ok">from the form</Pill></>}
    </label>
  );

  const noteField = question.has_fractional_note && (
    <input aria-label={`Private note — ${question.prompt}`} value={note}
      placeholder="Private note — never shown to the prospect" disabled={disabled}
      onChange={(e) => setNote(e.target.value)}
      onBlur={() => onSave(currentValue(), note)} />
  );

  function currentValue(): AnswerValue {
    if (schema === "diagnostic_triple") return { said, cause, tried };
    if (schema === "value_pair") return { value: text, why };
    if (schema === "agreed_note") return { agreed, notes };
    // Keep the prospect's own comment: changing the number must not silently
    // delete the sentence that explains it.
    if (schema === "rating_1_10") return { rating: Number(text || 0), comment };
    if (schema === "path_reaction") return { reaction: said, risk: cause, leaning: tried };
    return { text };
  }

  return (
    <div className="field" style={{ marginBottom: "1rem" }}>
      {label}
      {schema === "diagnostic_triple" && (
        <div className="row">
          <input aria-label={`What they said — ${question.prompt}`} value={said}
            placeholder="What they said" disabled={disabled}
            onChange={(e) => setSaid(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
          <input aria-label={`Who or what causes it — ${question.prompt}`} value={cause}
            placeholder="Who or what causes it" disabled={disabled}
            onChange={(e) => setCause(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
          <input aria-label={`What they tried — ${question.prompt}`} value={tried}
            placeholder="What they tried, and why it didn't stick" disabled={disabled}
            onChange={(e) => setTried(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
        </div>
      )}
      {schema === "path_reaction" && (
        <div className="row">
          <input aria-label={`Their reaction — ${question.prompt}`} value={said}
            placeholder="Their reaction" disabled={disabled}
            onChange={(e) => setSaid(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
          <input aria-label={`Honest risk — ${question.prompt}`} value={cause}
            placeholder="Honest risk, in their words" disabled={disabled}
            onChange={(e) => setCause(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
          <input aria-label={`Leaning — ${question.prompt}`} value={tried}
            placeholder="Leaning" disabled={disabled}
            onChange={(e) => setTried(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
        </div>
      )}
      {schema === "value_pair" && (
        <div className="row">
          <input aria-label={question.prompt} value={text} placeholder="In their words"
            disabled={disabled} onChange={(e) => setText(e.target.value)}
            onBlur={() => text.trim() && onSave(currentValue(), note)} />
          <input aria-label={`Why — ${question.prompt}`} value={why}
            placeholder="Why it matters to them" disabled={disabled}
            onChange={(e) => setWhy(e.target.value)}
            onBlur={() => text.trim() && onSave(currentValue(), note)} />
        </div>
      )}
      {schema === "agreed_note" && (
        <div className="row">
          <label className="small" style={{ display: "inline-flex", gap: ".4rem" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={agreed}
              aria-label={`Agreed — ${question.prompt}`} disabled={disabled}
              onChange={(e) => { setAgreed(e.target.checked);
                onSave({ agreed: e.target.checked, notes }, note); }} />
            Agreed on the call
          </label>
          <input aria-label={`Notes — ${question.prompt}`} value={notes}
            placeholder="Notes" disabled={disabled}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => onSave(currentValue(), note)} />
        </div>
      )}
      {schema === "rating_1_10" && (
        <div className="row">
          <select id={question.key} aria-label={question.prompt} value={text}
            style={{ width: "6rem" }} disabled={disabled}
            onChange={(e) => { setText(e.target.value);
              if (e.target.value) {
                onSave({ rating: Number(e.target.value), comment }, note);
              } }}>
            <option value="">—</option>
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <input aria-label={`${question.prompt} — comment`} value={comment}
            placeholder="What they said about it" disabled={disabled}
            onChange={(e) => setComment(e.target.value)}
            onBlur={() => text && onSave(currentValue(), note)} />
        </div>
      )}
      {schema === "free_text" && (
        <textarea id={question.key} rows={2} value={text} disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text.trim() && onSave(currentValue(), note)} />
      )}
      {noteField}
    </div>
  );
}

function PdfCard({ data, path, onChanged, setNote }: {
  data: StrategySessionRow; path: string; onChanged: () => void;
  setNote: (text: string) => void;
}) {
  const flags = useMutation({
    mutationFn: (body: Record<string, boolean>) => api.patch(`${path}pdf-flags/`, body),
    onSuccess: onChanged,
  });
  const send = useMutation({
    mutationFn: () => api.post(`${path}send-pdf/`),
    onSuccess: () => { setNote("Sent. It is on the contact's timeline and in the Outbox."); onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <Card title="The PDF">
      <p className="small muted">
        Everything private is left out unless you turn it on here. Each switch puts
        something you wrote in front of the prospect.
      </p>
      {Object.keys(FLAG_LABEL).map((key) => (
        <label key={key} className="small"
          style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          <input type="checkbox" style={{ width: "auto" }}
            checked={!!data.pdf_include_flags[key]} aria-label={FLAG_LABEL[key]}
            onChange={(e) => flags.mutate({ [key]: e.target.checked })} />
          Include {FLAG_LABEL[key]}
        </label>
      ))}
      <div className="row" style={{ marginTop: ".75rem" }}>
        <a className="btn ghost" href={`${path}pdf/?as=html`} target="_blank"
           rel="noreferrer">Preview it</a>
        <a className="btn ghost" href={`${path}pdf/`} target="_blank" rel="noreferrer">
          Download the file
        </a>
        <button className="primary" disabled={send.isPending} onClick={() => send.mutate()}>
          Send it to {data.contact?.name}
        </button>
      </div>
      <p className="small muted">
        Generating is not sending. Nothing leaves until you click send.
      </p>
    </Card>
  );
}

type Choice = {
  as?: string; baseline_value?: string; target_value?: string;
  baseline_unknown?: boolean;
};

/**
 * Conversion (FR-4.28–4.32, AC-4.11). The per-row chooser **is** the preview:
 * every accepted row, what it would become, and what it still needs. The button
 * is the confirmation, and nothing is written before it.
 *
 * Two things the 2026-09-21 Check-5 run found. The server refused every press —
 * nine measurables with no baseline, and a row set to "Leave it out" that the
 * server did not know the word for — and the refusal was drawn in the page's
 * banner, three screens above the button. So the card now carries its own
 * banner and marks the rows the server named, where the fractional is looking.
 */
function ConvertCard({ id, path, data, onChanged, setNote }: {
  id: string; path: string; data: StrategySessionRow; onChanged: () => void;
  setNote: (text: string) => void;
}) {
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const preview = useQuery<{ rows: ConversionRow[] }>({
    queryKey: ["conversion-preview", id],
    queryFn: () => api.get<{ rows: ConversionRow[] }>(`${path}conversion-preview/`),
  });
  const convert = useMutation({
    mutationFn: () => api.post<{ created: { as: string; title: string }[] }>(
      `${path}convert/`, { choices }),
    onSuccess: (result) => {
      setNote(`Created ${result.created.length} — ${result.created
        .map((c) => `${c.title} (${c.as})`).join(", ")}.`);
      onChanged();
    },
    onError: (e: Error) => setNote(e.message),
  });

  if (data.converted_at) {
    return (
      <Card title="Converted">
        <p className="small muted">
          Converted {when(data.converted_at)}. The goals and projects are on the Work
          screen, each linking back to the row it came from.
        </p>
      </Card>
    );
  }
  const rows = preview.data?.rows ?? [];
  const choiceFor = (row: ConversionRow): Choice => choices[row.row] ?? {};
  const asFor = (row: ConversionRow) => choiceFor(row).as ?? row.suggested;
  const set = (row: ConversionRow, patch: Choice) =>
    setChoices((current) => ({
      ...current,
      [row.row]: { as: asFor(row), ...(current[row.row] ?? {}), ...patch },
    }));

  // What the press will do, said before it is pressed.
  const counts = rows.reduce((tally, row) => {
    const as = asFor(row);
    return { ...tally, [as]: (tally[as] ?? 0) + 1 };
  }, {} as Record<string, number>);
  const making = (counts.goal ?? 0) + (counts.project ?? 0);
  const refusedError = convert.error as
    (Error & { data?: { rows?: string[] } }) | null;
  const refusedRows = refusedError?.data?.rows ?? [];

  return (
    <Card title="Convert to work">
      {rows.length === 0 ? (
        <p className="small muted">Accept a map row first — there is nothing to convert.</p>
      ) : (
        <>
          <p className="small muted">
            Nothing is created until you confirm. A goal carrying a measurable needs a
            baseline, or an explicit "not measured yet" — without a starting reading
            there is nothing to report against later.
          </p>
          {convert.isError && (
            <Banner kind="bad">{refusedError?.message}</Banner>
          )}
          {rows.map((row) => {
            const choice = choiceFor(row);
            const as = asFor(row);
            const notReady = refusedRows.includes(row.row);
            return (
              <div key={row.row} className="card"
                   style={{ marginBottom: ".5rem", opacity: as === "skip" ? 0.6 : 1 }}>
                <strong>{row.title}</strong>
                {notReady && <> <Pill kind="warn">not ready</Pill></>}
                <p className="small muted" style={{ margin: ".2rem 0" }}>
                  {row.owner_text && <>Owner: {row.owner_text}
                    {row.client_owner_contact
                      ? ` → ${row.client_owner_contact.name}`
                      : " (kept as text)"} · </>}
                  {row.horizon ? `${row.horizon} days · ` : ""}
                  {row.measurable || "no measurable"}
                </p>
                <div className="row">
                  <select aria-label={`Convert ${row.title} as`} value={as}
                    onChange={(e) => set(row, { as: e.target.value })}>
                    <option value="goal">A goal</option>
                    <option value="project">A project</option>
                    <option value="skip">Leave it out</option>
                  </select>
                  {as === "goal" && row.needs_baseline && (
                    <>
                      <input aria-label={`Baseline for ${row.title}`}
                        type="number" step="any" inputMode="decimal"
                        placeholder="Baseline today"
                        disabled={!!choice.baseline_unknown}
                        value={choice.baseline_value ?? ""}
                        onChange={(e) => set(row, { baseline_value: e.target.value })} />
                      <input aria-label={`Target for ${row.title}`}
                        type="number" step="any" inputMode="decimal" placeholder="Target"
                        disabled={!!choice.baseline_unknown}
                        value={choice.target_value ?? ""}
                        onChange={(e) => set(row, { target_value: e.target.value })} />
                      <label className="small" style={{ display: "inline-flex", gap: ".3rem" }}>
                        <input type="checkbox" style={{ width: "auto" }}
                          aria-label={`Not measured yet — ${row.title}`}
                          checked={!!choice.baseline_unknown}
                          onChange={(e) => set(row, { baseline_unknown: e.target.checked,
                            ...(e.target.checked
                              ? { baseline_value: "", target_value: "" } : {}) })} />
                        Not measured yet
                      </label>
                    </>
                  )}
                </div>
              </div>
            );
          })}
          <button className="primary" disabled={convert.isPending || making === 0}
            onClick={() => convert.mutate()}>
            Create the work
          </button>
          <p className="small muted" style={{ marginTop: ".4rem" }}>
            {making === 0
              ? "Every row is left out — there is nothing to create."
              : `Creates ${counts.goal ?? 0} goal${counts.goal === 1 ? "" : "s"} and `
                + `${counts.project ?? 0} project${counts.project === 1 ? "" : "s"}`
                + `${counts.skip ? `, leaving ${counts.skip} out` : ""}.`}
          </p>
        </>
      )}
    </Card>
  );
}
