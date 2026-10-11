# P6 — the finance expansion: the owner's brief

**Given by the owner on 2026-10-08. Saved here verbatim on 2026-10-11, at
his instruction.** M1 and M2 were specced before this file existed; M3 and
M4 are specced from it. **Where the brief and a spec disagree, the brief
wins unless a recorded decision says otherwise** (owner, 2026-10-11). The
specs: `p6_m1_reconciliation_month_close.md`, `p6_m2_cash_forecast.md`,
`p6_m4_personal_finance.md` (a placeholder).

Nothing below the line is edited.

---

Finance expansion — four modules, spec first (one spec file per module with a decisions table), build after my approval, demo seed data for each, nothing released until I say. Each is a priced add-on module in the plans model: Bookkeeping, Cash forecast, Balance sheet is part of Bookkeeping, Personal finance. Every screen in all four carries a one-line disclaimer: bookkeeping and projections, not tax or financial advice; confirm with your CPA.

M1 — RECONCILIATION AND MONTH CLOSE (practice owner only)
- Statement-based: choose an account and a month, enter the statement ending balance and date, tick cleared entries, the difference must be zero to close; unticked items carry forward. Close the month = lock through that date, recorded with who and when; reopen needs a reason and is audited.
- Guided mode for first-timers: plain numbered steps on the screen, an "Explain this step" that asks Claude only when pressed (costed, capped), and a checklist that ticks itself (all accounts reconciled, uncategorized entries = 0, invoices matched, 1099 payees named).
- Categories: sub-categories (two levels), merge, split, archive; the starting chart becomes my CPA's list (I will supply it; keep a placeholder) with a note on the screen: ask your CPA what they want to see, then add, remove or combine.

M2 — CASH FORECAST (practice owner only; needs ≥2 closed months)
- Arithmetic on the books, never AI-invented numbers: expected inflows from recurring invoice schedules and open invoices, timed by each client's average days-to-pay; expected outflows from recurring expenses detected in closed months, planned owner draws, and one-off items the owner enters; opening position from reconciled balances.
- The AI's role is to propose and ask: it lists the recurring items it found with amounts and cadence for confirmation, flags items that look irregular, and asks for anything upcoming the books cannot know (a tax payment, a hire, a trip). Owner answers in a form; nothing enters the forecast unconfirmed. One costed call per refresh.
- Views: 30 / 90 / 180 days, weekly buckets, low-point and negative-balance warnings, a scenario toggle (remove a client, add a recurring cost, change a draw) that recomputes without saving. Assumptions listed beside the chart; refreshable any time.

M3 — BALANCE SHEET (part of Bookkeeping)
- New account kinds: loan / line of credit (balance, rate, payment schedule) and, on the personal side, property and investment/retirement (monthly updated balance only).
- Balance sheet at a date: assets (cash, receivables from open invoices, prepaid if entered), liabilities (cards, loans, tax held), equity (contributions − draws + retained earnings), with every figure opening its source. Monthly snapshots so it can be shown over time. No depreciation or fixed assets in this version.

M4 — PERSONAL FINANCE (the person's, not the practice's)
- Ownership: a personal ledger belongs to the user, lives in a separate "Personal" area reached from the switcher, is visible only to its members, is protected from the platform owner exactly as practice data is (extend the isolation family), and survives the user leaving any practice.
- Household: the owner may invite one or more household members (a spouse) by email; each invite carries a permission set — Personal only, Business (practice-owner-equivalent on this practice), or both. Household members sign in through the external Google client (flag the Testing-mode test-user step). Changes to membership are audited.
- Same engine as the business books: accounts (bank, card, cash, loan, mortgage with value and balance, car loan, investment, retirement, property), categories with a personal starting chart, entries, CSV import with mapping, rules, reconciliation and month close, budgets.
- Income sources beyond the practice: other income kinds (spouse's pay, side business, investment income) as categories and expected inflows.
- Cash flow, not P&L: monthly in/out by category, upcoming bills from liability schedules and recurring expenses, the same 30/90/180 forecast engine with planned owner draws from the business forecast arriving as personal inflows.
- Net worth: assets minus liabilities from account balances, monthly snapshot, a simple trend; property value vs mortgage balance shown as equity.
- Smart budget: the AI proposes a monthly budget from closed months (regular items at their typical amount, irregular ones annualized and spread), the owner edits and sets it, then budget vs actual by category each month with overage flags. Proposals only; nothing set without the owner.
- The split tool: import an account marked "mixed"; tag each line business or personal (rules remember payees); business lines post to the practice books, personal lines to the personal ledger, and the app writes the matching owner draw (personal spend from a business account) or owner contribution (business spend from a personal account) so both sets of books stay honest. A line can be split by amount. Each posting is reversible from the import.
- Connections: CSV now; design the account model so an aggregator (Plaid or similar) can attach later without rework; no aggregator in this round.

ALL FOUR: AI calls costed and under the daily cap; migrations additive and shown first; privacy policy and beta agreement amended for personal financial data before any beta user is offered M4; demo seed: John Carter's practice closes months Jan 2025–Sep 2026 with a forecast and balance sheet, and John has a personal ledger with a spouse member, a mortgage, a car loan, retirement and investment balances, a mixed card that was split, a budget, and a net-worth trend.
