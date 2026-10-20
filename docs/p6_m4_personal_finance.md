# P6 M4 — Personal finance

**Spec · 2026-10-15 · stops 1–4 built (stop 1 released)**

Written from `docs/p6_m4_personal_finance_spec_draft.md` (Bryan's draft, saved
verbatim; drafted 2026-10-15 by Claude in chat with Bryan's decisions of that
day), the owner's brief `docs/p6_finance_expansion_brief.md` (its "M4 —
PERSONAL FINANCE" section and its "ALL FOUR" paragraph) and this file's
placeholder of 2026-10-10. **The brief wins where the two differ, unless this
spec records a decision** (owner, 2026-10-11); "Brief against spec" below says
where each difference stands. Decisions 1–27 are the draft's, unchanged except
where a note marked *Brief wins* says otherwise.

## What M4 is for

M4 puts the owner's household money in the same app as the practice's books, on its own side of Finance. It gives them a budget that builds itself from their history, envelopes, savings goals, a cash forecast, debts and retirement watched over time, a set-aside for quarterly estimated taxes, and a personal worksheet beside the business one for the CPA.

It is built on what M1 and M2 already have: accounts, imports (CSV, OFX, QFX, QBO, PDF), categories, rules, reconciliation and the forecast engine. Nothing is rebuilt; the personal side reuses them with a different chart and different screens.

**Who it serves.** The practice owner only. Associates, assistants and the platform owner never see it. Later, far down the line, the module should be able to stand alone for an owner's employees, so personal data hangs off a person, not off the practice.

**Who it is for in the market.** Some fractionals keep business and personal apart (separate accounts, separate cards). Many don't. M4 has to work for both: the first group adds personal accounts; the second marks their accounts as mixed and sorts each line to a side.

**What it is not.** No P&L on the personal side. No tax, legal or financial advice: every number that touches taxes is an estimate with "confirm with your CPA" beside it. No bank connections; statements come in the way they do today.

## Where it sits

Personal lives under Finance, behind a two-way switch at the top of every Finance screen: **Business | Personal**. The Personal side carries its own accent band and the word "Personal" in every page title, so nobody mistakes which money they are looking at. The browser remembers the last side used.

| Side | Pages |
| --- | --- |
| Business (as today) | Overview, Entries, Accounts, Reconcile, Close, Categories, Forecast, For your CPA |
| Personal (new) | Overview (envelopes and Unassigned), Entries, Accounts, Forecast, Goals, Debts, Retirement, Household, Taxes (set-aside), Categories |
| Shared | For your CPA, one page with a Business section and a Personal section |

The one mechanism that makes mixed finances work: every line has a **side**. An account is Business, Personal or Mixed; a Mixed account is imported and reconciled once, and each of its lines is sorted to a side by the same rules that set its category. Only business-side lines reach the books.

(Drawing in the Claude Doc: Business, Mixed and Personal accounts feed "every line gets a side"; the business side flows to the books, P&L, business forecast and the CPA business worksheet; the personal side to envelopes, goals, debts, retirement, the personal forecast, net worth and the itemized worksheet. A business line from a personal account is marked paid personally; a personal line from a business account posts an owner draw in the books.)

A mixed account is imported once; its lines are sorted to a side, and each side goes to its own place. A line that crosses sides (business spending from a personal account, or personal spending from a business one) is posted to the books as the note above says.

## Decisions 1–8: accounts, sides and sorting

Each decision has my recommendation. Overrule any of them in a comment.

1. **Account kinds.** Every account is Business, Personal or Mixed. Existing accounts stay Business. A Mixed account has one statement, one import and one reconciliation; its lines are sorted to a side. *Recommended: yes. It is the only way the "one card for everything" owner gets correct books.*
2. **A side on every line.** Business, Personal, or Split (a percentage or an amount, like a phone bill that is 60% business). Rules set the side the way they set categories, and the import's dry run shows the side beside the category. *Recommended: yes.*
3. **Crossing sides posts correctly.** A business-side line in a Personal or Mixed account posts to the books marked "paid personally" (an owner contribution), so the CPA worksheet counts it. A personal-side line in a Business or Mixed account posts to the books as an owner draw and to the personal side as the spend itself, in its envelope. *Recommended: yes. This is the marriage of the two sides; without it one of the two is always wrong. Each posting is reversible from the import's rollback.*
4. **A personal chart of categories.** Separate from the business chart, two levels, with a starting chart built in: Housing, Utilities, Groceries, Dining, Transportation, Health, Insurance, Childcare and education, Giving, Personal care, Entertainment and subscriptions, Travel, Gifts, Pets, Debt payments, Savings and retirement, Taxes, Income (pay from the practice, spouse pay, other), Transfers, Everything else. Each category can carry a **Tax-deductible** mark naming a group on the CPA's Itemized Deduction Worksheet. Combine, Split and Archive as in M1. *Recommended: yes.*
5. **Light sorting.** Rules learn from every choice. A line with no rule that is under a threshold goes to Everything else without asking; only lines over the threshold with no rule wait in **To sort**. The threshold is the owner's, default $25. Bulk actions as on business Entries. *Recommended: yes. This is what keeps hundreds of small lines from becoming a chore.*
6. **Sort these with Claude.** One button on To sort: priced first, costed after, proposes a category and side for every waiting line, the owner accepts all or edits. Accepted proposals become rules. Merchant names are sent (the button says so); amounts and names only, never account numbers. Counts against the monthly AI budget, not the daily Explain cap. *Recommended: yes.* *Brief wins ("AI calls costed and under the daily cap", not decided otherwise): it counts against the monthly budget **and** Finance's shared 20-a-day cap, one per press.*
7. **Transfers are not spending.** Moves between the owner's own accounts (checking to savings, a card payment) are transfers. The import pairs them when both accounts are imported; the card payment day already exists in M2. *Recommended: yes.*
8. **Reconcile is optional on the personal side.** Available on Personal and Mixed accounts, no month close on the personal side. A Mixed account reconciles once, all lines regardless of side, and its business lines close with the business month as now. *Recommended: yes; it keeps balances honest for the forecast without forcing the ritual.*

## Decisions 9–14: a budget that builds itself

The envelope idea from YNAB and Ramsey, without the typing: history proposes the budget, questions adjust it, and every dollar of income has a place to go.

