# P6 M2 — Cash forecast

**Spec for owner review · 2026-10-10 · no code; nothing is built until the decisions in §12 are made**

The second of the four finance modules asked for by the owner on 2026-10-08
(`docs/p6_m1_reconciliation_month_close.md`: M1 reconciliation and month
close, accepted on the demo 2026-10-10; M2 cash forecast, this file; M3
balance sheet; M4 personal finance). It gets its own spec, is built after
approval, gets demo data, and is released only on "release".

**What this spec is written from.** The owner's brief for the four modules
is not in the repository, and its text was not in front of me when this was
written. What the repository records of it for M2 is short, and is all taken
as decided:

- It is a **cash forecast**.
- It is **the practice owner's only**, like everything in finance.
- It is **a module of its own** (`forecast`), switched on the platform's
  record of the practice; the price is P4's (M1 §7).
- It needs **two closed months** to forecast from, and months "locked before
  month close began" do not count (M1 §3.5, M1-9).
- It carries **the disclaimer** on every screen: "Bookkeeping and projections
  only, not tax, legal or financial advice. Confirm with your CPA." (M1 §6).
- AI calls are **costed and capped**; migrations are **additive and shown
  first**.

**Everything else below is a recommendation, and each one that matters is a
question in §12.** Where the brief said something this spec does not, the
brief wins: say so and the section changes.

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

- **Cash, week by week, for the next 13 weeks,** and month by month for 12
  months (M2-1). One row a week: cash at the start, money in, money out, cash
  at the end.
- **The low point:** the week the cash is lowest, how low, and how long from
  today.
- **The floor:** an amount the owner sets ("I want at least this much in the
  bank"). The first week the forecast goes under it is marked, with what is
  due that week (M2-6).
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

A cost (or any money in that is not an invoice) is **regular** when, in the
closed months, it shows up in the same category **and** from the same payee
(or with the same description when there is no payee), in at least two of
the last three closed months.

| What is found | What is forecast |
|---|---|
| The same amount each month (rent, software, insurance) | That amount, on the day of the month it usually falls |
| A different amount each month (contractors, travel, advertising) | The median of the last three closed months, on its usual day |
| Quarterly or yearly (a sponsorship, tax preparation, an annual renewal) | The last amount, a quarter or a year after the last one. Needs four closed months, or thirteen, to be found at all |
| Owner draws | The median of the last three closed months, on the usual day (M2-7) |
| Estimated tax payments (the Federal and State marks) | The last amount of each, on the next of January 15, April 15, June 15 and September 15 |

- **This is why it needs two closed months.** With fewer, the forecast shows
  only the known lines of §2.1 and says so at the top: "Close two months and
  your regular costs will be forecast from them. Until then this is only
  your invoices." Months "locked before month close began" do not count.
- **Only closed months are read.** An open month is still being entered and
  would understate every cost.
- **Each regular line says what it was found from:** "Larimer Square Cowork,
  $695.00 on the 1st, in each of the last 3 closed months."
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

- **What is sent (M2-12):** the weekly table (cash, in, out); the floor; the
  low point; the regular and planned lines by **category and amount**, and
  the known lines by **amount and date**. **No client's name, no payee's
  name, no invoice number, no one's contact details.**
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

## 12. Decisions for the owner

Nothing is built until these are answered. Each has what I would do and why.

| # | Question | Recommendation |
|---|---|---|
| **M2-1** | **How far ahead, and in what steps.** | 13 weeks by week, and 12 months by month. Thirteen weeks is a quarter, the span where the known lines are most of the answer; past that it is mostly "regular" and the months view says so. |
| M2-2 | The forecast starts from the books' cash today, and warns when an account has no entry in 14 days. | Yes. It does not require the current month to be reconciled: that would make it useless for the first three weeks of every month. |
| M2-3 | A draft or ready invoice not yet sent counts as if sent today. | Yes, labelled "not sent yet". Otherwise the first of the month's retainers vanish from the forecast between being written and being sent. |
| **M2-4** | **A client is forecast to pay as they have paid:** the median days after the due date over their last 12 months, never earlier than the due date, and only with three paid invoices to go on. | Yes. It is the single thing that makes this better than adding up due dates, and it is that client's own record, shown on the line. |
| **M2-5** | **An invoice more than 60 days overdue is left out,** listed beside the forecast, and can be put back with a date. | Yes. The alternative is a forecast propped up by money that may never come. |
| **M2-6** | **The floor** is one amount the owner sets; the forecast marks the first week under it. | Yes, and empty until set: the app should not invent how much cash you want. |
| M2-7 | Owner draws are forecast from the last three closed months, like any regular line. | Yes, and it is the line you will most often change. Leaving draws out would show cash piling up that you know you will take. |
| M2-8 | The card: what is owed today leaves the bank on the usual payment day; after that, card spending is paid the month after it is charged. | Yes. It matches a card paid in full. A practice carrying a balance is forecast from the payments it has actually made. |
| **M2-9** | **What-ifs are a look, not a saved scenario.** One forecast as it stands, one what-if beside it. | Yes. Named, saved scenarios are a second product; one what-if answers "can I afford this" and "what if they leave". |
| M2-10 | "How good it has been" shows differences, with no accuracy score. | Yes. A score invites trusting the number; the three biggest differences tell you what to fix. |
| M2-11 | One line on the practice owner's dashboard: the lowest cash in the next 13 weeks and when. | Yes, and only when the module is on and two months are closed. |
| **M2-12** | **What "Explain this forecast" sends to Claude:** the weekly table, the floor, the low point, lines by category and amount or by amount and date. **No names of clients or payees.** | Yes. It is enough to say where the low point comes from. With names it could say "when Acme pays", which is more useful and is your clients' names leaving the app; I would start without. |
| M2-13 | Forecast needs Bookkeeping, and switching it on without is refused. | Yes. It reads closed months, which only Bookkeeping makes. |
| **M2-14** | **Existing practices start with Forecast off.** | Off, unlike Bookkeeping, which was switched on for them. It is new and separately priced; you switch it on for Executives Now when you want it. The demo's seed switches it on. |
| M2-15 | "Regular" means the same category and the same payee (or description) in at least two of the last three closed months. | Yes. Looser and one-off costs become forecasts; stricter and a new subscription takes a quarter to appear. |
| M2-16 | A regular line is worked out each time and never stored; only your adjustments are. | Yes. A stored forecast drifts from the books; this cannot. |
| **M2-17** | **One stop or two.** | **Two:** first the forecast from known and regular lines, the floor, the screen and the module switch; then planned lines, what-ifs, adjustments, "how good it has been", "Explain this forecast" and the demo data. |
| M2-18 | The disclaimer, on every screen and under every explanation, and at the foot of the download. | As M1 §6, the same sentence. |

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
