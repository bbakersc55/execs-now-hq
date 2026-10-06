import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { api } from "../lib/api";

/** GET /api/platform/practices — numbers and dates only (apps/platform/stats.py). */
export interface PracticeRow {
  id: string;
  display_name: string;
  legal_name: string;
  domain: string;
  status: "active" | "invited" | "archived";
  created_at: string;
  archived_at: string | null;
  oauth_client: "internal" | "external";
  staff_count: number;
  client_count: number;
  ai_spend_this_month_usd: string;
  last_activity_at: string | null;
}

const EMPTY = { legal_name: "", display_name: "", domain: "", owner_email: "" };
const STATUS_KIND: Record<string, string> = { active: "ok", invited: "warn", archived: "" };

/**
 * The Practices area (P2, owner 2026-10-02). The platform owner sees each
 * practice's record and its totals, and nothing inside it: no contacts, work,
 * notes, email, meetings or sessions. The server enforces that; this screen
 * only ever receives the numbers.
 */
export function Practices() {
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState({ legal_name: "", domain: "" });

  const list = useQuery<PracticeRow[]>({
    queryKey: ["platform-practices"],
    queryFn: () => api.get<PracticeRow[]>("/api/platform/practices"),
  });
  const done = (text: string) => {
    setProblem("");
    setNote(text);
    qc.invalidateQueries({ queryKey: ["platform-practices"] });
  };
  const failed = (e: Error) => { setNote(""); setProblem(e.message); };

  const create = useMutation({
    mutationFn: () => api.post<PracticeRow>("/api/platform/practices", form),
    onSuccess: (row) => {
      setForm(EMPTY);
      done(`${row.display_name} is set up. Its owner has not been invited yet.`);
    },
    onError: failed,
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "archive" | "unarchive" }) =>
      api.post<PracticeRow>(`/api/platform/practices/${id}/${action}`),
    onSuccess: (row, { action }) => done(action === "archive"
      ? `${row.display_name} is archived: nobody can sign in, nothing runs, all data is kept.`
      : `${row.display_name} is back.`),
    onError: failed,
  });
  // The answer to Invite shows in that practice's own row, where the button
  // was pressed: a refusal only at the top of the page went unseen (2026-10-03).
  const [rowNote, setRowNote] = useState<{ id: string; kind: "ok" | "bad"; text: string } | null>(null);
  const invite = useMutation({
    mutationFn: (id: string) =>
      api.post<{ sent_to: string }>(`/api/platform/practices/${id}/invite`),
    onMutate: () => setRowNote(null),
    onSuccess: (r, id) => setRowNote({ id, kind: "ok", text: `Invitation sent to ${r.sent_to}.` }),
    onError: (e: Error, id) => setRowNote({ id, kind: "bad", text: `Not sent: ${e.message}` }),
  });
  const save = useMutation({
    mutationFn: (id: string) => api.patch<PracticeRow>(`/api/platform/practices/${id}`, draft),
    onSuccess: (row) => { setEditing(null); done(`${row.display_name} updated.`); },
    onError: failed,
  });

  const rows = list.data ?? [];
  const set = (patch: Partial<typeof EMPTY>) => setForm({ ...form, ...patch });

  return (
    <>
      <PageHead title="Practices"
        sub={<>Every practice on the platform, with its totals. Nothing inside a practice is
          shown here, to you or anyone: its data is its own.</>} />
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}

      <Card title="Practices">
        {list.isError ? <Banner kind="bad">{(list.error as Error).message}</Banner>
          : rows.length === 0 ? <Empty>No practices yet.</Empty> : (
          <table>
            <thead><tr>
              <th>Practice</th><th>Status</th><th>Created</th><th>Team</th><th>Clients</th>
              <th>AI spend this month</th><th>Last activity</th><th></th>
            </tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.display_name}</strong>
                    {editing === p.id ? (
                      <div className="row" style={{ gap: "0.4rem", marginTop: "0.3rem" }}>
                        <input aria-label={`Legal name of ${p.display_name}`} value={draft.legal_name}
                          placeholder="Legal name"
                          onChange={(e) => setDraft({ ...draft, legal_name: e.target.value })} />
                        <input aria-label={`Domain of ${p.display_name}`} value={draft.domain}
                          placeholder="domain.com"
                          onChange={(e) => setDraft({ ...draft, domain: e.target.value })} />
                        <button className="primary" disabled={save.isPending}
                          onClick={() => save.mutate(p.id)}>Save</button>
                        <button className="ghost" onClick={() => setEditing(null)}>Cancel</button>
                      </div>
                    ) : (
                      <div className="muted small">
                        {p.legal_name || "No legal name yet"} · {p.domain || "no domain yet"}
                      </div>
                    )}
                  </td>
                  <td><Pill kind={STATUS_KIND[p.status]}>{p.status === "invited"
                    ? "Owner not signed in yet" : p.status === "active" ? "Active" : "Archived"}</Pill></td>
                  <td>{when(p.created_at)}</td>
                  <td>{p.staff_count}</td>
                  <td>{p.client_count}</td>
                  <td>${p.ai_spend_this_month_usd}</td>
                  <td>{p.last_activity_at ? when(p.last_activity_at) : "Never"}</td>
                  <td>
                    {editing !== p.id && (
                      <button className="ghost" onClick={() => {
                        setEditing(p.id);
                        setDraft({ legal_name: p.legal_name, domain: p.domain });
                      }}>Edit</button>
                    )}
                    {p.status === "invited" && (
                      <button className="ghost" disabled={invite.isPending}
                        onClick={() => invite.mutate(p.id)}>
                        {invite.isPending && invite.variables === p.id ? "Inviting…" : "Invite owner"}
                      </button>
                    )}
                    {rowNote?.id === p.id && (
                      <div role={rowNote.kind === "bad" ? "alert" : "status"}
                        style={{ maxWidth: "22rem", marginTop: "0.4rem" }}>
                        <Banner kind={rowNote.kind}>{rowNote.text}</Banner>
                      </div>
                    )}
                    {p.status === "archived" ? (
                      <button className="ghost" disabled={act.isPending}
                        onClick={() => act.mutate({ id: p.id, action: "unarchive" })}>
                        Unarchive</button>
                    ) : (
                      <button className="ghost" disabled={act.isPending} onClick={() => {
                        if (window.confirm(`Archive ${p.display_name}? Nobody in it can sign in `
                          + "and nothing runs or sends until you unarchive it. All of its data "
                          + "is kept.")) act.mutate({ id: p.id, action: "archive" });
                      }}>Archive</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Add a practice">
        <p className="muted small" style={{ marginTop: 0 }}>
          It starts empty, with default pipelines, digests held, AI spend limited to $50 a month
          and $5 a day unattended, and no strategy template. Nothing is sent to the owner until
          you invite them.
        </p>
        <div className="row" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
          <Field label="Legal name"><input aria-label="Legal name" value={form.legal_name}
            onChange={(e) => set({ legal_name: e.target.value })} /></Field>
          <Field label="Display name"><input aria-label="Display name" value={form.display_name}
            onChange={(e) => set({ display_name: e.target.value })} /></Field>
          <Field label="Domain"><input aria-label="Domain" value={form.domain}
            placeholder="theirpractice.com" onChange={(e) => set({ domain: e.target.value })} /></Field>
          <Field label="Owner's email"><input aria-label="Owner's email" value={form.owner_email}
            onChange={(e) => set({ owner_email: e.target.value })} /></Field>
        </div>
        <button className="primary" disabled={create.isPending || !form.legal_name.trim()
          || !form.display_name.trim() || !form.domain.trim() || !form.owner_email.trim()}
          onClick={() => create.mutate()}>{create.isPending ? "Creating…" : "Add practice"}</button>
      </Card>
    </>
  );
}
