# P6 M1 — Reconciliation and month close

**Spec · 2026-10-08 · decided 2026-10-08 · no code yet; stop 1 waits for the owner's word**

The first of four finance modules asked for by the owner on 2026-10-08:
M1 reconciliation and month close (this file), M2 cash forecast, M3 balance
sheet, M4 personal finance. Each gets its own spec, is built after approval,
gets demo data, and is released only on "release".

**Already decided (owner, 2026-10-08):**

- **Practice owner only.** An associate and an assistant have nothing here.
  `CLAUDE.md` and the matrix are unchanged.
- **A module a practice has or does not have.** M1 and M3 together are
  "Bookkeeping". Which practices have it is a switch on the platform's record
  of the practice; the price is P4's, which waits on the NMI sandbox (§7).
- **The starting chart is a common small-practice list written here** (§5.4).
  The owner will change his own to his CPA's list in the live app, with the
  add, remove and combine tools this module builds.
- **One line on every finance screen** (§6).
- AI calls costed and capped; migrations additive and shown first.

**Decided 2026-10-08: M1-1 to M1-16, all as recommended (§13), with these
specifics.**

- **M1-9:** production's lock date was read (read-only, 2026-10-09 UTC).
  **No practice in production has one.** Executives Now's finance settings
  have no date; Blue Sky has no finance settings yet. So "locked before month
  close began" will apply to nothing in production. The demo's typed lock
  (2025-12-31) is replaced by its seeded closes (§10).
- **M1-14:** the chart of §5.4 is a placeholder. **The owner's CPA's list is
  coming and replaces §5.4 before stop 1 is finished.** Stop 1 also builds a
  Categories action, **"Add the starting chart"**, for an existing practice
  (§5.4).
- **M1-15:** the disclaimer's exact words are the owner's (§6).
- **M1-16:** two stops.
- **Guided mode, one addition:** when a later statement shows a closed month
  was wrong, the fix is a correcting entry in the open month, not reopening,
  and the step says so (§1.5, §3.4, §4.2).
- **The "locked through" field leaves the finance settings** (§3.5).

---

## 0. What the app has today that this uses, and what changes

| Exists (P5, released) | In M1 |
|---|---|
| Accounts (bank, card, cash) with an opening balance and date | What a reconciliation is done against |
| Entries, with removal by reason and an audit trail | What is ticked as cleared |
| The bank import, which already knows the bank's own balance on its last line | Its lines arrive ticked (§1.4); its balance is offered as the statement balance |
| "Books are locked through" a date, typed by the owner in the finance settings | **Changes:** the date is set by closing a month and moved back by reopening one (§3.4) |
| Categories: one level, rename, reorder, archive, a CPA code | **Adds:** a second level, merge, split (§5) |
| Uncategorized entries counted beside the P&L; 1099 payees; invoice deposits matched by the import | Three of the four lines of the close checklist (§3.2) |
| `ai_call` with the cost of every Claude call; the monthly AI budget | "Explain this step" (§4.3) |

Nothing built in P5 is removed.

---

## 1. Reconciling an account

### 1.1 The idea, in the screen's own words

"Your bank's statement says what the bank thinks happened. Your books say
what you think happened. Reconciling is ticking off each line of the books
that the statement also shows, until the two agree to the cent."

### 1.2 The steps

1. **Choose an account and a month.**
2. **Enter the statement's ending date and ending balance.** For a card, the
   balance is what is owed.
3. **Tick each entry the statement shows.** The list is every entry in that
   account dated on or before the statement date that is not already cleared:
   this period's, and anything carried forward from earlier ones.
4. **The difference must be zero.** Shown at the top, always:

   > Statement balance − (starting balance + cleared money in − cleared money out) = difference

5. **Finish.** Only at a difference of exactly zero. The reconciliation is
   recorded with who finished it and when.

Entries left unticked are not wrong: a check not yet cashed, a charge not yet
posted. They **carry forward** and appear at the top of the next
reconciliation of that account, under "From earlier statements".

### 1.3 The starting balance

- **The first reconciliation of an account** starts from the account's
  opening balance on its opening date. If the owner begins reconciling later
  than that, the screen asks for the statement's own starting balance, and
  entries before that statement are marked "before reconciling began" and are
  never asked about (M1-3).
- **Every later one** starts from the previous statement's ending balance.
  It is not typed.

### 1.4 Help finding the difference

