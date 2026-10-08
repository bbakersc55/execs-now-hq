import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PriceBox } from "../components/InvoiceLines";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { Contact, PayeeReport, api } from "../lib/api";
import { dollars } from "../lib/money";

/**
 * 1099 tracking (P5, owner 2026-10-08): who the practice may owe a 1099, what
 * each was paid in a calendar year, and who is at or over the threshold.
 *
 * A payee is a contact you flag here. An expense names its payee, on the
 * entry or in an import. The practice owner's only, like the rest of the
 * books; the flag shows on no contact screen.
 */
export function FinancePayees() {
  const qc = useQueryClient();
  const [year, setYear] = useState(new Date().getFullYear());
  const [threshold, setThreshold] = useState<number | null>(null);
  const [term, setTerm] = useState("");
  const [said, setSaid] = useState("");
  const query = `?year=${year}${threshold === null ? "" : `&threshold_cents=${threshold}`}`;
  const report = useQuery<PayeeReport>({
    queryKey: ["finance-payees", year, threshold],
    queryFn: () => api.get<PayeeReport>(`/api/finance-payees/${query}`),
    // The last answer stays on screen while the next is fetched, so typing a
    // threshold is not interrupted by the table it is changing.
    placeholderData: keepPreviousData });
  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["contact-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 1 });
  const flag = useMutation({
    mutationFn: (body: { contact: string; is_payee: boolean }) =>
      api.post<PayeeReport>("/api/finance-payees/", body),
    onSuccess: () => { setSaid(""); setTerm(""); qc.invalidateQueries({ queryKey: ["finance-payees"] }); },
    onError: (e: Error) => setSaid(e.message),
  });
  const r = report.data;
  const years = Array.from({ length: 4 }, (_, i) => new Date().getFullYear() - i);
  const flagged = new Set((r?.payees ?? []).filter((p) => p.is_payee).map((p) => p.contact));
  return (
    <Card title="1099 payees"
      actions={<a className="btn small" href={`/api/finance-payees/export/${query}`}>
        Download as CSV</a>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Contractors and others you may owe a 1099 at year end. Each total is the expenses
        you entered as paid to them in the calendar year, less refunds. Payments by credit
        card are shown and left out of the reportable figure, because the card company
        reports those. <strong>Confirm the threshold and the card rule with your CPA</strong>:
        this is a worksheet for them, not a filing.
      </p>
      {said && <Banner kind="bad">{said}</Banner>}
      <div className="row">
        <Field label="Year">
          <select aria-label="Year" value={year} style={{ width: "auto" }}
            onChange={(e) => { setYear(Number(e.target.value)); setThreshold(null); }}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </Field>
        <Field label="Threshold">
          <PriceBox label="Threshold" cents={threshold ?? r?.threshold_cents ?? 0}
            onChange={(cents) => setThreshold(cents)} />
        </Field>
        <Field label="Add a payee">
          <input aria-label="Find a contact to flag as a 1099 payee" value={term}
            placeholder="A name or an email address" onChange={(e) => setTerm(e.target.value)} />
        </Field>
      </div>
      {r && threshold === null && (
        <p className="tiny muted">The threshold shown is this app's default for {r.year}:{" "}
          {dollars(r.default_threshold_cents)} ($600 through 2025, $2,000 from 2026).</p>
      )}
      {term.trim().length > 1 && (
        <p className="small">
          {(found.data?.contacts ?? []).filter((c) => !flagged.has(c.id)).slice(0, 8).map((c) => (
            <button key={c.id} className="small" style={{ marginRight: 6 }}
              disabled={flag.isPending}
              aria-label={`Flag ${c.first_name} ${c.last_name} as a 1099 payee`}
              onClick={() => flag.mutate({ contact: c.id, is_payee: true })}>
              {c.first_name} {c.last_name}</button>
          ))}
          {found.data && found.data.contacts.filter((c) => !flagged.has(c.id)).length === 0
            && <span className="muted">Nobody by that name who is not already a payee.</span>}
        </p>
      )}
      {!r ? <p>Adding up the year…</p> : r.payees.length === 0
        ? <Empty>No 1099 payees yet. Flag a contact above, then name them on the expenses
          you pay them.</Empty> : (
          <table aria-label={`1099 payees for ${r.year}`}>
            <thead><tr><th>Payee</th><th className="money">Paid in {r.year}</th>
              <th className="money">Of which by card</th>
              <th className="money">Reportable</th><th /><th /></tr></thead>
            <tbody>
              {r.payees.map((p) => (
                <tr key={p.contact}>
                  <td>{p.name}{p.company && <span className="muted"> · {p.company}</span>}
                    {!p.is_payee && <> <Pill>no longer flagged</Pill></>}</td>
                  <td className="money">{dollars(p.total_cents)}</td>
                  <td className="money">{p.by_card_cents ? dollars(p.by_card_cents) : ""}</td>
                  <td className="money"><strong>{dollars(p.reportable_cents)}</strong></td>
                  <td>{p.over_threshold && <Pill kind="warn">at or over the threshold</Pill>}</td>
                  <td className="money">{p.is_payee && (
                    <button className="ghost small" disabled={flag.isPending}
                      aria-label={`Remove the 1099 flag from ${p.name}`}
                      onClick={() => flag.mutate({ contact: p.contact, is_payee: false })}>
                      Unflag</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      {r && r.payees.length > 0 && (
        <p className="small">{r.over === 0 ? "Nobody is" : r.over === 1 ? "One payee is"
          : `${r.over} payees are`} at or over {dollars(r.threshold_cents)} for {r.year}.</p>
      )}
    </Card>
  );
}
