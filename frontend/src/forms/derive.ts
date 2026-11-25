/** Summaries the owner sees as they go. The server works the same things out
 *  again (apps/intake/derive.py) for what is sent; these are for reading. */
import type { Answers, Bed, OwnerForm } from "./types";

export function bedLabel(form: OwnerForm, type: number): string {
  return form.bed_types.find((b) => b.id === type)?.label ?? "Bed";
}

export function sleeps(form: OwnerForm, beds: Bed[]): number {
  return beds.reduce((n, b) => n + (form.bed_types.find((x) => x.id === b.type)?.sleeps ?? 2)
    * b.count, 0);
}

export function roomSummary(form: OwnerForm, title: string, beds: Bed[],
  note?: string): string {
  // Owner, 2026-11-24: no list of beds to choose from, so their own words.
  if (!beds.length && note) return `${title}: “${note}”`;
  const parts = beds.map((b) => `${bedLabel(form, b.type)} x${b.count}`);
  return `${title}: ${parts.length ? parts.join(", ") : "no beds yet"}, sleeps ${sleeps(form, beds)}`;
}

export function bathType(form: OwnerForm, fixtures: Record<string, number>): string {
  const kinds = new Set(Object.entries(fixtures).filter(([, n]) => n > 0)
    .map(([id]) => form.bathroom_fixtures.find((f) => String(f.id) === id)?.kind ?? ""));
  if (kinds.has("tub")) return "Full bathroom";
  if (kinds.has("shower")) return "Three-quarter bathroom";
  return "Half bathroom";
}

export function bathSummary(form: OwnerForm, title: string,
  fixtures: Record<string, number>, note?: string): string {
  if (!Object.values(fixtures).some((n) => n > 0) && note)
    return `${title}: “${note}”`;
  const parts = Object.entries(fixtures).filter(([, n]) => n > 0).map(([id, n]) => {
    const name = form.bathroom_fixtures.find((f) => String(f.id) === id)?.name ?? "Fixture";
    return n > 1 ? `${name} x${n}` : name;
  });
  return `${title}: ${bathType(form, fixtures)}${parts.length ? ` (${parts.join(", ")})` : ""}`;
}

export function totalSleeps(form: OwnerForm, a: Answers): number {
  let total = 0;
  for (const room of a.bedrooms ?? []) total += sleeps(form, room.beds);
  if (a.other_sleeping?.has === "yes")
    for (const place of a.other_sleeping.places ?? []) total += sleeps(form, place.beds);
  return total;
}

export function label(form: OwnerForm, list: string, value: string | undefined): string {
  return form.options[list]?.find((o) => o.value === value)?.label ?? "";
}

export function labels(form: OwnerForm, list: string, values: string[] | undefined): string {
  return (values ?? []).map((v) => label(form, list, v)).filter(Boolean).join(", ");
}
