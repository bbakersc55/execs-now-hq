import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import {
  BONUS_VIEW_LABEL, BonusComponentRow, BonusEditorChoices, BonusPayload, BonusPlanDraft,
  BonusPlanHead, BonusRow, BonusTier, BonusViewKey,
} from "../lib/scorecard";
import { Modal } from "./shell";
import { Banner } from "./ui";

/** Dollars as the bonus pages say them: "$504", "$383.22". */
export function usd(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const whole = Math.abs(value - Math.round(value)) < 0.005;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 })}`;
}

function achClass(a: number | null) {
  if (a === null) return "";
  return a >= 100 ? "bn-ok" : a >= 80 ? "bn-behind" : "bn-off";
}

/** As the mock-up labels a tier: "<80% · 0%", "80–100 · 50%", "110+ · 120%". */
function tierText(t: BonusTier, next?: BonusTier) {
  const range = !next ? `${t.from}+` : t.from === 0 ? `<${next.from}%` : `${t.from}–${next.from}`;
  return `${range} · ${t.share}%`;
}

const DEFAULT_TIERS: BonusTier[] = [
  { from: 0, share: 0 }, { from: 80, share: 50 }, { from: 100, share: 100 }, { from: 110, share: 120 }];

/**
 * Part 2's bonus views, to the approved mock-up (docs/design/kpi_scorecard/
 * Bonus.dc.html): My bonus for a person on a plan, Team bonus for a manager,
 * All bonuses for senior leadership, the client owner and the practice. The
 * server sends only the rows the reader may see (decision 7); this draws them.
 */
export function BonusArea({ companyId, view, companyName }: {
  companyId: string; view: BonusViewKey; companyName: string;
}) {
  const [plan, setPlan] = useState("");
  const [period, setPeriod] = useState("");
  const params = new URLSearchParams({ company: companyId, view });
  if (view === "mine" && plan) params.set("plan", plan);
  if (view !== "mine" && period) params.set("period", period);
  const q = useQuery<BonusPayload>({
    queryKey: ["scorecard-bonus", companyId, view, plan, period],
    queryFn: () => api.get<BonusPayload>(`/api/scorecard/bonus/?${params}`),
    placeholderData: (previous) => previous,
  });
  if (q.isError) return <Banner kind="bad">{(q.error as Error).message}</Banner>;
  const d = q.data;
  if (!d) return <p>Loading…</p>;
  if (view === "mine" && d.me && d.plan) {
    return <MyBonus d={d} companyName={companyName} onPlan={setPlan} />;
  }
  return <BonusTables d={d} view={view} companyId={companyId} onPeriod={setPeriod} />;
}

export function bonusLead(view: BonusViewKey) {
  return view === "mine" ? "Only you see this page. Your manager and the owner see the team's numbers."
    : view === "team" ? "Your team's bonuses: you see your own and the people on the teams you manage."
      : "Every plan and every person, with totals per plan. A closed period's Payroll list downloads as a spreadsheet.";
}

function MyBonus({ d, companyName, onPlan }: {
  d: BonusPayload; companyName: string; onPlan: (id: string) => void;
}) {
  const plan = d.plan!;
  const me = d.me!;
  const earned = me.earned ?? 0;
  const full = me.amount ?? 0;
  const noun = plan.period === "monthly" ? "month" : "quarter";
  const when = plan.closed ? "closed" : plan.ended ? "ended, waiting to close"
    : `${plan.days_left} day${plan.days_left === 1 ? "" : "s"} left`;
  return (
    <div className="bn-page">
      {(d.choices ?? []).length > 1 && (
        <div className="sc-controls bn-period">
          <label htmlFor="bn-plan" className="sc-muted">Period</label>
          <select id="bn-plan" className="sc-select" value={plan.id}
            onChange={(e) => onPlan(e.target.value)}>
            {d.choices!.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </div>
      )}
      <section aria-label="Earned so far" className="bn-hero">
        <div className="bn-hero-main">
          <div className="bn-eyebrow">{plan.period_label} · {when}</div>
          <div className="bn-big-line">
            <div className="bn-big">{usd(earned)}</div>
            <div className="bn-big-sub">
              {plan.closed ? "earned" : "earned so far"} of a {usd(full)} {me.prorated
                ? `bonus (${me.days_on} of ${me.days} days on the plan)` : `full-${noun} bonus`}</div>
          </div>
          <div className="bn-bar" role="img"
            aria-label={`${full ? Math.round((earned / full) * 100) : 0}% of the full bonus`}>
            <div style={{ width: `${full ? Math.min(100, (earned / full) * 100) : 0}%` }} />
          </div>
        </div>
        {me.next && (
          <div className="bn-moves">
            <div className="bn-moves-head">What moves the number</div>
            <div>{me.next}</div>
          </div>
        )}
        {plan.closed && (
          <div className="bn-moves">
            <div className="bn-moves-head">Closed</div>
            <div>Frozen on {new Date(plan.closed_at!).toLocaleDateString("en-US",
              { month: "long", day: "numeric" })} with the readings it was worked out from.</div>
          </div>
        )}
      </section>
      <div className="bn-cards">
        {me.components.map((c) => <ComponentCard key={c.kpi} c={c} plan={plan} noun={noun} />)}
      </div>
      <div className="bn-cards">
        {(d.earlier ?? []).length > 0 && (
          <section aria-label="Earlier periods" className="bn-card">
            <div className="bn-card-name">Earlier {noun}s</div>
            <div className="bn-earlier">
              {d.earlier!.map((e) => (
                <div key={e.id} className="bn-earlier-row">
                  <span>{e.short}</span>
                  <span className="bn-mini-bar"><span style={{
                    width: `${e.full ? Math.min(100, (e.earned / e.full) * 100) : 0}%` }} /></span>
                  <span className="bn-earlier-amt">{usd(e.earned)}</span>
                </div>
              ))}
            </div>
            <div className="sc-muted bn-small">A closed {noun} is frozen with the readings it was computed from.</div>
          </section>
        )}
        <section aria-label="About this plan" className="bn-card">
          <div className="bn-card-name">About this plan</div>
          <p className="bn-about">{plan.name}, set by {d.practice_name}. Achievement to date
            compares your numbers so far with the target prorated to today, so mid-{noun} figures
            are fair rather than frightening.</p>
          <p className="bn-about">The app shows what the plan earns; it doesn't pay it. {companyName} pays
            bonuses through payroll after the {noun} closes.</p>
        </section>
      </div>
    </div>
  );
}

function ComponentCard({ c, plan, noun }: { c: BonusComponentRow; plan: BonusPlanHead; noun: string }) {
  const summed = c.rollup === "sum";
  const lower = c.direction === "lower";
  const sub = summed && !lower
    ? `of ${c.target_text} this ${noun}${plan.closed || plan.ended ? "" : ` · ${c.expected_text} expected by today`}`
    : `${c.rollup === "average" ? "average" : "latest"} this ${noun} · ${lower ? "keep under" : "target"} ${c.target_text}`;
  return (
    <section aria-label={`${c.name} component`} className="bn-card">
      <div className="bn-card-head">
        <div className="bn-card-name">{c.name}</div>
        <span className="bn-weight">{c.weight}% of the plan</span>
      </div>
      <div className="bn-value-line">
        <div className="bn-value">{c.value === null ? "—" : c.value_text}</div>
        <div className="sc-muted">{c.value === null ? "No readings yet" : sub}</div>
      </div>
      <div className="bn-ach"><span>Achievement {plan.closed ? "" : "to date"}</span>
        <span className={achClass(c.achievement)}>{c.achievement === null ? "—" : `${c.achievement}%`}</span></div>
      {plan.straight_line ? (
        <div className="bn-tiers"><span className="bn-tier on">Straight line · capped at {plan.cap_pct}%</span></div>
      ) : (
        <div className="bn-tiers" aria-label={`Tiers: ${c.tiers.map((t, i) => tierText(t, c.tiers[i + 1])).join(", ")}`}>
          {c.tiers.map((t, i) => {
            const on = c.tier === i;
            const cls = on ? (t.share === 0 ? "bn-tier zero" : "bn-tier on") : "bn-tier";
            return <span key={i} className={cls}>{tierText(t, c.tiers[i + 1])}</span>;
          })}
        </div>
      )}
      {c.next && <div className="bn-next">{c.next.text}</div>}
      {c.earned !== undefined && (
        <div className="bn-earned"><span className="sc-muted">Earned {plan.closed ? "" : "so far"}</span>
          <span className="bn-earned-amt">{usd(c.earned)}</span></div>
      )}
    </section>
  );
}

function overall(r: BonusRow) {
  if (r.earned === undefined || !r.amount) {
    const shares = r.components.reduce((a, c) => a + (c.weight * c.share) / 100, 0);
    return Math.round(shares);
  }
  return Math.round((r.earned / r.amount) * 100);
}

function BonusTables({ d, view, companyId, onPeriod }: {
  d: BonusPayload; view: BonusViewKey; companyId: string; onPeriod: (key: string) => void;
}) {
  const [editing, setEditing] = useState<BonusPlanDraft | null>(null);
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["scorecard-bonus", companyId] });
    qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
  };
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post(path, body ?? {}),
    onSuccess: refresh,
  });
  const groups = d.plans ?? [];
  const startNew = () => setEditing({
    name: "", period: "monthly", period_start: new Date().toISOString().slice(0, 8) + "01",
    amount: "", straight_line: false, cap_pct: 120,
    components: [{ kpi: "", weight: 50, target_value: null, tiers: DEFAULT_TIERS },
      { kpi: "", weight: 50, target_value: null, tiers: DEFAULT_TIERS }],
    people: [] });
  const edit = async (id: string) => {
    const plan = await api.get<BonusPlanDraft>(`/api/scorecard/bonus/plans/${id}/`);
    setEditing(plan);
  };
  return (
    <div className="bn-page">
      <div className="sc-controls bn-period">
        {(d.periods ?? []).length > 0 && (
          <>
            <label htmlFor="bn-period" className="sc-muted">Period</label>
            <select id="bn-period" className="sc-select" value={d.period ?? ""}
              onChange={(e) => onPeriod(e.target.value)}>
              {d.periods!.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
          </>
        )}
        {d.may_build && <button className="primary small" onClick={startNew}>New plan</button>}
      </div>
      {act.isError && <Banner kind="bad">{(act.error as Error).message}</Banner>}
      {groups.length === 0 && (
        <div className="bn-card"><p className="sc-empty">
          {d.may_build ? "No bonus plans yet. A plan turns a few per-person KPIs into one number each person can check any day."
            : "No bonus plans in this period."}</p></div>
      )}
      {groups.map(({ plan, rows }) => (
        <section key={plan.id} className="bn-card bn-plan" aria-label={`${plan.name}, ${plan.period_label}`}>
          <div className="bn-plan-head">
            <div>
              <div className="bn-card-name">{plan.name}</div>
              <div className="sc-muted">{plan.period_label} · {plan.closed
                ? `closed${plan.closed_by ? ` by ${plan.closed_by}` : ""}`
                : plan.ended ? "ended, not closed yet" : `${plan.days_left} days left`}
                {plan.totals ? ` · ${usd(plan.totals.earned)} earned of ${usd(plan.totals.full)} for ${plan.totals.people} ${plan.totals.people === 1 ? "person" : "people"}` : ""}</div>
            </div>
            <div className="row tight">
              {d.may_build && !plan.closed && <button className="small" onClick={() => edit(plan.id)}>Edit</button>}
              {d.may_build && !plan.next_exists && (
                <button className="small" disabled={act.isPending}
                  onClick={() => act.mutate({ path: `/api/scorecard/bonus/plans/${plan.id}/copy-forward/` })}>
                  Copy forward</button>)}
              {d.may_close && plan.ended && !plan.closed && (
                <button className="primary small" disabled={act.isPending}
                  onClick={() => act.mutate({ path: `/api/scorecard/bonus/plans/${plan.id}/close/` })}>
                  Close {plan.period === "monthly" ? "the month" : "the quarter"}</button>)}
            </div>
          </div>
          {(plan.corrections ?? []).length > 0 && (
            <Corrections plan={plan} mayConfirm={d.may_confirm_reopen}
              onConfirm={() => act.mutate({ path: `/api/scorecard/bonus/plans/${plan.id}/reopen/`, body: { confirm: true } })}
              busy={act.isPending} />
          )}
          <div className="bn-table-box">
            <table className="bn-table" aria-label={`${plan.name} people`}>
              <thead><tr>
                <th>Person</th>
                {(rows[0]?.components ?? []).map((c) => <th key={c.kpi} className="money">{c.name} <span className="sc-muted">({c.weight}%)</span></th>)}
                <th className="money">Overall</th>
                {d.sees_amounts && <th className="money">Earned</th>}
                {d.sees_amounts && <th className="money">Of</th>}
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.membership}>
                    <td>{r.name}{r.prorated && <span className="sc-muted"> · {r.days_on} of {r.days} days</span>}</td>
                    {r.components.map((c) => (
                      <td key={c.kpi} className={`money ${achClass(c.achievement)}`}>
                        {c.achievement === null ? "—" : `${c.achievement}%`}</td>
                    ))}
                    <td className="money">{overall(r)}%</td>
                    {d.sees_amounts && <td className="money"><strong>{usd(r.earned)}</strong></td>}
                    {d.sees_amounts && <td className="money sc-muted">{usd(r.amount)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      {view === "all" && (d.payroll ?? []).length > 0 && (
        <section className="bn-card" aria-label="Payroll list">
          <div className="bn-plan-head">
            <div>
              <div className="bn-card-name">Payroll list</div>
              <div className="sc-muted">One row per person for the closed period, to key into payroll.
                The app doesn't pay it.</div>
            </div>
            <a className="btn small" href={`/api/scorecard/bonus/payroll/?company=${companyId}&period=${encodeURIComponent(d.period ?? "")}`}
              download>Download spreadsheet</a>
          </div>
          <div className="bn-table-box">
            <table className="bn-table" aria-label="Payroll">
              <thead><tr><th>Person</th><th>Plan</th><th>Period</th><th className="money">Amount earned</th></tr></thead>
              <tbody>
                {d.payroll!.map((p, i) => (
                  <tr key={i}><td>{p.name}</td><td>{p.plan}</td><td>{p.period}</td>
                    <td className="money"><strong>{usd(p.earned)}</strong></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {editing && d.editor && (
        <PlanEditor draft={editing} choices={d.editor} companyId={companyId}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />
      )}
    </div>
  );
}

function Corrections({ plan, mayConfirm, onConfirm, busy }: {
  plan: BonusPlanHead; mayConfirm: boolean; onConfirm: () => void; busy: boolean;
}) {
  const [sure, setSure] = useState(false);
  return (
    <div className="bn-corrections" role="note">
      <strong>Readings changed after the close.</strong> The amounts below are the frozen ones.
      <ul>
        {plan.corrections!.map((c, i) => (
          <li key={i}>{c.name}, {c.kpi}, {c.period}: {c.frozen ?? "none"} at the close, {c.now ?? "none"} now</li>
        ))}
      </ul>
      {mayConfirm ? (
        <div className="row tight">
          <label className="check"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
            {" "}I confirm working this period's amounts out again from the corrected readings</label>
          <button className="small" disabled={!sure || busy} onClick={onConfirm}>Work them out again</button>
        </div>
      ) : <div className="sc-muted">The client owner confirms before the amounts change.</div>}
    </div>
  );
}

function PlanEditor({ draft, choices, companyId, onClose, onSaved }: {
  draft: BonusPlanDraft; choices: BonusEditorChoices; companyId: string;
  onClose: () => void; onSaved: () => void;
}) {
  const [p, setP] = useState<BonusPlanDraft>(draft);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...p, company: companyId,
        components: p.components.map((c) => ({ ...c, target_value: c.target_value === "" ? null : c.target_value })) };
      return p.id ? api.patch(`/api/scorecard/bonus/plans/${p.id}/`, body)
        : api.post("/api/scorecard/bonus/plans/", body);
    },
    onSuccess: onSaved,
  });
  const set = (patch: Partial<BonusPlanDraft>) => setP({ ...p, ...patch });
  const setComp = (i: number, patch: Partial<BonusPlanDraft["components"][number]>) =>
    set({ components: p.components.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const onPlan = new Set(p.people.map((x) => x.membership));
  const total = p.components.reduce((a, c) => a + (Number(c.weight) || 0), 0);
  return (
    <Modal label={p.id ? "Edit bonus plan" : "New bonus plan"} wide onClose={onClose}
      title={p.id ? `Edit ${p.name}` : "New bonus plan"}>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <div className="bn-form">
        <label>Name<input value={p.name} onChange={(e) => set({ name: e.target.value })} /></label>
        <label>Period<select value={p.period} onChange={(e) => set({ period: e.target.value as "monthly" | "quarterly" })}>
          <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option></select></label>
        <label>Starting<input type="month" value={p.period_start.slice(0, 7)}
          onChange={(e) => set({ period_start: `${e.target.value}-01` })} /></label>
        <label>Amount per person, full period<input inputMode="decimal" value={p.amount}
          onChange={(e) => set({ amount: e.target.value })} /></label>
      </div>
      <fieldset className="bn-fieldset">
        <legend>Components ({total}% of 100%)</legend>
        <label className="check"><input type="checkbox" checked={p.straight_line}
          onChange={(e) => set({ straight_line: e.target.checked })} /> A straight line instead of tiers
          (the share is the achievement)</label>
        {p.straight_line && <label>Capped at %<input inputMode="decimal" value={p.cap_pct}
          onChange={(e) => set({ cap_pct: Number(e.target.value) || 0 })} /></label>}
        {p.components.map((c, i) => (
          <div key={i} className="bn-comp-row">
            <label>KPI<select aria-label={`Component ${i + 1} KPI`} value={c.kpi} onChange={(e) => setComp(i, { kpi: e.target.value })}>
              <option value="">Choose a per-person KPI</option>
              {choices.kpis.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select></label>
            <label>Weight %<input aria-label={`Component ${i + 1} weight`} inputMode="decimal" value={c.weight}
              onChange={(e) => setComp(i, { weight: e.target.value })} /></label>
            <label>Period target (optional)<input inputMode="decimal" value={c.target_value ?? ""}
              placeholder="from the KPI" onChange={(e) => setComp(i, { target_value: e.target.value })} /></label>
            {!p.straight_line && (
              <details className="bn-tier-edit"><summary>Tiers</summary>
                {c.tiers.map((t, j) => (
                  <div key={j} className="row tight">
                    <label>From %<input inputMode="decimal" value={t.from} disabled={j === 0}
                      onChange={(e) => setComp(i, { tiers: c.tiers.map((x, k) => (k === j ? { ...x, from: Number(e.target.value) || 0 } : x)) })} /></label>
                    <label>Share %<input inputMode="decimal" value={t.share}
                      onChange={(e) => setComp(i, { tiers: c.tiers.map((x, k) => (k === j ? { ...x, share: Number(e.target.value) || 0 } : x)) })} /></label>
                    {j > 0 && <button className="small ghost" onClick={() => setComp(i, { tiers: c.tiers.filter((_, k) => k !== j) })}>Remove</button>}
                  </div>
                ))}
                {c.tiers.length < 8 && <button className="small" onClick={() => setComp(i, {
                  tiers: [...c.tiers, { from: (c.tiers[c.tiers.length - 1]?.from ?? 0) + 10, share: 100 }] })}>Add a tier</button>}
              </details>
            )}
            {p.components.length > 2 && <button className="small ghost"
              onClick={() => set({ components: p.components.filter((_, j) => j !== i) })}>Remove</button>}
          </div>
        ))}
        {p.components.length < 5 && <button className="small" onClick={() => set({
          components: [...p.components, { kpi: "", weight: 0, target_value: null, tiers: DEFAULT_TIERS }] })}>
          Add a component</button>}
      </fieldset>
      <fieldset className="bn-fieldset">
        <legend>People on the plan</legend>
        {choices.members.map((m) => {
          const row = p.people.find((x) => x.membership === m.membership);
          return (
            <div key={m.membership} className="bn-person-row">
              <label className="check"><input type="checkbox" checked={onPlan.has(m.membership)}
                onChange={(e) => set({ people: e.target.checked
                  ? [...p.people, { membership: m.membership, amount: null, joined_on: null, left_on: null }]
                  : p.people.filter((x) => x.membership !== m.membership) })} /> {m.name}</label>
              {row && <>
                <label>Own amount<input inputMode="decimal" placeholder="the plan's" value={row.amount ?? ""}
                  onChange={(e) => set({ people: p.people.map((x) => (x === row ? { ...x, amount: e.target.value || null } : x)) })} /></label>
                <label>Joined part-way<input type="date" value={row.joined_on ?? ""}
                  onChange={(e) => set({ people: p.people.map((x) => (x === row ? { ...x, joined_on: e.target.value || null } : x)) })} /></label>
              </>}
            </div>
          );
        })}
      </fieldset>
      <div className="row tight">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          {p.id ? "Save the plan" : "Make the plan"}</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

export { BONUS_VIEW_LABEL };
