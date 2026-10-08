# P4 — Billing on NMI: PRD section and data model

**Practices beta program, phase 4 · spec only, no code · re-specified 2026-10-08**

**This replaces the Stripe version of 2026-10-03** (in git history at
`fa79a2a`). The owner decided D1–D10 on 2026-10-08 and changed the processor:
**NMI everywhere, no Stripe.** His decisions are recorded in §7, and his
answers to N1–N9 the same day in §8. **Next is Phase 0 (§6): prove NMI in its
sandbox, with no product code.** Nothing here is built.

**Words used here.** *The platform* is Noble Rose LLC, doing business as
Executives Now and Execs NOW HQ. *The platform account* is Noble Rose LLC's
NMI merchant account. *A practice's account* is that practice's own NMI
merchant account, connected with its own keys.

Two flows of money, and no third:

| | Who pays whom | On which NMI account | Section |
|---|---|---|---|
| **A. Practice subscriptions** | a practice pays the platform | the platform account | §2 |
| **B. Client invoicing** | a client (or any contact) pays a practice | **that practice's own** account | §3 |

**Payments never flow through the platform (D10).** There is no
collect-through-the-platform, no platform fee on a client's payment, and no
shared merchant account. A practice with no NMI account can make and send
invoices and mark them paid by hand; it cannot take a card payment in the app.

---

## 0. What is assumed about NMI, and what has to be proved first

**None of this has been run against NMI.** It is written from NMI's public
documentation and support articles, read on 2026-10-08, and two of the points
below had sources that disagreed. Phase 0 (§6) proves each one in NMI's
sandbox before anything is built on it.

| # | Assumed | Used for | Confidence |
|---|---|---|---|
| A1 | **Collect.js** puts NMI-hosted card fields on a page and returns a one-time `payment_token`. The card number never reaches this app's server. It needs the account's public tokenization key. | Card on file (§2), and the pay page if N3 is (b) | Documented; not run |
| A2 | **Customer Vault** stores a card or bank account from a `payment_token` and returns a `customer_vault_id`, which a later sale or a subscription can charge. | Card on file | Documented; not run |
| A3 | **Recurring** can run a subscription with its own amount and schedule (monthly, on a day of the month) against a vault record, without a shared plan, and its amount can be changed for the next charge. | Per-practice amounts and add-ons (§2.3) | **Creating: documented. Changing the amount of a live subscription: not confirmed.** |
| A4 | **Invoicing** (`add_invoice`) creates an invoice at NMI with a hosted payment page, and NMI emails the customer a link to it. Required: amount and email. It returns an invoice id used to update, resend or close it. | Pay link for a client invoice (§3.4) | Documented. **Not confirmed: whether NMI's own email can be turned off, and whether the pay page's URL is returned to us.** |
| A5 | **Webhooks** post transaction events (`transaction.sale.success`, `.failure`, refund, void) with an event id, signed with HMAC-SHA256 and a signing key from the account's settings. | Paid and failed (§4) | **Sources disagree on the header and on what is signed.** No source confirmed an event for a recurring charge or for a chargeback. |
| A6 | The **Query API** returns transactions by id, by subscription and by date range, with their condition (complete, failed, pending settlement). | Polling and the daily reconciliation (§4) | Documented; not run |
| A7 | Customer Vault, Recurring and Invoicing are **services switched on per merchant account**, sometimes at a monthly fee from the reseller. | Whether a practice's account can do §3 at all | Likely; to be checked on the platform account and stated to each practice |
| A8 | One merchant account can post webhooks to **more than one URL**. | The platform account is also Executives Now's practice account (§1.2) | Not confirmed. §4 does not depend on it. |

Because of A3, A4 and A5, **the design below never depends on a single NMI
feature without a fallback**, and says which is which.

---

## 1. The processor layer

### 1.1 One adapter

`apps/billing/nmi.py` is the only module that talks to NMI. Everything else
calls it with **an account** and never with a key:

| Call | What it does at NMI |
|---|---|
| `vault_add(account, payment_token, billing)` | Stores a card or bank account; returns the vault id, brand, last four and expiry |
| `vault_update`, `vault_delete` | Replace or remove the stored method |
| `sale(account, amount_cents, vault_id or payment_token, reference)` | One charge, carrying our reference |
| `subscription_add / update / cancel(account, …)` | The recurring schedule (§2.3) |
| `invoice_add / update / close(account, …)` | NMI's hosted invoice (§3.4, if N3 is (a)) |
| `refund(account, transaction_id, amount_cents)` | Not called from any screen in the first build; refunds are done in NMI's own portal |
| `query(account, …)` | Transactions by id, subscription or date |
| `verify_webhook(account, headers, raw_body)` | True only for a body signed with that account's signing key |

