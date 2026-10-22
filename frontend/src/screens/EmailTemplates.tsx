import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";

import { RichText, insertMergeField } from "../components/RichText";
import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { EmailTemplate, TEMPLATE_FIELDS, TemplateUse, api } from "../lib/api";

/** The merge fields, as buttons that drop a chip at the cursor. In one
 *  email's composer (`oneEmail`), a field that has a value only in another
 *  kind of email is listed greyed, saying where, and cannot be dropped in. */
export function MergeFieldBar({ fields = TEMPLATE_FIELDS, fallback, onFallback, oneEmail = false }: {
  fields?: { field: string; label: string; only?: string }[];
  fallback?: string;
  onFallback?: (value: string) => void;
  oneEmail?: boolean;
}) {
  const usable = oneEmail ? fields.filter((f) => !f.only) : fields;
  const elsewhere = oneEmail ? fields.filter((f) => f.only) : [];
  return (
    <div className="merge-fields" aria-label="Merge fields">
      <span className="small muted">Insert at the cursor:</span>
      {usable.map(({ field, label }) => (
        <button key={field} type="button" className="small ghost" title={label}
          onMouseDown={(e) => { e.preventDefault(); insertMergeField(field); }}>
          {field}
        </button>
      ))}
      {elsewhere.map(({ field, only }) => (
        <span key={field} className="small muted" aria-disabled="true"
          aria-label={`${field}, ${only}`} style={{ opacity: 0.6 }}>
          {field} <span className="tiny">({only})</span>
        </span>
      ))}
      {onFallback && (
        <label className="inline small">If a first name is missing, use:
          <input aria-label="If a first name is missing, use" style={{ width: "7rem" }}
            value={fallback ?? "there"} onChange={(e) => onFallback(e.target.value)} />
        </label>
      )}
    </div>
  );
}

type Draft = Pick<EmailTemplate, "name" | "subject" | "body" | "first_name_fallback">;

/**
 * Email templates (owner, 2026-10-20): the practice's one library. Stage
 * rules, referral touches, a new partner's first email, the thank-yous and
 * "Email these contacts" all pick from it; a campaign can start from one.
 * Plain text with merge fields; the signature is added to each email.
 */
