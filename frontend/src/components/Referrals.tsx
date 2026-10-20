import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill } from "./ui";
import { Contact, Referral, api } from "../lib/api";

/**
 * Inbound referrals (owner, 2026-10-20): who sent the practice a prospect.
 *
 * Any contact can be the referrer, with referral partners listed first; picking
 * someone else does not make them a partner.
 */

const fullName = (c: { first_name: string; last_name: string }) =>
  `${c.first_name} ${c.last_name}`.trim();

/** "2026-10-20" as a local date, not midnight UTC. */
export function day(value: string | null | undefined) {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString();
}

const isPartner = (c: Contact) => c.type_codes.includes("referral_partner");

/** Who matches what was typed: referral partners first, then by name. */
export function referrerChoices(contacts: Contact[], typed: string, excludeId?: string) {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  return contacts
    .filter((c) => c.id !== excludeId)
    .filter((c) => {
      const hay = `${fullName(c)} ${c.emails.map((e) => e.address).join(" ")}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .sort((a, b) => Number(isPartner(b)) - Number(isPartner(a))
      || fullName(a).localeCompare(fullName(b)));
}

export function ReferrerPicker({ value, onChange, excludeId, autoFocus }: {
  value: { id: string; name: string } | null;
  onChange: (picked: { id: string; name: string } | null) => void;
  excludeId?: string;
  autoFocus?: boolean;
}) {
  const listId = useId();
  const [typed, setTyped] = useState("");
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  if (value) {
    return (
      <div className="referrer-picked">
        <span>{value.name}</span>
        <button type="button" className="ghost" onClick={() => onChange(null)}
          aria-label="Choose someone else">Change</button>
      </div>
    );
  }
  const choices = typed.trim()
    ? referrerChoices(contacts.data ?? [], typed, excludeId).slice(0, 8)
    : [];
  return (
    <div className="referrer-picker">
      <input value={typed} autoFocus={autoFocus} aria-label="Referred by"
        aria-controls={listId} placeholder="Type a name or email"
        onChange={(e) => setTyped(e.target.value)} />
      {typed.trim() && (
        <ul id={listId} className="referrer-choices" role="listbox" aria-label="Contacts">
          {choices.length === 0 && <li className="muted small">No contact matches.</li>}
          {choices.map((c) => (
            <li key={c.id}>
              <button type="button" role="option" aria-selected={false}
                onClick={() => { setTyped(""); onChange({ id: c.id, name: fullName(c) }); }}>
                <span>{fullName(c)}</span>
                {isPartner(c) && <Pill>referral partner</Pill>}
                <span className="muted small">{c.emails[0]?.address ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The "Referred by" line on a prospect's Details card. */
export function ReferredByRow({ contact }: { contact: Contact }) {
  const qc = useQueryClient();
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState("");
  const current = contact.referred_by ?? null;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["contact", contact.id] });
    qc.invalidateQueries({ queryKey: ["referrals"] });
    qc.invalidateQueries({ queryKey: ["outbox"] });
    qc.invalidateQueries({ queryKey: ["timeline", contact.id] });
    qc.invalidateQueries({ queryKey: ["board"] });
  };
  const record = useMutation({
    mutationFn: (referrer: string) =>
      api.post("/api/referrals/", { prospect: contact.id, referrer }),
    onSuccess: () => { setChanging(false); setError(""); refresh(); },
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/referrals/${current!.id}/`),
    onSuccess: refresh,
  });

  return (
    <tr>
      <th>Referred by</th>
      <td>
        {changing ? (
          <>
            <ReferrerPicker value={null} excludeId={contact.id} autoFocus
              onChange={(picked) => picked && record.mutate(picked.id)} />
            <p className="muted small">
              {current
                ? `The credit moves from ${current.referrer_name}.`
                : "They join Sales at the first stage unless they are in it already."}{" "}
              A thank-you draft waits in the Outbox; nothing is sent.
            </p>
            <button type="button" className="ghost" onClick={() => setChanging(false)}>
              Cancel
            </button>
          </>
        ) : current ? (
          <div className="row-inline">
            <Link to={`/contacts/${current.referrer}`}>{current.referrer_name}</Link>
            <span className="muted small"> on {day(current.referred_on)}</span>
            <button type="button" className="ghost" onClick={() => setChanging(true)}>
              Change
            </button>
            <button type="button" className="ghost" disabled={remove.isPending}
              onClick={() => remove.mutate()}>Remove</button>
          </div>
        ) : (
          <button type="button" className="ghost" onClick={() => setChanging(true)}>
            Add who referred them
          </button>
        )}
        {error && <Banner kind="bad">{error}</Banner>}
      </td>
    </tr>
  );
}

function outcomePill(r: Referral) {
  if (r.outcome === "won") return <Pill kind="ok">Won {day(r.outcome_at)}</Pill>;
  if (r.outcome === "lost") return <Pill kind="bad">Lost {day(r.outcome_at)}</Pill>;
  if (r.stage?.semantic === "parked") return <Pill kind="warn">Parked</Pill>;
  return <Pill>Open</Pill>;
}

/** The referrer's list: everyone they sent, where each stands, how it ended. */
export function ReferralsCard({ contactId, partner }: { contactId: string; partner: boolean }) {
  const rows = useQuery<Referral[]>({
    queryKey: ["referrals", "by", contactId],
    queryFn: () => api.get<Referral[]>(`/api/referrals/?referrer=${contactId}`),
  });
  const list = rows.data ?? [];
  if (!partner && list.length === 0) return null;
  const won = list.filter((r) => r.outcome === "won").length;
  const lost = list.filter((r) => r.outcome === "lost").length;

  return (
    <Card title="Referrals">
      {list.length === 0 ? (
        <Empty>No one referred yet. Record it from the prospect's page, under Referred by.</Empty>
      ) : (
        <>
          <p className="muted small">
            {list.length} referred · {won} won · {lost} lost
          </p>
          <table className="referrals-table">
            <thead><tr><th>Prospect</th><th>Referred</th><th>Stage</th><th>Outcome</th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/contacts/${r.prospect.id}`}>{r.prospect.name}</Link>
                    {r.prospect.company && <div className="muted small">{r.prospect.company}</div>}
                  </td>
                  <td className="small">{day(r.referred_on)}</td>
                  <td>{r.stage ? <Pill>{r.stage.label}</Pill> : <span className="muted">—</span>}</td>
                  <td>{outcomePill(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}
