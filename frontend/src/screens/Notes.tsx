import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";

import { Chip, FilterBar, PageHead, SearchField } from "../components/shell";
import { Banner, Empty, when } from "../components/ui";
import { Me, Note, NoteFolder, api } from "../lib/api";
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
interface Grid { total: number; results: NoteCard[]; companies: Option[]; contacts: Option[];
                 folders?: NoteFolder[] }

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
  return id ? <NoteDetail me={me} /> : <NotesGrid me={me} />;
}

/**
 * The folders, as a row above the grid (owner, 2026-10-12). Opening one
 * filters the grid to it. Three are built in and follow what a note is linked
 * to; the practice adds its own, and the practice owner renames or removes
 * the one that is open. A folder's number is how many notes opening it shows.
 */
function Folders({ me, folders, open, onOpen }: {
  me: Me; folders: NoteFolder[]; open: string; onOpen: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"" | "add" | "rename" | "remove">("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const current = folders.find((f) => f.id === open);
  const done = () => {
    setMode(""); setName(""); setError("");
    qc.invalidateQueries({ queryKey: ["notes"] });
    qc.invalidateQueries({ queryKey: ["note-folders"] });
  };
  const failed = (e: Error) => setError(e.message);
  const add = useMutation({
    mutationFn: () => api.post<NoteFolder>("/api/note-folders/", { name }),
    onSuccess: (made) => { done(); onOpen(made.id); }, onError: failed,
  });
  const rename = useMutation({
    mutationFn: () => api.patch<NoteFolder>(`/api/note-folders/${open}/`, { name }),
    onSuccess: done, onError: failed,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/note-folders/${open}/`),
    onSuccess: () => { done(); onOpen(""); }, onError: failed,
  });
  const mayChange = me.role === "FF" && !!current && !current.built_in;

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Folders" style={{ flexWrap: "wrap" }}>
        <button type="button" role="tab" aria-selected={!open}
          className={open ? "tab" : "tab on"} onClick={() => onOpen("")}>All notes</button>
        {folders.map((f) => (
          <button type="button" role="tab" key={f.id} aria-selected={open === f.id}
            className={open === f.id ? "tab on" : "tab"} onClick={() => onOpen(f.id)}>
            {f.name} <span className="muted">{f.notes ?? 0}</span>
          </button>
        ))}
        <button type="button" className="tab" onClick={() => { setMode("add"); setName(""); }}>
          + New folder</button>
      </div>
      {error && <Banner kind="bad">{error}</Banner>}
      {(mode === "add" || mode === "rename") && (
        <form className="listbar" onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) (mode === "add" ? add : rename).mutate();
        }}>
          <input aria-label={mode === "add" ? "The new folder's name" : "The folder's new name"}
            placeholder="Folder name" value={name} maxLength={80} autoFocus
            style={{ width: "auto", flex: "0 1 280px" }}
            onChange={(e) => setName(e.target.value)} />
          <button className="primary small" type="submit"
            disabled={!name.trim() || add.isPending || rename.isPending}>
            {mode === "add" ? "Add folder" : "Rename"}</button>
          <button className="small" type="button" onClick={() => { setMode(""); setError(""); }}>
            Cancel</button>
        </form>
      )}
      {mode === "remove" && current && (
        <div className="listbar">
          <span className="small">Remove the folder "{current.name}"? Its {current.notes ?? 0}{" "}
            note{current.notes === 1 ? "" : "s"} are kept, each back in the folder its link
            gives it.</span>
          <button className="primary small" disabled={remove.isPending}
            onClick={() => remove.mutate()}>Remove the folder</button>
          <button className="small" onClick={() => setMode("")}>Cancel</button>
        </div>
      )}
      {mayChange && mode === "" && (
        <p className="small">
          <button className="ghost small"
            onClick={() => { setMode("rename"); setName(current!.name); }}>Rename folder</button>{" "}
          <button className="ghost small" onClick={() => setMode("remove")}>Remove folder</button>
        </p>
      )}
    </>
  );
}

function NotesGrid({ me }: { me: Me }) {
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
  const locked = get("locked");
  const folder = get("folder");
  const narrowed = !!(q || company || contact || name || after || before || locked || folder);
  const step = narrowed ? MATCH_PAGE : PAGE;
  const limit = Number(get("show")) || step;

  const request = new URLSearchParams();
  if (q) request.set("q", q);
  if (company) request.set("company", company);
  if (contact) request.set("contact", contact);
  if (name) request.set("name", name);
  if (locked) request.set("locked", locked);
  if (folder) request.set("folder", folder);
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
          its title only, and by every filter.</>} />

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
          <select aria-label="Filter by lock" value={locked}
            onChange={(e) => set({ locked: e.target.value })}>
            <option value="">All notes</option>
            <option value="only">Locked only</option>
          </select>
        </div>
      </div>

      <Folders me={me} folders={grid.data?.folders ?? []} open={folder}
        onOpen={(id) => set({ folder: id })} />

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
          {locked && <Chip label="Locked only" onClear={() => set({ locked: "" })} />}
          {folder && <Chip
            label={`Folder: ${(grid.data?.folders ?? []).find((f) => f.id === folder)?.name ?? "…"}`}
            onClear={() => set({ folder: "" })} />}
        </FilterBar>
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
