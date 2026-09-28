import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Check, Pencil, Search, SkipForward } from "lucide-react";

import { RichText } from "../components/RichText";
import { FilterBar, PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill, countdown } from "../components/ui";
import { Me, api } from "../lib/api";

type Category = "marketing" | "updates" | "transactional" | "correspondence";

interface QueueItem {
  key: string;
  kind: "outbox" | "digest";
  id: string;
  category: Category;
  label: string;
  to_name: string;
  to_address: string;
  from_address: string;
  subject: string;
  created_at: string;
  expires_at: string | null;
  /** "when approved", or — for a digest — "at its send window, …". */
  sends: string;
  warning: string;
  is_ai_generated: boolean;
  body_text: string;
  body_html: string;
}

interface Preview { subject: string; from: string; to: string; html: string; text: string }

const CATEGORIES: [Category | "", string][] = [
  ["", "All"], ["marketing", "Marketing"], ["updates", "Updates"],
  ["transactional", "Transactional"], ["correspondence", "Correspondence"],
];

const CATEGORY_KIND: Record<Category, string> = {
  marketing: "warn", updates: "ok", transactional: "", correspondence: "",
};

/**
 * Everything waiting to be sent, of every kind, in one list (owner,
 * 2026-09-28). Nothing leaves without approval here; what waits, and why, is
 * exactly as before — a digest approved here still goes at its send window.
 * The Outbox is the send log.
 */
