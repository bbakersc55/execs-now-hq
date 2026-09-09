import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty } from "../components/ui";
import { api, Contact, Stage } from "../lib/api";

export function Pipeline() {
  const qc = useQueryClient();
  const [moving, setMoving] = useState<Contact | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");

  const stages = useQuery<Stage[]>({
    queryKey: ["stages"], queryFn: () => api.get<Stage[]>("/api/pipeline-stages/"),
  });
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  const move = useMutation({
    mutationFn: (vars: { id: string; stage: string; reason: string }) =>
      api.post(`/api/contacts/${vars.id}/change-stage/`, {
        stage: vars.stage, reason: vars.reason,
      }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
      setNote(
        vars.stage === "client"
          ? "Moved to client. The contact type ‘client’ was added and their company flagged as a client company."
          : "Stage updated. Any matching automations have fired."
      );
      setMoving(null); setReason("");
    },
  });

  const ordered = (stages.data ?? []).slice().sort((a, b) => a.position - b.position);

  return (
    <>
      <h2>Pipeline</h2>
      <p className="sub">
        Stage is the single source of truth for who is a client. Moving someone to
        <strong> client</strong> adds the type and flags their company; moving them to
        <strong> lost</strong> or <strong>dormant</strong> removes neither.
      </p>

      {note && <Banner kind="ok">{note}</Banner>}

      <div className="board">
        {ordered.map((stage) => {
          const inStage = (contacts.data ?? []).filter((c) => c.stage_code === stage.code);
          return (
            <div className="col" key={stage.id}>
              <h4>{stage.label}</h4>
              <div className="count">{inStage.length} contact{inStage.length === 1 ? "" : "s"}</div>
              {inStage.length === 0 && <Empty>—</Empty>}
              {inStage.map((c) => (
                <div className="item" key={c.id} onClick={() => { setMoving(c); setTarget(""); }}>
                  <div>{c.first_name} {c.last_name}</div>
                  <div className="muted">{c.title || " "}</div>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {moving && (
        <Card title={`Move ${moving.first_name} ${moving.last_name}`}>
          <div className="row">
            <div>
              <label>New stage</label>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">Choose…</option>
                {ordered.filter((s) => s.code !== moving.stage_code).map((s) => (
                  <option key={s.code} value={s.code}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label>Reason {target === "lost" && <strong>(prompted for lost — may be skipped)</strong>}</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <div style={{ flex: "0 0 auto" }}>
              <button
                className="primary"
                disabled={!target || move.isPending}
                onClick={() => move.mutate({ id: moving.id, stage: target, reason })}
              >
                {move.isPending ? "Moving…" : "Move"}
              </button>{" "}
              <button onClick={() => setMoving(null)}>Cancel</button>
            </div>
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>
            <Link to={`/contacts/${moving.id}`}>Open contact →</Link>
          </p>
        </Card>
      )}
    </>
  );
}
