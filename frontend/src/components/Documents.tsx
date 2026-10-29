import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { FilePlus2 } from "lucide-react";

import { useMailboxes } from "./Mailboxes";
import { SignatureCapture, hasSignature } from "./SignatureCapture";
import { Banner, Card, Empty, Field, Pill } from "./ui";
import {
  CapturedSignature, Contact, DOCUMENT_FIELDS, DocumentState, DocumentTemplate, Me,
  SignDocument, api,
} from "../lib/api";
import { longDate } from "../lib/money";

/**
 * A company's documents for signature (e-signature, 2026-10-29): proposals
 * and engagement letters from Settings → Documents, or any PDF uploaded, to
 * one of the company's contacts, countersigned here. The practice owner and
 * associates make, send, countersign and void; an assistant sees each one's
 * state and nothing in it.
 */

const PILL: Record<DocumentState, "" | "ok" | "warn" | "bad"> = {
  draft: "", sent: "", viewed: "", signed: "warn", declined: "bad", countersigned: "ok",
  complete: "ok", void: "bad", expired: "bad",
};

const CONSENT = "By signing electronically, I agree that my electronic signature is the legal "
  + "equivalent of my handwritten signature on this document, and that it records my "
  + "countersignature for the practice.";

/** The address a document goes to: the contact's primary, else their first. */
function emailOf(contact: Contact): string {
  const emails = contact.emails ?? [];
  return (emails.find((e) => e.is_primary) ?? emails[0])?.address ?? "";
}

function day(iso: string | null | undefined) {
  return iso ? longDate(iso.slice(0, 10)) : "";
}

function timeline(d: SignDocument): string {
  const parts: string[] = [];
  if (d.sent_at) parts.push(`sent ${day(d.sent_at)}`);
  if (d.viewed_at) parts.push(`opened ${day(d.viewed_at)}`);
  if (d.signed_at) parts.push(`signed ${day(d.signed_at)}`);
  if (d.declined_at) parts.push(`declined ${day(d.declined_at)}`);
  if (d.countersigned_at) parts.push(`countersigned ${day(d.countersigned_at)}`
    + (d.countersigned_by ? ` by ${d.countersigned_by}` : ""));
  if (d.voided_at) parts.push(`voided ${day(d.voided_at)}`);
  if ((d.state === "sent" || d.state === "viewed") && d.expires_at)
    parts.push(`expires ${day(d.expires_at)}`);
  return parts.join(" · ");
}

export function DocumentsCard({ me, companyId, people }: {
  me: Me; companyId: string; people: Contact[];
}) {
  const qc = useQueryClient();
  const full = me.role === "FF" || me.role === "CF";
  const [making, setMaking] = useState(false);
  const [note, setNote] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const list = useQuery<SignDocument[]>({
    queryKey: ["documents", companyId],
    queryFn: () => api.get<SignDocument[]>(`/api/documents/?company=${companyId}`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["documents", companyId] });
    qc.invalidateQueries({ queryKey: ["outbox"] });
  };
  const rows = list.data ?? [];
  const signers = people.filter((p) => !!emailOf(p));

  return (
    <Card title="Documents" actions={full && !making ? (
      <button className="small" onClick={() => { setMaking(true); setNote(null); }}>
        <FilePlus2 size={16} /> New document</button>) : undefined}>
      {note && <Banner kind={note.kind}>{note.text}</Banner>}
      {making && (
        <NewDocument companyId={companyId} signers={signers}
          onCancel={() => setMaking(false)}
          onDone={(text) => { setMaking(false); setNote({ kind: "ok", text }); refresh(); }} />
      )}
      {rows.length === 0 && !making ? (
        <Empty>{list.isLoading ? "Loading…" : full
          ? "No documents yet. A proposal or an engagement letter, or any PDF, can be sent "
            + "from here for signature."
          : "No documents yet."}</Empty>
      ) : rows.map((d) => (
        <DocumentRow key={d.id} me={me} document={d} full={full} onChanged={refresh}
          onNote={setNote} />
      ))}
    </Card>
  );
}

