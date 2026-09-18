import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { Contact, Me, StrategySessionRow, api } from "../lib/api";

const STATE_LABEL: Record<string, string> = {
  draft: "Draft", precall_sent: "Form sent", precall_complete: "Form complete",
  in_call: "In the call", complete: "Complete", converted: "Converted", lost: "Lost",
};

/**
 * Matrix 10.2 — a VA may set a session up and send the form. Only the call
 * itself, the drafting and everything downstream of it are fractional-only, and
 * the session screen says so rather than hiding the controls without a reason.
 */
export function Sessions({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const sessions = useQuery<StrategySessionRow[]>({
    queryKey: ["strategy-sessions"],
    queryFn: () => api.get<StrategySessionRow[]>("/api/strategy-sessions/"),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["strategy-sessions"] });

  return (
    <>
      <h1>Strategy sessions</h1>
      {note && <Banner kind="ok">{note}</Banner>}
      <NewSession onDone={(text) => { setNote(text); refresh(); }} />

      {sessions.data?.length === 0 && (
        <Empty>No sessions yet. Start one from a prospect above.</Empty>
      )}
      {(sessions.data ?? []).map((session) => (
        <Card key={session.id}
          title={`${session.contact?.name ?? "—"}${session.company ? ` · ${session.company.name}` : ""}`}
          actions={<Pill kind={session.state === "converted" ? "ok" : ""}>
            {STATE_LABEL[session.state] ?? session.state}</Pill>}>
          <p className="small muted">
            {session.scheduled_at ? `Scheduled ${when(session.scheduled_at)}` : "Not scheduled"}
            {session.owner ? ` · ${session.owner}` : ""}
            {session.precall_sent ? " · pre-call form sent" : ""}
          </p>
          <Link className="btn" to={`/strategy/${session.id}`}>Open the session</Link>
        </Card>
      ))}
      {!me.role && <Banner kind="info">Sign in to see your sessions.</Banner>}
    </>
  );
}

function NewSession({ onDone }: { onDone: (message: string) => void }) {
  const [term, setTerm] = useState("");
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null);
  const [scheduledAt, setScheduledAt] = useState("");

  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["contact-search", term],
    queryFn: () => api.get<{ contacts: Contact[] }>(
      `/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 1 && !picked,
  });
  const start = useMutation({
    mutationFn: () => api.post<StrategySessionRow>("/api/strategy-sessions/", {
      contact: picked?.id,
      scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
    }),
    onSuccess: (session) => {
      onDone(`Session started for ${session.contact?.name ?? "the prospect"}.`);
      setPicked(null); setTerm(""); setScheduledAt("");
    },
  });

  return (
    <Card title="Start a session">
      <div className="row">
        <Field label="Find a prospect">
          <input aria-label="Find a prospect" value={picked ? picked.name : term}
            placeholder="Name or company"
            onChange={(e) => { setPicked(null); setTerm(e.target.value); }} />
        </Field>
        <Field label="When (optional)">
          <input aria-label="When" type="datetime-local" value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)} />
        </Field>
        <button className="primary" disabled={!picked || start.isPending}
          onClick={() => start.mutate()}>Start</button>
      </div>
      {!picked && (
        <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
          {(found.data?.contacts ?? []).slice(0, 6).map((c) => (
            <li key={c.id}>
              <button className="ghost" onClick={() => setPicked({
                id: c.id, name: `${c.first_name} ${c.last_name}`.trim() })}>
                {c.first_name} {c.last_name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {start.isError && <Banner kind="bad">{(start.error as Error).message}</Banner>}
    </Card>
  );
}
