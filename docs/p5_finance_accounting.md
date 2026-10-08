# P5 — Finance, the accounting half: books a practice can keep and hand to its CPA

**Spec for owner review · 2026-10-08 · no code yet**

Asked for by the owner on 2026-10-08 as "B", after client invoicing
(`docs/p4a_client_invoicing.md`, built). It is the accounting half of
`CLAUDE.md`'s "basic financials": income and expense entries, categories, a
CSV import of bank and card exports, paid invoices arriving as income, a P&L,
a simple balance view, the dashboard's finance figures and a CPA export.

**Already decided (owner, 2026-10-08): the practice owner only.** An associate
has nothing here; an assistant has nothing here, not entry and not import.
`CLAUDE.md` and the matrix are unchanged by this.

**Decided 2026-10-08: F1–F14 as recommended, with one change to F12.** 1099
tracking is in, in the second stop: a 1099 payee flag on vendors and
contacts, expense entries to that payee totaled by calendar year, and a
year-end report of payees over the threshold, exportable. W-2 stays out until
the HRIS module. The starting chart is as written; the year starts in January.
**The build is two stops (F14):** the books first, then the import, rules,
matching and 1099 tracking.

---

## 0. What the app has today that this uses, and one thing it cannot reuse

| Exists | Used for |
|---|---|
| `client_payment` (P4A): money recorded against an invoice, by hand | Each one becomes an income entry (§3) |
| `ai_call`, with the cost of every Claude call; the dashboard's "Practice finances" slot, which shows AI spend to the practice owner today | The AI figure, and where the new figures go (§6) |
| The contact import: three steps (map the columns, a dry run that writes nothing, commit), a saved mapping, and a rollback that undoes a committed import | The same three steps, the same CSV reader and the same wizard screen (§4) |
| `AuditEvent`; integer cents (`apps/billing/money.py`) | The trail on every change; every amount |

**The contact import's tables cannot hold bank lines.** `import_batch`,
`import_row` and `import_mapping_profile` are built around contacts (each row
points at a contact), and **an assistant can read them**: CSV import is an
assistant's job. A bank export stored there would put every transaction in
front of the one role that has no financials. So this spec reuses the flow,
the reader and the screen, and gives finance its own three tables (F2).

---

## 1. The shape of the books

**Single-entry and cash-basis.** One line per movement of money, each in one
category. Income counts when the money arrives and an expense when it leaves
(F1). This is what a consulting practice's CPA expects from a small client,
and it is what "QB-lite" can honestly be. It is not double-entry, and it has
no journal.

### 1.1 An entry

| Field | Rule |
|---|---|
| **Kind** | `income`, `expense`, `transfer` (between two of the practice's own accounts), or `owner` (money the owner puts in or takes out). Only the first two are in the P&L (F3). |
| **Date** | The day the money moved |
| **Amount** | Whole cents, always positive; the kind says which way it went |
| **Category** | One, of a type that fits the kind (§1.3). A transfer has none. |
| **Account** | The bank account, card or cash it moved through (§1.2). A transfer has two. Empty on an invoice payment not yet seen at the bank (§3). |
| **Description, payee or payer** | Free text |
| **Client company** | Optional: who the income came from, or who an expense was for |
| **Reference** | A check number, a confirmation |
| **Source** | Typed by hand, from an import, or from an invoice payment. Kept, and shown. |

### 1.2 Accounts

The places the practice's money sits: **bank**, **credit card** or **cash**.
Each has a name, the last four digits, an opening balance and the date it is
as of. An account is closed, never deleted, once it has entries.

### 1.3 Categories

Each has a name, a type (income, expense, owner, or sales tax held), an order,
and an optional **CPA code**: free text the owner's CPA can ask for (a tax
form line, their own account number), carried into the export.

A practice starts with this chart and edits it freely: rename, add, reorder,
and archive (a category with entries is archived, not deleted, and its type
is fixed once it is used). The list itself is F7.

| Income | Expenses | |
|---|---|---|
| Client fees | Contractors and associates | Insurance |
| Project fees | Payroll and wages | Office and supplies |
| Workshops and speaking | Payroll taxes and benefits | Rent and coworking |
| Referral fees received | Software and subscriptions | Phone and internet |
| Reimbursed expenses | AI and API usage | Education and training |
| Other income | Marketing and advertising | Dues and memberships |
| | Travel | Bank and merchant fees |
| | Meals | Referral fees paid |
| | Professional services (legal, accounting) | Taxes and licenses |
| | | Interest · Other expenses |

