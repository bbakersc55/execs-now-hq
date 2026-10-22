import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Banner } from "../components/ui";
import { Me, api } from "../lib/api";
import {
  BulkSheet, CADENCE_NOUN, Cadence, EntryForm, EntryKpi, fmt, targetText, unitLabel,
} from "../lib/scorecard";
import { useWords } from "../lib/words";
import { scorecardPath } from "./Scorecard";

const keyOf = (kpi: string, period: string, membership: string | null) =>
  `${kpi}|${period}|${membership ?? ""}`;

interface SaveResult { saved: number; changed: number; errors: Record<string, string> }

/**
 * Enter readings (M5 part 1; docs/design/kpi_scorecard/Entry.dc.html). One
 * form for the period: every KPI the person may enter, in page order, with
 * its unit and last period's value; per-person KPIs as one row per person
 * they cover. "Catch up on several weeks" is the bulk table, periods across.
 */
export function ScorecardEntry({ me }: { me: Me }) {
  const { id } = useParams();
  const companyId = id ?? me.client_company ?? "";
  const w = useWords();
  const qc = useQueryClient();
  const [day, setDay] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const [bulk, setBulk] = useState(false);
  const back = scorecardPath(me, companyId);

  const params = new URLSearchParams({ company: companyId });
  if (day) params.set("day", day);
  const form = useQuery<EntryForm>({
    queryKey: ["scorecard-entry", companyId, day],
    queryFn: () => api.get<EntryForm>(`/api/scorecard/entry/?${params}`),
  });
  const save = useMutation({
    mutationFn: (readings: { kpi: string; period_start: string; membership: string | null; value: string }[]) =>
      api.post<SaveResult>("/api/scorecard/readings/", { company: companyId, readings }),
    onSuccess: (r) => {
      setErrors({});
      setValues({});
      setNote({ kind: "ok", text: r.saved + r.changed === 0 ? "Nothing to save: no value changed."
        : `Saved ${r.saved + r.changed} reading${r.saved + r.changed === 1 ? "" : "s"}`
          + (r.changed ? `, ${r.changed} replacing an earlier value (kept in its history).` : ".") });
      qc.invalidateQueries({ queryKey: ["scorecard-entry", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard-bulk", companyId] });
    },
    onError: (e: Error) => {
      const body = (e as { data?: SaveResult }).data;
      if (body?.errors) { setErrors(body.errors); setNote({ kind: "bad", text: "Nothing was saved. Fix the fields marked below." }); }
      else setNote({ kind: "bad", text: e.message });
    },
  });

  if (form.isError) return <Banner kind="bad">{(form.error as Error).message}</Banner>;
  const f = form.data;
  if (!f) return <p>Loading…</p>;

  const company = f.kpis.filter((k) => !k.per_person);
  const personal = f.kpis.filter((k) => k.per_person);
  const people = new Map<string, { name: string; you: boolean }>();
  personal.forEach((k) => k.fields.forEach((x) => {
    if (x.membership) people.set(x.membership, { name: x.name, you: x.you });
  }));
  const set = (key: string, value: string) => setValues({ ...values, [key]: value });
  const submit = () => {
    const readings = f.kpis.flatMap((k) => k.fields.map((x) => ({
      kpi: k.id, period_start: k.period_start, membership: x.membership,
      value: values[keyOf(k.id, k.period_start, x.membership)] ?? "",
    }))).filter((r) => r.value.trim() !== "");
    save.mutate(readings);
  };
  const shown = (k: EntryKpi, x: EntryKpi["fields"][number]) => {
    const key = keyOf(k.id, k.period_start, x.membership);
    return values[key] ?? (x.value === null ? "" : String(x.value));
  };
  const noun = (k: EntryKpi) => CADENCE_NOUN[k.cadence as Cadence];

  return (
    <div className="sc-page">
      <div className="sc-context"><Link to={back}>{w.Scorecard}</Link> › Enter readings ·
        {" "}Signed in as {me.full_name || me.email}{me.portal?.level_label ? `, ${me.portal.level_label}` : ""}</div>
      <div className="sc-head">
        <div className="sc-head-text">
          <h1>Enter readings</h1>
          <div className="sc-sub">Only the {w.kpis} you're responsible for are listed. Last period's value
            sits beside each field.</div>
        </div>
        <div className="sc-controls">
          <label htmlFor="sc-period" className="sc-muted">Period</label>
          <select id="sc-period" className="sc-select" value={day || f.period.day}
            onChange={(e) => { setDay(e.target.value); setValues({}); setErrors({}); setNote(null); }}>
            {f.choices.map((c, i) => (
              <option key={c.day} value={c.day}>
                {c.label.charAt(0).toUpperCase() + c.label.slice(1)}{i === 0 && f.period.open ? " (open)" : ""}</option>
            ))}
          </select>
          <button className="linklike" onClick={() => setBulk(!bulk)}>
            {bulk ? "Back to one period" : "Catch up on several weeks"}</button>
        </div>
      </div>
      {note && <div role={note.kind === "ok" ? "status" : "alert"}><Banner kind={note.kind}>{note.text}</Banner></div>}

      {bulk ? <BulkTable companyId={companyId} /> : (
        <div className="sc-entry">
          <form className="sc-entry-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
            {f.kpis.length === 0 && <section className="sc-tile"><p className="sc-empty">
              There are no readings for you to enter for this period.</p></section>}
            {company.length > 0 && (
              <section className="sc-tile sc-entry-section" aria-label={`Company ${w.kpis} you enter`}>
                <div className="sc-entry-title">Company {w.kpis} you enter</div>
                {company.map((k) => {
                  const x = k.fields[0];
                  const key = keyOf(k.id, k.period_start, null);
                  const unit = unitLabel(k);
                  return (
                    <div key={k.id} className="sc-entry-line">
                      <label htmlFor={`f-${k.id}`}>
                        <span className="sc-entry-name">{k.name}</span>
                        {x.edited && <span className="sc-edited"> edited</span>}
                        <span className="sc-muted"> · {k.note || targetText(k, k.target)}
                          {k.cadence !== "weekly" ? ` · ${k.period_label}` : ""}</span>
                      </label>
                      <div className={`sc-input${errors[key] ? " bad" : ""}`}>
                        <input id={`f-${k.id}`} type="text" inputMode="decimal" value={shown(k, x)}
                          aria-invalid={!!errors[key]} onChange={(e) => set(key, e.target.value)} />
                        {unit && <span className="sc-input-unit">{unit}</span>}
                      </div>
                      <div className="sc-muted">last {noun(k)} {fmt(k, x.last)}</div>
                      {errors[key] && <div className="sc-field-error" role="alert">{errors[key]}</div>}
                    </div>
                  );
                })}
              </section>
            )}
            {personal.length > 0 && (
              <section className="sc-tile sc-entry-section" aria-label="Readings per person">
                <div className="sc-entry-title-row">
                  <div className="sc-entry-title">Readings per person</div>
                  <div className="sc-muted">One row per person · each person sees only their own row on
                    the {w.scorecard}</div>
                </div>
                <div className="sc-scroll">
                  <table className="sc-entry-table">
                    <thead><tr><th scope="col">Person</th>
                      {personal.map((k) => (
                        <th key={k.id} scope="col">{k.name} <span className="sc-th-note">
                          · {unitLabel(k) || k.kind}, {targetText(k, k.target)}</span></th>
                      ))}</tr></thead>
                    <tbody>
                      {[...people.entries()].map(([m, who]) => (
                        <tr key={m}>
                          <th scope="row">{who.name}{who.you && <span className="sc-muted"> (you)</span>}</th>
                          {personal.map((k) => {
                            const x = k.fields.find((y) => y.membership === m);
                            if (!x) return <td key={k.id} className="sc-muted">—</td>;
                            const key = keyOf(k.id, k.period_start, m);
                            return (
                              <td key={k.id}>
                                <div className="sc-person-cell">
                                  <input type="text" inputMode="decimal" className={errors[key] ? "bad" : ""}
                                    aria-label={`${who.name} ${k.name}`} aria-invalid={!!errors[key]}
                                    value={shown(k, x)} onChange={(e) => set(key, e.target.value)} />
                                  <span className="sc-muted">last {fmt(k, x.last)}</span>
                                </div>
                                {errors[key] && <div className="sc-field-error" role="alert">{errors[key]}</div>}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            {f.kpis.length > 0 && (
              <div className="sc-entry-actions">
                <button type="submit" className="sc-save" disabled={save.isPending}>
                  {save.isPending ? "Saving…" : "Save readings"}</button>
                <Link to={back}>Cancel</Link>
                <span className="sc-muted">Saving again replaces a value and keeps the earlier one in its
                  history, with who changed it.</span>
              </div>
            )}
          </form>
          <aside className="sc-entry-aside" aria-label="This period">
            <section className="sc-tile">
              <div className="sc-entry-title">This week, across the company</div>
              <div className="sc-progress-list">
                {f.progress.map((p) => (
                  <div key={p.id} className="sc-progress-line">
                    <span>{p.name}</span>
                    <span className={`sc-state-${p.state}`}>
                      {p.state === "yours" ? "Yours, above" : p.state === "in"
                        ? `In${p.owner ? ` · ${p.owner.split(" ")[0]}` : ""}`
                        : `Waiting${p.owner ? ` · ${p.owner.split(" ")[0]}` : ""}`}</span>
                  </div>
                ))}
              </div>
              <div className="sc-aside-note">The week closes at the end of {f.period.week_start === "sunday"
                ? "Saturday" : "Sunday"}. Anyone still waiting gets one reminder the next morning.</div>
            </section>
            {f.kpis.some((k) => k.note) && (
              <section className="sc-tile">
                <div className="sc-entry-title">How these are measured</div>
                {f.kpis.filter((k) => k.note).map((k) => (
                  <div key={k.id} className="sc-measure"><strong>{k.name}.</strong> {k.note}</div>
                ))}
              </section>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

/** Periods across, KPIs down, for catching up; the same rules as the form. */
function BulkTable({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [cadence, setCadence] = useState<Cadence>("weekly");
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  const sheet = useQuery<BulkSheet>({
    queryKey: ["scorecard-bulk", companyId, cadence],
    queryFn: () => api.get<BulkSheet>(`/api/scorecard/bulk/?company=${companyId}&cadence=${cadence}&count=6`),
  });
  const save = useMutation({
    mutationFn: (readings: unknown[]) => api.post<SaveResult>("/api/scorecard/readings/",
      { company: companyId, readings }),
    onSuccess: (r) => {
      setValues({}); setErrors({});
      setNote({ kind: "ok", text: `Saved ${r.saved + r.changed} reading${r.saved + r.changed === 1 ? "" : "s"}.` });
      qc.invalidateQueries({ queryKey: ["scorecard-bulk", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard-entry", companyId] });
    },
    onError: (e: Error) => {
      const body = (e as { data?: SaveResult }).data;
      if (body?.errors) { setErrors(body.errors); setNote({ kind: "bad", text: "Nothing was saved. Fix the cells marked below." }); }
      else setNote({ kind: "bad", text: e.message });
    },
  });
  const s = sheet.data;
  return (
    <section className="sc-tile" aria-label="Catch up">
      <div className="sc-entry-title-row">
        <div className="sc-entry-title">Catch up on several periods</div>
        <select aria-label="Cadence" className="sc-select" value={cadence}
          onChange={(e) => { setCadence(e.target.value as Cadence); setValues({}); }}>
          <option value="daily">Daily</option><option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option>
        </select>
      </div>
      {note && <div role={note.kind === "ok" ? "status" : "alert"}><Banner kind={note.kind}>{note.text}</Banner></div>}
      {!s ? <p>Loading…</p> : s.lines.length === 0 ? <p className="sc-empty">Nothing of this cadence for you to enter.</p> : (
        <>
          <div className="sc-scroll">
            <table className="sc-entry-table">
              <thead><tr><th scope="col">KPI</th>{s.periods.map((p) => <th key={p.start} scope="col">{p.label}</th>)}</tr></thead>
              <tbody>
                {s.lines.map((l) => (
                  <tr key={`${l.id}-${l.membership ?? ""}`}>
                    <th scope="row">{l.name}{l.person && <span className="sc-muted"> · {l.person}</span>}</th>
                    {l.cells.map((c) => {
                      const key = keyOf(l.id, c.period_start, l.membership);
                      return (
                        <td key={c.period_start}>
                          <input type="text" inputMode="decimal" className={errors[key] ? "bad" : ""}
                            aria-label={`${l.name}${l.person ? `, ${l.person}` : ""}, ${c.period_start}`}
                            value={values[key] ?? (c.value === null ? "" : String(c.value))}
                            onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
                          {errors[key] && <div className="sc-field-error" role="alert">{errors[key]}</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="sc-entry-actions">
            <button className="sc-save" disabled={save.isPending} onClick={() => save.mutate(
              Object.entries(values).filter(([, v]) => v.trim() !== "").map(([k, v]) => {
                const [kpi, period_start, membership] = k.split("|");
                return { kpi, period_start, membership: membership || null, value: v };
              }))}>Save readings</button>
          </div>
        </>
      )}
    </section>
  );
}
