import type { ReactNode } from "react";

/**
 * One order for every list of companies to pick from or filter by (Bryan,
 * 2026-11-18): client companies first, in alphabetical order, then every
 * other company in alphabetical order, upper and lower case alike. A list
 * that mixes the two shows them under plain labels; a list that only ever
 * holds clients is simply alphabetical.
 */
export const CLIENTS_LABEL = "Clients";
export const OTHERS_LABEL = "Other companies";

/** Alphabetical, ignoring upper and lower case ("acme" beside "Acme"). */
export function byName(a: string, b: string): number {
  return a.localeCompare(b, undefined, { sensitivity: "base" }) || a.localeCompare(b);
}

/** Clients first, each group alphabetical. Without `isClient`, every item is
 *  taken for a client: the list is simply alphabetical. */
export function sortCompanies<T>(list: readonly T[], name: (c: T) => string,
  isClient: (c: T) => boolean = () => true): T[] {
  return [...list].sort((a, b) =>
    Number(!isClient(a)) - Number(!isClient(b)) || byName(name(a), name(b)));
}

/** For anything shaped like a company record. */
export const companyName = (c: { name: string }) => c.name;
export const isClientCompany = (c: { is_client_company?: boolean | null }) => !!c.is_client_company;

/** The two groups of a mixed list, each alphabetical. */
export function companyGroups<T>(list: readonly T[], name: (c: T) => string,
  isClient: (c: T) => boolean): { clients: T[]; others: T[] } {
  return {
    clients: sortCompanies(list.filter(isClient), name),
    others: sortCompanies(list.filter((c) => !isClient(c)), name),
  };
}

/**
 * The `<option>`s of a company drop-down in that order. With `isClient` and
 * both kinds present they sit under "Clients" and "Other companies"; with
 * one kind only (or no `isClient`, for a list of clients) they are plain
 * options, alphabetical. Options such as "Every client" or "No company" stay
 * with the caller, before or after these.
 */
export function CompanyOptions<T>({ items, id, name, label, isClient }: {
  items: readonly T[]; id: (c: T) => string; name: (c: T) => string;
  /** What the option says, when it is more than the name. */
  label?: (c: T) => ReactNode;
  isClient?: (c: T) => boolean;
}) {
  const say = label ?? name;
  const option = (c: T) => <option key={id(c)} value={id(c)}>{say(c)}</option>;
  if (!isClient) return <>{sortCompanies(items, name).map(option)}</>;
  const { clients, others } = companyGroups(items, name, isClient);
  if (clients.length === 0 || others.length === 0) {
    return <>{[...clients, ...others].map(option)}</>;
  }
  return (
    <>
      <optgroup label={CLIENTS_LABEL}>{clients.map(option)}</optgroup>
      <optgroup label={OTHERS_LABEL}>{others.map(option)}</optgroup>
    </>
  );
}

/** A list of the practice's own and its clients' (plans, SOPs, tool runs):
 *  the practice's own first, as "Our practice" always has been, then the
 *  clients alphabetically. */
export function practiceThenClients<T extends { name: string; is_practice?: boolean }>(
  list: readonly T[]): T[] {
  return [...list].sort((a, b) =>
    Number(!a.is_practice) - Number(!b.is_practice) || byName(a.name, b.name));
}
