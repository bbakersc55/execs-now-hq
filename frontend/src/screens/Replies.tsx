import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Inbox, Mail, Paperclip, RefreshCw } from "lucide-react";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { Contact, InboundHealth, Me, UnmatchedRow, api } from "../lib/api";

/**
 * Module 6 — replies coming back (PRD §8).
 *
 * **Nothing here was dropped.** A reply the app could not place is stored, not
 * logged, and this screen is where a person decides whose it is. The failure
 * mode this module is built against is silence, so the queue says *why* each
 * one could not be matched rather than presenting it as a mystery.
 */
export function Replies({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");

  const health = useQuery<InboundHealth>({
    queryKey: ["inbound-health"],
    queryFn: () => api.get("/api/unmatched-inbound/poll/"),
  });
  const waiting = useQuery<UnmatchedRow[]>({
    queryKey: ["unmatched-inbound"],
    queryFn: () => api.get<UnmatchedRow[]>("/api/unmatched-inbound/"),
  });

  const collect = useMutation({
    mutationFn: () => api.post<{ matched: number; unmatched: number;
                                 already_had: number; errors: number }>(
      "/api/unmatched-inbound/poll/"),
    onSuccess: (report) => {
      setNote(`${report.matched} new repl${report.matched === 1 ? "y" : "ies"} filed`
        + `${report.unmatched ? `, ${report.unmatched} waiting for you` : ""}.`);
      setProblem("");
      qc.invalidateQueries({ queryKey: ["unmatched-inbound"] });
      qc.invalidateQueries({ queryKey: ["inbound-health"] });
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const rows = waiting.data ?? [];
  return (
    <>
      <PageHead title="Replies"
        sub="Mail that came back on threads the app started. Anything we could
             not place is here — nothing is ever dropped."
        action={me.role === "FF" && (
          <button className="primary" disabled={collect.isPending}
            onClick={() => collect.mutate()}>
            <RefreshCw size={16} /> {collect.isPending ? "Reading…" : "Collect now"}
          </button>
        )} />

      {note && <Banner kind="info">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {health.data && !health.data.can_read && (
        <Banner kind="warn">{health.data.detail}</Banner>
      )}
      {health.data?.can_read && (
        <p className="small muted">
          Reading {health.data.threads_watched} thread
          {health.data.threads_watched === 1 ? "" : "s"} as {health.data.account}
          {" · "}last looked{" "}
          {health.data.last_polled_at ? when(health.data.last_polled_at) : "never"}
          {health.data.errors > 0 && ` · ${health.data.errors} could not be read`}
        </p>
      )}

      {rows.length === 0 && (
        <Empty>
          <Inbox size={14} /> Nothing waiting to be filed. Replies that match
          a thread go straight onto the contact's record.
        </Empty>
      )}
      {rows.map((row) => (
        <Unfiled key={row.id} row={row} setProblem={setProblem}
          onFiled={(name) => {
            setNote(`Filed to ${name}.`);
            qc.invalidateQueries({ queryKey: ["unmatched-inbound"] });
          }} />
      ))}
    </>
  );
}

/** One reply nobody has placed yet (R13). */
function Unfiled({ row, onFiled, setProblem }: {
  row: UnmatchedRow; onFiled: (name: string) => void;
  setProblem: (text: string) => void;
}) {
  const [pick, setPick] = useState("");
  const [remember, setRemember] = useState(true);

  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts", "for-filing"],
    queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  const file = useMutation({
    mutationFn: () => api.post(`/api/unmatched-inbound/${row.id}/file/`,
      { contact: pick, add_address: remember }),
    onSuccess: () => {
      const chosen = (contacts.data ?? []).find((c) => c.id === pick);
      onFiled(chosen ? `${chosen.first_name} ${chosen.last_name}`.trim() : "the contact");
    },
    onError: (e: Error) => setProblem(e.message),
  });

  return (
    <Card title={row.subject || "(no subject)"}
      actions={<Pill>{row.received_at ? when(row.received_at) : "no date"}</Pill>}>
      <p className="small muted">
        <Mail size={12} /> {row.from_name ? `${row.from_name} · ` : ""}
        {row.from_address}
      </p>
      {/* Why it could not be placed. Saying so is most of filing it. */}
      <p className="tiny muted">{row.reason}</p>
      <p style={{ whiteSpace: "pre-wrap" }}>{row.body}</p>

      <div className="row" style={{ marginTop: "var(--s3)" }}>
        <Field label="Whose is this?">
          <select aria-label={`File ${row.from_address} to`} value={pick}
            onChange={(e) => setPick(e.target.value)}>
            <option value="">Choose a contact…</option>
            {(contacts.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.first_name} {c.last_name}
                {c.emails[0] ? ` · ${c.emails[0].address}` : ""}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <label className="choice">
        <input type="checkbox" checked={remember}
          onChange={(e) => setRemember(e.target.checked)} />
        <span>
          Remember {row.from_address} for them, so the next reply files itself
        </span>
      </label>
      <div className="row tight" style={{ marginTop: "var(--s2)" }}>
        <button className="primary small" disabled={!pick || file.isPending}
          aria-label={`File ${row.from_address}`}
          onClick={() => file.mutate()}>
          <Paperclip size={14} /> File it
        </button>
      </div>
    </Card>
  );
}
