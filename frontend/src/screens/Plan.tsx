import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Modal, PageHead, useNarrowWindow } from "../components/shell";
import { Banner, Empty, Pill } from "../components/ui";
import { api, Me } from "../lib/api";
import {
  about, CloseWalk, HorizonKey, MONTH_NAMES, PLAN_STATUSES, PlanChoices, PlanColumn, PlanItemRow,
  PlanKpi, PlanPayload, PlansIndex, PlanStatus, PlanTask, SourcesPayload, WeekPayload,
} from "../lib/plans";
import { useWords } from "../lib/words";

const STAFF = ["FF", "CF", "VA"];

function statusPill(status: PlanStatus, label: string) {
  const kind = status === "on_track" ? "ok" : status === "off_track" ? "bad"
    : status === "done" ? "info" : undefined;
  return <Pill kind={kind}>{label}</Pill>;
}

function kpiPill(k: PlanKpi) {
  if (!k.status) return <span className="muted">no status yet</span>;
  const kind = k.status === "on_track" ? "ok" : k.status === "behind" ? "warn" : "bad";
  return <Pill kind={kind}>{k.status_label}</Pill>;
}

/** Where the plan is asked for: a company's id, "practice", or the portal's "mine". */
function planKey(me: Me, id?: string, practice?: boolean) {
  if (practice) return "practice";
  if (id) return id;
  return STAFF.includes(me.role ?? "") ? "practice" : "mine";
}

/**
 * The Plan page (P11): five horizons, side by side, or as tabs on a phone.
 * Each item says what it serves above and what serves it below. The practice
 * adds, drafts from sources, accepts what Claude or the client proposed, and
 * closes a week, a month or a quarter; a client sees and adds what their
 * level allows (the server decides; this draws what it sends).
 */
