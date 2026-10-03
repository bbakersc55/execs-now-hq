import { useState, type DragEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowDown, ArrowLeftRight, ArrowRight, ArrowUp, CheckSquare, GripVertical, Hourglass, Mail, Target,
  TrendingUp,
} from "lucide-react";

import { GettingStarted } from "../components/GettingStarted";
import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { Dashboard as Board, Me, Pipeline, aiPausedMessage, api } from "../lib/api";
import { useRemembered } from "../lib/remembered";

type Move = Board["pipeline"][number];

const TILES = ["tasks", "digests", "pipeline", "goals", "waiting"] as const;
const PANELS = ["due", "approval", "pipeline", "finances", "clients"] as const;
type TileId = (typeof TILES)[number];
type PanelId = (typeof PANELS)[number];
/** A block anywhere on the dashboard. Prefixed, because "pipeline" is both a
 *  tile and a panel. */
type BlockKey = `tile:${TileId}` | `panel:${PanelId}`;
type RowName = "top" | "bottom";
/** Two rows, each holding any blocks in any order (backlog, 2026-10-03: free
 *  drag across rows). Saved per person in this browser. */
interface Layout { top: BlockKey[]; bottom: BlockKey[] }

const ALL_BLOCKS: BlockKey[] = [
  ...TILES.map((id) => `tile:${id}` as BlockKey), ...PANELS.map((id) => `panel:${id}` as BlockKey),
];
const DEFAULT_LAYOUT: Layout = {
  top: TILES.map((id) => `tile:${id}` as BlockKey),
  bottom: PANELS.map((id) => `panel:${id}` as BlockKey),
};

const TILE_NAMES: Record<TileId, string> = {
  tasks: "Tasks due", digests: "Digests waiting", pipeline: "Pipeline moves",
  goals: "Open goals", waiting: "Waiting on others",
};
const PANEL_NAMES: Record<PanelId, string> = {
  due: "Due by day", approval: "Waiting for approval", pipeline: "Pipeline",
  finances: "Practice finances", clients: "Clients",
};

/**
 * The landing page (design brief, Tier 2).
 *
 * **One screen with one question: what needs me today.** Four tiles across the
 * top answer it at a glance, and each panel below is the same answer with
 * enough detail to act on. Everything here links somewhere — a dashboard you
 * can only read is a dashboard you stop opening.
 *
 * Elevation is spent on nothing here (Tier 1 foundations): these are all cards
 * at rest, and the one thing that stands out is whatever is overdue, marked in
 * colour rather than in shadow.
 *
 * **The order is the person's own.** "Arrange" lets them drag any block to any
 * place in either row, remembered per user in this browser like the other
 * remembered choices. *(Until 2026-10-03 tiles stayed among tiles and panels
 * among panels; the owner asked for free movement across rows.)*
 */
