import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BulkBar } from "../components/BulkBar";
import { DISCIPLINES } from "../components/Introductions";
import {
  Avatar, Chip, FilterBar, PageHead, SearchField, Sheet, SortHeader, Sort, sorted,
  useRowLink,
} from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { RichText } from "../components/RichText";
import {
  Contact, ContactType, EmailTemplate, Me, Note, Pipeline, TEMPLATE_FIELDS, api,
} from "../lib/api";
import { MergeFieldBar } from "./EmailTemplates";
import { AddContact } from "./AddContact";
import { NoteRow } from "./Notes";

export function Contacts({ me }: { me: Me }) {
  const navigate = useNavigate();
  const rowLink = useRowLink();
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");
  const [sort, setSort] = useState<Sort>({ key: "name", asc: true });
  const [peek, setPeek] = useState<Contact | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  // R3b: a partner found by what they do.
  const [disciplineFilter, setDisciplineFilter] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("");
  const specialties = useQuery<{ specialty: string; contacts: number }[]>({
    queryKey: ["specialties"], queryFn: () => api.get("/api/contacts/specialties/"),
  });
  const [composing, setComposing] = useState(false);
  // `template` is the one copied from, if any: its first-name fallback applies.
  const [draft, setDraft] = useState<{ subject: string; body_text: string; template?: string }>(
    { subject: "", body_text: "" });
  const templates = useQuery<EmailTemplate[]>({
    queryKey: ["templates"], queryFn: () => api.get<EmailTemplate[]>("/api/email-templates/"),
    enabled: composing,
  });

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
    && (!stageFilter || (c.pipeline_positions ?? []).some((p) => p.stage === stageFilter))
    && (!disciplineFilter || c.discipline === disciplineFilter)
    && (!specialtyFilter || (c.specialties ?? []).some((s) => s.toLowerCase() === specialtyFilter.toLowerCase())));

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
        sub="Everyone the practice deals with. Search covers names, titles, background, and what partners do."
        action={!adding && (
          <span className="row tight">
            {/* Merge is FF and VA (matrix 4.5), so the way in is too. */}
            {(me.role === "FF" || me.role === "VA") && (
              <Link className="button" to="/contacts/duplicates">Merge duplicates</Link>
            )}
            {/* The contacts import is FF and VA too; U2's Import door lists it as well. */}
            {(me.role === "FF" || me.role === "VA") && (
              <Link className="button" to="/import/contacts">Import</Link>
            )}
            <button className="primary" onClick={() => { setAdding(true); setNote(""); }}>
              Add contact
            </button>
          </span>
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
          <select aria-label="Filter by discipline" value={disciplineFilter}
            onChange={(e) => { setDisciplineFilter(e.target.value); setPicked([]); }}>
            <option value="">Any discipline</option>
            {Object.entries(DISCIPLINES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {(specialties.data ?? []).length > 0 && (
            <select aria-label="Filter by specialty" value={specialtyFilter}
              onChange={(e) => { setSpecialtyFilter(e.target.value); setPicked([]); }}>
              <option value="">Any specialty</option>
              {specialties.data!.map((s) => <option key={s.specialty} value={s.specialty}>{s.specialty} ({s.contacts})</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Chips, not bare dropdowns: what is narrowing the list is stated, and
          clearing one is a click rather than a hunt through a menu. */}
      {(typeFilter || stageFilter || disciplineFilter || specialtyFilter || active) && (
        <FilterBar onClearAll={() => {
          setTypeFilter(""); setStageFilter(""); setDisciplineFilter(""); setSpecialtyFilter("");
          setTerm(""); setPicked([]);
        }}>
          {active && <Chip label={`Search: ${active}`}
            onClear={() => setTerm("")} />}
          {typeFilter && <Chip
            label={`Type: ${(contactTypes.data ?? []).find((t) => t.code === typeFilter)?.label ?? typeFilter}`}
            onClear={() => { setTypeFilter(""); setPicked([]); }} />}
          {stageFilter && <Chip label={`Stage: ${stageLabel(pipelines.data, stageFilter)}`}
            onClear={() => { setStageFilter(""); setPicked([]); }} />}
          {disciplineFilter && <Chip label={`Discipline: ${DISCIPLINES[disciplineFilter]}`}
            onClear={() => { setDisciplineFilter(""); setPicked([]); }} />}
          {specialtyFilter && <Chip label={`Specialty: ${specialtyFilter}`}
            onClear={() => { setSpecialtyFilter(""); setPicked([]); }} />}
        </FilterBar>
      )}

      {composing && (
        <Card title={`Draft an email to ${picked.length} contacts`}>
          <p className="muted small">
            One Outbox draft per recipient, each <strong>pending approval</strong>, filled in
            for each person and signed by you.
          </p>
          <Field label="Start from a template">
            <select aria-label="Start from a template" value=""
              onChange={(e) => {
                const t = (templates.data ?? []).find((row) => row.id === e.target.value);
                if (t) setDraft({ subject: t.subject, body_text: t.body, template: t.id });
              }}>
              <option value="">Choose one to copy its subject and words…</option>
              {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <label htmlFor="bulk-subject">Subject</label>
          <input id="bulk-subject" value={draft.subject}
            onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          <MergeFieldBar fields={TEMPLATE_FIELDS} oneEmail />
          <RichText plain label="Message" value={draft.body_text}
            onChange={(text) => setDraft({ ...draft, body_text: text })} />
          <DraftPreview ids={picked} subject={draft.subject} body={draft.body_text} />
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
          <table className="records cards-on-phone">
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
                <tr key={c.id} {...rowLink(`/contacts/${c.id}`)}>
                  <td className="card-pick">
                    <input type="checkbox" checked={picked.includes(c.id)}
                      aria-label={`Select ${c.first_name} ${c.last_name}`}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, c.id]
                        : picked.filter((x) => x !== c.id))} />
                  </td>
                  <td className="card-title">
                    <span className="named">
                      <Avatar name={`${c.first_name} ${c.last_name}`} />
                      {/* The row opens the record and so does the name, which
                          is the link a keyboard reaches. Peek stays its own
                          button. */}
                      <Link className="rowname" to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</Link>
                    </span>
                  </td>
                  <td data-label="Title" className="muted">{c.title || "—"}</td>
                  <td data-label="Stage" className="small">
                    {(c.pipeline_positions ?? []).length === 0 ? "—" : c.pipeline_positions.map((p) => (
                      <div key={p.pipeline}>
                        <Pill>{p.stage_label}</Pill>{" "}
                        <span className="muted">{p.pipeline_name}</span>
                      </div>
                    ))}
                  </td>
                  <td data-label="Types">{c.type_codes.map((t) => <Pill key={t}>{t.replace(/_/g, " ")}</Pill>)}</td>
                  <td data-label="Email" className="mono">{emailOf(c)}</td>
                  <td className="rowactions card-actions">
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


interface DraftPreviewData {
  to: string; subject: string; body: string;
  empty: { field: string; label: string; why: string; people: number; of: number }[];
}

/** The email as the first person picked would get it, and every field that
 *  has nothing in it, by name (finding T5): never a surprise blank. */
function DraftPreview({ ids, subject, body }: { ids: string[]; subject: string; body: string }) {
  const [asked, setAsked] = useState({ subject, body });
  useEffect(() => {
    const timer = setTimeout(() => setAsked({ subject, body }), 400);
    return () => clearTimeout(timer);
  }, [subject, body]);
  const preview = useQuery<DraftPreviewData>({
    queryKey: ["draft-preview", ids, asked],
    queryFn: () => api.post<DraftPreviewData>("/api/contacts/draft-emails/preview/",
      { ids, subject: asked.subject, body_text: asked.body }),
    enabled: ids.length > 0 && !!(asked.subject.trim() || asked.body.trim()),
  });
  if (preview.isError) return <Banner kind="bad">{(preview.error as Error).message}</Banner>;
  const p = preview.data;
  if (!p) return null;
  return (
    <div className="card" aria-label="Preview" style={{ marginTop: ".6rem" }}>
      <p className="small muted" style={{ marginTop: 0 }}>Preview for {p.to}, before your
        signature</p>
      <p className="small" style={{ margin: 0 }}>Subject <strong>{p.subject}</strong></p>
      <p className="small" style={{ whiteSpace: "pre-line" }}>{p.body}</p>
      {p.empty.map((e) => (
        <div key={e.field} role="note">
          <Banner kind="warn">{`{${e.field}}`} has nothing
            {e.of > 1 ? ` for ${e.people} of ${e.of} people` : ""}
            {e.why ? ` (${e.why})` : ""}, so it reads as blank.</Banner>
        </div>
      ))}
    </div>
  );
}