- **Lines brought in by the bank import arrive ticked.** They came from the
  bank, so the statement shows them. The owner can untick any (M1-4).
- **"Tick all through the statement date"** and "untick all".
- **When the difference is not zero**, the screen says which of four things
  it usually is, each checked by arithmetic, no AI:
  - an unticked entry of exactly that amount ("Tick this one?");
  - a ticked entry of exactly half that amount entered the wrong way round;
  - two digits swapped (the difference divides by 9);
  - something on the statement that is not in the books: "Add an entry", from
    here, without leaving the screen.
- **A transfer** is one entry in two accounts. It is ticked separately in
  each, when each statement shows it.
- **An invoice payment not yet placed in an account** cannot be ticked. It is
  listed under the bank account as "Received, not yet placed", with "Place it
  here".

### 1.5 After it is finished

- An entry cleared in a finished reconciliation keeps its **date, amount,
  account and direction**. Changing or removing one means reopening that
  reconciliation first, with a reason. Its category, description and payee
  can still change while its month is open.
- **Reopen a reconciliation:** practice owner, with a reason, audited. Only
  the newest finished one of an account, so the starting balances after it
  stay true.
- **A statement that does not end on the last day of a month** (most cards)
  belongs to the month its ending date falls in (M1-5).
- **When a later statement shows that a closed month was wrong** (a charge
  that posted for a different amount, a deposit the bank reversed), **the fix
  is a correcting entry dated in the open month,** saying what it corrects.
  The closed month, and anything already sent to the CPA from it, stays as it
  was. Reopening (§3.4) is for a month closed by mistake, not for this.

### 1.6 Cash accounts

A cash account has no statement. It is reconciled to a count the owner types
("Counted on"), or left out of the close altogether: the account has a
switch, "Reconciled each month", on for bank and card and off for cash (M1-6).

---

## 2. The reconcile screen

`/finance/reconcile`, a tab in Finance beside Entries.

- **A grid, accounts down and months across,** from the first month with
  entries. Each cell: not started · in progress (with its difference) ·
  reconciled (with the date) · not needed.
- **Open a cell** for the steps of §1.2. Money in and money out are two
  columns; ticked lines move to a "Cleared" list that can be opened.
- **A report for each finished one:** statement balance, cleared in and out,
  what is still outstanding, who and when. Printable. It is what a CPA asks
  for.

---

## 3. Closing a month

### 3.1 What closing is

**Closing a month locks the books through its last day.** Nothing dated on
or before it can be added, changed, removed, imported or rolled back, which
is what "locked through" already does. Recorded with who closed it and when.

### 3.2 The checklist, which ticks itself

| # | Line | Ticks itself when | Blocks the close |
|---|---|---|---|
| 1 | Every account reconciled | Each account set to "reconciled each month" has a finished reconciliation with a statement date in the month | **Yes** |
| 2 | Nothing uncategorized | No income or expense entry dated in the month is without a category | **Yes** |
| 3 | Invoice payments placed | No payment received in the month is still "not yet placed" in an account | **Yes** |
| 4 | 1099 payees named | No entry in the month sits in a category marked "paid to contractors" without a person named | No: a warning, and the close records that it was closed with it showing (M1-8) |

Each unticked line links to the list that would tick it.

### 3.3 Order

- **Months close in order.** March cannot close while February is open.
- The current month can be closed only after its last day.

### 3.4 Reopening

- **Practice owner, with a reason, audited.** The lock moves back to the end
  of the month before.
- **Reopening a month reopens every later closed month too,** and says so
  with their names before it does it. Their reconciliations stay finished.
- A month that has been closed, reopened and closed again shows all three,
  with who and why.
- **The reopen screen says first what it is not for:** "If a later statement
  showed a mistake in this month, add a correcting entry in the open month
  instead. Reopen only if the month should not have been closed."

### 3.5 The lock date that exists today

- **It stops being typed, and the field leaves the finance settings**
  (decided). The reconcile screen shows the date and which close set it.
- **A practice that has already typed one keeps it.** The months through
  that date are shown as "Locked before month close began": locked, not
  reconciled, and not counted as closed for M2's "two closed months". The
  owner can leave them, or reopen back through them and close them properly
  (M1-9).

---

## 4. Guided mode

### 4.1 What it is

A switch at the top of the reconcile and close screens, **"Walk me through
it"**. On for a practice owner until their first month is closed; theirs to
turn on or off after that. Remembered per person.

