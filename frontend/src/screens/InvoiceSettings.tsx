import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Flash, useFlash } from "../components/ui";
import { InvoiceSettingsData, api } from "../lib/api";

/** Settings → Invoices (matrix 13.4f): the practice owner's. Numbering, what
 *  a new invoice starts with, and how a client is told to pay. */
export function InvoiceSettings() {
  const qc = useQueryClient();
  const settings = useQuery<InvoiceSettingsData>({
    queryKey: ["invoice-settings"],
    queryFn: () => api.get<InvoiceSettingsData>("/api/invoice-settings/") });
  const [form, setForm] = useState<InvoiceSettingsData | null>(null);
  const [saved, flash] = useFlash();
  useEffect(() => { if (settings.data) setForm(settings.data); }, [settings.data]);
  const save = useMutation({
    mutationFn: (f: InvoiceSettingsData) => api.post<InvoiceSettingsData>(
      "/api/invoice-settings/", {
        prefix: f.prefix, next_value: Number(f.next_value), terms_days: Number(f.terms_days),
        default_notes: f.default_notes, default_terms: f.default_terms,
        pay_instructions: f.pay_instructions, email_subject: f.email_subject,
        email_body: f.email_body }),
    onSuccess: (data) => { qc.setQueryData(["invoice-settings"], data); flash("Saved"); },
  });
  if (!form) return <p>Loading the invoice settings…</p>;
  const set = (patch: Partial<InvoiceSettingsData>) => setForm({ ...form, ...patch });
  const area = (label: string, field: "pay_instructions" | "default_notes" | "default_terms"
                | "email_body", rows = 3) => (
    <Field label={label}>
      <textarea rows={rows} aria-label={label} value={form[field]}
        onChange={(e) => set({ [field]: e.target.value })} />
    </Field>
  );
  return (
    <>
      <PageHead title="Invoices"
        sub="How your invoices are numbered, what a new one starts with, and how your
             clients are told to pay." />
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <Card title="How to pay">
        <p className="small muted" style={{ marginTop: 0 }}>
          Printed on every invoice. Nothing is charged through the app, so this is how a
          client knows where to send the money. An invoice cannot be made ready without it.
        </p>
        {area("How to pay", "pay_instructions", 4)}
      </Card>
      <Card title="Numbering">
        <div className="row">
          <Field label="Prefix">
            <input aria-label="Number prefix" value={form.prefix} maxLength={12}
              onChange={(e) => set({ prefix: e.target.value })} />
          </Field>
          <Field label="Next number">
            <input type="number" min={1} aria-label="Next number" value={form.next_value}
              onChange={(e) => set({ next_value: Number(e.target.value) })} />
          </Field>
          <Field label="Payment due, in days">
            <input type="number" min={0} max={365} aria-label="Payment terms in days"
              value={form.terms_days} onChange={(e) => set({ terms_days: Number(e.target.value) })} />
          </Field>
        </div>
        <p className="tiny muted" style={{ marginBottom: 0 }}>
          The next invoice made ready will be {settings.data?.next_number}. The next number
          can be raised, to carry on from another system, and never lowered: a lower one may
          already be on an invoice.
        </p>
      </Card>
      <Card title="What a new invoice starts with">
        {area("Notes", "default_notes")}
        {area("Terms", "default_terms")}
        <p className="small muted">The email. You can use{" "}
          {form.merge_fields.map((f) => `{${f}}`).join(", ")}.</p>
        <Field label="Subject">
          <input aria-label="Email subject" value={form.email_subject} maxLength={200}
            onChange={(e) => set({ email_subject: e.target.value })} />
        </Field>
        {area("Message", "email_body", 6)}
      </Card>
      <div className="row tight">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate(form)}>
          {save.isPending ? "Saving…" : "Save"}</button>
        <Flash text={saved} />
      </div>
    </>
  );
}
