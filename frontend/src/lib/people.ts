/**
 * Names in a list of people (owner, 2026-11-25). Where two people in the same
 * list share a name, each also says its role, so the list can tell them apart:
 * "Bryan Baker (Practice owner), Bryan Baker (Client owner)" (one person's two
 * accounts). Everyone else keeps their plain name. Roles are always shown by
 * name, never by code (lib/roles.ts).
 */
import { roleLabel } from "./roles";

const same = (name: string) => name.trim().replace(/\s+/g, " ").toLowerCase();

/** A namer for exactly this list: call it on each person as it is shown.
 *  `roleOf` gives a person's role as a name ("Client owner"). */
export function apart<T extends { name: string }>(
  people: readonly T[], roleOf: (person: T) => string | null | undefined,
): (person: T) => string {
  const count = new Map<string, number>();
  for (const p of people) count.set(same(p.name), (count.get(same(p.name)) ?? 0) + 1);
  return (person: T) => {
    const role = roleOf(person);
    return (count.get(same(person.name)) ?? 0) > 1 && role ? `${person.name} (${role})`
      : person.name;
  };
}

/** For lists whose `role` is a code (/api/portal-people/ and the like). */
export const roleByCode = (person: { role?: string | null }) =>
  (person.role ? roleLabel(person.role) : "");

/** For lists whose `role` is already a name (the agreements screens). */
export const roleByName = (person: { role?: string | null }) => person.role ?? "";