export function PlanScreen({ me, practice = false }: { me: Me; practice?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const key = planKey(me, id, practice);
  const [periods, setPeriods] = useState<Partial<Record<HorizonKey, string>>>({});
  const params = new URLSearchParams(Object.entries(periods) as [string, string][]);
  const q = useQuery<PlanPayload>({
    queryKey: ["plan", key, params.toString()],
    queryFn: () => api.get<PlanPayload>(`/api/plans/${key}/${params.toString() ? `?${params}` : ""}`),
    placeholderData: (previous) => previous,
  });
  const narrow = useNarrowWindow(860);
  const [tab, setTab] = useState<HorizonKey | null>(null);
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  const d = q.data;
  if (!d) return <p>Loading…</p>;
  const columns = d.horizons;
  // On a phone: the week when it has a sprint, else the lowest horizon with
  // something on it, so the first tab shown is never an empty one by default.
  const filled = [...columns].reverse().find((c) => c.items.length || c.proposals.length);
  const week = columns.find((c) => c.key === "week");
  const shown = tab && columns.some((c) => c.key === tab) ? tab
    : (week && week.items.length ? week : filled ?? week ?? columns[0])?.key;
  const title = d.company.is_practice ? "Our practice's plan" : `${d.company.name} plan`;
  return (
    <div className="pl-page">
      <PageHead title={title}
        crumbs={STAFF.includes(me.role ?? "") ? [{ to: "/plans", label: "Plans" }] : undefined}
        sub={<FiscalLine d={d} planKey={key} />} />
      {narrow ? (
        <>
          <div className="pl-tabs" role="tablist" aria-label="Horizons">
            {columns.map((c) => (
              <button key={c.key} role="tab" aria-selected={c.key === shown}
                className={`pl-tab${c.key === shown ? " on" : ""}`}
                onClick={() => setTab(c.key)}>{c.name}</button>
            ))}
          </div>
          {columns.filter((c) => c.key === shown).map((c) => (
            <Column key={c.key} c={c} d={d} planKey={key} me={me}
              onPeriod={(start) => setPeriods({ ...periods, [c.key]: start })} />
          ))}
        </>
      ) : (
        <div className="pl-grid" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(176px, 1fr))` }}>
          {columns.map((c) => (
            <Column key={c.key} c={c} d={d} planKey={key} me={me}
              onPeriod={(start) => setPeriods({ ...periods, [c.key]: start })} />
          ))}
        </div>
      )}
    </div>
  );
}

function FiscalLine({ d, planKey: key }: { d: PlanPayload; planKey: string }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (month: number) => api.patch(`/api/plans/${key}/`, { fiscal_year_start: month }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plan", key] }),
  });
  const month = MONTH_NAMES[d.company.fiscal_year_start - 1];
  return (
    <span className="pl-fiscal">
      Each item serves the one above it.{" "}
      {d.access.edits ? (
        <span>The fiscal year starts in{" "}
          <select className="pl-inline-select" aria-label="Fiscal year starts in"
            value={d.company.fiscal_year_start}
            onChange={(e) => save.mutate(Number(e.target.value))}>
            {MONTH_NAMES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>.</span>
      ) : <>The fiscal year starts in {month}.</>}
      {d.access.edits && <> · <Link to="/settings/branding#plan-horizons">Rename the horizons</Link></>}
    </span>
  );
}

function Column({ c, d, planKey: key, me, onPeriod }: {
  c: PlanColumn; d: PlanPayload; planKey: string; me: Me; onPeriod: (start: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [drafting, setDrafting] = useState<{ parent?: PlanItemRow; period?: string } | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const adds = d.access.may_add.includes(c.key);
  const proposes = d.access.may_propose.includes(c.key);
  const isWeek = c.key === "week";
  const closeWord = c.key === "week" ? "week" : c.key === "month" ? "month" : "quarter";
  return (
    <section className="pl-col" aria-label={c.name}>
      <header className="pl-col-head">
        <h3>{c.name}</h3>
        <div className="pl-period">
          <button className="ghost small" aria-label={`Earlier: ${c.name}`}
            onClick={() => onPeriod(c.previous)}>‹</button>
          <span>{c.period_label}{c.is_current ? "" : " · not the current one"}</span>
          <button className="ghost small" aria-label={`Later: ${c.name}`}
            onClick={() => onPeriod(c.next)}>›</button>
        </div>
      </header>
      {c.closed && <div className="pl-closed" role="note">Closed. {c.closed.summary}</div>}
      {!c.closed && c.last_close && (
        <div className="pl-last" role="note"><strong>Last {closeWord}:</strong> {c.last_close.summary}</div>
      )}
      <div className="pl-actions">
        {(adds || proposes) && !(isWeek && c.items.length > 0) && (
          <button className="small" onClick={() => setAdding(true)}>
            {adds ? (isWeek ? "Set the sprint" : "Add") : "Propose"}</button>
        )}
        {d.access.may_draft && !(isWeek && c.items.length > 0) && (
          <button className="small" onClick={() => setDrafting({})}>Draft from sources</button>
        )}
        {c.close_offer && (
          <button className="small primary" onClick={() => setClosing(c.close_offer!.period_start)}>
            {c.close_offer.late ? `Close last ${closeWord}` : `Close the ${closeWord}`}</button>
        )}
      </div>
      {c.proposals.length > 0 && c.items.length > 0 && (
        <a className="pl-tray-note" href={`#tray-${c.key}`}>{d.access.sees_tray
          ? `${c.proposals.length} proposed, waiting below` : "Your proposal is waiting below"}</a>
      )}
      {c.items.length === 0 ? (
        <Empty>{isWeek ? "No sprint set for this week." : "Nothing here yet."}</Empty>
      ) : c.items.map((item) => (
        <ItemCard key={item.id} item={item} d={d} planKey={key} me={me}
          onBreakDown={() => setDrafting({ parent: item })} />
      ))}
      {c.proposals.length > 0 && (
        <div className="pl-tray" id={`tray-${c.key}`} aria-label={`Proposed for ${c.name}`}>
          <div className="pl-tray-head">{d.access.sees_tray ? `Proposed · ${c.proposals.length}`
            : "Waiting for the practice"}</div>
          {c.proposals.map((p) => <Proposal key={p.id} p={p} d={d} planKey={key} />)}
        </div>
      )}
      {adding && <ItemForm horizon={c.key} column={c} d={d} planKey={key}
        propose={!adds} onClose={() => setAdding(false)} />}
      {drafting && <DraftModal planKey={key} horizon={c.key} column={c}
        parent={drafting.parent} period={drafting.period ?? c.period_start}
        onClose={() => setDrafting(null)} />}
      {closing && <CloseModal planKey={key} horizon={c.key as "week" | "month" | "quarter"}
        period={closing} onClose={() => setClosing(null)}
        onDraftNext={(start) => { setClosing(null); onPeriod(start);
          setDrafting({ period: start }); }} />}
    </section>
  );
}

