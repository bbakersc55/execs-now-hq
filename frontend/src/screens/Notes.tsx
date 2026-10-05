import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";

import { Chip, FilterBar, PageHead, SearchField } from "../components/shell";
import { Banner, Card, Empty, Field, when } from "../components/ui";
import { Me, Note, NotesSettings, api } from "../lib/api";
import { LinkChips, NoteDetail } from "./NoteDetail";

export function NoteRow({ note }: { note: Note }) {
  return (
    <li>
      <Link to={`/notes/${note.id}`}>{note.is_locked && "🔒 "}{note.title}</Link>{" "}
      <span className="muted small">{when(note.created_at)}</span>
      <br />
      <LinkChips note={note} />
    </li>
  );
}

interface NoteCard { id: string; title: string; is_locked: boolean; created_at: string }
interface Option { id: string; name: string }
interface Grid { total: number; results: NoteCard[]; companies: Option[]; contacts: Option[] }

/** The grid opens with this many, and "Show older" adds this many. */
const PAGE = 20;
/** A search or a filter shows every match, this many at a time. */
const MATCH_PAGE = 200;

const RANGES: Record<string, string> = {
  today: "Today", "7": "Last 7 days", "30": "Last 30 days", custom: "Custom…",
};

/** A local calendar day, as the instant it starts. */
function dayStart(text: string, plusDays = 0) {
  const day = text ? new Date(`${text}T00:00:00`) : new Date();
  if (Number.isNaN(day.getTime())) return undefined;
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + plusDays);
}

/** The date filter as the two instants the server compares against. */
function bounds(range: string, from: string, to: string) {
  if (range === "today") return { after: dayStart("") };
  if (range === "7" || range === "30") return { after: dayStart("", -Number(range)) };
  if (range === "custom") {
    return { after: from ? dayStart(from) : undefined, before: to ? dayStart(to, 1) : undefined };
  }
  return {};
}

function day(value: string) {
  return new Date(value).toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
}

/**
 * Notes (UI spec §9): **a grid of cards, and a note opens as the page.**
 *
 * This replaces the list-beside-note panel. The owner's complaint was that an
 * entry did not read as a note until it was hovered; a card does. Each note is
 * still its own URL.
 */
export function Notes({ me }: { me: Me }) {
  const { id } = useParams();
  return (
    <>
      {id ? <NoteDetail me={me} /> : <NotesGrid />}
      {me.role === "FF" && <RecordingSettings />}
    </>
  );
}

