import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { BulkBar } from "../components/BulkBar";
import { RichText, toPlainText } from "../components/RichText";
import { Banner, Card, Pill, when } from "../components/ui";
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
  const [subjects, setSubjects] = useState<Record<string, string>>({});
  const [senderChoice, setSenderChoice] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<string[]>([]);

  const me = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const messages = useQuery<OutboxMessage[]>({
    queryKey: ["outbox"], queryFn: () => api.get<OutboxMessage[]>("/api/outbox/"),
  });

  const canSend = me.data?.role === "FF" || me.data?.role === "CF";

  /** A plain-text draft rendered into the HTML editor without losing its breaks. */
  function textToHtml(text: string) {
    return (text || "")
      .split(/\n{2,}/)
      .map((para) => `<p>${para.replace(/\n/g, "<br>")}</p>`)
      .join("");
  }

  /** Persist edits before approving, so what was read is what is sent. */
  const saveEdits = useMutation({
    mutationFn: (id: string) => {
      const html = edited[id];
      return api.patch(`/api/outbox/${id}/edit/`, {
        ...(subjects[id] !== undefined ? { subject: subjects[id] } : {}),
        ...(html !== undefined
          ? { body_html: html, body_text: toPlainText(html) } : {}),
        ...(senderChoice[id] ? { sender: senderChoice[id] } : {}),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbox"] }),
  });

  const addAttachment = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return api.post(`/api/outbox/${id}/attachments/`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbox"] }),
    onError: (e: Error) => setNote(e.message),
  });

  const removeAttachment = useMutation({
    mutationFn: ({ id, attachment }: { id: string; attachment: string }) =>
      api.del(`/api/outbox/${id}/attachments/${attachment}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outbox"] }),
  });

  const approveSelected = useMutation({
    mutationFn: () => api.post<{ approved_count: number; failed: { to: string; detail: string }[] }>(
      "/api/outbox/approve-selected/", { ids: picked },
    ),
    onSuccess: (r) => {
      setNote(
        `${r.approved_count} approved and sent.`
        + (r.failed.length
          ? ` ${r.failed.length} failed: ${r.failed.map((f) => `${f.to} (${f.detail})`).join(", ")}.`
          : ""),
      );
      setPicked([]);
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

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

      {filter === "pending_approval" && shown.length > 0 && canSend && (
        <Card>
          <BulkBar
            total={shown.length} selected={picked.length}
            onSelectAll={() => setPicked(shown.map((m) => m.id))}
            onClear={() => setPicked([])}
          >
            <button className="primary" disabled={!picked.length || approveSelected.isPending}
              onClick={() => approveSelected.mutate()}>
              Approve {picked.length || ""} selected
            </button>
          </BulkBar>
          <p className="muted small" style={{ marginBottom: 0 }}>
            Each one is still approved individually — this is one review pass over a
            batch, not a way around approval. Read them before you tick them.
          </p>
        </Card>
      )}

      {shown.length === 0 ? (
        <Card title={filter === "all" ? "Nothing here yet" : `No ${filter.replace(/_/g, " ")} messages`}>
          <p className="muted small">
            <strong>Every email the app sends is a row here</strong> — the Outbox is both
            the approval queue and the complete send log. If a message left the app,
            there is a row for it.
          </p>
          <p className="muted small">What lands here, and from where:</p>
          <ul className="muted small">
            <li><strong>Stage automations</strong> — a rule with “draft an email” queues one
              when a contact reaches its stage.</li>
            <li><strong>Referral touches</strong> — drafted 3 days before each partner's due
              date, or on demand with <em>Draft touch now</em> on the contact.</li>
            <li><strong>Referral onboarding</strong> — queued the moment someone first
              becomes a referral partner.</li>
            <li><strong>Anything you send from a contact</strong> — those are written
              straight to <em>sent</em>, because your click was the approval.</li>
          </ul>
          <p className="muted small" style={{ marginBottom: 0 }}>
            Nothing here sends itself. A draft left unapproved past its send-by date
            <strong> expires</strong> rather than going out.
          </p>
        </Card>
      ) : shown.map((m) => (
        <Card key={m.id}>
          <div className="spread">
            <div>
              {m.state === "pending_approval" && canSend && (
                <input type="checkbox" checked={picked.includes(m.id)}
                  aria-label={`Select ${m.subject}`}
                  style={{ marginRight: ".5rem" }}
                  onChange={(e) => setPicked(e.target.checked
                    ? [...picked, m.id]
                    : picked.filter((x) => x !== m.id))} />
              )}
              <strong>{m.subject}</strong>
              <div className="muted small">
                To {m.to_address} · from {m.from_address} · {m.producer.replace(/_/g, " ")}
              </div>
              {/* FR-0.7 — answered BEFORE approval: is a real person about to
                  receive this? `dev_real_send` is only written after a send. */}
              <div className="small" style={{ marginTop: ".3rem" }}>
                <Pill kind={m.delivery?.target === "real" ? "warn" : ""}>
                  {m.delivery?.label ?? "—"}
                </Pill>
                {m.delivery?.detail && (
                  <span className="muted"> {m.delivery.detail}</span>
                )}
              </div>
            </div>
            <div className="right">
              <Pill kind={STATE_KIND[m.state] ?? ""}>{m.state.replace(/_/g, " ")}</Pill>{" "}
              {m.is_ai_generated && <Pill kind="ai">AI-drafted</Pill>}{" "}
              {m.dev_real_send && <Pill kind="warn">sent for real, from dev</Pill>}
            </div>
          </div>

          {m.warning && <Banner kind="warn">{m.warning}</Banner>}

          {/* FR-1.23b — the flyer was always attached; the Outbox never said so,
              which read as "no attachment" to the one person who needed to know. */}
          {(m.attachments ?? []).length > 0 && (
            <ul className="attachments muted">
              {m.attachments.map((a) => (
                <li key={a.id}>
                  📎 {a.filename} · {Math.max(1, Math.round(a.byte_size / 1024))} KB
                  {a.content_present === false && (
                    <> <Pill kind="bad">file missing — re-upload before sending</Pill></>
                  )}
                  {open === m.id && m.state === "pending_approval" && (
                    <>{" "}
                      <button className="ghost small"
                        aria-label={`Remove ${a.filename}`}
                        onClick={() => removeAttachment.mutate({ id: m.id, attachment: a.id })}>
                        Remove
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="muted small" style={{ margin: ".5rem 0" }}>
            {m.send_by && m.state === "pending_approval"
              ? <>Expires {when(m.send_by)} — if not approved by then it will <strong>not</strong> send.</>
              : m.sent_at ? <>Sent {when(m.sent_at)}</> : <>Created {when(m.created_at)}</>}
          </div>

          {open === m.id ? (
            <>
              {(m.sender_options ?? []).length > 1 && (
                <div style={{ marginBottom: ".6rem" }}>
                  <label htmlFor={`sender-${m.id}`}>Send from</label>
                  <select id={`sender-${m.id}`}
                    value={senderChoice[m.id] ?? ""}
                    onChange={(e) => setSenderChoice({ ...senderChoice, [m.id]: e.target.value })}>
                    <option value="">{m.from_address} (as drafted)</option>
                    {m.sender_options.map((o) => (
                      <option key={o.value} value={o.value}>{o.label} — {o.address}</option>
                    ))}
                  </select>
                </div>
              )}

              <label>Subject</label>
              <input value={subjects[m.id] ?? m.subject}
                aria-label="Subject"
                onChange={(e) => setSubjects({ ...subjects, [m.id]: e.target.value })} />

              <RichText
                label="Message body"
                value={edited[m.id] ?? m.body_html ?? textToHtml(m.body_text)}
                onChange={(html) => setEdited({ ...edited, [m.id]: html })}
              />

              <div style={{ marginTop: ".5rem" }}>
                <label htmlFor={`attach-${m.id}`} className="muted small">Add an attachment</label>
                <input id={`attach-${m.id}`} type="file" aria-label="Add an attachment"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) addAttachment.mutate({ id: m.id, file });
                  }} />
              </div>
              <div style={{ marginTop: ".6rem" }}>
                {canSend && (
                  <button className="primary" disabled={approve.isPending}
                    onClick={async () => {
                      await saveEdits.mutateAsync(m.id);
                      approve.mutate(m.id);
                    }}>
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