### 4.2 The steps

Plain numbered steps, one open at a time, each with two or three sentences
written here in the app, free, and always shown:

1. Get your statement. *(Where to find it, what "ending balance" means.)*
2. Type its ending date and ending balance.
3. Tick what the statement shows.
4. Look at what is left. *(Why an unticked line is usually fine.)*
5. Get the difference to zero. *(The four usual causes of §1.4.)*
6. Finish, and do the next account.
7. Check the list. *(The checklist of §3.2.)*
8. Close the month. *(What locking means. And: "If a later statement shows
   this month was wrong, do not reopen it. Add a correcting entry in the open
   month that says what it corrects. Your CPA will thank you.")*

### 4.3 "Explain this step"

- **Asks Claude only when pressed.** Nothing is sent by opening a step.
- **What is sent (M1-10):** which step; the account's kind; the statement
  date and balance; the starting balance; the totals cleared in and out; the
  difference; and, on steps 4 and 5 only, the unticked lines of that one
  account and period (date, amount, description). No other account, no
  client list, no one's contact details.
- **What comes back:** a short explanation in plain words, about these
  numbers. Shown under the step with the one-line disclaimer.
- **It changes nothing.** It cannot tick, add, categorize or close. It is
  told not to give tax advice and to say "ask your CPA" where the question is
  one.
- **Costed:** the button says about what it costs before it is pressed, and
  the answer says what it did cost. It is an `ai_call` like any other.
- **Capped:** 20 a day per practice, and never past the practice's monthly AI
  budget where one is set. At the cap the button says so and when it resets
  (M1-11).
- **Not kept:** the answer is not stored. The same step with the same numbers
  is answered once per session from the browser's own copy.
- With no Anthropic key the button says so, as every Claude button does.

---

## 5. Categories

### 5.1 Two levels

- A category may have **sub-categories**, one level down. "Travel" holds
  "Airfare", "Lodging", "Ground transport".
- A sub-category has its parent's type.
- **An entry may sit on either.** One on the parent is shown under it as
  "Travel, not broken down" (M1-12).
- The P&L shows each parent with its total and its sub-categories indented
  beneath, collapsible. The CPA export gains a "Parent category" column.
- A CPA code may be set on either level.

### 5.2 Merge ("combine")

- **A into B:** every entry, rule and import line that named A now names B.
  A is archived and remembers where it went.
- A and B must be the same type. A parent merges into a parent, taking its
  sub-categories with it; a sub-category into any category of its type.
- **The screen shows the count first:** "214 entries from January 2025 to
  today move from A to B. No total, balance or net changes."
- **Closed months are included (M1-13).** A merge changes no figure but the
  two categories' own; it is recorded against each closed month it touched,
  so "the March export differs from what was sent" has an answer.
- Not undone by a button. "Split" is the way back.

### 5.3 Split, add, remove

- **Split:** make one or more new categories (or sub-categories) from an
  existing one, then move entries to them: all those whose description or
  payee contains some text, or the ones ticked in the list. The same
  count-first screen. Closed months included, recorded the same way.
- **Add, rename, reorder, move** a sub-category to another parent.
- **Remove:** a category with no entries is deleted; one with entries is
  archived, as today.
- **A rule** may point at a sub-category.

### 5.4 The starting chart

**A placeholder (owner, 2026-10-08):** the owner's CPA's list replaces this
section before stop 1 is finished, and the build takes the chart from here.

For a new practice it is the chart it starts with. **An existing practice's
chart is not touched.** It gets a Categories action, **"Add the starting
chart"** (stop 1), so Executives Now and Blue Sky can pick it up:

- it adds every category and sub-category of the chart that the practice does
  not already have, matched by name and type without regard to case;
- **it never renames, moves, re-types, archives or removes anything already
  there,** and never moves an entry;
- a sub-category whose parent the practice already has is added under that
  parent; one the practice already has somewhere else is left where it is;
- it shows what it would add before it adds it, can be pressed again later
  (it then adds only what is new in the chart), and is audited.

**Income**

| Category | Sub-categories |
|---|---|
| Client fees | Retainers · Project fees · Workshops and speaking |
| Referral fees received | |
| Reimbursed expenses | |
| Interest income | |
| Other income | |

**Expenses**

| Category | Sub-categories |
|---|---|
| Contractors and associates *(paid to contractors)* | Associates · Assistants · Other contractors |
| Payroll | Wages · Payroll taxes · Benefits · Payroll service fees |
| Software and subscriptions | Software · AI and API usage |
| Marketing and advertising | Advertising · Website · Events and sponsorships |
| Travel | Airfare · Lodging · Ground transport |
| Meals | |
| Vehicle | Mileage and fuel · Parking and tolls |
| Professional services | Accounting · Legal · Coaching and consulting |
| Insurance | Business liability · Health |
| Office | Supplies · Equipment · Postage and printing |
| Rent and coworking | |
| Phone and internet | |
| Education and training | |
| Dues and memberships | |
| Bank and merchant fees | |
| Referral fees paid | |
| Taxes and licenses | |
| Interest paid | |
| Charitable giving | |
| Other expenses | |

**Owner:** Owner contribution · Owner draw (Draws · Estimated tax payments).
**Held:** Sales tax collected.

Above the list, on the categories screen:

> Ask your CPA what they want to see, then add, remove or combine. These are
> common names, not a recommendation.

---

## 6. The disclaimer

One constant, shown as the last line of every Finance screen and under every
"Explain this step" answer, and printed at the foot of the reconciliation
report:

> Bookkeeping and projections only, not tax, legal or financial advice. Confirm with your CPA.

A test walks every finance route and fails if a screen is without it.

---

## 7. The module switch

- **"Bookkeeping" is a module a practice has or does not have** (M1 and M3).
  M2 and M4 will each be one of their own.
- The switch is on the platform's record of the practice, set by the
  platform owner in the Practices area, audited. It is a fact about the
  practice, like its name; the platform owner still sees nothing inside.
- **A practice without it:** the routes answer 404 and the screens are not in
  the menu.
- **What it covers (M1-1):** reconciliation, month close, guided mode,
  sub-categories, merge and split now; the balance sheet in M3. **Everything
  P5 built stays with every practice** (entries, the import, the P&L, 1099,
  the export), so nobody loses a screen they have today.
- **Existing practices are switched on by the migration (M1-2).**
- No price here. P4 attaches one.

---

## 8. Who sees and does what

| # | Capability | Practice owner | Associate | Assistant | Client users | Platform owner |
|---|---|---|---|---|---|---|
| 13.11 | Reconcile an account; reopen a reconciliation | ✅ | ❌ | ❌ | — | ❌ |
| 13.12 | Close a month; reopen one | ✅ | ❌ | ❌ | — | ❌ |
| 13.13 | Sub-categories, merge, split | ✅ | ❌ | ❌ | — | ❌ |
| 13.14 | "Explain this step" | ✅ | ❌ | ❌ | — | ❌ |
| P.x | Switch a practice's modules | — | — | — | — | ✅ |

An associate and an assistant get 403; a client user and another practice
get 404. None of it is in search, the activity feed, a timeline or an email.

---

## 9. Data model

All additive. Every new table is practice-scoped and joins the isolation
registry.

| Table | Columns |
|---|---|
| `finance_reconciliation` *(new)* | `id`, `tenant_id`, `account_id`, `month` (its first day), `statement_on`, `statement_balance_cents`, `starting_balance_cents`, `state` (`open / finished`), `finished_by_id`, `finished_at`, `reopened_by_id`, `reopened_at`, `reopen_reason`. One per account and statement date. |
| `finance_cleared` *(new)* | `id`, `tenant_id`, `reconciliation_id`, `entry_id`, `account_id`. One per entry and account, so a transfer can be cleared once on each side. |
| `finance_month_close` *(new)* | `id`, `tenant_id`, `month`, `closed_by_id`, `closed_at`, `warnings` (what showed on the checklist), `reopened_by_id`, `reopened_at`, `reopen_reason`. A row per closing, kept when reopened. |
| `finance_category_change` *(new)* | `id`, `tenant_id`, `kind` (`merge / split`), `from_id`, `to_ids`, `entries_moved`, `first_on`, `last_on`, `by_id`, `at` |
| `finance_category` | **adds** `parent_id` (null), `merged_into_id` (null), `is_contractor` (bool) |
| `finance_account` | **adds** `reconciled_monthly` (bool), `reconciling_from` (date, null) |
| `practice_module` *(new, platform's)* | `tenant_id`, `module` (`bookkeeping / forecast / personal`), `enabled_at`, `enabled_by_id`, `disabled_at`. Not practice data: the platform's record. |

`finance_settings.locked_through` stays, written only by closing and
reopening.

**Migration:** one for `finance`, one for `platform`. SQL shown first; applied
on `execsnowhq_local` only until "release". The data step switches
Bookkeeping on for each existing practice, sets `reconciled_monthly`, and
marks the contractor category; its counts are shown before it runs.

---

## 10. Demo data

John Carter's practice, in `seed_demo`:

- **Bank and card reconciled for every month from January 2025 to September
  2026** (42 reconciliations), each made by the reconcile code with the
  clock moved, and **21 months closed** in order. The seed stops typing a
  lock date; the closes put it at 2026-09-30.
- **One correcting entry** in an open month for a mistake found in a closed
  one, so the rule of §1.5 has an example.
- **A few entries carried forward** each month: the owner's check to the
  Chamber clears the month after it is written.
- **October open:** the bank reconciliation in progress with a difference
  that is one unticked deposit, so guided mode and "what is the difference"
  have something to show. The card not started.
- **One month reopened and closed again** (a refund entered late), with its
  reason.
- **The chart with sub-categories,** and one merge and one split on record.
- The demo has no Anthropic key, so "Explain this step" says so there unless
  one is entered.

---

## 11. Tests

| Family | Tests |
|---|---|
| **Practice isolation** | The four new tables in the registry. Practice A never sees or reconciles B's accounts, by id or in a total. A's reconciliation cannot clear B's entry. The platform owner reaches none of it, and the module switch returns nothing from inside a practice. |
| **Role boundaries** | An assistant and an associate: 403 on every new route, "Explain this step" included. A client user: 404. A practice without the module: 404, and nothing in the menu. |
| Reconciling | The difference is the arithmetic of §1.2 for a bank and for a card. Finishing is refused at any difference but zero. Unticked entries carry forward and appear once. A transfer clears separately in each account. The second reconciliation starts from the first's ending balance. Imported lines arrive ticked. A cleared entry refuses a change of date, amount, account or removal. |
| Closing | Each checklist line ticks itself from the books and unticks when the books change. The three blocking lines block. Months close only in order. Closing locks; a locked month refuses everything P5's lock refuses. Reopening needs a reason, moves the lock back, reopens later months, and is audited. |
| The old lock | A practice with a typed lock keeps it; those months are locked, not "closed". |
| Categories | A sub-category has its parent's type; no third level. A merge moves every entry, rule and import line, changes no P&L total, and is recorded against each closed month. A split moves exactly the entries chosen. The P&L's parents are the sums of their children. |
| Explain | Nothing is sent until pressed. What is sent is the list of §4.3 and nothing else (asserted on the prompt). The cap refuses the 21st; the monthly budget refuses past it. It writes nothing but its `ai_call`. |
| Disclaimer | Every finance route renders the line. |

**Not verifiable without a browser:** ticking through a real statement with
a few hundred lines; the grid at two years wide; whether the guided steps
read clearly to someone who has never reconciled. **Not verifiable without a
key:** what Claude actually says, and whether it stays off tax advice.

---

## 12. Not in this module

Statement files attached to a reconciliation; reading a statement PDF;
automatic reconciliation from a bank feed; adjusting journal entries; accrual;
more than two category levels; a fiscal year that does not start in January;
loans and the balance sheet (M3); budgets (M4).

---

## As built: stop 1 (2026-10-08) — the switch, categories, the disclaimer

Built on `dev`; not released. Stop 2 (reconciliation, close, guided mode, the
demo's closes) is not started.

**The module switch.** `practice_module` (in `apps/tenancy`, the platform's
record) and `apps/tenancy/modules.py`. The Practices area has a "Bookkeeping"
tick per practice (`POST /api/platform/practices/<id>/modules`), audited in
the practice's own trail. `/api/me` names a practice's modules to its staff.
The migration switches it on for every practice that exists.

**Categories.** `apps/finance/chart.py`. Sub-categories (`parent`), moving one
under another or back to the top, the order within a parent, remove (unused
only), combine (`…/merge/`), split (`…/split/`), the list of what was combined
and split (`…/changes/`), and "Add the starting chart" (`…/starting-chart/`).
Combine and split take `preview: true` and then only count. The P&L, its CSV
and both CPA files show two levels; the entries file and the summary have a
"Parent category" column.

**Where the build differs from the text above, or adds to it:**

- **A split moves entries by the text they contain.** Moving the ones ticked
  in a list (§5.3) is in the API (`entries: [ids]`) and tested there; the
  screen offers text only. The entries list's own "Change the category" still
  moves ticked entries in open months, unrecorded as a split.
- **A split makes one new category at a time.** "One or more" is the same
  thing done again.
- **Names stay unique across the whole chart, not within a parent,** as they
  were before. "Other" under two parents is refused; the starting chart has no
  repeated name.
- **A category the practice archived counts as one it has** for "Add the
  starting chart": it is not brought back, and neither are sub-categories the
  chart would put under it. They are listed as left out, with why.
- **Combining a category that paid invoices go to** points paid invoices at
  the category it was combined into.
- **A parent is archived only once its sub-categories are; a sub-category is
  restored only once its parent is.**
- **A practice without the module still sees a two-level chart** if it has
  one (a new practice starts with §5.4). What it does not have are the tools
  that reshape it.
- **`finance_category_change` has one `to_category`,** not a list, since a
  split makes one at a time; and `contains`, the text a split chose by.
- **The "locked through" field is still in the finance settings.** It leaves
  with stop 2, when closing a month is what sets it.
- **The P&L opens the entries behind a figure:** a category's figure opens
  its own entries and its sub-categories' (`subs=1`); a sub-category's, or
  "not broken down", its own.

**Tests that were pinned to the old chart and changed with it:** the count
and names of the starting chart, the order call (now per level), the
archive-what-is-relied-on case (its sub-categories go first), and the CPA
summary's columns (`tests/test_finance_books.py`).

**Not seen in a browser:** every screen of this stop.

---

## 13. Decisions (all decided 2026-10-08, as recommended; specifics at the top)

| # | Question | Decided |
|---|---|---|
| **M1-1** | **What "Bookkeeping" covers.** | Reconciliation, close, guided mode, sub-categories, merge, split, and M3's balance sheet. Everything P5 built stays with every practice. |
| **M1-2** | **Existing practices** (Executives Now, Blue Sky, the demo). | Switched on by the migration. New practices are off until switched on. |
| M1-3 | Reconciling may begin at any month, not only an account's first. | Yes. It asks once for that statement's starting balance. Otherwise two years of statements stand between you and the first close. |
| M1-4 | Lines from the bank import arrive ticked. | Yes. They came from the bank. You still have to reach zero. |
| **M1-5** | **A statement ending mid-month counts for the month its ending date is in,** and that month can close with the days after it not yet reconciled. | Yes. Most cards end mid-month. If a later statement shows a mistake in a closed month, the fix is a correcting entry in the open month (§1.5). |
| M1-6 | Cash accounts are left out of the close unless switched in. | Yes. |
| **M1-7** | **Reopening a month reopens every later closed month.** | Yes. A changed March makes April's starting point untrue. It names them first. |
| **M1-8** | **The 1099 line warns and does not block.** | Yes. A payee can be named in January for the whole year; blocking every month's close on it would teach you to ignore the checklist. |
| **M1-9** | **A lock date you typed before this existed is kept,** shown as "locked before month close began", and those months do not count as closed for the forecast. | Yes. Read 2026-10-09 UTC: no practice in production has a lock date. |
| **M1-10** | **What "Explain this step" sends to Claude:** the step, the balances, the totals, the difference, and on two steps the unticked lines of that one account (date, amount, description). | Yes. Without the lines it can only repeat the written step. It is your key and your data; nothing about clients beyond what a bank line says. |
| M1-11 | The cap: 20 explanations a day per practice, and never past the monthly AI budget. | Yes. A press is a fraction of a cent to about two cents; 20 is far more than one close needs. |
| M1-12 | An entry may sit on a parent category or on a sub-category. | Yes. Forcing every entry down a level would make adding a sub-category break the books until hundreds of entries were moved. |
| **M1-13** | **Merge and split include closed months,** recorded against each one. | Yes. You will combine categories into your CPA's list once, across two years. No total changes. |
| M1-14 | The starting chart of §5.4, for new practices; existing ones get "Add the starting chart", which only adds. | §5.4 as the placeholder; the CPA's list replaces it before stop 1 is finished. The action is in stop 1. |
| M1-15 | The disclaimer's exact words, §6. | "Bookkeeping and projections only, not tax, legal or financial advice. Confirm with your CPA." |
| **M1-16** | **One stop or two.** | **Two:** first the module switch, categories (with "Add the starting chart") and the disclaimer; then reconciliation, close, guided mode and the demo data. |
