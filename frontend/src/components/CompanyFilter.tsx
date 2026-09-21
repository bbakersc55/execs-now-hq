import { useQuery } from "@tanstack/react-query";

import { Company, Me, api } from "../lib/api";
import { useRemembered } from "../lib/remembered";
import { Field } from "./ui";

const TENANT = ["FF", "CF", "VA"];

/** The practice's own work, which has no company id to be filtered by. Sent to
 *  the server in place of one, and read there by the same name. */
export const INTERNAL = "internal";

/** Anything carrying a client company: a goal, a project or a task. Narrowing
 *  needs only the id; a heading needs the name as well. */
interface Filed { client_company: string | null }
interface Named extends Filed { client_company_name: string }

/**
 * The company dimension, shared by Work and Tasks.
 *
 * One control and one set of words for the same question on two screens, and —
 * more to the point — one definition of what "All clients" and "Internal" mean,
 * so the two screens cannot come to disagree about which work is whose.
 *
 * **Staff only.** A client user has exactly one company and every row they can
 * see belongs to it, so a selector there would be a control with one option;
 * the portal is left exactly as it was. The companies request is not made at
 * all for them — `/api/companies/` is staff-only and would 403.
 */
export function useCompanyFilter(me: Me, key: string) {
  const isTenant = !!me.role && TENANT.includes(me.role);
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], enabled: isTenant,
    queryFn: () => api.get<Company[]>("/api/companies/"),
  });
  const clients = (companies.data ?? []).filter((c) => c.is_client_company);
  const [chosen, choose] = useRemembered(`${key}:${me.email || "anon"}`, "");

  // A remembered company that is no longer offered — deleted, no longer a
  // client, or a CF who lost the assignment — falls back to all clients rather
  // than filtering the screen down to nothing with no way to see why. Only once
  // the list has actually loaded: before that, the remembered choice stands.
  const gone = companies.isSuccess && !!chosen && chosen !== INTERNAL
    && !clients.some((c) => c.id === chosen);

  return {
    isTenant,
    clients,
    company: isTenant && !gone ? chosen : "",
    choose,
  };
}

export function CompanyFilter({ value, onChange, companies, asChip }: {
  value: string; onChange: (value: string) => void; companies: Company[];
  /** On a filter bar it is a control among chips, with no stacked label
      (design brief, Tier 1). On a form it keeps its label. */
  asChip?: boolean;
}) {
  const select = (
    <select aria-label="Filter by client company" value={value}
      style={asChip ? { width: "auto", minWidth: 170 } : undefined}
      onChange={(e) => onChange(e.target.value)}>
      <option value="">All clients</option>
      {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      <option value={INTERNAL}>Internal — the practice's own</option>
    </select>
  );
  return asChip ? select : <Field label="Client">{select}</Field>;
}

/** Whether one row falls on the chosen side of the dimension. */
export function inCompany(row: Filed, company: string) {
  if (!company) return true;
  if (company === INTERNAL) return row.client_company === null;
  return row.client_company === company;
}

export interface CompanyGroup<T> { key: string; label: string; rows: T[] }

/**
 * Rows under one heading per client company, the practice's own work last.
 *
 * Built from the rows themselves rather than from the company list, so a client
 * with no work in view is not given an empty heading — and a heading never
 * appears for work the person cannot see.
 */
export function groupByCompany<T extends Named>(rows: T[]): CompanyGroup<T>[] {
  const groups = new Map<string, CompanyGroup<T>>();
  for (const row of rows) {
    const key = row.client_company ?? INTERNAL;
    const label = row.client_company
      ? row.client_company_name || "Unnamed company"
      : "Internal — the practice's own";
    if (!groups.has(key)) groups.set(key, { key, label, rows: [] });
    groups.get(key)!.rows.push(row);
  }
  return [...groups.values()].sort((a, b) => {
    if (a.key === INTERNAL) return 1;
    if (b.key === INTERNAL) return -1;
    return a.label.localeCompare(b.label);
  });
}
