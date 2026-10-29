import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill, when } from "./ui";
import { Company, MailItem, MailPage, Mailbox, Mailboxes, Me, api } from "../lib/api";

/**
 * The practice's mailboxes (2026-10-28): someone's own (their connection
 * above), a shared address like info@, or a client's mailbox the practice
 * runs. Each sends as its own checked address, reads replies when it was
 * connected with permission to, and files mail with contacts and companies
 * when that is turned on; disconnecting one stops both.
 */
export function useMailboxes(enabled = true) {
  return useQuery<Mailboxes>({
    queryKey: ["mailboxes"],
    queryFn: () => api.get<Mailboxes>("/api/mailboxes/"),
    enabled, retry: false,
  });
}

export function MailboxesCard() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const list = useMailboxes();
  useEffect(() => {
    const connected = params.get("mailbox_connected");
    const warning = params.get("mailbox_warning");
    if (connected) setNote(`Connected ${connected}.`);
    if (warning) setProblem(warning);
    if (connected || warning) {
      const next = new URLSearchParams(params);
      next.delete("mailbox_connected"); next.delete("mailbox_warning");
      setParams(next, { replace: true });
      qc.invalidateQueries({ queryKey: ["mailboxes"] });
    }
  }, [params, setParams, qc]);
  const said = (data: Mailbox | Mailboxes, ok: string) => {
    if ("mailboxes" in data) qc.setQueryData(["mailboxes"], data);
    else qc.invalidateQueries({ queryKey: ["mailboxes"] });
    const error = "verify_error" in data ? data.verify_error : "";
    if (error) { setProblem(error); setNote(""); } else { setNote(ok); setProblem(""); }
  };
  const disconnect = useMutation({
    mutationFn: (m: Mailbox) => api.post<Mailboxes>(`/api/mailboxes/${m.id}/disconnect/`),
    onSuccess: (data, m) => said(data, `Disconnected ${m.email_address}. Nothing is sent through it or read from it now.`),
    onError: (e: Error) => setProblem(e.message),
  });
  const verify = useMutation({
    mutationFn: (m: Mailbox) => api.post<Mailbox>(`/api/mailboxes/${m.id}/verify/`),
    onSuccess: (data) => said(data, `${data.sends_as} is checked. Mail from this mailbox sends as it.`),
    onError: (e: Error) => setProblem(e.message),
  });
  const change = useMutation({
    mutationFn: ({ m, body }: { m: Mailbox; body: Record<string, unknown> }) =>
      api.patch<Mailbox>(`/api/mailboxes/${m.id}/`, body),
    onSuccess: (data) => said(data, `Saved ${data.email_address}.`),
    onError: (e: Error) => setProblem(e.message),
  });

  if (list.isLoading) return null;
  if (list.isError) return null;
  const rows = list.data!.mailboxes;
  return (
    <Card title="Mailboxes"
      actions={!adding && <button className="primary" onClick={() => setAdding(true)}>
        Connect another mailbox</button>}>
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      <p className="muted small">
        Every mailbox the practice sends from and reads. Someone&apos;s own is their
        connection above; a shared address (like info@) or a client&apos;s mailbox is
        connected here, with its own sign-in. Disconnecting one stops sending through it and
        reading it at once.
      </p>
      {adding && <ConnectMailbox onCancel={() => setAdding(false)} onProblem={setProblem} />}
      {rows.length === 0 ? <Empty>No mailbox is connected yet.</Empty> : (
        <ul className="mailbox-list">
          {rows.map((m) => (
            <li key={m.id} className="mailbox-row">
              <div className="spread">
                <div>
                  <strong>{m.label || m.email_address}</strong>{" "}
                  {m.connected ? <Pill kind="ok">connected</Pill> : <Pill kind="warn">disconnected</Pill>}
                  {" "}<Pill>{m.kind === "client" && m.company_name ? `${m.company_name}'s` : m.kind_label}</Pill>
                  {m.provider === "microsoft" && <> <Pill>{m.provider_label}</Pill></>}
                  <div className="muted small">{m.email_address}
                    {m.connected && m.sends_as && m.sends_as !== m.email_address && <> · sends as {m.sends_as}</>}
                    {m.connected_by && m.kind !== "own" && <> · connected by {m.connected_by}</>}
                  </div>
                </div>
                {m.connected && m.kind !== "own" && m.may_change && (
                  <div className="row tight">
                    <button className="ghost small" disabled={verify.isPending}
                      onClick={() => verify.mutate(m)}>Check send-as</button>
                    <button className="danger small" disabled={disconnect.isPending}
                      aria-label={`Disconnect ${m.email_address}`}
                      onClick={() => disconnect.mutate(m)}>Disconnect</button>
                  </div>
                )}
              </div>
              {m.connected && (
                <div className="muted small">
                  {m.kind !== "own" && (m.send_as_verified
                    ? <>Send-as <Pill kind="ok">checked</Pill></>
                    : <>Send-as <Pill kind="warn">not checked</Pill>{m.send_as_error && ` ${m.send_as_error}`}</>)}
                  {" "}Replies {m.reads ? <Pill kind="ok">collected</Pill> : <Pill>not read</Pill>}
                  {m.reads && m.may_change && (
                    <label className="choice inline">
                      <input type="checkbox" checked={m.files_mail} disabled={change.isPending}
                        aria-label={`File mail with contacts and companies from ${m.email_address}`}
                        onChange={(e) => change.mutate({ m, body: { files_mail: e.target.checked } })} />
                      <span>File mail with contacts and companies</span>
                    </label>
                  )}
                  {m.files_mail && m.files_after && <> · filed from {when(m.files_after)}</>}
                  {m.files_error && <Banner kind="warn">{m.files_error}</Banner>}
                  {m.last_poll_error && <Banner kind="warn">{m.last_poll_error}</Banner>}
                </div>
              )}
              {list.data!.is_local_build && m.allowlist.length > 0 && (
                <div className="muted small">Real mail from this mailbox on this laptop also goes to: {m.allowlist.map((e) => e.address).join(", ")}</div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">
        &ldquo;File mail with contacts and companies&rdquo; reads new mail in that mailbox and keeps
        only messages to or from a contact, or someone at a company&apos;s domain, on their
        Mail tab. Anything else, personal mail included, is never stored.
      </p>
    </Card>
  );
}

function ConnectMailbox({ onCancel, onProblem }: {
  onCancel: () => void; onProblem: (text: string) => void;
}) {
  const [kind, setKind] = useState<"shared" | "client">("shared");
  const [label, setLabel] = useState("");
  const [company, setCompany] = useState("");
  const [provider, setProvider] = useState<"gmail" | "microsoft">("gmail");
  const [inbound, setInbound] = useState(true);
  const [files, setFiles] = useState(false);
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
    enabled: kind === "client",
  });
  const start = useMutation({
    mutationFn: () => api.post<{ authorization_url: string }>("/api/mailboxes/start/", {
      kind, label, company: kind === "client" ? company : "", provider, inbound,
      files_mail: inbound && files }),
    onSuccess: (data) => { window.location.href = data.authorization_url; },
    onError: (e: Error) => onProblem(e.message),
  });
  return (
    <div className="mailbox-connect">
      <div className="row">
        <Field label="Whose mailbox">
          <select aria-label="Whose mailbox" value={kind}
            onChange={(e) => setKind(e.target.value as "shared" | "client")}>
            <option value="shared">A shared address, like info@</option>
            <option value="client">A client&apos;s mailbox the practice runs</option>
          </select>
        </Field>
        <Field label="Name">
          <input aria-label="Mailbox name" value={label} placeholder="Info"
            onChange={(e) => setLabel(e.target.value)} />
        </Field>
        {kind === "client" && (
          <Field label="Client">
            <select aria-label="Client" value={company} onChange={(e) => setCompany(e.target.value)}>
              <option value="">Choose…</option>
              {(companies.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Provider">
          <select aria-label="Provider" value={provider}
            onChange={(e) => setProvider(e.target.value as "gmail" | "microsoft")}>
            <option value="gmail">Gmail</option>
            <option value="microsoft">Microsoft 365</option>
          </select>
        </Field>
      </div>
      <label className="choice">
        <input type="checkbox" checked={inbound} onChange={(e) => setInbound(e.target.checked)} />
        <span>Also collect replies</span>
      </label>
      {inbound && (
        <label className="choice">
          <input type="checkbox" checked={files} onChange={(e) => setFiles(e.target.checked)} />
          <span>File mail with contacts and companies (from the last 30 days on)</span>
        </label>
      )}
      <p className="muted small">
        You&apos;ll sign in as that mailbox, not as yourself; your own connection is not
        changed. Collecting replies asks for a read over the whole mailbox, as your own does.
      </p>
      <div className="row tight">
        <button className="primary" disabled={start.isPending || (kind === "client" && !company)}
          onClick={() => start.mutate()}>Sign in to the mailbox</button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/** "My default mailbox": what the practice alias would have been for mail I
 *  send. On Settings → Email, above who-your-mail-comes-from. */
export function DefaultMailbox() {
  const qc = useQueryClient();
  const list = useMailboxes();
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: (mailbox: string) => api.post<Mailboxes>("/api/mailboxes/default/", { mailbox }),
    onSuccess: (data) => { qc.setQueryData(["mailboxes"], data); setNote("Saved. New mail you send uses it."); },
    onError: (e: Error) => setNote(e.message),
  });
  const connected = (list.data?.mailboxes ?? []).filter((m) => m.connected);
  if (!list.data || connected.length < 2) return null;
  return (
    <Field label="My default mailbox">
      <select aria-label="My default mailbox" value={list.data.default ?? ""}
        onChange={(e) => save.mutate(e.target.value)}>
        <option value="">The practice alias, as set below</option>
        {connected.map((m) => <option key={m.id} value={m.id}>{m.sends_as} · {m.label || m.kind_label}</option>)}
      </select>
      <p className="muted small">
        Mail you send goes from it unless the mail is about a client whose company has its own
        mailbox, or you choose another From on the Outbox item. {note}
      </p>
    </Field>
  );
}

/** On a company's Mail tab: "mail about this client goes from this mailbox". */
export function CompanyMailFrom({ company }: { company: string }) {
  const qc = useQueryClient();
  const key = ["company-mail-from", company];
  const current = useQuery<{ mailbox: string | null; options: { value: string; mailbox: string; address: string; label: string }[] }>({
    queryKey: key,
    queryFn: () => api.get(`/api/mailboxes/company/?company=${company}`),
    retry: false,
  });
  const save = useMutation({
    mutationFn: (mailbox: string) => api.post("/api/mailboxes/company/", { company, mailbox }),
    onSuccess: (data) => qc.setQueryData(key, data),
  });
  if (!current.data || current.data.options.length < 2) return null;
  return (
    <Field label="Mail about this company goes from">
      <select aria-label="Mail about this company goes from" value={current.data.mailbox ?? ""}
        onChange={(e) => save.mutate(e.target.value)}>
        <option value="">Whoever sends it, by their own default</option>
        {current.data.options.map((o) => <option key={o.mailbox} value={o.mailbox}>{o.address} · {o.label}</option>)}
      </select>
    </Field>
  );
}

/** A contact's or company's Mail tab: every message in or out, across the
 *  practice's mailboxes, newest first, with reply in place through the
 *  mailbox its thread is in. Marketing mail is still written and approved in
 *  the Outbox. */
export function MailTab({ me, contact, company }: { me: Me; contact?: string; company?: string }) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const [replying, setReplying] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const query = contact ? `contact=${contact}` : `company=${company}`;
  const mail = useQuery<MailPage>({
    queryKey: ["mail", contact ?? company, page],
    queryFn: () => api.get<MailPage>(`/api/mail/?${query}&page=${page}`),
    retry: false,
  });
  const reply = useMutation({
    mutationFn: (m: MailItem) => api.post<{ state: string; detail: string }>("/api/mail/reply/",
      { message: m.id, body_text: body }),
    onSuccess: (data) => {
      setNote(data.detail); setProblem(""); setReplying(null); setBody("");
      qc.invalidateQueries({ queryKey: ["mail"] });
    },
    onError: (e: Error) => setProblem(e.message),
  });

  if (mail.isLoading) return <p className="muted">Loading…</p>;
  if (mail.isError) return <Banner kind="warn">{(mail.error as Error).message}</Banner>;
  const d = mail.data!;
  return (
    <Card title="Mail">
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {company && (me.role === "FF" || me.role === "CF") && <CompanyMailFrom company={company} />}
      {d.results.length === 0 ? (
        <Empty>No mail with {contact ? "this contact" : "this company"} yet, in any connected
          mailbox.</Empty>
      ) : (
        <ul className="mail-list">
          {d.results.map((m) => (
            <li key={m.id} className="mail-item">
              <button className="mail-head" aria-expanded={open === m.id}
                onClick={() => setOpen(open === m.id ? null : m.id)}>
                <span className={`mail-dir mail-${m.direction}`}>{m.direction === "inbound" ? "In" : "Out"}</span>
                <span className="mail-subject">{m.subject || "(no subject)"}</span>
                <span className="mail-meta muted small">
                  {m.direction === "inbound" ? `from ${m.from_address}` : `to ${m.to_addresses.join(", ")}`}
                  {" · "}{when(m.when)}
                  {m.mailbox && <> · {m.mailbox.label}</>}
                </span>
              </button>
              {open === m.id ? <div className="mail-body">{m.body}</div>
                : <div className="mail-snippet muted small">{m.snippet}</div>}
              {open === m.id && m.may_reply && (replying === m.id ? (
                <div className="mail-reply">
                  <label htmlFor={`reply-${m.id}`}>Reply from {m.reply_from}</label>
                  <textarea id={`reply-${m.id}`} rows={5} value={body}
                    onChange={(e) => setBody(e.target.value)} />
                  <div className="row tight">
                    <button className="primary" disabled={!body.trim() || reply.isPending}
                      onClick={() => reply.mutate(m)}>
                      {me.role === "VA" ? "Save as a draft for approval" : "Send reply"}</button>
                    <button className="ghost" onClick={() => setReplying(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <button className="ghost small" onClick={() => { setReplying(m.id); setBody(""); }}>
                  Reply</button>
              ))}
              {open === m.id && !m.may_reply && m.reply_refusal && (
                <p className="muted small">{m.reply_refusal}</p>)}
            </li>
          ))}
        </ul>
      )}
      {(d.previous || d.next) && (
        <div className="row tight">
          <button className="ghost" disabled={!d.previous} onClick={() => setPage(page - 1)}>Newer</button>
          <button className="ghost" disabled={!d.next} onClick={() => setPage(page + 1)}>Older</button>
        </div>
      )}
    </Card>
  );
}

/** The Overview / Mail switch over a contact's or company's page. */
export function RecordTabs({ tab, onTab }: { tab: "overview" | "mail"; onTab: (t: "overview" | "mail") => void }) {
  return (
    <div className="record-tabs" role="tablist" aria-label="Record">
      {(["overview", "mail"] as const).map((t) => (
        <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""}
          onClick={() => onTab(t)}>{t === "overview" ? "Overview" : "Mail"}</button>
      ))}
    </div>
  );
}
