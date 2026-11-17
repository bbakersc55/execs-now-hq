import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { InvoiceLines, cleanLines } from "../components/InvoiceLines";
import { IncomeCategoryPicker } from "../components/IncomeCategoryPicker";
import { TermsPicker } from "../components/PaymentTerms";
import { Modal, PageHead, useRowLink } from "../components/shell";
import { ClearTestPayments, GatewayModeBanner } from "../components/TestMode";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  Company, Contact, Invoice, InvoiceLine, InvoiceList, InvoiceRow, InvoiceSchedule,
  InvoiceSettingsData, Me, NmiEvent, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * Invoices (P4A; matrix 13.4a–13.4f). The practice owner sees every invoice;
 * an associate sees and drafts for the client companies they are assigned to.
 * An assistant has no financials, so this screen is not in their navigation
 * and the server refuses it.
 *
 * No payment is taken here: an invoice is sent with its PDF, and what the
 * client pays is recorded by hand on the invoice.
 */

/** POST /api/payment-account/clear-test-payments/ — what was done. */
export interface Cleared {
  cleared: { payments: number; reopened: number; voided: number; cards: number };
}

export function cleared(data?: Cleared): string {
  if (!data) return "";
  const c = data.cleared;
  const parts = [`${c.payments} test payment${c.payments === 1 ? "" : "s"} cleared`];
  if (c.reopened) parts.push(`${c.reopened} invoice${c.reopened === 1 ? "" : "s"} reopened`);
  if (c.voided) parts.push(`${c.voided} voided`);
  if (c.cards) parts.push(`${c.cards} test card${c.cards === 1 ? "" : "s"} deleted from the vault`);
  return parts.join(", ") + ".";
}

const STATUSES: [string, string][] = [
  ["", "Every status"], ["draft", "Draft"], ["ready", "Ready to send"], ["sent", "Sent"],
  ["partially_paid", "Partly paid"], ["paid", "Paid"], ["overdue", "Overdue"],
  ["void", "Void"],
];

export function StatusPill({ row }: { row: Pick<InvoiceRow, "status" | "status_label"
                                                | "overdue"> & Partial<InvoiceRow> }) {
  const kind = row.status === "paid" ? "ok" : row.status === "void" ? ""
    : row.status === "draft" || row.status === "ready" ? "ai" : "warn";
  return (
    <>
      <Pill kind={kind}>{row.status_label}</Pill>
      {(row.test_paid_cents ?? 0) > 0 && <> <Pill kind="warn">Test</Pill></>}
      {row.overdue && <> <Pill kind="bad">Overdue</Pill></>}
      {row.send_state === "waiting" && <> <Pill>waiting to be approved</Pill></>}
      {row.send_state === "sent_back" && <> <Pill kind="warn">sent back</Pill></>}
    </>
  );
}