function useRefresh(key: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["plan", key] });
    qc.invalidateQueries({ queryKey: ["plan-week"] });
  };
}

function Proposal({ p, d, planKey: key }: { p: PlanItemRow; d: PlanPayload; planKey: string }) {
  const refresh = useRefresh(key);
  const [editing, setEditing] = useState(false);
  const act = useMutation({
    mutationFn: (verb: "accept" | "discard") => api.post(`/api/plan-items/${p.id}/${verb}/`),
    onSuccess: refresh,
  });
  const who = p.from_ai_app ? "From an AI app" : p.from_ai ? "Drafted by Claude"
    : p.proposed_by ? `Proposed by ${p.proposed_by}` : p.source_label;
  return (
    <div className="pl-proposal">
      <div className="pl-item-title">{p.title}</div>
      <div className="small muted pl-oneline" title={[p.done_means && `Done means: ${p.done_means}`,
        p.serves && `Serves: ${p.serves.title}`].filter(Boolean).join(" · ")}>
        {who}{p.drew_on.length > 0 && <> · drew on {p.drew_on.join("; ")}</>}</div>
      {act.isError && <Banner kind="bad">{(act.error as Error).message}</Banner>}
      {d.access.sees_tray && (
        <div className="row tight">
          <button className="small primary" disabled={act.isPending}
            onClick={() => act.mutate("accept")}>Accept</button>
          <button className="small" onClick={() => setEditing(true)}>Edit</button>
          <button className="small ghost" disabled={act.isPending}
            onClick={() => act.mutate("discard")}>Discard</button>
        </div>
      )}
      {editing && <ItemForm horizon={p.horizon} item={p} d={d} planKey={key}
        onClose={() => setEditing(false)} />}
    </div>
  );
}

