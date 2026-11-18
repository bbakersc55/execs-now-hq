import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "./shell";
import { Banner, Field } from "./ui";
import { api } from "../lib/api";

/**
 * "Set up KPIs from a sheet" (2026-11-17): open a Google Sheet through the
 * practice's Google connection, choose its tab, the date column and whether
 * its dates are the first or the last day of each period; every other column
 * is proposed as a KPI (its name, unit, cadence, direction and roll-up), to
 * rename, skip or change, put on a page (an existing one or a new one with its
 * audience), and make all at once, each with a Sheets feed on its own column.
 * Ends with what was made and what was skipped, and why.
 */

export interface SheetColumn {
  column: string; header: string; name: string; kind: "number" | "percent" | "money";
  cadence: string; direction: string; rollup: string; numbers: number; blanks: number;
  not_numbers: number; sample: string[]; skip: boolean; why_skip: string;
}

export interface SheetProposal {
  header_row: number | null; date_column: string; date_header: string;
  date_is: "" | "start" | "end"; cadence: string;
  dates: { count: number; first: string; last: string };
  columns: SheetColumn[]; skipped: { column: string; reason: string }[];
  already: { column: string; header: string; kpi: string }[];
  pages: { id: string; name: string; audience: string; audience_label: string }[];
}

interface Opened {
  spreadsheet_id: string; title: string; tabs: { title: string; id: number }[]; tab: string;
  account: string; rows: string[][]; proposal: SheetProposal | null; problem: string;
}

interface Summary {
  created: { id: string; name: string; page: string }[]; readings: number; blank_cells: number;
  cells_skipped: { why: string; count: number }[];
  columns_skipped: { column: string; reason: string }[];
  already: { column: string; header: string; kpi: string }[];
  failed: { kpi: string; error: string }[];
}

type Choice = SheetColumn & { page: string };
type NewPage = { key: string; name: string; audience: string };

const KINDS = { number: "Number", percent: "Percent", money: "Money" };
const CADENCES = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly" };
const DIRECTIONS = { higher: "Higher is better", lower: "Lower is better" };
const ROLLUPS = { sum: "Sum", average: "Average", last: "Last" };
const AUDIENCES = { everyone: "Everyone at the company", leadership: "Senior leadership and up",
  each_person: "Each person sees their own" };
const DATE_IS = { end: "The last day of each period", start: "The first day of each period",
  "": "A day in the period" };