9. **History proposes the budget.** Once imports cover three months or more, every personal category gets a proposed monthly amount: the median of the last six months (three if that is all there is), rounded to the nearest $10, labelled "From your history". Income is proposed the same way. The owner types nothing to start. *Recommended: yes.*
10. **Envelopes.** An envelope is a category with a monthly amount. Each month shows Planned, Spent and Left. Overspending turns an envelope red and asks where to take it from (another envelope's Left) or whether to let it stand; nothing moves by itself. *Recommended: yes.*
11. **Rollover by kind.** Left in an everyday envelope (groceries, dining) resets each month. Left in a savings-type envelope (goals, yearly bills, the tax envelope) rolls forward. Each envelope has the switch; the defaults follow the kind. *Recommended: this mix. YNAB rolls everything, Ramsey resets everything; owners need both.*
12. **Every dollar has a job.** The Overview shows Income this month minus all envelopes as **Unassigned**. Above zero, it asks where the rest goes (a goal, a debt, the tax envelope). Below zero, it shows which envelopes are over the income. *Recommended: yes. This is the envelope discipline without the envelope chores.*
13. **Guided adjustments.** After the proposal, and again when a category drifts 25% from plan for two months, the app asks a short run of questions, one screen each, any of them skippable:
    - "Groceries have run $812 a month. Keep that, or set a target?"
    - "Dining was $340 twice and $120 once. Which is normal?"
    - "This looks like a yearly bill: car insurance, $1,140 in March. Spread it monthly?"
    - "Anything coming that your history doesn't show?" (which creates a goal or a planned line)
    These are the app's own questions, no AI call. "Explain this budget" with Claude is separate and priced first. *Recommended: yes.*
14. **Goals.** A goal is a name, a target amount, a target date (or none), what is already saved, and which account holds it. The app computes the monthly amount, makes an envelope that rolls, and puts the target on the forecast as a planned line. A vehicle repair, a vacation not yet booked, Christmas, an insurance deductible. An emergency fund is a goal whose target is a number of months of envelopes. Yearly bills found in history (M2 already finds "likely annual") are spread the same way, so the money is there on the day. *Recommended: yes.*

## Decisions 15–19: forecast, debts, retirement, household, net worth

15. **Personal cash forecast.** M2's engine on the personal accounts: cash today, Known lines (bills with due dates, debt minimums, estimated-tax dates), Regular lines from history, Planned lines (goals, one-offs), what-ifs, a floor, the 30/90/180-day and 12-month views, and "How good it has been". Pay from the practice is a Known line at the cadence it has been paid; spouse pay is Regular. Its own page under Personal; never drawn in the same chart as the business forecast. The Overview shows both sides' ending balances side by side. *Recommended: yes.*
16. **Debts.** Name, kind (card, auto, mortgage, student, personal, medical, other), balance, rate, minimum payment, due day, whose. A credit card that is also an imported account takes its balance from the import; other debts take a balance entered monthly or from a statement. A payoff plan: **smallest balance first** or **highest rate first** (renamed from "Snowball" and "Avalanche" on 2026-10-19, on screen, here and in the AI prompts; the codes stay), plus an extra monthly amount; shows each debt's payoff date, total interest, and what the other order would cost or save. The extra becomes an envelope; payments show on the forecast; each debt has a balance-over-time chart. *Recommended: yes, both orders offered, smallest balance first the default.*
17. **Retirement and investments.** Accounts with a balance history (entered monthly or from a statement; no live feeds), contributions recognized from transfers, a target (an amount by a year), and "on track / behind" from the contribution rate and an assumed yearly return the owner sets (default 6%), with the estimate disclaimer. A progress chart per account. *Recommended: yes, simple.*
18. **Household.** The owner plus the people they add (a spouse or partner). A person is a label, not a sign-in. Income, accounts, debts and retirement each carry *whose*: owner, spouse or joint. Views: the household, or one person. The spouse's expected W-2 withholding feeds the tax estimate. *Recommended: yes.*
19. **Net worth.** Assets (bank accounts, retirement and investments, plus items entered by hand such as a home or vehicle with a value and a date) minus debts, as one line over time on the Overview, with a home's value against its mortgage shown as equity. No valuations fetched. *Recommended: yes; it is almost free once 16 and 17 exist, and it is the number people check.*

## Decisions 20–23: paying yourself, quarterly taxes, For your CPA

20. **Paying yourself is one line on both sides.** A draw from the practice is an owner draw in the books (as now) and "Pay from <practice>" on the personal side, matched automatically when both accounts are imported (same amount, same or next day). The personal budget tells the business forecast what is needed: "Your envelopes need $X a month; you have paid yourself $Y on average." The owner can set the business forecast's pay-yourself line from it. *Recommended: yes. This is the loop that makes the two sides one system.*
21. **Quarterly tax set-aside, an estimate.** Inputs the owner enters once a year: filing status, state, last year's total tax and taxable income from the return (or just an effective rate), and the spouse's expected withholding. From business net profit year to date (the books) and the household's other income the app estimates self-employment tax (15.3% of 92.35% of net profit, with half deductible), federal income tax at the year's brackets, and state at a rate the owner enters. It shows: the amount per quarter with the IRS dates (Apr 15, Jun 15, Sep 15, Jan 15); the safe-harbor alternative (100% or 110% of last year's tax); a **set-aside percent per draw**; and a **Tax envelope** with saved-so-far against needed-by-next-date. Estimated payments already made (marked on the business side today, and now on the personal side too) reduce what is needed. The bracket table is data with a year on it; a missing year says so and uses the last one with a note. Every figure carries "estimate; confirm with your CPA". *Recommended: yes.*
22. **For your CPA shows both sides.** One page, a year selector, two sections. Business: the worksheet as built in M1. Personal: the CPA's Itemized Deduction Worksheet by its groups (medical and dental, health insurance, interest paid, property taxes, charitable contributions, non-cash donations by charity, as on the CPA's sheet; medical and charitable miles are year-end facts like M1's business miles, and a non-cash donation names its charity on the line), filled from personal lines whose category carries the Tax-deductible mark, every line listed; and a **Personal facts** block: estimated payments by quarter with dates, health insurance premiums paid as a self-employed person, retirement contributions by account, HSA, childcare and education, each with an "ask your CPA" note. One PDF with both sections; the business export alone stays as it is. *Recommended: yes.*
23. **Standard against itemized.** The personal section shows the itemized total next to the standard deduction for the filing status and year, so the owner sees whether itemizing is likely to matter. No advice beyond "ask your CPA". *Recommended: yes.*

## Decisions 24–27: privacy, AI, wording, module

24. **Privacy.** Personal data belongs to the owner. Associates, assistants, the platform's Practices page, digests, staff Activity and the business features' AI prompts never see it. It is in the same database and the same backups. *Brief wins ("ALL FOUR"): the privacy policy and the beta agreement are amended for personal financial data before any beta user is offered M4.* The owner can delete the whole personal side in Settings, with a confirmation that names what goes. Account numbers are never stored, as in M1, and the isolation test family is extended to cover the personal side, as the brief asks. *Recommended: yes.*
25. **AI, priced first every time.** Three uses: Sort these with Claude (decision 6); Explain this budget and Explain this forecast (M2's pattern, low effort, the shared 20-a-day cap); Review with Claude, which proposes changes to envelopes, goals and the set-aside (M2's pattern). The practice's key and monthly budget. Merchant names go out for sorting and the button says so; amounts and category names for the rest; never account numbers, balances of retirement accounts, or the owner's name. *Recommended: yes.*
26. **Wording and disclaimers.** "Personal" in every page title on that side. Plain words on screen: envelope, goal, debt, set aside; never "sinking fund" or "zero-based". The Finance disclaimer gets a personal version on every personal screen, bold on the Taxes page: *"Budgeting, forecasting and tax estimates only, not tax, legal or financial advice. Confirm with your CPA."* *Recommended: yes.*
27. **Module and demo.** Personal finance is its own module switch per practice in the Practices area, off for existing practices, on for the demo. Priced as a module when pricing is set ($25 or $50 a month were the figures heard). The demo seed gives John Carter a personal side: two personal accounts and one mixed card, six months of lines, three goals, two debts, one retirement account, a spouse with pay, and a set-aside in progress. *Recommended: yes.* *Brief wins: the two debts are a mortgage and a car loan, and there are retirement **and** investment balances; the mixed card has been split, there is a budget and a net-worth trend.*

## The tax-deductible groups (owner, 2026-10-10, kept from the placeholder)

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

How this spec settles those four, decided where it says so and otherwise the
spec's reading, for Bryan to overrule:

- **Miles** (medical and charitable) are year-end facts, as M1's business
  miles are (decision 22).
- **Non-cash donations** name their charity on the line (decision 22).
- **Tax-deductible is a mark on a category**, naming one of the six groups;
  the chart keeps two levels (brief against spec, last row).
- **Who sees it:** the owner of the ledger only (decision 24). Household
  members with their own sign-in come in a later stop (decided 10/15).

## Build order

Four stops, each released on its own after an owner acceptance pass on the demo, the way M1 and M2 went. Sizes are CC days, rough.

| Stop | Builds | Proves | Size |
| --- | --- | --- | --- |
| 1. Sides | Account kinds, a side on every line, rules and dry run, the crossing-sides posting (paid personally, owner draw), the personal chart with tax marks, To sort and the threshold, Sort these with Claude, transfers, optional reconcile, the Business / Personal switch, the Accounts and Entries pages, connection fields on accounts unused for now | One mixed card imports once and both sides come out right | 3 days |
| 2. Budget | Proposals from history, envelopes, rollover by kind, Unassigned, the guided questions, goals, yearly bills spread, the Overview with a Cash flow table by month | A budget exists without anyone typing one | 3 days |
| 3. Forecast and the rest | Personal forecast, debts with the payoff plan, retirement, household (labels), net worth with property equity | The vehicle repair shows on the forecast; the payoff date moves when the extra changes | 2–3 days |
| 4. Taxes and the CPA | Pay-yourself loop, the set-aside with the Tax envelope, For your CPA with both sections and the standard-against-itemized line | The quarterly number and the Jan 15 line; one CPA PDF with both sides | 2 days |

Stop 1 must come first; everything else stands on sides. The other three can be reordered. If the set-aside matters before the Jan 15 estimated payment, run 1, 4, 2, 3 instead. Household sign-in invitations come after stop 4, once the external Google client is sorted.

## Brief against spec

The brief (saved 2026-10-11) wins where the two differ, unless a recorded decision says otherwise. The four open points were decided on 10/15 (Bryan): **the four decisions of 2026-10-15** are the first four rows. The rest are folded into the decisions above, or marked *Brief wins*.

| Point | The brief says | This spec says | Stands |
| --- | --- | --- | --- |
| Where it lives | Its own Personal area from the top-left switcher; the ledger belongs to the user, not the practice, and survives leaving any practice | Under Finance behind a Business / Personal switch | **Decided 10/15: a Business / Personal toggle inside Finance, so Personal is its own section but stays under Finance. Ownership as the brief: the ledger is the user's and survives leaving a practice** |
| Household sign-in | Members invited by email, sign in through the external Google client (test-user step), with a permission set: Personal, Business or both; audited | A person is a label, no sign-in | **Decided 10/15: a spouse's own sign-in is wanted but not first. Labels in stop 3; invitations with a permission set as a later stop, once the external Google client is sorted** |
| Month close | Reconciliation and month close on the personal side | Reconcile optional, no close | **Decided 10/15: no month close on the personal side (decision 8 stands)** |
| Budget proposal | The AI proposes from closed months; the owner sets it; budget against actual with overage flags | Arithmetic from history, guided questions, Claude on request | **Decided 10/15: arithmetic from history, Claude on request (decisions 9 and 13 stand); overage flags are in decision 10** |
| Cash flow view | Monthly in and out by category | Envelopes only | Added: a Cash flow table by month on the Overview |
| Postings reversible | Each posting from a mixed import is reversible | Silent | Added to decision 3 |
| Aggregator later | Account model ready for Plaid or similar; none now | Silent | Added to stop 1: accounts carry a connection id and fields, unused for now |
| Property equity | Property value against mortgage balance shown as equity | Net worth only | Added to decision 19 |
| Isolation | Extend the isolation test family | Privacy in words | Added to decision 24 |
| Account kinds shared with M3 | M3 adds loan, line of credit, property, investment and retirement kinds | Debts and retirement as their own lists | Build the kinds once; whichever of M3 or M4 comes first creates them |
| Tax-deductible groups | The placeholder's six CPA groups; miles are counts; non-cash donations name a charity | Had generic Schedule A groups | Fixed in decision 22 |
| Tax-deductible: level or mark | Undecided in the placeholder | A mark on categories | Spec stands; the chart keeps two levels |
| Privacy policy and beta agreement | Amended for personal financial data before any beta user is offered M4 ("ALL FOUR") | Silent | **Brief wins** (found when writing this spec, 10/15): a condition on offering M4, not on building it |
| AI cap | AI calls costed and under the daily cap ("ALL FOUR") | Sort these with Claude: the monthly budget, not the daily Explain cap | **Brief wins** (found 10/15): one count on Finance's shared 20-a-day cap per press, and the monthly budget |
| Demo seed | A mortgage, a car loan, retirement and investment balances, a mixed card that was split, a budget, a net-worth trend, a spouse member | Two debts, one retirement account | **Brief wins** (found 10/15): decision 27 is read with the brief's list |

## Open questions

- The don't-ask threshold: $25, or another number?
- Rollover defaults: everyday envelopes reset, savings-type roll. Keep?
- Smallest balance first as the default payoff order, with highest rate first a switch away?
- Assumed return for retirement projections: 6% default?
- Tax inputs: will owners enter last year's total tax and taxable income, or should the first version take only a percent?
- State tax as a flat rate the owner enters, or should the app know each state's brackets?
- Build order: 1, 2, 3, 4 as written, or taxes before the budget for the Jan 15 payment?
- A spouse for John Carter on the demo: name and job?
- Where M3 sits now that M4 is high on the list.
- Decided 10/15: where it lives (a toggle inside Finance), spouse sign-in (later), no month close, budget by arithmetic.

## As built: stop 1 (2026-10-15)

### The first slice (`0f324a8`)

**Built and tested:**

- **Ownership** (the brief, decided 10/15): a new app, `apps/personal`, whose
  rows hang off a `PersonalLedger` that belongs to one **user**, not a
  practice. They are not tenant-scoped, so the ledger survives its owner
  leaving any practice. The isolation family is extended to it
  (`tests/test_personal_sides.py`): every model of the app is registered and
  read through `of(user)`; another practice owner, anyone else in the
  practice, the platform owner and a practice without the module reach none
  of it.
- **The module** (decision 27): "Personal finance", switched per practice in
  the Practices area, off for every practice. Without it the routes are 404
  and the switch is not shown.
- **Account kinds** (decision 1): a practice account is Business or **Mixed**
  (Settings → Finance, the Side column). Personal accounts are the
  household's own, in the ledger. All carry connection fields, unused.
- **A side on every line** (decision 2), set by rules (a rule now has a
  side: business, personal, or split with a percent) and shown beside the
  category in the import's dry run, where the owner can change it.
- **The crossing posting** (decision 3): a personal line in a Mixed or
  Business account is an **owner draw** in the books (money in: an owner
  contribution) and the spend itself in the ledger, under a personal
  category; a split is an expense for its business part and a draw for the
  rest. Only business lines reach the P&L. Removing the draw (by hand, in
  bulk, or by rolling the import back) removes its ledger line; editing its
  date or amount carries to the ledger.
- **The personal chart** (decision 4), with the CPA's six groups as
  Tax-deductible marks on the sub-categories they fit (Personal →
  Categories), editable.
- **Light sorting** (decision 5): a Mixed account's line with no rule under
  the owner's threshold (default $25) is personal, Everything else, without
  asking; at or over it, it waits in **To sort**. Sorting it (to either side,
  with a category) can remember a rule. Ledger lines are recategorized one
  at a time or in bulk.
- **The Business | Personal switch** at the top of Finance, remembered in the
  browser; the Personal side has its own band, "Personal" in its title and
  the personal disclaimer (decision 26), and three pages: Entries (with To
  sort), Accounts, Categories.

**Choices made while building** (Bryan, 2026-10-15: **all five stand**):

1. A **Mixed account lives in the practice's books**, not the ledger: its
   business lines are the practice's, it is reconciled with the business
   month (decision 8), and its personal lines are owner draws there. Its
   personal lines are copied into the owner's ledger, so they stay the
   owner's if they leave.
2. A line of a Mixed account that waits in To sort is in the books as an
   uncategorized expense or income until it is sorted (marked "to sort"),
   because the bank shows it and the card's balance must be right.
3. The threshold applies only to **Mixed** accounts among the practice's: a
   Business account's line with no rule is the practice's, as before; a
   personal rule still reaches it. (On a household account the threshold
   applies as decision 5 says; see below.)
4. A split chosen by hand in the dry run is in dollars (the business part);
   a split rule is a percent.
5. Whose ledger: the person who commits the import (Finance is the practice
   owner's alone).

### The rest of stop 1 (second slice)

**Built and tested** (`tests/test_personal_accounts.py`, the demo seed test,
`FinanceImport.test.tsx`, `PersonalFinance.test.tsx`; screens looked at in
headless Chrome at 1366):

- **Rules by hand.** Settings → Finance → Import rules has **Add rule** and
  **Edit**: the text to look for, the category, and with Personal finance the
  side (Business, Personal with a personal category, or Split with the
  percent that is business and a personal category for the rest). Without
  the module a rule has no side and the route refuses one. The dry run's
  "remember" now works for a **split** chosen by hand, saved as the percent
  that line's split works out to (a $50 business part of $200 is a 25% rule),
  and the import's other lines take it at once. Rules learned on the
  personal side (sorting a line, or a personal account's dry run) carry the
  side and the personal category.
- **Importing into a personal account** (decisions 2, 3, 5), Personal →
  Import: CSV, OFX/QFX/QBO and PDF, the books' own reading and the same three
  steps (dry run, commit, rollback), in the ledger's own tables
  (`PersonalImport`, `PersonalImportRow`: the owner's, not the practice's).
  With no rule a line is personal, under the threshold in Everything else,
  at or over it To sort. A line that is the practice's (by a business rule,
  or chosen) is **paid personally**: in the books an income or expense in
  its category, side `paid_personally`, in **no account of the practice's**;
  it is in the P&L, in its line of the CPA's worksheet, and named again
  under the worksheet's Net as "Expenses paid from a personal account … an
  owner contribution". The balance view and the forecast leave it out of the
  practice's cash. In the ledger the line stays in its account, in the system
  category **Paid for the practice** (not spending), so the account's balance
  is the bank's. A split is both. The rollback takes all of it back (an
  entry edited in the books since is kept and named, as the books' rollback
  does). Moving a paid-personally entry into one of the practice's accounts
  in the books, or removing it, sends its line back to To sort; sorting the
  line to personal removes the entry.
- **Transfers** (decision 7): a line that matches one already in the ledger
  (the other way, the same amount, within five days, from another of the
  household's accounts or the personal side of a Mixed card's line, not yet
  sorted or already a transfer) is proposed in the dry run as **the other
  side of a transfer**, and declinable. On commit the two are paired and both
  are in Transfers, which is never spending. A card payment from joint
  checking pairs with the Mixed card's payment line. The rollback unpairs and
  puts the other line's category back.
- **Reconcile, optional** (decision 8): Personal → Accounts shows each
  household account's balance and "reconciled through", and a **Reconcile**
  for each: the statement's date and balance, tick until the difference is
  zero, Finish; Reopen the last one; throw away one in progress. No month
  close, and nothing in the books is locked by it. A finished statement holds
  its lines: an import under it cannot be rolled back until it is reopened.
- **Sort these with Claude** (decision 6), on To sort: priced before it is
  pressed, by the number of lines waiting (at most 80 a press); the button
  says what is sent (each line's description as the bank printed it, its
  amount and way, and the category names; never an account's name or number,
  a balance, or the owner's name). One call proposes a side and a category per
  line and the text to remember it by (a piece of the line's own
  description; otherwise its first two words). Nothing is stored or changed
  by the call. The owner unticks or edits, then **Accept all**: each goes
  through the ordinary sort route and becomes a rule. It counts once a press
  on Finance's shared 20 a day (`explain.PRESSED`) and stops at the monthly
  AI budget. Its cost is the call's `ai_call`.
- **The demo seed's personal side** (decision 27 with the brief), built inside
  the books' month loop so each month's statements come in before that month
  is reconciled and closed (`apps/tenancy/demo/household.py`): the module on;
  John Carter and **Dana Carter** (spouse, a pediatric nurse: the spec's open
  question, answered for the demo only); **Joint checking** and **Joint
  savings**; a Mixed card, **Everyday Visa**, reconciled with each business
  month; the owner's rules typed by hand (groceries, dining, fuel, Netflix
  personal; home internet 40% and Amazon 25% business splits; printing and
  Canva the practice's); **six months** of each account's statement
  imported, the card through the books' import and the two household
  accounts through the personal one, the odd line sorted by the owner each
  month; spouse pay twice a month and pay from the practice the day after
  each owner draw, with 28% of each draw moved to savings for tax; card
  payments and savings moves paired as transfers; Canva from joint checking
  paid personally; last month's savings statement reconciled; last month's
  Costco, hardware and doctor lines and this month's card lines no rule
  knows waiting in To sort. **Data only until stops 2–4 draw them**: the home
  mortgage and the car loan with month-end balances, a Solo 401(k), Dana's
  403(b), a Roth IRA and a joint brokerage with month-end balances, three
  goals (emergency fund, car repairs, Christmas) and this year's tax
  set-aside so far. The seed's summary counts all of it.

**Models added** (`personal 0002`): `PersonalMember`, `PersonalImport`,
`PersonalImportRow`, `PersonalReconciliation`, and for the later stops
`PersonalDebt`, `PersonalHolding`, `PersonalBalance`, `PersonalGoal`,
`PersonalSetAside`; on `PersonalAccount` whose and the remembered columns; on
`PersonalLine` the paid-personally entry, the transfer's pair and the
statement it was ticked on. `finance 0015`: the side `paid_personally`, and
the side's shape allowing it. All in the isolation family.

**Choices made in this slice, for Bryan to keep or overrule:**

1. **Paid personally is one entry**, an income or expense in no account of
   the practice's, marked `paid_personally`, not an expense plus a separate
   owner-contribution entry. The P&L and worksheet count it; "an owner
   contribution" is how the balance between them reads it, and the balance
   sheet (M3) will read it from the mark.
2. **The PDF of a personal statement is not kept**; its lines, period, two
   balances and cost are. (The books keep theirs for the Reconcile screen.)
3. **On a household account the threshold applies**: no rule and under $25
   is Everything else; at or over, To sort (decision 5 as written).
4. The practice's **transfer and ignore rules, and rules for one of its own
   accounts, do not reach a household account's lines**; its category rules
   (business, personal, split) do. Transfers between household accounts are
   found by matching, not by rule.
5. **Sort these with Claude proposes personal or business only**, never a
   split; a split is the owner's to make.
6. An in-progress personal reconciliation can be **thrown away** (its ticks
   come off); a finished one is only reopened.

**Not built in stop 1:** screens for debts, retirement and investments,
goals, the household and the set-aside (their stops); a business line paid
personally from cash; transfer rules for household accounts; removing a
personal line by hand.

## As built: stop 2 (2026-10-17)

Decisions 9–14 as written, the brief's Cash flow table, and "Explain this
budget". The open questions taken as recommended (Bryan, 2026-10-17): the
$25 threshold; everyday envelopes reset and saving-up ones roll; smallest
balance first the default, 6% the assumed return, tax inputs either way and state as a
flat rate, all later.

**Built and tested** (`tests/test_personal_budget.py`, the isolation family
in `tests/test_personal_sides.py`, the demo seed test,
`PersonalBudget.test.tsx`; the Overview, the questions and a goal looked at
in headless Chrome at 1366):

- **The proposal** (9, `apps/personal/budget.py`): once the lines cover three
  complete months, each personal category's monthly totals over the last
  six complete months (fewer if that is all), a month with nothing counted
  as nothing, the median to the nearest $10, "From your history". Income the
  same way. Transfers never. Shown as a table with the months; nothing is set
  until **Use this budget**.
- **Envelopes** (10): Planned, Spent (the month's lines in the category, less
  money back in it) and Left. Overspent: red, and **Take it from** another
  envelope's Left (an `PersonalEnvelopeMove`, at most what it has), or **Let
  it stand** (remembered for the month). Nothing moves by itself. Spending in
  a category with no envelope is named under the table.
- **Rollover by kind** (11): everyday resets, saving-up (goals, yearly bills,
  Taxes) rolls; a switch on each, the default by kind.
- **Unassigned** (12): planned income minus every envelope. Above zero, "Where
  does the rest go?", put toward a goal (its monthly amount goes up). Below
  zero, the envelopes over the income, largest first.
- **The questions** (13, `apps/personal/questions.py`, no AI): after the
  proposal, keep-or-target for the two largest everyday envelopes that varied,
  which-is-normal where a category's months fell into a high and a low group,
  a yearly bill for each one found, and "Anything coming?" (a goal, or a cost
  on a date: a `PersonalPlanned`). One screen each, skippable, each with a key
  so never asked twice. Again, keep-or-target, when an everyday envelope has
  been 25% or more off its plan in each of the last two complete months.
  "Something coming that your history doesn't show?" asks the last one again.
- **Goals** (14): name, target, date or none, saved already, the account. The
  monthly amount is what is still to save over the months left, up to the
  next $10; with no date, the owner's amount or a year's worth. An envelope
  that rolls, and with a date a planned line on that day for the target. An
  emergency fund is a number of months of the everyday envelopes. Progress is
  what was saved plus what its envelope has set aside. Put away: its envelope
  and planned line go.
- **Yearly bills** found in history (a single payment of $250 or more in a
  category with nothing in the other months) are asked about and, if spread,
  become a rolling envelope at a twelfth.
- **The Cash flow table** by month on the Overview: in and out by category,
  the last six complete months and this one so far, with In, Out and Net.
- **Explain this budget** (`budget_ai.py`): priced before it is pressed, on
  Finance's shared 20 a day and the monthly budget. Sends the envelopes,
  goals, yearly bills and six months of totals by category; never the
  owner's name, an account's name or number, or a merchant.
- **The Personal side** now opens on **Overview**, then Goals, Entries
  (moved to `/finance/personal/entries`), Import, Accounts, Categories.
- **The demo:** John Carter's budget proposed from the six seeded months and
  used; the three goals live with their envelopes, two of them dated with a
  planned line; a home policy of $1,380 in the window's second month spread
  (its question answered); a family dinner and a Costco run this month so
  Dining and Groceries are over; the other questions waiting.

**Models** (`personal 0003`, additive): `PersonalEnvelope`,
`PersonalEnvelopeMove`, `PersonalPlanned`, `PersonalQuestion`; on
`PersonalGoal` the months of envelopes and a chosen monthly amount. All in the
isolation family.

**Choices made in stop 2, for Bryan to keep or overrule:**

1. **A bill the same amount every month is proposed up to the next $10**, not
   to the nearest. At the nearest, a $22.99 subscription gets $20 and reads as
   overspent every month; the demo showed four envelopes over for that alone.
   Everything else is the nearest $10 as decision 9 says.
2. **Unassigned uses planned income**, not what has come in so far, so it does
   not swing through the month; "in so far" is shown beside it.
3. **A goal's progress** is what was saved when it was made (or updated) plus
   what its envelope has set aside since. Moving money to savings is a
   transfer, so the app does not count it toward a goal by itself.
4. **One envelope per category.** Spreading a yearly bill turns that
   category's envelope into a saving-up one.
5. **A yearly bill** is found by a single payment of $250 or more with nothing
   else in that category over the months covered. Six months of history
   cannot tell yearly from twice a year (the demo's car insurance is asked
   about too), which is why it is a question, never applied.
6. **The demo's Unassigned is large** ($17,660 on the day it was looked at):
   pay from the practice is planned at the median of the draws, and the 28%
   moved to savings for tax is a transfer, not an envelope. The Tax envelope
   (stop 4) is where that will show.

**Not built in stop 2:** the personal forecast that will read the planned
lines (stop 3); a debt as a place for Unassigned (stop 3); the Tax envelope
(stop 4); removing a planned line from the Overview.

## As built: stop 3 (2026-10-17)

Decisions 15–19 as written, "Explain this forecast" and "Review with Claude"
on the personal forecast (M2's pattern), and Unassigned toward debts (stop 2's
"not built"). Open questions as recommended (Bryan, 2026-10-17): smallest balance
first the default, 6% the assumed return. Stop 2's six choices were kept.

**The stop's proof** is tested: the car repair (a dated goal) is a Planned
line on its date in the forecast, and a debt's payoff date moves when the
extra changes (`tests/test_personal_forecast.py`, the first test of each).

**Built and tested** (`tests/test_personal_forecast.py`, 35 tests; the
isolation family in `tests/test_personal_sides.py` with the three new
models; the demo seed test; `PersonalForecast.test.tsx`,
`PersonalWorth.test.tsx`; the forecast, Debts, the Overview's net worth,
Retirement and Household looked at in headless Chrome at 1366 on a freshly
seeded scratch demo, no console errors):

- **The personal forecast** (15, `apps/personal/forecast.py`, its own page
  under Personal → Forecast). M2's table, spans, summaries, views (30, 90,
  180 days, 12 months), floor and what-if, on the household's own accounts:
  - **Cash** is the household's bank and cash accounts, from their lines.
    A card is not cash: its payment out of checking is drawn, its charges
    are not. A Mixed card's payment from joint checking is drawn the same way.
  - **Known:** pay from the practice at the cadence it has been paid (as many
    times a month as the last three complete months show, each on the median
    day and amount); each debt's payment under the payoff plan on its due day
    (this month's left out once a line in its category is in, drawn today if
    its day has passed without one); each yearly bill the budget spreads, in
    its month on the day it was last paid; estimated tax paid from a
    household account, on the IRS dates.
  - **Regular:** M2's rules on the complete months (monthly when seen in two
    of the last three, quarterly when about three months apart), by category
    and payee, but the Known categories. Moves between two of the household's
    cash accounts are neither in nor out. Spouse pay is Regular.
  - **Planned:** goals with a date (the target, spent that day), one-offs and
    repeating lines, and what-ifs (drawn only while tried, never counted).
  - **Adjustments:** a Regular line is "not regular", or another amount from a
    date; undone, not deleted.
  - **"How good it has been":** a snapshot the first time each month's
    forecast is worked out, beside what happened.
  - Two complete months are needed before anything is Regular; until then
    it is only Known and Planned, and it says so.
- **Debts** (16, `apps/personal/debts.py`, Personal → Debts): name, kind,
  balance, rate, minimum, due day, whose, and the category its payments land
  in. A card that is an imported household account takes its balance from its
  lines. The plan, month by month from this one: interest at a twelfth of the
  yearly rate, every minimum, then the extra plus each paid-off debt's minimum
  to one debt at a time in the plan's order, set from today's balances.
  Shown: each debt's payoff date and interest, the totals, what the other
  order would cost or save (interest and months), and what the extra saves
  against the minimums alone. Changing the order or the extra on the page is
  a look; "Save the plan" saves. A balance-over-time chart per debt: what was
  entered, then the plan's projection, dashed. A debt whose minimum never
  covers its interest says so.
- **The extra is an envelope** in "Debt payments": made, moved by the
  difference, put away at nothing. Unassigned can go toward the debts; the
  extra goes up by it.
- **Retirement and investments** (17, `apps/personal/retirement.py`):
  balances entered monthly or from a statement; contributions recognized from
  lines out of the household's accounts that contain the account's text
  ("VANGUARD ROTH"), averaged over six complete months, or typed where no
  line shows them; a target by a year; on track or behind at the owner's
  assumed return (6% unless changed, 0–20%), compounded monthly to the end of
  the target year, with what a month would reach it; the estimate disclaimer
  in bold; a chart per account with the target as a line.
- **The household** (18, `apps/personal/household.py`, Personal → Household):
  the owner (made the first time) and the people they add, labels only; each
  income category, account, debt, retirement account and thing owned carries
  whose (a person, or joint); Debts, Retirement and net worth show the
  household or one person (theirs alone). A spouse's expected W-2
  withholding is kept for stop 4. Taking someone out makes theirs joint.
- **Net worth** (19, `apps/personal/networth.py`, on the Overview): the
  household's bank and cash accounts, retirement and investments, and things
  owned with a value entered by hand (a home, a vehicle; `PersonalAsset`),
  less debts; month ends back to the first with a figure (at most twelve) and
  today, as one line; a home or vehicle against the loan named on it as
  equity.
- **Both sides on the Overview** (15): the personal and the business
  forecast's cash in 90 days, today's figure and the low point, as numbers
  side by side, never one chart; "not switched on" for a practice without the
  Cash forecast module.
- **Explain this forecast and Review with Claude** (`forecast_ai.py`): priced
  before they are pressed, one count each on Finance's shared 20 a day,
  never past the monthly budget. Sent: amounts, dates and category names. A
  line goes by its category, a debt by its kind ("Mortgage payment"); never a
  merchant or lender, an account's name or number, a retirement balance, or
  the owner's name. The review proposes one-offs among the Regular lines,
  recurring lines not picked up, and up to six questions, each answered by the
  owner through the ordinary routes (not regular; a planned line).
- **The demo:** the mortgage and the car loan with their payment categories;
  the payoff plan (smallest balance first, $200 extra, so the car loan goes first, by
  October 2028); the Roth IRA's contributions recognized from its transfers,
  the Solo 401(k)'s ($2,000) and Dana's 403(b)'s ($450) typed; a target on the
  Solo 401(k) (behind) and the Roth (on track); Dana as a household member
  with her pay and $8,400 expected withholding; the house ($612,000) against
  the mortgage and the Subaru against its loan; a $8,000 floor, a summer trip
  planned and a new roof as a what-if; and the forecast as he saw it on the
  third of each month, so four months show in "How good it has been".

**Models** (`personal 0004`): `PersonalAsset`, `PersonalForecastSnapshot`,
`PersonalForecastAdjustment`; on the ledger the floor, the payoff order and
extra, and the assumed return; on a member the expected withholding and a
removed time; whose on a category; a payment category on a debt; the
contribution text and a typed monthly amount on a holding; repeat and
what-if on a planned line; an asset's value on `PersonalBalance` (its check
constraint now allows one of three); the envelope source "debt". All in the
isolation family.