export function SendingQueue({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [category, setCategory] = useState<Category | "">("");
  const [recipient, setRecipient] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const mayApprove = me.role === "FF" || me.role === "CF";

  const all = useQuery<QueueItem[]>({
    queryKey: ["sending-queue"], queryFn: () => api.get<QueueItem[]>("/api/sending-queue/"),
  });
  const rows = (all.data ?? []).filter((r) => (!category || r.category === category)
    && (!recipient.trim()
        || `${r.to_name} ${r.to_address}`.toLowerCase().includes(recipient.trim().toLowerCase())));
  const inView = picked.filter((key) => rows.some((r) => r.key === key));
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["sending-queue"] });
    qc.invalidateQueries({ queryKey: ["queue-preview"] });
  };

  const act = useMutation({
    mutationFn: ({ verb, keys }: { verb: "approve" | "skip"; keys: string[] }) =>
      api.post<{ done_count: number; failed: { key: string; detail: string }[] }>(
        `/api/sending-queue/${verb}/`, { keys }),
    onSuccess: (r, { verb }) => {
      const failed = r.failed.length
        ? ` ${r.failed.length} not ${verb === "approve" ? "approved" : "skipped"}: `
          + r.failed.map((f) => f.detail).join(" · ")
        : "";
      setNote(`${r.done_count} ${verb === "approve" ? "approved" : "skipped"}.${failed}`);
      setPicked([]);
      refresh();
    },
    onError: (e: Error) => setNote(e.message),
  });

  const counts = (key: Category | "") =>
    (all.data ?? []).filter((r) => !key || r.category === key).length;

  return (
    <>
      <PageHead title="Sending queue"
        sub="Everything waiting to be sent, of every kind. Nothing leaves without approval; a
             digest approved here goes at its send window. The Outbox is the send log." />
      {note && <Banner kind="info">{note}</Banner>}

      <FilterBar>
        <span className="search">
          <Search size={16} strokeWidth={1.75} />
          <input aria-label="Filter by recipient" placeholder="Recipient"
            value={recipient} onChange={(e) => { setRecipient(e.target.value); setPicked([]); }} />
        </span>
      </FilterBar>
      <div className="queue-filters">
        <div className="tabs" role="tablist" aria-label="Category">
          {CATEGORIES.map(([value, label]) => (
            <button key={label} role="tab" aria-selected={category === value}
              className={category === value ? "tab on" : "tab"}
              onClick={() => { setCategory(value); setPicked([]); }}>
              {label} <span className="count">{counts(value)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="queue">
        <Card>
          <div className="spread queue-bar">
            <span className="small">
              <input type="checkbox" aria-label="Select all in this view"
                style={{ width: "auto" }}
                checked={rows.length > 0 && inView.length === rows.length}
                onChange={(e) => setPicked(e.target.checked ? rows.map((r) => r.key) : [])} />
              {" "}{inView.length} of {rows.length} selected
            </span>
            <span className="inline">
              {mayApprove && (
                <button className="small" disabled={!inView.length || act.isPending}
                  onClick={() => act.mutate({ verb: "approve", keys: inView })}>
                  <Check size={16} /> Approve selected
                </button>
              )}
              <button className="small" disabled={!inView.length || act.isPending}
                onClick={() => act.mutate({ verb: "skip", keys: inView })}>
                <SkipForward size={16} /> Skip selected
              </button>
            </span>
          </div>
          {rows.length === 0 ? <Empty>Nothing waiting{category ? " in this category" : ""}.</Empty> : (
            <ul className="queue-list">
              {rows.map((r) => (
                <li key={r.key} className={open === r.key ? "on" : ""}>
                  <input type="checkbox" aria-label={`Select ${r.subject} to ${r.to_name || r.to_address}`}
                    style={{ width: "auto" }} checked={picked.includes(r.key)}
                    onChange={(e) => setPicked(e.target.checked
                      ? [...picked, r.key] : picked.filter((k) => k !== r.key))} />
                  <button className="queue-row" onClick={() => setOpen(r.key)}>
                    <span className="queue-subject">{r.subject || "(no subject)"}</span>
                    <span className="small muted">
                      {r.to_name || r.to_address} · {r.label}
                      {r.expires_at && <> · {r.kind === "digest" ? "window" : "expires"}{" "}
                        {countdown(r.expires_at)}</>}
                    </span>
                    <span className="inline">
                      <Pill kind={CATEGORY_KIND[r.category]}>{r.category}</Pill>
                      {r.is_ai_generated && <Pill kind="ai">AI-drafted</Pill>}
                      {r.warning && <Pill kind="bad">check</Pill>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {open && rows.some((r) => r.key === open) ? (
          <Detail item={rows.find((r) => r.key === open)!} mayApprove={mayApprove}
            busy={act.isPending}
            onAct={(verb) => act.mutate({ verb, keys: [open] })}
            onSaved={() => { setNote("Saved. The preview shows the edit."); refresh(); }} />
        ) : (
          <Card><Empty>Choose one to see it exactly as it will land.</Empty></Card>
        )}
      </div>
    </>
  );
}

function Detail({ item, mayApprove, busy, onAct, onSaved }: {
  item: QueueItem; mayApprove: boolean; busy: boolean;
  onAct: (verb: "approve" | "skip") => void; onSaved: () => void;
}) {
  const [part, setPart] = useState<"html" | "text">("html");
  const [editing, setEditing] = useState(false);
  const preview = useQuery<Preview>({
    queryKey: ["queue-preview", item.key],
    queryFn: () => api.get<Preview>(`/api/sending-queue/preview/?key=${encodeURIComponent(item.key)}`),
  });
  const p = preview.data;

  return (
    <Card title={p?.subject || item.subject}
      actions={
        <span className="inline">
          {mayApprove && (
            <button className="primary" disabled={busy} onClick={() => onAct("approve")}>
              <Check size={16} /> Approve
            </button>
          )}
          <button disabled={busy} onClick={() => setEditing(!editing)}>
            <Pencil size={16} /> {editing ? "Close editor" : "Edit"}
          </button>
          <button disabled={busy} onClick={() => onAct("skip")}>
            <SkipForward size={16} /> Skip
          </button>
        </span>
      }>
      <p className="small muted">
        From {p?.from || item.from_address} · to {item.to_name ? `${item.to_name} ` : ""}
        &lt;{p?.to || item.to_address}&gt; · sends {item.sends}
      </p>
      {item.warning && <Banner kind="warn">{item.warning}</Banner>}
      {!mayApprove && (
        <p className="small muted">Only the founder or a fractional approves. You can edit or
          skip.</p>
      )}
      {editing && <Editor item={item} onSaved={() => { setEditing(false); onSaved(); }} />}
      <div className="tabs" role="tablist" aria-label="Which part">
        {(["html", "text"] as const).map((which) => (
          <button key={which} role="tab" aria-selected={part === which}
            className={part === which ? "tab on" : "tab"} onClick={() => setPart(which)}>
            {which === "html" ? "Email" : "Plain text"}
          </button>
        ))}
      </div>
      {part === "html"
        ? <iframe title="Exactly as it lands" className="email-preview" sandbox=""
            srcDoc={p?.html ?? ""} />
        : <pre className="email-text">{p?.text ?? ""}</pre>}
    </Card>
  );
}

/** The same edits their own screens allow: an Outbox draft's subject and
 *  body; a digest's words. */
function Editor({ item, onSaved }: { item: QueueItem; onSaved: () => void }) {
  const [subject, setSubject] = useState(item.subject);
  const [html, setHtml] = useState(item.body_html
    || item.body_text.split(/\n\s*\n/).map((p) => `<p>${p.replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/\n/g, "<br>")}</p>`).join(""));
  const [text, setText] = useState(item.body_text);
  const save = useMutation({
    mutationFn: () => item.kind === "outbox"
      ? api.patch(`/api/outbox/${item.id}/edit/`, { subject, body_html: html, body_text: text })
      : api.post(`/api/digests/${item.id}/edit/`, { body_text: text }),
    onSuccess: onSaved,
  });
  return (
    <div className="queue-editor">
      {item.kind === "outbox" ? (
        <>
          <Field label="Subject">
            <input aria-label="Edit subject" value={subject}
              onChange={(e) => setSubject(e.target.value)} />
          </Field>
          <RichText label="Edit body" value={html}
            onChange={(h, t) => { setHtml(h); setText(t); }} />
        </>
      ) : (
        <Field label="The digest's words">
          <textarea aria-label="Edit digest" rows={10} value={text}
            onChange={(e) => setText(e.target.value)} />
        </Field>
      )}
      <button className="primary small" disabled={save.isPending} onClick={() => save.mutate()}>
        Save edit
      </button>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
    </div>
  );
}
