# P4 — Billing: PRD section and data model

**Practices beta program, phase 4 · spec only, no code · 2026-10-03**

Three separate flows of money, kept separate in the code and in this document:

| | Who pays whom | Through | Section |
|---|---|---|---|
| **A. Practice subscriptions** | a practice pays the platform (Noble Rose LLC) | the platform's Stripe account | §1 |
| **B. Client invoicing** | a client pays its practice | the **practice's own** processor | §2 |
| **C. Collect through the platform** (optional) | a client pays its practice, and the platform takes a fee | Stripe Connect | §3 |

Nothing here is built until you approve it. Decisions are **D1–D10** in §6.

---

## 1. Practice subscriptions (platform → practice)

### 1.1 What it does

- **Plans.** Each plan has a name, a price, a billing interval (monthly) and a
  trial length. Beta has **one plan, "Beta at cost"**, whose monthly amount is
  **set by you per practice**: your direct cost of hosting and database for
  that practice, with no markup (agreement, clause 3). Released plans are
  ordinary fixed-price plans, added later without schema change.
- **A trial** is days before the first invoice. Beta: none by default (**D1**).
- **Invoices are emailed by Stripe** to the practice's billing email
  (`collection_method = send_invoice`, **due in 15 days**: agreement clause 3).
  The invoice carries Stripe's hosted payment page, where the practice owner
  pays by card or bank transfer. The app never sees card details.
- **Suspension (agreement clause 3).** An invoice unpaid **30 days after it was
  issued** makes the practice **eligible for suspension**. The agreement says
  "we may suspend", so the app **flags it and you decide** (**D2**). The
  Practices screen shows "Overdue 30+ days: suspend?"; nothing suspends by
  itself.
- **Suspended** means the practice's staff see one screen ("Your practice is
  suspended until the invoice is paid", with the pay link). Clients see
  nothing new, and the practice's scheduled jobs and sends stop. **No data is
  touched.** Paying lifts it: on Stripe's `invoice.paid` the app flags the
  practice as reinstatable. Lifting is automatic or yours (**D3**).
- **The practice owner sees** Settings → Billing: plan, monthly amount, next
  invoice date, every invoice with its status and pay link. Associates,
  assistants and clients don't (`CLAUDE.md`: financials are the practice
  owner's).
- **You see**, in the Practices area: each practice's plan, amount, status
  (trialing / active / past due / suspended) and the date of the oldest unpaid
  invoice. Billing data is the platform's own record of its customers, not
  data inside a practice, so it sits beside the totals P2 already shows.

### 1.2 How it maps to Stripe