**Choices made in stop 3, for Bryan to keep or overrule:**

1. **A card is paid as it has been paid.** The personal forecast draws a
   card's monthly payment out of checking as a Regular line and does not draw
   its charges, rather than M2's "what is owed today, then what is forecast
   to be charged". It works the same for a household card and the Mixed card,
   which lives in the practice's books.
2. **A Regular line comes as often as it has come.** M2 adds a month's
   occurrences into one line on the first day; here, pay twice a month is two
   lines, so the weekly view is right. (M2's own forecast is unchanged.)
3. **A debt's payments are Known only when the debt names its category.**
   Otherwise its payments would be counted twice, as the plan's and as
   everyday spending. The demo's two do.
4. **A goal with no date is not a line.** An emergency fund is saved for and
   never spent on a day; the forecast lists it under Planned with where its
   money sits (savings, which is in the cash). The demo's car repairs and
   Christmas are lines; the emergency fund is listed.
5. **The extra is added to "Debt payments"' envelope** if the category
   already has one, by the difference, rather than replacing it (one
   envelope per category, stop 2's choice 4).
6. **"How good it has been" is worked out from the lines each time**, not
   stored at a month close: the personal side has none, and statements come
   in days after a month ends. "What happened" is the month's lines that came
   in after the snapshot was taken.
7. **One person's view is theirs alone;** joint things are in the
   household's. The forecast is the household's only: its accounts are joint.
8. **Review with Claude reviews the forecast**, as M2's does and as Bryan's
   brief for this stop says. Decision 25 also has it proposing changes to
   envelopes, goals and the set-aside; that waits for stop 4, with the
   set-aside.
9. **A Mixed card is not in net worth:** it is the practice's account. Its
   personal lines are, as they are paid from household accounts.

**Not built in stop 3:** household sign-ins (a later stop); the Tax envelope,
the set-aside and the pay-yourself loop (stop 4); a personal forecast for one
person; an "until" on a repeating personal planned line; M2's "likely annual"
on the personal side (yearly bills are the budget's questions instead).

## As built: stop 4 (2026-10-19)

Decisions 20–23 as written, decision 25's Review with Claude on envelopes,
goals and the set-aside, and the payoff orders renamed (backlog U3).

**The stop's proof** is tested: the quarterly number and the Jan 15 line
(`tests/test_personal_taxes.py`,
`test_the_four_dates_the_jan_15_line_and_the_safe_harbor`), and one CPA PDF
with both sides (`test_one_page_and_one_pdf_with_both_sections_and_the_business_csv_unchanged`).

**Built and tested** (`tests/test_personal_taxes.py`, 33 tests; the isolation
family in `tests/test_personal_sides.py` with the two new models; the demo
seed test; `PersonalTaxes.test.tsx`, the review in `PersonalForecast.test.tsx`,
the names in `PersonalWorth.test.tsx`; the Taxes page, For your CPA (page and
PDF) and the Overview's pay-yourself card looked at in headless Chrome at
1366 on a freshly seeded scratch demo, no console errors, no sideways
scroll):

- **Paying yourself** (20, `apps/personal/paydays.py`). An owner draw out of
  one of the practice's bank or cash accounts (not estimated tax, not
  personal spending on a practice card) and money in to a household bank
  account of the same amount, that day or the next, are **matched**: the
  personal import's dry run proposes the line as pay, and the commit links
  it (`PersonalLine.draw_entry`). Matching also runs when the books import or
  a draw is typed. A line the owner placed in another category is left
  alone; removing the draw unmatches the line, which stays pay. The starting
  chart's "Pay from the practice" is named **"Pay from <practice>"** the
  first time the ledger is opened from the practice (a name the owner gave it
  is kept). With no household account imported, the books' unmatched draws
  are the personal forecast's Known pay line, at their cadence. The
  Overview's **Paying yourself** card: "Your envelopes need $X a month
  (beyond other income); you have paid yourself $Y a month on average over
  the last six months", and **Set it to $X a month** sets the business
  forecast's pay-yourself line: an amount adjustment of its largest regular
  owner-draw line (source "personal", undone there like any other), or, with
  no draws found yet, a planned "Pay yourself" line monthly.
- **The set-aside** (21, `apps/personal/taxes.py`, `tax_tables.py`, Personal
  → Taxes). Inputs once a year (`PersonalTaxYear`): filing status, state and
  its flat rate, last year's total tax and taxable income, or a federal rate
  instead of the brackets, and other household income before withholding
  (empty: the income lines at this year's pace). The estimate: business net
  profit so far (cash basis) at this year's pace; self-employment tax; half
  of it deducted; the standard deduction, or the itemized total if larger;
  federal at the year's brackets (2025 and 2026, data with a year; a missing
  year names the year used); state at the owner's rate on the same taxable
  income; less the spouse's expected withholding. The four dates, a quarter
  of the year's figure each; the next date's figure (all quarters through it,
  less what is paid); the safe harbor beside it (100%, or 110% over $150,000);
  payments from the practice's books (marked estimated tax) and the
  household's Taxes categories, a January payment counting to the year
  before. The set-aside: the percent and what is set aside so far (the
  owner's), what that percent of the draws since the last payment comes to,
  and the share of each draw from here that covers what is still needed.
  **The Tax envelope** is an envelope in Taxes (source `tax`, saved up):
  Planned is its monthly amount and counts against Unassigned; its Left is
  what is set aside so far. "Use $X a month" sets it to what reaches the
  rest by January 15. Bold "Estimate; confirm with your CPA." on every card,
  the personal disclaimer in bold at the top.
- **For your CPA with both sides** (22, `apps/personal/cpa.py`,
  `/finance/export` with the module on, also a Personal tab). A year
  selector; the business worksheet as data (`finance.reports.worksheet`),
  shown on the page, in the PDF, and written as the same CSV as before
  (checked line for line against the old function on the demo for 2024–2026);
  then the personal worksheet by the six groups, every line listed with its
  date, item and account, figures the owner adds for the CPA
  (`PersonalTaxItem`: a non-cash donation, which must name its charity, or an
  amount from a form such as the lender's 1098), medical and charitable miles
  and the HSA as year-end facts; **standard against itemized** (23); the
  **Personal facts** (estimated payments by quarter with where each was paid
  from, health insurance premiums, retirement contributions by account, HSA,
  childcare and education), each with "Ask your CPA." **One PDF** with both
  sections (`/api/personal/cpa/pdf`); the range exports stay below.
- **Review with Claude** now also lists the envelopes (planned against the
  last three months), the goals and the set-aside, each with an id and the
  app's own figure (the recent median; the estimate's percent). Claude picks
  ids and says why; the owner presses "Set it a month" (editable) or "Use
  N%" through the ordinary routes; a goal links to Goals. Priced higher
  (6,500 in, 1,400 out). The pay category goes to Claude as "Pay from the
  practice" in every personal prompt: the practice's name can be the owner's.
- **The payoff orders by name** (U3): "Smallest balance first" and "Highest
  rate first" on the Debts page, in this spec, in its refusals and in what the
  review sends; the codes `snowball` and `avalanche` stay in the data.
- **The demo:** each month's pay in joint checking matched to its draw;
  "Pay from Summit Operations Partners"; John and Dana's inputs (married
  filing jointly, CO at 4.4%, last year $61,840 tax on $186,200 taxable,
  Dana's $72,000); this year's last two state estimated payments made from
  joint savings ($700 each, June and September), the rest from the practice;
  the $5,320 set aside (28% of the September 28 draw) as the Tax envelope's
  Left, the envelope at 28% of the average draw ($5,710 a month); the
  property tax ($2,140, June), the doctor's bills, the church giving, the
  mortgage interest from the lender's statement ($14,409) and a Goodwill
  donation ($340), 86 medical and 140 charitable miles.

**Models** (`personal 0005`, additive): `PersonalTaxYear`, `PersonalTaxItem`;
`PersonalLine.draw_entry`; the envelope source `tax` (no SQL). Both models in
the isolation family.

**Choices made in stop 4, for Bryan to keep or overrule:**

1. **Self-employment tax stops its Social Security part at the year's wage
   base** ($184,500 in 2026). Decision 21's "15.3% of 92.35%" as written would
   overstate the demo's by about $11,000; the Medicare 2.9% goes on above it.
   Not counted, and said under the figures: the 20% qualified business income
   deduction, the 0.9% additional Medicare tax, credits. QBI is the big one for
   most fractionals. **Added 2026-10-19 (Bryan):** a QBI choice on the
   Taxes page, off by default, "None" or "20% of net profit", with the note
   that consulting is a specified service whose deduction phases out above an
   income threshold; when on it lowers the federal income-tax part only
   (`personal 0006`, additive). All stop 4 choices kept (Bryan, 2026-10-19).
2. **The year's profit is the pace so far** (so far ÷ the share of the year
   gone by), not the so-far figure, so October does not under-estimate.
3. **The state rate applies to federal taxable income** (Colorado's base);
   the screen says so.
4. **The safe harbor's 110% test uses last year's taxable income** as a stand-in
   for AGI. Over $150,000 taxable is over it on AGI too; under it, the screen
   says 110% may still apply and to ask the CPA.
5. **What is set aside so far is the owner's figure**, with "N% of the draws
   since the last payment comes to $X" beside it as a check. The app cannot
   tell which move to savings was for tax.
6. **The Tax envelope's Left is what is set aside**, not its months added up,
   so it says one number, the Taxes page's.
7. **"Paid yourself" counts draws to your accounts plus personal spending on
   the practice's accounts** (both owner draws); estimated tax paid from the
   practice is named beside it, not in it.
8. **A goal's change from the review is a link to Goals**, not a one-press
   change: the goal route takes the whole goal, and a press with only part of
   it would reset what is saved.
9. **The demo shows John well behind on estimated tax** ($84,970 needed by
   January 15 on the estimate, $45,430 on the safe harbor), because the books'
   seed pays each quarter from one month's draw. That reads as the app catching
   it; the books' seed could pay three months' worth instead, which would move
   the $5,320.
10. **"Two estimated payments made this year"** is read as two on the personal
    side (June and September state, from joint savings), with the books' own
    federal ones and April's state one still from the practice: 2026 has three
    quarters paid, as the date says it should.

**Not built in stop 4:** state brackets (a flat rate only); payments made in a
later year for an earlier one beyond January; household sign-ins (a later
stop). The privacy policy and beta agreement amendments, the condition on
offering M4, followed on 10/20: the policy draft's "Personal finance"
paragraph and the beta agreement's v3, clause 8.