function select<T extends Record<string, string>>(label: string, value: string, options: T,
  onChange: (v: string) => void) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {Object.entries(options).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

export function SheetSetup({ companyId, onClose, onMade }: {
  companyId: string; onClose: () => void; onMade: () => void;
}) {
  const [address, setAddress] = useState("");
  const [opened, setOpened] = useState<Opened | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [pages, setPages] = useState<NewPage[]>([]);
  const [newName, setNewName] = useState("");
  const [newAudience, setNewAudience] = useState("everyone");
  const [summary, setSummary] = useState<Summary | null>(null);

  const open = useMutation({
    mutationFn: (more: Record<string, unknown>) => api.post<Opened>(
      "/api/scorecard/sheet-setup/open/", { company: companyId, spreadsheet: address, ...more }),
    onSuccess: (data) => {
      setOpened(data);
      const first = data.proposal?.pages[0]?.id ?? "";
      setChoices((data.proposal?.columns ?? []).map((c) => ({ ...c, page: first })));
    },
  });
  const make = useMutation({
    mutationFn: () => {
      const p = opened!.proposal!;
      return api.post<Summary>("/api/scorecard/sheet-setup/", {
        company: companyId, spreadsheet: address, spreadsheet_name: opened!.title,
        tab: opened!.tab, header_row: p.header_row, date_column: p.date_column,
        date_is: p.date_is, new_pages: pages,
        columns: choices.map((c) => ({
          column: c.column, header: c.header, name: c.name, kind: c.kind, cadence: c.cadence,
          direction: c.direction, rollup: c.rollup, skip: c.skip,
          ...(c.page.startsWith("new:") ? { new_page: c.page.slice(4) } : { page: c.page }),
        })),
      });
    },
    onSuccess: (data) => { setSummary(data); onMade(); },
  });
  const reopen = (more: Record<string, unknown>) => {
    const p = opened?.proposal;
    open.mutate({ tab: opened?.tab, header_row: p?.header_row, date_column: p?.date_column,
                  date_is: p?.date_is, ...more });
  };
  const change = (i: number, patch: Partial<Choice>) =>
    setChoices(choices.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const making = choices.filter((c) => !c.skip);
  const pageOptions: Record<string, string> = {
    ...Object.fromEntries((opened?.proposal?.pages ?? []).map((p) => [p.id, p.name])),
    ...Object.fromEntries(pages.map((p) => [`new:${p.key}`, `${p.name} (new)`])),
  };

  return (
    <Modal title="Set up KPIs from a sheet" label="Set up KPIs from a sheet" wide
      onClose={onClose}>
      {summary ? <Done summary={summary} onClose={onClose} /> : (
        <>
          <form className="row tight" aria-label="Open a Google Sheet"
            onSubmit={(e) => { e.preventDefault(); setOpened(null); open.mutate({}); }}>
            <Field label="The sheet's address">
              <input aria-label="The sheet's address" value={address}
                placeholder="https://docs.google.com/spreadsheets/d/…"
                onChange={(e) => setAddress(e.target.value)} />
            </Field>
            <button className="primary small" type="submit" disabled={!address || open.isPending}>
              {open.isPending ? "Opening…" : "Open the sheet"}</button>
          </form>
          {open.isError && <Banner kind="bad">{(open.error as Error).message}</Banner>}
          {opened && (
            <>
              <p className="small muted">{opened.title}, through {opened.account}.</p>
              <div className="row tight" style={{ flexWrap: "wrap" }}>
                <Field label="Tab">
                  <select aria-label="Tab" value={opened.tab}
                    onChange={(e) => reopen({ tab: e.target.value, date_column: "",
                                              date_is: undefined, header_row: undefined })}>
                    {opened.tabs.map((t) => <option key={t.id} value={t.title}>{t.title}</option>)}
                  </select>
                </Field>
                {opened.proposal && <Field label="Date column">
                  <select aria-label="Date column" value={opened.proposal.date_column}
                    onChange={(e) => reopen({ date_column: e.target.value, date_is: undefined })}>
                    {(opened.rows[opened.proposal.header_row ?? 0] ?? []).map((h, i) => {
                      const letter = columnLetter(i);
                      return <option key={letter} value={letter}>{letter}{h ? `: ${h}` : ""}</option>;
                    })}
                  </select>
                </Field>}
                {opened.proposal && <Field label="Its dates are">
                  {select("Its dates are", opened.proposal.date_is, DATE_IS,
                          (v) => reopen({ date_is: v }))}
                </Field>}
              </div>
              {opened.problem && <Banner kind="bad">{opened.problem}</Banner>}
            </>
          )}
          {opened?.proposal && (
            <>
              <p className="small">
                {opened.proposal.dates.count} dates, {opened.proposal.dates.first} to{" "}
                {opened.proposal.dates.last}: {CADENCES[opened.proposal.cadence as keyof typeof
                CADENCES] ?? opened.proposal.cadence}. A blank cell is no reading, never zero.</p>
              {opened.proposal.skipped.map((s) => (
                <p key={s.column} className="small muted">Column {s.column}: {s.reason}</p>))}
              {opened.proposal.already.length > 0 && (
                <p className="small muted">Already set up: {opened.proposal.already.map(
                  (a) => `${a.column} (${a.kpi})`).join(", ")}.</p>)}
              <fieldset className="row tight" style={{ flexWrap: "wrap" }}>
                <legend className="small">New pages</legend>
                {pages.map((p) => <span key={p.key} className="small">{p.name} ·{" "}
                  {AUDIENCES[p.audience as keyof typeof AUDIENCES]}</span>)}
                <input aria-label="New page name" placeholder="New page, e.g. Money"
                  value={newName} onChange={(e) => setNewName(e.target.value)} />
                {select("New page audience", newAudience, AUDIENCES, setNewAudience)}
                <button type="button" className="small" disabled={!newName.trim()}
                  onClick={() => {
                    setPages([...pages, { key: `p${pages.length + 1}`, name: newName.trim(),
                                          audience: newAudience }]);
                    setNewName("");
                  }}>Add the page</button>
                <Field label="Put every KPI on">
                  {select("Put every KPI on", "", { "": "Choose a page", ...pageOptions },
                          (v) => v && setChoices(choices.map((c) => ({ ...c, page: v }))))}
                </Field>
              </fieldset>
              {choices.length === 0 ? <p>Every column with a header is set up already.</p> : (
                <div className="table-fit">
                  <table aria-label="Columns proposed as KPIs" className="small">
                    <thead><tr><th>Make it</th><th>Column</th><th>Name</th><th>Unit</th>
                      <th>Cadence</th><th>Direction</th><th>Roll-up</th><th>Page</th>
                      <th>In the sheet</th></tr></thead>
                    <tbody>
                      {choices.map((c, i) => (
                        <tr key={c.column}>
                          <td><input type="checkbox" checked={!c.skip}
                            aria-label={`Make ${c.header}`}
                            onChange={(e) => change(i, { skip: !e.target.checked })} /></td>
                          <td>{c.column}</td>
                          <td><input aria-label={`Name for ${c.header}`} value={c.name}
                            onChange={(e) => change(i, { name: e.target.value })} />
                            {c.why_skip && <div className="small muted">{c.why_skip}</div>}</td>
                          <td>{select(`Unit for ${c.header}`, c.kind, KINDS,
                                      (v) => change(i, { kind: v as Choice["kind"] }))}</td>
                          <td>{select(`Cadence for ${c.header}`, c.cadence, CADENCES,
                                      (v) => change(i, { cadence: v }))}</td>
                          <td>{select(`Direction for ${c.header}`, c.direction, DIRECTIONS,
                                      (v) => change(i, { direction: v }))}</td>
                          <td>{select(`Roll-up for ${c.header}`, c.rollup, ROLLUPS,
                                      (v) => change(i, { rollup: v }))}</td>
                          <td>{select(`Page for ${c.header}`, c.page, pageOptions,
                                      (v) => change(i, { page: v }))}</td>
                          <td className="muted">{c.numbers} numbers{c.blanks ? `, ${c.blanks} blank`
                            : ""}{c.sample.length ? ` · last ${c.sample[c.sample.length - 1]}` : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {make.isError && <Banner kind="bad">{(make.error as Error).message}</Banner>}
              <div className="row tight">
                <button className="primary" disabled={!making.length || make.isPending
                  || making.some((c) => !c.page || !c.name.trim())}
                  onClick={() => make.mutate()}>
                  {make.isPending ? "Making them…" : `Make ${making.length} KPI${
                    making.length === 1 ? "" : "s"}`}</button>
                <button className="ghost" onClick={onClose}>Cancel</button>
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

function columnLetter(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function Done({ summary, onClose }: { summary: Summary; onClose: () => void }) {
  return (
    <div role="status" aria-label="What was set up">
      <p><strong>{summary.created.length} KPI{summary.created.length === 1 ? "" : "s"} made, {
        summary.readings} reading{summary.readings === 1 ? "" : "s"} loaded.</strong> New rows
        arrive with the nightly read.</p>
      {summary.blank_cells > 0 && (
        <p className="small">{summary.blank_cells} blank cell{summary.blank_cells === 1 ? "" : "s"}:
          no reading for those periods, never zero.</p>)}
      {summary.cells_skipped.length > 0 && (
        <ul aria-label="Cells skipped" className="small">
          {summary.cells_skipped.map((c) => <li key={c.why}>{c.count} × {c.why}</li>)}
        </ul>)}
      {summary.columns_skipped.length > 0 && (
        <ul aria-label="Columns skipped" className="small">
          {summary.columns_skipped.map((c) => <li key={c.column}>Column {c.column}: {c.reason}</li>)}
        </ul>)}
      {summary.already.length > 0 && (
        <p className="small muted">{summary.already.length} column{summary.already.length === 1
          ? " was" : "s were"} set up already, and not made again.</p>)}
      {summary.failed.map((f) => <Banner key={f.kpi} kind="bad">{f.kpi}: {f.error}</Banner>)}
      <button className="primary" onClick={onClose}>Done</button>
    </div>
  );
}
