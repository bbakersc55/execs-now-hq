import { WorkStatus } from "../lib/api";

export const STATUSES: WorkStatus[] = [
  "not_started", "in_progress", "blocked", "waiting_on_client", "done", "cancelled",
];

export const STATUS_LABELS: Record<WorkStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  waiting_on_client: "Waiting on client",
  done: "Done",
  cancelled: "Cancelled",
};

/** FR-3.7/3.8 — six statuses, each rendered distinctly. `derived` marks a
 *  goal or project status that was rolled up from children rather than set. */
export function StatusPill({ status, derived = false }: { status: WorkStatus; derived?: boolean }) {
  return (
    <span className={`pill status-${status}${derived ? " derived" : ""}`}
      title={derived ? "Derived from the work underneath — not set by hand" : undefined}>
      {STATUS_LABELS[status]}{derived ? " (derived)" : ""}
    </span>
  );
}
