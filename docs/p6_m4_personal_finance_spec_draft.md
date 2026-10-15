# Personal Finance (M4) Spec

Drafted 2026-10-15 by Claude (chat) with Bryan's decisions of 2026-10-15. Source: the Claude Doc "Personal Finance (M4) Spec".

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
6. **Sort these with Claude.** One button on To sort: priced first, costed after, proposes a category and side for every waiting line, the owner accepts all or edits. Accepted proposals become rules. Merchant names are sent (the button says so); amounts and names only, never account numbers. Counts against the monthly AI budget, not the daily Explain cap. *Recommended: yes.*
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
16. **Debts.** Name, kind (card, auto, mortgage, student, personal, medical, other), balance, rate, minimum payment, due day, whose. A credit card that is also an imported account takes its balance from the import; other debts take a balance entered monthly or from a statement. A payoff plan: **Snowball** (smallest balance first) or **Avalanche** (highest rate first), plus an extra monthly amount; shows each debt's payoff date, total interest, and what the other order would cost or save. The extra becomes an envelope; payments show on the forecast; each debt has a balance-over-time chart. *Recommended: yes, both orders offered, Snowball the default.*
17. **Retirement and investments.** Accounts with a balance history (entered monthly or from a statement; no live feeds), contributions recognized from transfers, a target (an amount by a year), and "on track / behind" from the contribution rate and an assumed yearly return the owner sets (default 6%), with the estimate disclaimer. A progress chart per account. *Recommended: yes, simple.*
18. **Household.** The owner plus the people they add (a spouse or partner). A person is a label, not a sign-in. Income, accounts, debts and retirement each carry *whose*: owner, spouse or joint. Views: the household, or one person. The spouse's expected W-2 withholding feeds the tax estimate. *Recommended: yes.*
19. **Net worth.** Assets (bank accounts, retirement and investments, plus items entered by hand such as a home or vehicle with a value and a date) minus debts, as one line over time on the Overview, with a home's value against its mortgage shown as equity. No valuations fetched. *Recommended: yes; it is almost free once 16 and 17 exist, and it is the number people check.*

## Decisions 20–23: paying yourself, quarterly taxes, For your CPA

20. **Paying yourself is one line on both sides.** A draw from the practice is an owner draw in the books (as now) and "Pay from <practice>" on the personal side, matched automatically when both accounts are imported (same amount, same or next day). The personal budget tells the business forecast what is needed: "Your envelopes need $X a month; you have paid yourself $Y on average." The owner can set the business forecast's pay-yourself line from it. *Recommended: yes. This is the loop that makes the two sides one system.*
21. **Quarterly tax set-aside, an estimate.** Inputs the owner enters once a year: filing status, state, last year's total tax and taxable income from the return (or just an effective rate), and the spouse's expected withholding. From business net profit year to date (the books) and the household's other income the app estimates self-employment tax (15.3% of 92.35% of net profit, with half deductible), federal income tax at the year's brackets, and state at a rate the owner enters. It shows: the amount per quarter with the IRS dates (Apr 15, Jun 15, Sep 15, Jan 15); the safe-harbor alternative (100% or 110% of last year's tax); a **set-aside percent per draw**; and a **Tax envelope** with saved-so-far against needed-by-next-date. Estimated payments already made (marked on the business side today, and now on the personal side too) reduce what is needed. The bracket table is data with a year on it; a missing year says so and uses the last one with a note. Every figure carries "estimate; confirm with your CPA". *Recommended: yes.*
22. **For your CPA shows both sides.** One page, a year selector, two sections. Business: the worksheet as built in M1. Personal: the CPA's Itemized Deduction Worksheet by its groups (medical and dental, health insurance, interest paid, property taxes, charitable contributions, non-cash donations by charity, as on the CPA's sheet; medical and charitable miles are year-end facts like M1's business miles, and a non-cash donation names its charity on the line), filled from personal lines whose category carries the Tax-deductible mark, every line listed; and a **Personal facts** block: estimated payments by quarter with dates, health insurance premiums paid as a self-employed person, retirement contributions by account, HSA, childcare and education, each with an "ask your CPA" note. One PDF with both sections; the business export alone stays as it is. *Recommended: yes.*
23. **Standard against itemized.** The personal section shows the itemized total next to the standard deduction for the filing status and year, so the owner sees whether itemizing is likely to matter. No advice beyond "ask your CPA". *Recommended: yes.*

## Decisions 24–27: privacy, AI, wording, module

24. **Privacy.** Personal data belongs to the owner. Associates, assistants, the platform's Practices page, digests, staff Activity and the business features' AI prompts never see it. It is in the same database and the same backups. The owner can delete the whole personal side in Settings, with a confirmation that names what goes. Account numbers are never stored, as in M1, and the isolation test family is extended to cover the personal side, as the brief asks. *Recommended: yes.*
25. **AI, priced first every time.** Three uses: Sort these with Claude (decision 6); Explain this budget and Explain this forecast (M2's pattern, low effort, the shared 20-a-day cap); Review with Claude, which proposes changes to envelopes, goals and the set-aside (M2's pattern). The practice's key and monthly budget. Merchant names go out for sorting and the button says so; amounts and category names for the rest; never account numbers, balances of retirement accounts, or the owner's name. *Recommended: yes.*
26. **Wording and disclaimers.** "Personal" in every page title on that side. Plain words on screen: envelope, goal, debt, set aside; never "sinking fund" or "zero-based". The Finance disclaimer gets a personal version on every personal screen, bold on the Taxes page: *"Budgeting, forecasting and tax estimates only, not tax, legal or financial advice. Confirm with your CPA."* *Recommended: yes.*
27. **Module and demo.** Personal finance is its own module switch per practice in the Practices area, off for existing practices, on for the demo. Priced as a module when pricing is set ($25 or $50 a month were the figures heard). The demo seed gives John Carter a personal side: two personal accounts and one mixed card, six months of lines, three goals, two debts, one retirement account, a spouse with pay, and a set-aside in progress. *Recommended: yes.*

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

The brief of 2026-10-11 wins where the two differ, unless a recorded decision says otherwise. The four open points were decided on 10/15; the rest are folded into the decisions above.

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

## Open questions

- The don't-ask threshold: $25, or another number?
- Rollover defaults: everyday envelopes reset, savings-type roll. Keep?
- Snowball as the default payoff order, with Avalanche a switch away?
- Assumed return for retirement projections: 6% default?
- Tax inputs: will owners enter last year's total tax and taxable income, or should the first version take only a percent?
- State tax as a flat rate the owner enters, or should the app know each state's brackets?
- Build order: 1, 2, 3, 4 as written, or taxes before the budget for the Jan 15 payment?
- A spouse for John Carter on the demo: name and job?
- Where M3 sits now that M4 is high on the list.
- Decided 10/15: where it lives (a toggle inside Finance), spouse sign-in (later), no month close, budget by arithmetic.
