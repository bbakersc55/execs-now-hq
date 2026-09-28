import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlarmClock, Check } from "lucide-react";

import { Pill, when } from "./ui";
import { Commitment, api } from "../lib/api";

/**
 * Commitments as a table: who owes what, by when, when we look again, and
 * where it came from — with Done and Snooze on the open ones. Used by the
 * "Waiting on others" screen and on a contact's page (owner, 2026-09-28).
 */
export function CommitmentList({ rows, onChanged, showPerson = true }: {
  rows: Commitment[]; onChanged?: () => void; showPerson?: boolean;
}) {
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: ({ id, verb, body }: { id: string; verb: "done" | "snooze"; body?: object }) =>
      api.post<Commitment>(`/api/commitments/${id}/${verb}/`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["commitments"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onChanged?.();
    },
  });
  return (
    <table>
      <thead>
        <tr>
          {showPerson && <th>Person</th>}
          <th>What</th><th>Due</th><th>Follow up</th><th>How</th><th>From</th><th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className={row.state === "done" ? "muted" : ""}>
            {showPerson && (
              <td>
                {row.contact ? <Link to={`/contacts/${row.contact}`}>{row.owner_name}</Link>
                  : row.owner_name}
                {row.company_name && <div className="tiny muted">{row.company_name}</div>}
              </td>
            )}
            <td>
              {row.text}
              {row.source_excerpt && (
                <div className="tiny muted" style={{ fontStyle: "italic" }}>
                  “{row.source_excerpt}”</div>
              )}
            </td>
            <td className="small tabular">{row.due_date ?? "—"}</td>
            <td className="small tabular">
              {row.follow_up_date ?? "—"}
              {row.overdue && <> <Pill kind="bad">overdue</Pill></>}
            </td>
            <td className="small">
              {row.task ? <Link to={`/tasks/${row.task}`}>{row.outcome_label}</Link>
                : row.outcome_label}
            </td>
            <td className="small muted">
              {row.meeting ? `${row.meeting.title}${row.meeting.date ? `, ${row.meeting.date}` : ""}`
                : "a meeting"}
            </td>
            <td className="right">
              {row.state === "open" ? (
                <span className="inline">
                  <button className="small" disabled={act.isPending}
                    aria-label={`Snooze ${row.text}`}
                    onClick={() => act.mutate({ id: row.id, verb: "snooze", body: { days: 7 } })}>
                    <AlarmClock size={14} /> 7 days
                  </button>
                  <button className="small" disabled={act.isPending}
                    aria-label={`Done: ${row.text}`}
                    onClick={() => act.mutate({ id: row.id, verb: "done" })}>
                    <Check size={14} /> Done
                  </button>
                </span>
              ) : <span className="tiny muted">done {when(row.done_at)}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
