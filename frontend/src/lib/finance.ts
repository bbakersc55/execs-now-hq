import { FinanceCategory } from "./api";

/** The one line every Finance screen carries (P6 M1-15, the owner's words).
 *  `apps/finance/disclaimer.py` holds the same sentence, and
 *  `tests/test_finance_chart.py` holds the two together. */
export const FINANCE_DISCLAIMER =
  "Bookkeeping and projections only, not tax, legal or financial advice. Confirm with your CPA.";

/** The note above the categories (P6 M1 §5.4). */
export const CHART_NOTE =
  "Ask your CPA what they want to see, then add, remove or combine. These are common names, not a recommendation.";

const byPosition = (a: FinanceCategory, b: FinanceCategory) =>
  a.position - b.position || a.name.localeCompare(b.name);

/** The top-level categories, each followed by its sub-categories: the order
 *  every list and picker shows them in. */
export function inTreeOrder(categories: FinanceCategory[]): FinanceCategory[] {
  const ids = new Set(categories.map((c) => c.id));
  // One whose parent is not in this list (filtered out, say) stands by itself.
  const top = categories.filter((c) => !c.parent || !ids.has(c.parent)).sort(byPosition);
  return top.flatMap((parent) => [
    parent, ...categories.filter((c) => c.parent === parent.id).sort(byPosition)]);
}

/** A sub-category named with what it is under: "Travel: Airfare". */
export function categoryLabel(category: FinanceCategory, all: FinanceCategory[]): string {
  const parent = category.parent ? all.find((c) => c.id === category.parent) : undefined;
  return parent ? `${parent.name}: ${category.name}` : category.name;
}

/** What a category picker offers: `[id, label]` in tree order. */
export function categoryOptions(categories: FinanceCategory[],
                                all: FinanceCategory[] = categories): [string, string][] {
  return inTreeOrder(categories).map((c) => [c.id, categoryLabel(c, all)]);
}
