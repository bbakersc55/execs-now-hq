import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "./shell";
import { Banner } from "./ui";
import { api } from "../lib/api";
import { FeedPreview, FeedState, SheetGrid, columnLetter } from "../lib/scorecard";

type Mode = "column" | "cell";
type Pick = "date" | "value" | "name";

/**
 * The Google Sheet feed for one KPI (M5 part 3, spec "Feeds"): the practice
 * pastes the spreadsheet's address, picks the tab, and either clicks the
 * date and number columns (and the names, for a per-person KPI) or the one
 * cell that holds the number. Nothing is saved until the preview has shown
 * which readings would be made for which periods.
 */
export function SheetFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<FeedState>({
    queryKey: ["scorecard-feed", companyId, kpiId],
    queryFn: () => api.get<FeedState>(`/api/scorecard/feeds/?company=${companyId}&kpi=${kpiId}`),
  });
  const s = state.data;
  const title = s ? `Feed ${s.kpi.name} from a Google Sheet` : "Google Sheet feed";
  return (
    <Modal label={title} title={title} wide onClose={onClose}>
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      {!s ? <p>Loading…</p> : !s.google.ready ? <Reconnect s={s} companyId={companyId} /> : (
        <FeedForm s={s} companyId={companyId} onClose={onClose} onSaved={(text) => {
          qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
          qc.invalidateQueries({ queryKey: ["scorecard-feed", companyId, kpiId] });
          onSaved(text);
        }} />
      )}
    </Modal>
  );
}

function Reconnect({ s, companyId }: { s: FeedState; companyId: string }) {
  const consent = useMutation({
    mutationFn: () => api.post<{ authorization_url: string }>("/api/scorecard/feeds/consent/",
      { company: companyId, kpi: s.kpi.id }),
    onSuccess: (r) => { window.location.assign(r.authorization_url); },
  });
  if (s.google.refusal) return <p className="sc-feed-step">{s.google.refusal}</p>;
  return (
    <div className="sc-feed-step">
      <p>{s.google.reconnect
        ? "Your practice's Google connection was made before the scorecard could read spreadsheets. Reconnect Google to add read-only access to Google Sheets. Sending mail and anything else it already does keep working."
        : "No Google account is connected for this practice yet. Connect Google to read a spreadsheet."}</p>
      <p className="sc-muted">The permission is read-only: the scorecard can open a spreadsheet that has been
        shared with your Google account, and can't change it.</p>
      {consent.isError && <Banner kind="bad">{(consent.error as Error).message}</Banner>}
      <button type="button" disabled={consent.isPending} onClick={() => consent.mutate()}>
        {s.google.reconnect ? "Reconnect Google" : "Connect Google"}</button>
    </div>
  );
}

