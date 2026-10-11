# P6 M4 — Personal finance

**Placeholder · 2026-10-10 · not specified, not built**

The fourth of the four finance modules the owner asked for on 2026-10-08
(`docs/p6_m1_reconciliation_month_close.md`: M1 reconciliation and month
close, M2 cash forecast, M3 balance sheet, M4 personal finance). It gets its
own spec, is built after approval, gets demo data, and is released only on
"release". This file holds what has been said about it so far, so the spec
starts from it.

**The owner's brief for all four modules is `docs/p6_finance_expansion_brief.md`**
(saved verbatim 2026-10-11). M4's spec is written from its "M4 — PERSONAL
FINANCE" section and its "ALL FOUR" paragraph; where the brief and the spec
disagree, the brief wins unless a recorded decision says otherwise.

## Recorded for the spec (owner, 2026-10-10): the tax-deductible group

The owner's CPA's **Itemized Deduction Worksheet** groups personal
deductibles as below. **The personal starting chart should carry these as a
"Tax-deductible" group beside the ordinary household categories, so year-end
itemizing is a filter, and the personal export mirrors that worksheet**, as
the practice's worksheet export mirrors the Business Income & Expense
Worksheet (M1 §5.5).

| Group (the worksheet's) | Items |
|---|---|
| Medical and dental | Prescriptions · Doctors and dentists · Hospitals and nursing homes · Eyeglasses and contacts · Travel for medical · Medical miles · Other |
| Health insurance | Medical premiums · Medicare Part B · Long-term care premiums |
| Interest paid | Mortgage interest/points · Home equity interest · Investment interest |
| Property taxes | Personal residence · Investment property |
| Charitable contributions | Church · Schools · Health charities · Misc · Charitable miles |
| Non-cash donations | By charity |

Things the spec will have to decide, noted here and not decided:

- "Medical miles" and "Charitable miles" are counts of miles, not money: the
  same kind of year-end fact as M1's business miles (`finance_year_facts`),
  or entries with a quantity.
- "Non-cash donations, by charity" is a list with a charity named on each
  line, which a category alone does not hold.
- Whether "Tax-deductible" is a level above the categories, or a mark on
  them, given M1's chart has two levels and no more.
- Who sees it. M1 is the practice owner's only; a household is not a
  practice.