export function Dashboard({ me }: { me: Me }) {
  const board = useQuery<Board>({
    queryKey: ["dashboard"], queryFn: () => api.get<Board>("/api/dashboard/"),
  });
  // The dashboard carries each move's pipeline by *name*, which the FF can
  // rename; `kind` is what behaviour keys on (FR-1.6), so it is looked up here.
  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });
  const [saved, remember] = useRemembered<Layout | LegacyLayout>(
    `dashboard-layout:${me.email || "anon"}`, DEFAULT_LAYOUT);
  const [arranging, setArranging] = useState(false);

  if (board.isLoading) return <p className="muted">Loading…</p>;
  if (!board.data) return null;
  const { tiles, due_by_day: days, digests, pipeline, clients } = board.data;
  const first = me.full_name.split(" ")[0];

  const layout = normalise(saved);
  // A VA has no financials (access matrix), so not even the empty slot.
  const hidden = (key: BlockKey) => key === "panel:finances" && me.role === "VA";
  const kinds = new Map((pipelines.data ?? []).map((p) => [p.name, p.kind]));

  const tile: Record<TileId, ReactNode> = {
    tasks: (
      <Tile label="Tasks due" value={tiles.tasks_due} icon={CheckSquare}
        to="/tasks"
        // Folded into the total and named on its own: a number that hides
        // how much of it is late is a number you stop reading.
        note={tiles.tasks_overdue > 0
          ? `${tiles.tasks_overdue} overdue` : "none overdue"}
        bad={tiles.tasks_overdue > 0} />
    ),
    digests: (
      <Tile label="Digests waiting" value={tiles.digests_pending} icon={Mail}
        to="/digests" note="for your approval" />
    ),
    pipeline: (
      <Tile label="Pipeline moves" value={tiles.pipeline_moves} icon={TrendingUp}
        to="/pipeline" note="in the last week" />
    ),
    goals: (
      <Tile label="Open goals" value={tiles.goals_open} icon={Target}
        to="/work" note="across every client" />
    ),
    // Commitments by people outside the practice (2026-09-28), overdue named.
    waiting: (
      <Tile label="Waiting on others" value={board.data.waiting?.open ?? 0} icon={Hourglass}
        to="/waiting"
        note={(board.data.waiting?.overdue ?? 0) > 0
          ? `${board.data.waiting!.overdue} overdue` : "none overdue"}
        bad={(board.data.waiting?.overdue ?? 0) > 0} />
    ),
  };

  const panel: Record<PanelId, ReactNode> = {
    due: (
      <Card title="Due by day">
        {days.every((day) => day.count === 0) ? (
          <Empty>Nothing due this week.</Empty>
        ) : (
          <ul className="byday">
            {days.map((day) => (
              <li key={day.label} className={day.overdue ? "late" : ""}>
                <span className="day">{day.label}</span>
                {/* Quiet days are shown, not skipped: a list that hides them
                    makes a light week look like a missing one. */}
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, day.count * 20)}%` }} />
                </span>
                <span className="count">{day.count || "—"}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    ),
    approval: (
      <Card title="Waiting for approval"
        actions={digests.length > 0 &&
          <Link className="small" to="/digests">All digests <ArrowRight size={12} /></Link>}>
        {digests.length === 0 ? (
          <Empty>Nothing waiting. Digests appear here before they send.</Empty>
        ) : (
          <ul className="moves">
            {digests.map((digest) => (
              <li key={digest.id}>
                {/* FR-3.29 — **approving is a read, not a click.** The
                    approval screen exists because approving something you
                    have not read is the failure it prevents, and this panel
                    cannot show the rendered digest. So it lists what is
                    waiting and takes you there. */}
                <Link to="/digests">{digest.contact}</Link>
                <span className="small muted">
                  {digest.cadence} · through {digest.period_end.slice(0, 10)}
                  {digest.ai_prose && " · AI-drafted"}
                  {digest.stale && " · out of date"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    ),
    pipeline: (
      <Card title="Pipeline"
        actions={<Link className="small" to="/pipeline">Pipeline <ArrowRight size={12} /></Link>}>
        {pipeline.length === 0 ? (
          <Empty>No stage changes in the last week.</Empty>
        ) : (
          <div className="pipe-cols">
            <PipelineColumn title="New prospects"
              moves={pipeline.filter((m) => kinds.get(m.pipeline) === "sales")} />
            <PipelineColumn title="New partners"
              moves={pipeline.filter((m) => kinds.get(m.pipeline) === "referral")} />
          </div>
        )}
      </Card>
    ),
    finances: (
      <Card title="Practice finances">
        {/* AI credit, the FF's only (FR-0.9): the one money figure the app
            already has. A warning here is the same one the AI usage screen
            shows (owner, 2026-09-28). */}
        {board.data.ai && (
          <>
            {board.data.ai.warnings.map((w) => (
              <Banner key={w.kind} kind="warn">{w.message}</Banner>
            ))}
            <p className="small">
              AI this month <strong>${board.data.ai.month_spend}</strong>
              {board.data.ai.monthly_budget_usd && <> of ${board.data.ai.monthly_budget_usd}</>}
              {board.data.ai.estimated_balance !== null && (
                <> · about <strong>${board.data.ai.estimated_balance}</strong> left on the
                  account (estimate)</>
              )}
              {" · "}<Link to="/ai-usage">AI usage</Link>
            </p>
          </>
        )}
        {/* A reserved slot, so the layout has its home before the finance
            module does. No figures until then — not even zeros, which would
            read as a practice that earned nothing. */}
        <Empty>Income, expenses and margin appear here once the finance module lands.</Empty>
      </Card>
    ),
    clients: (
      <>
        <h3 className="section">Clients</h3>
        {clients.length === 0 ? (
          <Empty>No client companies yet.</Empty>
        ) : (
          <div className="clients">
            {clients.map((client) => (
              <Link key={client.id} className="client-card"
                to={`/companies/${client.id}`}>
                <strong>{client.name}</strong>
                <span className="small muted">
                  {client.open_tasks} open · {client.open_goals} goal
                  {client.open_goals === 1 ? "" : "s"}
                </span>
                {client.overdue > 0 && <Pill kind="bad">{client.overdue} overdue</Pill>}
              </Link>
            ))}
          </div>
        )}
      </>
    ),
  };

  return (
    <>
      <PageHead title={`Good to see you, ${first}`}
        sub={`What needs you over the next ${board.data.window_days} days.`}
        action={
          <span className="inline">
            {arranging && (
              <button className="ghost small" onClick={() => remember(DEFAULT_LAYOUT)}>
                Reset layout
              </button>
            )}
            <button className={arranging ? "primary small" : "ghost small"}
              aria-pressed={arranging} onClick={() => setArranging(!arranging)}>
              {arranging ? "Done" : "Arrange"}
            </button>
          </span>
        } />

      {/* P2: the practice owner's Getting started list, until it is all done. */}
      {me.role === "FF" && <GettingStarted />}

      {board.data.ai_paused && (
        <Banner kind="warn">
          {aiPausedMessage(board.data.ai_paused)}
          {me.role === "FF" && <> <Link to="/ai-usage">AI usage</Link></>}
        </Banner>
      )}

      {arranging && (
        <p className="small muted arrange-hint">
          Drag the tiles and panels into the order you want, or use the arrows.
          Saved for you in this browser.
        </p>
      )}

      <ArrangeRows arranging={arranging} layout={layout} hidden={hidden}
        onChange={remember}
        render={(key) => key.startsWith("tile:")
          ? tile[key.slice(5) as TileId] : panel[key.slice(6) as PanelId]} />
    </>
  );
}

/**
 * One pipeline's recent movement, as names grouped by week.
 *
 * Names only: the stage and the exact time are one hover away, because the
 * question this panel answers is *who* is new, and a line of dates under every
 * name made that harder to see. A contact who moved twice is listed once, at
 * their latest move. "This week" is the last seven days, matching the rest of
 * the dashboard (`WINDOW_DAYS`), not the calendar week.
 */
function PipelineColumn({ title, moves }: { title: string; moves: Move[] }) {
  const latest = new Map<string, Move>();
  for (const move of [...moves].sort((a, b) => b.at.localeCompare(a.at))) {
    if (!latest.has(move.contact)) latest.set(move.contact, move);
  }
  const week = 7 * 24 * 60 * 60 * 1000;
  const age = (move: Move) => Date.now() - new Date(move.at).getTime();
  const groups = [
    { label: "This week", rows: [...latest.values()].filter((m) => age(m) < week) },
    { label: "Last week",
      rows: [...latest.values()].filter((m) => age(m) >= week && age(m) < 2 * week) },
  ].filter((group) => group.rows.length > 0);

  return (
    <div className="pipe-col">
      <h4>{title}</h4>
      {groups.length === 0 ? (
        <p className="small muted">None.</p>
      ) : groups.map((group) => (
        <div key={group.label}>
          <div className="pipe-week">{group.label}</div>
          <ul className="names">
            {group.rows.map((move) => (
              <li key={move.contact}>
                <Link to={`/contacts/${move.contact}`}
                  title={`${move.from ? `${move.from} → ` : "Entered "}${move.to} · ${when(move.at)}`}>
                  {move.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function nameOf(key: BlockKey): string {
  return key.startsWith("tile:") ? TILE_NAMES[key.slice(5) as TileId]
    : PANEL_NAMES[key.slice(6) as PanelId];
}

/**
 * Arrange mode: the two rows, and any block may move to any place in either
 * (backlog, 2026-10-03). Before, tiles stayed among tiles and panels among
 * panels; now a panel can sit in the top row and a tile in the bottom one.
 *
 * Drop a block on another to take its place, or on a row's end zone to go
 * last in that row (which is also how an emptied row is filled again). The
 * arrows and "to the other row" are the same moves for a keyboard. While
 * arranging, the links inside the blocks are inert: a drag that ends as a
 * click would leave the page halfway through arranging it.
 */
function ArrangeRows({ arranging, layout, hidden, onChange, render }: {
  arranging: boolean; layout: Layout; hidden: (key: BlockKey) => boolean;
  onChange: (layout: Layout) => void; render: (key: BlockKey) => ReactNode;
}) {
  const [dragging, setDragging] = useState<BlockKey | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const visible = { top: layout.top.filter((k) => !hidden(k)),
                    bottom: layout.bottom.filter((k) => !hidden(k)) };

  /** Move a block to `index` among the *visible* blocks of `row`. Hidden
   *  blocks keep their saved place. */
  const moveTo = (key: BlockKey, row: RowName, index: number) => {
    const next: Layout = { top: layout.top.filter((k) => k !== key),
                           bottom: layout.bottom.filter((k) => k !== key) };
    const shown = next[row].filter((k) => !hidden(k));
    const clamped = Math.max(0, Math.min(index, shown.length));
    const before = shown[clamped];
    const at = before === undefined ? next[row].length : next[row].indexOf(before);
    next[row].splice(at, 0, key);
    if (next.top.join() !== layout.top.join() || next.bottom.join() !== layout.bottom.join()) {
      onChange(next);
    }
  };
  const clear = () => { setDragging(null); setOver(null); };
  const other = (row: RowName): RowName => (row === "top" ? "bottom" : "top");

  return (
    <>
      {(["top", "bottom"] as RowName[]).map((row) => (
        <div key={row} data-testid={`row-${row}`}
          className={`${row === "top" ? "tiles" : "panels"}${arranging ? " arranging" : ""}`}>
          {visible[row].map((key, index) => {
            const id = key.split(":")[1];
            const classes = ["slot",
              key === "panel:clients" ? "wide" : "",
              dragging === key ? "dragging" : "",
              over === key && dragging !== key ? "drop-target" : ""].filter(Boolean).join(" ");
            if (!arranging) {
              return <div key={key} className={classes}>{render(key)}</div>;
            }
            const name = nameOf(key);
            return (
              <div key={key} className={classes} data-testid={`slot-${id}`} data-key={key}
                draggable
                onDragStart={(event: DragEvent) => {
                  setDragging(key);
                  // Firefox will not start a drag without data on the transfer.
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", key);
                }}
                onDragOver={(event: DragEvent) => {
                  if (dragging === null) return;
                  event.preventDefault();
                  if (over !== key) setOver(key);
                }}
                onDrop={(event: DragEvent) => {
                  event.preventDefault();
                  if (dragging !== null) moveTo(dragging, row, index);
                  clear();
                }}
                onDragEnd={clear}>
                <div className="slot-bar">
                  <GripVertical size={14} aria-hidden="true" />
                  <span className="small">{name}</span>
                  <span className="grow" />
                  <button className="icon-button" disabled={index === 0}
                    aria-label={`Move ${name} earlier`}
                    onClick={() => moveTo(key, row, index - 1)}>
                    <ArrowUp size={14} />
                  </button>
                  <button className="icon-button" disabled={index === visible[row].length - 1}
                    aria-label={`Move ${name} later`}
                    onClick={() => moveTo(key, row, index + 1)}>
                    <ArrowDown size={14} />
                  </button>
                  <button className="icon-button"
                    aria-label={`Move ${name} to the ${other(row)} row`}
                    onClick={() => moveTo(key, other(row), visible[other(row)].length)}>
                    <ArrowLeftRight size={14} />
                  </button>
                </div>
                <div className="slot-body">{render(key)}</div>
              </div>
            );
          })}
          {arranging && (
            <div className={`row-end${over === `end:${row}` ? " drop-target" : ""}`}
              data-testid={`row-end-${row}`}
              onDragOver={(event: DragEvent) => {
                if (dragging === null) return;
                event.preventDefault();
                if (over !== `end:${row}`) setOver(`end:${row}`);
              }}
              onDrop={(event: DragEvent) => {
                event.preventDefault();
                if (dragging !== null) moveTo(dragging, row, visible[row].length);
                clear();
              }}>
              Drop here to put it last in this row
            </div>
          )}
        </div>
      ))}
    </>
  );
}

/** The shape saved before 2026-10-03: tiles and panels in their own lists. */
interface LegacyLayout { tiles?: unknown; panels?: unknown }

/**
 * What was saved, made safe to lay out: an old two-list layout becomes the two
 * rows; anything no longer on the dashboard is dropped; and anything new is
 * added at the end of its usual row, so a block added in a later release (the
 * finances slot, for one) appears for people who had already arranged theirs.
 */
function normalise(saved: Layout | LegacyLayout | null | undefined): Layout {
  const asKeys = (ids: unknown, prefix: "tile" | "panel" | ""): BlockKey[] =>
    (Array.isArray(ids) ? ids : []).map((id) => (prefix && !String(id).includes(":")
      ? `${prefix}:${id}` : String(id)) as BlockKey);
  const raw = saved as Partial<Layout> & LegacyLayout | null | undefined;
  let top: BlockKey[];
  let bottom: BlockKey[];
  if (raw && ("top" in raw || "bottom" in raw)) {
    top = asKeys(raw.top, "");
    bottom = asKeys(raw.bottom, "");
  } else {
    top = asKeys(raw?.tiles, "tile");
    bottom = asKeys(raw?.panels, "panel");
  }
  const seen = new Set<BlockKey>();
  const keep = (keys: BlockKey[]) => keys.filter((key) => {
    if (!ALL_BLOCKS.includes(key) || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  top = keep(top);
  bottom = keep(bottom);
  for (const key of ALL_BLOCKS) {
    if (!seen.has(key)) (key.startsWith("tile:") ? top : bottom).push(key);
  }
  return { top, bottom };
}

function Tile({ label, value, note, icon: Icon, to, bad }: {
  label: string; value: number; note: string;
  icon: typeof Target; to: string; bad?: boolean;
}) {
  return (
    <Link className="tile" to={to}>
      <span className="tile-label"><Icon size={14} /> {label}</span>
      <span className="tile-value">{value}</span>
      <span className={`tile-note${bad ? " bad" : ""}`}>{note}</span>
    </Link>
  );
}