- **Every outgoing call carries our own reference** (the id of the
  `practice_invoice` or `client_invoice` it is for) in NMI's order id field,
  so a transaction read back later is matched by our reference, never by
  amount, email or account.
- **Money is integer cents** in this app and converted at the adapter's edge.
- **A fake adapter** stands in for NMI in every test, as `fake_claude` does
  for Claude. No test reaches the network.
- **Which NMI API** (the form-posted Payment API or the newer REST API) is
  chosen in Phase 0 and hidden behind this module.

### 1.2 Two kinds of account, kept apart

| | The platform account | A practice's account |
|---|---|---|
| Whose | Noble Rose LLC | The practice's own |
| Keys kept in | Environment only: `NMI_PLATFORM_SECURITY_KEY`, `NMI_PLATFORM_TOKENIZATION_KEY`, `NMI_PLATFORM_WEBHOOK_KEY` | `tenant_secret`, encrypted, write-only (as the Anthropic key is) |
| Entered by | The owner, in Railway | The practice owner, in Settings → Payments |
| Used by | §2 only (`apps/platform/billing.py`) | §3 only, and only for that practice |
| Statement descriptor | "Execs NOW HQ", set by the owner in NMI | The practice's, set by the practice in NMI |

**The platform account is also the account Executives Now uses as a practice**
(same legal entity). The code still treats them as two accounts: the platform
side reads the environment and never a `tenant_secret`; the Executives Now
practice enters the same keys in Settings → Payments like any other practice.
A payment is told apart by **our reference on it**, never by which account it
arrived on, so a client paying Executives Now can never be read as a practice
paying its subscription, or the reverse. This has its own tests (§5).

### 1.3 What the app never holds

Card numbers, security codes and bank account numbers never reach this app's
server, its logs or its database (A1). It stores a vault id, a brand, the last
four digits and an expiry month. **The design assumes SAQ A** (N9): the owner
is asking NMI which self-assessment applies with their card fields on this
app's pages. If the answer is not SAQ A, §2.2's card screen and §3.4 are
looked at again before they are built.

---

## 2. Practice subscriptions (a practice pays the platform)

### 2.1 Plans and add-ons (D9)

- **A plan** is a base monthly price. **An add-on** is a monthly price for one
  module, added to the base.
- **Beta has one plan, "Beta at cost": $20.00 a month by default,** and the
  owner sets a different figure for any one practice. It has no add-ons:
  everything in the app is included.
- **Released pricing is a base rate plus per-module add-ons, set later.** The
  tables exist now with **placeholder prices marked as placeholders**
  (`is_placeholder`), and no screen shows a placeholder price to a practice.
- A practice's monthly amount is **the base (or its own override) plus the
  add-ons it has**. The app works this out; NMI is told one number.
- Whether an add-on also switches its module on and off is N6.

### 2.2 What it does

- **No trial (D1), and no part-month.** The fee is charged **on the first day
  of each month** (agreement v2, clause 3). A card put on file mid-month is
  not charged until the next 1st, so the days before a practice's first 1st
  are not charged for.
- **Card on file.** Settings → Billing has NMI's own card fields (A1). The
  practice owner enters a card; the app stores the vault id on the platform
  account. Associates, assistants and clients never see this screen.
- **On the 1st** NMI charges the stored card (§2.3). For every charge the app
  has **its own invoice**: number, period, lines (base and each add-on),
  total, status and a PDF, which the practice owner sees and downloads (D8).
- **A receipt is emailed for every successful charge**, to the practice's
  billing email, with that invoice's PDF attached (the agreement promises it).
  It is sent by the app, as a transactional message, not by NMI.
- **A failed charge** leaves that invoice open. The practice owner is emailed
  through the Outbox with a link to Settings → Billing, where they update the
  card and press **Pay now** (one `sale` against the vault).
- **Changing the amount (D4)** takes effect at the next period, with no
  part-month charge or credit. **A module added mid-month is included for the
  rest of that month** and charged from the next period. Settings → Billing
  says so in those words beside each add-on; the agreement needs the same
  sentence (N1).
