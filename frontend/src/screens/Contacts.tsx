import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BulkBar } from "../components/BulkBar";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { Contact, ContactType, Me, Note, Pipeline, api } from "../lib/api";
import { AddContact } from "./AddContact";
import { NoteRow } from "./Notes";

export function Contacts({ me }: { me: Me }) {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState({ subject: "", body_text: "" });

  const list = useQuery<Contact[]>({
    queryKey: ["contacts"],
    queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  const contactTypes = useQuery<ContactType[]>({
    queryKey: ["contact-types"], queryFn: () => api.get<ContactType[]>("/api/contact-types/"),
  });
  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });

  const results = useQuery<{ contacts: Contact[]; companies: unknown[]; notes: Note[] }>({
    queryKey: ["search", active],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(active)}`),
    enabled: active.length > 0,
  });

  const qc = useQueryClient();
  const base = active ? results.data?.contacts ?? [] : list.data ?? [];
  // Filters narrow what "select all" means, which is the point: selecting
  // behind a filter you cannot see is how people mail the wrong list.
  const rows = base.filter((c) =>
    (!typeFilter || c.type_codes.includes(typeFilter))
    && (!stageFilter || (c.pipeline_positions ?? []).some((p) => p.stage === stageFilter)));

  const draftTouches = useMutation({
    mutationFn: () => api.post<{ drafted_count: number; skipped: { name: string; detail: string }[] }>(
      "/api/contacts/draft-touches/", { ids: picked },
    ),
    onSuccess: (r) => {
      setNote(`${r.drafted_count} touches drafted into the Outbox, pending approval.`
        + (r.skipped.length ? ` ${r.skipped.length} skipped.` : ""));
      setPicked([]);
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const draftEmails = useMutation({
    mutationFn: () => api.post<{ drafted_count: number; skipped: unknown[] }>(
      "/api/contacts/draft-emails/", { ids: picked, ...draft },
    ),
    onSuccess: (r) => {
      setNote(`${r.drafted_count} drafts created, one per recipient, all pending approval. Nothing was sent.`);
      setPicked([]); setComposing(false); setDraft({ subject: "", body_text: "" });
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <>
      <div className="spread">
        <h2>Contacts</h2>
        {!adding && (
          <button className="primary" onClick={() => { setAdding(true); setNote(""); }}>
            Add contact
          </button>
        )}
      </div>
      <p className="sub">Everyone the practice deals with. Search covers names, titles, and background.</p>

      {note && <Banner kind="ok">{note}</Banner>}

      {adding && (
        <AddContact
          me={me}
          onDone={(contact) => {
            setAdding(false);
            if (contact) {
              setNote(`Added ${contact.first_name} ${contact.last_name}.`);
              navigate(`/contacts/${contact.id}`);
            }
          }}
        />
      )}

      <Card>
        <form
          className="row"
          onSubmit={(e) => { e.preventDefault(); setActive(term.trim()); }}
        >
          <div style={{ flex: "3 1 320px" }}>
            <input
              placeholder="Search contacts…"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              aria-label="Search contacts"
            />
          </div>
          <div style={{ flex: "0 0 auto" }}>
            <button className="primary" type="submit">Search</button>{" "}
            {active && <button type="button" onClick={() => { setTerm(""); setActive(""); }}>Clear</button>}
          </div>
        </form>
      </Card>

      <Card title="Filter">
        <div className="row">
          <div>
            <label htmlFor="type-filter">Type</label>
            <select id="type-filter" value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setPicked([]); }}>
              <option value="">— any type —</option>
              {(contactTypes.data ?? []).map((t) => (
                <option key={t.code} value={t.code}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="stage-filter">Pipeline stage</label>
            <select id="stage-filter" value={stageFilter}
              onChange={(e) => { setStageFilter(e.target.value); setPicked([]); }}>
              <option value="">— any stage —</option>
              {(pipelines.data ?? []).map((p) => (
                <optgroup key={p.id} label={p.name}>
                  {p.stages.slice().sort((a, b) => a.position - b.position).map((st) => (
                    <option key={st.id} value={st.id}>{st.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {composing && (
        <Card title={`Draft an email to ${picked.length} contacts`}>
          <p className="muted small">
            One Outbox draft per recipient, each <strong>pending approval</strong>. Use{" "}
            <code>{"{first_name}"}</code> to address each person by name.
          </p>
          <label htmlFor="bulk-subject">Subject</label>
          <input id="bulk-subject" value={draft.subject}
            onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          <label htmlFor="bulk-body">Message</label>
          <textarea id="bulk-body" rows={6} value={draft.body_text}
            onChange={(e) => setDraft({ ...draft, body_text: e.target.value })} />
          <div style={{ marginTop: ".6rem" }}>
            <button className="primary" disabled={!draft.subject || draftEmails.isPending}
              onClick={() => draftEmails.mutate()}>
              Draft for {picked.length} recipients
            </button>{" "}
            <button onClick={() => setComposing(false)}>Cancel</button>
          </div>
        </Card>
      )}

      <Card title={active ? `Results for “${active}”` : "All contacts"}>
        {rows.length > 0 && (
          <BulkBar
            total={rows.length} selected={picked.length}
            onSelectAll={() => setPicked(rows.map((c) => c.id))}
            onClear={() => setPicked([])}
          >
            <button disabled={!picked.length || draftTouches.isPending}
              onClick={() => draftTouches.mutate()}>
              Draft touch now
            </button>{" "}
            <button className="primary" disabled={!picked.length}
              onClick={() => setComposing(true)}>
              Draft email
            </button>
          </BulkBar>
        )}
        {rows.length === 0 ? (
          <Empty>
            No contacts{active ? " match that search" : " yet — add one above, or import a CSV"}.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th></th><th>Name</th><th>Title</th><th>Stage</th><th>Types</th><th>Email</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <input type="checkbox" checked={picked.includes(c.id)}
                      aria-label={`Select ${c.first_name} ${c.last_name}`}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, c.id]
                        : picked.filter((x) => x !== c.id))} />
                  </td>
                  <td><Link to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</Link></td>
                  <td className="muted">{c.title || "—"}</td>
                  <td className="small">
                    {(c.pipeline_positions ?? []).length === 0 ? "—" : c.pipeline_positions.map((p) => (
                      <div key={p.pipeline}>
                        <Pill>{p.stage_label}</Pill>{" "}
                        <span className="muted">{p.pipeline_name}</span>
                      </div>
                    ))}
                  </td>
                  <td>{c.type_codes.map((t) => <Pill key={t}>{t.replace(/_/g, " ")}</Pill>)}</td>
                  <td className="mono">{c.emails.find((e) => e.is_primary)?.address ?? c.emails[0]?.address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {/* FR-2.7 — one search box. A locked note matches on its title only. */}
      {active && (results.data?.notes ?? []).length > 0 && (
        <Card title="Notes matching this search">
          <ul className="timeline">{results.data!.notes.map((n) => <NoteRow key={n.id} note={n} />)}</ul>
        </Card>
      )}
    </>
  );
}
