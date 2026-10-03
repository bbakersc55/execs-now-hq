import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Pill } from "../components/ui";
import { StrategySessionRow, api } from "../lib/api";

/**
 * What the live view shows only for a session started from a builder template
 * (P3). A classic or focused session renders none of this.
 */

/** The scale, said once above the rated items, in the template's own words. */
export function RatingScale({ scale }: { scale: string }) {
  if (!scale) return null;
  return (
    <p className="small muted" style={{ marginTop: 0 }}>
      Rate each one from 1 to 10 — {scale}.
    </p>
  );
}

/**
 * The v3 diagnostic. Claude proposes questions from what the prospect wrote
 * before the call, and from the two lowest ratings once those are taken; the
 * person on the call can also type one in. **Only an accepted question is
 * asked.** The template's number is where a session starts; the session holds
 * `most` at the outside.
 */
export function DiagnosticTrayV3({ sessionPath, data, mayRun, onChanged }: {
  sessionPath: string; data: StrategySessionRow; mayRun: boolean; onChanged: () => void;
}) {
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  const [typed, setTyped] = useState("");
  const done = { onSuccess: () => { setProblem(""); onChanged(); },
                 onError: (e: Error) => { setSaid(""); setProblem(e.message); } };
  const propose = useMutation({
    mutationFn: (fromRatings: boolean) => api.post<{ proposed: unknown[] }>(
      `${sessionPath}propose-diagnostic/`, fromRatings ? { from_ratings: true } : {}),
    onSuccess: (result) => {
      setProblem("");
      setSaid(result.proposed.length === 0
        ? "Nothing new to propose from what is there." : "");
      onChanged();
    },
    onError: done.onError,
  });
  const add = useMutation({
    mutationFn: () => api.post("/api/strategy-diagnostic-proposals/",
                               { session: data.id, prompt: typed.trim() }),
    onSuccess: () => { setTyped(""); done.onSuccess(); },
    onError: done.onError,
  });
  const act = useMutation({
    mutationFn: ({ id, suffix }: { id: string; suffix: string }) =>
      api.post(`/api/strategy-diagnostic-proposals/${id}/${suffix}`), ...done });
  const edit = useMutation({
    mutationFn: ({ id, prompt }: { id: string; prompt: string }) =>
      api.patch(`/api/strategy-diagnostic-proposals/${id}/`, { prompt }), ...done });

  if (!mayRun) return null;
  const all = data.diagnostic_proposals ?? [];
  const tray = all.filter((p) => p.state === "proposed");
  const inSession = all.filter((p) => p.state === "accepted");
  const size = data.diagnostic?.size ?? 3;
  const most = data.diagnostic?.most ?? 8;
  const full = inSession.length >= most;
  const rated = (data.six_key_components?.answered ?? 0) >= 2;
  const busy = propose.isPending || add.isPending || act.isPending;

  return (
    <div style={{ marginBottom: ".75rem" }}>
      <div className="row">
        <button disabled={busy || full} onClick={() => propose.mutate(false)}>
          {propose.isPending ? "Proposing…"
            : all.length ? "Propose more" : "Propose questions from the pre-call answers"}
        </button>
        <button disabled={busy || full || !rated}
          title={rated ? "" : "Take at least two ratings first."}
          onClick={() => propose.mutate(true)}>
          Propose from the ratings
        </button>
        <span className="small muted">
          {inSession.length > 0
            ? `${inSession.length} in the session (this template starts with ${size}; `
              + `${most} at most).`
            : "Nothing accepted yet: the section asks the template's fixed questions."}
        </span>
      </div>
      {problem && <Banner kind="warn">{problem}</Banner>}
      {said && <p className="small muted" role="status">{said}</p>}

      {inSession.length > 0 && (
        <>
          <h3 style={{ marginBottom: ".25rem" }}>In the session — {inSession.length} accepted</h3>
          <ul aria-label="Accepted diagnostic questions" style={{ listStyle: "none", padding: 0 }}>
            {inSession.map((p) => (
              <li key={p.id} className="row" style={{ alignItems: "baseline", gap: ".5rem" }}>
                <span style={{ flex: 1 }}>
                  {p.prompt}{" "}
                  {!p.from_ai && <Pill>added by hand</Pill>}
                </span>
                <button className="ghost small" aria-label={`Remove "${p.prompt}" from the session`}
                  disabled={busy} onClick={() => act.mutate({ id: p.id, suffix: "remove/" })}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {tray.length > 0 && (
        <h3 style={{ marginBottom: ".25rem" }}>
          Tray — {tray.length} proposed question{tray.length === 1 ? "" : "s"}
        </h3>
      )}
      {tray.map((p) => (
        <div key={p.id} className="card" style={{ marginBottom: ".4rem" }}>
          <p className="tiny muted" style={{ margin: 0 }}>
            <Pill>{p.rule_label}</Pill> {p.basis}
          </p>
          <textarea aria-label={`Proposed question: ${p.prompt}`} rows={2}
            defaultValue={p.prompt} style={{ width: "100%", marginTop: ".3rem" }}
            onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== p.prompt
              && edit.mutate({ id: p.id, prompt: e.target.value.trim() })} />
          <div className="row" style={{ marginTop: ".3rem" }}>
            <button className="primary" aria-label={`Accept "${p.prompt}"`}
              disabled={busy || full}
              onClick={() => act.mutate({ id: p.id, suffix: "accept/" })}>
              Accept
            </button>
            <button className="danger" aria-label={`Discard "${p.prompt}"`} disabled={busy}
              onClick={() => act.mutate({ id: p.id, suffix: "discard/" })}>Discard</button>
          </div>
        </div>
      ))}

      <div className="row" style={{ marginTop: ".5rem" }}>
        <input aria-label="A diagnostic question of your own" value={typed}
          placeholder="Type a question of your own" style={{ flex: 1 }} maxLength={500}
          disabled={full} onChange={(e) => setTyped(e.target.value)} />
        <button disabled={busy || full || !typed.trim()} onClick={() => add.mutate()}>
          Add a question
        </button>
      </div>
      <p className="tiny muted" style={{ margin: ".25rem 0 0" }}>
        {full ? `This session holds ${most} diagnostic questions, the most it can. `
          + "Remove one to add another."
          : "A question you add goes straight into this session. It does not change "
          + "the template."}
      </p>
    </div>
  );
}
