import { useState } from "react";

import { WorkStatus } from "../lib/api";
import { STATUSES, STATUS_LABELS, StatusPill } from "./StatusPill";
import { Banner } from "./ui";

/**
 * FR-3.16 — on a status change a tenant user is **prompted, not forced**, for
 * one line on what the change means for the client, and the prompt says why it
 * is asking. Skipping saves the status change on its own.
 *
 * That line is the difference between a digest that reads as value delivered
 * and one that reads as a changelog, which is why it is asked for here — at
 * the moment the work actually moved — rather than at digest time.
 */
export function StatusChange({ status, disabled, askForLine = true, onChange }: {
  status: WorkStatus;
  disabled?: boolean;
  /** False for a client user: the client-facing line is the practice's. */
  askForLine?: boolean;
  onChange: (status: WorkStatus, clientFacingLine: string) => void;
}) {
  const [pending, setPending] = useState<WorkStatus | null>(null);
  const [line, setLine] = useState("");

  function pick(next: WorkStatus) {
    if (next === status) return;
    if (!askForLine) { onChange(next, ""); return; }
    setLine("");
    setPending(next);
  }

  if (pending) {
    return (
      <div className="card" role="dialog" aria-label="What this means for the client">
        <p style={{ marginTop: 0 }}>
          Moving to <StatusPill status={pending} />
        </p>
        <label htmlFor="client-facing-line">
          One line on what this means for the client — optional
        </label>
        <textarea id="client-facing-line" rows={3} value={line} autoFocus
          placeholder="e.g. We can now see where invoices stall; the fix lands next week."
          onChange={(e) => setLine(e.target.value)} />
        <Banner kind="info">
          This is what their progress report will say. Without it the report shows the
          status change alone, which reads as a changelog rather than as progress.
        </Banner>
        <div className="row">
          <button className="primary" onClick={() => { onChange(pending, line.trim()); setPending(null); }}>
            Save change{line.trim() ? " and line" : ""}
          </button>
          <button onClick={() => { onChange(pending, ""); setPending(null); }}>
            Skip the line
          </button>
          <button className="ghost" onClick={() => setPending(null)}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <select aria-label="Status" value={status} disabled={disabled}
      onChange={(e) => pick(e.target.value as WorkStatus)}>
      {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
    </select>
  );
}
