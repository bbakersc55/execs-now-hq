import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill } from "../components/ui";
import { Board, Contact, Pipeline as PipelineType, api } from "../lib/api";

/** What a stage means, in the two words a board needs. */
const SEMANTIC_HINT: Record<string, string> = {
  entry: "where contacts enter",
  won: "reaching this makes them a client",
  lost: "closed, not lost from the record",
  parked: "still yours, just not active",
};

export function Pipeline() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string>("");
  const [moving, setMoving] = useState<Contact | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [dragging, setDragging] = useState<Contact | null>(null);
  const [over, setOver] = useState<string>("");

  const pipelines = useQuery<PipelineType[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<PipelineType[]>("/api/pipelines/"),
  });

  const current = selected || pipelines.data?.[0]?.id || "";

  const board = useQuery<Board>({
    queryKey: ["board", current],
    queryFn: () => api.get<Board>(`/api/pipelines/${current}/board/`),
    enabled: !!current,
  });

  const move = useMutation({
    mutationFn: (vars: { id: string; stage: string; reason: string }) =>
      api.post(`/api/contacts/${vars.id}/change-stage/`, {
        stage: vars.stage, reason: vars.reason,
      }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["board"] });
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
      const stage = board.data?.columns.find((c) => c.stage.id === vars.stage)?.stage;
      const isSale = stage?.semantic === "won" && board.data?.pipeline.kind === "sales";
      setNote(
        isSale
          ? `Moved to ${stage?.label}. The contact type ‘client’ was added and their company flagged as a client company.`
          : "Stage updated. Any matching automations for this pipeline have fired."
      );
      setMoving(null); setReason("");
    },
  });

  /**
   * A drop is the same move as the panel: the same endpoint, so the same
   * automations and the same client invariant.
   *
   * Dropping on a `lost` stage does NOT move them straight away — it opens the
   * move panel with that stage selected so the reason can be typed. FR-1.7
   * prompts for a reason on a lost stage, and a drag that skipped the prompt
   * would be a quieter way of doing the one move that most deserves a note.
   */
  function handleDrop(contact: Contact, stageId: string, semantic: string) {
    setOver("");
    setDragging(null);
    const current = columns.find((c) =>
      c.contacts.some((x) => x.id === contact.id))?.stage;
    if (current?.id === stageId) return;
    if (semantic === "lost") {
      setMoving(contact);
      setTarget(stageId);
      setReason("");
      return;
    }
    move.mutate({ id: contact.id, stage: stageId, reason: "" });
  }

  if (pipelines.isLoading) return <p className="muted">Loading…</p>;
  const list = pipelines.data ?? [];
  if (list.length === 0) {
    return (
      <>
        <h2>Pipeline</h2>
        <Empty>No pipelines yet. An FF creates them in pipeline settings.</Empty>
      </>
    );
  }

  const columns = board.data?.columns ?? [];
  const activePipeline = board.data?.pipeline;
  const movingHere = moving
    ? columns.find((c) => c.contacts.some((x) => x.id === moving.id))?.stage
    : undefined;

  return (
    <>
      <h2>Pipeline</h2>
      <p className="sub">
        A contact holds an independent position in each pipeline they belong to — a
        referral partner who is also a live prospect appears on both boards, and moving
        them on one does not touch the other.
      </p>
      <p className="muted small">
        <strong>Drag a card to another column to move it</strong>, or use <em>Move…</em> on
        the card — both run the same rules. Click a name to open the contact. Dropping
        onto a <strong>lost</strong> stage opens the panel so you can give a reason.
      </p>

      <div className="row" style={{ marginBottom: "1rem" }}>
        {list.map((p) => (
          <button
            key={p.id}
            className={p.id === current ? "primary" : "ghost"}
            style={{ flex: "0 0 auto" }}
            onClick={() => { setSelected(p.id); setMoving(null); }}
          >
            {p.name} <span className="muted">· {p.contact_count}</span>
          </button>
        ))}
      </div>

      {note && <Banner kind="ok">{note}</Banner>}

      {activePipeline?.kind === "sales" && (
        <p className="muted small">
          This is the sales pipeline: reaching its <strong>won</strong> stage is what makes
          someone a client (FR-1.6a). Other pipelines have their own end states and none
          of them flag a company.
        </p>
      )}

      {board.isLoading ? <p className="muted">Loading board…</p> : (
        <div className="board">
          {columns.map((col) => (
            <div
              className={`col${over === col.stage.id ? " drop-target" : ""}`}
              key={col.stage.id}
              onDragOver={(e) => { e.preventDefault(); setOver(col.stage.id); }}
              onDragLeave={() => setOver((o) => (o === col.stage.id ? "" : o))}
              onDrop={(e) => {
                e.preventDefault();
                if (dragging) handleDrop(dragging, col.stage.id, col.stage.semantic);
              }}
            >
              <h4>{col.stage.label}</h4>
              <div className="count">
                {col.count} contact{col.count === 1 ? "" : "s"}
                {SEMANTIC_HINT[col.stage.semantic] && (
                  <> · <span title={col.stage.semantic}>{SEMANTIC_HINT[col.stage.semantic]}</span></>
                )}
              </div>
              {col.contacts.length === 0 && <Empty>—</Empty>}
              {col.contacts.map((c) => (
                <div
                  className={`item${dragging?.id === c.id ? " dragging" : ""}`}
                  key={c.id}
                  draggable
                  onDragStart={(e) => {
                    setDragging(c);
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", c.id);
                  }}
                  onDragEnd={() => { setDragging(null); setOver(""); }}
                >
                  {/* A real link: the card opens the contact, and it stays
                      reachable by keyboard. Dragging is a mouse affordance on
                      top, never the only way to move someone. */}
                  <Link to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</Link>
                  <div className="muted">{c.title || " "}</div>
                  {(c.pipeline_positions ?? []).length > 1 && (
                    <div className="muted small">
                      also in {(c.pipeline_positions ?? [])
                        .filter((p) => p.pipeline !== current)
                        .map((p) => p.pipeline_name).join(", ")}
                    </div>
                  )}
                  <button className="ghost small" aria-label={`Move ${c.first_name} ${c.last_name}`}
                    onClick={() => { setMoving(c); setTarget(""); setReason(""); }}>
                    Move…
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {moving && (
        <Card title={`Move ${moving.first_name} ${moving.last_name} in ${activePipeline?.name}`}>
          <div className="row">
            <div>
              <label htmlFor="move-stage">New stage</label>
              <select id="move-stage" value={target}
                onChange={(e) => setTarget(e.target.value)}>
                <option value="">Choose…</option>
                {columns
                  .filter((c) => c.stage.id !== movingHere?.id)
                  .map((c) => (
                    <option key={c.stage.id} value={c.stage.id}>{c.stage.label}</option>
                  ))}
              </select>
            </div>
            <div>
              <label>
                Reason{" "}
                {columns.find((c) => c.stage.id === target)?.stage.semantic === "lost" && (
                  <strong>(prompted on a lost stage — may be skipped)</strong>
                )}
              </label>
              <input value={reason} autoFocus={!!target} aria-label="Reason"
                onChange={(e) => setReason(e.target.value)} />
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
          {(moving.pipeline_positions ?? []).length > 0 && (
            <p className="muted small">
              Currently:{" "}
              {(moving.pipeline_positions ?? [])
                .map((p) => `${p.pipeline_name} → ${p.stage_label}`).join(" · ")}
              . Only <strong>{activePipeline?.name}</strong> changes.
            </p>
          )}
          {columns.find((c) => c.stage.id === target)?.stage.semantic === "won"
            && activePipeline?.kind === "sales" && (
            <Banner kind="warn">
              This adds the client contact type and flags their company as a client
              company — the same as any other route to that stage.
            </Banner>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>
            <Link to={`/contacts/${moving.id}`}>Open contact →</Link>
          </p>
        </Card>
      )}

      <Card title="Where each pipeline stands">
        <table>
          <thead><tr><th>Pipeline</th><th>Kind</th><th>Stages</th><th>Contacts</th></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td><Pill kind={p.kind === "sales" ? "ai" : ""}>{p.kind}</Pill></td>
                <td className="muted small">
                  {p.stages.slice().sort((a, b) => a.position - b.position)
                    .map((s) => s.label).join(" → ")}
                </td>
                <td className="muted small">{p.contact_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
