import { FINANCE_DISCLAIMER } from "../lib/finance";

/** The last line of every Finance screen (P6 M1 §6). */
export function FinanceDisclaimer() {
  return (
    <p className="tiny muted" role="note" aria-label="Disclaimer"
      style={{ marginTop: "var(--s5)" }}>{FINANCE_DISCLAIMER}</p>
  );
}