**Owner:** Owner contribution, Owner draw. **Held:** Sales tax collected.

---

## 2. Entering and changing

- **Add an entry** by hand: date, kind, amount, category, account, the rest
  optional. A quick form at the top of the entries list.
- **The list:** newest first; filters for dates, kind, category, account,
  client company, source and "no category yet"; a search over description and
  payee; totals for what is listed.
- **Edit and remove.** Any field of a hand-typed or imported entry. Removing
  needs a reason and keeps the row, marked removed. **An entry made from an
  invoice payment is changed only on the invoice** (§3): its amount and date
  are the payment's.
- **Recategorize several at once**: tick rows, choose a category.
- **Locked periods (F8).** The practice owner sets "books are locked through"
  a date, usually after handing a period to the CPA. Nothing dated on or
  before it can be added, changed, removed, imported or rolled back until the
  date is moved back, which is itself audited.
- **Every add, change, removal, import, rollback and lock writes an audit
  event** with what it was before and after.

---

## 3. Paid invoices become income

- **When a payment is recorded against an invoice** (P4A), an income entry is
  written in the same transaction: the payment's date and amount, the
  category "Client fees" (or the practice's chosen default), the client
  company, the description "Invoice INV-0007", the payment's reference. A
  part payment makes an entry for that part.
- **When a payment is removed**, its entry is removed with it, with the same
  reason. A void invoice has no payments (P4A refuses the void while one
  counts), so nothing is left behind.
- **Sales tax (F5).** Where an invoice carries tax, each payment is split in
  the invoice's own proportion: the fee to income, the tax to "Sales tax
  collected", which is held, not earned, and shows on the balance view.
- **Not yet seen at the bank.** A payment recorded by hand names no bank
  account. Its entry has no account until an imported bank line is matched to
  it (§4.3). The balance view shows these as "Received, not yet seen at the
  bank", so they are never counted twice and never lost.
- **An invoice is never income before it is paid.** What clients owe shows
  beside the balance view, from P4A's totals, and is in no P&L (F1).
- **Payments recorded before this is built** are given their entries once, by
  the migration that creates these tables, with the count shown first (F13).

---

## 4. Importing a bank or card export

### 4.1 The three steps, as the contact import has them

1. **Choose the account and the file, and map the columns.** Date (and its
   format, detected and shown), description, and the amount: either one
   signed column (with "money out is negative" or its opposite) or separate
   debit and credit columns. Optional: a running balance, a reference, the
   bank's own transaction id. **The mapping is saved per account**, so next
   month's file from the same bank needs no mapping.
2. **The dry run.** Every row is shown with what will happen to it, and
   **nothing is written to the books**. The owner fixes categories here.
3. **Commit**, in one transaction. **A committed import can be rolled back**:
   every entry it made that has not been edited since is removed, and every
   match it made is undone. Rolling back is refused for a locked period.

### 4.2 What the dry run decides for each row

| Outcome | When | On commit |
|---|---|---|
| **New, with a category** | A rule (§4.4) named one, or the owner chose one in the dry run | An entry is made |
| **New, needs a category** | Nothing named one | An entry is made with no category, and shows under "no category yet". It is left out of the P&L until it has one, and the P&L says how many there are. |
| **Already in the books** | The same account, date, amount and description (or the bank's own id) is already there. Downloading an overlapping range every month is normal. | Nothing |
| **This is an invoice payment** | A deposit matches an unmatched invoice payment's amount, within seven days (F4) | No new entry. The payment's entry is given this account. |
| **This is a transfer** | The owner marks it (a card payment from the bank; a move between accounts), or it matches the other side already imported | One transfer entry, not two |
| **Owner contribution or draw** | The owner marks it | An `owner` entry |
| **Ignore** | The owner marks it (a pending line, a balance row) | Nothing |
| **Cannot be read** | No date or no amount | Nothing; the row and why are listed |

Two identical lines on the same day (two $5 coffees) are two entries: the
second is matched against a second existing one, not against the first.

### 4.3 Why matching matters

Without it the same money is counted twice: once when the payment is recorded
on the invoice, and again when the bank's deposit is imported. The dry run
proposes each match with both sides shown; the owner accepts it or says the
deposit is something else. Nothing is matched without being shown.

### 4.4 Rules (F6)

When the owner gives a line a category, the app offers to remember it: "lines
whose description contains *ADOBE* are Software and subscriptions". Rules are
the practice's own, listed and editable in Settings → Finance, and applied in
the next dry run, where each is shown beside the row it decided. **No AI is
used anywhere in this module.**

### 4.5 Limits

5,000 rows a file; UTF-8 or Windows-1252; amounts with `$`, commas and
bracketed negatives; US dollars. A file with no header row is refused with a
sentence saying so.

---

## 5. What the books say

### 5.1 P&L

For a year, **by month or by quarter**: income categories, expense
categories, a total for each, and net (income less expenses) per period and
for the year. Calendar months and quarters (F10). Any figure opens the
entries behind it. Transfers, owner entries and held sales tax are not in it.
Entries with no category are named in a line above it ("14 entries, $2,310.44,
have no category and are not in these figures"), never silently dropped.
Downloadable as CSV.

### 5.2 The balance view

As of a date:

| Line | From |
|---|---|
| Each bank and cash account | Its opening balance, plus and minus its entries |
| Received, not yet seen at the bank | Invoice payments with no account yet |
| **Cash** | The sum of the above |
| Each credit card, as owed | Its opening balance, plus and minus its entries |
| Sales tax collected, not yet paid over | The held category |
| **Net** | Cash, less what is owed |
| *Beside it, not in it:* owed to you by clients | P4A's outstanding invoices |

Where the last imported file carried a running balance, the view says so
beside the account: "Your bank said $18,204.11 on October 31; the books say
$18,204.11", or the difference. It is a check, not a reconciliation tool.

This is a statement of cash, cards and tax held. It is **not a balance
sheet**: no fixed assets, no loans, no retained earnings. The screen and the
export say "balance view", and say what it leaves out.

### 5.3 The dashboard (practice owner only)

In the existing "Practice finances" panel: **revenue this month**, **expenses
this month**, **margin** (net as a share of revenue; a dash when there is no
revenue), and **AI spend this month**, which is there today. Each opens the
P&L or the entries behind it. An associate and an assistant see the panel
exactly as they do now.

**AI spend comes from the app's own record of Claude calls (F9)**, as it does
today, not from the books. The practice's Anthropic bill arrives in the books
when its card statement is imported, as "AI and API usage"; the two are not
added together and nothing is entered automatically from one into the other.

### 5.4 The CPA export

For a range of dates, two CSV files (F11):

- **Entries:** date, kind, category, CPA code, description, payee or payer,
  account, money in, money out, client company, invoice number, reference,
  source. Removed entries are left out; uncategorized ones are in, marked.
- **Summary:** each category with its CPA code and its total for the range,
  and net.

Each download is an audit event: who, when, which dates.

---

## 6. Who sees and does what

| # | Capability | Practice owner | Associate | Assistant | Client owner | Client team member |
|---|---|---|---|---|---|---|
| 13.1 | View the P&L and the balance view *(existing row)* | ✅ | ❌ | ❌ | ❌ | ❌ |
| 13.6 | Entries: see, add, change, remove | ✅ | ❌ | ❌ | — | — |
| 13.7 | Accounts, categories, rules, the lock | ✅ | ❌ | ❌ | — | — |
| 13.8 | Import a bank or card export; roll one back | ✅ | ❌ | ❌ | — | — |
| 13.9 | The CPA export | ✅ | ❌ | ❌ | — | — |
| 13.10 | The dashboard's revenue, expenses and margin | ✅ | ❌ | ❌ | — | — |

- **Status codes:** an associate and an assistant get 403 on every finance
  route; a client user gets 404; another practice gets 404.
- **An associate keeps what P4A gave them** (invoices for assigned client
  companies) and gains nothing: not the income entry a payment made, not a
  total.
- **The platform owner** sees none of it.
- **Nowhere else:** a finance entry is in no search, no activity feed, no
  timeline, no email and no import list an assistant can read. Its audit
  events are not in the activity feed's list.

---

## 7. Data model

A new app, `apps/finance`. Every table is practice-scoped (`tenant_id`,
fail-closed manager) and joins the isolation registry. **Nothing existing is
altered.**

| Table | Columns |
|---|---|
| `finance_settings` | `tenant_id` (unique), `invoice_income_category_id`, `locked_through` (null) |
| `finance_account` | `id`, `tenant_id`, `name`, `kind` (`bank / card / cash`), `last4`, `opening_balance_cents`, `opening_on`, `closed_at` |
| `finance_category` | `id`, `tenant_id`, `name` (unique per practice among live ones), `type` (`income / expense / owner / held`), `position`, `cpa_code`, `is_system` (the two this module relies on), `archived_at` |
| `finance_entry` | `id`, `tenant_id`, `kind` (`income / expense / transfer / owner`), `on_date`, `amount_cents` (> 0), `category_id` (null), `account_id` (null), `to_account_id` (transfers only), `owner_direction` (`in / out`, owner entries only), `description`, `counterparty`, `client_company_id` (null), `reference`, `source` (`manual / import / invoice`), `client_payment_id` (null), `import_row_id` (null), `bank_id` (the bank's own transaction id), `created_by_id`, `removed_at`, `removed_by_id`, `remove_reason` |
| `finance_rule` | `id`, `tenant_id`, `contains` (matched without regard to case), `account_id` (null = any), `category_id` or `as_kind` (`transfer / owner / ignore`), `position`, `is_active` |
| `finance_import_profile` | `id`, `tenant_id`, `account_id` (unique), `mapping` (json: columns, date format, sign) |
| `finance_import_batch` | `id`, `tenant_id`, `account_id`, `filename`, `status` (`dry_run / committed / rolled_back`), `mapping` (as the dry run used it), `counts`, `last_balance_cents`, `last_balance_on`, `created_by_id`, `committed_at`, `rolled_back_at` |
| `finance_import_row` | `id`, `tenant_id`, `batch_id`, `row_number`, `raw` (json), `on_date`, `amount_cents`, `direction` (`in / out`), `description`, `outcome` (§4.2), `category_id`, `matched_entry_id`, `rule_id`, `error_text`, `entry_id` (what the commit made) |

Constraints: an amount is positive; a transfer has two different accounts and
no category; income and expense categories match their entry's kind; one
entry per invoice payment (`client_payment_id` unique among live entries).

**Migration:** one, `finance 0001`, creating the eight tables, seeding the
default chart for each existing practice, and writing an entry for each
existing invoice payment (F13). Its SQL is shown before it is generated; the
count of entries it would write is shown before it runs; it is applied on
`execsnowhq_local` only.

**The one hook into existing code:** `billing.services.record_payment` and
`remove_payment` call `finance.services.payment_recorded` / `payment_removed`
in the same transaction.

---

## 8. Tests

| Family | Tests |
|---|---|
| **Practice isolation** | All eight tables in the registry. Practice A never sees B's entries, accounts, categories, rules, imports or exports, by list, by id or in a total. A's import cannot name B's account. The platform owner reaches nothing. |
| **Role boundaries** | **An assistant: 403 on every finance route, including the import**, and none of it in search, the activity feed, the dashboard or the contact import list. An associate: 403 on every route, including for an assigned client company, and the dashboard panel unchanged. A client user: 404. |
| Money | Whole cents; totals add up; no float anywhere. P&L: each month's net is income less expenses; the quarters are the sums of their months; the year is the sum of the quarters; an entry on the last day of a month is in that month. |
| Invoices | A payment makes one income entry in the same transaction; a part payment, one for that part; a removed payment removes its entry; tax is split in proportion and the pieces add up to the payment exactly. Nothing is income before it is paid. |
| No double counting | A deposit that matches an invoice payment makes no new entry. A card payment imported from both the bank's file and the card's is one transfer. Importing the same file twice adds nothing. Two identical lines on one day are two entries, once. |
| Import | The dry run writes nothing to the books. The commit writes what the dry run showed, even if rules changed in between. Rollback removes what it made and undoes its matches; an entry edited since is kept and named. Debit and credit columns, a signed column either way, bracketed negatives, four date formats. A locked period refuses all of it. |
| Balance view | Opening balances, transfers moving money without changing net, unmatched payments shown once, the bank's own balance compared. |
| Export | The entries file adds up to the summary file; the dates are inclusive; removed entries are out; each download is audited. |
| Lock | Nothing on or before the date is added, changed, removed, imported or rolled back. |

**Not verifiable without a browser:** the import wizard on a real bank's
file; the P&L's layout with twelve months across; the entries list at volume.

---

## As built

**First stop (2026-10-08): the books.** `apps/finance` (`models.py`,
`services.py`, `reports.py`, `views.py`), the screens `Finance` (entries,
profit and loss, balance view, for your CPA) and `FinanceSettings`, the
dashboard's three figures, `tests/test_finance_books.py` and
`frontend/src/screens/Finance.test.tsx`. Matrix rows 13.6–13.10.

**Migration `finance 0001`, applied on `execsnowhq_local` only:** four tables
(`finance_account`, `finance_category`, `finance_entry`, `finance_settings`).
Nothing existing is altered. The other four tables of §7 are the second
stop's.

Differences from the text above:

- **A fifth kind of entry, `held`**, for sales tax collected and, later, paid
  over. §1.1 named four kinds; tax held is not the owner's money and needed
  its own. With it an entry has a **direction** (in or out), fixed by the
  kind for income and expense and chosen for owner money and tax held.
- **The chart is made the first time a practice's books are opened**, not by
  the migration, so a practice provisioned later gets it too. It is made once:
  archiving every category does not bring it back.
- **Payments recorded before the books (F13)** are entered by a command with a
  dry run, `manage.py backfill_invoice_income`, not by the migration. On the
  laptop it found none.
- **The lock reaches invoicing.** A payment dated in a locked period is
  refused on the invoice, in the same words, and is not recorded: the payment
  and its entry are one transaction.
- **An invoice payment's entry** can have its category, account and
  description changed in the books; its amount, date and client are changed
  on the invoice. Placing it in an account by hand is how it leaves "not yet
  placed" until the import can match it.
- **An entry may have no category** when typed in, as an imported one may. It
  is named beside the P&L and in the export, and left out of the figures.
- **The balance view** counts an account from its opening date: an entry dated
  before that is taken to be inside the opening balance. The comparison with
  the bank's own balance (§5.2) comes with the import.
- **The dashboard panel** for an associate now reads "The practice's income,
  expenses and margin are shown to the practice owner", in place of the old
  line about the finance module arriving.
- The entries list shows the newest 500 of what is filtered, and says so.

**Second stop, not built:** the import with its own tables, rules, matching a
deposit to an invoice payment, and 1099 tracking (a payee flag on vendors and
contacts, expense entries to that payee totaled by calendar year, and a
year-end report of payees over the threshold, exportable).

## 9. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| **F1** | **Cash basis:** income counts when paid, an expense when the money leaves; what clients owe is shown beside the balance view and is in no P&L. | Yes. It is what you asked for ("when paid") and what a CPA expects from a practice this size. Accrual would be a different module. |
| **F2** | **The import has its own tables**, and reuses the contact import's three steps, CSV reader and wizard screen, not its tables. | Yes. An assistant can read the contact import's tables; bank lines cannot go there. |
| **F3** | **Transfers and owner money are kinds of their own**, outside the P&L. | Yes. Without them, paying the card from the bank is an expense twice, and your own draw is a cost. |
| **F4** | **A bank deposit is matched to the invoice payment it is**, proposed in the dry run and accepted by you, within seven days and for the same amount. | Yes. It is the difference between revenue and revenue counted twice. |
| F5 | Sales tax on a paid invoice goes to "Sales tax collected", in proportion, and not to income. | Yes. It is rarely used in Beta, and wrong income is worse than an extra category. |
| F6 | Rules remembered from your own choices ("contains ADOBE"), and no AI. | Yes. Otherwise every month's import is categorized from scratch. |
| **F7** | **The starting chart of §1.3.** | Yours to edit before the build: these are the names every new practice starts with. |
| F8 | "Books are locked through" a date. | Yes. It is what makes a CPA export stay true after it is sent. |
| F9 | AI spend on the dashboard stays the app's own record of Claude calls; nothing is entered into the books from it. | Yes. The books get it from the card statement; entering it twice would double it. |
| F10 | Calendar months, quarters and years. No fiscal-year setting. | Yes for Beta. Say if your year does not start in January. |
| F11 | The CPA export is two CSV files: entries, and a summary by category. | Yes. Ask your CPA whether another layout would save them work; it is cheap to add. |
| **F12** | **Not in this round:** 1099 and W-2 tracking (it is in `CLAUDE.md`'s list for this module), receipts attached to entries, live bank feeds, budgets, accrual, double-entry and a true balance sheet, and any QuickBooks connection. | As listed. 1099 tracking is the natural next piece: "Contractors and associates" by payee for a year. |
| F13 | Invoice payments recorded before this is built get their entries from the migration, with the count shown first. | Yes. Today that is whatever has been recorded on the laptop; production has none. |
| **F14** | **One stop or two for the build.** This is larger than client invoicing: the import is about half of it. | **Two stops:** first the entries, accounts, categories, paid invoices as income, the P&L, the balance view, the dashboard and the export; then the import, rules and matching. The first is useful by itself. Say if you would rather have one. |
