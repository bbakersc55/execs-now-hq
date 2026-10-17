import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { day } from "../components/DemoVisitor";
import { Banner, Card, Empty, Field, Pill, countdown, when } from "../components/ui";
import { api } from "../lib/api";

/** GET /api/platform/demo-visitors (apps/tenancy/demo/visitors.py `rows`). */
export interface DemoVisitorRow {
  id: string;
  name: string;
  email: string;
  note: string;
  state: "setting_up" | "ready" | "failed";
  state_error: string;
  created_at: string;
  expires_at: string;
  deletes_on: string;
  ended: boolean;
  invited_at: string | null;
  last_activity_at: string | null;
  ai_spent_today_usd: string;
  ai_spent_total_usd: string;
  reset_count: number;
}

const EMPTY = { name: "", email: "", days: "30", note: "" };

function stateOf(v: DemoVisitorRow): [string, string] {
  if (v.ended) return ["", "Ended, read-only"];
  if (v.state === "setting_up") return ["warn", "Being set up"];
  if (v.state === "failed") return ["bad", "Setup did not finish"];
  return ["ok", v.invited_at ? "Ready, invited" : "Ready"];
}

/**
 * Demo visitors (Melissa's feedback W1, decisions 2026-10-17), in the
 * platform owner's Practices area on the demo: invite one, and each visitor's
 * own copy of the demo practice with its dates and AI spend. Extend, Reset,
 * Delete. Nothing inside a copy is shown here.
 */
