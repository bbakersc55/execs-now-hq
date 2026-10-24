import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { ReferrerPicker, day } from "./Referrals";
import { Banner, Card, Empty, Pill } from "./ui";
import { Contact, Introduction, api } from "../lib/api";

export const DISCIPLINES: Record<string, string> = {
  cmo: "Fractional CMO", cfo: "Fractional CFO", coo: "Fractional COO",
  chro: "Fractional CHRO", other: "Other",
};
const OUTCOMES: Record<string, string> = {
  "": "Not set", no_reply: "No reply", met: "Met", client: "Became a client", not_fit: "Not a fit",
};

/**
 * R3b: what a referral partner does, a general discipline and several
 * specialties in the practice's own words, suggested from the ones already
 * used. Searchable from Contacts.
 */
export function WhatTheyDo({ contact }: { contact: Contact }) {
  const qc = useQueryClient();
  const listId = useId();
  const [editing, setEditing] = useState(false);
  const [discipline, setDiscipline] = useState(contact.discipline ?? "");
  const [chips, setChips] = useState<string[]>(contact.specialties ?? []);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const used = useQuery<{ specialty: string; contacts: number }[]>({
    queryKey: ["specialties"], queryFn: () => api.get("/api/contacts/specialties/"), enabled: editing,
  });
  const save = useMutation({
    mutationFn: () => api.patch(`/api/contacts/${contact.id}/`, {
      discipline, specialties: typed.trim() ? [...chips, typed.trim()] : chips }),
    onSuccess: () => {
      setEditing(false); setTyped(""); setError("");
      qc.invalidateQueries({ queryKey: ["contact", contact.id] });
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["specialties"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const add = () => {
    const text = typed.trim().replace(/\s+/g, " ");
    if (text && !chips.some((c) => c.toLowerCase() === text.toLowerCase())) setChips([...chips, text]);
    setTyped("");
  };
  return (
    <Card title="What they do" actions={!editing && (
      <button className="ghost small" onClick={() => {
        setDiscipline(contact.discipline ?? ""); setChips(contact.specialties ?? []); setEditing(true); }}>
        Change</button>)}>
      {!editing ? (
        <>
          <p style={{ marginTop: 0 }}>{contact.discipline_label || <span className="muted">No discipline set.</span>}</p>
          {(contact.specialties ?? []).length > 0 ? (
            <div className="chips">{contact.specialties!.map((s) => <Pill key={s}>{s}</Pill>)}</div>
          ) : <p className="small muted">No specialties yet. Add the phrases they use for their work.</p>}
        </>
      ) : (
        <div className="what-they-do-form">
          {error && <Banner kind="bad">{error}</Banner>}
          <label className="small" htmlFor={`${listId}-d`}>Discipline</label>
          <select id={`${listId}-d`} value={discipline} onChange={(e) => setDiscipline(e.target.value as typeof discipline)}>
            <option value="">Not set</option>
            {Object.entries(DISCIPLINES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="small" htmlFor={`${listId}-s`}>Specialties</label>
          <div className="chips">
            {chips.map((c) => (
              <span key={c} className="pill chip">{c}
                <button type="button" className="chip-x" aria-label={`Remove ${c}`}
                  onClick={() => setChips(chips.filter((x) => x !== c))}>×</button></span>
            ))}
          </div>
          <div className="row">
            <input id={`${listId}-s`} list={`${listId}-used`} value={typed} placeholder="Go to market"
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} />
            <button type="button" className="ghost small" style={{ flex: "0 0 auto" }} onClick={add}>Add</button>
          </div>
          <datalist id={`${listId}-used`}>
            {(used.data ?? []).filter((u) => !chips.includes(u.specialty)).map((u) =>
              <option key={u.specialty} value={u.specialty} />)}
          </datalist>
          <div className="row">
            <button className="primary small" style={{ flex: "0 0 auto" }} disabled={save.isPending}
              onClick={() => save.mutate()}>Save</button>
            <button className="ghost small" style={{ flex: "0 0 auto" }} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}
    </Card>
  );
}

/**
 * R3: introductions the practice made. On a partner's page, "Introduce to…"
 * records one and drafts it to both people for approval; on either person's
 * page it is listed with the outcome the practice sets, and a partner's page
 * counts them.
 */
export function IntroductionsCard({ contact, partner }: { contact: Contact; partner: boolean }) {
  const qc = useQueryClient();
  const [making, setMaking] = useState(false);
  const [to, setTo] = useState<{ id: string; name: string } | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);
  const rows = useQuery<{ introductions: Introduction[]; counts: { made: number; became_client: number };
    counts_text: string }>({
    queryKey: ["introductions", contact.id],
    queryFn: () => api.get(`/api/introductions/?contact=${contact.id}`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["introductions"] });
    qc.invalidateQueries({ queryKey: ["outbox"] });
  };
  const make = useMutation({
    mutationFn: () => api.post("/api/introductions/", { partner: contact.id, to: to!.id, note }),
    onSuccess: () => {
      setMessage({ kind: "ok", text: `Introduction recorded. A draft to each of ${contact.first_name} and ${to!.name} is waiting in the Outbox for approval.` });
      setMaking(false); setTo(null); setNote(""); refresh();
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });
  const outcome = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => api.patch(`/api/introductions/${id}/`, { outcome: value }),
    onSuccess: refresh,
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });
  const list = rows.data?.introductions ?? [];
  if (!partner && list.length === 0) return null;
  return (
    <Card title="Introductions" actions={partner && !making && (
      <button className="small" onClick={() => { setMaking(true); setMessage(null); }}>Introduce to…</button>)}>
      {partner && rows.data && <p className="muted small" style={{ marginTop: 0 }}>{rows.data.counts_text}</p>}
      {message && <div role={message.kind === "ok" ? "status" : "alert"}><Banner kind={message.kind}>{message.text}</Banner></div>}
      {making && (
        <div className="intro-form" role="group" aria-label={`Introduce ${contact.first_name} to someone`}>
          <ReferrerPicker value={to} onChange={setTo} excludeId={contact.id} autoFocus label="Introduce to" />
          <textarea aria-label="Why you're introducing them" rows={2} value={note}
            placeholder="Why the two should talk (it goes in both emails)" onChange={(e) => setNote(e.target.value)} />
          <div className="row">
            <button className="primary small" style={{ flex: "0 0 auto" }} disabled={!to || make.isPending}
              onClick={() => make.mutate()}>Draft the introduction</button>
            <button className="ghost small" style={{ flex: "0 0 auto" }} onClick={() => { setMaking(false); setTo(null); }}>Cancel</button>
          </div>
        </div>
      )}
      {list.length === 0 ? (
        <Empty>No introductions yet.</Empty>
      ) : (
        <ul className="intro-list">
          {list.map((r) => {
            const other = r.partner.id === contact.id ? r.to : r.partner;
            return (
              <li key={r.id}>
                <div>
                  {r.partner.id === contact.id ? "Introduced to " : "Introduced by us to "}
                  <Link to={`/contacts/${other.id}`}>{other.name}</Link>
                  {other.company && <span className="muted small"> · {other.company}</span>}
                  <div className="small muted">{day(r.on)}{r.made_by ? ` · by ${r.made_by}` : ""}
                    {r.draft_state === "pending_approval" ? " · drafts waiting in the Outbox" : ""}</div>
                  {r.note && <div className="small">{r.note}</div>}
                </div>
                <select aria-label={`How the introduction to ${other.name} went`} value={r.outcome}
                  disabled={outcome.isPending} onChange={(e) => outcome.mutate({ id: r.id, value: e.target.value })}>
                  {Object.entries(OUTCOMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
