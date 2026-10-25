import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { InvoiceLines, cleanLines } from "../components/InvoiceLines";
import { IncomeCategoryPicker } from "../components/IncomeCategoryPicker";
import { TermsPicker } from "../components/PaymentTerms";
import { Modal, PageHead, useRowLink } from "../components/shell";
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

/** A recurring invoice as its form holds it. `terms` null is the practice's. */
type ScheduleDraft = {
  company: string; contact: string; day: string; lines: InvoiceLine[];
  terms: number | null; income: string; pay_instructions: string;
  email_subject: string; email_body: string;
};

const blankSchedule = (): ScheduleDraft => ({
  company: "", contact: "", day: "1",
  lines: [{ description: "", quantity: "1", unit_price_cents: 0 }],
  terms: null, income: "", pay_instructions: "", email_subject: "", email_body: "" });

const scheduleDraft = (row: InvoiceSchedule): ScheduleDraft => ({
  company: row.client_company.id, contact: row.contact.id, day: String(row.day_of_month),
  lines: row.lines.length ? row.lines : blankSchedule().lines,
  terms: row.terms_days, income: row.income_category ?? "",
  pay_instructions: row.pay_instructions, email_subject: row.email_subject,
  email_body: row.email_body });

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
  const save = useMutation({
    mutationFn: () => {
      const body = {
        client_company: form.company, contact: form.contact, day_of_month: Number(form.day),
        lines: cleanLines(form.lines) };
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
        <Field label="Day of the month (1 to 28)">
          <input type="number" min={1} max={28} aria-label="Day of the month" value={form.day}
            style={{ width: "5rem" }} onChange={(e) => set({ day: e.target.value })} />
        </Field>
        <TermsPicker label="Payment terms for the recurring invoice" value={form.terms}
          practice={practice?.terms_days} onChange={(terms) => set({ terms })} />
      </div>
      <InvoiceLines lines={form.lines} onChange={(lines) => set({ lines })} />
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
            || save.isPending}
          onClick={() => save.mutate()}>
          {editing ? "Save the changes" : "Save the recurring invoice"}</button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </Modal>
  );
}

/** Recurring invoices: each writes a draft on its day and nothing else. */
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
  const rows = schedules.data ?? [];
  const editing = rows.find((row) => row.id === open) ?? null;
  return (
    <Card title="Recurring invoices"
      actions={!open && <button className="small" onClick={() => setOpen("new")}>
        New recurring invoice</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        On its day each month a recurring invoice writes a draft. It does not number it and
        does not send it: you check the draft and make it ready, as for any other.
      </p>
      {rows.length === 0 && !open && <Empty>No recurring invoices.</Empty>}
      {rows.length > 0 && (
        <table className="cards-on-phone">
          <thead><tr><th>Client</th><th>Addressed to</th><th>Day</th><th>Terms</th>
            <th>Next draft</th>
            <th className="money">Each month</th>
            {owner && <th>In your books</th>}<th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="card-title">{row.client_company.name}</td>
                <td data-label="To">{row.contact.name}</td>
                <td data-label="Day">{row.day_of_month}</td>
                <td data-label="Terms">{row.terms_label}
                  {row.terms_days === null && <span className="muted"> · the practice's</span>}</td>
                <td data-label="Next draft">{row.is_active ? longDate(row.next_on) : <Pill>paused</Pill>}</td>
                <td data-label="Each month" className="money">{dollars(row.total_cents)}</td>
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
                  <button className="ghost small" disabled={toggle.isPending}
                    aria-label={`${row.is_active ? "Pause" : "Resume"} the recurring invoice for ${row.client_company.name}`}
                    onClick={() => toggle.mutate(row)}>
                    {row.is_active ? "Pause" : "Resume"}</button>
                </td>
              </tr>
            ))}
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
  const rows = events.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Card title="From NMI: please look">
      <p className="small muted" style={{ marginTop: 0 }}>Found in your NMI account by the daily check. The
        invoices' balances are not changed by these: record what each means by hand.</p>
      <ul className="moves nmi-events">
        {rows.map((e) => (
          <li key={e.id}>
            <span>
              <Pill kind={e.outcome === "unmatched" ? "bad" : "warn"}>
                {e.outcome === "unmatched" ? `Unmatched ${e.kind_label.toLowerCase()}` : e.kind_label}</Pill>{" "}
              {e.invoice ? <Link to={`/invoices/${e.invoice}`}>{e.note}</Link> : e.note}
            </span>
            <button className="ghost small" aria-label={`Mark as seen: ${e.note}`} disabled={seen.isPending}
              onClick={() => seen.mutate(e.id)}>Mark as seen</button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
