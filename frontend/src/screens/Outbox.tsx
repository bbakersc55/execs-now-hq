import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api, Me, OutboxMessage } from "../lib/api";

const STATE_KIND: Record<string, string> = {
  sent: "ok", pending_approval: "warn", draft: "warn",
  expired: "bad", rejected: "bad", approved: "ok",
};

export function Outbox() {
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("pending_approval");
  const [note, setNote] = useState("");

  const me = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const messages = useQuery<OutboxMessage[]>({
    queryKey: ["outbox"], queryFn: () => api.get<OutboxMessage[]>("/api/outbox/"),
  });

  const canSend = me.data?.role === "FF" || me.data?.role === "CF";

  const approve = useMutation({
    mutationFn: (id: string) => api.post(`/api/outbox/${id}/approve/`),
    onSuccess: () => {
      setNote("Approved and sent. It now appears in the send log below.");
      qc.invalidateQueries({ queryKey: ["outbox"] });
      setOpen(null);
    },
    onError: (e: Error) => setNote(e.message),
  });

  const reject = useMutation({
    mutationFn: (id: string) => api.post(`/api/outbox/${id}/reject/`),
    onSuccess: () => {
      setNote("Rejected. Nothing was sent.");
      qc.invalidateQueries({ queryKey: ["outbox"] });
      setOpen(null);
    },
  });

  const all = messages.data ?? [];
  const shown = filter === "all" ? all : all.filter((m) => m.state === filter);
  const pendingCount = all.filter((m) => m.state === "pending_approval").length;

  return (
    <>
      <h2>Outbox</h2>
      <p className="sub">
        Every email the app has produced — the approval queue and the complete send log
        in one place. Drafts expire on their send-by date rather than sending.
      </p>

      {note && <Banner kind="ok">{note}</Banner>}
      {!canSend && (
        <Banner kind="info">
          You can read, edit, and reject drafts. Approving and sending is done by a
          fractional.
        </Banner>
      )}

      <Card>
        <div className="row">
          {["pending_approval", "sent", "expired", "rejected", "all"].map((f) => (
            <div key={f} style={{ flex: "0 0 auto" }}>
              <button className={filter === f ? "primary" : ""} onClick={() => setFilter(f)}>
                {f.replace(/_/g, " ")}
                {f === "pending_approval" && pendingCount > 0 && ` (${pendingCount})`}
              </button>
            </div>
          ))}
        </div>
      </Card>

      {shown.length === 0 ? (
        <Card><Empty>Nothing in this view.</Empty></Card>
      ) : shown.map((m) => (
        <Card key={m.id}>
          <div className="spread">
            <div>
              <strong>{m.subject}</strong>
              <div className="muted small">
                To {m.to_address} · from {m.from_address} · {m.producer.replace(/_/g, " ")}
              </div>
            </div>
            <div className="right">
              <Pill kind={STATE_KIND[m.state] ?? ""}>{m.state.replace(/_/g, " ")}</Pill>{" "}
              {m.is_ai_generated && <Pill kind="ai">AI-drafted</Pill>}{" "}
              {m.dev_real_send && <Pill kind="warn">sent for real, from dev</Pill>}
            </div>
          </div>

          {m.warning && <Banner kind="warn">{m.warning}</Banner>}

          <div className="muted small" style={{ margin: ".5rem 0" }}>
            {m.send_by && m.state === "pending_approval"
              ? <>Expires {when(m.send_by)} — if not approved by then it will <strong>not</strong> send.</>
              : m.sent_at ? <>Sent {when(m.sent_at)}</> : <>Created {when(m.created_at)}</>}
          </div>

          {open === m.id ? (
            <>
              <textarea
                rows={9}
                value={edited[m.id] ?? m.body_text}
                onChange={(e) => setEdited({ ...edited, [m.id]: e.target.value })}
              />
              <div style={{ marginTop: ".6rem" }}>
                {canSend && (
                  <button className="primary" disabled={approve.isPending}
                    onClick={() => approve.mutate(m.id)}>
                    {approve.isPending ? "Sending…" : "Approve & send"}
                  </button>
                )}{" "}
                <button className="danger" onClick={() => reject.mutate(m.id)}>Reject</button>{" "}
                <button onClick={() => setOpen(null)}>Close</button>
              </div>
            </>
          ) : (
            <>
              <pre className="small" style={{
                whiteSpace: "pre-wrap", background: "#fafbfc", padding: ".7rem",
                borderRadius: "6px", margin: ".4rem 0", fontFamily: "inherit",
              }}>{m.body_text}</pre>
              {(m.state === "pending_approval" || m.state === "draft") && (
                <button onClick={() => setOpen(m.id)}>Review & edit</button>
              )}
            </>
          )}
        </Card>
      ))}
    </>
  );
}