export function DemoVisitors() {
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [days, setDays] = useState<Record<string, string>>({});
  const list = useQuery<DemoVisitorRow[]>({
    queryKey: ["demo-visitors"],
    queryFn: () => api.get<DemoVisitorRow[]>("/api/platform/demo-visitors"),
    // A copy being set up turns ready by itself; the list follows it.
    refetchInterval: (query) => (query.state.data?.some((v) => v.state === "setting_up")
      ? 10000 : false),
  });
  const done = (text: string) => {
    setProblem("");
    setNote(text);
    qc.invalidateQueries({ queryKey: ["demo-visitors"] });
  };
  const failed = (e: Error) => { setNote(""); setProblem(e.message); };

  const invite = useMutation({
    mutationFn: () => api.post<DemoVisitorRow>("/api/platform/demo-visitors",
                                               { ...form, days: Number(form.days) }),
    onSuccess: (row) => {
      setForm(EMPTY);
      done(`${row.name}'s demo is being set up. The invitation goes to ${row.email} when it `
           + "is ready, in a few minutes.");
    },
    onError: failed,
  });
  const act = useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: "extend" | "reset" | "invite";
                                         body?: object }) =>
      api.post<DemoVisitorRow>(`/api/platform/demo-visitors/${id}/${action}`, body ?? {}),
    onSuccess: (row, { action }) => done(action === "extend"
      ? `${row.name}'s demo now ends on ${day(row.expires_at)}.`
      : action === "invite" ? `The invitation went to ${row.email}.`
      : `${row.name}'s demo is being set up again.`),
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/platform/demo-visitors/${id}`),
    onSuccess: () => done("Deleted: the copy, its files and its sign-in."),
    onError: failed,
  });

  const rows = list.data ?? [];
  const set = (patch: Partial<typeof EMPTY>) => setForm({ ...form, ...patch });
  const busy = act.isPending || remove.isPending;

  return (
    <>
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      <Card title="Invite a demo visitor">
        <p className="muted small" style={{ marginTop: 0 }}>
          They get their own private copy of this demo practice, dated from today, as its
          practice owner. They sign in by a link to their email; everything their copy sends
          goes to that address only. Its AI stops at $2 a day and $10 in all. It lasts the
          days you choose, then stays read-only for a week, then is deleted.
        </p>
        <div className="row" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
          <Field label="Name"><input aria-label="Visitor's name" value={form.name}
            onChange={(e) => set({ name: e.target.value })} /></Field>
          <Field label="Email"><input aria-label="Visitor's email" value={form.email}
            type="email" onChange={(e) => set({ email: e.target.value })} /></Field>
          <Field label="Days"><input aria-label="Days" value={form.days} type="number"
            min={1} max={365} style={{ width: "6rem" }}
            onChange={(e) => set({ days: e.target.value })} /></Field>
        </div>
        <Field label="Note (for you; they never see it)">
          <textarea aria-label="Note" rows={2} value={form.note}
            onChange={(e) => set({ note: e.target.value })} />
        </Field>
        <button className="primary" disabled={invite.isPending || !form.name.trim()
          || !form.email.trim() || !Number(form.days)}
          onClick={() => invite.mutate()}>
          {invite.isPending ? "Inviting…" : "Invite and set up their demo"}</button>
      </Card>

      <Card title="Demo visitors">
        {list.isError ? <Banner kind="bad">{(list.error as Error).message}</Banner>
          : rows.length === 0 ? <Empty>No demo visitors yet.</Empty> : (
          <div className="card-grid">
            {rows.map((v) => {
              const [kind, label] = stateOf(v);
              return (
                <article key={v.id} className="card practice" aria-label={`Demo of ${v.name}`}>
                  <div className="spread" style={{ alignItems: "flex-start" }}>
                    <div style={{ minWidth: 0 }}>
                      <h3 style={{ margin: 0 }}>{v.name}</h3>
                      <div className="muted small">{v.email}</div>
                    </div>
                    <Pill kind={kind}>{label}</Pill>
                  </div>
                  {v.state_error && (
                    <p className="small" role="alert" style={{ color: "var(--bad)" }}>
                      {v.state_error}</p>)}
                  <dl className="facts" style={{ margin: "var(--s3) 0" }}>
                    <dt>Created</dt><dd>{day(v.created_at)}</dd>
                    <dt>Ends</dt>
                    <dd>{day(v.expires_at)}{v.ended
                      ? `; deleted ${day(v.deletes_on)}` : ` (${countdown(v.expires_at)})`}</dd>
                    <dt>Last activity</dt>
                    <dd>{v.last_activity_at ? when(v.last_activity_at) : "Never signed in"}</dd>
                    <dt>AI spend</dt>
                    <dd>${v.ai_spent_today_usd} today, ${v.ai_spent_total_usd} in all</dd>
                    {v.reset_count > 0 && <><dt>Resets</dt><dd>{v.reset_count}</dd></>}
                    {v.note && <><dt>Note</dt><dd>{v.note}</dd></>}
                  </dl>
                  <div className="row tight">
                    <input aria-label={`Days to add for ${v.name}`} type="number" min={1}
                      max={365} style={{ width: "4.5rem" }} value={days[v.id] ?? "30"}
                      onChange={(e) => setDays({ ...days, [v.id]: e.target.value })} />
                    <button className="ghost" disabled={busy} onClick={() => act.mutate(
                      { id: v.id, action: "extend",
                        body: { days: Number(days[v.id] ?? "30") } })}>Extend</button>
                    <button className="ghost" disabled={busy || v.state === "setting_up"}
                      onClick={() => {
                        if (window.confirm(`Reset ${v.name}'s demo? Everything in it is `
                          + "emptied and set up again as of today. Their sign-in and its end "
                          + "date stay.")) act.mutate({ id: v.id, action: "reset" });
                      }}>Reset</button>
                    {v.state === "ready" && !v.ended && (
                      <button className="ghost" disabled={busy}
                        onClick={() => act.mutate({ id: v.id, action: "invite" })}>
                        {v.invited_at ? "Send the invitation again" : "Send the invitation"}
                      </button>)}
                    <button className="danger" disabled={busy} onClick={() => {
                      if (window.confirm(`Delete ${v.name}'s demo now? The copy, its files `
                        + "and their sign-in go at once, and cannot be brought back."))
                        remove.mutate(v.id);
                    }}>Delete</button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Card>
    </>
  );
}