- **Suspension (D2).** An invoice unpaid 30 days after it was issued makes the
  practice **eligible**. The Practices screen shows "Overdue 30+ days:
  suspend?" and the owner presses Suspend. Nothing suspends by itself.
- **Suspended** means the practice's staff see one screen ("Your practice is
  suspended until the invoice is paid", with Pay now). Its scheduled jobs and
  sends stop. Clients see nothing new. **No data is touched.**
- **Lifting (D3)** is automatic when the overdue invoice is recorded as paid,
  whether by Pay now, by a webhook or by the reconciliation.
- **Tax (D5).** None in Beta. Every invoice has a tax line that is zero. At
  release tax is on for every practice, the Beta ones included. NMI does not
  work out sales tax, so where the rates come from is N7.
- **The owner's own practice** is not billed.
- **Archiving** a practice cancels its subscription at NMI at once and makes
  no further charge. Unarchiving starts a new one.
- **Refunds and credits** are made in NMI's portal. The reconciliation
  records a refund against the invoice; the app has no refund button.

### 2.3 How it maps to NMI

| App | NMI, on the platform account |
|---|---|
| A practice | A Customer Vault record |
| A practice's subscription | **One recurring subscription with its own amount** (A3), monthly, **on day 1**, starting on the first 1st after the card is put on file |
| A change of amount | The subscription's amount is updated before the next charge. **If A3 fails in the sandbox:** cancel it and add a new one starting on the next period's date. |
| A monthly charge | A transaction carrying the subscription's id; the app makes its invoice for the period and marks it from §4 |
| Pay now | One `sale` against the vault, carrying the open invoice's reference |

**The alternative, if Phase 0 shows NMI's recurring is too blunt** (N2): the
app's own daily job charges each practice's vault on its day. The app then
makes the invoice first and knows the result of every charge at once.

---

## 3. Client invoicing (a client pays its practice)

### 3.1 Kinds of invoice (D7)

| Kind | To | How it starts |
|---|---|---|
| **One-off** | A client company | A person writes it |
| **Recurring** | A client company | A schedule (monthly, on a day) writes a **draft** each period; a person approves the send |
| **One-off to a contact** | Any contact, client or not | A person writes it. Sent by email only, with the PDF and the pay link. It appears in no portal. |

A recurring invoice is a **recurring draft**, not a recurring charge: review
queues over automation. Charging a client's stored card with nobody approving
it is N4.

### 3.2 What an invoice is

- Number, issue date, due date (net 15 by default), lines, subtotal, tax (zero
  in Beta), total, notes and terms. **Status:** draft → sent → paid, partly
  paid or void. Numbers run per practice (`INV-0001`, prefix editable) and
  never skip or repeat.
- A line has a description, quantity, unit price and amount, and optionally
  the project or goal it bills for.
