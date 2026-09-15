import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Field } from "../components/ui";
import { Company, Contact, Me, api } from "../lib/api";

/**
 * FR-1.3 — add one company by hand.
 *
 * `is_client_company` is deliberately absent: FR-1.6a derives it from a contact
 * reaching a `won` stage in the sales pipeline, one way only. A checkbox here
 * would be a second source of truth for exactly the thing that invariant exists
 * to keep single.
 */
export function AddCompany({ me, onDone, existing, people = [] }: {
  me: Me;
  onDone: (c: Company) => void;
  /** When present the form EDITS this company instead of creating one. */
  existing?: Company;
  /** This company's own contacts: the only people who may be its primary contact. */
  people?: Contact[];
}) {
  const qc = useQueryClient();
  const editing = !!existing;
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    name: existing?.name ?? "",
    industry: existing?.industry ?? "",
    domains: (existing?.domains ?? []).join(", "),
    address: ((existing?.address as { lines?: string[] } | null)?.lines ?? []).join("\n"),
    seat_count: existing?.seat_count != null ? String(existing.seat_count) : "",
    primary_contact: existing?.primary_contact ?? "",
  });

  const isFF = me.role === "FF";
  // Matrix 4.8 — FF or CF. A new company has no contacts yet, so edit only.
  const maySetPrimary = editing && (me.role === "FF" || me.role === "CF");
  const theirs = people.filter((p) => p.company === existing?.id);
  const current = people.find((p) => p.id === existing?.primary_contact);

  const save = useMutation({
    mutationFn: () => {
      const primary = form.primary_contact || null;
      const body = {
        name: form.name.trim(),
        industry: form.industry.trim(),
        domains: form.domains.split(/[,;\s]+/).map((d) => d.trim()).filter(Boolean),
        address: form.address.trim() ? { lines: form.address.split("\n") } : null,
        ...(isFF && form.seat_count ? { seat_count: Number(form.seat_count) } : {}),
        // Sent only when changed, so saving other fields never touches it.
        ...(maySetPrimary && primary !== (existing?.primary_contact ?? null)
          ? { primary_contact: primary } : {}),
      };
      return editing
        ? api.patch<Company>(`/api/companies/${existing!.id}/`, body)
        : api.post<Company>("/api/companies/", body);
    },
    onSuccess: (company) => {
      qc.invalidateQueries({ queryKey: ["companies"] });
      onDone(company);
    },
    onError: (e: Error & { data?: Record<string, unknown> }) => {
      const detail = e.data
        ? Object.entries(e.data).map(([k, v]) => `${k}: ${[v].flat().join(" ")}`).join(" · ")
        : e.message;
      setError(detail || e.message);
    },
  });

  return (
    <Card title={editing ? "Edit company" : "Add a company"} actions={
      <button onClick={() => onDone(null as unknown as Company)}>Cancel</button>
    }>
      {error && <Banner kind="bad">{error}</Banner>}

      <form onSubmit={(e) => { e.preventDefault(); setError(""); save.mutate(); }}>
        <div className="row">
          <Field label="Name">
            <input value={form.name} aria-label="Name"
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Industry">
            <input value={form.industry} aria-label="Industry"
              onChange={(e) => setForm({ ...form, industry: e.target.value })} />
          </Field>
        </div>

        <Field label="Email domains">
          <input value={form.domains} aria-label="Email domains"
            placeholder="acme.com, acme.co.uk"
            onChange={(e) => setForm({ ...form, domains: e.target.value })} />
          <p className="muted small" style={{ marginBottom: 0 }}>
            Used to match imported contacts to this company by their email address.
          </p>
        </Field>

        <Field label="Address">
          <textarea rows={3} value={form.address} aria-label="Address"
            onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </Field>

        {maySetPrimary && (
          <Field label="Primary contact">
            <select aria-label="Primary contact" value={form.primary_contact}
              onChange={(e) => setForm({ ...form, primary_contact: e.target.value })}>
              <option value="">No primary contact</option>
              {existing?.primary_contact && !theirs.some((p) => p.id === existing.primary_contact) && (
                <option value={existing.primary_contact}>Current (no longer listed at this company)</option>
              )}
              {theirs.map((p) => (
                <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>
              ))}
            </select>
            <p className="muted small" style={{ marginBottom: 0 }}>
              One of this company's own contacts. Portal access offers them as the founder
              user; changing it does not change anyone's existing portal role.
            </p>
          </Field>
        )}
        {editing && !maySetPrimary && (
          <p className="muted small">
            Primary contact: {current ? `${current.first_name} ${current.last_name}` : "none"}.
            Only the founder fractional or a CF changes it.
          </p>
        )}

        {isFF && (
          <Field label="Client seat count">
            <input type="number" min={0} value={form.seat_count} aria-label="Client seat count"
              onChange={(e) => setForm({ ...form, seat_count: e.target.value })} />
            <p className="muted small" style={{ marginBottom: 0 }}>
              Optional. Seats in use are counted from live logins, never stored.
            </p>
          </Field>
        )}

        <p className="muted small">
          <strong>Client company</strong> is not set here. It is derived when one of
          their contacts reaches the sales pipeline's won stage (FR-1.6a), so there is
          only ever one answer to “is this a client”.
        </p>

        <button className="primary" type="submit"
          disabled={!form.name.trim() || save.isPending}>
          {save.isPending ? "Saving…" : editing ? "Save changes" : "Save company"}
        </button>
      </form>
    </Card>
  );
}
