import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty } from "../components/ui";
import { api } from "../lib/api";

interface TagRow { tag: string; contacts: number }
interface Changed { changed: number; tags: TagRow[] }

/**
 * Settings, Tags (owner, 2026-10-12). A tag is added on a contact, as it
 * always was; here the practice owner changes one everywhere it is used:
 * rename it (onto a tag that already exists, the two become one) or remove it.
 */
export function ContactTags() {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState("");
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState("");
  const tags = useQuery<TagRow[]>({
    queryKey: ["contact-tags"], queryFn: () => api.get<TagRow[]>("/api/contact-tags/"),
  });
  const done = (said: string) => (result: Changed) => {
    setEditing(""); setRemoving(""); setError("");
    setNote(`${said} on ${result.changed} contact${result.changed === 1 ? "" : "s"}.`);
    qc.setQueryData(["contact-tags"], result.tags);
    qc.invalidateQueries({ queryKey: ["contacts"] });
  };
  const rename = useMutation({
    mutationFn: (tag: string) =>
      api.post<Changed>("/api/contact-tags/rename/", { tag, to: name.trim() }),
    onSuccess: (result) => done("Renamed")(result),
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: (tag: string) => api.post<Changed>("/api/contact-tags/remove/", { tag }),
    onSuccess: (result) => done("Removed")(result),
    onError: (e: Error) => setError(e.message),
  });
  const rows = tags.data ?? [];
  const merging = (tag: string) => rows.some((r) => r.tag === name.trim() && r.tag !== tag);

  return (
    <>
      <PageHead title="Tags"
        sub="The tags on your contacts. Add one on a contact; rename or remove one here and
             it changes on every contact that has it." />
      {note && <Banner kind="ok">{note}</Banner>}
      {error && <Banner kind="bad">{error}</Banner>}
      <Card>
        {tags.isLoading ? <p>Loading…</p> : rows.length === 0 ? (
          <Empty>No tags yet. Add one on a contact, in its Tags field.</Empty>
        ) : (
          <table aria-label="Tags">
            <thead><tr><th>Tag</th><th>Contacts</th><th /></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.tag}>
                  <td>
                    {editing === row.tag ? (
                      <input aria-label={`New name for ${row.tag}`} value={name} maxLength={64}
                        autoFocus onChange={(e) => setName(e.target.value)} />
                    ) : row.tag}
                    {editing === row.tag && merging(row.tag) && (
                      <div className="small muted">
                        "{name.trim()}" exists already: the two will become one tag.</div>
                    )}
                    {removing === row.tag && (
                      <div className="small">
                        Remove "{row.tag}" from {row.contacts} contact
                        {row.contacts === 1 ? "" : "s"}? The contacts stay.</div>
                    )}
                  </td>
                  <td>{row.contacts}</td>
                  <td className="right">
                    {editing === row.tag ? (
                      <span className="row tight" style={{ justifyContent: "flex-end" }}>
                        <button className="primary small"
                          disabled={!name.trim() || name.trim() === row.tag || rename.isPending}
                          onClick={() => rename.mutate(row.tag)}>Save</button>
                        <button className="small" onClick={() => setEditing("")}>Cancel</button>
                      </span>
                    ) : removing === row.tag ? (
                      <span className="row tight" style={{ justifyContent: "flex-end" }}>
                        <button className="primary small" disabled={remove.isPending}
                          onClick={() => remove.mutate(row.tag)}>Remove it</button>
                        <button className="small" onClick={() => setRemoving("")}>Cancel</button>
                      </span>
                    ) : (
                      <span className="row tight" style={{ justifyContent: "flex-end" }}>
                        <button className="ghost small" aria-label={`Rename ${row.tag}`}
                          onClick={() => { setEditing(row.tag); setName(row.tag);
                                           setRemoving(""); setNote(""); }}>Rename</button>
                        <button className="ghost small" aria-label={`Remove ${row.tag}`}
                          onClick={() => { setRemoving(row.tag); setEditing("");
                                           setNote(""); }}>Remove</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