function DocumentRow({ me, document: d, full, onChanged, onNote }: {
  me: Me; document: SignDocument; full: boolean; onChanged: () => void;
  onNote: (note: { kind: "ok" | "bad"; text: string }) => void;
}) {
  const [open, setOpen] = useState<"" | "send" | "refill" | "countersign" | "void">("");
  const fail = (e: Error) => onNote({ kind: "bad", text: e.message });
  const demoLink = useMutation({
    mutationFn: () => api.post<{ url: string }>(`/api/documents/${d.id}/demo-link/`),
    onSuccess: (r) => { window.open(r.url, "_blank", "noopener"); },
    onError: fail,
  });
  const path = `/api/documents/${d.id}/pdf/`;
  const waitingOnOutbox = d.request && ["draft", "pending_approval", "approved"]
    .includes(d.request.state);

  return (
    <div className="doc-row">
      <div className="doc-main">
        <strong>{d.title}</strong> <Pill kind={PILL[d.state]}>{d.state_label}</Pill>
        <div className="small muted">
          To {d.signer.name} ({d.signer.email}){timeline(d) && <> · {timeline(d)}</>}
        </div>
        {d.state === "draft" && waitingOnOutbox && (
          <div className="small">Its email is waiting for approval in the{" "}
            <Link to="/outbox">Outbox</Link>{d.request?.from && <> (from {d.request.from})</>}.
          </div>
        )}
        {d.state === "draft" && d.request && !waitingOnOutbox && (
          <div className="small muted">Its email was {d.request.state_label.toLowerCase()}.</div>
        )}
        {d.state === "signed" && full && (
          <div className="small"><strong>Needs your countersignature.</strong></div>
        )}
        {d.decline_reason && <div className="small">Why: “{d.decline_reason}”</div>}
        {d.void_reason && <div className="small muted">Voided: {d.void_reason}</div>}
        {full && d.final_sha256 && (
          <div className="small muted" style={{ overflowWrap: "anywhere" }}>
            Final PDF SHA-256 {d.final_sha256}</div>
        )}
      </div>
      {full && (
        <div className="doc-actions">
          <a className="btn small ghost" href={path} target="_blank" rel="noreferrer">PDF</a>
          {d.has_final_pdf && <a className="btn small ghost" href={`${path}?which=final`}
            target="_blank" rel="noreferrer">Signed copy</a>}
          {!d.has_final_pdf && d.has_signed_pdf && <a className="btn small ghost"
            href={`${path}?which=signed`} target="_blank" rel="noreferrer">Signed by client</a>}
          {d.can?.send && <button className="small primary" onClick={() => setOpen("send")}>
            Send for signature</button>}
          {d.can?.refill && <button className="small" onClick={() => setOpen("refill")}>
            Fill in</button>}
          {d.can?.countersign && <button className="small primary"
            onClick={() => setOpen("countersign")}>Countersign</button>}
          {me.environment === "demo" && (d.state === "sent" || d.state === "viewed") && (
            <button className="small" disabled={demoLink.isPending}
              onClick={() => demoLink.mutate()}>Open the signing page</button>)}
          {d.can?.void && <button className="small ghost" onClick={() => setOpen("void")}>
            Void</button>}
        </div>
      )}
      {open === "send" && <SendPanel document={d} onClose={() => setOpen("")}
        onDone={() => { setOpen(""); onChanged(); onNote({ kind: "ok", text:
          "Its email is in the Outbox, waiting for approval. The link is added when it goes." }); }} />}
      {open === "refill" && <RefillPanel document={d} onClose={() => setOpen("")}
        onDone={() => { setOpen(""); onChanged(); onNote({ kind: "ok", text: "Filled in: a new PDF." }); }} />}
      {open === "countersign" && <CountersignPanel me={me} document={d}
        onClose={() => setOpen("")}
        onDone={() => { setOpen(""); onChanged(); onNote({ kind: "ok", text:
          "Countersigned. The signed copy is emailed to both of you." }); }} />}
      {open === "void" && <VoidPanel document={d} onClose={() => setOpen("")}
        onDone={() => { setOpen(""); onChanged(); onNote({ kind: "ok", text: "Voided. Its link no longer works." }); }} />}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel" style={{ flexBasis: "100%", marginTop: "var(--s2)" }}>
      <strong className="small">{title}</strong>
      <div style={{ marginTop: "var(--s2)" }}>{children}</div>
    </div>
  );
}

