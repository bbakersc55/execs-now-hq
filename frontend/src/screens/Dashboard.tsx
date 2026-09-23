import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, CheckSquare, Mail, Target, TrendingUp } from "lucide-react";

import { PageHead } from "../components/shell";
import { Card, Empty, Pill, when } from "../components/ui";
import { Dashboard as Board, Me, api } from "../lib/api";

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
 */
export function Dashboard({ me }: { me: Me }) {
  const board = useQuery<Board>({
    queryKey: ["dashboard"], queryFn: () => api.get<Board>("/api/dashboard/"),
  });

  if (board.isLoading) return <p className="muted">Loading…</p>;
  if (!board.data) return null;
  const { tiles, due_by_day: days, digests, pipeline, clients } = board.data;
  const first = me.full_name.split(" ")[0];

  return (
    <>
      <PageHead title={`Good to see you, ${first}`}
        sub={`What needs you over the next ${board.data.window_days} days.`} />

      <div className="tiles">
        <Tile label="Tasks due" value={tiles.tasks_due} icon={CheckSquare}
          to="/tasks"
          // Folded into the total and named on its own: a number that hides
          // how much of it is late is a number you stop reading.
          note={tiles.tasks_overdue > 0
            ? `${tiles.tasks_overdue} overdue` : "none overdue"}
          bad={tiles.tasks_overdue > 0} />
        <Tile label="Digests waiting" value={tiles.digests_pending} icon={Mail}
          to="/digests" note="for your approval" />
        <Tile label="Pipeline moves" value={tiles.pipeline_moves} icon={TrendingUp}
          to="/pipeline" note="in the last week" />
        <Tile label="Open goals" value={tiles.goals_open} icon={Target}
          to="/work" note="across every client" />
      </div>

      <div className="panels">
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

        <Card title="Pipeline this week">
          {pipeline.length === 0 ? (
            <Empty>No stage changes in the last week.</Empty>
          ) : (
            <ul className="moves">
              {pipeline.map((move) => (
                <li key={move.id}>
                  <Link to={`/contacts/${move.contact}`}>{move.name}</Link>
                  <span className="small muted">
                    {move.from ? `${move.from} → ` : "entered "}
                    <strong>{move.to}</strong> · {when(move.at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

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
  );
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
