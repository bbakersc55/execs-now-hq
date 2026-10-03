import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import {
  Contact, Me, StrategySessionRow, StrategyTemplateRow, activeTemplates, api,
} from "../lib/api";

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
  // Archived is its own list, not a state (owner, 2026-09-26).
  const [params, setParams] = useSearchParams();
  const archived = params.get("archived") === "1";
  const sessions = useQuery<StrategySessionRow[]>({
    queryKey: ["strategy-sessions", archived ? "archived" : "active"],
    queryFn: () => api.get<StrategySessionRow[]>(
      `/api/strategy-sessions/${archived ? "?archived=1" : ""}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["strategy-sessions"] });
  const run = useMutation({
    mutationFn: ({ id, suffix, method }: { id: string; suffix: string;
                                           method?: "post" | "delete" }) =>
      method === "delete" ? api.del(`/api/strategy-sessions/${id}/`)
        : api.post(`/api/strategy-sessions/${id}/${suffix}`),
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <>
      <h1>Strategy sessions</h1>
      {me.role === "FF" && (
        <p className="small muted">
          <Link to="/strategy/template">Manage the templates</Link> — questions,
          budgets, the practice default. Sessions already under way are never affected.
        </p>
      )}
      {note && <Banner kind="ok">{note}</Banner>}
      {!archived && (
        <NewSession onDone={(text) => { setNote(text); refresh(); }}
          initialTemplate={params.get("template") ?? ""}
          initialContact={params.get("contact") ?? ""}
          focus={params.get("new") === "1"} />
      )}

      <div className="row" role="group" aria-label="Which sessions">
        <button className={archived ? "ghost" : "primary"} aria-pressed={!archived}
          onClick={() => setParams({})}>Active</button>
        <button className={archived ? "primary" : "ghost"} aria-pressed={archived}
          onClick={() => setParams({ archived: "1" })}>Archived</button>
      </div>

      {sessions.data?.length === 0 && (
        archived
          ? <Empty>Nothing archived.</Empty>
          : <Empty>No sessions yet. Start one from a prospect above.</Empty>
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
          <div className="row">
            <Link className="btn" to={`/strategy/${session.id}`}>Open the session</Link>
            {archived && session.may_archive && (
              <button disabled={run.isPending}
                onClick={() => run.mutate({ id: session.id, suffix: "unarchive/" }, {
                  onSuccess: () => { setNote("Restored to the sessions list."); refresh(); },
                })}>Restore</button>
            )}
            {archived && session.may_delete && (
              <button className="danger" disabled={run.isPending || !!session.delete_refusal}
                title={session.delete_refusal || undefined}
                onClick={() => {
                  if (!confirm(`Delete the session with ${session.contact?.name ?? "this "
                    + "prospect"} permanently? Its answers, strategy map, prep and notes `
                    + "go with it, and it cannot be undone.")) return;
                  run.mutate({ id: session.id, suffix: "", method: "delete" }, {
                    onSuccess: () => { setNote("Deleted, and recorded in the audit log.");
                                       refresh(); },
                  });
                }}>Delete permanently</button>
            )}
          </div>
          {archived && session.may_delete && session.delete_refusal && (
            <p className="small muted">{session.delete_refusal}</p>
          )}
        </Card>
      ))}
      {!me.role && <Banner kind="info">Sign in to see your sessions.</Banner>}
    </>
  );
}

function NewSession({ onDone, initialTemplate = "", initialContact = "", focus = false }: {
  onDone: (message: string) => void; initialTemplate?: string; initialContact?: string;
  focus?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null);
  // Arrived from a session's "Start a new session": the prospect, if named,
  // is filled in, and the form is where the eye lands.
  const fromContact = useQuery<Contact>({
    queryKey: ["contact", initialContact],
    queryFn: () => api.get<Contact>(`/api/contacts/${initialContact}/`),
    enabled: !!initialContact,
  });
  useEffect(() => {
    if (fromContact.data) {
      setPicked({ id: fromContact.data.id,
                  name: `${fromContact.data.first_name} ${fromContact.data.last_name}`.trim() });
    }
  }, [fromContact.data]);
  const formRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focus) formRef.current?.scrollIntoView?.({ block: "start" });
  }, [focus]);
  const [scheduledAt, setScheduledAt] = useState("");
  // The template picker (owner, 2026-09-26): the practice default unless
  // somebody chooses otherwise. Archived ones are not offered.
  const templates = useQuery<StrategyTemplateRow[]>({
    queryKey: ["strategy-templates"],
    queryFn: () => api.get<StrategyTemplateRow[]>("/api/strategy-templates/"),
  });
  const offered = activeTemplates(templates.data);
  const [templateId, setTemplateId] = useState(initialTemplate);
  // A builder template that is not ready (P3) is listed, and cannot be chosen.
  const chosenTemplate = offered.find((t) => t.id === templateId)
    ?? offered.find((t) => t.ready !== false) ?? offered[0];

  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["contact-search", term],
    queryFn: () => api.get<{ contacts: Contact[] }>(
      `/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 1 && !picked,
  });
  const start = useMutation({
    mutationFn: () => api.post<StrategySessionRow>("/api/strategy-sessions/", {
      contact: picked?.id,
      template: chosenTemplate?.id ?? null,
      scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
    }),
    onSuccess: (session) => {
      onDone(`Session started for ${session.contact?.name ?? "the prospect"}, `
        + `from “${session.template.name}”.`);
      setPicked(null); setTerm(""); setScheduledAt("");
    },
  });

  return (
    <div ref={formRef}>
    <Card title="Start a session">
      <div className="row">
        <Field label="Find a prospect">
          <input aria-label="Find a prospect" value={picked ? picked.name : term}
            placeholder="Name or company"
            onChange={(e) => { setPicked(null); setTerm(e.target.value); }} />
        </Field>
        <Field label="Template">
          <select aria-label="Template" value={chosenTemplate?.id ?? ""}
            onChange={(e) => setTemplateId(e.target.value)}>
            {offered.map((t) => (
              <option key={t.id} value={t.id} disabled={t.ready === false}>
                {t.name}{t.is_default ? " (practice default)" : ""}
                {t.ready === false ? " (not ready to run)" : ""}
              </option>
            ))}
          </select>
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
      {templates.data && offered.length === 0 && (
        <p className="small muted">
          This practice has no strategy template yet.{" "}
          <Link to="/strategy/template">Build one</Link> before starting a session.
        </p>
      )}
      {start.isError && <Banner kind="bad">{(start.error as Error).message}</Banner>}
    </Card>
    </div>
  );
}
