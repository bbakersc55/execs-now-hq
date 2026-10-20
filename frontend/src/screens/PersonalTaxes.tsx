import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { CpaPage, PayYourself, TaxEstimate, TaxInputs, api } from "../lib/api";
import { dollars, longDate, toCents } from "../lib/money";
import { PERSONAL_DISCLAIMER } from "../lib/personal";

/**
 * P6 M4 stop 4 (`docs/p6_m4_personal_finance.md`, decisions 20–23): paying
 * yourself, the quarterly tax set-aside and For your CPA with both sides.
 * Every figure is the server's arithmetic on the owner's own inputs and
 * books: an estimate, never advice, and the Taxes page says so in bold.
 */

const CONFIRM = "Estimate; confirm with your CPA.";

/** Whole dollars when there are no cents: "$820", "$1,380", "$12.50". */
function money(cents: number | null | undefined) {
  if (cents === null || cents === undefined) return "—";
  const text = dollars(cents);
  return text.endsWith(".00") ? text.slice(0, -3) : text;
}

const asText = (cents: number | null | undefined) =>
  cents === null || cents === undefined ? "" : (cents / 100).toFixed(cents % 100 ? 2 : 0);

type Said = { kind: string; text: string } | null;

function Confirm() {
  return <p className="small" style={{ margin: "var(--s2) 0 0" }}><strong>{CONFIRM}</strong></p>;
}

// ============================================================ the Taxes page

