# P4 — Billing on NMI: PRD section and data model

**Practices beta program, phase 4 · re-specified 2026-10-08, and for NMI's v5 API on 2026-10-21 · part 1 built**

**This replaces the Stripe version of 2026-10-03** (in git history at
`fa79a2a`). The owner decided D1–D10 on 2026-10-08 and changed the processor:
**NMI everywhere, no Stripe.** His decisions are recorded in §7, and his
answers to N1–N9 the same day in §8. **Next is Phase 0 (§6): prove NMI in its
sandbox, with no product code.** Nothing here is built.

**Client invoicing is being built first without a processor**
(`docs/p4a_client_invoicing.md`, 2026-10-08), while NMI's sandbox is not
available. Phase 2 here then adds NMI to those invoices (connecting a
practice's account, the pay link, paid by NMI) and makes no second invoice
model: where §3 and §5.2 differ from that document, that document is the
newer one.

**2026-10-21: NMI's v5 REST API and the Payment Component.** Bryan set the
requirements for the processor layer and answered five choices the same day
(§10). Where this document and §10 differ, §10 holds; the sections below are
brought up to date where they were wrong. In short: card fields are NMI's
**Payment Component** (not Collect.js) and every call is **v5 REST** (not the
classic `transact.php`, which does not accept the component's tokens); the
platform's keys are `NMI_ENVIRONMENT`, `NMI_PUBLIC_TOKENIZATION_KEY` and
`NMI_PRIVATE_API_KEY`; **no webhooks** (a daily read-back instead); the
**app's own job** charges subscriptions; the pay link is **this app's own
page** (N3 (b)); **auto-pay** with the client's consent replaces N4; and the
build is five parts (§6). Phase 0's raw-card script is deleted: a charge on
typed card numbers proves nothing about the token path.

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

## 0. What was proved about NMI, 2026-10-21

Run against NMI's sandbox with the platform's sandbox keys, tokens made by
the Payment Component in headless Chrome. Where NMI's documentation
contradicted itself or the sandbox, **the sandbox is what the code follows**.

| # | Proved | How |
|---|---|---|
| A1 | The **Payment Component** (`@nmipayments/nmi-pay` 1.1.1) shows NMI's own card fields (frames from `secure.nmi.com`) and hands the page a one-time `payment_token`. The public tokenization key selects sandbox or live; the component has no environment setting. | Four tokens made in headless Chrome |
| A2 | **Customer Vault from a token:** `POST /api/v5/customers` with `billing: {first_name, last_name, payment_details: {payment_token}}`. The guides' `billing_address` form is refused. The answer has the record's id and the card masked (`411111******1111`, `card_exp` MMYY); no brand. A vault charge is `customer_vault: {id}` at the top of a sale; `payment_details.customer_vault_id` is refused. `DELETE /customers/{id}` answers 204. | Sandbox |
| A3 | NMI's recurring subscriptions: **not used** (§10, choice 2). | — |
| A4 | NMI's hosted invoice: **not used** (N3 is (b)). | — |
| A5, A8 | Webhooks: **not used** (§10, choice 5). | — |
| A6 | **Read back:** `GET /api/v5/payments/{id}` returns the transaction with `merchant_defined_fields`. 401 for a bad or a public key, 404 for an unknown id, so it is also the connection test. | Sandbox |
| A9 | **Our reference:** `merchant_defined_fields: {"field_1": "<ours>"}` is accepted, returned on the sale, and carried onto its refunds. | Sandbox |
| A10 | **Unknown fields are refused** (422, `extraParameters`). A decline is HTTP 200 with `response` "2" (`response_code` 200); validation errors are 422, not the documented 400. Amounts are dollars; a string `"12.34"` and a number both work. | Sandbox |
| A11 | **Refunds:** `POST /api/v5/payments/{id}/refund` with `{"amount": "2.00"}` refunds part of a sale **that has not settled** (NMI's reference page says only settled ones; the sandbox did it). More than what is left is refused (400). No void is used. **Proved in the sandbox only**; a live account's behavior is checked at the first live refund. | Sandbox |
| A12 | **Duplicates:** the same card for the same amount again within minutes is refused, HTTP 400 `error_code: E_DUPLICATE`, `"Duplicate transaction"`; nothing is charged. | Sandbox, 10/21 |
| A13 | **Finding a lost sale.** v5 has no search (its reference lists only get-by-id). The classic **Query API** (`query.php`, form-posted, XML back), with the same private key as `security_key`, finds a transaction by `order_id`; a sandbox account must use `sandbox.nmi.com`. So every sale also carries our reference as `order_details.id`, and the lookup is read-only: it never charges. **The one use of a classic endpoint**, and only because v5 cannot do it. | Sandbox, 10/21, through the lookup's own code |
| A7 | Vault and the v5 API on a **live** account: whether every practice's account has them switched on is still to be checked per account; the connection test proves the key, not the services. | Open |

## 1. The processor layer

### 1.1 One adapter

`apps/billing/gateway/` is the only code that talks to NMI (`nmi.py`, the v5
client; `stub.py`, its stand-in). Everything else calls `gateway()` with an
**account** and never with a key:

| Call | What it does at NMI |
|---|---|
| `check_connection(account)` | One authenticated read; proves the private key |
| `sale(account, amount_cents, reference, payment_token= or vault_id=)` | One charge, carrying our reference in `merchant_defined_fields.field_1` |
| `refund(account, transaction_id, amount_cents)` | A whole or partial refund; no void. Not called from any screen in the first build |
| `get_transaction(account, id)` | The transaction, for the daily read-back |
| `vault_add(account, payment_token, billing)`, `vault_delete` | A card stored or removed; returns the vault id, last four and expiry |

- **The guard.** Nothing reaches NMI unless `NMI_LIVE_CALLS` is on, and
  never under the test runner, whatever the setting; otherwise `gateway()` is
  the stub. No method has a card parameter, and a body carrying any card or
  bank field name, at any depth, is refused before it is sent.
- **Keys** go only in the `Authorization` header. An account does not print
  them, and an error from NMI is scrubbed of them before anyone sees it. Log
  lines carry the route shape, the status and NMI's `ref_id`, never a body.
- **Money is integer cents** in this app and dollars only at NMI's edge.
- **The only backend probe** is `manage.py nmi_check` (connectivity and the
  private key). The token path is proved by `scripts/nmi_token_proof.py`:
  headless Chrome types NMI's test card into NMI's own fields on a
  laptop-and-sandbox-only page, and the server runs a sale, a partial refund,
  the read-back, a vault record, a sale on it, its refund and the delete.

### 1.2 Two kinds of account, kept apart

| | The platform account | A practice's account |
|---|---|---|
| Whose | Noble Rose LLC | The practice's own |
| Keys kept in | Environment only: `NMI_ENVIRONMENT`, `NMI_PUBLIC_TOKENIZATION_KEY`, `NMI_PRIVATE_API_KEY` (live only in production; refused on localhost) | `tenant_secret` (`nmi_private_key`, `nmi_public_key`), both encrypted, write-only (as the Anthropic key is), with a sandbox/live switch on `payment_account` |
| Entered by | The owner, in Railway | The practice owner, in Settings → Billing, tested with NMI before saving |
| Used by | §2 only (`gateway.platform_account()`) | §3 only, and only for that practice (`payment_accounts.practice_account`) |
| Statement descriptor | "Execs NOW HQ", set by the owner in NMI | The practice's, set by the practice in NMI |

**The platform account is also the account Executives Now uses as a practice**
(same legal entity). The code still treats them as two accounts: the platform
side reads the environment and never a `tenant_secret`; the Executives Now
practice enters the same keys in Settings → Billing like any other practice.
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
  whether by Pay now, by the monthly charge or by the daily read-back.
- **Tax (D5).** None in Beta. Every invoice has a tax line that is zero. At
  release tax is on for every practice, the Beta ones included. NMI does not
  work out sales tax, so where the rates come from is N7.
- **The owner's own practice** is not billed.
- **Archiving** a practice cancels its subscription at NMI at once and makes
  no further charge. Unarchiving starts a new one.
- **Refunds and credits** are made in NMI's portal. The reconciliation
  records a refund against the invoice; the app has no refund button.

### 2.3 How it maps to NMI

**The app's own job charges each practice (§10, choice 2; N2's fallback).**
On the 1st it makes the period's invoice, then one `sale` against the
practice's vault record on the platform account, carrying the invoice's
reference, and knows the result at once. NMI's recurring subscriptions are
not used, so A3 never matters.

| App | NMI, on the platform account |
|---|---|
| A practice's card | A Customer Vault record (A2) |
| A monthly charge | One `sale` on the vault record, by the app's job on the 1st, carrying the invoice's reference |
| A change of amount | Nothing at NMI: the next invoice has the new amount |
| Pay now | One `sale` against the vault, carrying the open invoice's reference |

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

**Settings → Billing**, practice owner only (built in part 1). Two keys: the
private API key and the public tokenization key, each stored encrypted and
never shown again, and a **sandbox/live switch** (live accepted only on the
production app). New keys, or a new environment, are tested with one
authenticated read before anything is saved; on a refusal nothing changes.
**Test connection** repeats it on the stored keys and records the result. The
test proves the private key; the public key is proved the first time a card
form loads with it. No webhook key (§4).

The card's **pricing program** (interchange-plus or dual pricing) is set by
the platform owner on the Practices screen when the practice is set up, and
shown read-only here (§10, choice 1). Only the field exists: the display
rules for dual pricing come later from the processor.

**QuickBooks is not a processor (D6).** It is a later accounting connection
for practices that keep books for their clients, and takes no payment.

### 3.4 The pay link (N3: (b))

**A pay page in this app with NMI's own card fields**, two ways in: **Pay**
on the invoice in the portal (part 2), and a **signed link** in the invoice
email and on its PDF for paying without signing in (part 3). The link's
token is random and stored only as a hash; it stops working when the invoice
is voided. The charge is made **with the practice's own key on the
practice's own account**; the page never routes money through the platform.
**Card payments are the full balance only** (§10, choice 4); a part payment
is still recorded by hand.

**Auto-pay (part 4; replaces N4).** A signed-in client owner can save a card
(the practice's vault) and consent to auto-pay; the consent's wording,
version, time and person are kept, and the client can revoke it. The
practice still approves every send. An invoice sent after consent is charged
**on its due date** (§10, choice 3), until consent is revoked.

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

**No webhooks (§10, choice 5).** Every charge is made by this app, so the
sale's own answer says paid or declined at once. A **daily read-back** per
account (`get_transaction` on the last several days' charges, by our
reference) finds what happened in NMI's portal since: a refund or a
chargeback is recorded on the invoice and shown to the practice owner, a day
late at most. A charge whose answer was lost (a timeout) is left "unknown"
and settled by the same read-back, so nothing is recorded twice.

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
| `payment_account` *(built, part 1)* | `id`, `tenant_id` (unique), `environment` (`sandbox / live`), `checked_at`, `check_ok`, `check_detail`, `checked_by_id`. The keys are `tenant_secret` rows of kinds `nmi_private_key` and `nmi_public_key`. No webhook columns |
| `tenant` (add, built) | `pricing_program` (`'' / interchange_plus / dual_pricing`), set on the Practices screen |
| `client_invoice` | `id`, `tenant_id`, `kind` (`one_off / recurring / contact`), `client_company_id` (null for `contact`), `contact_id`, `schedule_id` (null), `number` (unique per practice), `issue_date`, `due_date`, `status` (`draft / sent / paid / partially_paid / void`), `subtotal_cents`, `tax_cents`, `total_cents`, `balance_cents`, `currency`, `notes`, `terms`, `pay_token_hash`, `nmi_invoice_id`, `pdf_id`, `outbox_message_id`, `created_by_id`, `sent_at`, `voided_at` |
| `client_invoice_line` | `id`, `tenant_id`, `invoice_id`, `position`, `description`, `quantity` (numeric 10,2), `unit_price_cents`, `amount_cents`, `project_id` (null), `goal_id` (null) |
| `client_invoice_schedule` | `id`, `tenant_id`, `client_company_id`, `day_of_month`, `next_on`, `lines` (the template), `notes`, `terms`, `is_active`, `ends_on` |
| `client_payment` | `id`, `tenant_id`, `invoice_id`, `amount_cents`, `paid_on`, `method` (`card / ach / check / wire / other`), `reference`, `nmi_transaction_id` (unique per practice), `recorded_by_id` (null when from NMI) |
| `invoice_number_sequence` | `tenant_id` (unique), `prefix`, `next_value`: advanced in the transaction that sends |

A constraint holds `client_company_id` null exactly when `kind = contact`.
Every migration is shown as SQL first, as the rule requires.

---

## 6. Build parts, and tests

The 10/08 phases are replaced by five parts (2026-10-21), each stopping for
Bryan:

| Part | What | State |
|---|---|---|
| **1. Gateway and Settings → Billing** | The v5 client, its stub and the guard; the practice's two keys, the sandbox/live switch and the connection test; the pricing program on the Practices screen; `nmi_check`; the token proof | **Built 2026-10-21** |
| **2. Pay in the portal** | Pay on a sent or partly paid invoice for a client owner or client team member, when the practice's account is ready; "Test mode" on a sandbox account; NMI's component with the practice's public key, fetched at runtime; `payment_attempt` written with the invoice locked, one pending or unknown per invoice (a partial unique index); one sale on the practice's own key, never retried; the `ClientPayment` through `record_payment` (books included); NMI's decline text kept; a duplicate refused with a plain message; a lost answer "unknown" and settled by `billing.resolve_card_payments` every 10 minutes (A13); the receipt to whoever paid and the notice to the practice owner, both financial (hidden from assistants), neither able to undo a payment; nothing paid while acting as the client | **Built 2026-10-21** |
| **3. The signed pay link** | `/pay/<token>`, no sign-in: the practice, the number, the amount due, the due date, the PDF and the card form, nothing else; "Test mode" on a sandbox account; the practice found from the token; issued when the invoice is made ready (if the practice can take cards then; otherwise at its next send, so an invoice sent before links gets one when resent); the token an HMAC under the app's secret key of the invoice and the moment of issue, **only its hash stored** (`pay_token_hash`, unique), so it can be printed again on a resend without being kept; `pay_url` filled in memory for the PDF and never written; `{PayLink}` in the invoice email (kept unfilled in the invoice's stored wording, filled as the email is queued; a line holding it is left out with no link; wording without it gets the link added at the end) and in the template library (reads as nothing outside invoice emails); a 404, the same for each, for a wrong token, a voided invoice (its hash is cleared) or one not yet sent; Paid once paid; rate-limited per link (60 views, 10 card tries an hour) and per address (120 an hour); contact invoices pay this way (in no portal); the receipt goes to the invoice's address, the attempt is marked `via = link` | **Built 2026-10-21** |
| **4. Card on file and auto-pay** | `client_payment_method`: one card per company in the **practice's own** Customer Vault (vault id, environment, brand from the masked number's first digits since NMI names none, last four, expiry, who added it, removed when and by whom); saved only by a signed-in client owner in the portal (a client team member 403, practice staff 404, never by the pay link, never while acting); a new card replaces the old, which is deleted from the vault; removing the card turns auto-pay off. `autopay_consent`: who, when, the exact wording shown and its version (`2026-10-21`), address and browser; one standing per company; revocable by any client owner, the revocation kept. The practice still approves every send: an invoice whose email is queued while consent stands says "This invoice will be charged to the card ending NNNN on <date>" and is tied to that consent (`client_invoice.autopay_consent`). `billing.run_autopay`, daily at 9:00: charges the card on file on the due date for the balance while that consent stands and the invoice was sent after it; a failure leaves the invoice open, tells the client (`autopay_notice`) and the practice owner, and is tried once more on a later day, never a third; safe to run twice (never two tries in a day, never while one is in flight). The client is told once, 30 days before the card's last month ends | **Built 2026-10-21** |
| 5. Practice subscriptions | §2 on v5, charged by the app's job on the 1st; agreement v4 ships with it | Not started |

No release until the owner says so.

| Family | Tests |
|---|---|
| **Practice isolation** | Every new practice-scoped table joins the registry. Practice A never sees B's invoices, payments, schedules, keys or subscription. A charge for practice A is made only with A's key; a read-back for a reference that is not A's changes nothing. **A payment to Executives Now as a practice never marks a subscription invoice paid, and the reverse, on the shared account.** The platform never reads a `tenant_secret`. |
| **Role boundaries** | The matrix of §3.5, row by row: an associate only for assigned client companies and never a send; an assistant 403 on every billing and invoicing route; a client team member sees their own company's invoices and nothing of another company's; a contact invoice appears in no portal. The platform owner reads subscription status and never a client invoice. |
| NMI | Tests never reach NMI (the stub, always). No method takes a card field and no body carrying one is sent. The read-back marks a payment once, also after a lost answer. No key, card number or full NMI body is ever written to a log or a row. |
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
| **N1** | **The agreement.** Clause 3 said direct cost "invoiced monthly", paid "within 15 days", which a card charged automatically is not. | The owner writes or approves the clause. | **His wording, as `docs/legal/beta_agreement_v2.md`; every practice re-accepts.** The clause governs this spec: charged on the 1st, no part-month, a receipt for every charge. **The app still shows v1.** It moves to v2 in the same release as subscriptions, because v2 describes a card on file that the app cannot take until then. *(10/20: the app moved to v3, which is v1 plus clause 8 on personal finance; the subscriptions release ships v4, v3 with v2's clause 3.)* |
| **N2** | Who runs the monthly charge: NMI's recurring subscription, or this app's own daily job. | NMI's recurring, if Phase 0 shows its amount can be changed and its failures seen within the hour; otherwise the app's own job. | **As recommended.** |
| **N3** | The pay link for a client invoice: (a) NMI's hosted invoice, or (b) a pay page in this app with NMI's card fields. | (a) if Phase 0 shows NMI's own email can be turned off; otherwise (b). | **As recommended.** |
| **N4** | Recurring client invoices: a draft each period that a person approves, or also charging a stored card unattended. | Drafts only in the first build. | **As recommended.** |
| N5 | Can a client owner switch off a client team member's view of the company's invoices? | No switch in the first build. | **As recommended.** |
| N6 | Does an add-on also switch its module on and off, or only price it? | Price and record only, for now. | **As recommended.** |
| N7 | Where sales tax rates come from at release. | Decide at release; the tax line exists now, at zero. | **As recommended.** |
| N8 | Sandbox keys for Phase 0. | The owner provides them. | **He is getting them.** *(10/21: provided as `NMI_ENVIRONMENT`, `NMI_PUBLIC_TOKENIZATION_KEY`, `NMI_PRIVATE_API_KEY`; no webhook key.)* |
| N9 | Which PCI self-assessment applies. | Ask NMI or the acquiring bank. | **He is asking NMI. Assume SAQ A for the design.** |

**Order:** Phase 0, then stop and report what the sandbox showed; then
subscriptions; then client invoicing; stopping after each.

---

## 9. Heard on the 2026-10-12 call, not decided

Recorded as said. None of it changes §7 or §8 until Bryan decides; D9's "$20
a month by default" is the only figure here that is already a decision.

| What | Heard |
|---|---|
| During beta | **$20 a month** (as D9). |
| Beta practices after release, base | **$50 a month for life.** |
| Modules | **$25 or $50 a month each.** Which module is which is not said. |
| Portal seats | **25 included, then $10 a month for each further 25.** |

**Hard cost.** The platform's cost for a practice is a **share of hosting**.
AI and email are on the practice's own accounts (its Anthropic key, its own
mailbox), so they are not a platform cost and are not in the price.

Open, for when this is decided: whether "for life" covers modules or only the
base; what a released, non-beta practice pays as its base; and whether portal
seats are counted per practice or per client company (CLAUDE.md models a seat
count per client company).

---

## 10. Decisions, 2026-10-21

Bryan's requirements for the processor layer, and his answers to the five
choices of the plan, all "as recommended".

| # | Question | Decided |
|---|---|---|
| R1 | Card data | **Never touches the app.** NMI's Payment Component tokenizes in the browser; the public key reaches the page at runtime; the private key never reaches the frontend bundle. |
| R2 | Which API | **v5 REST** at `sandbox.nmi.com` or `secure.nmi.com` by `NMI_ENVIRONMENT`; the key in `Authorization`; the token under `payment_details.payment_token`; our id in `merchant_defined_fields`; refunds by the v5 route, partials allowed, no void. Never `transact.php`. |
| R3 | Card on file | **Customer Vault.** The app stores only the vault id and the last four. |
| R4 | The guard | Tests always run against a stub gateway; a real call needs an explicit setting (`NMI_LIVE_CALLS`); no backend method accepts raw card fields. |
| R5 | Proof | The only backend probe is connectivity and auth (`nmi_check`); the token path is proved end to end in headless Chrome against the sandbox with NMI's test card. |
| R6 | Keys | Each practice holds its own two keys, encrypted, under Settings → Billing with a sandbox/live switch and a connection test; the platform's come from the environment. |
| 1 | Who sets the pricing program | **The platform owner, on the Practices screen at setup**; read-only to the practice. |
| 2 | What charges subscriptions | **The app's own job on the 1st**, a sale on the vault. |
| 3 | Auto-pay | **On the due date, for invoices sent after consent, until revoked.** |
| 4 | Part payments by card | **No: the full balance only.** |
| 5 | Webhooks | **None; a daily read-back per account.** |

