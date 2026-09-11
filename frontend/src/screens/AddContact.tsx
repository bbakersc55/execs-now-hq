import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Field } from "../components/ui";
import { Company, Contact, ContactType, Me, Pipeline, api } from "../lib/api";

interface Row { value: string; is_primary: boolean }

const blank = (): Row => ({ value: "", is_primary: false });

/**
 * FR-1.1 / FR-1.2 / FR-1.3 — add one contact by hand.
 *
 * Everything a contact *is* is on one form: a person with two email addresses
 * and a company is one record, and making the user save four times to build
 * them would be a worse experience than the spreadsheet they are leaving.
 */
export function AddContact({ me, onDone, existing }: {
  me: Me;
  onDone: (c: Contact) => void;
  /** When present the form EDITS this contact instead of creating one. */
  existing?: Contact;
}) {
  const qc = useQueryClient();
  const editing = !!existing;
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    first_name: existing?.first_name ?? "",
    last_name: existing?.last_name ?? "",
    title: existing?.title ?? "",
    source: existing?.source ?? "",
    background: existing?.background ?? "",
    company: existing?.company ?? "",
    company_name: "",
    tags: (existing?.tags ?? []).join(", "),
    owner: existing?.owner ?? "",
  });
  const [emails, setEmails] = useState<Row[]>(
    existing && existing.emails.length
      ? existing.emails.map((e) => ({ value: e.address, is_primary: e.is_primary }))
      : [{ ...blank(), is_primary: true }],
  );
  const [phones, setPhones] = useState<Row[]>(
    existing && existing.phones.length
      ? existing.phones.map((p) => ({ value: p.number, is_primary: p.is_primary }))
      : [{ ...blank(), is_primary: true }],
  );
  const [types, setTypes] = useState<string[]>(existing?.type_codes ?? []);
  const [pipelineId, setPipelineId] = useState("");
  const [stageCode, setStageCode] = useState("");

  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
  });
  const contactTypes = useQuery<ContactType[]>({
    queryKey: ["contact-types"], queryFn: () => api.get<ContactType[]>("/api/contact-types/"),
  });
  const pipelines = useQuery<Pipeline[]>({
    queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines/"),
  });

  const stages = pipelines.data?.find((p) => p.id === pipelineId)?.stages ?? [];

  const staff = useQuery<{ id: string; full_name: string; email: string }[]>({
    queryKey: ["staff"], queryFn: () => api.get("/api/staff/"),
    enabled: editing && me.role === "FF",
  });

  const save = useMutation({
    mutationFn: () => {
      const body = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      title: form.title.trim(),
      source: form.source.trim(),
      background: form.background.trim(),
      company: form.company || null,
      company_name: form.company ? "" : form.company_name.trim(),
      tags: form.tags.split(/[,;]/).map((t) => t.trim()).filter(Boolean),
      emails: emails.filter((e) => e.value.trim())
        .map((e) => ({ address: e.value.trim(), is_primary: e.is_primary })),
      phones: phones.filter((p) => p.value.trim())
        .map((p) => ({ number: p.value.trim(), is_primary: p.is_primary })),
      types,
      ...(pipelineId && stageCode
        ? { placement: { pipeline: pipelineId, stage: stageCode } }
        : {}),
      // FR-1.1 — only an FF may reassign a contact's owner (matrix 4.11's
      // sibling: ownership drives a CF's whole visible universe).
      ...(editing && me.role === "FF" && form.owner ? { owner: form.owner } : {}),
      };
      return editing
        ? api.patch<Contact>(`/api/contacts/${existing!.id}/`, body)
        : api.post<Contact>("/api/contacts/", body);
    },
    onSuccess: (contact) => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["board"] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
      onDone(contact);
    },
    onError: (e: Error & { data?: Record<string, unknown> }) => {
      // Show the field message the API gave, not a generic failure.
      const detail = e.data
        ? Object.entries(e.data).map(([k, v]) => `${k}: ${[v].flat().join(" ")}`).join(" · ")
        : e.message;
      setError(detail || e.message);
    },
  });

  /** Exactly one primary, always — the database enforces it too. */
  function markPrimary(rows: Row[], index: number) {
    return rows.map((r, i) => ({ ...r, is_primary: i === index }));
  }

  const named = form.first_name.trim() || form.last_name.trim();

  return (
    <Card title={editing ? "Edit contact" : "Add a contact"} actions={
      <button onClick={() => onDone(null as unknown as Contact)}>Cancel</button>
    }>
      {error && <Banner kind="bad">{error}</Banner>}

      <form onSubmit={(e) => { e.preventDefault(); setError(""); save.mutate(); }}>
        <div className="row">
          <Field label="First name">
            <input value={form.first_name} aria-label="First name"
              onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          </Field>
          <Field label="Last name">
            <input value={form.last_name} aria-label="Last name"
              onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          </Field>
          <Field label="Title">
            <input value={form.title} aria-label="Title"
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
        </div>

        <fieldset>
          <legend className="small">Email addresses</legend>
          {emails.map((row, i) => (
            <div className="row" key={i}>
              <input value={row.value} placeholder="name@example.com"
                aria-label={`Email ${i + 1}`}
                onChange={(e) => setEmails(emails.map((r, j) =>
                  j === i ? { ...r, value: e.target.value } : r))} />
              <label className="small" style={{ flex: "0 0 auto" }}>
                <input type="radio" name="primary-email" checked={row.is_primary}
                  aria-label={`Make email ${i + 1} primary`}
                  onChange={() => setEmails(markPrimary(emails, i))} /> primary
              </label>
              {emails.length > 1 && (
                <button type="button" className="ghost" style={{ flex: "0 0 auto" }}
                  aria-label={`Remove email ${i + 1}`}
                  onClick={() => setEmails(emails.filter((_, j) => j !== i))}>
                  Remove
                </button>
              )}
            </div>
          ))}
          <button type="button" className="ghost"
            onClick={() => setEmails([...emails, blank()])}>
            Add another email
          </button>
        </fieldset>

        <fieldset>
          <legend className="small">Phone numbers</legend>
          {phones.map((row, i) => (
            <div className="row" key={i}>
              <input value={row.value} placeholder="+1 555 0100"
                aria-label={`Phone ${i + 1}`}
                onChange={(e) => setPhones(phones.map((r, j) =>
                  j === i ? { ...r, value: e.target.value } : r))} />
              <label className="small" style={{ flex: "0 0 auto" }}>
                <input type="radio" name="primary-phone" checked={row.is_primary}
                  aria-label={`Make phone ${i + 1} primary`}
                  onChange={() => setPhones(markPrimary(phones, i))} /> primary
              </label>
              {phones.length > 1 && (
                <button type="button" className="ghost" style={{ flex: "0 0 auto" }}
                  aria-label={`Remove phone ${i + 1}`}
                  onClick={() => setPhones(phones.filter((_, j) => j !== i))}>
                  Remove
                </button>
              )}
            </div>
          ))}
          <button type="button" className="ghost"
            onClick={() => setPhones([...phones, blank()])}>
            Add another phone
          </button>
        </fieldset>

        <div className="row">
          <Field label="Company">
            <select value={form.company} aria-label="Company"
              onChange={(e) => setForm({ ...form, company: e.target.value })}>
              <option value="">— none, or type a new one below —</option>
              {(companies.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </Field>
          <Field label="…or a new company">
            <input value={form.company_name} disabled={!!form.company}
              aria-label="New company name" placeholder="Creates it on save"
              onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
          </Field>
        </div>

        <Field label="Types">
          <div className="row">
            {(contactTypes.data ?? []).map((t) => (
              <label key={t.code} className="small" style={{ flex: "0 0 auto" }}>
                <input type="checkbox" checked={types.includes(t.code)}
                  aria-label={t.label}
                  onChange={(e) => setTypes(e.target.checked
                    ? [...types, t.code]
                    : types.filter((c) => c !== t.code))} />{" "}
                {t.label}
              </label>
            ))}
          </div>
          {types.includes("referral_partner") && (
            <p className="muted small">
              Saving will queue their onboarding email in the Outbox for approval and
              place them in the referral pipeline. It does not send anything.
            </p>
          )}
        </Field>

        <div className="row">
          <Field label="Source">
            <input value={form.source} aria-label="Source" placeholder="Referral, webinar…"
              onChange={(e) => setForm({ ...form, source: e.target.value })} />
          </Field>
          <Field label="Tags">
            <input value={form.tags} aria-label="Tags" placeholder="comma or semicolon separated"
              onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </Field>
        </div>

        <Field label="Background">
          <textarea rows={2} value={form.background} aria-label="Background"
            placeholder="Who this is / how we met"
            onChange={(e) => setForm({ ...form, background: e.target.value })} />
        </Field>

        <div className="row">
          <Field label="Put them in a pipeline (optional)">
            <select value={pipelineId} aria-label="Pipeline"
              onChange={(e) => { setPipelineId(e.target.value); setStageCode(""); }}>
              <option value="">— not yet —</option>
              {(pipelines.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="At stage">
            <select value={stageCode} disabled={!pipelineId} aria-label="Stage"
              onChange={(e) => setStageCode(e.target.value)}>
              <option value="">— choose —</option>
              {stages.slice().sort((a, b) => a.position - b.position).map((s) => (
                <option key={s.id} value={s.code}>{s.label}</option>
              ))}
            </select>
          </Field>
        </div>

        {!editing && (
          <p className="muted small">
            Owner defaults to you ({me.full_name || me.email}).
          </p>
        )}

        {editing && me.role === "FF" && (
          <Field label="Owner">
            <select value={form.owner} aria-label="Owner"
              onChange={(e) => setForm({ ...form, owner: e.target.value })}>
              <option value="">— unassigned —</option>
              {(staff.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>{u.full_name || u.email}</option>
              ))}
            </select>
          </Field>
        )}

        <button className="primary" type="submit" disabled={!named || save.isPending}>
          {save.isPending ? "Saving…" : editing ? "Save changes" : "Save contact"}
        </button>
      </form>
    </Card>
  );
}