| App | Stripe |
|---|---|
| A practice | a **Customer** (email = the practice's billing email; metadata `practice_id`) |
| "Beta at cost" for one practice | a **Price** on a shared Product, `unit_amount` = your figure; a new figure is a new Price, applied from the next period (Stripe prices are immutable) |
| The subscription | a **Subscription**, `collection_method = send_invoice`, `days_until_due = 15`, `trial_period_days` from the plan |
| An invoice | a Stripe **Invoice**; mirrored in the app for display and the 30-day check |
| What the app learns | **webhooks** at `/api/stripe/webhook`, signature-verified: `invoice.finalized`, `invoice.paid`, `invoice.payment_failed`, `invoice.marked_uncollectible`, `customer.subscription.updated/deleted` |

Secrets: `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`, in env only. Every
webhook is recorded once by its event id (idempotent; Stripe retries). A
missed webhook is caught by a **daily reconciliation** that re-reads open
invoices from Stripe.

### 1.3 Edge cases settled in the spec

- **Changing a practice's monthly amount** takes effect at the next period, no
  proration (**D4**).
- **Archiving** a practice (P2) cancels its subscription at period end. An
  unarchive restarts it.
- **Your own practice** is not billed.
- **Refunds and credits** are done in the Stripe dashboard, and the app shows
  whatever Stripe says. Beta has no refund UI.
- **Tax:** not collected in Beta (at-cost, B2B, US). **D5** if that changes:
  Stripe Tax.

---

## 2. Client invoicing (practice → client), the finance module

This is the "invoicing" item in `CLAUDE.md`'s post-Beta order: a PDF invoice
by email with an embedded payment link from **the practice's own processor**,
and no in-app payment processing.

### 2.1 What it does

- **Invoices** belong to a client company: number, issue date, due date
  (default net 15, editable), lines, subtotal, tax, total, notes, terms.
  **Status:** draft → sent → paid / void. Numbers run per practice
  (`INV-0001`), prefix editable.
- **Lines** carry a description, quantity, unit price and amount, and
  optionally a link to the project or goal they bill for.
- **Sending is an Outbox message**, approved like any client email (review
  queues over automation). It has the PDF attached (WeasyPrint, practice
  branding from P1) and a **Pay now** button to the practice's processor.
- **The practice's processor** (Settings → Payments), one per practice:

  | Kind | How the pay link is made | Paid status |
  |---|---|---|
  | **Payment link** (Beta default) | a URL the practice pastes, with `{invoice}` and `{amount}` placeholders | marked paid by hand |
  | QuickBooks Online | the QBO invoice's own pay link, via the QBO API | read back from QBO (with the QBO connector) |
  | Authorize.Net | Accept Hosted payment page per invoice | webhook |
  | NMI | Collect Checkout / payment link per invoice | webhook |
  | Through the platform | §3 | Stripe webhook |

  Beta ships **Payment link** only (**D6**). The others follow, one at a
  time, with the connectors.
- **Marking paid** records the date, amount, method and a reference. Partial
  payments are allowed, and the invoice shows the balance.
- **Who:** the practice owner sees and does everything. An associate sees and
  drafts invoices **only for client companies they're assigned to**, and can't
  send without the practice owner's approval (**D7**). Assistants: none.
  Clients: the client owner sees their company's invoices and pay links in the
  portal (**D8**); a client team member: none.
- **Reminders:** an approved reminder draft when an invoice passes its due
  date, in the review queue, never sent automatically.

### 2.2 What it is not

No ledger, no accounts receivable aging beyond "open / overdue", no QuickBooks
sync in P4. Those belong to the basic-financials module that follows.

---

## 3. Collect through the platform (optional)

For a practice without a processor, or one that wants payments simple.

- **Stripe Connect, Express accounts.** The practice completes Stripe's own
  onboarding (identity, bank account; Stripe handles KYC and 1099-K). The
  platform never holds the practice's money.
- **Each invoice's Pay now** opens a Stripe Checkout session on the practice's
  connected account (a **direct charge**), with `application_fee_amount` =
  your **platform fee** (**D9**: a percentage, a fixed amount, or both). The
  client pays the practice; the fee goes to the platform's account; Stripe's
  own processing fee comes out of the practice's side.
- **Paid** comes back by webhook (`checkout.session.completed`,
  `charge.refunded`, `charge.dispute.created`) to the platform's Connect
  endpoint, and the invoice updates itself.
- **Refunds and disputes** are handled in the practice's Stripe Express
  dashboard. The app records what Stripe reports.
- **What it costs you to offer:** the platform becomes a Connect platform.
  Stripe's Connect terms apply, and the fee and how disputes are handled must
  go in the released product's terms. **Not in Beta** (**D10**).

---

## 4. Data model

All new tables are practice-scoped (`tenant_id`, fail-closed manager)
**except** `billing_plan` and `stripe_event`, which are platform tables.
Platform reads of practice billing rows go through one module
(`apps/platform/billing.py`), like `stats.py` and `feedback.py`.

### 4.1 Subscriptions (§1)

| Table | Columns |
|---|---|
| `billing_plan` *(platform)* | `id`, `code` (`beta_at_cost`, …), `name`, `interval` (`month`), `price_cents` (null = set per practice), `trial_days`, `stripe_product_id`, `is_active` |
| `practice_subscription` | `id`, `tenant_id` (unique), `plan_id`, `monthly_amount_cents`, `currency` (`usd`), `billing_email`, `stripe_customer_id`, `stripe_subscription_id`, `stripe_price_id`, `status` (`trialing / active / past_due / canceled / not_billed`), `trial_ends_at`, `current_period_end`, `created_at`, `updated_at` |
| `practice_invoice` | `id`, `tenant_id`, `stripe_invoice_id` (unique), `number`, `amount_due_cents`, `amount_paid_cents`, `status` (`draft / open / paid / uncollectible / void`), `issued_at`, `due_at`, `paid_at`, `hosted_invoice_url`, `pdf_url` |
| `stripe_event` *(platform)* | `id`, `stripe_event_id` (unique), `type`, `received_at`, `processed_at`, `error` |
| `tenant` (add) | `status` gains **`suspended`**; `suspended_at`, `suspension_reason` |

### 4.2 Client invoicing (§2)

| Table | Columns |
|---|---|
| `payment_processor` | `id`, `tenant_id` (unique), `kind` (`link / qbo / authnet / nmi / platform`), `link_template`, `secret_id` → `tenant_secret` (API credentials, encrypted), `stripe_account_id` (§3), `platform_fee_bps`, `platform_fee_fixed_cents`, `is_ready` |
| `client_invoice` | `id`, `tenant_id`, `client_company_id`, `number` (unique per practice), `issue_date`, `due_date`, `status` (`draft / sent / paid / partially_paid / void`), `subtotal_cents`, `tax_cents`, `total_cents`, `balance_cents`, `currency`, `notes`, `terms`, `pay_url`, `pdf_id` → `stored_file`, `outbox_message_id`, `created_by_id`, `sent_at`, `voided_at` |
| `client_invoice_line` | `id`, `tenant_id`, `invoice_id`, `position`, `description`, `quantity` (numeric 10,2), `unit_price_cents`, `amount_cents`, `project_id` (null), `goal_id` (null) |
| `client_payment` | `id`, `tenant_id`, `invoice_id`, `amount_cents`, `paid_on`, `method` (`card / ach / check / wire / other / platform`), `reference`, `external_id` (processor or Stripe id, unique per practice), `fee_cents` (§3), `recorded_by_id` (null when from a webhook) |
| `invoice_number_sequence` | `tenant_id` (unique), `prefix`, `next_value`: advanced in the same transaction that sends, so numbers never skip or repeat |

Money is integer cents throughout; amounts are never floats.

---

## 5. Tests (written with the build)

| Family | Tests |
|---|---|
| **Practice isolation** | Every new practice-scoped table joins the registry. Practice A never sees B's invoices, payments, processor or subscription. The Stripe webhook resolves the practice from Stripe's ids, never from the request. |
| **Role boundaries** | Settings → Billing and client invoicing: practice owner only, associates only for assigned client companies (D7), assistants 403, client team members 403, client owners only their own company's invoices (D8). The platform owner reads subscription status, never client invoices. |
| Stripe | Bad webhook signature → 400. A repeated event is processed once. Reconciliation finds a missed `invoice.paid`. Prices are never edited, only replaced. |
| Suspension | Flagged at 30 days after issue, not suspended by itself. A suspended practice's staff see only the billing screen; its jobs stop; no row changes. Payment lifts it per D3. |
| Invoices | Numbers never skip or repeat under concurrency. Totals are integer cents. A sent invoice is immutable except through void. Sending is an approved Outbox message with the PDF. |

---

## 6. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| D1 | Trial length for Beta at cost | None: the first invoice covers the first month |
| D2 | Suspension after 30 days unpaid | Flagged; you press Suspend |
| D3 | Lifting a suspension when paid | Automatic on `invoice.paid` |
| D4 | Changing a practice's monthly amount | Next period, no proration |
| D5 | Sales tax on subscriptions | Not in Beta; Stripe Tax at release if needed |
| D6 | Processors in the first client-invoicing build | Payment link only; QBO next |
| D7 | Associates and invoices | Draft for assigned clients; practice owner approves the send |
| D8 | Clients see invoices in the portal | Client owner only |
| D9 | Platform fee for collect-through-platform | Your call: a percentage, a fixed fee, or both |
| D10 | Collect through the platform in Beta | No: after release, with terms that cover it |

**Build order once approved:** subscriptions (§1), then client invoicing with
payment links (§2), then QBO links, then Connect (§3).
