# P4A — Client invoicing without a processor

**Spec for owner review · 2026-10-08 · no code yet**

Asked for by the owner on 2026-10-08, to build while NMI's sandbox is not
available. It is the invoicing half of `docs/p4_billing.md` §3 **with no
payment taken in the app**: a practice writes an invoice, sends it, and
records by hand that it was paid. The NMI pay link is a field that stays empty
until P4's client-invoicing phase fills it. Nothing here talks to NMI.

Already decided, and not asked again (P4 D7, D8 and the owner's answers of
2026-10-08): the three kinds of invoice; associates draft for assigned client
companies and the practice owner approves every send; assistants have nothing;
client owners and client team members both see and download their company's
invoices; an invoice to a contact goes by email only.

**What this needs from the owner is I1–I9 in §8.**

---

## 0. What the app has today that this uses

| Exists | Used for |
|---|---|
| The Outbox and the Sending queue (`OutboxMessage`, attachments, approval, the per-kind sender address in mail preferences) | Sending an invoice, with the PDF attached, after approval |
| `ClientAssignment` (which associate is assigned to which client company) | An associate's view of invoices |
| `StoredFile` and the private media bucket | The invoice PDF |
| WeasyPrint and the practice's branding (logo, colors, footer; P1) | The PDF |
| The client portal, with a client user bound to one company | Seeing and downloading invoices |
| `AuditEvent` | The trail on every change |
| Access matrix §13, written before any financial module existed | It says invoicing is the practice owner's alone. §5 here replaces rows 13.4 and 13.5's client columns, as the owner decided in P4. |

**One thing in today's app works against "assistants have no financials"**,
and this spec has to close it: an assistant can see the whole Outbox and the
send log (matrix 5.1, 5.9), and every sent email is threaded into the client's
shared history. An invoice email carries amounts. See §5.2 and I4.

---

## 1. What an invoice is

