import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Mail, MoreHorizontal, Phone } from "lucide-react";
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { SearchField } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { Board, Contact, Pipeline as PipelineType, api } from "../lib/api";

function fullName(c: Contact) {
  return `${c.first_name} ${c.last_name}`.trim();
}

/** The one marked primary, or the first when none is. */
function primary<T extends { is_primary: boolean }>(rows: T[] | undefined) {
  return rows?.find((r) => r.is_primary) ?? rows?.[0];
}

function matches(c: Contact, query: string) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [
    fullName(c), c.company_name ?? "",
    ...(c.emails ?? []).map((e) => e.address),
    ...(c.phones ?? []).map((p) => p.number),
  ].some((text) => text.toLowerCase().includes(q));
}

/** What a stage means, in the two words a board needs. */
const SEMANTIC_HINT: Record<string, string> = {
  entry: "where contacts enter",
  won: "reaching this makes them a client",
  lost: "closed, not lost from the record",
  parked: "still yours, just not active",
};

export function Pipeline() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string>("");
  const [moving, setMoving] = useState<Contact | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [dragging, setDragging] = useState<Contact | null>(null);
  const [over, setOver] = useState<string>("");
  const [query, setQuery] = useState("");
  // What the server is asked: the search once typing pauses, and the columns
  // whose "Show more" was pressed. Both are part of the one board request, so
  // a move refreshes them along with everything else.
  const [asked, setAsked] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => setAsked(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  const pipelines = useQuery<PipelineType[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<PipelineType[]>("/api/pipelines/"),
  });

  const current = selected || pipelines.data?.[0]?.id || "";

  const board = useQuery<Board>({
    queryKey: ["board", current, asked, expanded],
    queryFn: () => {
      const params = new URLSearchParams();
      if (asked) params.set("q", asked);
      if (expanded.length) params.set("expand", expanded.join(","));
      const qs = params.toString();
      return api.get<Board>(`/api/pipelines/${current}/board/${qs ? `?${qs}` : ""}`);
    },
    enabled: !!current,
    // The cards stay put while a search or a "Show more" is on its way.
    placeholderData: keepPreviousData,
  });

  const move = useMutation({
    mutationFn: (vars: { id: string; stage: string; reason: string }) =>
      api.post(`/api/contacts/${vars.id}/change-stage/`, {
        stage: vars.stage, reason: vars.reason,
      }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["board"] });
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
      const stage = board.data?.columns.find((c) => c.stage.id === vars.stage)?.stage;
      const isSale = stage?.semantic === "won" && board.data?.pipeline.kind === "sales";
      setNote(
        isSale
          ? `Moved to ${stage?.label}. The contact type ‘client’ was added and their company flagged as a client company.`
          : "Stage updated. Any matching automations for this pipeline have fired."
      );
      setMoving(null); setReason("");
    },
  });

  /**
   * A drop is the same move as the panel: the same endpoint, so the same
   * automations and the same client invariant.
   *
   * Dropping on a `lost` stage does NOT move them straight away — it opens the
   * move panel with that stage selected so the reason can be typed. FR-1.7
   * prompts for a reason on a lost stage, and a drag that skipped the prompt
   * would be a quieter way of doing the one move that most deserves a note.
   */
  function handleDrop(contact: Contact, stageId: string, semantic: string) {
    setOver("");
    setDragging(null);
    const current = columns.find((c) =>
      c.contacts.some((x) => x.id === contact.id))?.stage;
    if (current?.id === stageId) return;
    if (semantic === "lost") {
      setMoving(contact);
      setTarget(stageId);
      setReason("");
      return;
    }
    move.mutate({ id: contact.id, stage: stageId, reason: "" });
  }

  if (pipelines.isLoading) return <p className="muted">Loading…</p>;
  const list = pipelines.data ?? [];
  if (list.length === 0) {
    return (
      <>
        <h2>Pipeline</h2>
        <Empty>No pipelines yet. The practice owner creates them in pipeline settings.</Empty>
      </>
    );
  }

  const columns = board.data?.columns ?? [];
  const activePipeline = board.data?.pipeline;
  const movingHere = moving
    ? columns.find((c) => c.contacts.some((x) => x.id === moving.id))?.stage
    : undefined;

  const draggingFrom = dragging
    ? columns.find((c) => c.contacts.some((x) => x.id === dragging.id))?.stage.id
    : undefined;

  function openMove(contact: Contact) {
    setMoving(contact); setTarget(""); setReason("");
  }

  return (
    <>
      <h2>Pipeline</h2>
      <p className="sub">
        Drag a card to another stage, or use the menu on the card. A contact in two
        pipelines has a card on each board, and moving one does not move the other.
      </p>

      <div className="pipeline-bar">
        <div className="row tight">
          {list.map((p) => (
            <button
              key={p.id}
              className={p.id === current ? "primary" : "ghost"}
              onClick={() => { setSelected(p.id); setMoving(null); setExpanded([]); }}
            >
              {p.name} <span className="muted">· {p.contact_count}</span>
            </button>
          ))}
        </div>
        <SearchField label="Find on this board" value={query} onChange={setQuery}
          placeholder="Find by name, company, email or phone" />
      </div>

      {note && <Banner kind="ok">{note}</Banner>}

      {board.isError && (
        <Banner kind="bad">The board could not be loaded. Reload the page to try again.</Banner>
      )}

      {board.isLoading ? <p className="muted">Loading board…</p> : (
        <div className="pipeline-board">
          {columns.map((col) => {
            // Typing narrows the loaded cards at once; the server's answer,
            // which also covers the cards not loaded, follows.
            const shown = col.contacts.filter((c) => matches(c, query));
            const searching = !!query.trim();
            const answered = (board.data?.q ?? "") === query.trim();
            // `matched` is the whole column unless the server ran the search.
            const total = col.matched ?? col.count;
            const hidden = Math.max(0, total - col.contacts.length);
            const canDrop = !!dragging && draggingFrom !== col.stage.id;
            const classes = ["col"];
            if (canDrop) classes.push("can-drop");
            if (canDrop && over === col.stage.id) classes.push("drop-target");
            return (
              <section
                className={classes.join(" ")}
                key={col.stage.id}
                aria-label={`${col.stage.label} column`}
                onDragOver={(e) => { e.preventDefault(); setOver(col.stage.id); }}
                onDragLeave={(e) => {
                  // Crossing onto a card inside the column is not leaving it.
                  if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
                  setOver((o) => (o === col.stage.id ? "" : o));
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragging) handleDrop(dragging, col.stage.id, col.stage.semantic);
                }}
              >
                <header className="col-top">
                  <div className="col-head">
                    <h4>{col.stage.label}</h4>
                    <span className="count"
                      aria-label={`${col.count} contact${col.count === 1 ? "" : "s"}`}>
                      {searching ? `${answered ? total : shown.length} of ${col.count}` : col.count}
                    </span>
                  </div>
                  {SEMANTIC_HINT[col.stage.semantic] && (
                    <div className="hint">{SEMANTIC_HINT[col.stage.semantic]}</div>
                  )}
                </header>
                <div className="col-cards">
                  {shown.length === 0 && (
                    <p className="none">
                      {col.count === 0 ? "No one here" : "No match"}
                    </p>
                  )}
                  {shown.map((c) => (
                    <ContactCard
                      key={c.id}
                      contact={c}
                      alsoIn={(c.pipeline_positions ?? [])
                        .filter((p) => p.pipeline !== current)
                        .map((p) => p.pipeline_name)}
                      dragging={dragging?.id === c.id}
                      onDragStart={() => setDragging(c)}
                      onDragEnd={() => { setDragging(null); setOver(""); }}
                      onMove={() => openMove(c)}
                    />
                  ))}
                  {hidden > 0 && (searching && !answered ? (
                    <p className="none">Searching {hidden} more not shown here…</p>
                  ) : (
                    <div className="more">
                      <span>
                        Showing {col.contacts.length} of {total}{searching ? " matches" : ""}
                      </span>
                      <button type="button" className="small"
                        disabled={board.isFetching}
                        aria-label={`Show more in ${col.stage.label}`}
                        onClick={() => setExpanded((e) => [...e, col.stage.id])}>
                        Show more
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {moving && (
        <>
        <div className="sheet-backdrop" onClick={() => setMoving(null)} />
        <div className="move-dialog" role="dialog" aria-modal="true"
          aria-label={`Move ${fullName(moving)}`}
          onKeyDown={(e) => { if (e.key === "Escape") setMoving(null); }}>
          <h3>Move {fullName(moving)} in {activePipeline?.name}</h3>
          <div className="row">
            <div>
              <label htmlFor="move-stage">New stage</label>
              <select id="move-stage" value={target} autoFocus={!target}
                onChange={(e) => setTarget(e.target.value)}>
                <option value="">Choose…</option>
                {columns
                  .filter((c) => c.stage.id !== movingHere?.id)
                  .map((c) => (
                    <option key={c.stage.id} value={c.stage.id}>{c.stage.label}</option>
                  ))}
              </select>
            </div>
            <div>
              <label>
                Reason{" "}
                {columns.find((c) => c.stage.id === target)?.stage.semantic === "lost" && (
                  <strong>(prompted on a lost stage — may be skipped)</strong>
                )}
              </label>
              <input value={reason} autoFocus={!!target} aria-label="Reason"
                onChange={(e) => setReason(e.target.value)} />
            </div>
            <div style={{ flex: "0 0 auto" }}>
              <button
                className="primary"
                disabled={!target || move.isPending}
                onClick={() => move.mutate({ id: moving.id, stage: target, reason })}
              >
                {move.isPending ? "Moving…" : "Move"}
              </button>{" "}
              <button onClick={() => setMoving(null)}>Cancel</button>
            </div>
          </div>
          {(moving.pipeline_positions ?? []).length > 0 && (
            <p className="muted small">
              Currently:{" "}
              {(moving.pipeline_positions ?? [])
                .map((p) => `${p.pipeline_name} → ${p.stage_label}`).join(" · ")}
              . Only <strong>{activePipeline?.name}</strong> changes.
            </p>
          )}
          {columns.find((c) => c.stage.id === target)?.stage.semantic === "won"
            && activePipeline?.kind === "sales" && (
            <Banner kind="warn">
              This adds the client contact type and flags their company as a client
              company — the same as any other route to that stage.
            </Banner>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>
            <Link to={`/contacts/${moving.id}`}>Open contact →</Link>
          </p>
        </div>
        </>
      )}

      <Card title="Where each pipeline stands">
        <table>
          <thead><tr><th>Pipeline</th><th>Kind</th><th>Stages</th><th>Contacts</th></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td><Pill kind={p.kind === "sales" ? "ai" : ""}>{p.kind}</Pill></td>
                <td className="muted small">
                  {p.stages.slice().sort((a, b) => a.position - b.position)
                    .map((s) => s.label).join(" → ")}
                </td>
                <td className="muted small">{p.contact_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

/**
 * One contact on the board. The whole card is the handle and the whole card
 * opens the contact; the menu is the one part that does neither.
 */
function ContactCard({ contact, alsoIn, dragging, onDragStart, onDragEnd, onMove }: {
  contact: Contact; alsoIn: string[]; dragging: boolean;
  onDragStart: () => void; onDragEnd: () => void; onMove: () => void;
}) {
  const navigate = useNavigate();
  const name = fullName(contact);
  const email = primary(contact.emails)?.address;
  const phone = primary(contact.phones)?.number;
  const open = () => navigate(`/contacts/${contact.id}`);

  return (
    <div
      className={`contact-card${dragging ? " dragging" : ""}`}
      draggable
      onDragStart={(e) => {
        onDragStart();
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", contact.id);
      }}
      onDragEnd={onDragEnd}
      onClick={(e) => {
        // The name is a link and opens it by itself; the menu opens nothing.
        if ((e.target as HTMLElement).closest("a, .card-menu")) return;
        open();
      }}
    >
      <div className="card-top">
        {/* A real link, so the contact is reachable by keyboard and opens in
            a new tab. Not draggable itself: grabbing the name drags the card. */}
        <Link className="name" to={`/contacts/${contact.id}`} draggable={false}>{name}</Link>
        <CardMenu name={name} onMove={onMove} onOpen={open} />
      </div>
      {contact.company_name && (
        <div className="line"><Building2 size={14} aria-hidden="true" />
          <span>{contact.company_name}</span></div>
      )}
      {email && (
        <div className="line"><Mail size={14} aria-hidden="true" /><span>{email}</span></div>
      )}
      {phone && (
        <div className="line"><Phone size={14} aria-hidden="true" /><span>{phone}</span></div>
      )}
      {alsoIn.length > 0 && <Pill>also in {alsoIn.join(", ")}</Pill>}
    </div>
  );
}

/**
 * The way to move a card without dragging it: keyboard, and touch, where the
 * browser's drag and drop does not work at all.
 */
function CardMenu({ name, onMove, onOpen }: {
  name: string; onMove: () => void; onOpen: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  const items = () => Array.from(
    wrap.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    // The last card in a long column opens its menu below the fold.
    wrap.current?.querySelector('[role="menu"]')?.scrollIntoView?.({ block: "nearest" });
    const away = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  function onKeyDown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const all = items();
      const at = all.indexOf(document.activeElement as HTMLElement);
      const step = e.key === "ArrowDown" ? 1 : -1;
      all[(at + step + all.length) % all.length]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  const choose = (action: () => void) => () => { setOpen(false); action(); };

  return (
    <div className="card-menu" ref={wrap} onKeyDown={onKeyDown}>
      <button ref={button} type="button" className="icon-button"
        aria-label={`Actions for ${name}`} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" aria-label={`Actions for ${name}`}>
          <button type="button" role="menuitem" onClick={choose(onMove)}>
            Move to another stage…
          </button>
          <button type="button" role="menuitem" onClick={choose(onOpen)}>
            Open contact
          </button>
        </div>
      )}
    </div>
  );
}