function FeedForm({ s, companyId, onClose, onSaved }: {
  s: FeedState; companyId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const f = s.feed;
  const [address, setAddress] = useState(f ? `https://docs.google.com/spreadsheets/d/${f.spreadsheet_id}` : "");
  const [grid, setGrid] = useState<SheetGrid | null>(null);
  const [tab, setTab] = useState(f?.tab ?? "");
  const [mode, setMode] = useState<Mode>(f?.mode ?? "column");
  const [cols, setCols] = useState<Record<Pick, { letter: string; header: string }>>({
    date: { letter: f?.date_column ?? "", header: f?.date_header ?? "" },
    value: { letter: f?.value_column ?? "", header: f?.value_header ?? "" },
    name: { letter: f?.name_column ?? "", header: f?.name_header ?? "" },
  });
  const [headerRow, setHeaderRow] = useState<number | null>(f?.header_row ?? null);
  const [cell, setCell] = useState(f?.cell ?? "");
  const [people, setPeople] = useState<Record<string, string>>(f?.people ?? {});
  const [refresh, setRefresh] = useState<"hourly" | "daily">(f?.refresh ?? "daily");
  const [picking, setPicking] = useState<Pick>("date");
  const [preview, setPreview] = useState<FeedPreview | null>(null);
  const [error, setError] = useState("");

  const open = useMutation({
    mutationFn: (pickTab?: string) => api.post<SheetGrid>("/api/scorecard/feeds/open/",
      { company: companyId, kpi: s.kpi.id, spreadsheet: address, tab: pickTab ?? tab }),
    onSuccess: (g) => {
      setGrid(g); setTab(g.tab); setError(""); setPreview(null);
      if (headerRow === null || g.tab !== tab) setHeaderRow(g.header_row);
    },
    onError: (e: Error) => { setGrid(null); setError(e.message); },
  });
  const body = () => ({
    company: companyId, kpi: s.kpi.id, spreadsheet: address, spreadsheet_name: grid?.title ?? f?.spreadsheet_name ?? "",
    tab, mode, refresh, cell, header_row: headerRow, people,
    date_column: cols.date.letter, date_header: cols.date.header,
    value_column: cols.value.letter, value_header: cols.value.header,
    name_column: s.kpi.per_person ? cols.name.letter : "", name_header: s.kpi.per_person ? cols.name.header : "",
  });
  const check = useMutation({
    mutationFn: () => api.post<FeedPreview>("/api/scorecard/feeds/preview/", body()),
    onSuccess: (p) => { setPreview(p); setError(""); if (p.header_row !== undefined) setHeaderRow(p.header_row); },
    onError: (e: Error) => { setPreview(null); setError(e.message); },
  });
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; update?: number; error?: string } }>(
      "/api/scorecard/feeds/", body()),
    onSuccess: (r) => onSaved(r.run.ok
      ? `${s.kpi.name} now reads from the sheet: ${r.run.new ?? 0} new reading${r.run.new === 1 ? "" : "s"}${r.run.update ? `, ${r.run.update} updated` : ""}.`
      : `${s.kpi.name}'s feed is saved, but the first read failed: ${r.run.error}`),
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/feeds/?company=${companyId}&kpi=${s.kpi.id}`),
    onSuccess: () => onSaved(`${s.kpi.name} is entered by hand again. Its readings are kept.`),
    onError: (e: Error) => setError(e.message),
  });

  const roles: Pick[] = s.kpi.per_person ? ["date", "value", "name"] : ["date", "value"];
  const roleWord: Record<Pick, string> = { date: "Dates", value: "Numbers", name: "Names" };
  const headerOf = (col: number) => (grid && headerRow !== null ? grid.rows[headerRow]?.[col] ?? "" : "");
  const chooseColumn = (role: Pick, col: number) => {
    setCols({ ...cols, [role]: { letter: columnLetter(col), header: headerOf(col).trim() } });
    setPreview(null);
    const next = roles[roles.indexOf(role) + 1];
    if (next) setPicking(next);
  };
  const roleOf = (col: number) => (mode === "column"
    ? roles.find((r) => cols[r].letter === columnLetter(col)) : undefined);
  const width = grid ? Math.max(1, ...grid.rows.map((r) => r.length)) : 0;
  const ready = mode === "cell" ? !!cell : roles.every((r) => cols[r].letter);

  return (
    <div className="sc-feed">
      {f && (
        <p className="sc-muted">
          Reading {f.spreadsheet_name ? `“${f.spreadsheet_name}”` : "a spreadsheet"}, tab “{f.tab}”, {f.refresh}.
          {f.last_success_at ? ` Last read ${new Date(f.last_success_at).toLocaleString()}.` : ""}
          {f.last_error && <> <strong>Last read failed:</strong> {f.last_error}</>}
        </p>
      )}
      <div className="sc-feed-step">
        <label htmlFor="sc-feed-sheet">The spreadsheet's address</label>
        <div className="sc-feed-row">
          <input id="sc-feed-sheet" type="text" value={address} placeholder="https://docs.google.com/spreadsheets/d/…"
            onChange={(e) => { setAddress(e.target.value); setGrid(null); setPreview(null); }} />
          <button type="button" disabled={!address.trim() || open.isPending} onClick={() => open.mutate(undefined)}>
            {open.isPending ? "Opening…" : "Open"}</button>
        </div>
        <p className="sc-muted">It is read as {s.google.account}. Whoever owns the sheet shares it with that
          address (Viewer is enough).</p>
      </div>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}

      {grid && (
        <>
          <div className="sc-feed-step sc-feed-row wrap">
            <label htmlFor="sc-feed-tab">Tab of “{grid.title}”</label>
            <select id="sc-feed-tab" className="sc-select" value={tab}
              onChange={(e) => { setTab(e.target.value); open.mutate(e.target.value); }}>
              {grid.tabs.map((t) => <option key={t.id} value={t.title}>{t.title}</option>)}
            </select>
            <fieldset className="sc-feed-modes">
              <legend className="sc-muted">Read it</legend>
              <label><input type="radio" name="sc-feed-mode" checked={mode === "column"}
                onChange={() => { setMode("column"); setPreview(null); }} /> By column (a row per period)</label>
              <label><input type="radio" name="sc-feed-mode" checked={mode === "cell"} disabled={s.kpi.per_person}
                onChange={() => { setMode("cell"); setPreview(null); }} /> From one cell (this period's number)</label>
            </fieldset>
          </div>

          {mode === "column" ? (
            <div className="sc-feed-step sc-feed-row wrap">
              {roles.map((r) => (
                <button key={r} type="button" className={picking === r ? "small" : "ghost small"}
                  aria-pressed={picking === r} onClick={() => setPicking(r)}>
                  {roleWord[r]}: {cols[r].letter ? `${cols[r].letter}${cols[r].header ? ` (${cols[r].header})` : ""}` : "click a column"}
                </button>
              ))}
              <label htmlFor="sc-feed-header" className="sc-muted">Headings in row</label>
              <select id="sc-feed-header" className="sc-select" value={headerRow ?? ""}
                onChange={(e) => {
                  const row = e.target.value === "" ? null : Number(e.target.value);
                  setHeaderRow(row); setPreview(null);
                  setCols(Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, {
                    letter: v.letter, header: v.letter && row !== null && grid
                      ? (grid.rows[row]?.[colIndex(v.letter)] ?? "").trim() : "" }])) as typeof cols);
                }}>
                <option value="">None</option>
                {grid.rows.slice(0, 20).map((_, i) => <option key={i} value={i}>{i + 1}</option>)}
              </select>
            </div>
          ) : (
            <p className="sc-feed-step">Click the cell that holds this period's number{cell ? `: ${cell}` : ""}.
              It is read when each {s.kpi.cadence_noun} closes and kept as that {s.kpi.cadence_noun}'s reading.</p>
          )}

          <div className="sc-scroll sc-feed-grid" role="region" aria-label="The tab's first rows" tabIndex={0}>
            <table>
              <thead>
                <tr><th scope="col" />{Array.from({ length: width }, (_, c) => (
                  <th key={c} scope="col" className={roleOf(c) ? `picked ${roleOf(c)}` : ""}>
                    {mode === "column" ? (
                      <button type="button" className="linklike" aria-label={`Column ${columnLetter(c)} for ${roleWord[picking].toLowerCase()}`}
                        onClick={() => chooseColumn(picking, c)}>{columnLetter(c)}</button>
                    ) : columnLetter(c)}
                    {roleOf(c) && <span className="sc-feed-tag">{roleWord[roleOf(c)!]}</span>}
                  </th>))}</tr>
              </thead>
              <tbody>
                {grid.rows.map((row, r) => (
                  <tr key={r} className={r === headerRow && mode === "column" ? "header" : ""}>
                    <th scope="row">{r + 1}</th>
                    {Array.from({ length: width }, (_, c) => {
                      const ref = `${columnLetter(c)}${r + 1}`;
                      const on = mode === "cell" ? cell === ref : !!roleOf(c);
                      return (
                        <td key={c} className={on ? "picked" : ""}>
                          {mode === "cell" ? (
                            <button type="button" className="sc-feed-cell" aria-label={`Cell ${ref}`}
                              aria-pressed={cell === ref} onClick={() => { setCell(ref); setPreview(null); }}>
                              {row[c] ?? ""}</button>
                          ) : (row[c] ?? "")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {grid.more_rows > 0 && <p className="sc-muted">The tab has {grid.more_rows} more rows below these; all of them are read.</p>}

          <div className="sc-feed-step sc-feed-row wrap">
            {mode === "column" && <>
              <label htmlFor="sc-feed-refresh">Refresh</label>
              <select id="sc-feed-refresh" className="sc-select" value={refresh}
                onChange={(e) => setRefresh(e.target.value as "hourly" | "daily")}>
                <option value="hourly">Every hour</option><option value="daily">Once a day</option>
              </select>
            </>}
            <button type="button" disabled={!ready || check.isPending} onClick={() => check.mutate()}>
              {check.isPending ? "Reading…" : "Show what it would make"}</button>
          </div>
        </>
      )}

      {preview && <Preview p={preview} kpi={s.kpi} people={people} setPeople={(p) => { setPeople(p); setPreview(null); }} />}

      <div className="sc-entry-actions">
        <button type="button" disabled={!preview || save.isPending} onClick={() => save.mutate()}
          title={preview ? "" : "Show what it would make first"}>Save the feed</button>
        <button type="button" className="ghost" onClick={onClose}>Cancel</button>
        {f && <button type="button" className="ghost" disabled={stop.isPending}
          onClick={() => stop.mutate()}>Stop the feed</button>}
      </div>
    </div>
  );
}

function colIndex(letter: string) {
  return letter.toUpperCase().split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
}

function Preview({ p, kpi, people, setPeople }: {
  p: FeedPreview; kpi: FeedState["kpi"]; people: Record<string, string>;
  setPeople: (p: Record<string, string>) => void;
}) {
  const c = p.counts;
  if (p.cell) {
    const when = new Date(`${p.cell.closes}T12:00:00`).toLocaleDateString(undefined,
      { month: "long", day: "numeric" });
    return (
      <section className="sc-feed-preview" aria-label="What it would make">
        <p role="status"><strong>{p.cell.ref} reads {p.cell.value === null ? "nothing (it is blank)" : p.cell.value} now.</strong>{" "}
          When {p.cell.period} closes on {when}, the number in {p.cell.ref} then is kept as its
          reading, and each {kpi.cadence_noun} after the same way. Earlier {kpi.cadence_noun}s are left as they are.</p>
      </section>
    );
  }
  return (
    <section className="sc-feed-preview" aria-label="What it would make">
      <p role="status"><strong>{c.new} new reading{c.new === 1 ? "" : "s"}</strong>
        {c.update ? `, ${c.update} replacing the sheet's earlier value` : ""}
        {c.same ? `, ${c.same} already in` : ""}
        {c.kept ? `, ${c.kept} kept as entered by hand` : ""}
        {c.open ? `, ${c.open} waiting for the period to close` : ""}.
        {p.header_row !== null ? ` Headings found in row ${p.header_row + 1}.` : ""}</p>
      {p.periods.length > 0 && (
        <div className="sc-scroll">
          <table className="sc-back-table">
            <thead><tr><th>Period</th>{kpi.per_person && <th>Person</th>}<th className="money">Reading</th>
              <th>From rows</th><th>What happens</th></tr></thead>
            <tbody>
              {p.periods.map((r) => (
                <tr key={`${r.start}-${r.person}`} className={`sc-feed-${r.what}`}>
                  <td>{r.label.charAt(0).toUpperCase() + r.label.slice(1)}</td>
                  {kpi.per_person && <td>{r.person}</td>}
                  <td className="money">{r.value}</td>
                  <td>{r.rows.join(", ")}</td>
                  <td>{r.says}{r.what === "kept" && r.had !== null ? ` (${r.had})` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {p.more > 0 && <p className="sc-muted">And {p.more} earlier period{p.more === 1 ? "" : "s"}.</p>}
        </div>
      )}
      {p.unmatched.length > 0 && (
        <div className="sc-feed-step">
          <p><strong>Names that match no one on {kpi.name}.</strong> Choose who each one is, or leave it
            and those rows are left out.</p>
          {p.unmatched.map((u) => (
            <div key={u.name} className="sc-feed-row">
              <label htmlFor={`sc-feed-who-${u.name}`}>“{u.name}” ({u.rows} row{u.rows === 1 ? "" : "s"})</label>
              <select id={`sc-feed-who-${u.name}`} className="sc-select" value={people[u.name] ?? ""}
                onChange={(e) => setPeople({ ...people, [u.name]: e.target.value })}>
                <option value="">Leave these rows out</option>
                {kpi.people.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </div>
          ))}
        </div>
      )}
      {p.skipped.length > 0 && (
        <details>
          <summary>{p.skipped.length + p.skipped_more} row{p.skipped.length + p.skipped_more === 1 ? "" : "s"} left out</summary>
          <ul>{p.skipped.map((x) => <li key={x.row}>Row {x.row}: {x.why}</li>)}</ul>
          {p.skipped_more > 0 && <p className="sc-muted">And {p.skipped_more} more.</p>}
        </details>
      )}
    </section>
  );
}