export function PersonalTaxes() {
  const qc = useQueryClient();
  const [year, setYear] = useState<number | null>(null);
  const [said, setSaid] = useState<Said>(null);
  const found = useQuery<TaxEstimate>({
    queryKey: ["personal-taxes", year],
    queryFn: () => api.get<TaxEstimate>(`/api/personal/taxes${year ? `?year=${year}` : ""}`) });
  const act = useMutation({
    mutationFn: ({ what, body }: { what: string; body: object }) =>
      api.post<TaxEstimate>(`/api/personal/taxes/${what}`, { year: found.data?.year, ...body }),
    onSuccess: (data, { what }) => {
      qc.setQueryData(["personal-taxes", year], data);
      for (const key of ["personal-budget", "personal-pay-yourself", "personal-cpa"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      setSaid({ kind: "ok", text: what === "inputs" ? "Saved. The estimate is worked out again."
        : what === "envelope" ? "The Tax envelope is in your budget." : "Saved." });
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }) });
  const send = (what: string, body: object) => act.mutate({ what, body });
  const data = found.data;
  if (found.isError) return <Banner kind="bad">{(found.error as Error).message}</Banner>;
  if (!data) return <p>Loading…</p>;
  return (
    <>
      <p role="note" aria-label="Taxes disclaimer" style={{ marginTop: 0 }}>
        <strong>{PERSONAL_DISCLAIMER}</strong></p>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
        <label className="small inline">Tax year
          <select aria-label="Tax year" value={data.year} style={{ width: "auto" }}
            onChange={(e) => setYear(Number(e.target.value))}>
            {[data.year + 1, data.year, data.year - 1]
              .filter((y, i, all) => all.indexOf(y) === i)
              .map((y) => <option key={y} value={y}>{y}</option>)}
          </select></label>
      </div>
      <TaxInputsCard data={data} busy={act.isPending}
        onSave={(body) => send("inputs", body)} />
      {!data.ready ? (
        <Card title={`Personal: taxes, ${data.year}`}>
          <Empty>To work out the estimate, enter {data.missing.join(" and ")} above.</Empty>
        </Card>
      ) : (
        <>
          <EstimateCard data={data} />
          <QuartersCard data={data} />
          <SetAsideCard data={data} busy={act.isPending} send={send} />
        </>
      )}
      <PaymentsCard data={data} />
    </>
  );
}

const MONEY_INPUTS: [keyof TaxInputs, string, string][] = [
  ["last_year_tax_cents", "Last year's total tax", "From last year's return"],
  ["last_year_taxable_cents", "Last year's taxable income", "From last year's return"],
  ["other_income_cents", "Other household income this year",
   "Before withholding: a spouse's wages, interest. Empty: from your income lines"],
];

function TaxInputsCard({ data, busy, onSave }: {
  data: TaxEstimate; busy: boolean; onSave: (body: object) => void;
}) {
  const i = data.inputs;
  const start = () => ({
    filing_status: i.filing_status, state: i.state, state_rate: i.state_rate_percent ?? "",
    rate: i.effective_rate_percent ?? "",
    last_year_tax_cents: asText(i.last_year_tax_cents),
    last_year_taxable_cents: asText(i.last_year_taxable_cents),
    other_income_cents: asText(i.other_income_cents), qbi: i.qbi ?? "",
  });
  const [draft, setDraft] = useState(start);
  useEffect(() => { setDraft(start()); }, [data.year]);  // eslint-disable-line
  const set = (name: string, value: string) => setDraft({ ...draft, [name]: value });
  const cents = (text: string) => (text.trim() === "" ? null : toCents(text));
  const bad = MONEY_INPUTS.some(([name]) => {
    const text = draft[name as keyof typeof draft] as string;
    return text.trim() !== "" && toCents(text) === null;
  });
  return (
    <Card title={`Personal: what the estimate uses, ${data.year}`}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Entered once a year. Last year's figures come from last year's return; or give
        only the rate your federal income tax came to, and it is used instead of the
        brackets. The spouse's expected withholding is kept under{" "}
        <Link to="/finance/personal/household">Household</Link>
        {data.withholding_cents ? ` (${money(data.withholding_cents)} this year)` : ""}.
      </p>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <Field label="Filing status">
          <select aria-label="Filing status" value={draft.filing_status}
            onChange={(e) => set("filing_status", e.target.value)}>
            <option value="">Choose…</option>
            {Object.entries(data.statuses).map(([code, label]) => (
              <option key={code} value={code}>{label}</option>))}
          </select>
        </Field>
        <Field label="State">
          <input aria-label="State" value={draft.state} maxLength={2} style={{ width: "4rem" }}
            placeholder="CO" onChange={(e) => set("state", e.target.value.toUpperCase())} />
        </Field>
        <Field label="State rate, %">
          <input aria-label="State rate" value={draft.state_rate} style={{ width: "5rem" }}
            placeholder="4.4" onChange={(e) => set("state_rate", e.target.value)} />
        </Field>
        <Field label="QBI deduction">
          <select aria-label="QBI deduction" value={draft.qbi}
            onChange={(e) => set("qbi", e.target.value)}>
            <option value="">None</option>
            <option value="20">20% of net profit</option>
          </select>
          <div className="tiny muted" style={{ maxWidth: "16rem" }}>Consulting is a specified
            service; the deduction phases out above an income threshold. Ask your CPA.</div>
        </Field>
        <Field label="Or a federal rate, %">
          <input aria-label="Effective federal rate" value={draft.rate}
            style={{ width: "5rem" }} placeholder="none"
            onChange={(e) => set("rate", e.target.value)} />
        </Field>
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {MONEY_INPUTS.map(([name, label, hint]) => (
          <Field key={name} label={label}>
            <input aria-label={label} value={draft[name as keyof typeof draft] as string}
              inputMode="decimal" placeholder="0" style={{ width: "9rem" }}
              onChange={(e) => set(name, e.target.value)} />
            <div className="tiny muted">{hint}</div>
          </Field>
        ))}
      </div>
      <button className="primary small" disabled={busy || bad}
        onClick={() => onSave({
          filing_status: draft.filing_status, state: draft.state,
          state_rate_percent: draft.state_rate.trim() || null,
          effective_rate_percent: draft.rate.trim() || null,
          last_year_tax_cents: cents(draft.last_year_tax_cents),
          last_year_taxable_cents: cents(draft.last_year_taxable_cents),
          other_income_cents: cents(draft.other_income_cents), qbi: draft.qbi,
        })}>Save</button>
      {bad && <span className="small" style={{ color: "var(--bad)" }}> An amount is
        dollars and cents, like 61840.</span>}
    </Card>
  );
}

function Line({ label, cents, note, strong }: {
  label: string; cents: number | null | undefined; note?: string; strong?: boolean;
}) {
  return (
    <tr>
      <td>{strong ? <strong>{label}</strong> : label}
        {note && <div className="tiny muted">{note}</div>}</td>
      <td className="num">{strong ? <strong>{money(cents)}</strong> : money(cents)}</td>
    </tr>
  );
}

function EstimateCard({ data }: { data: TaxEstimate }) {
  const share = Math.round(data.profit.share_of_year * 100);
  return (
    <Card title={`Personal: the year's tax, ${data.year}`}>
      {data.brackets_note && <Banner kind="warn">{data.brackets_note}</Banner>}
      <table className="data" aria-label="How the estimate is worked out">
        <tbody>
          <Line label="The practice's net profit, at this year's pace"
            cents={data.profit.for_year_cents}
            note={`${money(data.profit.so_far_cents)} so far, through ${longDate(
              data.profit.through)} (${share}% of the year), cash basis`} />
          <Line label="Other household income" cents={data.other_income.cents}
            note={data.other_income.from === "typed" ? "As you entered it"
              : "From your income lines at this pace: take-home pay, so likely less "
                + "than before withholding"} />
          <Line label="Self-employment tax" cents={data.se_tax_cents}
            note={`15.3% of 92.35% of net profit (the Social Security part up to the year's `
              + `wage base); half of it, ${money(data.se_half_cents)}, is deducted`} />
          <Line label={data.deduction?.kind === "itemized" ? "Itemized deductions"
            : "Standard deduction"} cents={data.deduction?.cents}
            note={data.deduction?.kind === "itemized"
              ? `Larger than the standard ${money(data.deduction.standard_cents)}`
              : `Your itemized total so far is ${money(data.deduction?.itemized_cents)}`} />
          <Line label="Taxable income" cents={data.taxable_cents} />
          {!!data.qbi_cents && (
            <Line label="Less the QBI deduction, for federal only" cents={-data.qbi_cents}
              note="20% of net profit, as you chose. Consulting is a specified service; the
                deduction phases out above an income threshold. Ask your CPA." />
          )}
          <Line label="Federal income tax" cents={data.federal_cents}
            note={data.method === "rate" ? `At the rate you gave, ${
              data.inputs.effective_rate_percent}%`
              : `At ${data.brackets_year}'s brackets for ${
                data.statuses[data.inputs.filing_status]?.toLowerCase()}`} />
          <Line label={`State income tax${data.inputs.state ? `, ${data.inputs.state}` : ""}`}
            cents={data.state_cents}
            note={`At the flat ${data.state_rate_percent ?? 0}% you gave, on the same `
              + "taxable income"} />
          <Line label="The year's tax" cents={data.total_cents} strong />
          <Line label="Less the expected withholding" cents={-(data.withholding_cents ?? 0)} />
          <Line label="For estimated payments to cover" cents={data.required_cents} strong />
        </tbody>
      </table>
      <p className="tiny muted">Not counted: deductions and credits only your return shows
        (the qualified business income deduction among them), and income that is in
        neither your books nor your lines.</p>
      <Confirm />
    </Card>
  );
}

function QuartersCard({ data }: { data: TaxEstimate }) {
  const next = data.by_next;
  const harbor = data.safe_harbor;
  return (
    <Card title="Personal: the quarterly payments">
      {next && (
        <p style={{ marginTop: 0 }} aria-label="Needed by the next date">
          By <strong>{longDate(next.on_date)}</strong> ({next.label.toLowerCase()}):{" "}
          <strong>{money(next.needed_cents)}</strong> on this year's estimate
          {next.safe_harbor_cents !== null && <>, or {money(next.safe_harbor_cents)} on
            the safe harbor</>}, after the {money(data.paid_cents)} paid so far.
        </p>
      )}
      <table className="data" aria-label="Quarterly payments">
        <thead><tr><th>Due</th><th className="num">This year's estimate</th>
          <th className="num">Safe harbor</th><th className="num">Paid</th><th></th></tr></thead>
        <tbody>
          {(data.quarters ?? []).map((q) => (
            <tr key={q.on_date} className={q.next ? "current" : ""}>
              <td>{longDate(q.on_date)}<div className="tiny muted">{q.label}</div></td>
              <td className="num">{money(q.amount_cents)}</td>
              <td className="num">{q.safe_harbor_cents === null ? "—"
                : money(q.safe_harbor_cents)}</td>
              <td className="num">{q.paid_cents ? money(q.paid_cents) : "—"}</td>
              <td>{q.next ? <Pill kind="warn">next</Pill>
                : q.past && q.paid_cents < q.amount_cents ? <Pill>paid less</Pill>
                  : q.past ? <Pill kind="ok">paid</Pill> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">
        {harbor ? <>The safe harbor is {harbor.percent}% of last year's{" "}
          {money(harbor.last_year_tax_cents)} tax, less the withholding: {harbor.why}</>
          : "Enter last year's total tax to see the safe harbor beside it."}</p>
      <Confirm />
    </Card>
  );
}

function SetAsideCard({ data, busy, send }: {
  data: TaxEstimate; busy: boolean; send: (what: string, body: object) => void;
}) {
  const env = data.envelope!;
  const draws = data.draws!;
  const [percent, setPercent] = useState(data.set_aside.percent_per_draw ?? "");
  const [saved, setSaved] = useState(asText(data.set_aside.saved_cents));
  useEffect(() => {
    setPercent(data.set_aside.percent_per_draw ?? "");
    setSaved(asText(data.set_aside.saved_cents));
  }, [data.set_aside.percent_per_draw, data.set_aside.saved_cents]);
  const since = draws.since_last_payment_cents;
  const suggested = draws.suggested_percent;
  return (
    <Card title="Personal: the Tax envelope">
      <dl className="row" style={{ margin: 0, gap: "var(--s5)", flexWrap: "wrap" }}
        aria-label="The Tax envelope">
        <div><dt className="small muted">Set aside so far</dt>
          <dd style={{ margin: 0, fontSize: "var(--t-20)", fontWeight: 600 }}>
            {money(env.saved_cents)}</dd></div>
        <div><dt className="small muted">Needed by {env.next_on ? longDate(env.next_on)
          : "the next date"}</dt>
          <dd style={{ margin: 0, fontSize: "var(--t-20)", fontWeight: 600 }}>
            {money(env.needed_by_next_cents)}</dd></div>
        <div><dt className="small muted">Short</dt>
          <dd style={{ margin: 0, fontSize: "var(--t-20)", fontWeight: 600,
                       color: env.short_cents ? "var(--bad)" : undefined }}>
            {money(env.short_cents)}</dd></div>
      </dl>
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end",
                                    marginTop: "var(--s3)" }}>
        <Field label="Set aside so far">
          <input aria-label="Set aside so far" value={saved} inputMode="decimal"
            style={{ width: "8rem" }} onChange={(e) => setSaved(e.target.value)} />
        </Field>
        <Field label="Of each draw, %">
          <input aria-label="Set-aside percent of each draw" value={percent}
            style={{ width: "5rem" }} onChange={(e) => setPercent(e.target.value)} />
        </Field>
        <button className="small primary" style={{ flex: "none" }}
          disabled={busy || toCents(saved || "0") === null}
          onClick={() => send("set-aside", { percent_per_draw: percent.trim(),
                                             saved_cents: toCents(saved || "0") })}>
          Save</button>
      </div>
      <ul className="small" aria-label="What to set aside">
        {since && (
          <li>{data.set_aside.percent_per_draw}% of the {money(since.drawn_cents)} drawn since
            the last estimated payment ({longDate(since.since)}) is{" "}
            <strong>{money(since.cents)}</strong>.</li>
        )}
        <li>{suggested === null
          ? "There are no draws in the last six months to take a share of."
          : suggested > 100
            ? <>What is still needed for the year, after what is set aside, is more than
              every draw between now and January 15 at your average of{" "}
              {money(draws.average_draw_cents)} a month ({money(draws.to_cover_cents)}{" "}
              against about {money(draws.draws_ahead_cents)}).</>
            : <>About <strong>{suggested}%</strong> of each draw from here covers what is
              still needed for the year ({money(draws.to_cover_cents)}), at your average
              draw of {money(draws.average_draw_cents)} a month.</>}</li>
        <li>The envelope in your budget: {env.planned_cents === null ? "not made yet"
          : `${money(env.planned_cents)} a month`}. {money(env.suggested_monthly_cents)} a
          month gets the rest there by January 15.{" "}
          <button className="link" disabled={busy}
            onClick={() => send("envelope", { planned_cents: env.suggested_monthly_cents })}>
            Use {money(env.suggested_monthly_cents)} a month</button></li>
      </ul>
      <Confirm />
    </Card>
  );
}

function PaymentsCard({ data }: { data: TaxEstimate }) {
  return (
    <Card title={`Personal: estimated payments made for ${data.year}`}>
      {data.payments.length === 0 ? (
        <Empty>None yet. A payment marked as estimated tax in the practice's books, or a
          line in your Taxes categories, shows here.</Empty>
      ) : (
        <table className="data" aria-label="Estimated payments made">
          <thead><tr><th>Date</th><th>For</th><th>Which</th><th>From</th>
            <th className="num">Amount</th></tr></thead>
          <tbody>
            {data.payments.map((p) => (
              <tr key={p.id}>
                <td>{longDate(p.on_date)}</td><td>{p.quarter_label}</td>
                <td>{p.which === "federal" ? "Federal" : "State"}</td>
                <td><Link to={p.link}>{p.from === "practice" ? "The practice's account"
                  : "A household account"}</Link></td>
                <td className="num">{money(p.amount_cents)}</td>
              </tr>
            ))}
            <tr><td colSpan={4}><strong>Paid so far</strong></td>
              <td className="num"><strong>{money(data.paid_cents)}</strong></td></tr>
          </tbody>
        </table>
      )}
      <p className="tiny muted">A payment made in January counts toward the year before.</p>
    </Card>
  );
}

// ======================================================= the Overview's loop

/** Decision 20: "Your envelopes need $X a month; you have paid yourself $Y on
 *  average", and the business forecast's pay-yourself line set from it. */
export function PayYourselfCard() {
  const qc = useQueryClient();
  const [said, setSaid] = useState<Said>(null);
  const found = useQuery<PayYourself>({
    queryKey: ["personal-pay-yourself"],
    queryFn: () => api.get<PayYourself>("/api/personal/pay-yourself") });
  const set = useMutation({
    mutationFn: (cents: number) => api.post<PayYourself>("/api/personal/pay-yourself",
                                                          { amount_cents: cents }),
    onSuccess: (data) => {
      qc.setQueryData(["personal-pay-yourself"], data);
      qc.invalidateQueries({ queryKey: ["finance-forecast"] });
      setSaid({ kind: "ok", text: "The business forecast's pay-yourself line is set. Undo it "
        + "there, under Forecast, like any change." });
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }) });
  const d = found.data;
  if (!d) return null;
  const line = d.business_line;
  return (
    <Card title="Paying yourself">
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <p style={{ marginTop: 0 }} aria-label="Paying yourself">
        {d.needed_cents === null ? "Once you have a budget, this says what it needs."
          : <>Your envelopes need <strong>{money(d.needed_cents)}</strong> a month
            {d.other_income_cents ? ` beyond ${money(d.other_income_cents)} of other income`
              : ""}; </>}
        {d.paid.average_cents === null ? " the practice's books show no draws to you yet."
          : <>{d.needed_cents === null ? "You" : "you"} have paid yourself{" "}
            <strong>{money(d.paid.average_cents)}</strong> a month on average over the
            last {d.paid.months === 1 ? "month" : `${d.paid.months} months`}.</>}
      </p>
      {d.paid.average_cents !== null && (
        <p className="small muted">
          {money(d.paid.drawn_cents)} a month drawn to your accounts
          {d.paid.spent_cents ? `, and ${money(d.paid.spent_cents)} of personal spending on `
            + "the practice's accounts" : ""}
          {d.paid.tax_cents ? `. Estimated tax paid from the practice, ${money(
            d.paid.tax_cents)} a month on average, is not in it` : ""}.
          {d.matched > 0 && ` ${d.matched} draws are matched to "${d.pay_category}" in your `
            + "lines."}
        </p>
      )}
      {!d.forecasting ? (
        <p className="small muted">The practice's cash forecast is its own module, which this
          practice does not have.</p>
      ) : d.needed_cents !== null && d.needed_cents > 0 && line && (
        <p className="small">
          The business forecast pays you{" "}
          {line.amount_cents === null ? "nothing yet (it has found no draws)"
            : `${money(line.amount_cents)} a month`}.{" "}
          <button className="small" disabled={set.isPending
            || line.amount_cents === d.needed_cents}
            onClick={() => set.mutate(d.needed_cents!)}>
            Set it to {money(d.needed_cents)} a month</button>
        </p>
      )}
    </Card>
  );
}

// ================================================ For your CPA, both sides

const GROUP_HINTS: Record<string, string> = {
  medical: "Doctors and dentists, prescriptions, hospitals, eyeglasses, travel for medical",
  health_insurance: "Medical premiums, Medicare Part B, long-term care premiums",
  interest: "Mortgage interest and points, home equity interest, investment interest",
  property_tax: "Personal residence, investment property",
  charitable: "Church, schools, health charities, other charities",
  non_cash: "By charity: what was given and what it was worth",
};

export function ForYourCpaBothSides() {
  const qc = useQueryClient();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [said, setSaid] = useState<Said>(null);
  const page = useQuery<CpaPage>({
    queryKey: ["personal-cpa", year],
    queryFn: () => api.get<CpaPage>(`/api/personal/cpa?year=${year}`) });
  const done = (data: CpaPage) => {
    qc.setQueryData(["personal-cpa", year], data);
    qc.invalidateQueries({ queryKey: ["personal-taxes"] });
  };
  const fail = (e: Error) => setSaid({ kind: "bad", text: e.message });
  const item = useMutation({
    mutationFn: ({ method, id, body }: { method: "post" | "delete"; id?: string;
                                          body?: object }) =>
      method === "post" ? api.post<CpaPage>("/api/personal/cpa/items", { year, ...body })
        : api.del<CpaPage>(`/api/personal/cpa/items/${id}`),
    onSuccess: (data) => { setSaid(null); done(data); }, onError: fail });
  const facts = useMutation({
    mutationFn: (body: object) => api.post("/api/personal/taxes/inputs", { year, ...body }),
    onSuccess: () => { setSaid({ kind: "ok", text: "Saved." });
                       qc.invalidateQueries({ queryKey: ["personal-cpa", year] }); },
    onError: fail });
  const data = page.data;
  return (
    <>
      <Card title="For your CPA: business and personal">
        <p className="small muted" style={{ marginTop: 0 }}>
          One page for a calendar year: the practice's worksheet as your CPA has it, then
          your household's itemized deduction worksheet and the personal facts your CPA
          asks for. One PDF has both; the business worksheet's own file is below, as it
          always was.</p>
        <div className="row tight">
          <label className="small inline">Year
            <select aria-label="CPA year" value={year} style={{ width: "auto" }}
              onChange={(e) => setYear(Number(e.target.value))}>
              {[thisYear, thisYear - 1, thisYear - 2].map((y) => (
                <option key={y} value={y}>{y}</option>))}
            </select></label>
          <a className="btn primary" href={`/api/personal/cpa/pdf?year=${year}`}>
            Download the PDF, both sections</a>
          <a className="btn" href={`/api/finance-reports/export-worksheet/?year=${year}`}>
            The business worksheet alone (CSV)</a>
        </div>
      </Card>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      {page.isError && <Banner kind="bad">{(page.error as Error).message}</Banner>}
      {!data ? <p>Loading…</p> : (
        <>
          <BusinessSheet sheet={data.business} />
          <div className="personal-band" style={{ marginTop: "var(--s4)" }}>
            <h2 style={{ marginTop: 0 }}>Personal: itemized deductions, {data.year}</h2>
            <p className="small muted">From your lines in categories marked
              tax-deductible (under{" "}
              <Link to="/finance/personal/categories">Personal → Categories</Link>), and
              what you add here. Every line is listed.</p>
            {data.personal.groups.map((g) => (
              <CpaGroupCard key={g.group} g={g} year={data.year} busy={item.isPending}
                onAdd={(body) => item.mutate({ method: "post", body })}
                onRemove={(id) => item.mutate({ method: "delete", id })}
                onMiles={(miles) => facts.mutate(
                  { [g.group === "medical" ? "medical_miles" : "charitable_miles"]: miles })} />
            ))}
            <StandardCard s={data.personal.standard} />
            <PersonalFacts page={data} busy={facts.isPending}
              onHsa={(cents) => facts.mutate({ hsa_cents: cents })} />
            <p className="small"><strong>{data.personal.confirm}</strong>{" "}
              {PERSONAL_DISCLAIMER}</p>
          </div>
        </>
      )}
    </>
  );
}

function BusinessSheet({ sheet }: { sheet: CpaPage["business"] }) {
  return (
    <Card title={`Business: ${sheet.title}`}>
      {sheet.sections.map((section) => (
        <table key={section.title} className="data" aria-label={`Business ${section.title}`}
          style={{ marginBottom: "var(--s3)" }}>
          <thead><tr><th>{section.title}</th><th className="num">Amount</th><th>Note</th></tr>
          </thead>
          <tbody>
            {section.rows.map((row, i) => (
              <tr key={i}>
                <td style={row.sub ? { paddingLeft: "var(--s5)" } : undefined}>{row.name}</td>
                <td className="num">{dollars(row.amount_cents)}</td>
                <td className="small muted">{row.note}</td>
              </tr>
            ))}
            <tr><td><strong>{section.total_label}</strong></td>
              <td className="num"><strong>{dollars(section.total_cents)}</strong></td><td /></tr>
          </tbody>
        </table>
      ))}
      <p><strong>Net {dollars(sheet.net_cents)}</strong></p>
      {sheet.paid_personally.length > 0 && (
        <p className="small">Paid personally, in the figures above:{" "}
          {sheet.paid_personally.map((r) => `${r.name} ${dollars(r.amount_cents)} (${
            r.note.toLowerCase()})`).join("; ")}.</p>
      )}
      <p className="small">Estimated tax payments from the practice: federal{" "}
        {dollars(sheet.estimated_federal_cents)}, state {dollars(sheet.estimated_state_cents)}
        {sheet.estimated.length > 0 && ` (${sheet.estimated.length} payments)`}. Year-end
        facts: {sheet.facts.map((f) => `${f.name.toLowerCase()} ${f.value ?? "not entered"}`)
          .join(", ")}.</p>
      <p className="tiny muted">{sheet.disclaimer}</p>
    </Card>
  );
}

function CpaGroupCard({ g, year, busy, onAdd, onRemove, onMiles }: {
  g: CpaPage["personal"]["groups"][number]; year: number; busy: boolean;
  onAdd: (body: object) => void; onRemove: (id: string) => void;
  onMiles: (miles: number | null) => void;
}) {
  const nonCash = g.group === "non_cash";
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ charity: "", description: "", amount: "", on_date: "" });
  const [miles, setMiles] = useState(g.miles === null ? "" : String(g.miles));
  useEffect(() => { setMiles(g.miles === null ? "" : String(g.miles)); }, [g.miles, year]);
  const cents = toCents(draft.amount);
  return (
    <Card title={g.label}
      actions={!adding && <button className="small" onClick={() => setAdding(true)}>
        {nonCash ? "Add a donation" : "Add a figure from a form"}</button>}>
      <p className="tiny muted" style={{ marginTop: 0 }}>{GROUP_HINTS[g.group]}</p>
      {g.rows.length === 0 ? <Empty>Nothing in {year}.</Empty> : (
        <table className="data" aria-label={g.label}>
          <thead><tr><th>Date</th>{nonCash && <th>Charity</th>}<th>Item</th>
            <th>Description</th><th className="num">Amount</th><th /></tr></thead>
          <tbody>
            {g.rows.map((r) => (
              <tr key={r.id}>
                <td>{r.on_date ? longDate(r.on_date) : "The year"}</td>
                {nonCash && <td>{r.charity}</td>}
                <td>{r.item}</td>
                <td>{r.description}{r.account && <div className="tiny muted">{r.account}</div>}
                  {r.kind === "item" && <div className="tiny muted">Added for your CPA</div>}</td>
                <td className="num">{money(r.amount_cents)}</td>
                <td>{r.kind === "item" && (
                  <button className="ghost small" disabled={busy}
                    aria-label={`Remove ${r.description}`}
                    onClick={() => onRemove(r.id)}>Remove</button>)}</td>
              </tr>
            ))}
            <tr><td colSpan={nonCash ? 4 : 3}><strong>Total</strong></td>
              <td className="num"><strong>{money(g.total_cents)}</strong></td><td /></tr>
          </tbody>
        </table>
      )}
      {g.miles_label && (
        <div className="row tight" style={{ marginTop: "var(--s2)" }}>
          <label className="small inline">{g.miles_label}, for the year
            <input aria-label={g.miles_label} value={miles} inputMode="numeric"
              style={{ width: "6rem" }} onChange={(e) => setMiles(e.target.value)} /></label>
          <button className="small" disabled={busy || (miles !== "" && !/^\d+$/.test(miles))}
            onClick={() => onMiles(miles === "" ? null : Number(miles))}>Save</button>
        </div>
      )}
      {adding && (
        <div className="row" role="group" aria-label={`Add to ${g.label}`}
          style={{ flexWrap: "wrap", alignItems: "flex-end", marginTop: "var(--s3)" }}>
          {nonCash && <Field label="Charity">
            <input aria-label="Charity" value={draft.charity}
              onChange={(e) => setDraft({ ...draft, charity: e.target.value })} /></Field>}
          <Field label={nonCash ? "What was given" : "What it is"}>
            <input aria-label="Description" value={draft.description}
              placeholder={nonCash ? "Clothing, four bags" : "Interest from the lender's statement"}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></Field>
          <Field label={nonCash ? "What it was worth" : "Amount"}>
            <input aria-label="Amount" value={draft.amount} inputMode="decimal"
              style={{ width: "7rem" }}
              onChange={(e) => setDraft({ ...draft, amount: e.target.value })} /></Field>
          <Field label="Date">
            <input type="date" aria-label="Date" value={draft.on_date}
              onChange={(e) => setDraft({ ...draft, on_date: e.target.value })} /></Field>
          <button className="small primary"
            disabled={busy || !cents || !draft.description.trim()
              || (nonCash && !draft.charity.trim())}
            onClick={() => { onAdd({ tax_group: g.group, description: draft.description,
                                     charity: draft.charity, amount_cents: cents,
                                     on_date: draft.on_date || null });
                             setAdding(false);
                             setDraft({ charity: "", description: "", amount: "",
                                        on_date: "" }); }}>Add</button>
          <button className="ghost small" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      )}
    </Card>
  );
}