- **Sending is an Outbox message**, approved like any client email, with the
  PDF attached (the practice's own branding) and a **Pay now** link.
- **A sent invoice cannot be edited.** It is voided and a new one written.

### 3.3 Connecting a practice's NMI account

Settings → Payments, practice owner only: the account's security key, its
public tokenization key and its webhook signing key, each stored encrypted and
never shown again. **Test connection** makes one read-only query. The screen
says which NMI services the practice's account needs (A7) and gives the
webhook address to paste into NMI (§4).

**QuickBooks is not a processor (D6).** It is a later accounting connection
for practices that keep books for their clients, and takes no payment.

### 3.4 The pay link (N3)

Two ways to make "Pay now", and the choice is the owner's:

| | (a) NMI's hosted invoice | (b) A pay page in this app |
|---|---|---|
| The client lands on | A page at NMI | A page at `app.getexecutivesnow.com/pay/<token>`, with NMI's own card fields in it (A1) |
| Card details reach this app | Never | Never (the fields are NMI's) |
| Who emails the client | **NMI does, itself** (A4), unless that can be turned off | Only the practice, through the Outbox |
| Branding | NMI's page, the practice's NMI settings | The practice's own |
| Depends on | A4's two open points; the Invoicing service on every practice's account | Only Collect.js and a sale |
| The money | To the practice's account | To the practice's account |

Either way the charge is made **with the practice's own key on the practice's
own account**. Option (b) does not route money through the platform: the app
shows the page, NMI takes the card, and the practice's account is paid.

### 3.5 Paid, and who sees what

- **Paid** is recorded from §4, or **by hand** (date, amount, method,
  reference) for a check or a bank transfer. Part payments are kept, and the
  invoice shows the balance.
- **Reminders:** when an invoice passes its due date a reminder is drafted
  into the review queue. Nothing is sent by itself.

| # | Capability | Practice owner | Associate | Assistant | Client owner | Client team member |
|---|---|---|---|---|---|---|
| 12.1 | Connect or change the practice's NMI account | ✅ | ❌ | ❌ | — | — |
| 12.2 | See and download invoices | ✅ every one | 🔸 assigned client companies | ❌ | ✅ their company's | ✅ their company's (D8) |
| 12.3 | Write and edit a draft | ✅ | 🔸 assigned client companies | ❌ | — | — |
| 12.4 | Approve a send; void; mark paid by hand | ✅ | ❌ | ❌ | — | — |
| 12.5 | Pay an invoice | — | — | — | ✅ | ✅ |
| 12.6 | Invoices to a contact that is not a client company | ✅ | ❌ | ❌ | — | — |
| 12.7 | Settings → Billing (the practice's own subscription) | ✅ | ❌ | ❌ | — | — |

**D8 gives a client team member a first view of money.** Until now nothing
financial reached that role. It is limited to their own company's invoices;
whether a client owner can narrow it is N5.

**The platform owner** sees each practice's plan, amount, status and oldest
unpaid subscription invoice, and **never** a practice's client invoices, its
NMI keys or its clients' payments.

---

## 4. Learning that a charge was paid or failed

Both are built; neither is trusted alone.

- **Webhooks**, where the account has them set up:
  - The platform account posts to `/api/nmi/webhook/platform`, verified with
    the platform's signing key.
  - A practice's account posts to `/api/nmi/webhook/<opaque address>`, an
    address that names the practice without being guessable, verified with
    **that practice's** signing key. The practice is taken from the address
    and proved by the signature, never read from the body.
  - A body that fails verification is refused (400) and recorded. An event is
    processed once, by its event id.
  - An event whose reference is not one of that account's own open invoices
    is recorded and ignored. This is what keeps the shared account of §1.2
    apart.
- **Polling**, always: an hourly job asks NMI about every invoice that is open
  and every subscription charge that is due, per account, and a daily job
  reconciles the last several days. A practice that never sets up a webhook
  still gets its invoices marked paid within the hour.
- **Either source reaches the same function**, which marks the invoice from
  what NMI says and is safe to run twice.
- A chargeback or a refund found by the reconciliation is recorded on the
  invoice and shown to the practice owner. No source confirmed NMI sends an
  event for a chargeback (A5), so this may be found a day late.

---

## 5. Data model

A new app, `apps/billing`. Every table is practice-scoped (`tenant_id`,
fail-closed manager) **except** `billing_plan`, `billing_addon` and
`nmi_event`, which are the platform's. Platform reads of practice billing rows
go through one module (`apps/platform/billing.py`), as `stats.py` does.

### 5.1 Subscriptions

| Table | Columns |
|---|---|
| `billing_plan` *(platform)* | `id`, `code` (`beta_at_cost`, …), `name`, `interval` (`month`), `price_cents`, `is_placeholder`, `is_active` |
| `billing_addon` *(platform)* | `id`, `code` (a module), `name`, `price_cents`, `is_placeholder`, `is_active` |
| `practice_subscription` | `id`, `tenant_id` (unique), `plan_id`, `amount_override_cents` (null = the plan's price), `currency`, `billing_email`, `nmi_vault_id`, `card_brand`, `card_last4`, `card_expires`, `nmi_subscription_id`, `status` (`not_billed / needs_card / active / past_due / canceled`), `first_charge_on`, `current_period_end`, timestamps |
| `practice_subscription_addon` | `id`, `tenant_id`, `subscription_id`, `addon_id`, `added_at`, `charged_from` (the next period's start, D4), `removed_at` |
| `practice_invoice` | `id`, `tenant_id`, `number`, `period_start`, `period_end`, `subtotal_cents`, `tax_cents`, `total_cents`, `amount_paid_cents`, `status` (`open / paid / void / refunded`), `issued_at`, `due_at`, `paid_at`, `nmi_transaction_id`, `pdf_id` → `stored_file` |
| `practice_invoice_line` | `id`, `tenant_id`, `invoice_id`, `position`, `description`, `amount_cents`, `addon_id` (null for the base) |
| `nmi_event` *(platform)* | `id`, `event_id` (unique with the account), `account` (`platform` or a practice id), `type`, `reference`, `received_at`, `processed_at`, `outcome`, `error`. **No card data and no body beyond what is listed.** |
| `tenant` (add) | `status` gains **`suspended`**; `suspended_at`, `suspension_reason` |

### 5.2 Client invoicing

| Table | Columns |
|---|---|
| `payment_account` | `id`, `tenant_id` (unique), `security_key_id`, `tokenization_key_id`, `webhook_key_id` → `tenant_secret`, `webhook_address` (unique, opaque), `is_ready`, `checked_at` |
| `client_invoice` | `id`, `tenant_id`, `kind` (`one_off / recurring / contact`), `client_company_id` (null for `contact`), `contact_id`, `schedule_id` (null), `number` (unique per practice), `issue_date`, `due_date`, `status` (`draft / sent / paid / partially_paid / void`), `subtotal_cents`, `tax_cents`, `total_cents`, `balance_cents`, `currency`, `notes`, `terms`, `pay_token_hash`, `nmi_invoice_id`, `pdf_id`, `outbox_message_id`, `created_by_id`, `sent_at`, `voided_at` |
| `client_invoice_line` | `id`, `tenant_id`, `invoice_id`, `position`, `description`, `quantity` (numeric 10,2), `unit_price_cents`, `amount_cents`, `project_id` (null), `goal_id` (null) |
| `client_invoice_schedule` | `id`, `tenant_id`, `client_company_id`, `day_of_month`, `next_on`, `lines` (the template), `notes`, `terms`, `is_active`, `ends_on` |
| `client_payment` | `id`, `tenant_id`, `invoice_id`, `amount_cents`, `paid_on`, `method` (`card / ach / check / wire / other`), `reference`, `nmi_transaction_id` (unique per practice), `recorded_by_id` (null when from NMI) |
| `invoice_number_sequence` | `tenant_id` (unique), `prefix`, `next_value`: advanced in the transaction that sends |

A constraint holds `client_company_id` null exactly when `kind = contact`.
Every migration is shown as SQL first, as the rule requires.

---

## 6. Build phases, and tests

| Phase | What | Stops for |
|---|---|---|
| **0. Prove NMI** | A1–A8 run in NMI's sandbox with test keys the owner provides: `scripts/nmi_sandbox_check.py` and a short written result per point. **No product code.** It reads `NMI_SANDBOX_SECURITY_KEY`, `NMI_SANDBOX_TOKENIZATION_KEY` and `NMI_SANDBOX_WEBHOOK_KEY` from the laptop's `.env`, and never the live names. A5 and A8 need an address NMI can reach, which the laptop is not: see the note under this table. | The owner reads the results; N2 and N3 are settled on what was found |
| **1. Subscriptions** | The adapter and its fake; plans and add-ons; card on file; the monthly charge and its invoice; Pay now; the 30-day flag, Suspend and the automatic lift; Settings → Billing; the Practices columns | The owner |
| **2. Client invoicing** | Connecting a practice's account; one-off, recurring and to-a-contact invoices; the PDF and the approved send; the pay link (N3); paid by NMI and by hand; the portal view | The owner |

No release until the owner says so.

**Webhooks in Phase 0.** NMI can only post to a public address. Two ways to
see a real delivery, neither of them product code: a request-capture service
the owner opens for an hour (it shows the headers and the raw body, which is
all A5 needs), or a tunnel to the laptop. Which one is the owner's choice when
the keys arrive; the other six points do not wait on it.

| Family | Tests |
|---|---|
| **Practice isolation** | Every new practice-scoped table joins the registry. Practice A never sees B's invoices, payments, schedules, keys or subscription. A webhook on A's address signed with B's key is refused. A webhook for a reference that is not A's changes nothing. **A payment to Executives Now as a practice never marks a subscription invoice paid, and the reverse, on the shared account.** The platform never reads a `tenant_secret`. |
| **Role boundaries** | The matrix of §3.5, row by row: an associate only for assigned client companies and never a send; an assistant 403 on every billing and invoicing route; a client team member sees their own company's invoices and nothing of another company's; a contact invoice appears in no portal. The platform owner reads subscription status and never a client invoice. |
| NMI | A bad signature is refused. An event is processed once. Polling finds a payment the webhook missed, and marks it once when both arrive. No key, card number or full webhook body is ever written to a log or a row. |
| Subscriptions | No charge before a card, and none before the next 1st. A receipt with the PDF for every successful charge, and none for a failed one. $20.00 by default; an override applies from the next period; an add-on added mid-month is not charged until the next period. Flagged at 30 days and not suspended by itself. A suspended practice's staff see only the billing screen, its jobs stop, no row changes. Paying lifts it. |
| Invoices | Numbers never skip or repeat under concurrency. Totals are integer cents. A sent invoice is unchanged except by void. A schedule makes a draft and sends nothing. Sending is an approved Outbox message with the PDF. |

---

## 7. Decisions made by the owner, 2026-10-08

| # | Question | Decided |
|---|---|---|
| — | Processor | **NMI everywhere; no Stripe.** |
| D1 | Trial for Beta at cost | **None.** |
| D2 | Suspension after 30 days unpaid | **Flagged; the owner presses Suspend.** |
| D3 | Lifting a suspension | **Automatic when paid.** |
| D4 | A change of monthly amount | **Next period, no part-month.** The rest of the first month of a newly added module is included, and the screen and the agreement say so. |
| D5 | Sales tax | **None in Beta. On at release, for Beta practices too.** |
| D6 | Processors | **NMI only**, for subscriptions and for client invoicing. QuickBooks is a later accounting connection, never a processor. |
| D7 | Kinds of invoice | **Platform to practice (subscription); practice to client, recurring and one-off; one-off to any contact.** Associates: draft for assigned client companies, the practice owner approves every send; assistants nothing. A contact invoice goes by email only. |
| D8 | Who sees invoices | **Client owners and client team members both see and download their company's.** The practice side sees and downloads everything (an associate within assigned client companies). |
| D9 | Pricing | **"Beta at cost" is $20 a month by default, adjustable per practice by the owner.** Released pricing is a base rate plus per-module add-ons, set later; plans and add-ons are modeled now with placeholder prices. |
| D10 | Payments through the platform | **Never.** Every practice connects its own NMI account. The platform's charges run on Noble Rose LLC's account, descriptor "Execs NOW HQ". |

---

## 8. Decisions this re-spec needed, answered by the owner 2026-10-08

| # | Question | Recommendation | Owner |
|---|---|---|---|
| **N1** | **The agreement.** Clause 3 said direct cost "invoiced monthly", paid "within 15 days", which a card charged automatically is not. | The owner writes or approves the clause. | **His wording, as `docs/legal/beta_agreement_v2.md`; every practice re-accepts.** The clause governs this spec: charged on the 1st, no part-month, a receipt for every charge. **The app still shows v1.** It moves to v2 in the same release as subscriptions, because v2 describes a card on file that the app cannot take until then. |
| **N2** | Who runs the monthly charge: NMI's recurring subscription, or this app's own daily job. | NMI's recurring, if Phase 0 shows its amount can be changed and its failures seen within the hour; otherwise the app's own job. | **As recommended.** |
| **N3** | The pay link for a client invoice: (a) NMI's hosted invoice, or (b) a pay page in this app with NMI's card fields. | (a) if Phase 0 shows NMI's own email can be turned off; otherwise (b). | **As recommended.** |
| **N4** | Recurring client invoices: a draft each period that a person approves, or also charging a stored card unattended. | Drafts only in the first build. | **As recommended.** |
| N5 | Can a client owner switch off a client team member's view of the company's invoices? | No switch in the first build. | **As recommended.** |
| N6 | Does an add-on also switch its module on and off, or only price it? | Price and record only, for now. | **As recommended.** |
| N7 | Where sales tax rates come from at release. | Decide at release; the tax line exists now, at zero. | **As recommended.** |
| N8 | Sandbox keys for Phase 0. | The owner provides them. | **He is getting them.** `NMI_SANDBOX_SECURITY_KEY`, `NMI_SANDBOX_TOKENIZATION_KEY`, `NMI_SANDBOX_WEBHOOK_KEY`, in the laptop's `.env`. |
| N9 | Which PCI self-assessment applies. | Ask NMI or the acquiring bank. | **He is asking NMI. Assume SAQ A for the design.** |

**Order:** Phase 0, then stop and report what the sandbox showed; then
subscriptions; then client invoicing; stopping after each.
