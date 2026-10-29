import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";

import { RichText } from "../components/RichText";
import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import { DocumentTemplate, api } from "../lib/api";
import { MergeFieldBar } from "./EmailTemplates";

type Draft = Pick<DocumentTemplate, "name" | "title" | "body">;

/**
 * Settings → Documents (e-signature, 2026-10-29): the practice's proposals
 * and engagement letters, in the email templates' editor with the same merge
 * chips, plus the document's own: {Scope}, {Fee}, {Term}, {StartDate}. The
 * two built-ins can be restored. A line starting "# " is a heading.
 */
export function DocumentTemplates() {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState("");
  const [draft, setDraft] = useState<Partial<Draft>>({});
  const [note, setNote] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const list = useQuery<DocumentTemplate[]>({
    queryKey: ["document-templates"],
    queryFn: () => api.get<DocumentTemplate[]>("/api/document-templates/"),
  });
  const fields = useQuery<{ field: string; label: string }[]>({
    queryKey: ["document-template-fields"],
    queryFn: () => api.get<{ field: string; label: string }[]>("/api/document-templates/fields/"),
  });
  const rows = list.data ?? [];
  const current = rows.find((t) => t.id === chosen) ?? rows[0];
  useEffect(() => { setDraft({}); }, [current?.id]);
  const t = current ? { ...current, ...draft } : null;
  const dirty = Object.keys(draft).length > 0;

  const refresh = (saved?: DocumentTemplate) => {
    if (saved) setChosen(saved.id);
    setDraft({});
    qc.invalidateQueries({ queryKey: ["document-templates"] });
  };
  const fail = (e: Error) => setNote({ kind: "bad", text: e.message });
  const save = useMutation({
    mutationFn: () => api.patch<DocumentTemplate>(`/api/document-templates/${current!.id}/`, draft),
    onSuccess: (saved) => { refresh(saved); setNote({ kind: "ok", text: "Saved." }); },
    onError: fail,
  });
  const create = useMutation({
    mutationFn: () => api.post<DocumentTemplate>("/api/document-templates/", {
      name: "New document", title: "Agreement",
      body: "Prepared for {FirstName} {LastName}, {Company}\n\n# Scope of work\n{Scope}\n",
    }),
    onSuccess: (made) => { refresh(made); setNote({ kind: "ok", text: "Template added." }); },
    onError: fail,
  });
  const restore = useMutation({
    mutationFn: () => api.post<DocumentTemplate>(`/api/document-templates/${current!.id}/restore/`),
    onSuccess: (saved) => { refresh(saved); setNote({ kind: "ok", text: "The original wording is back." }); },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/document-templates/${current!.id}/`),
    onSuccess: () => { setChosen(""); refresh(); setNote({ kind: "ok", text: "Deleted." }); },
    onError: fail,
  });
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  return (
    <>
      <PageHead title="Documents"
        sub="Proposals and engagement letters, sent for signature from a company's page. The
             signer's details and the fields you fill in when you send one are merged in."
        action={<button className="primary" disabled={create.isPending}
          onClick={() => create.mutate()}><Plus size={16} /> New template</button>} />
      {note && <Banner kind={note.kind}>{note.text}</Banner>}
      {rows.length === 0 ? <Card><Empty>{list.isLoading ? "Loading…" : "No templates yet."}</Empty></Card> : (
        <div className="template-library">
          <Card title="Templates">
            <ul className="template-list" aria-label="Document templates">
              {rows.map((row) => (
                <li key={row.id}>
                  <button type="button" aria-current={row.id === current?.id ? "true" : undefined}
                    className={row.id === current?.id ? "template-pick on" : "template-pick"}
                    onClick={() => setChosen(row.id)}>
                    <span className="template-name">{row.name}</span>
                    <span className="template-tags">
                      {row.is_original && <Pill kind={row.changed ? "warn" : ""}>
                        {row.changed ? "Built-in, changed" : "Built-in"}</Pill>}
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
              <Field label="Title on the document">
                <input aria-label="Title on the document" value={t.title}
                  onChange={(e) => set({ title: e.target.value })} />
              </Field>
              <MergeFieldBar fields={fields.data ?? []} />
              <RichText plain key={t.id} label="Document body" value={t.body}
                onChange={(text) => set({ body: text })} />
              <p className="small muted">
                A line starting with “# ” is a heading. {"{Scope}"}, {"{Fee}"}, {"{Term}"} and
                {" {StartDate}"} are asked for when the document is made; the signature page is
                added after the last page when it is signed.
              </p>
              {t.used_for.length > 0 && (
                <p className="small"><strong>Used by:</strong> {t.used_for.join("; ")}.</p>
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
