import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { InvoiceLines, cleanLines } from "../components/InvoiceLines";
import { PageHead, useRowLink } from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  Company, Contact, Invoice, InvoiceLine, InvoiceList, InvoiceRow, InvoiceSchedule, Me, api,
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
          <table>
            <thead>
              <tr><th>Number</th><th>Client</th><th>Addressed to</th><th>Issued</th>
                <th>Due</th><th className="money">Total</th><th className="money">Balance</th>
                <th>Status</th></tr>
            </thead>
            <tbody>
              {data.invoices.map((row) => (
                <tr key={row.id} {...rowLink(`/invoices/${row.id}`)}>
                  <td><Link className="rowname" to={`/invoices/${row.id}`}>
                    {row.number || "Draft"}</Link>
                    {row.from_schedule && row.status === "draft"
                      && <> <Pill>from a schedule</Pill></>}</td>
                  <td>{row.client_company?.name ?? <span className="muted">Not a client</span>}</td>
                  <td>{row.contact.name}</td>
                  <td>{longDate(row.issue_date)}</td>
                  <td>{longDate(row.due_date)}</td>
                  <td className="money">{dollars(row.total_cents)}</td>
                  <td className="money">{row.status === "draft" || row.status === "void"
                    ? "" : dollars(row.balance_cents)}</td>
                  <td><StatusPill row={row} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Recurring clients={clients} />
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
    <Card title="New invoice">
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
        <button className="primary" disabled={!contact || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? "Starting…" : "Start the draft"}</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
      {!toContact && company && people.length === 0 && (
        <p className="small muted">That company has no contacts yet. Add the person the
          invoice goes to on the company's page first.</p>
      )}
    </Card>
  );
}

/** Recurring invoices: each writes a draft on its day and nothing else. */
function Recurring({ clients }: { clients: Company[] }) {
  const qc = useQueryClient();
  const schedules = useQuery<InvoiceSchedule[]>({
    queryKey: ["invoice-schedules"],
    queryFn: () => api.get<InvoiceSchedule[]>("/api/invoice-schedules/") });
  const [adding, setAdding] = useState(false);
  const [company, setCompany] = useState("");
  const [contact, setContact] = useState("");
  const [day, setDay] = useState("1");
  const [lines, setLines] = useState<InvoiceLine[]>([
    { description: "", quantity: "1", unit_price_cents: 0 }]);
  const people = useRecipients(company);
  const done = () => qc.invalidateQueries({ queryKey: ["invoice-schedules"] });
  const save = useMutation({
    mutationFn: () => api.post<InvoiceSchedule>("/api/invoice-schedules/", {
      client_company: company, contact, day_of_month: Number(day), lines: cleanLines(lines) }),
    onSuccess: () => {
      done(); setAdding(false); setCompany(""); setContact("");
      setLines([{ description: "", quantity: "1", unit_price_cents: 0 }]);
    },
  });
  const toggle = useMutation({
    mutationFn: (row: InvoiceSchedule) => api.patch<InvoiceSchedule>(
      `/api/invoice-schedules/${row.id}/`, { is_active: !row.is_active }),
    onSuccess: done,
  });
  const rows = schedules.data ?? [];
  return (
    <Card title="Recurring invoices"
      actions={!adding && <button className="small" onClick={() => setAdding(true)}>
        New recurring invoice</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        On its day each month a recurring invoice writes a draft. It does not number it and
        does not send it: you check the draft and make it ready, as for any other.
      </p>
      {rows.length === 0 && !adding && <Empty>No recurring invoices.</Empty>}
      {rows.length > 0 && (
        <table>
          <thead><tr><th>Client</th><th>Addressed to</th><th>Day</th><th>Next draft</th>
            <th className="money">Each month</th><th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.client_company.name}</td>
                <td>{row.contact.name}</td>
                <td>{row.day_of_month}</td>
                <td>{row.is_active ? longDate(row.next_on) : <Pill>paused</Pill>}</td>
                <td className="money">{dollars(row.total_cents)}</td>
                <td className="money">
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
      {adding && (
        <div className="card">
          {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
          <div className="row">
            <Field label="Client company">
              <select aria-label="Client company for the recurring invoice" value={company}
                onChange={(e) => { setCompany(e.target.value); setContact(""); }}>
                <option value="">Choose a client</option>
                {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Addressed to">
              <select aria-label="Recurring invoice addressed to" value={contact}
                disabled={people.length === 0} onChange={(e) => setContact(e.target.value)}>
                <option value="">Choose a person</option>
                {people.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
              </select>
            </Field>
            <Field label="Day of the month (1 to 28)">
              <input type="number" min={1} max={28} aria-label="Day of the month" value={day}
                style={{ width: "5rem" }} onChange={(e) => setDay(e.target.value)} />
            </Field>
          </div>
          <InvoiceLines lines={lines} onChange={setLines} />
          <div className="row tight" style={{ marginTop: "var(--s3)" }}>
            <button className="primary"
              disabled={!company || !contact || cleanLines(lines).length === 0 || save.isPending}
              onClick={() => save.mutate()}>Save the recurring invoice</button>
            <button className="ghost" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}
    </Card>
  );
}