function StandardCard({ s }: { s: CpaPage["personal"]["standard"] }) {
  return (
    <Card title="Standard against itemized">
      <p style={{ marginTop: 0 }} aria-label="Standard against itemized">
        Itemized total <strong>{money(s.itemized_cents)}</strong>
        {s.standard_cents === null
          ? <>. Enter your filing status under{" "}
            <Link to="/finance/personal/taxes">Taxes</Link> to see the standard deduction
            beside it.</>
          : <>; the standard deduction for {s.status_label.toLowerCase()} in{" "}
            {s.figures_year} is <strong>{money(s.standard_cents)}</strong>.</>}
      </p>
      {s.figures_note && <p className="small muted">{s.figures_note}</p>}
      <p className="small">{s.note}</p>
    </Card>
  );
}

function PersonalFacts({ page, busy, onHsa }: {
  page: CpaPage; busy: boolean; onHsa: (cents: number | null) => void;
}) {
  const facts = page.personal.facts;
  const hsa = facts.find((f) => f.key === "hsa");
  const [hsaText, setHsa] = useState(asText(hsa?.total_cents ?? null));
  useEffect(() => { setHsa(asText(hsa?.total_cents ?? null)); }, [hsa?.total_cents]);
  return (
    <Card title="Personal facts">
      {facts.map((f) => (
        <div key={f.key} role="group" aria-label={f.label} style={{ marginBottom: "var(--s3)" }}>
          <strong>{f.label}</strong>
          {f.key === "estimated" ? (
            <table className="data" aria-label="Estimated payments by quarter">
              <tbody>
                {f.quarters!.map((q) => (
                  <tr key={q.due_on}>
                    <td>{q.label}<div className="tiny muted">due {longDate(q.due_on)}</div></td>
                    <td className="small">{q.payments.length === 0 ? "none yet"
                      : q.payments.map((p) => `${longDate(p.on_date)}, ${p.which}, ${
                        p.from === "practice" ? "from the practice" : "from the household"} ${
                        money(p.amount_cents)}`).join("; ")}</td>
                    <td className="num">{money(q.total_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : f.key === "retirement" ? (
            f.accounts!.length === 0 ? <p className="small muted" style={{ margin: 0 }}>
              None found this year.</p> : (
              <ul className="small" style={{ margin: 0 }}>
                {f.accounts!.map((a) => <li key={a.name}>{a.name}: {money(a.cents)}{" "}
                  <span className="muted">({a.detail})</span></li>)}
              </ul>
            )
          ) : f.key === "hsa" ? (
            <div className="row tight">
              <input aria-label="HSA contributions" value={hsaText} inputMode="decimal"
                placeholder="none" style={{ width: "8rem" }}
                onChange={(e) => setHsa(e.target.value)} />
              <button className="small" disabled={busy
                || (hsaText.trim() !== "" && toCents(hsaText) === null)}
                onClick={() => onHsa(hsaText.trim() === "" ? null : toCents(hsaText))}>
                Save</button>
            </div>
          ) : (
            <span> {money(f.total_cents)}</span>
          )}
          <div className="tiny muted">{f.note}</div>
        </div>
      ))}
    </Card>
  );
}
