import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BulkBar } from "../components/BulkBar";
import {
  Avatar, Chip, FilterBar, PageHead, SearchField, Sheet, SortHeader, Sort, sorted,
} from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { Contact, ContactType, Me, Note, Pipeline, api } from "../lib/api";
import { AddContact } from "./AddContact";
import { NoteRow } from "./Notes";

export function Contacts({ me }: { me: Me }) {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");
  const [sort, setSort] = useState<Sort>({ key: "name", asc: true });
  const [peek, setPeek] = useState<Contact | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState({ subject: "", body_text: "" });

  // Instant, not type-then-press-Search. Debounced so a five-letter name is
  // one request rather than five.
  useEffect(() => {
    const timer = setTimeout(() => setActive(term.trim()), 250);
    return () => clearTimeout(timer);
  }, [term]);

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

  const shown = sorted(rows, sort, (c) => ({
    name: `${c.last_name} ${c.first_name}`.trim(),
    title: c.title,
    stage: (c.pipeline_positions ?? [])[0]?.stage_label ?? "",
    email: emailOf(c, ""),
  }[sort.key] ?? ""));

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
      <PageHead title="Contacts"
        sub="Everyone the practice deals with. Search covers names, titles and background."
        action={!adding && (
          <button className="primary" onClick={() => { setAdding(true); setNote(""); }}>
            Add contact
          </button>
        )} />

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

      <div className="listbar">
        <SearchField label="Search contacts" value={term} onChange={setTerm}
          placeholder="Search contacts…" />
        <div className="addfilter">
          <select aria-label="Filter by type" value={typeFilter}
            onChange={(e) => { setTypeFilter(e.target.value); setPicked([]); }}>
            <option value="">Any type</option>
            {(contactTypes.data ?? []).map((t) => (
              <option key={t.code} value={t.code}>{t.label}</option>
            ))}
          </select>
          <select aria-label="Filter by pipeline stage" value={stageFilter}
            onChange={(e) => { setStageFilter(e.target.value); setPicked([]); }}>
            <option value="">Any stage</option>
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

      {/* Chips, not bare dropdowns: what is narrowing the list is stated, and
          clearing one is a click rather than a hunt through a menu. */}
      {(typeFilter || stageFilter || active) && (
        <FilterBar onClearAll={() => {
          setTypeFilter(""); setStageFilter(""); setTerm(""); setPicked([]);
        }}>
          {active && <Chip label={`Search: ${active}`}
            onClear={() => setTerm("")} />}
          {typeFilter && <Chip
            label={`Type: ${(contactTypes.data ?? []).find((t) => t.code === typeFilter)?.label ?? typeFilter}`}
            onClear={() => { setTypeFilter(""); setPicked([]); }} />}
          {stageFilter && <Chip label={`Stage: ${stageLabel(pipelines.data, stageFilter)}`}
            onClear={() => { setStageFilter(""); setPicked([]); }} />}
        </FilterBar>
      )}

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
          <table className="records">
            <thead>
              <tr>
                <th></th>
                <SortHeader label="Name" field="name" sort={sort} onSort={setSort} />
                <SortHeader label="Title" field="title" sort={sort} onSort={setSort} />
                <SortHeader label="Stage" field="stage" sort={sort} onSort={setSort} />
                <th>Types</th>
                <SortHeader label="Email" field="email" sort={sort} onSort={setSort} />
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id}>
                  <td>
                    <input type="checkbox" checked={picked.includes(c.id)}
                      aria-label={`Select ${c.first_name} ${c.last_name}`}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, c.id]
                        : picked.filter((x) => x !== c.id))} />
                  </td>
                  <td>
                    <span className="named">
                      <Avatar name={`${c.first_name} ${c.last_name}`} />
                      {/* The name opens the record; the row opens a peek. Two
                          different intentions, so two different targets. */}
                      <Link to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</Link>
                    </span>
                  </td>
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
                  <td className="mono">{emailOf(c)}</td>
                  <td className="rowactions">
                    <button className="small" onClick={() => setPeek(c)}
                      aria-label={`Peek at ${c.first_name} ${c.last_name}`}>
                      Peek
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {peek && (
        <Sheet label="Contact" onClose={() => setPeek(null)}
          title={<>
            <h3 style={{ margin: 0 }}>{peek.first_name} {peek.last_name}</h3>
            <p className="tiny muted" style={{ margin: 0 }}>{peek.title || "no title"}</p>
          </>}>
          {/* A look, not the record. Enough to decide whether to open it,
              and a way to open it. */}
          <dl className="facts">
            <dt>Email</dt><dd className="mono">{emailOf(peek)}</dd>
            <dt>Types</dt>
            <dd>{peek.type_codes.length
              ? peek.type_codes.map((t) => <Pill key={t}>{t.replace(/_/g, " ")}</Pill>)
              : "—"}</dd>
            <dt>Stage</dt>
            <dd>{(peek.pipeline_positions ?? []).length === 0 ? "—"
              : peek.pipeline_positions.map((p) => (
                <div key={p.pipeline}>{p.stage_label}
                  <span className="muted"> · {p.pipeline_name}</span></div>))}</dd>
            <dt>Source</dt><dd>{peek.source || "—"}</dd>
          </dl>
          {peek.background && <p style={{ whiteSpace: "pre-wrap" }}>{peek.background}</p>}
          <Link className="primary button" to={`/contacts/${peek.id}`}>
            Open the full record
          </Link>
        </Sheet>
      )}

      {/* FR-2.7 — one search box. A locked note matches on its title only. */}
      {active && (results.data?.notes ?? []).length > 0 && (
        <Card title="Notes matching this search">
          <ul className="timeline">{results.data!.notes.map((n) => <NoteRow key={n.id} note={n} />)}</ul>
        </Card>
      )}
    </>
  );
}


function emailOf(contact: Contact, fallback = "—") {
  return contact.emails.find((e) => e.is_primary)?.address
    ?? contact.emails[0]?.address ?? fallback;
}

function stageLabel(pipelines: Pipeline[] | undefined, id: string) {
  for (const pipeline of pipelines ?? []) {
    const found = pipeline.stages.find((stage) => stage.id === id);
    if (found) return found.label;
  }
  return id;
}
