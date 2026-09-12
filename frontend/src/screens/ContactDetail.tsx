import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { GrantPortalAccess } from "../components/GrantPortalAccess";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { AddContact } from "./AddContact";
import { Contact, Me, OutboxMessage, api } from "../lib/api";

interface TimelineEntry { kind: string; when: string; text: string; note_id?: string; locked?: boolean; }
interface Duplicate { contact: Contact; match_reason: string; rank: number; }

export function ContactDetail({ me }: { me: Me }) {
  const { id } = useParams();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [lookingForDupes, setLookingForDupes] = useState(false);

  const contact = useQuery<Contact>({
    queryKey: ["contact", id], queryFn: () => api.get<Contact>(`/api/contacts/${id}/`),
  });
  const timeline = useQuery<TimelineEntry[]>({
    queryKey: ["timeline", id], queryFn: () => api.get<TimelineEntry[]>(`/api/contacts/${id}/timeline/`),
  });
  const outbox = useQuery<OutboxMessage[]>({
    queryKey: ["outbox"], queryFn: () => api.get<OutboxMessage[]>("/api/outbox/"),
  });
  const duplicates = useQuery<Duplicate[]>({
    queryKey: ["duplicates", id],
    queryFn: () => api.get<Duplicate[]>(`/api/contacts/${id}/duplicates/`),
    enabled: lookingForDupes,
  });

  const draftTouch = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/api/contacts/${id}/draft-touch/`),
    onSuccess: () => {
      setNote("Touch drafted into the Outbox, pending approval. Nothing was sent.");
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const addType = useMutation({
    mutationFn: (code: string) => api.post(`/api/contacts/${id}/add-type/`, { code }),
    onSuccess: (_d, code) => {
      qc.invalidateQueries({ queryKey: ["contact", id] });
      qc.invalidateQueries({ queryKey: ["timeline", id] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
      if (code === "referral_partner") {
        setNote(
          "Referral partner added. A post-meeting follow-up draft is waiting in the Outbox " +
          "with the marketing flyer attached — nothing has been sent."
        );
      }
    },
  });

  const save = useMutation({
    mutationFn: (patch: Partial<Contact>) => api.patch(`/api/contacts/${id}/`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["contact", id] }),
  });

  if (contact.isLoading) return <p>Loading…</p>;
  if (contact.isError) return <Banner kind="bad">That contact is not available to you.</Banner>;

  const c = contact.data!;
  const theirs = (outbox.data ?? []).filter((m) => m.to_contact === c.id);

  if (editing) {
    return (
      <AddContact
        me={me}
        existing={c}
        onDone={(updated) => {
          setEditing(false);
          if (updated) {
            setNote("Contact updated.");
            qc.invalidateQueries({ queryKey: ["contact", id] });
            qc.invalidateQueries({ queryKey: ["contacts"] });
          }
        }}
      />
    );
  }

  return (
    <>
      <div className="spread">
        <h2>{c.first_name} {c.last_name}</h2>
        <button onClick={() => setEditing(true)}>Edit contact</button>
      </div>
      <p className="sub">
        {c.title || "No title"}
        {c.type_codes.map((t) => <span key={t}> · <Pill>{t.replace(/_/g, " ")}</Pill></span>)}
      </p>

      {params.get("merged") === "1" && (
        <Banner kind="ok">
          Merged. Everything from the other record — notes, tasks, emails, stage history,
          types, categories — now appears on this contact's timeline below.
        </Banner>
      )}
      {note && <Banner kind="ok">{note}</Banner>}

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "1.15rem" }}>
        <div>
          <Card title="Pipelines">
            <p className="muted small">
              A contact holds an independent position in each pipeline they belong to.
              Being a referral partner and a live prospect at the same time is normal.
            </p>
            {(c.pipeline_positions ?? []).length === 0 ? (
              <Empty>Not in any pipeline. Add them from the Pipeline board.</Empty>
            ) : (
              <table>
                <thead><tr><th>Pipeline</th><th>Stage</th><th>Since</th></tr></thead>
                <tbody>
                  {(c.pipeline_positions ?? []).map((p) => (
                    <tr key={p.pipeline}>
                      <td>{p.pipeline_name}</td>
                      <td>
                        <Pill kind={p.semantic === "won" ? "ok"
                          : p.semantic === "lost" ? "bad"
                          : p.semantic === "parked" ? "warn" : ""}>
                          {p.stage_label}
                        </Pill>
                      </td>
                      <td className="muted small">{when(p.entered_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Details">
            <table>
              <tbody>
                <tr><th>Email</th><td className="mono">
                  {c.emails.map((e) => <div key={e.id}>{e.address}{e.is_primary && " (primary)"}</div>)}
                  {c.emails.length === 0 && "—"}
                </td></tr>
                <tr><th>Phone</th><td className="mono">
                  {c.phones.map((p) => <div key={p.id}>{p.number}</div>)}
                  {c.phones.length === 0 && "—"}
                </td></tr>
                <tr><th>Company</th><td>
                  {c.company ? <Link to={`/companies/${c.company}`}>Open company →</Link> : "—"}
                </td></tr>
                <tr><th>Source</th><td className="muted">{c.source || "—"}</td></tr>
                <tr><th>Tags</th><td>{c.tags.length ? c.tags.map((t) => <Pill key={t}>{t}</Pill>) : "—"}</td></tr>
              </tbody>
            </table>
          </Card>

          <Card
            title="Possible duplicates"
            actions={
              <button onClick={() => setLookingForDupes(true)} disabled={lookingForDupes}>
                {lookingForDupes ? "Searching…" : "Find duplicates"}
              </button>
            }
          >
            {!lookingForDupes ? (
              <p className="muted small" style={{ marginBottom: 0 }}>
                Looks for contacts sharing an email address, or the same name at the same
                company. Nothing is merged without you choosing.
              </p>
            ) : (duplicates.data ?? []).length === 0 ? (
              <Empty>No likely duplicates of this contact.</Empty>
            ) : (
              <table>
                <thead><tr><th>Contact</th><th>Why it matched</th><th></th></tr></thead>
                <tbody>
                  {duplicates.data!.map((d) => (
                    <tr key={d.contact.id}>
                      <td>
                        <Link to={`/contacts/${d.contact.id}`}>
                          {d.contact.first_name} {d.contact.last_name}
                        </Link>
                        <div className="muted mono small">
                          {d.contact.emails[0]?.address ?? "no email"}
                        </div>
                      </td>
                      <td><Pill>{d.match_reason}</Pill></td>
                      <td className="right">
                        <Link className="btn" to={`/merge/${c.id}/${d.contact.id}`}>
                          Merge…
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Background">
            <p className="muted small">
              A short “who this is / how we met”. Longer material belongs in notes.
            </p>
            <textarea
              rows={3}
              defaultValue={c.background}
              onBlur={(e) => save.mutate({ background: e.target.value })}
            />
          </Card>

          <Card title="Referral partner settings">
            {!c.type_codes.includes("referral_partner") ? (
              <>
                <p className="muted small">Not a referral partner.</p>
                <button onClick={() => addType.mutate("referral_partner")}>
                  Make a referral partner
                </button>
                <p className="muted small" style={{ marginTop: ".6rem", marginBottom: 0 }}>
                  This immediately queues a post-meeting follow-up draft in the Outbox.
                  It does not send.
                </p>
              </>
            ) : (
              <>
                <div className="row">
                  <Field label="Cadence">
                    <select
                      defaultValue={c.referral_cadence || "monthly"}
                      onChange={(e) => save.mutate({ referral_cadence: e.target.value })}
                    >
                      <option value="monthly">Monthly</option>
                      <option value="bimonthly">Bi-monthly</option>
                      <option value="quarterly">Quarterly</option>
                    </select>
                  </Field>
                  <Field label="Touch mode">
                    <select
                      defaultValue={c.referral_touch_mode}
                      onChange={(e) => save.mutate({ referral_touch_mode: e.target.value })}
                    >
                      <option value="ai">AI-drafted</option>
                      <option value="template">My template</option>
                    </select>
                  </Field>
                </div>
                <Field label="Fee terms (optional — omitted from the email when blank)">
                  <input
                    defaultValue={c.referral_fee_terms}
                    placeholder="10% of first 3 months"
                    onBlur={(e) => save.mutate({ referral_fee_terms: e.target.value })}
                  />
                </Field>
                <p className="muted small">
                  Onboarded {when(c.referral_onboarded_at)} · next touch {when(c.referral_next_touch_at)}
                </p>
                <button className="primary" disabled={draftTouch.isPending}
                  onClick={() => draftTouch.mutate()}>
                  {draftTouch.isPending ? "Drafting…" : "Draft touch now"}
                </button>
                <p className="muted small" style={{ marginTop: ".5rem", marginBottom: 0 }}>
                  Drafts this partner's touch into the Outbox for approval, using the same
                  composer the scheduled job uses. It does not send, and it does not move
                  their next touch date — an extra touch now is not a replacement for the
                  one already due.
                </p>
              </>
            )}
          </Card>
        </div>

        <div>
          <GrantPortalAccess me={me} contactId={id!} />

          <Card title="Timeline">
            {(timeline.data ?? []).length === 0 ? (
              <Empty>Nothing yet.</Empty>
            ) : (
              <ul className="timeline">
                {timeline.data!.map((entry, i) => (
                  <li key={i}>
                    <div>{entry.note_id
                      ? <Link to={`/notes/${entry.note_id}`}>{entry.locked && "🔒 "}{entry.text}</Link>
                      : entry.text}</div>
                    <div className="when">{entry.kind} · {when(entry.when)}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Email for this contact">
            {theirs.length === 0 ? <Empty>No messages.</Empty> : (
              <ul className="timeline">
                {theirs.map((m) => (
                  <li key={m.id}>
                    <div>{m.subject}</div>
                    <div className="when">
                      <Pill kind={m.state === "sent" ? "ok" : m.state === "expired" ? "bad" : "warn"}>
                        {m.state.replace(/_/g, " ")}
                      </Pill>{" "}
                      {m.producer.replace(/_/g, " ")} · {when(m.sent_at || m.created_at)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <Link className="small" to="/outbox">Open the Outbox →</Link>
          </Card>
        </div>
      </div>
    </>
  );
}
