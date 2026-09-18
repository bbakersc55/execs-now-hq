import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { Banner, Card } from "../components/ui";
import { AnswerValue, PreCallForm as Form, api } from "../lib/api";

/**
 * FR-4.6 / matrix 10.13 — the pre-call form. **No sign-in, and no role**: the
 * token in the link is the whole of the authentication, and it can reach
 * nothing but this session's pre-call questions.
 *
 * Every field autosaves on blur, because the realistic failure is a prospect
 * filling half of it on a phone and coming back tomorrow — resuming is just
 * opening the same link again. There is no submit button standing between them
 * and their work being kept; "I'm done" only tells the fractional.
 */
export function PreCallForm() {
  const { token } = useParams();
  const qc = useQueryClient();
  const path = `/api/strategy/precall/${token}`;
  const [saved, setSaved] = useState<string>("");
  const [failed, setFailed] = useState<string>("");

  const form = useQuery<Form>({
    queryKey: ["precall", token], queryFn: () => api.get<Form>(path), retry: false,
  });
  const save = useMutation({
    mutationFn: (body: { question_key: string; value: AnswerValue }) =>
      api.post<{ saved_at: string; answered: number; of: number }>(path, body),
    onSuccess: (result) => {
      setFailed("");
      setSaved(new Date(result.saved_at).toLocaleTimeString());
      qc.setQueryData<Form>(["precall", token], (old) =>
        old ? { ...old, answered: result.answered } : old);
    },
    onError: (e: Error) => setFailed(e.message),
  });
  const done = useMutation({
    mutationFn: () => api.post<Form>(`${path}/complete`),
    onSuccess: (result) => qc.setQueryData(["precall", token], result),
  });

  if (form.isLoading) return <main style={{ padding: "2rem" }}>Opening the form…</main>;
  if (form.isError) {
    return (
      <main style={{ padding: "2rem", maxWidth: "34rem" }}>
        <Banner kind="bad">{(form.error as Error).message}</Banner>
      </main>
    );
  }
  const data = form.data!;

  return (
    <main style={{ padding: "2rem 1rem", maxWidth: "44rem", margin: "0 auto" }}>
      <h1 style={{ marginBottom: ".25rem" }}>Before we talk</h1>
      <p className="muted">
        {data.practice}{data.company ? ` · ${data.company}` : ""}
      </p>
      <p>
        Hi {data.first_name} — these take about ten minutes. Everything saves as you
        go, so you can stop and come back to this same link.
      </p>

      <Card>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <strong>{data.answered} of {data.of} answered</strong>
          <span className="small muted" aria-live="polite">
            {failed ? failed : saved ? `Saved at ${saved}` : "Nothing to save yet"}
          </span>
        </div>
      </Card>

      {data.sections.map((section) => (
        <Card key={section.code} title={section.title}>
          {section.questions.map((question) => (
            <Question key={question.key} question={question}
              onSave={(value) => save.mutate({ question_key: question.key, value })} />
          ))}
        </Card>
      ))}

      <Card>
        {data.complete ? (
          <Banner kind="ok">
            Thank you — we have this. You can still add to it before we talk; anything
            you change is saved the same way.
          </Banner>
        ) : (
          <>
            <button className="primary" disabled={done.isPending}
              onClick={() => done.mutate()}>
              I'm done for now
            </button>
            <p className="small muted">
              This tells us you have finished. Your answers are already saved either way.
            </p>
          </>
        )}
      </Card>
    </main>
  );
}

function Question({ question, onSave }: {
  question: Form["sections"][number]["questions"][number];
  onSave: (value: AnswerValue) => void;
}) {
  const initial = question.value ?? {};
  const [text, setText] = useState(String(initial.text ?? ""));
  const [rating, setRating] = useState(initial.rating ? String(initial.rating) : "");
  const [comment, setComment] = useState(String(initial.comment ?? ""));

  // A late-arriving fetch (a resumed form) must fill the boxes.
  useEffect(() => {
    setText(String(initial.text ?? ""));
    setRating(initial.rating ? String(initial.rating) : "");
    setComment(String(initial.comment ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question.key]);

  if (question.response_schema === "rating_1_10") {
    return (
      <div className="field" style={{ marginBottom: "1rem" }}>
        <label htmlFor={question.key}>{question.prompt}</label>
        <div className="row">
          <select id={question.key} aria-label={question.prompt} value={rating}
            style={{ width: "6rem" }}
            onChange={(e) => {
              setRating(e.target.value);
              if (e.target.value) {
                onSave({ rating: Number(e.target.value), comment });
              }
            }}>
            <option value="">—</option>
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <input aria-label={`${question.prompt} — comment`} value={comment}
            placeholder="Anything you want to add (optional)"
            onChange={(e) => setComment(e.target.value)}
            onBlur={() => rating && onSave({ rating: Number(rating), comment })} />
        </div>
      </div>
    );
  }

  return (
    <div className="field" style={{ marginBottom: "1rem" }}>
      <label htmlFor={question.key}>{question.prompt}</label>
      <textarea id={question.key} rows={2} value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text.trim() && onSave({ text })} />
    </div>
  );
}
