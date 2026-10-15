import { useQuery } from "@tanstack/react-query";

import { Me, PersonalCategory, PersonalChart, api } from "./api";

/**
 * P6 M4: Personal finance, the owner's household money on its own side of
 * Finance. The switch between the two sides is remembered in this browser
 * (spec, "Where it sits").
 */
export type FinanceSide = "business" | "personal";
const SIDE_KEY = "enhq.finance.side";

export function rememberedSide(): FinanceSide {
  try { return localStorage.getItem(SIDE_KEY) === "personal" ? "personal" : "business"; }
  catch { return "business"; }
}

export function rememberSide(side: FinanceSide) {
  try { localStorage.setItem(SIDE_KEY, side); } catch { /* private window */ }
}

export function hasPersonal(me: Me | undefined) {
  return (me?.modules ?? []).includes("personal");
}

/** Decision 26: on every personal screen. */
export const PERSONAL_DISCLAIMER = "Budgeting, forecasting and tax estimates only, not tax, "
  + "legal or financial advice. Confirm with your CPA.";

export function usePersonalChart(enabled = true) {
  return useQuery<PersonalChart>({
    queryKey: ["personal-categories"], enabled,
    queryFn: () => api.get<PersonalChart>("/api/personal/categories") });
}

/** Two levels, as `categoryOptions` does for the books: "Parent: child". */
export function personalOptions(rows: PersonalCategory[], type?: string): [string, string][] {
  const live = rows.filter((row) => !row.archived && (!type || row.type === type));
  const names = Object.fromEntries(rows.map((row) => [row.id, row.name]));
  const tops = live.filter((row) => !row.parent);
  const out: [string, string][] = [];
  for (const top of tops) {
    out.push([top.id, top.name]);
    for (const child of live.filter((row) => row.parent === top.id)) {
      out.push([child.id, `${names[top.id]}: ${child.name}`]);
    }
  }
  return out;
}