export function EmailTemplates() {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<string>("");
  const [draft, setDraft] = useState<Partial<Draft>>({});
  const [note, setNote] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const list = useQuery<EmailTemplate[]>({
    queryKey: ["templates"], queryFn: () => api.get<EmailTemplate[]>("/api/email-templates/"),
  });
  const rows = list.data ?? [];
  const current = rows.find((t) => t.id === chosen) ?? rows[0];
  useEffect(() => { setDraft({}); }, [current?.id]);
  const t = current ? { ...current, ...draft } : null;
  const dirty = Object.keys(draft).length > 0;

  const refresh = (saved?: EmailTemplate) => {
    if (saved) setChosen(saved.id);
    setDraft({});
    qc.invalidateQueries({ queryKey: ["templates"] });
  };
  const fail = (e: Error) => setNote({ kind: "bad", text: e.message });
  const save = useMutation({
    mutationFn: () => api.patch<EmailTemplate>(`/api/email-templates/${current!.id}/`, draft),
    onSuccess: (saved) => { refresh(saved); setNote({ kind: "ok", text: "Saved." }); },
    onError: fail,
  });
  const create = useMutation({
    mutationFn: () => api.post<EmailTemplate>("/api/email-templates/", {
      name: "New template", subject: "A note from {PracticeName}", body: "Hi {FirstName},\n\n",
    }),
    onSuccess: (made) => { refresh(made); setNote({ kind: "ok", text: "Template added." }); },
    onError: fail,
  });
  const restore = useMutation({
    mutationFn: () => api.post<EmailTemplate>(`/api/email-templates/${current!.id}/restore/`),
    onSuccess: (saved) => {
      refresh(saved); setNote({ kind: "ok", text: "The original wording is back." });
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/email-templates/${current!.id}/`),
    onSuccess: () => { setChosen(""); refresh(); setNote({ kind: "ok", text: "Deleted." }); },
    onError: fail,
  });
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <PageHead title="Email templates"
        sub="The practice's words for the emails it drafts. Stage rules, referral touches, a new
             partner's first email, the thank-yous and “Email these contacts” use them; a
             campaign can start from one. Your signature is added to each email."
        action={
          <button className="primary" disabled={create.isPending}
            onClick={() => create.mutate()}><Plus size={16} /> New template</button>
        } />
      {note && <Banner kind={note.kind}>{note.text}</Banner>}
      {rows.length === 0 ? <Card><Empty>{list.isLoading ? "Loading…" : "No templates yet."}</Empty></Card> : (
        <div className="template-library">
          <Card title="Templates">
            <ul className="template-list" aria-label="Templates">
              {rows.map((row) => (
                <li key={row.id}>
                  <button type="button" aria-current={row.id === current?.id ? "true" : undefined}
                    className={row.id === current?.id ? "template-pick on" : "template-pick"}
                    onClick={() => setChosen(row.id)}>
                    <span className="template-name">{row.name}</span>
                    <span className="template-tags">
                      {row.is_original && <Pill kind={row.changed ? "warn" : ""}>
                        {row.changed ? "Built-in, changed" : "Built-in"}</Pill>}
                      {row.used_for.length === 0 && !row.is_original
                        && <Pill>Not in use</Pill>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {t && (
            <Card title={t.name}>
              <Field label="Name">
                <input aria-label="Name" value={t.name} onChange={(e) => set({ name: e.target.value })} />
              </Field>
              <Field label="Subject">
                <input aria-label="Subject" value={t.subject}
                  onChange={(e) => set({ subject: e.target.value })} />
              </Field>
              <MergeFieldBar fallback={t.first_name_fallback}
                onFallback={(value) => set({ first_name_fallback: value })} />
              <RichText plain key={t.id} label="Template body" value={t.body}
                onChange={(text) => set({ body: text })} />
              <p className="small muted">
                A line that is only merge fields with nothing to fill them is left out of the
                email, so {"{PracticeNews}"} or {"{FeeTerms}"} with nothing to say leaves no gap.
              </p>
              {t.used_for.length > 0 && (
                <p className="small"><strong>Used for:</strong> {t.used_for.join("; ")}.</p>
              )}
              <div className="row tight">
                <button className="primary" disabled={!dirty || save.isPending}
                  onClick={() => save.mutate()}>
                  <Save size={16} /> {save.isPending ? "Saving…" : dirty ? "Save" : "Saved"}
                </button>
                {t.is_original && (
                  <button disabled={(!t.changed && !dirty) || restore.isPending}
                    onClick={() => restore.mutate()}>
                    <RotateCcw size={16} /> Restore the original
                  </button>
                )}
                {!t.is_original && (
                  <button className="danger" disabled={remove.isPending || t.used_for.length > 0}
                    title={t.used_for.length > 0 ? "In use: choose another there first" : undefined}
                    onClick={() => remove.mutate()}><Trash2 size={16} /> Delete</button>
                )}
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  );
}

/** Which template each practice-wide email uses (Referral settings). */
export function TemplateUses({ onNote }: { onNote: (text: string) => void }) {
  const qc = useQueryClient();
  const uses = useQuery<{ uses: TemplateUse[] }>({
    queryKey: ["template-uses"],
    queryFn: () => api.get<{ uses: TemplateUse[] }>("/api/email-templates/uses/"),
  });
  const templates = useQuery<EmailTemplate[]>({
    queryKey: ["templates"], queryFn: () => api.get<EmailTemplate[]>("/api/email-templates/"),
  });
  const choose = useMutation({
    mutationFn: (body: { use: string; template: string }) =>
      api.post<{ uses: TemplateUse[] }>("/api/email-templates/uses/", body),
    onSuccess: (r) => {
      qc.setQueryData(["template-uses"], r);
      qc.invalidateQueries({ queryKey: ["templates"] });
      onNote("Template chosen. New drafts use it.");
    },
    onError: (e: Error) => onNote(e.message),
  });
  return (
    <Card title="Which template each email uses">
      <p className="muted small">
        The words are under <Link to="/settings/templates">Email templates</Link>. A partner
        can also have a touch template of their own, on their page.
      </p>
      <table>
        <tbody>
          {(uses.data?.uses ?? []).map((u) => (
            <tr key={u.use}>
              <td>{u.label}</td>
              <td>
                <select aria-label={u.label} value={u.template} disabled={choose.isPending}
                  onChange={(e) => choose.mutate({ use: u.use, template: e.target.value })}>
                  {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
