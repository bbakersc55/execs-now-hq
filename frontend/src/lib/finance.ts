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

/** Guided mode's steps (P6 M1 §4.2): written here, free, and always shown.
 *  `apps/finance/explain.py` names the same eight, and a test holds the two
 *  together. */
export const GUIDE_STEPS: [string, string][] = [
  ["Get your statement",
   "Open or download the statement for this account from your bank's or card's website. "
   + "The ending balance is what the bank says the account held on the statement's last "
   + "day. For a card, it is what you owed."],
  ["Type its ending date and ending balance",
   "Both are printed at the top of the statement. The starting balance is not typed: it "
   + "is where your last reconciliation of this account ended."],
  ["Tick what the statement shows",
   "Go down the statement and tick each line here that it also shows. Lines your bank "
   + "import brought in are ticked already, because they came from the bank. Untick any "
   + "the statement does not show."],
  ["Look at what is left",
   "An unticked line is usually fine: a check not yet cashed, a charge not yet posted. "
   + "It carries forward and appears at the top of the next reconciliation, under From "
   + "earlier statements."],
  ["Get the difference to zero",
   "When it is not zero it is usually one of four things: a line you have not ticked, an "
   + "entry typed the wrong way round, two digits swapped in an amount, or something on "
   + "the statement that is not in your books yet. The screen checks for each."],
  ["Finish, and do the next account",
   "Finish is offered only at a difference of exactly zero. Then do the same for each "
   + "other account for the month."],
  ["Check the list",
   "Open the month. Its checklist ticks itself: every account reconciled, nothing "
   + "uncategorized, invoice payments placed, and 1099 payees named. The first three "
   + "must be done to close; the fourth is a warning."],
  ["Close the month",
   "Closing locks the books through the month's last day: nothing dated in it can be "
   + "added, changed or removed. If a later statement shows this month was wrong, do not "
   + "reopen it. Add a correcting entry in the open month that says what it corrects. "
   + "Your CPA will thank you."],
];