function NotesGrid() {
  // Search and filters live in the address, so "Back to notes" and the
  // browser's Back both return to exactly this grid.
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const get = (key: string) => params.get(key) ?? "";
  const set = (changes: Record<string, string>) => {
    // From the address as it is now, not as it was when this was set up: a
    // filter chosen while a typed search is still settling must not be lost.
    setParams((now) => {
      const next = new URLSearchParams(now);
      // Narrowing differently starts the count of shown notes again.
      if (!("show" in changes)) next.delete("show");
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value); else next.delete(key);
      }
      return next;
    }, { replace: true });
  };

  const q = get("q");
  const [term, setTerm] = useState(q);
  const [nameTerm, setNameTerm] = useState(get("name"));
  useEffect(() => {
    const timer = setTimeout(() => {
      const changes: Record<string, string> = {};
      if (term.trim() !== q) changes.q = term.trim();
      if (nameTerm.trim() !== get("name")) changes.name = nameTerm.trim();
      if (Object.keys(changes).length) set(changes);
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term, nameTerm]);

  const company = get("company");
  const contact = get("contact");
  const name = get("name");
  const range = get("date");
  const { after, before } = bounds(range, get("from"), get("to"));
  const narrowed = !!(q || company || contact || name || after || before);
  const step = narrowed ? MATCH_PAGE : PAGE;
  const limit = Number(get("show")) || step;

  const request = new URLSearchParams();
  if (q) request.set("q", q);
  if (company) request.set("company", company);
  if (contact) request.set("contact", contact);
  if (name) request.set("name", name);
  if (after) request.set("after", after.toISOString());
  if (before) request.set("before", before.toISOString());
  request.set("limit", String(limit));

  const grid = useQuery<Grid>({
    queryKey: ["notes", "browse", request.toString()],
    queryFn: () => api.get<Grid>(`/api/notes/browse/?${request}`),
    placeholderData: keepPreviousData,
  });
  const cards = grid.data?.results ?? [];
  const total = grid.data?.total ?? 0;
  const companies = grid.data?.companies ?? [];
  const contacts = grid.data?.contacts ?? [];
  const label = (options: Option[], value: string) =>
    options.find((o) => o.id === value)?.name ?? "…";

  const clearAll = () => {
    setTerm(""); setNameTerm("");
    setParams(new URLSearchParams(), { replace: true });
  };

  return (
    <>
      <PageHead title="Notes"
        sub={<>Press <span className="mono">n</span> anywhere to write one. Search
          covers titles, text and accepted summaries; a locked note is found by
          its title only.</>} />

      <div className="listbar">
        <SearchField label="Search notes" value={term} onChange={setTerm}
          placeholder="Search notes…" />
        <div className="addfilter">
          <select aria-label="Filter by company" value={company}
            onChange={(e) => set({ company: e.target.value })}>
            <option value="">Any company</option>
            {companies.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <select aria-label="Filter by contact" value={contact}
            onChange={(e) => set({ contact: e.target.value })}>
            <option value="">Any contact</option>
            {contacts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <select aria-label="Filter by date" value={range}
            onChange={(e) => set({ date: e.target.value, from: "", to: "" })}>
            <option value="">Any date</option>
            {Object.entries(RANGES).map(([value, text]) => (
              <option key={value} value={value}>{text}</option>
            ))}
          </select>
          <input aria-label="Filter by name" placeholder="Name contains…" value={nameTerm}
            onChange={(e) => setNameTerm(e.target.value)} />
        </div>
      </div>

      {range === "custom" && (
        <div className="listbar">
          <label className="inline small">From
            <input type="date" aria-label="From date" value={get("from")}
              onChange={(e) => set({ from: e.target.value })} />
          </label>
          <label className="inline small">To
            <input type="date" aria-label="To date" value={get("to")}
              onChange={(e) => set({ to: e.target.value })} />
          </label>
        </div>
      )}

      {narrowed && (
        <FilterBar onClearAll={clearAll}>
          {q && <Chip label={`Search: ${q}`} onClear={() => setTerm("")} />}
          {company && <Chip label={`Company: ${label(companies, company)}`}
            onClear={() => set({ company: "" })} />}
          {contact && <Chip label={`Contact: ${label(contacts, contact)}`}
            onClear={() => set({ contact: "" })} />}
          {(after || before) && <Chip
            label={`Date: ${range === "custom"
              ? [get("from") && `from ${get("from")}`, get("to") && `to ${get("to")}`]
                .filter(Boolean).join(" ")
              : RANGES[range]}`}
            onClear={() => set({ date: "", from: "", to: "" })} />}
          {name && <Chip label={`Name: ${name}`} onClear={() => setNameTerm("")} />}
        </FilterBar>
      )}
      {(company || contact) && (
        <p className="small muted">
          Locked notes are left out of the company and contact filters.
        </p>
      )}

      {grid.isError && (
        <Banner kind="bad">Notes could not be loaded. Reload the page to try again.</Banner>
      )}

      {grid.isLoading ? <p className="muted">Loading…</p> : cards.length === 0 ? (
        <Empty>{narrowed ? "No notes match." : "No notes yet."}</Empty>
      ) : (
        <>
          <p className="small muted">
            {narrowed
              ? `${total} note${total === 1 ? "" : "s"} match${total === 1 ? "es" : ""}`
              : total > cards.length ? `Latest ${cards.length} of ${total} notes`
                : `${total} note${total === 1 ? "" : "s"}`}
          </p>
          <ul className="note-grid">
            {cards.map((note) => (
              <li key={note.id}>
                <Link className="note-card" to={`/notes/${note.id}`}
                  state={{ notesFrom: location.search }}>
                  <span className="title">{note.title}</span>
                  <span className="meta">
                    {note.is_locked && <Lock size={14} aria-label="Locked" />}
                    {day(note.created_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {total > cards.length && (
            <p>
              <button type="button" disabled={grid.isFetching}
                onClick={() => set({ show: String(limit + step) })}>
                {narrowed ? "Show more" : "Show older"}
              </button>
            </p>
          )}
        </>
      )}
    </>
  );
}

function RecordingSettings() {
  const qc = useQueryClient();
  const settings = useQuery<NotesSettings>({
    queryKey: ["notes-settings"], queryFn: () => api.get<NotesSettings>("/api/notes/settings/"),
  });
  const [days, setDays] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.patch<NotesSettings>("/api/notes/settings/", { audio_retention_days: Number(days) }),
    onSuccess: () => { setDays(null); qc.invalidateQueries({ queryKey: ["notes-settings"] }); },
  });
  const value = days ?? String(settings.data?.audio_retention_days ?? "");

  return (
    <Card title="Recording audio retention">
      <p className="small">
        Transcripts and summaries are kept indefinitely. The audio itself is deleted this many
        days after recording — but only once it has been transcribed. Audio that never
        transcribed is kept, and flagged on its note, until someone retries or discards it.
      </p>
      <Field label="Keep audio for (days)">
        <input aria-label="Keep audio for (days)" type="number" min={0} value={value}
          onChange={(e) => setDays(e.target.value)} style={{ maxWidth: "8rem" }} />
      </Field>
      {value === "0" && (
        <Banner kind="warn">
          At 0, audio is deleted as soon as its transcript is made. <strong>A recording can then
          never be transcribed again</strong> — if the transcript is poor, there is nothing to retry.
        </Banner>
      )}
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <button className="primary" disabled={days === null || save.isPending} onClick={() => save.mutate()}>Save</button>
    </Card>
  );
}