/** "From": a connected mailbox, or the defaults (the company's, then yours). */
function FromSelect({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const boxes = useMailboxes();
  const usable = (boxes.data?.mailboxes ?? []).filter((m) => m.connected);
  return (
    <Field label="From">
      <select aria-label="From" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">The usual for this company</option>
        {usable.map((m) => (
          <option key={m.id} value={m.id}>{m.label} ({m.sends_as || m.email_address})</option>
        ))}
      </select>
    </Field>
  );
}

function SendPanel({ document: d, onClose, onDone }: {
  document: SignDocument; onClose: () => void; onDone: () => void;
}) {
  const [mailbox, setMailbox] = useState("");
  const [problem, setProblem] = useState("");
  const send = useMutation({
    mutationFn: () => api.post(`/api/documents/${d.id}/send/`, { mailbox: mailbox || null }),
    onSuccess: onDone, onError: (e: Error) => setProblem(e.message),
  });
  return (
    <Panel title={`Send ${d.title} to ${d.signer.name}`}>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <FromSelect value={mailbox} onChange={setMailbox} />
      <div className="row tight">
        <button className="primary" disabled={send.isPending} onClick={() => send.mutate()}>
          Put it in the Outbox</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Panel>
  );
}

function FieldInputs({ used, values, onChange }: {
  used: string[]; values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
}) {
  const shown = DOCUMENT_FIELDS.filter((f) => used.includes(f.field));
  if (!shown.length) return null;
  return (
    <div className="doc-fields">
      {shown.map((f) => (
        <div key={f.field} className={f.long ? "wide" : undefined}>
          <Field label={f.label}>
            {f.long ? (
              <textarea aria-label={f.label} rows={3} value={values[f.field] ?? ""}
                onChange={(e) => onChange({ ...values, [f.field]: e.target.value })} />
            ) : (
              <input aria-label={f.label} type={f.date ? "date" : "text"}
                value={values[f.field] ?? ""}
                onChange={(e) => onChange({ ...values, [f.field]: e.target.value })} />
            )}
          </Field>
        </div>
      ))}
    </div>
  );
}

function RefillPanel({ document: d, onClose, onDone }: {
  document: SignDocument; onClose: () => void; onDone: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(d.fields ?? {});
  const [problem, setProblem] = useState("");
  const save = useMutation({
    mutationFn: () => api.patch(`/api/documents/${d.id}/fields/`, { fields: values }),
    onSuccess: onDone, onError: (e: Error) => setProblem(e.message),
  });
  return (
    <Panel title="Fill in again">
      {problem && <Banner kind="bad">{problem}</Banner>}
      <FieldInputs used={d.fields_used ?? []} values={values} onChange={setValues} />
      <div className="row tight">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          Save and make the PDF again</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Panel>
  );
}

function CountersignPanel({ me, document: d, onClose, onDone }: {
  me: Me; document: SignDocument; onClose: () => void; onDone: () => void;
}) {
  const [value, setValue] = useState<CapturedSignature>({
    method: "typed", typed: me.full_name || "", drawn: "" });
  const [agreed, setAgreed] = useState(false);
  const [problem, setProblem] = useState("");
  const sign = useMutation({
    mutationFn: () => api.post(`/api/documents/${d.id}/countersign/`, { agreed, ...value }),
    onSuccess: onDone, onError: (e: Error) => setProblem(e.message),
  });
  return (
    <Panel title={`Countersign ${d.title}`}>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        {d.signer.name} signed it. Your countersignature completes it: the signature page
        gets both signatures, and the signed copy is emailed to them and to you.</p>
      <SignatureCapture value={value} onChange={setValue}
        consent={d.countersign_consent || CONSENT} agreed={agreed}
        onAgree={setAgreed} />
      <div className="row tight" style={{ marginTop: "var(--s3)" }}>
        <button className="primary" disabled={!agreed || !hasSignature(value) || sign.isPending}
          onClick={() => sign.mutate()}>{sign.isPending ? "Countersigning…" : "Countersign"}</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Panel>
  );
}

function VoidPanel({ document: d, onClose, onDone }: {
  document: SignDocument; onClose: () => void; onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState("");
  const go = useMutation({
    mutationFn: () => api.post(`/api/documents/${d.id}/void/`, { reason }),
    onSuccess: onDone, onError: (e: Error) => setProblem(e.message),
  });
  return (
    <Panel title={`Void ${d.title}`}>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <Field label="Why (for the record)">
        <input aria-label="Why it is voided" value={reason}
          onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="row tight">
        <button className="danger" disabled={go.isPending} onClick={() => go.mutate()}>
          Void it</button>
        <button className="ghost" onClick={onClose}>Keep it</button>
      </div>
    </Panel>
  );
}

/** New document: a template filled in, or a PDF; its signer; a preview; then
 *  From, and its email into the Outbox. */
function NewDocument({ companyId, signers, onCancel, onDone }: {
  companyId: string; signers: Contact[]; onCancel: () => void; onDone: (text: string) => void;
}) {
  const templates = useQuery<DocumentTemplate[]>({
    queryKey: ["document-templates"],
    queryFn: () => api.get<DocumentTemplate[]>("/api/document-templates/"),
  });
  const [kind, setKind] = useState<"template" | "upload">("template");
  const [templateId, setTemplateId] = useState("");
  const [signer, setSigner] = useState(signers[0]?.id ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [mailbox, setMailbox] = useState("");
  const [problem, setProblem] = useState("");
  const template = (templates.data ?? []).find((t) => t.id === templateId)
    ?? (templates.data ?? [])[0];
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const look = useMutation({
    mutationFn: async () => {
      if (kind === "upload") {
        if (!file) throw new Error("Choose the PDF to upload.");
        return URL.createObjectURL(file);
      }
      const pdf = await api.blob("/api/documents/preview/", {
        company: companyId, signer, template: template?.id, fields: values });
      return URL.createObjectURL(pdf);
    },
    onSuccess: (url) => { setProblem(""); setPreview(url); },
    onError: (e: Error) => setProblem(e.message),
  });
  const make = useMutation({
    mutationFn: async () => {
      let made: SignDocument;
      if (kind === "upload") {
        if (!file) throw new Error("Choose the PDF to upload.");
        const form = new FormData();
        form.append("company", companyId);
        form.append("signer", signer);
        form.append("title", title);
        form.append("file", file);
        made = await api.post<SignDocument>("/api/documents/", form);
      } else {
        made = await api.post<SignDocument>("/api/documents/", {
          company: companyId, signer, template: template?.id, fields: values });
      }
      await api.post(`/api/documents/${made.id}/send/`, { mailbox: mailbox || null });
      return made;
    },
    onSuccess: (made) => onDone(`${made.title} is in the Outbox, waiting for approval. `
      + "The signing link is added when it goes."),
    onError: (e: Error) => setProblem(e.message),
  });

  const change = (fn: () => void) => { fn(); setPreview(""); };
  if (!signers.length) {
    return (
      <div className="panel">
        <p className="small" style={{ marginTop: 0 }}>Nobody at this company has an email address
          to send a document to. Add one on a contact first.</p>
        <button className="ghost" onClick={onCancel}>Close</button>
      </div>
    );
  }
  return (
    <div className="panel" style={{ marginBottom: "var(--s3)" }}>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <div className="sig-tabs" role="group" aria-label="What to send"
        style={{ marginBottom: "var(--s3)" }}>
        {(["template", "upload"] as const).map((k) => (
          <button key={k} type="button" aria-pressed={kind === k}
            className={kind === k ? "small primary" : "small"}
            onClick={() => change(() => setKind(k))}>
            {k === "template" ? "From a template" : "Upload a PDF"}</button>
        ))}
      </div>
      <div className="doc-fields">
        {kind === "template" ? (
          <Field label="Template">
            <select aria-label="Template" value={template?.id ?? ""}
              onChange={(e) => change(() => setTemplateId(e.target.value))}>
              {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
        ) : (
          <>
            <Field label="Title">
              <input aria-label="Title" value={title} placeholder="Master services agreement"
                onChange={(e) => change(() => setTitle(e.target.value))} />
            </Field>
            <Field label="PDF">
              <input aria-label="PDF" type="file" accept="application/pdf,.pdf"
                onChange={(e) => change(() => setFile(e.target.files?.[0] ?? null))} />
            </Field>
          </>
        )}
        <Field label="Signer">
          <select aria-label="Signer" value={signer}
            onChange={(e) => change(() => setSigner(e.target.value))}>
            {signers.map((p) => <option key={p.id} value={p.id}>
              {p.first_name} {p.last_name} ({emailOf(p)})</option>)}
          </select>
        </Field>
      </div>
      {kind === "template" && template && (
        <FieldInputs used={template.fields_used} values={values}
          onChange={(v) => change(() => setValues(v))} />
      )}
      <div className="row tight" style={{ marginTop: "var(--s2)" }}>
        <button disabled={look.isPending} onClick={() => look.mutate()}>
          {look.isPending ? "Making the preview…" : "Preview"}</button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
      {preview && (
        <>
          <iframe className="pdf-frame" title="Preview" src={preview}
            style={{ width: "100%", height: "60vh", minHeight: 320, marginTop: "var(--s3)",
                     border: "1px solid var(--line)", borderRadius: "var(--radius-sm)" }} />
          <FromSelect value={mailbox} onChange={setMailbox} />
          <div className="row tight">
            <button className="primary" disabled={make.isPending} onClick={() => make.mutate()}>
              {make.isPending ? "Putting it in the Outbox…" : "Send for approval"}</button>
          </div>
          <p className="small muted">It goes in the Outbox like every email, and is sent when
            it is approved. The signer gets a link of their own, good for 30 days.</p>
        </>
      )}
    </div>
  );
}
