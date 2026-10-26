/** A goal's figures the way a sentence says them (owner, 2026-10-26): "54",
 *  not "54.0000"; "1,250.5"; and, by the goal's unit as a KPI's kind would,
 *  "54%" and "$1,200". The twin of `apps/work/figures.py`. */

const PERCENT = new Set(["%", "percent", "pct"]);
const MONEY = new Set(["$", "usd", "dollars"]);

export function numberText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function figure(value: string | number | null | undefined, unit = ""): string {
  const text = numberText(value);
  if (!text) return "";
  const kind = unit.trim().toLowerCase();
  if (PERCENT.has(kind)) return `${text}%`;
  if (MONEY.has(kind)) return text.startsWith("-") ? `-$${text.slice(1)}` : `$${text}`;
  return text;
}

/** The unit written after the figures: none when it is already on them. */
export function unitAfter(unit = ""): string {
  const kind = unit.trim().toLowerCase();
  return PERCENT.has(kind) || MONEY.has(kind) ? "" : unit;
}