function ItemCard({ item, d, planKey: key, me, onBreakDown }: {
  item: PlanItemRow; d: PlanPayload; planKey: string; me: Me; onBreakDown: () => void;
}) {
  const w = useWords();
  const refresh = useRefresh(key);
  const [editing, setEditing] = useState(false);
  const status = useMutation({
    mutationFn: (s: PlanStatus) => api.patch(`/api/plan-items/${item.id}/`, { status: s }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/plan-items/${item.id}/`), onSuccess: refresh });
  const staff = STAFF.includes(me.role ?? "");
  const scorecard = staff ? `/companies/${d.company.id}/scorecard` : "/scorecard";
  const done = item.tasks.filter((t) => t.done).length;
  return (
    <article className={`pl-item s-${item.status}`} aria-label={item.title}>
      {item.serves && <div className="pl-serves" title={`Serves: ${item.serves.title}`}>
        Serves: {item.serves.title}</div>}
      <div className="pl-item-title">{item.title}</div>
      <div className="pl-item-meta">
        {item.may_edit ? (
          <select aria-label={`Status of ${item.title}`} value={item.status}
            onChange={(e) => status.mutate(e.target.value as PlanStatus)}>
            {PLAN_STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        ) : statusPill(item.status, item.status_label)}
        {item.owner && <span className="small muted">{item.owner.name}</span>}
        {item.client_team && <span className="small muted">· {item.client_team.name}</span>}
      </div>
      {item.kpis.length > 0 && (
        <ul className="pl-kpis" aria-label={`${w.Kpis} of ${item.title}`}>
          {item.kpis.map((k) => (
            <li key={k.id}><Link to={scorecard}>{k.name}</Link> {k.value_text && <span className="muted">{k.value_text}</span>} {kpiPill(k)}</li>
          ))}
        </ul>
      )}
      {item.done_means && <div className="small">Done means: {item.done_means}</div>}
      {item.target_value !== null && <div className="small">Target: {item.target_value}</div>}
      {item.goal && (
        <div className="small">{w.Goal}: <Link to={`/work/goals/${item.goal.id}`}>{item.goal.title}</Link></div>
      )}
      {item.project && (
        <div className="small">{w.Project}: <Link to={`/work/projects/${item.project.id}`}>{item.project.title}</Link></div>
      )}
      {item.tasks.length > 0 && (
        <details className="pl-tasks" open={item.horizon === "week"}>
          <summary>{w.Tasks}: {done} of {item.tasks.length} done</summary>
          <ul>{item.tasks.map((t) => <TaskLine key={t.id} t={t} />)}</ul>
        </details>
      )}
      {item.served_by.length > 0 && (
        <details className="pl-served">
          <summary className="small muted">Served by {item.served_by.length}</summary>
          <ul>{item.served_by.map((c) => (
            <li key={c.id} className="small">{c.title} <span className="muted">· {c.status_label}</span></li>
          ))}</ul>
        </details>
      )}
      {(item.may_edit || d.access.may_draft) && (
        <div className="row tight pl-item-actions">
          {item.may_edit && <button className="small ghost" onClick={() => setEditing(true)}>Edit</button>}
          {d.access.may_draft && item.horizon !== "week" && (
            <button className="small ghost" onClick={onBreakDown}>Break this down</button>
          )}
          {d.access.edits && <button className="small ghost" disabled={remove.isPending}
            onClick={() => remove.mutate()}>Remove</button>}
        </div>
      )}
      {editing && <ItemForm horizon={item.horizon} item={item} d={d} planKey={key}
        onClose={() => setEditing(false)} />}
    </article>
  );
}

function TaskLine({ t }: { t: PlanTask }) {
  return (
    <li className={t.done ? "pl-task done" : "pl-task"}>
      <span aria-hidden="true">{t.done ? "✓" : "○"}</span> {t.title}
      <span className="muted small"> · {t.status_label}{t.client_owner ? ` · ${t.client_owner}`
        : t.owner ? ` · ${t.owner}` : ""}{t.due_date ? ` · due ${t.due_date}` : ""}</span>
    </li>
  );
}

/** Add an item (or propose one), or edit one: title, done means, owner, what
 *  it serves, its status and links. */
function ItemForm({ horizon, item, column, d, planKey: key, propose = false, onClose }: {
  horizon: HorizonKey; item?: PlanItemRow; column?: PlanColumn; d: PlanPayload; planKey: string;
  propose?: boolean; onClose: () => void;
}) {
  const w = useWords();
  const refresh = useRefresh(key);
  const choices: PlanChoices = d.choices ?? { people: [], goals: [], projects: [], tasks: [],
    kpis: [], teams: [] };
  const above = d.horizons[d.horizons.findIndex((c) => c.key === horizon) - 1];
  const [f, setF] = useState({
    title: item?.title ?? "", done_means: item?.done_means ?? "", owner: item?.owner?.id ?? "",
    parent: item?.serves?.id ?? "", status: item?.status ?? "on_track",
    goal: item?.goal?.id ?? "", project: item?.project?.id ?? "",
    client_team: item?.client_team?.id ?? "", target_value: item?.target_value?.toString() ?? "",
    tasks: item?.tasks.map((t) => t.id) ?? [] as string[],
    kpis: item?.kpis.map((k) => k.id) ?? [] as string[], new_task: "",
  });
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch });
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        title: f.title, done_means: f.done_means, owner: f.owner || null,
        parent: f.parent || null, status: f.status,
      };
      if (d.access.edits) {
        Object.assign(body, { goal: f.goal || null, project: f.project || null,
          kpis: f.kpis, target_value: f.target_value || null });
      }
      if (horizon === "month" || horizon === "week") body.client_team = f.client_team || null;
      if (horizon !== "picture") body.tasks = f.tasks;
      if (f.new_task.trim()) body.new_tasks = f.new_task.split("\n").filter((x) => x.trim());
      if (item) return api.patch(`/api/plan-items/${item.id}/`, body);
      return api.post("/api/plan-items/", { ...body, company: key, horizon,
        period_start: column?.period_start });
    },
    onSuccess: () => { refresh(); onClose(); },
  });
  const verb = item ? "Save" : propose ? "Propose it" : "Add it";
  const heading = item ? `Edit: ${item.title}` : propose ? `Propose for ${column?.name}`
    : `Add to ${column?.name}`;
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
  return (
    <Modal label={heading} title={heading} wide onClose={onClose}>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {propose && <Banner>The practice approves it before it goes on the plan.</Banner>}
      <div className="pl-form">
        <label>{horizon === "week" ? "Sprint goal (one sentence)" : "Title"}
          <input value={f.title} maxLength={300} onChange={(e) => set({ title: e.target.value })} /></label>
        <label>Done means
          <input value={f.done_means} placeholder="How anyone will know it's done"
            onChange={(e) => set({ done_means: e.target.value })} /></label>
        {choices.people.length > 0 && (
          <label>Owner<select value={f.owner} onChange={(e) => set({ owner: e.target.value })}>
            <option value="">No one yet</option>
            {choices.people.map((p) => <option key={p.id} value={p.id}>{p.name}{p.side === "client" ? " (client)" : ""}</option>)}
          </select></label>
        )}
        {above && (
          <label>Serves<select value={f.parent} onChange={(e) => set({ parent: e.target.value })}>
            <option value="">Nothing above it</option>
            {above.items.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
          </select></label>
        )}
        <label>Status<select value={f.status} onChange={(e) => set({ status: e.target.value as PlanStatus })}>
          {PLAN_STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select></label>
        {(horizon === "month" || horizon === "week") && choices.teams.length > 0 && (
          <label>Team<select value={f.client_team} onChange={(e) => set({ client_team: e.target.value })}>
            <option value="">The whole company</option>
            {choices.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select></label>
        )}
        {d.access.edits && horizon === "year" && (
          <label>{w.Goal}<select value={f.goal} onChange={(e) => set({ goal: e.target.value })}>
            <option value="">{item ? "Keep as it is" : `Make a new ${w.goal} from the title`}</option>
            {choices.goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
          </select></label>
        )}
        {d.access.edits && horizon !== "picture" && horizon !== "year" && choices.goals.length > 0 && (
          <label>{w.Goal} (optional)<select value={f.goal} onChange={(e) => set({ goal: e.target.value })}>
            <option value="">None</option>
            {choices.goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
          </select></label>
        )}
        {d.access.edits && horizon !== "picture" && choices.projects.length > 0 && (
          <label>{w.Project} (optional)<select value={f.project} onChange={(e) => set({ project: e.target.value })}>
            <option value="">None</option>
            {choices.projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select></label>
        )}
        {d.access.edits && horizon === "picture" && (
          <label>Measurable target (optional)<input inputMode="decimal" value={f.target_value}
            onChange={(e) => set({ target_value: e.target.value })} /></label>
        )}
      </div>
      {horizon !== "picture" && (
        <fieldset className="pl-fieldset">
          <legend>{w.Tasks}{horizon === "week" ? " in the sprint" : " (optional)"}</legend>
          <div className="pl-picks">
            {choices.tasks.map((t) => (
              <label key={t.id} className="check"><input type="checkbox" checked={f.tasks.includes(t.id)}
                onChange={() => set({ tasks: toggle(f.tasks, t.id) })} /> {t.title}</label>
            ))}
            {choices.tasks.length === 0 && <span className="small muted">No open {w.tasks} yet.</span>}
          </div>
          <label>New {w.tasks}, one a line<textarea rows={2} value={f.new_task}
            onChange={(e) => set({ new_task: e.target.value })} /></label>
        </fieldset>
      )}
      {d.access.edits && choices.kpis.length > 0 && (
        <fieldset className="pl-fieldset">
          <legend>{w.Kpis} it is read by (optional)</legend>
          <div className="pl-picks">{choices.kpis.map((k) => (
            <label key={k.id} className="check"><input type="checkbox" checked={f.kpis.includes(k.id)}
              onChange={() => set({ kpis: toggle(f.kpis, k.id) })} /> {k.name}</label>
          ))}</div>
        </fieldset>
      )}
      <div className="row tight">
        <button className="primary" disabled={save.isPending || !f.title.trim()}
          onClick={() => save.mutate()}>{verb}</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

/** "Draft from sources" (or "Break this down"): price first, then proposals
 *  into the tray, each naming what it drew on. */
function DraftModal({ planKey: key, horizon, column, parent, period, onClose }: {
  planKey: string; horizon: HorizonKey; column: PlanColumn; parent?: PlanItemRow; period: string;
  onClose: () => void;
}) {
  const refresh = useRefresh(key);
  const q = useQuery<SourcesPayload>({ queryKey: ["plan-sources", key],
    queryFn: () => api.get<SourcesPayload>(`/api/plans/${key}/sources/`) });
  const [chosen, setChosen] = useState<string[]>([]);
  const [pasted, setPasted] = useState("");
  const [done, setDone] = useState<string>("");
  const run = useMutation({
    mutationFn: () => api.post<{ proposals: PlanItemRow[]; cost_usd: string }>(
      `/api/plans/${key}/draft/`, {
        horizon, period_start: period, parent: parent?.id,
        sources: (q.data?.sources ?? []).filter((s) => chosen.includes(`${s.type}|${s.id}`))
          .map((s) => ({ type: s.type, id: s.id })), pasted }),
    onSuccess: (r) => {
      refresh();
      setDone(`${r.proposals.length} proposed into the tray (cost $${Number(r.cost_usd).toFixed(2)}). Accept, edit or discard each.`);
    },
  });
  const ai = q.data?.ai;
  const title = parent ? `Break this down: ${parent.title}` : `Draft ${column.name} from sources`;
  return (
    <Modal label={title} title={title} wide onClose={onClose}>
      {q.isError && <Banner kind="bad">{(q.error as Error).message}</Banner>}
      {run.isError && <Banner kind="bad">{(run.error as Error).message}</Banner>}
      {done && <Banner kind="ok">{done}</Banner>}
      <p className="small muted">Claude reads what you choose and proposes items. Nothing goes on
        the plan until someone accepts it. Mail, PIN-locked notes and People records are never read.</p>
      {q.data && (
        <fieldset className="pl-fieldset">
          <legend>{parent ? "Also draw on (optional)" : "Draw on"}</legend>
          <div className="pl-picks">
            {q.data.sources.map((s) => {
              const id = `${s.type}|${s.id}`;
              return (
                <label key={id} className="check"><input type="checkbox" checked={chosen.includes(id)}
                  onChange={() => setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id])} />
                  {" "}{s.label} <span className="muted small">· {s.detail}</span></label>
              );
            })}
          </div>
          <label>Pasted text, such as a notebook's summary
            <textarea rows={4} value={pasted} onChange={(e) => setPasted(e.target.value)} /></label>
        </fieldset>
      )}
      <div className="row tight">
        {ai?.refused ? <Banner kind="warn">{ai.refused}</Banner> : (
          <button className="primary" disabled={!ai || run.isPending
            || (!parent && chosen.length === 0 && !pasted.trim())}
            onClick={() => run.mutate()}>
            {run.isPending ? "Asking Claude…" : `Draft with Claude (${about(ai?.estimate_usd)})`}</button>
        )}
        <button onClick={onClose}>{done ? "Done" : "Cancel"}</button>
        {ai && <span className="small muted">{ai.used_today} of {ai.cap} today</span>}
      </div>
    </Modal>
  );
}

/** Close a week, a month or a quarter: each row done, not done or carried
 *  over (chosen, never by itself). The summary goes into the weekly digest
 *  drafts; a month or a quarter then offers to draft the next one. */
function CloseModal({ planKey: key, horizon, period, onClose, onDraftNext }: {
  planKey: string; horizon: "week" | "month" | "quarter"; period: string; onClose: () => void;
  onDraftNext: (start: string) => void;
}) {
  const refresh = useRefresh(key);
  const w = useWords();
  const q = useQuery<CloseWalk>({ queryKey: ["plan-close", key, horizon, period],
    queryFn: () => api.get<CloseWalk>(`/api/plans/${key}/close/?horizon=${horizon}&period=${period}`) });
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ summary: string; next: { period_start: string; period_label: string };
    offer_draft: boolean } | null>(null);
  const close = useMutation({
    mutationFn: () => api.post<typeof result>(`/api/plans/${key}/close/`,
      { horizon, period_start: period, outcomes: chosen }),
    onSuccess: (r) => { refresh(); setResult(r); },
  });
  const walk = q.data;
  const title = walk ? `Close ${walk.period_label}` : "Close";
  const outcome = (id: string, suggested: string) => chosen[id] ?? suggested;
  const what = horizon === "week" ? w.tasks : "items";
  return (
    <Modal label={title} title={title} wide onClose={onClose}>
      {q.isError && <Banner kind="bad">{(q.error as Error).message}</Banner>}
      {close.isError && <Banner kind="bad">{(close.error as Error).message}</Banner>}
      {result ? (
        <>
          <Banner kind="ok">{result.summary}</Banner>
          <p className="small muted">The summary goes into this week's digest drafts for the
            company's people: a draft already waiting says to update it.</p>
          <div className="row tight">
            {result.offer_draft && (
              <button className="primary" onClick={() => onDraftNext(result.next.period_start)}>
                Draft {result.next.period_label} from sources</button>
            )}
            <button onClick={onClose}>Done</button>
          </div>
        </>
      ) : walk && (
        <>
          {walk.sprint && <p><strong>Sprint goal:</strong> {walk.sprint}</p>}
          <p className="small muted">Each of the {what}: done, not done, or carried over to
            {" "}{walk.next.period_label}. Nothing is carried over unless you choose it.</p>
          <table className="pl-close-table">
            <thead><tr><th>{horizon === "week" ? w.Task : "Item"}</th><th>Done</th><th>Not done</th><th>Carry over</th></tr></thead>
            <tbody>
              {walk.rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.title}</td>
                  {(["done", "not_done", "carried"] as const).map((o) => (
                    <td key={o}><input type="radio" name={`o-${r.id}`}
                      aria-label={`${r.title}: ${o === "done" ? "done" : o === "not_done" ? "not done" : "carry over"}`}
                      checked={outcome(r.id, r.suggested) === o}
                      onChange={() => setChosen({ ...chosen, [r.id]: o })} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row tight">
            <button className="primary" disabled={close.isPending} onClick={() => close.mutate()}>
              Close {walk.period_label}</button>
            <button onClick={onClose}>Cancel</button>
          </div>
        </>
      )}
    </Modal>
  );
}

/** Plans: the practice's own and each client's, with the week at a glance. */
export function PlansScreen() {
  const q = useQuery<PlansIndex>({ queryKey: ["plans"],
    queryFn: () => api.get<PlansIndex>("/api/plans/") });
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  if (!q.data) return <p>Loading…</p>;
  return (
    <div>
      <PageHead title="Plans" sub="One plan per client, and one for the practice: from the three-year picture to this week's sprint." />
      <div className="clients">
        {q.data.plans.map((p) => (
          <Link key={p.id} className="client-card"
            to={p.is_practice ? "/plans/practice" : `/companies/${p.id}/plan`}>
            <strong>{p.is_practice ? "Our practice" : p.name}</strong>
            <span className="small muted">{glanceText(p.week)}</span>
            {p.week && p.week.off_track > 0 && <Pill kind="bad">{p.week.off_track} off track</Pill>}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function glanceText(week: { sprint: string; done: number; total: number } | null | undefined): ReactNode {
  if (!week) return "No sprint this week";
  if (!week.sprint) return "No sprint this week";
  return `This week: ${week.sprint} · ${week.done} of ${week.total} done`;
}

/** The portal's This week: what a team member opens on Monday. */
export function ThisWeekScreen() {
  const w = useWords();
  const q = useQuery<WeekPayload>({ queryKey: ["plan-week"],
    queryFn: () => api.get<WeekPayload>("/api/plans/mine/week/") });
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  const d = q.data;
  if (!d) return <p>Loading…</p>;
  const list = (title: string, tasks: PlanTask[], empty: string) => (
    <section className="pl-week-list" aria-label={title}>
      <h3>{title}</h3>
      {tasks.length === 0 ? <p className="small muted">{empty}</p>
        : <ul>{tasks.map((t) => <TaskLine key={t.id} t={t} />)}</ul>}
    </section>
  );
  return (
    <div className="pl-week">
      <PageHead title={d.name} sub={d.period_label} />
      {!d.sprint ? <Empty>No sprint is set for this week yet.</Empty> : (
        <>
          <section className="pl-sprint" aria-label="The sprint goal">
            <div className="pl-eyebrow">This week we will</div>
            <div className="pl-sprint-goal">{d.sprint.title}</div>
            {d.sprint.done_means && <div className="small">Done means: {d.sprint.done_means}</div>}
            <div className="small muted">{d.done ?? 0} of {d.total ?? 0} {w.tasks} done</div>
          </section>
          {d.serves.length > 0 && (
            <section className="pl-serves-chain" aria-label="What the week serves">
              <h3>What it serves</h3>
              <ol>{d.serves.map((s) => (
                <li key={s.id}><span className="muted small">{s.name}:</span> {s.title} <span className="muted small">· {s.status_label}</span></li>
              ))}</ol>
            </section>
          )}
          <div className="pl-week-cols">
            {list(`Your ${w.tasks}`, d.mine, `None of the sprint's ${w.tasks} are yours.`)}
            {list(`Your team's ${w.tasks}`, d.team, `Nothing else for your team this week.`)}
            {d.others.length > 0 && list(`Everyone else's ${w.tasks}`, d.others, "")}
          </div>
          <p className="small"><Link to="/plan">See the whole plan</Link></p>
        </>
      )}
    </div>
  );
}