| Field | Rule |
|---|---|
| **Kind** | `one_off` (to a client company), `recurring` (a draft made by a schedule, §3), `contact` (to any one contact) |
| **Bill to** | A client company and a named recipient among its contacts; or, for `contact`, the contact. The name, company and address printed are **copied onto the invoice when it is made ready**, so a later edit to the contact changes no sent invoice. |
| **Number** | Per practice, `INV-0001` upward, prefix editable. §1.1. |
| **Dates** | Issue date (today by default); due date (issue date plus the practice's terms, net 15 by default; editable) |
| **Lines** | Description, quantity (two decimals), unit price, amount. Optionally the project or goal the line is for. At least one line; 50 at most. |
| **Totals** | Subtotal, tax (I5), total, paid so far, balance. Integer cents everywhere; never a float. US dollars only. |
| **Notes, terms** | Free text, printed. Defaults come from Settings → Invoices. |
| **How to pay** | The practice's own payment instructions, printed on every invoice (I6). With no processor this is the only way a client learns where to send money. |
| **Pay link** | Empty. Nothing prints or shows for it while it is empty. Filled by P4's NMI phase. |
| **Status** | `draft` → `ready` → `sent` → `partially_paid` → `paid`; or `void` from any numbered status. **Overdue is not a status**: it is "sent or partly paid, and past its due date", worked out when read, so it cannot go stale. |

### 1.1 Numbers

- A draft has **no number**. A draft that is thrown away never had one.
- The number is given **when the invoice is made ready to send**, in the same
  transaction, from the practice's own counter. From that moment the invoice
  keeps that number for good and **cannot be deleted, only voided**.
- So numbers never skip and never repeat: every number ever given belongs to
  an invoice that still exists, sent, paid or void.
- The practice owner can change the prefix, and can raise the next number
  (to carry on from an older system), never lower it.

### 1.2 What can change, and when

| Status | Can be edited | Can be deleted |
|---|---|---|
| Draft | Everything | Yes |
| Ready (numbered, waiting in the Sending queue) | Nothing. "Back to draft" reopens it, **keeping its number**; the waiting message is withdrawn. | No; void it |
| Sent and after | Nothing but payments and void. A mistake is corrected by voiding it and writing a new one. | No |

---

## 2. Writing, sending and the PDF

1. **Write** a draft: from the client company's page, from the invoices list,
   or (practice owner) for any contact.
2. **Make ready.** The invoice gets its number, its PDF is made and stored,
   and a message goes into the **Sending queue** as pending approval, with the
   PDF attached and the full email on screen. An associate's part ends here.
3. **The practice owner approves** in the Sending queue, as for any client
   email, or sends it back. Approving sends it and marks the invoice sent.
   For the practice owner's own invoice, see I3.
4. **Resend** (practice owner): the same PDF, to the same or another address
   at that company, through the Sending queue again. It makes no new invoice.

**The PDF** (WeasyPrint, the practice's logo, colors and footer): the
practice's name and address, "Invoice", number, dates, bill-to, the lines,
subtotal, tax, total, notes, terms and how to pay. It is **the document as
sent**: stored once and never regenerated, so what a client downloads next
year is what they were emailed. Payment status is shown beside it on screen,
not printed onto it. A void invoice's PDF is kept; the screens mark it void.

**The email** is short and the practice's own: a default subject and body in
Settings → Invoices with merge fields (`{Client}`, `{Number}`, `{Total}`,
`{Due date}`, `{Practice}`), editable per invoice before it is made ready.
It goes from the address the practice chose for this kind of message (I2).

**A contact invoice** is sent the same way and appears in no portal.

---

## 3. Recurring

A **schedule** belongs to a client company: the lines, notes and terms to
use, a day of the month (1 to 28), a first date, an optional last date, and
on or off.

- On its day a daily job writes **a draft**, dated that day, marked "from the
  schedule", and moves the schedule on a month. **It numbers nothing and
  sends nothing.** A person opens the draft, changes what needs changing and
  makes it ready, and the practice owner approves the send as for any other.
- The dashboard's "Waiting for approval" panel counts drafts made by a
  schedule, for the practice owner and the assigned associate.
- A schedule whose client company is archived stops. A day missed (the worker
  was down) is made up once, not once per missed day.
- An associate makes and edits schedules for assigned client companies.

---

## 4. Paid, part paid, void, overdue

- **Record a payment** (practice owner): date, amount, method (card, bank
  transfer, check, wire, other), reference, a note. Payments add up: less than
  the total is partly paid, the total is paid. More than the balance is
  refused.
- **Remove a payment** recorded in error (practice owner), with a reason. The
  row is kept, marked removed, and no longer counts.
- **Void** (practice owner), with a reason. Refused while the invoice has a
  payment that still counts: remove the payment first, so money received is
  never hidden by a void.
- **Every one of these writes an audit event**: who, when, what the invoice
  was before and after, and the reason. The invoice's own page shows that
  history in order.
- **Overdue** shows as a flag on the invoice, in the list, on the client
  company's page and in the portal ("Due 3 October"). Nothing is sent because
  an invoice is overdue (I8).

**The practice's invoice list:** every invoice the person may see, newest
first; filters for status (with "overdue"), client company and dates; and
totals for what is listed: invoiced, paid, outstanding, and overdue. The list
and its totals download as CSV.

---

## 5. Who sees and does what

### 5.1 The matrix (replaces rows 13.4 and the client columns of 13.5)

| # | Capability | Practice owner | Associate | Assistant | Client owner | Client team member |
|---|---|---|---|---|---|---|
| 13.4a | See and download invoices, and the list with its totals | ✅ every one | 🔸 assigned client companies | ❌ | ✅ their company's, sent and after | ✅ their company's, sent and after |
| 13.4b | Write and edit a draft; make it ready; schedules | ✅ | 🔸 assigned client companies | ❌ | — | — |
| 13.4c | Approve a send; resend | ✅ | ❌ | ❌ | — | — |
| 13.4d | Record or remove a payment; void | ✅ | ❌ | ❌ | — | — |
| 13.4e | Invoices to a contact (not a client company) | ✅ | ❌ | ❌ | — | — |
| 13.4f | Settings → Invoices (prefix, next number, terms, how to pay, the email) | ✅ | ❌ | ❌ | — | — |

- **An associate's totals** are the totals of what they may see, never the
  practice's.
- **A client user** sees their own company's invoices only: number, dates,
  total, balance, status, the overdue flag and the PDF. Never a draft, never a
  ready one that has not been sent, never the practice's notes about payment,
  never another company's. A void invoice they were sent stays listed, marked
  void (I7).
- **The platform owner** sees none of it.

### 5.2 Keeping invoices away from an assistant, everywhere

"No financials" has to hold in every place an invoice could surface, not only
on the invoice screens. Each of these is a test:

| Where | Rule |
|---|---|
| Invoice screens and every invoicing route | 403 |
| **The Outbox, the Sending queue and the send log** | A message that is an invoice is left out for an assistant: not listed, not counted, 404 by id |
| **A client's shared email history** | The sent invoice email is left out for an assistant. Everyone else who may see invoices for that company sees it. |
| Global search | No invoice, and no invoice email, in an assistant's results |
| The dashboard | No invoice count or figure in an assistant's panels |
| The client company's page | No invoices section |
| A project or goal an invoice line points at | Nothing on the project or goal says it was invoiced, for an assistant |

The same rules hold for **an associate and a client company they are not
assigned to**.

---

## 6. Data model

A new app, `apps/billing`, which P4's NMI work joins later. Every table is
practice-scoped (`tenant_id`, fail-closed manager) and joins the isolation
registry.

| Table | Columns |
|---|---|
| `invoice_settings` | `tenant_id` (unique), `prefix` (`INV-`), `next_value`, `terms_days` (15), `default_notes`, `default_terms`, `pay_instructions`, `email_subject`, `email_body` |
| `client_invoice` | `id`, `tenant_id`, `kind` (`one_off / recurring / contact`), `client_company_id` (null for `contact`), `contact_id` (the recipient), `schedule_id` (null), `number` (null until ready; unique per practice), `issue_date`, `due_date`, `status` (`draft / ready / sent / partially_paid / paid / void`), `bill_to` (json: the name, company and address as printed), `subtotal_cents`, `tax_cents`, `total_cents`, `paid_cents`, `currency` (`usd`), `notes`, `terms`, `pay_instructions`, `email_subject`, `email_body`, `pay_url` (empty until P4), `pdf_id` → `stored_file`, `outbox_message_id`, `created_by_id`, `ready_at`, `sent_at`, `voided_at`, `void_reason` |
| `client_invoice_line` | `id`, `tenant_id`, `invoice_id`, `position`, `description`, `quantity` (numeric 10,2), `unit_price_cents`, `amount_cents`, `project_id` (null), `goal_id` (null) |
| `client_invoice_schedule` | `id`, `tenant_id`, `client_company_id`, `contact_id`, `day_of_month` (1–28), `next_on`, `ends_on` (null), `lines` (json), `notes`, `terms`, `is_active`, `created_by_id` |
| `client_payment` | `id`, `tenant_id`, `invoice_id`, `amount_cents`, `paid_on`, `method`, `reference`, `note`, `recorded_by_id`, `removed_at`, `removed_by_id`, `remove_reason` |

Constraints: `client_company_id` is null exactly when `kind = contact`; every
status but `draft` has a number, and **a number, once set, is never cleared**
(a reopened draft keeps its own); `paid_cents` never exceeds `total_cents`;
amounts are never negative.

`OutboxMessage.Producer` gains `client_invoice`. That is a choice list and
changes no SQL.

**Migrations:** one, `billing 0001`, creating the five tables. Its SQL is
shown before it is generated, and it is applied on `execsnowhq_local` only.
Nothing existing is altered.

---

## 7. Tests

| Family | Tests |
|---|---|
| **Practice isolation** | All five tables in the registry. Practice A never sees B's invoices, lines, schedules, payments or settings, by list or by id, and a PDF's download address for A's invoice is 404 for B. Two practices each have their own `INV-0001`. The platform owner reaches nothing. |
| **Role boundaries** | §5.1 row by row, and **every row of §5.2 for an assistant**. An associate: assigned companies only, by list, by id, by PDF and in the totals; never a send approval, a payment, a void, a contact invoice or the settings. A client owner and a client team member: their own company's sent invoices and PDFs; never a draft, a ready one, another company's, or a contact invoice, even when they are that contact. |
| Numbers | No number on a draft. Twenty invoices made ready at once get twenty consecutive numbers. A reopened invoice keeps its number. A numbered invoice cannot be deleted. The next number can be raised and not lowered. |
| Money | Integer cents; a line's amount is its quantity times its price, rounded once; totals add up; a payment over the balance is refused. |
| Sending | Making ready sends nothing. Only the practice owner's approval sends. The PDF attached is the PDF stored. A rejected message leaves the invoice ready and unsent. Nothing sends while someone is acting as another user. |
| Frozen | After it is ready, an edit to the contact, the company, the practice's branding or the settings changes neither the invoice nor its PDF. |
| Recurring | The job makes one draft on the day, none twice, sends nothing and numbers nothing; a missed day is made up once; an archived company's schedule stops. |
| Payments and void | Part paid, then paid. Removing a payment reverses the status. A void is refused while a payment counts. Each writes an audit event with its reason. |
| Overdue | Flagged the day after the due date and not before; not for a paid or void invoice. |

**Not verifiable without a browser:** how the PDF looks; the invoice form
with many lines; the portal's invoices page; the list on a narrow window.

---

## 8. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| **I1** | **When an invoice gets its number.** | When it is made ready to send, and it keeps it for good; a numbered invoice is voided, never deleted (§1.1). This is what makes "never skip, never repeat" true. |
| I2 | Which address an invoice is sent from. | The practice's own sending address, as digests are, with replies going to the practice owner. It is a setting per kind of message already; the owner can switch invoices to their own mailbox. |
| **I3** | **The practice owner's own invoice:** does pressing Send count as the approval, or does it wait in the Sending queue for a second press? | It counts. The owner has the PDF and the full email on screen when pressing it, which is what approval is. It is still logged in the queue. An associate's always waits for the owner. |
| **I4** | **An assistant never sees an invoice email**: not in the Outbox, the Sending queue, the send log, the client's shared history or search (§5.2). This is the one exception to "everyone on the practice sees the same client history". | Yes. Without it "assistants have no financials" is false the first time an invoice is sent. |
| I5 | Tax on a client invoice. | One optional amount the practice types in, labeled "Tax". No rates and no calculation in this round. |
| I6 | "How to pay": the practice's payment instructions printed on every invoice. | Yes, required before the first invoice can be made ready. Without a processor it is the only way a client knows where to pay. |
| I7 | A void invoice in the portal. | It stays listed, marked void, because the client was emailed it. Drafts and unsent invoices never show. |
| I8 | Overdue reminders to the client. | Not in this round: the flag only, as you listed. A reminder drafted into the review queue is a small addition later. |
| I9 | Does a client see payments recorded against an invoice (dates and amounts), or only the balance? | The balance and status only, in this round. |

**Build, once approved:** one phase. Migration SQL shown first; applied on
`execsnowhq_local` only; then stop with tests and what was not seen in a
browser. No release until the owner says so.
