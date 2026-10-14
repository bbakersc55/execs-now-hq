import { useEffect, useState } from "react";

import { Field } from "./ui";

/** Payment terms, as the server says them (`billing.services.terms_label`):
 *  one number of days, where 0 is due on receipt. */
export function termsLabel(days: number): string {
  return days === 0 ? "Due on receipt" : `Net ${days}`;
}

const USUAL = [0, 15, 30];

/** The day an invoice issued on `issued` is due, at these terms. */
export function dueOn(issued: string, days: number): string {
  const [y, m, d] = issued.split("-").map(Number);
  if (!y || !m || !d || !Number.isFinite(days)) return "";
  const due = new Date(Date.UTC(y, m - 1, d + days));
  return due.toISOString().slice(0, 10);
}

/**
 * Due on receipt, net 15, net 30, or a number of days (owner, 2026-10-14).
 *
 * `value` null is "the practice's own terms", which only a recurring invoice
 * offers: it then follows the practice's as they stand on the day each
 * invoice is written. `practice` is what that comes to today.
 */
export function TermsPicker({ label, value, onChange, practice, disabled, field = "Payment terms" }: {
  label: string; value: number | null; onChange: (days: number | null) => void;
  /** Given, the picker offers "The practice's" as its first choice. */
  practice?: number; disabled?: boolean; field?: string;
}) {
  const other = value !== null && !USUAL.includes(value);
  const choice = value === null ? "practice" : other ? "other" : String(value);
  return (
    <Field label={field}>
      <select aria-label={label} value={choice} disabled={disabled}
        onChange={(e) => {
          const next = e.target.value;
          onChange(next === "practice" ? null : next === "other" ? 45 : Number(next));
        }}>
        {practice !== undefined && (
          <option value="practice">The practice's ({termsLabel(practice)})</option>
        )}
        <option value="0">Due on receipt</option>
        <option value="15">Net 15</option>
        <option value="30">Net 30</option>
        <option value="other">A number of days…</option>
      </select>
      {other && (
        <>{" "}
          <DaysBox label={`${label}, in days`} value={value ?? 45} disabled={disabled}
            onChange={onChange} />{" "}
          <span className="small muted">days</span>
        </>
      )}
    </Field>
  );
}


/** The number of days, kept as typed until the box is left or Enter is
 *  pressed: a box emptied on the way to another number is not "due on
 *  receipt", and a setting is not saved once for every digit. */
function DaysBox({ label, value, disabled, onChange }: {
  label: string; value: number; disabled?: boolean; onChange: (days: number) => void;
}) {
  const [typed, setTyped] = useState(String(value));
  useEffect(() => setTyped(String(value)), [value]);
  const commit = () => {
    const days = Number(typed);
    if (typed.trim() && Number.isInteger(days) && days >= 1 && days <= 365) {
      if (days !== value) onChange(days);
    } else {
      setTyped(String(value));
    }
  };
  return (
    <input type="number" min={1} max={365} aria-label={label} style={{ width: "5rem" }}
      value={typed} disabled={disabled} onChange={(e) => setTyped(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />
  );
}