export function Invoices({ me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const filters = {
    status: params.get("status") ?? "", company: params.get("company") ?? "",
    from: params.get("from") ?? "", to: params.get("to") ?? "" };
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    setParams(next, { replace: true });
  };
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value)).toString();
  const list = useQuery<InvoiceList>({
    queryKey: ["invoices", query],
    queryFn: () => api.get<InvoiceList>(`/api/invoices/${query ? `?${query}` : ""}`),
  });
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/") });
  const clients = (companies.data ?? []).filter((c) => c.is_client_company);
  const rowLink = useRowLink();
  const [writing, setWriting] = useState(false);
  const owner = me.role === "FF";
  const qc = useQueryClient();
  // 2026-11-16: test payments, once the card processor reads live again.
  const clear = useMutation({
    mutationFn: (invoices: "reopen" | "void") =>
      api.post<Cleared>("/api/payment-account/clear-test-payments/", { invoices }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["payment-account"] });
    },
  });

  if (list.isError) return <Banner kind="bad">{(list.error as Error).message}</Banner>;
  const data = list.data;
  const filtered = !!query;

  return (
    <>
      <PageHead title="Invoices"
        sub={<>What you have billed and what is still owed. Nothing is charged here: an
          invoice is sent with its PDF, and you record the payment when it arrives.
          {owner && <> <Link to="/settings/invoices">Invoice settings</Link></>}</>}
        action={<button className="primary" onClick={() => setWriting(true)}>
          New invoice</button>} />

      {owner && data && (
        <>
          <GatewayModeBanner mode={data.gateway_mode}
            again="Turned it off? Press Test connection under Settings, Billing." />
          <ClearTestPayments summary={data.test_payments} busy={clear.isPending}
            onClear={(invoices) => clear.mutate(invoices)} />
          {clear.isSuccess && <div role="status"><Banner kind="ok">{cleared(clear.data)}
            </Banner></div>}
          {clear.isError && <Banner kind="bad">{(clear.error as Error).message}</Banner>}
        </>
      )}
      {owner && <FromNmi />}

      {writing && <NewInvoice clients={clients} owner={owner}
        preset={filters.company} onClose={() => setWriting(false)} />}

      {data && data.drafts_from_schedules > 0 && (
        <Banner kind="info">
          {data.drafts_from_schedules === 1 ? "One draft" : `${data.drafts_from_schedules} drafts`}
          {" "}written by a recurring invoice {data.drafts_from_schedules === 1 ? "is" : "are"}
          {" "}waiting to be checked and made ready.{" "}
          <button className="link" onClick={() => set("status", "draft")}>Show drafts</button>
        </Banner>
      )}

      {data && (
        <div className="totals" aria-label={filtered ? "Totals for what is listed" : "Totals"}>
          {([["Invoiced", data.totals.invoiced_cents, false],
             ["Paid", data.totals.paid_cents, false],
             ["Outstanding", data.totals.outstanding_cents, false],
             ["Overdue", data.totals.overdue_cents, data.totals.overdue_cents > 0],
          ] as [string, number, boolean][]).map(([label, cents, bad]) => (
            <div key={label} className={bad ? "total bad" : "total"}>
              <div className="label">{label}</div>
              <div className="figure">{dollars(cents)}</div>
            </div>
          ))}
        </div>
      )}

      <Card>
        <div className="row tight" style={{ marginBottom: "var(--s3)" }}>
          <select aria-label="Status" value={filters.status} style={{ width: "auto" }}
            onChange={(e) => set("status", e.target.value)}>
            {STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <select aria-label="Client company" value={filters.company} style={{ width: "auto" }}
            onChange={(e) => set("company", e.target.value)}>
            <option value="">Every client</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <label className="small inline">Issued from
            <input type="date" aria-label="Issued from" value={filters.from}
              style={{ width: "auto" }} onChange={(e) => set("from", e.target.value)} /></label>
          <label className="small inline">to
            <input type="date" aria-label="Issued to" value={filters.to}
              style={{ width: "auto" }} onChange={(e) => set("to", e.target.value)} /></label>
          <a className="btn small" href={`/api/invoices/export/${query ? `?${query}` : ""}`}>
            Download as CSV</a>
        </div>
        {!data ? <p>Loading the invoices…</p> : data.invoices.length === 0 ? (
          <Empty>{filtered ? "No invoice matches." : "No invoices yet."}</Empty>
        ) : (
          <table className="cards-on-phone">
            <thead>
              <tr><th>Number</th><th>Client</th><th>Addressed to</th><th>Issued</th>
                <th>Due</th><th className="money">Total</th><th className="money">Balance</th>
                <th>Status</th></tr>
            </thead>
            <tbody>
              {data.invoices.map((row) => (
                <tr key={row.id} {...rowLink(`/invoices/${row.id}`)}>
                  <td className="card-title"><Link className="rowname" to={`/invoices/${row.id}`}>
                    {row.number || "Draft"}</Link>
                    {row.from_schedule && row.status === "draft"
                      && <> <Pill>from a schedule</Pill></>}</td>
                  <td data-label="Client">{row.client_company?.name ?? <span className="muted">Not a client</span>}</td>
                  <td data-label="To">{row.contact.name}</td>
                  <td data-label="Issued">{longDate(row.issue_date)}</td>
                  <td data-label="Due">{longDate(row.due_date)}</td>
                  <td data-label="Total" className="money">{dollars(row.total_cents)}</td>
                  <td data-label="Balance" className="money">{row.status === "draft" || row.status === "void"
                    ? "" : dollars(row.balance_cents)}</td>
                  <td data-label="Status"><StatusPill row={row} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Recurring clients={clients} owner={owner} />
    </>
  );
}

/** Who an invoice or a schedule is for: a client company and someone at it. */
function useRecipients(companyId: string) {
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
    enabled: !!companyId });
  return (contacts.data ?? []).filter((c) => c.company === companyId);
}

const name = (c: Contact) => `${c.first_name} ${c.last_name}`.trim();

function NewInvoice({ clients, owner, preset, onClose }: {
  clients: Company[]; owner: boolean; preset: string; onClose: () => void;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [toContact, setToContact] = useState(false);
  const [company, setCompany] = useState(preset);
  const [contact, setContact] = useState("");
  const [term, setTerm] = useState("");
  const people = useRecipients(toContact ? "" : company);
  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["contact-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: toContact && term.trim().length > 1 });
  const create = useMutation({
    mutationFn: () => api.post<Invoice>("/api/invoices/", toContact
      ? { kind: "contact", contact, lines: [] }
      : { client_company: company, contact, lines: [] }),
    onSuccess: (made) => {
      qc.invalidateQueries({ queryKey: ["invoices"] });
      navigate(`/invoices/${made.id}`);
    },
  });
  const choices = toContact ? (found.data?.contacts ?? []) : people;
  return (
    <Modal title="New invoice" label="New invoice" onClose={onClose}>
      {create.isError && <Banner kind="bad">{(create.error as Error).message}</Banner>}
      {owner && (
        <label className="small" style={{ display: "flex", gap: ".4rem" }}>
          <input type="checkbox" checked={toContact}
            onChange={(e) => { setToContact(e.target.checked); setContact(""); }} />
          This is for someone who is not a client (sent by email only; it shows in no
          client's view)
        </label>
      )}
      <div className="row">
        {toContact ? (
          <Field label="Find the person">
            <input aria-label="Find the person to invoice" value={term}
              placeholder="A name or an email address"
              onChange={(e) => { setTerm(e.target.value); setContact(""); }} />
          </Field>
        ) : (
          <Field label="Client company">
            <select aria-label="Client company to invoice" value={company}
              onChange={(e) => { setCompany(e.target.value); setContact(""); }}>
              <option value="">Choose a client</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Addressed to">
          <select aria-label="Addressed to" value={contact}
            disabled={choices.length === 0} onChange={(e) => setContact(e.target.value)}>
            <option value="">{choices.length === 0
              ? (toContact ? "Search first" : "Choose a client first") : "Choose a person"}
            </option>
            {choices.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
          </select>
        </Field>
      </div>
      {!toContact && company && people.length === 0 && (
        <p className="small muted">That company has no contacts yet. Add the person the
          invoice goes to on the company's page first.</p>
      )}
      <p className="small muted">Saving starts a draft and opens it, to add its lines.
        Nothing is numbered or sent.</p>
      <div className="row tight">
        <button className="primary" disabled={!contact || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? "Saving…" : "Save the draft"}</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

/** A recurring invoice as its form holds it. `terms` null is the practice's.
 *  2026-11-17: `mode` "auto" bills automatically. Its schedule is one of the
 *  presets, turned into the server's cadence fields by `timingBody`. */
type Preset = "weekly" | "biweekly" | "twice" | "monthly" | "quarterly" | "yearly" | "custom";
type ScheduleDraft = {
  company: string; contact: string; day: string; lines: InvoiceLine[];
  terms: number | null; income: string; pay_instructions: string;
  email_subject: string; email_body: string;
  mode: "send" | "auto"; days: string[]; first: string; term: string; lead: string;
  preset: Preset; weekday: string; every: string; unit: "weeks" | "months";
  qday: string; firstMonth: string;
};

const PRESETS: [Preset, string][] = [
  ["weekly", "Weekly"], ["biweekly", "Every two weeks"],
  ["twice", "Twice a month (1st and 15th)"], ["monthly", "Monthly"],
  ["quarterly", "Quarterly"], ["yearly", "Yearly"], ["custom", "Custom"]];
/** As the server counts them: 0 is Monday. */
const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                       "Sunday"];
const pad2 = (n: number | string) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
/** The first day from today that passes `test`, as YYYY-MM-DD. */
function nextDay(test: (d: Date) => boolean): string {
  const d = new Date();
  for (let i = 0; i < 400; i += 1) {
    if (test(d)) return isoDay(d);
    d.setDate(d.getDate() + 1);
  }
  return "";
}
const weekdayOf = (d: Date) => (d.getDay() + 6) % 7;

/** What the server stores for a preset (`apps/billing/timing.py`). */
function timingBody(f: ScheduleDraft) {
  const weekday = Number(f.weekday);
  const weekly = (every: number) => ({ cadence: "weekly", every, weekday, days_of_month: [],
                                       first_billing_on: f.first });
  switch (f.preset) {
    case "weekly": return weekly(1);
    case "biweekly": return weekly(2);
    case "twice": return { cadence: "monthly", every: 1, weekday: null, days_of_month: [1, 15],
                           first_billing_on: f.first };
    case "quarterly": return { cadence: "monthly", every: 3, weekday: null,
                               days_of_month: [Number(f.qday)],
                               first_billing_on: f.firstMonth
                                 ? `${f.firstMonth}-${pad2(f.qday)}` : "" };
    case "yearly": return { cadence: "yearly", every: 1, weekday: null, days_of_month: [],
                            first_billing_on: f.first };
    case "custom": return f.unit === "weeks" ? weekly(Number(f.every)) : {
      cadence: "monthly", every: Number(f.every), weekday: null,
      days_of_month: [Number(f.qday)], first_billing_on: f.first };
    default: return { cadence: "monthly", every: 1, weekday: null,
                      days_of_month: f.days.filter((d) => d.trim()).map(Number),
                      first_billing_on: f.first };
  }
}

function presetOf(row: InvoiceSchedule): Preset {
  if (!row.first_billing_on) return "monthly";
  if (row.cadence === "weekly") return row.every === 1 ? "weekly" : row.every === 2
    ? "biweekly" : "custom";
  if (row.cadence === "yearly") return "yearly";
  const days = row.days_of_month ?? [];
  if (row.every === 1) return days.length === 2 && days[0] === 1 && days[1] === 15
    ? "twice" : "monthly";
  if (row.every === 3 && days.length === 1) return "quarterly";
  return "custom";
}

const blankSchedule = (): ScheduleDraft => ({
  company: "", contact: "", day: "1",
  lines: [{ description: "", quantity: "1", unit_price_cents: 0 }],
  terms: null, income: "", pay_instructions: "", email_subject: "", email_body: "",
  mode: "send", days: ["1"], first: "", term: "", lead: "3",
  preset: "monthly", weekday: "4", every: "2", unit: "weeks", qday: "1", firstMonth: "" });

const scheduleDraft = (row: InvoiceSchedule): ScheduleDraft => ({
  company: row.client_company.id, contact: row.contact.id, day: String(row.day_of_month),
  lines: row.lines.length ? row.lines : blankSchedule().lines,
  terms: row.terms_days, income: row.income_category ?? "",
  pay_instructions: row.pay_instructions, email_subject: row.email_subject,
  email_body: row.email_body, mode: row.mode ?? "send",
  days: (row.days_of_month ?? []).length ? row.days_of_month.map(String) : ["1"],
  first: row.first_billing_on ?? "", term: row.term_ends_on ?? "",
  lead: String(row.lead_days ?? 3),
  preset: presetOf(row), weekday: String(row.weekday ?? 4), every: String(row.every ?? 2),
  unit: row.cadence === "weekly" ? "weeks" : "months",
  qday: String((row.days_of_month ?? [])[0] ?? 1),
  firstMonth: (row.first_billing_on ?? "").slice(0, 7) });

/**
 * The one form a recurring invoice is made and changed in (owner, 2026-10-14:
 * once saved it could only be paused).
 *
 * Its own "how to pay" and covering email are optional: left empty, each
 * invoice it writes takes the practice's, as it stands that day. A change
 * applies to the invoices it writes from then on. The ones already written
 * are documents of their own and are not touched.
 */
function ScheduleForm({ editing, clients, owner, practice, onDone, onCancel }: {
  editing: InvoiceSchedule | null; clients: Company[]; owner: boolean;
  practice: InvoiceSettingsData | undefined; onDone: () => void; onCancel: () => void;
}) {
  const [form, setForm] = useState<ScheduleDraft>(
    editing ? scheduleDraft(editing) : blankSchedule);
  const set = (patch: Partial<ScheduleDraft>) => setForm({ ...form, ...patch });
  const people = useRecipients(form.company);
  const what = editing ? `${editing.client_company.name}'s recurring invoice`
    : "the recurring invoice";
  const auto = form.mode === "auto";
  // While the client's agreement is in force, what they agreed to is fixed.
  const agreed = !!editing?.automatic
    && (editing.automatic.state === "active" || editing.automatic.state === "ending");
  // "You send each invoice", monthly on one day, made before cadences or now:
  // its day of the month, exactly as before (2026-11-17).
  const oneDay = !auto && form.preset === "monthly" && !editing?.first_billing_on;
  const save = useMutation({
    mutationFn: () => {
      const body = auto ? {
        mode: "auto", client_company: form.company, contact: form.contact,
        ...timingBody(form), term_ends_on: form.term || null,
        lead_days: Number(form.lead), lines: cleanLines(form.lines) } : oneDay ? {
        client_company: form.company, contact: form.contact, day_of_month: Number(form.day),
        lines: cleanLines(form.lines) } : {
        client_company: form.company, contact: form.contact, ...timingBody(form),
        lines: cleanLines(form.lines) };
      if (auto) {
        const extra = {
          pay_instructions: form.pay_instructions, email_subject: form.email_subject,
          email_body: form.email_body, ...(owner ? { income_category: form.income } : {}) };
        return editing
          ? api.patch<InvoiceSchedule>(`/api/invoice-schedules/${editing.id}/`,
            { ...body, ...extra })
          : api.post<InvoiceSchedule>("/api/invoice-schedules/", {
            ...body,
            ...(form.pay_instructions.trim() ? { pay_instructions: form.pay_instructions } : {}),
            ...(form.email_subject.trim() ? { email_subject: form.email_subject } : {}),
            ...(form.email_body.trim() ? { email_body: form.email_body } : {}),
            ...(owner && form.income ? { income_category: form.income } : {}) });
      }
      return editing
        // Everything the form holds, so what is saved is what is shown: an
        // emptied box goes back to the practice's own.
        ? api.patch<InvoiceSchedule>(`/api/invoice-schedules/${editing.id}/`, {
          ...body, terms_days: form.terms, pay_instructions: form.pay_instructions,
          email_subject: form.email_subject, email_body: form.email_body,
          ...(owner ? { income_category: form.income } : {}) })
        // A new one names only what was chosen; the rest is the practice's.
        : api.post<InvoiceSchedule>("/api/invoice-schedules/", {
          ...body,
          ...(form.terms !== null ? { terms_days: form.terms } : {}),
          ...(form.pay_instructions.trim() ? { pay_instructions: form.pay_instructions } : {}),
          ...(form.email_subject.trim() ? { email_subject: form.email_subject } : {}),
          ...(form.email_body.trim() ? { email_body: form.email_body } : {}),
          ...(owner && form.income ? { income_category: form.income } : {}) });
    },
    onSuccess: onDone,
  });
  // The people offered are the chosen company's. While they load for a
  // schedule being edited, the person it is addressed to is still offered.
  const offered = editing && form.company === editing.client_company.id
    && !people.some((c) => c.id === editing.contact.id)
    ? [{ id: editing.contact.id, label: editing.contact.name },
       ...people.map((c) => ({ id: c.id, label: name(c) }))]
    : people.map((c) => ({ id: c.id, label: name(c) }));
  return (
    <Modal wide onClose={onCancel}
      title={editing ? `Edit ${what}` : "New recurring invoice"}
      label={editing ? `Editing ${what}` : "The new recurring invoice"}>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {editing && (
        <p className="small muted" style={{ marginTop: 0 }}>
          Changes apply to the invoices it writes from now on. Invoices it has already
          written are not changed.
        </p>
      )}
      <div className="row">
        <Field label="Client company">
          <select aria-label="Client company for the recurring invoice" value={form.company}
            onChange={(e) => set({ company: e.target.value, contact: "" })}>
            <option value="">Choose a client</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Addressed to">
          <select aria-label="Recurring invoice addressed to" value={form.contact}
            disabled={offered.length === 0} onChange={(e) => set({ contact: e.target.value })}>
            <option value="">Choose a person</option>
            {offered.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </Field>
        {oneDay && (
          <Field label="Day of the month (1 to 28)">
            <input type="number" min={1} max={28} aria-label="Day of the month"
              value={form.day} style={{ width: "5rem" }}
              onChange={(e) => set({ day: e.target.value })} />
          </Field>
        )}
        {!auto && (
          <TermsPicker label="Payment terms for the recurring invoice" value={form.terms}
            practice={practice?.terms_days} onChange={(terms) => set({ terms })} />
        )}
      </div>
      {!editing && owner && (
        <fieldset className="row tight" aria-label="How it is billed">
          <label className="check">
            <input type="radio" name="schedule-mode" checked={!auto}
              onChange={() => set({ mode: "send" })} /> You send each invoice
          </label>
          <label className="check">
            <input type="radio" name="schedule-mode" checked={auto}
              onChange={() => set({ mode: "auto" })} /> Bill automatically
          </label>
        </fieldset>
      )}
      <ScheduleTiming form={form} set={set} locked={agreed} auto={auto} oneDay={oneDay}
        company={clients.find((c) => c.id === form.company)?.name ?? "the client"} />
      <p className="small muted" style={{ marginTop: 0 }}>
        {auto ? "Once the client owner agrees in the portal, each invoice is made, numbered "
          + "and emailed by itself before its billing date, and the saved card is charged on "
          + "the date. Nothing is billed until they agree."
          : "On its day each month it writes a draft for you to check, make ready and send."}
      </p>
      <InvoiceLines lines={form.lines} onChange={(lines) => set({ lines })} />
      {agreed && (
        <p className="small muted">A change of lines or price applies from the first
          billing date at least 7 days out, and the client is emailed.</p>
      )}
      {owner && (
        <Field label="In your books, its payments go to">
          <IncomeCategoryPicker kind="recurring" value={form.income}
            onChange={(income) => set({ income })}
            label={editing ? `Income category for ${what}`
              : "Income category for the new recurring invoice"} />
        </Field>
      )}
      <Field label="How to pay (leave empty for the practice's own)">
        <textarea rows={2} aria-label="How to pay, for the recurring invoice"
          placeholder={practice?.pay_instructions ?? ""} value={form.pay_instructions}
          onChange={(e) => set({ pay_instructions: e.target.value })} />
      </Field>
      <Field label="Covering email (leave empty for the practice's own)">
        <input aria-label="Email subject, for the recurring invoice" maxLength={200}
          placeholder={practice?.email_subject ?? ""} value={form.email_subject}
          onChange={(e) => set({ email_subject: e.target.value })} />
        <textarea rows={4} aria-label="Email body, for the recurring invoice"
          placeholder={practice?.email_body ?? ""} value={form.email_body}
          onChange={(e) => set({ email_body: e.target.value })} />
        {practice && (
          <p className="tiny muted" style={{ marginBottom: 0 }}>
            You can use {practice.merge_fields.map((f) => `{${f}}`).join(", ")}. They are
            filled in when each invoice is made ready.
          </p>
        )}
      </Field>
      <div className="row tight" style={{ marginTop: "var(--s3)" }}>
        <button className="primary"
          disabled={!form.company || !form.contact || cleanLines(form.lines).length === 0
            || (!oneDay && !timingBody(form).first_billing_on)
            || save.isPending}
          onClick={() => save.mutate()}>
          {editing ? "Save the changes" : "Save the recurring invoice"}</button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </Modal>
  );
}

/** 2026-11-17: when a recurring invoice bills or writes its draft, for both
 *  kinds: a preset (Weekly, Every two weeks, Twice a month, Monthly,
 *  Quarterly, Yearly, Custom) and the few fields it needs; for automatic
 *  billing also an optional contract end and how many days before each date
 *  the invoice is emailed. */
function ScheduleTiming({ form, set, locked, auto, oneDay, company }: {
  form: ScheduleDraft; set: (patch: Partial<ScheduleDraft>) => void; locked: boolean;
  auto: boolean; oneDay: boolean; company: string;
}) {
  const setDay = (index: number, value: string) =>
    set({ days: form.days.map((d, i) => (i === index ? value : d)) });
  const onWeekday = (weekday: string) =>
    nextDay((d) => weekdayOf(d) === Number(weekday));
  const choose = (preset: Preset) => {
    const patch: Partial<ScheduleDraft> = { preset };
    if (preset === "weekly" || preset === "biweekly"
        || (preset === "custom" && form.unit === "weeks")) {
      patch.first = onWeekday(form.weekday);
    } else if (preset === "twice") {
      patch.first = nextDay((d) => d.getDate() === 1 || d.getDate() === 15);
    }
    set(patch);
  };
  const weekdays = form.preset === "weekly" || form.preset === "biweekly"
    || (form.preset === "custom" && form.unit === "weeks");
  const oneMonthDay = form.preset === "quarterly"
    || (form.preset === "custom" && form.unit === "months");
  const daysList = form.preset === "monthly" && !oneDay;
  const firstBox = !oneDay && form.preset !== "quarterly" && form.preset !== "yearly";
  return (
    <div className="card-inset" aria-label="When it bills">
      {locked && (
        <p className="small muted" style={{ marginTop: 0 }}>{company} agreed to this schedule,
          this first date and this contract end, so they can't change while the agreement
          is in force.</p>
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <Field label="Schedule">
          <select aria-label="Schedule" value={form.preset} disabled={locked}
            onChange={(e) => choose(e.target.value as Preset)}>
            {PRESETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        {form.preset === "custom" && (
          <Field label="Every">
            <span className="row tight">
              <input type="number" min={1} max={form.unit === "weeks" ? 52 : 12}
                aria-label="Every how many" value={form.every} disabled={locked}
                style={{ width: "4.5rem" }} onChange={(e) => set({ every: e.target.value })} />
              <select aria-label="Weeks or months" value={form.unit} disabled={locked}
                onChange={(e) => set({ unit: e.target.value as "weeks" | "months",
                  ...(e.target.value === "weeks" ? { first: onWeekday(form.weekday) } : {}) })}>
                <option value="weeks">weeks</option><option value="months">months</option>
              </select>
            </span>
          </Field>
        )}
        {weekdays && (
          <Field label="Weekday">
            <select aria-label="Weekday" value={form.weekday} disabled={locked}
              onChange={(e) => set({ weekday: e.target.value, first: onWeekday(e.target.value) })}>
              {WEEKDAY_NAMES.map((name, i) => <option key={name} value={i}>{name}</option>)}
            </select>
          </Field>
        )}
        {oneMonthDay && (
          <Field label="Day of the month (1 to 28)">
            <input type="number" min={1} max={28} aria-label="Day of the month it bills on"
              value={form.qday} disabled={locked} style={{ width: "4.5rem" }}
              onChange={(e) => set({ qday: e.target.value })} />
          </Field>
        )}
        {form.preset === "quarterly" && (
          <Field label="First month">
            <input type="month" aria-label="First month" value={form.firstMonth}
              disabled={locked} onChange={(e) => set({ firstMonth: e.target.value })} />
          </Field>
        )}
        {form.preset === "yearly" && (
          <Field label="Date each year (not February 29)">
            <input type="date" aria-label="Date each year" value={form.first} disabled={locked}
              onChange={(e) => set({ first: e.target.value })} />
          </Field>
        )}
      </div>
      {daysList && (
        <Field label="Billing days of the month (1 to 28)">
          <div className="row tight" style={{ flexWrap: "wrap" }}>
            {form.days.map((day, index) => (
              <span key={index} className="row tight">
                <input type="number" min={1} max={28} value={day} disabled={locked}
                  aria-label={`Billing day ${index + 1}`} style={{ width: "4.5rem" }}
                  onChange={(e) => setDay(index, e.target.value)} />
                {form.days.length > 1 && !locked && (
                  <button type="button" className="ghost small"
                    aria-label={`Remove billing day ${index + 1}`}
                    onClick={() => set({ days: form.days.filter((_, i) => i !== index) })}>
                    ✕</button>
                )}
              </span>
            ))}
            {!locked && form.days.length < 28 && (
              <button type="button" className="small"
                onClick={() => set({ days: [...form.days, ""] })}>Add a day</button>
            )}
          </div>
        </Field>
      )}
      <div className="row" style={{ flexWrap: "wrap" }}>
        {firstBox && (
          <Field label={auto ? "First billing date" : "First invoice date"}>
            <input type="date" aria-label="First billing date" value={form.first}
              disabled={locked} onChange={(e) => set({ first: e.target.value })} />
          </Field>
        )}
        {auto && (
          <>
            <Field label="Contract end date (optional; then month to month)">
              <input type="date" aria-label="Contract end date" value={form.term}
                disabled={locked} onChange={(e) => set({ term: e.target.value })} />
            </Field>
            <Field label="Email each invoice this many days before (0 to 14)">
              <input type="number" min={0} max={14} aria-label="Days before each billing date"
                value={form.lead} style={{ width: "5rem" }}
                onChange={(e) => set({ lead: e.target.value })} />
            </Field>
          </>
        )}
      </div>
      {auto && (
        <p className="tiny muted" style={{ marginBottom: 0 }}>Never more days before than the
          gap between two billing dates.</p>
      )}
    </div>
  );
}

/** What a recurring invoice billed automatically shows under its row: its
 *  timeline and the practice owner's actions. */
function AutomaticDetails({ row, onChanged }: {
  row: InvoiceSchedule; onChanged: (next: InvoiceSchedule & { message?: string }) => void;
}) {
  const a = row.automatic!;
  const [endOn, setEndOn] = useState("");
  const [sure, setSure] = useState(false);
  const [said, setSaid] = useState("");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api.post<InvoiceSchedule & { message?: string }>(
        `/api/invoice-schedules/${row.id}/${path}`, body ?? {}),
    onSuccess: (next) => { setSaid(next.message ?? ""); setSure(false); onChanged(next); },
    onError: () => setSaid(""),
  });
  const name = row.client_company.name;
  const live = a.state === "active" || a.state === "ending";
  return (
    <div aria-label={`Automatic billing for ${name}`} className="small">
      {act.isError && <Banner kind="bad">{(act.error as Error).message}</Banner>}
      {said && <div role="status"><Banner kind="ok">{said}</Banner></div>}
      <p style={{ marginTop: 0 }}>{dollars(row.total_cents)} {a.timing_words}.
        {a.pending && <> From {longDate(a.pending.from)}: {dollars(a.pending.total_cents)} each
          time.</>}</p>
      {a.timeline.length > 0 && (
        <ol aria-label={`Timeline for ${name}`}>
          {a.timeline.map((t, i) => (
            <li key={i}>{t.what}: {longDate(t.on)}{t.by ? `, ${t.by}` : ""}
              {t.future ? " (to come)" : ""}</li>
          ))}
        </ol>
      )}
      <div className="row tight" style={{ flexWrap: "wrap" }}>
        {(a.state === "waiting" || a.state === "ended") && (
          <button className="small" disabled={act.isPending}
            onClick={() => act.mutate({ path: "send-link/" })}>
            Email {name} the link to agree</button>
        )}
        {a.can_run_now && (
          <button className="small" disabled={act.isPending}
            onClick={() => act.mutate({ path: "run-now/" })}>
            Run the next billing now</button>
        )}
      </div>
      {live && (
        <div className="row tight" style={{ flexWrap: "wrap", marginTop: "0.5rem" }}>
          <Field label={a.ends_on ? "Move the end earlier" : "End billing on"}>
            <input type="date" aria-label={`Last day to bill ${name}`} value={endOn}
              max={a.ends_on ?? undefined} onChange={(e) => setEndOn(e.target.value)} />
          </Field>
          <button className="small" disabled={!endOn || act.isPending}
            onClick={() => act.mutate({ path: "set-end/", body: { ends_on: endOn } })}>
            Set the end</button>
          {!sure ? (
            <button className="small ghost" onClick={() => setSure(true)}>Stop now</button>
          ) : (
            <button className="small primary" disabled={act.isPending}
              onClick={() => act.mutate({ path: "set-end/", body: { now: true } })}>
              Yes, stop billing {name} now</button>
          )}
        </div>
      )}
    </div>
  );
}

/** Recurring invoices: each writes a draft on its day and nothing else;
 *  2026-11-17: or bills automatically, once the client agrees. */
function Recurring({ clients, owner }: { clients: Company[]; owner: boolean }) {
  const qc = useQueryClient();
  const schedules = useQuery<InvoiceSchedule[]>({
    queryKey: ["invoice-schedules"],
    queryFn: () => api.get<InvoiceSchedule[]>("/api/invoice-schedules/") });
  // "new", a schedule's id, or nothing open.
  const [open, setOpen] = useState("");
  const practice = useQuery<InvoiceSettingsData>({
    queryKey: ["invoice-settings"], retry: false,
    queryFn: () => api.get<InvoiceSettingsData>("/api/invoice-settings/") });
  const done = () => qc.invalidateQueries({ queryKey: ["invoice-schedules"] });
  const toggle = useMutation({
    mutationFn: (row: InvoiceSchedule) => api.patch<InvoiceSchedule>(
      `/api/invoice-schedules/${row.id}/`, { is_active: !row.is_active }),
    onSuccess: done,
  });
  const recategorize = useMutation({
    mutationFn: ({ row, id }: { row: InvoiceSchedule; id: string }) =>
      api.patch<InvoiceSchedule>(`/api/invoice-schedules/${row.id}/`, { income_category: id }),
    onSuccess: done,
  });
  const [shown, setShown] = useState("");
  const rows = schedules.data ?? [];
  const editing = rows.find((row) => row.id === open) ?? null;
  const pill = (a: NonNullable<InvoiceSchedule["automatic"]>) => (
    <Pill kind={a.state === "active" ? "ok" : a.state === "ended" ? "" : "warn"}>
      {a.state_label}</Pill>);
  return (
    <Card title="Recurring invoices"
      actions={!open && <button className="small" onClick={() => setOpen("new")}>
        New recurring invoice</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        "You send each invoice": on its day each month it writes a draft. It does not number
        it and does not send it: you check the draft and make it ready, as for any other.
        "Bill automatically": once the client owner agrees in the portal, each invoice is
        made and emailed by itself, and the saved card charged on its billing date.
      </p>
      {rows.length === 0 && !open && <Empty>No recurring invoices.</Empty>}
      {rows.length > 0 && (
        <table className="cards-on-phone">
          <thead><tr><th>Client</th><th>Addressed to</th><th>How</th><th>When</th>
            <th>State</th><th>Next</th><th>Last billed</th>
            <th className="money">Each time</th>
            {owner && <th>In your books</th>}<th /></tr></thead>
          <tbody>
            {rows.map((row) => (<Fragment key={row.id}>
              <tr>
                <td className="card-title">{row.client_company.name}</td>
                <td data-label="To">{row.contact.name}</td>
                <td data-label="How">{row.mode === "auto" ? "Bills automatically"
                  : "You send each"}</td>
                <td data-label="When">{row.automatic ? row.automatic.timing_words
                  : row.timing_words ? <>{row.timing_words} · {row.terms_label}</>
                  : <>Day {row.day_of_month} · {row.terms_label}
                    {row.terms_days === null && <span className="muted"> · the practice's</span>}</>}</td>
                <td data-label="State">{row.automatic ? pill(row.automatic)
                  : row.is_active ? <Pill kind="ok">Active</Pill> : <Pill>paused</Pill>}</td>
                <td data-label="Next">{row.automatic
                  ? (row.automatic.next_billing_on ? longDate(row.automatic.next_billing_on) : "")
                  : row.is_active ? longDate(row.next_on) : ""}</td>
                <td data-label="Last billed">{row.automatic?.last_billed_on
                  ? longDate(row.automatic.last_billed_on) : ""}</td>
                <td data-label="Each time" className="money">{dollars(row.total_cents)}</td>
                {owner && (
                  <td data-label="In your books">
                    <IncomeCategoryPicker kind="recurring" value={row.income_category ?? ""}
                      disabled={recategorize.isPending}
                      label={`Income category for ${row.client_company.name}'s recurring invoice`}
                      onChange={(id) => recategorize.mutate({ row, id })} />
                  </td>
                )}
                <td className="money card-actions">
                  <button className="ghost small" disabled={!!open}
                    aria-label={`Edit the recurring invoice for ${row.client_company.name}`}
                    onClick={() => setOpen(row.id)}>Edit</button>{" "}
                  {row.automatic ? (
                    <button className="ghost small" aria-expanded={shown === row.id}
                      aria-label={`Details of automatic billing for ${row.client_company.name}`}
                      onClick={() => setShown(shown === row.id ? "" : row.id)}>
                      {shown === row.id ? "Hide" : "Details"}</button>
                  ) : (
                    <button className="ghost small" disabled={toggle.isPending}
                      aria-label={`${row.is_active ? "Pause" : "Resume"} the recurring invoice for ${row.client_company.name}`}
                      onClick={() => toggle.mutate(row)}>
                      {row.is_active ? "Pause" : "Resume"}</button>
                  )}
                </td>
              </tr>
              {row.automatic && shown === row.id && (
                <tr><td colSpan={owner ? 10 : 9}>
                  <AutomaticDetails row={row} onChanged={() => done()} />
                </td></tr>
              )}
            </Fragment>))}
          </tbody>
        </table>
      )}
      {(open === "new" || editing) && (
        <ScheduleForm key={open} editing={editing} clients={clients} owner={owner}
          practice={practice.data} onCancel={() => setOpen("")}
          onDone={() => { done(); setOpen(""); }} />
      )}
    </Card>
  );
}

/**
 * P4 §4: what the daily read-back found in the practice's NMI account that
 * the app did not do: refunds, voids and chargebacks made in NMI's portal
 * (recorded against their payment), and anything it couldn't match. The
 * practice owner's only. Nothing here changes an invoice's money.
 */
function FromNmi() {
  const qc = useQueryClient();
  const events = useQuery<NmiEvent[]>({
    queryKey: ["nmi-events"], queryFn: () => api.get<NmiEvent[]>("/api/nmi-events/?open=1"),
  });
  const seen = useMutation({
    mutationFn: (id: string) => api.post(`/api/nmi-events/${id}/seen/`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["nmi-events"] }),
  });
  // 2026-11-16: one made in the portal, recorded against its payment.
  const record = useMutation({
    mutationFn: (id: string) => api.post(`/api/nmi-events/${id}/record/`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["nmi-events"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
  const rows = events.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Card title="From NMI: please look">
      <p className="small muted" style={{ marginTop: 0 }}>Found in your NMI account by the daily check. The
        invoices' balances are not changed by these by themselves. A refund or cancel made in
        the processor's portal is recorded on its invoice and in your books with Record this
        refund; anything else, record by hand.</p>
      {record.isError && <Banner kind="bad">{(record.error as Error).message}</Banner>}
      <ul className="moves nmi-events">
        {rows.map((e) => (
          <li key={e.id}>
            <span>
              <Pill kind={e.outcome === "unmatched" ? "bad" : "warn"}>
                {e.outcome === "unmatched" ? `Unmatched ${e.kind_label.toLowerCase()}` : e.kind_label}</Pill>{" "}
              {e.invoice ? <Link to={`/invoices/${e.invoice}`}>{e.note}</Link> : e.note}
            </span>
            <span className="row tight">
              {e.can_record && (
                <button className="small" aria-label={`Record this refund: ${e.note}`}
                  disabled={record.isPending} onClick={() => record.mutate(e.id)}>
                  Record this refund</button>
              )}
              <button className="ghost small" aria-label={`Mark as seen: ${e.note}`} disabled={seen.isPending}
                onClick={() => seen.mutate(e.id)}>Mark as seen</button>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
