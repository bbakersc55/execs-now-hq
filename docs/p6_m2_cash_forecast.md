# P6 M2 — Cash forecast

**Spec · 2026-10-10 · decided 2026-10-11 · stop 1 in build; stop 2 waits for the owner's word**

The second of the four finance modules asked for by the owner on 2026-10-08
(`docs/p6_m1_reconciliation_month_close.md`: M1 reconciliation and month
close, accepted on the demo 2026-10-10; M2 cash forecast, this file; M3
balance sheet; M4 personal finance). It gets its own spec, is built after
approval, gets demo data, and is released only on "release".

**Decided 2026-10-11: M2-1 to M2-18, all as recommended, with these changes
and additions** (each is written into its section below, and §12 says which):

- **M2-6, added:** a balance below zero is always marked, floor or no floor.
- **M2-12, changed:** "Explain" and "Review" may send **payee and category
  names for expenses, never client names**; clients appear as "Client A",
  "Client B". A finance setting, "Include client names in AI explanations",
  off by default, lifts that (§6).
- **M2-15, changed:** quarterly and annual cadences are added to monthly
  (§2.2). An annual item is shown as "likely annual, confirm" and enters the
  forecast only when the owner confirms it, as a planned line.
- **M2-17:** two stops as proposed, with **"Review with Claude" in stop 2**.
- **Added, from the brief: "Review with Claude"** (§6a), stop 2.

**The brief.** This spec was first written without the owner's brief in
front of me; it is saved now, verbatim, as
`docs/p6_finance_expansion_brief.md`. **Where the brief and a spec disagree,
the brief wins unless a recorded decision says otherwise** (owner,
2026-10-11). §12a sets the brief's M2 beside this spec, line by line, and
says which holds.

---

## 0. What the app has today that this uses

| Exists | In M2 |
|---|---|
| Accounts with balances from the books; reconciliations (M1) | Where the forecast starts: the cash the practice has today |
| Closed months (M1) | What "history" means: only closed months are trusted to forecast from |
| Invoices sent and unpaid, with due dates; each client's payment history (P4A) | Money expected in, and when each client actually pays |
| Recurring invoice schedules (P4A) | Money that will be invoiced in the months ahead |
| Entries by category and payee, two levels (P5, M1) | The practice's regular costs, found in its own history |
| Transfers to a card; the card's reconciled statement balance (M1) | The card payment that will leave the bank |
| The "Estimated tax payment" mark on an owner draw (M1 §5.5) | The four dates a year the owner pays tax, and about how much |
| `ai_call`, the monthly AI budget, M1's "Explain this step" | "Explain this forecast" (§6) |
| The module switch (M1 §7) | `forecast`, a second module |

Nothing built in P5 or M1 is changed. The forecast **reads** the books and
the invoices; it writes only its own tables (§9).

---

## 1. What the forecast is

### 1.1 In the screen's own words

"This is how much cash your practice is likely to have in the bank, week by
week, if clients pay as they have been paying and your costs go on as they
have been going. It is arithmetic on your own books, not a prediction. You
can see every line it is made of, and change any of them."

### 1.2 What it shows

- **Cash, week by week,** over 30, 90 or 180 days (the brief's three views;
  90 days is the 13 weeks of M2-1 and is what opens), and month by month for
  12 months (M2-1). One row a week: cash at the start, money in, money out,
  cash at the end.
- **The low point:** the week the cash is lowest, how low, and how long from
  today.
- **The floor:** an amount the owner sets ("I want at least this much in the
  bank"). The first week the forecast goes under it is marked, with what is
  due that week (M2-6).
- **Below zero is always marked,** floor or no floor (M2-6, added
  2026-10-11): the first week the forecast ends under nothing, in words at
  the top and on the row.
- **Every figure opens the lines it is made of** (§2): which invoices, which
  costs, each with where it came from.

### 1.3 Where it starts

**Cash today** is the books' balance of every bank and cash account that is
open, as the balance view has it. A card is not cash: what is owed on it
leaves the bank on the day the card is paid (§2.3).

The screen says how fresh that is: "Checking is reconciled through September
30 and has entries through October 9." If an account has no entry in the
last 14 days, it says so: a forecast that starts from a stale balance is
wrong from its first row (M2-2).

### 1.4 Cash basis, as the books are

A sale is cash when the client pays, not when the invoice is sent. An
expense is cash when it leaves the account. A transfer between the
practice's own bank accounts is not a movement of cash; a card payment is.
Owner draws and estimated tax are cash going out, though they are not
expenses.

---

## 2. What it is made of

Three kinds of line. Each is labelled with which kind it is, wherever it is
shown.

### 2.1 Known: already in the app, with a date

| Line | From | When it lands |
|---|---|---|
| An invoice sent and not paid (or part paid: what is left) | P4A | Its due date, moved by how that client pays (below) |
| An invoice a recurring schedule will write | P4A schedules, active, to each one's end date | The schedule's day, plus the practice's terms, moved the same way |
| A draft or a ready invoice not yet sent | P4A | As if sent today (M2-3) |

**How a client pays.** For each client company with at least three paid
invoices: the median number of days between an invoice's due date and its
last payment, over the last 12 months. A client who pays 9 days late is
forecast 9 days late; one who pays early is forecast on the due date, not
before it. A client with fewer than three paid invoices is forecast on the
due date. The line says which: "Acme: usually 9 days after the due date."
(M2-4)

**An invoice more than 60 days overdue is left out of the forecast** and
listed beside it as "overdue, not counted": hoping is not forecasting. The
owner can put one back with a date (M2-5).

### 2.2 Regular: found in the practice's own closed months

A cost (or any money in that is not an invoice) is **regular** when the
closed months show it in the same category **and** from the same payee (or
with the same description when there is no payee), at one of three cadences
(M2-15, as changed 2026-10-11):

| Cadence | Found when | What is forecast |
|---|---|---|
| **Monthly** | It is in at least two of the last three closed months | The same amount each month where it has been the same (rent, software, insurance); where it varies (contractors, travel, advertising), the median of the months it appeared in. On the day of the month it usually falls |
| **Quarterly** | It is at roughly three-month spacing (two to four months apart) at least twice in the last 12 closed months, and is not monthly | The last amount, three months after the last one, and each three months after |
| **Quarterly, by definition** | An owner draw carrying the "Estimated tax payment" mark, Federal or State, in the last 12 closed months | The last amount of each mark, on the next of the IRS dates: January 15, April 15, June 15, September 15 |
| **Annual** | It is seen once, 11 to 13 months ago, and not since | **Nothing, until the owner confirms it.** It is listed as "likely annual, confirm"; confirming makes it a planned line (§2.4), with last year's amount and date to start from |

Owner draws are regular lines like any other (M2-7): the median of the months
they appeared in, on the usual day.

- **This is why it needs two closed months.** With fewer, the forecast shows
  only the known lines of §2.1 and says so at the top: "Close two months and
  your regular costs will be forecast from them. Until then this is only
  your invoices." Months "locked before month close began" do not count.
- **Only closed months are read.** An open month is still being entered and
  would understate every cost.
- **Each regular line says what it was found from, and its cadence:**
  "Larimer Square Cowork, $695.00 on the 1st, monthly: in each of the last 3
  closed months."
- **Stop 1 lists the "likely annual" items and does not yet confirm them:**
  confirming makes a planned line, and planned lines are stop 2's.
- **Nothing found is hidden and nothing is assumed silently.** The list of
  regular lines is on the screen, and each can be changed, paused or removed
  (§3).
- A regular cost that has **already been entered this month** is not forecast
  again for this month.
- Contractors paid a share of fees (the demo's associates) are found as "a
  different amount each month", not as a percentage of invoices. Tying a
  cost to the income that causes it is not in this module (§11).

### 2.3 The card

What is owed on a card today leaves the bank on the day the card is usually
paid (the day of the month of the transfers to it in the closed months).
After that, card spending is its regular lines (§2.2), paid the month after
they are charged. A practice that pays its card in full each month sees one
payment a month; one that carries a balance sees the payments it has
actually been making (M2-8).

### 2.4 Planned: typed by the owner

Things the books cannot know: a hire in January, a client who has said they
are leaving, new equipment, a deposit on a project.

- **A planned line** has a description, an amount, in or out, a date, and
  optionally "every month until". It is in the forecast until it is removed
  or its date passes.
- **A planned line does not become an entry.** When the real thing happens,
  it is entered or imported as always, and the planned line is ticked "this
  happened" (or expires a week after its date, and is listed as "did not
  happen?").
- **"What if":** any line of the forecast, of any kind, can be switched off
  for a look ("what if Globex does not renew"), and a planned line can be
  marked "what if" so it is drawn but not counted until switched on. The
  screen always shows the forecast **as it stands** and, when anything is
  switched, the **what-if** beside it, with the difference at the low point.
  A what-if is not saved unless the owner saves it as planned (M2-9).

---

## 3. Changing a line

The forecast is the owner's to correct. For any regular line:

- **Change the amount or the day** from here on ("rent goes to $750 in
  January"). The change has a start date and is kept.
- **Pause it** until a date, or **end it** ("I cancelled that").
- **"This is not regular"**: it is not forecast again unless it recurs anew.

Each is kept as the owner's own adjustment, shown beside the line with when
it was made, and can be undone. An adjustment outlives the next month's
close: the forecast finds the cost again and applies what the owner said.

For a known line: **move an invoice's expected date** ("she told me the
15th"), or leave it out.

---

## 4. How good it has been

A forecast nobody checks is decoration.

- **When a month is closed, the forecast as it stood on the first day of
  that month is kept,** and set beside what happened: cash at the end
  forecast and actual, money in and out forecast and actual, and the three
  largest differences by line ("Travel: forecast $900, was $2,340").
- The screen shows the last six closed months this way, in one table.
- It does not grade itself or produce an accuracy score: the differences
  are the information (M2-10).

---

## 5. The screen

`/finance/forecast`, a tab in Finance after Reconcile, for a practice with
the Forecast module.

- **At the top:** cash today, the low point, and the floor, in one line.
- **A chart of the cash line** for 13 weeks, with the floor drawn across it
  and the what-if line beside it when there is one. Under it, the same as a
  table, so nothing is only in a picture.
- **Weeks or months,** a switch.
- **Three lists under it,** each collapsible: Known, Regular, Planned. A row
  opens to its source (the invoice; the entries it was found from).
- **"How good it has been"** (§4), last.
- **For your CPA or your bank:** a CSV of the weekly table and the lines
  behind it. Each download is recorded.
- The dashboard's "Practice finances" slot, for the practice owner only,
  gains one line: "Lowest cash in the next 13 weeks: $X, the week of …"
  (M2-11).

---

## 6. "Explain this forecast"

As M1's "Explain this step": written help is free and always there; Claude
is asked only when a button is pressed.

- **What is sent (M2-12, as changed 2026-10-11):** the weekly table (cash,
  in, out); the floor; the low point; the regular and planned lines with
  their **category and payee names, for expenses**; and the known lines by
  amount and date. **Never a client's name:** a client appears as "Client A",
  "Client B", the same letter for the same client throughout one call. No
  invoice number and no one's contact details.
- **"Include client names in AI explanations"** is a finance setting, off by
  default. On, clients are sent by name. It is the practice owner's, audited
  when changed, and the button says which way it is set before it is pressed.
- An income line that is not an invoice (a referral fee received) is treated
  as a client's: its payer is lettered too.
- **What comes back:** a short reading in plain words: where the low point
  comes from, which few lines move it most, and what would change it.
- **It changes nothing,** gives no tax, legal or financial advice, and says
  "ask your CPA" where the question is one. It is told not to recommend
  borrowing, investing or cutting anyone.
- **Costed and capped** as M1's: the price before, the cost after, an
  `ai_call` like any other, 20 a day per practice across both buttons, and
  never past the monthly AI budget where one is set.
- **Not kept.** With no key the button says so.

---

## 6a. "Review with Claude" (from the brief; stop 2)

The brief: "The AI's role is to propose and ask." The numbers are arithmetic
on the books; Claude never supplies one.

- **One costed call, pressed only,** priced before and costed after, an
  `ai_call` like any other, under the same cap as "Explain" (20 a day per
  practice across the two) and never past the monthly AI budget where one is
  set. With no key the button says so.
- **What it reads:** the regular lines as found (category, payee, cadence,
  amount, day), and the last 12 closed months by category and payee, month by
  month. Under the names rule of §6: expense payees and categories by name,
  clients by letter unless the setting is on.
- **What comes back, three lists:**
  1. **Regular lines that look like one-offs** ("the $1,850 to Ledger & Quill
     in March looks like a once-a-year tax return, not a monthly cost").
  2. **Items that look recurring and were not picked up** ("LinkedIn appears
     in 9 of 12 months under two descriptions").
  3. **Questions about what the books cannot know:** a client ending, a hire,
     equipment, a tax payment, a trip.
- **The owner answers in a form.** Each item has its own answer: for list 1,
  "it is a one-off" or "it is regular"; for list 2, "add it" with an amount
  and cadence, or "no"; for list 3, a date and an amount, or "nothing
  planned".
- **Each answer becomes an adjustment or a planned line only when the owner
  confirms it.** Nothing Claude returns enters the forecast unconfirmed, and
  an amount in the forecast is always one the owner typed or the books
  produced, never one Claude wrote. Closing the form without confirming
  changes nothing.
- **The answers are kept; the review is not.** What was confirmed is an
  adjustment or a planned line like any other, marked "from a review". The
  lists themselves are not stored: pressed again, it is a new call.
- It gives no tax, legal or financial advice and says "ask your CPA" where
  the question is one.

---

## 7. The module switch

- **"Forecast" is its own module** (`forecast`), beside Bookkeeping, switched
  by the platform owner in the Practices area, audited. A practice without it
  gets 404 from its routes and does not see the tab.
- **It needs Bookkeeping,** because it reads closed months. Switching
  Forecast on for a practice without Bookkeeping is refused, with why (M2-13).
- **Existing practices** (Executives Now, Blue Sky, the demo): off until
  switched on, since it is new and priced separately (M2-14).
- No price here. P4 attaches one.

---

## 8. Who sees and does what

| # | Capability | Practice owner | Associate | Assistant | Client users | Platform owner |
|---|---|---|---|---|---|---|
| 13.18 | See the cash forecast and its lines; download it | ✅ | ❌ | ❌ | — | ❌ |
| 13.19 | Planned lines, what-ifs, adjustments, the floor | ✅ | ❌ | ❌ | — | ❌ |
| 13.20 | "Explain this forecast" | ✅ | ❌ | ❌ | — | ❌ |
| P.x | Switch the Forecast module | — | — | — | — | ✅ |

An associate and an assistant get 403; a client user and another practice
get 404. None of it is in search, the activity feed, a timeline, a digest or
any email. The dashboard line is in the practice owner's payload only.

---

## 9. Data model

All additive. Every new table is practice-scoped and joins the isolation
registry.

| Table | Columns |
|---|---|
| `finance_forecast_settings` *(new)* | `id`, `tenant_id` (one per practice), `floor_cents` (null), `updated_by_id` |
| `finance_forecast_planned` *(new)* | `id`, `tenant_id`, `description`, `direction` (`in / out`), `amount_cents`, `on_date`, `monthly_until` (null), `is_what_if` (bool), `happened_at` (null), `removed_at` (null), `created_by_id` |
| `finance_forecast_adjustment` *(new)* | `id`, `tenant_id`, `line_key` (what identifies a regular line: category, payee or description, account), `kind` (`amount / day / pause / end / not_regular`), `amount_cents` (null), `day_of_month` (null), `from_date`, `until_date` (null), `undone_at` (null), `by_id`. Also `invoice_id` (null) and `expected_on` (null) for a known line whose date was moved |
| `finance_forecast_snapshot` *(new)* | `id`, `tenant_id`, `month` (the month it forecast), `taken_on`, `weeks` (JSON: the table as it stood), `lines` (JSON: each line, its kind and amount), `actual` (JSON, filled when the month is closed). One per practice and month |
| `practice_module` | no change: `forecast` is already one of its values |

**Nothing is stored for a regular line itself.** It is worked out from the
closed months each time, so it can never disagree with the books; only the
owner's adjustments to it are kept.

**Migration:** one, for `finance`. SQL shown first; applied on
`execsnowhq_local` only until "release". No data step.

---

## 10. Demo data

John Carter's practice, in `seed_demo` (it has 21 closed months, so every
kind of regular line is found):

- **The module switched on.**
- **A floor of $15,000,** and a forecast whose low point comes within a few
  thousand of it in the week the card and the associates are both paid, so
  the mark and the warning have something to show.
- **Two overdue invoices** (Globex, Dunder Mifflin) forecast late by those
  clients' own habit, and one old enough to be "overdue, not counted".
- **Planned lines:** a hire in two months (a monthly cost until further
  notice), new laptops next month, and one what-if: "Globex does not renew".
- **Two adjustments:** the coworking rent going up from a date, and one cost
  marked "this is not regular".
- **Six months of "how good it has been",** with differences that look like
  a real practice's: travel over, a client paying later than usual.
- With the demo's key kept across reseeds, "Explain this forecast" works
  there; the console's own limit is its guard (M1 §12).

---

## 11. Not in this module

A forecast of profit (this is cash); budgets and budget-against-actual (M4
has budgets for a household; a practice's are not asked for); tying a cost
to the income that causes it (an associate's share of a client's fee);
loans, lines of credit and their repayment schedules (M3 has loans);
seasonality beyond "quarterly" and "yearly"; probability-weighted or
best-and-worst-case ranges; forecasting the sales pipeline (prospects are
not money); bank feeds; any change to what the books or invoices hold.

---

## 12. Decisions (decided 2026-10-11: all as recommended, with the changes marked)

| # | Question | Decided |
|---|---|---|
| **M2-1** | **How far ahead, and in what steps.** | 13 weeks by week, and 12 months by month. Thirteen weeks is a quarter, the span where the known lines are most of the answer; past that it is mostly "regular" and the months view says so. |
| M2-2 | The forecast starts from the books' cash today, and warns when an account has no entry in 14 days. | Yes. It does not require the current month to be reconciled: that would make it useless for the first three weeks of every month. |
| M2-3 | A draft or ready invoice not yet sent counts as if sent today. | Yes, labelled "not sent yet". Otherwise the first of the month's retainers vanish from the forecast between being written and being sent. |
| **M2-4** | **A client is forecast to pay as they have paid:** the median days after the due date over their last 12 months, never earlier than the due date, and only with three paid invoices to go on. | Yes. It is the single thing that makes this better than adding up due dates, and it is that client's own record, shown on the line. |
| **M2-5** | **An invoice more than 60 days overdue is left out,** listed beside the forecast, and can be put back with a date. | Yes. The alternative is a forecast propped up by money that may never come. |
| **M2-6** | **The floor** is one amount the owner sets; the forecast marks the first week under it. | Yes, and empty until set: the app should not invent how much cash you want. **Added 2026-10-11: a balance below zero is always marked, floor or no floor.** |
| M2-7 | Owner draws are forecast from the last three closed months, like any regular line. | Yes, and it is the line you will most often change. Leaving draws out would show cash piling up that you know you will take. |
| M2-8 | The card: what is owed today leaves the bank on the usual payment day; after that, card spending is paid the month after it is charged. | Yes. It matches a card paid in full. A practice carrying a balance is forecast from the payments it has actually made. |
| **M2-9** | **What-ifs are a look, not a saved scenario.** One forecast as it stands, one what-if beside it. | Yes. Named, saved scenarios are a second product; one what-if answers "can I afford this" and "what if they leave". |
| M2-10 | "How good it has been" shows differences, with no accuracy score. | Yes. A score invites trusting the number; the three biggest differences tell you what to fix. |
| M2-11 | One line on the practice owner's dashboard: the lowest cash in the next 13 weeks and when. | Yes, and only when the module is on and two months are closed. |
| **M2-12** | **What "Explain this forecast" sends to Claude.** | **Changed 2026-10-11:** "Explain" and "Review" may send payee and category names for expenses, never client names; clients appear as "Client A", "Client B". A finance setting, "Include client names in AI explanations", off by default, lifts that. (Recommended was no names at all.) |
| M2-13 | Forecast needs Bookkeeping, and switching it on without is refused. | Yes. It reads closed months, which only Bookkeeping makes. |
| **M2-14** | **Existing practices start with Forecast off.** | Off, unlike Bookkeeping, which was switched on for them. It is new and separately priced; you switch it on for Executives Now when you want it. The demo's seed switches it on. |
| **M2-15** | **What "regular" means.** | **Changed 2026-10-11:** two of the last three closed months stays, for monthly. Added: **quarterly** (the same category and payee at roughly three-month spacing at least twice in the last 12 closed months; marked estimated-tax payments are quarterly by definition, on the IRS dates) and **annual** (seen once 11 to 13 months ago and not since: shown as "likely annual, confirm", entering the forecast only when confirmed, as a planned line). |
| M2-16 | A regular line is worked out each time and never stored; only your adjustments are. | Yes. A stored forecast drifts from the books; this cannot. |
| **M2-17** | **One stop or two.** | **Two:** first the forecast from known and regular lines, the floor, the screen and the module switch; then planned lines, what-ifs, adjustments, "how good it has been", "Explain this forecast", **"Review with Claude" (added 2026-10-11, §6a)** and the demo data. |
| M2-18 | The disclaimer, on every screen and under every explanation, and at the foot of the download. | As M1 §6, the same sentence. |

### 12a. The brief's M2, beside this spec

The brief was saved after this spec was written and decided. Where they
differ, a recorded decision holds; where no decision speaks, the brief does.

| The brief says | This spec | Which holds |
|---|---|---|
| "needs ≥2 closed months" | The same; with fewer, it shows invoices only and says so (§2.2) | Agree |
| "Arithmetic on the books, never AI-invented numbers" | The same (§1.1, §6a) | Agree |
| Inflows "timed by each client's **average** days-to-pay" | The **median** days after the due date, never earlier than due, with three paid invoices to go on (M2-4) | The decision, M2-4. A median is not moved by the one invoice paid four months late |
| "opening position from **reconciled** balances" | The books' cash **today**, saying how far each account is reconciled and warning when one is stale (M2-2) | The decision, M2-2. The screen shows the reconciled-through date beside the figure, so the brief's point is on the screen |
| "planned owner draws" | Draws found as a regular line (M2-7), and changed by an adjustment (stop 2) | Agree: found in stop 1, planned in stop 2 |
| "one-off items the owner enters" | Planned lines (§2.4), stop 2 | Agree |
| "The AI's role is to propose and ask … Owner answers in a form; nothing enters the forecast unconfirmed. One costed call per refresh." | Was missing. **Added 2026-10-11 as "Review with Claude" (§6a), stop 2.** It is one call each time it is pressed; the forecast itself refreshes without any call | The brief, as the owner restated it |
| "Views: 30 / 90 / 180 days, weekly buckets" | M2-1 decided 13 weeks by week and 12 months by month | **Both, decided 2026-10-11:** the weekly view has 30, 90 and 180 days (90 is the 13 weeks, and is what opens), and the monthly view is M2-1's 12 months. Both stay |
| "low-point and negative-balance warnings" | The low point (§1.2); below zero always marked (M2-6, added) | Agree |
| "a scenario toggle (remove a client, add a recurring cost, change a draw) that recomputes without saving" | The what-if (§2.4, M2-9), stop 2 | Agree |
| "Assumptions listed beside the chart; refreshable any time" | The three lists under the chart, each line saying what it was found from; worked out from the books every time the screen is opened (M2-16) | Agree |
| "AI calls costed and under the daily cap" | 20 a day per practice across "Explain" and "Review", and never past the monthly budget (§6, §6a). **The practice's daily cap (`ai_unattended_daily_cap_usd`) counts only what the worker does with nobody asking, and both of these are pressed by a person**, so that cap does not count them; the 20 a day is theirs | **The spec, decided 2026-10-11:** pressed calls get the 20 a day; the worker's cap stays for unattended spend; the hard stop ("monthly AI budget can be set to stop, not warn", M1 §12) stays on the later list |
| "Each is a priced add-on module … Cash forecast" | The `forecast` module (§7), off for existing practices (M2-14), needing Bookkeeping (M2-13) | Agree |
| The disclaimer on every screen | M2-18 | Agree |
| Demo: "John Carter's practice … with a forecast" | §10, in stop 2 (M2-17) | Agree |

---

## As built: stop 1 (2026-10-11) — the forecast, the floor, the screen, the switch

Built on `dev`; not released. Stop 2 (planned lines, what-ifs, adjustments,
"how good it has been", "Explain this forecast", "Review with Claude", the
finance setting for client names, and the demo data) is not started.

**The forecast.** `apps/finance/forecast.py`. `build(tenant)` works the whole
thing out from the books each time: cash today; known lines (invoices sent,
unsent, and each schedule's to come, each on the day that client usually
pays); regular lines at each cadence; the card's payments; 26 weeks and 12
months of rows; and the low point, the first row under the floor and the
first under zero for each of the four views. It asks Claude nothing.

**Routes.** `GET /api/finance-forecast/`, `POST …/floor/`, `GET …/export/`
(a CSV, each download an audit event). 404 for a practice without the module.

**The screen.** Finance → Forecast (`frontend/src/screens/FinanceForecast.tsx`),
after Reconcile: three figures; where cash today comes from, with how far
each account is reconciled and a warning when one is stale; a chart of the
cash line with zero and the floor drawn on it, and the same figures as a
table; 30, 90 and 180 days and 12 months; each row opening its lines; Known
and Regular lists, each line saying where it comes from; "Overdue, not
counted"; "Likely annual, to confirm". One line on the practice owner's
dashboard.

**The module.** `forecast`, named "Cash forecast" (the brief's name for it).
The Practices area shows its tick beside Bookkeeping. Switching it on without
Bookkeeping is refused, and so is switching Bookkeeping off while it is on.
No practice is switched on by the migration.

**Migration:** `finance` 0009, one new table, `finance_forecast_settings`
(the floor). No data step. The other three tables of §9 are stop 2's.

**Where the build differs from the text above, or adds to it:**

- **Cash today includes invoice payments received and not yet placed in an
  account,** as the balance view's cash does, and lists them as their own row.
- **A row is seven days from today,** not a calendar week: "the week of
  October 11" starts on the day the forecast is opened.
- **"30 days" is five weeks** (35 days), so that it is whole rows.
- **The months view's first row is the rest of this month,** from today.
- **A monthly cost not yet entered this month, whose usual day has passed,**
  is forecast for today: it is still expected. One already entered for the
  month is not forecast again for it (§2.2).
- **A varying monthly cost is the median of the months it appeared in** among
  the last three closed months (two or three figures).
- **"The same payee"** is the person named on the entry; else the payee as
  typed; else its description, with the numbers a bank adds taken out, so
  "GUSTO FEE 677210" and "GUSTO FEE 677211" are one line.
- **"Roughly three-month spacing"** is two to four months between every pair
  of occurrences in the last 12 closed months, with at least two occurrences.
- **A marked estimated tax payment already made within a fortnight of a due
  date** is not forecast again for that date.
- **A card with no payment to it in the closed months** is forecast to be
  paid in 30 days, and says so.
- **Card charges are regular lines marked "on a card" and are not in the
  cash line;** the card's payment is. The second payment covers the charges
  forecast up to the first, and so on.
- **A transfer between the practice's own accounts is never a regular line.**
- **Money in that is not an invoice** (a referral fee received) is found as a
  regular line like a cost. Money the owner puts in is not: it is not regular.
- **"Likely annual" is listed and cannot yet be confirmed** (decided; §2.2).
- **The download is 180 days by week** with every line behind it; it has no
  months table.
- **The dashboard line works the whole forecast out** each time the practice
  owner's dashboard loads. Timed on the demo's books on Railway, 2026-10-11
  (924 entries, 21 closed months, 532 forecast lines): the Forecast tab's
  build took a median of 110 ms in 24 queries, the dashboard line 88 ms.
  Both are under the half second the owner set, so **no cache was added.**
  It has not been timed on a real practice's books.

**Not seen in a browser:** the screen, the chart and the dashboard line.
**Not run on real books:** whether these rules find a real practice's regular
costs without finding its one-offs. The demo cannot be looked at yet either:
its seed switches the module on in stop 2, so until then the platform owner
switches it on there by hand.

---

## As built: stop 2 (2026-10-11) — planned, what-if, changes, how good, the two buttons, the demo

Built on `dev`; not committed, not released.

**Planned lines and what-ifs (§2.4).** A description, in or out, an amount, a
date, once or monthly or quarterly, and an end date or none. A planned line
is counted from its date; a what-if is drawn and not counted. "Try it" works
the forecast out a second time with what-ifs switched on and any lines
switched off, and draws it beside the first as a dashed line with its own
low point: it saves nothing, and the forecast as it stands is the same
before and after. A planned line is ended by "It happened" (the real thing
is in the books now) or "Remove". A one-off whose date has passed without
either is shown as lapsed and is no longer counted.

**Changing a line (§3).** On a regular line: a new amount from a date, a new
day of the month, a pause between two dates, an end date, or "this is not
regular". On an invoice: the date it is expected, or leave it out. On an
estimated tax line: amount, pause, end, not regular. Each is one row that can
be undone, and the line says what was changed and by whom. Every one of
these, and each planned line, is an audit event.

**How good it has been (§4).** The last six closed months: what the forecast
said for the month, what happened, and the three largest differences by
name. No score (M2-10).

**"Explain this forecast" (§6) and "Review with Claude" (§6a).**
`apps/finance/forecast_ai.py`. Each asks only when pressed and shows about
what a press costs first. Explain returns words. Review returns up to a few
proposals and questions, each naming a line by an id this app gave it; the
amount shown beside each is the books' own, and nothing enters the forecast
until the owner confirms it, through the same routes as doing it by hand.
An id Claude returns that was not sent is dropped.

**The setting.** "Include client names in AI explanations", on the Forecast
tab, off by default, audited. Off, a client is "Client A", "Client B", the
same letter throughout one call.

**Routes,** all under `/api/finance-forecast/`: `what-if/`, `planned/`,
`planned/<id>/`, `planned/<id>/happened/`, `adjust/`, `adjust/<id>/undo/`,
`client-names/`, `explain/`, `review/`. Practice owner only; 404 without the
module.

**Migration:** `finance` 0010. One column on `finance_forecast_settings`
(`include_client_names`, false) and three new tables:
`finance_forecast_planned`, `finance_forecast_adjustment`,
`finance_forecast_snapshot`. No data step.

**The demo (§10).** Module on; a floor; planned: "Operations analyst, part
time" monthly from two months out, and two laptops next month; one what-if,
"Globex does not renew: its retainer stops"; two changes: the coworking rent
to $745 from the month the hire starts, and one meals line marked not
regular; one invoice 60-odd days overdue and not counted; six months of
"how good it has been".

**Where the build differs from the text above, or adds to it:**

- **The snapshot is taken the first time the forecast is worked out in a
  month,** by the screen or the dashboard line, not by a job on the first.
  A practice whose owner does not open the app in a month has no row for
  that month in "how good it has been". A scheduled job would close that
  gap and was left out so that this stop added nothing to the worker.
  *(Added 2026-10-12: see "As built: after stop 2" at the end.)*
- **"What happened" is counted from the day the snapshot was taken** to the
  end of the month, so a snapshot taken on the 9th is set beside the 9th
  onward, not the whole month.
- **One limit of 20 a day is shared** by "Explain this step", "Explain this
  forecast" and "Review with Claude" together, not 20 each.
- **The demo's floor is not $15,000.** It is set, to the whole thousand,
  two to three thousand under the 90-day low point as the books alone give
  it, so that the planned lines take the forecast under it whatever the
  seed's books come to. §10's "$15,000" was written before the books were.
- **The demo's two overdue invoices a month behind** are as M1 left them;
  the old one is a new invoice to a referral partner's member company, sent
  96 days before the seed's today.
- **"Not regular" lasts until it is undone;** it is not asked again at the
  next close.
- **A card's payment cannot be changed,** only tried without in a what-if.
- **"Likely annual" is confirmed into a planned line** a year after it was
  last seen (today, if that day has passed), at last year's amount; the
  owner can change both before saving, or mark it "not regular".
- **Explain sends the 180-day view** when the screen is on 12 months: the
  months are the same lines summed.
- **Lines sent to Claude are capped at 120,** the earliest first, and the
  prompt says so when there were more.
- **A what-if can switch off a client** (all of that client's invoices and
  schedules to come) or any single line, the card's payment included; switch
  on a what-if line; and try a different amount for a line. To keep a
  different amount is an adjustment, which is saved.

**Proven by tests:** the arithmetic of each of the above; that a look saves
nothing; isolation and role boundaries on every new route and table; what is
sent to Claude, read as text, with and without client names; the cap and the
budget refusing; the seed.
**Not seen in a browser:** any of the stop 2 screen, the dashed what-if line
on the chart, the forms. **Not run with a real key:** what Claude says, and
whether its review proposals are useful or stay off advice; the tests answer
for Claude. **Not run on real books.**

---

## 13. Tests

| Family | Tests |
|---|---|
| **Practice isolation** | The four new tables in the registry. Practice A's forecast is made of A's invoices, entries and closed months only, by id and in every total. A's planned line, adjustment and floor are not B's. The platform owner reaches none of it, and the module switch returns nothing from inside a practice. |
| **Role boundaries** | An assistant and an associate: 403 on every route, "Explain this forecast" included, and no forecast figure in their dashboard payload. A client user: 404. A practice without the module: 404, and no tab. |
| Where it starts | Cash today is the balance view's cash. A card is not cash. A stale account is named. |
| Known lines | An unpaid invoice lands on its due date moved by that client's median; never before the due date; on the due date with fewer than three paid invoices. A part-paid one forecasts what is left. A schedule forecasts each month to its end date and not past it. Over 60 days overdue is left out and listed. |
| Regular lines | Found from closed months only; an open month and a "locked before" month are not read. Fixed, varying, quarterly and yearly each forecast as §2.2 says. One already entered this month is not forecast again for it. Fewer than two closed months: no regular lines, and the screen says why. |
| The card | What is owed leaves the bank on the usual day, once. |
| Planned and what-if | A planned line is in the forecast until its date; a what-if is not counted until switched on; switching a line off changes the what-if and never the forecast as it stands; nothing here writes an entry. |
| Adjustments | Each kind does what it says from its date, survives the next close, and can be undone. |
| The arithmetic | Each week's end is its start plus in less out, and is the next week's start. The months view is the weeks view summed. The low point and the first week under the floor are those of the table. |
| How good it has been | The snapshot is taken as the month begins and is not changed afterwards; "actual" is the books' own figure once the month is closed. |
| Explain | Nothing is sent until pressed. What is sent is the list of §6 and nothing else, with no client or payee name (asserted on the prompt). The cap and the budget refuse. It writes nothing but its `ai_call`. |
| Disclaimer | Every forecast route renders the line. |

**Not verifiable without a browser:** whether the chart reads clearly; the
table at thirteen weeks wide on a laptop; whether "known, regular, planned"
is understood without explanation. **Not verifiable without a key:** what
Claude says about a forecast, and whether it stays off advice. **Not
verifiable without real books:** whether "two of the last three closed
months" finds a real practice's regular costs without finding its one-offs;
the demo's history is tidier than anyone's.

## As built: after stop 2 (2026-10-12) — two fixes before the release

- **"Not counted" and "Likely annual, to confirm" say "None." when they are
  empty,** and keep their card and the sentence saying what they are for.
  Before, each was not drawn at all when empty. "What you have changed" and
  "How good it has been" still are not drawn when empty; Known, Regular and
  Planned already showed "(0)".
- **The month's forecast is kept by a scheduled job,**
  `finance.keep_month_forecast` (`apps/finance/tasks.py`, declared in
  `ensure_schedules`). It runs **every day at the practice's own midnight**
  and keeps this month's forecast if it is not kept yet, so on the 1st it is
  kept as the month begins and "what happened" is the whole month. It is
  daily and not monthly so that a 1st the worker missed is made up the next
  day it runs (shown as "as it stood on" that day) and not a month later. It
  uses the practice's date, not the server's. It does nothing for a practice
  without the Cash forecast or with fewer than two closed months, and calls
  no AI.
- **The first look is still the fallback:** a practice the job has not
  reached (the module switched on mid-month, a worker that was down, the
  demo, which has no worker) has its month kept the first time the forecast
  is worked out, as before.
- No migration. **At a release, `ensure_schedules` must be run in production
  for the schedule to exist there.**

## As built: after Bryan's look on the demo (2026-10-13) — three fixes

- **"Explain this forecast" was cut off every time.** The model reasons
  before it writes and the reasoning is counted as output; Explain allowed
  800 tokens for both. The ceiling is 16,000 for Explain, Review and M1's
  "Explain this step", and Explain this forecast asks for low effort. The
  answer's length is still set by the prompt. **The cause is inferred, not
  observed:** the demo's `ai_call` rows were not read.
- **The form a review's proposal opens follows the proposal.** The review
  names a cadence for each line that was not picked up (monthly, quarterly,
  yearly); where it does not, the cadence is worked out from how far apart
  the books show the line. "When" is the date it next falls, counted from
  the day the books last show it, and is never today. A planned line can
  repeat **"Every year"** (`finance` 0011, the new choice only, no SQL).
  Confirming a "likely annual" item is unchanged: once, on its date.
- **Review is told what money in the forecast already has:** a line for each
  client's recurring invoice schedule (how often, how much each, how many in
  the next 12 months, the first expected) and a line for each client's open
  invoices (how many, their total, when expected), and is told not to ask
  about it. By letter, or by name with "Include client names in AI
  explanations" on; the letters are now the same ones Explain uses. No
  invoice number. This adds invoice amounts to what Review sends; Explain
  already sent them (M2-12).

**Proven by tests:** each of the three, the first with a double that answers
as the API does (a thinking block, then the text, and cut off when the limit
cannot hold both). **Not run with a real key since:** whether Explain now
answers, what it says at low effort, and whether Review stops asking about
client payments.
