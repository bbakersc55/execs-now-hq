# P4 — Billing on NMI: PRD section and data model

**Practices beta program, phase 4 · re-specified 2026-10-08, and for NMI's v5 API on 2026-10-21 · part 1 built**

**2026-11-16:** void and refund from the app (§11) and knowing when the
processor is in Test Mode (§12), released at Release 44.

**2026-11-17, released at Release 45:** recurring invoices that bill automatically (§14): the client
owner agrees in the portal, each invoice is made and emailed by itself, and
the saved card is charged on each billing date. Also auto-pay never passes over
an invoice silently, and web and the worker each report whether they can reach
the processor (§14.1).

**2026-11-17, later:** auto-pay beside automatic billing is "for other
invoices", offered only when asked; Remove the card held through the end
date; the schedule and the stop rule said in the box and the terms; and the
daily jobs keep practice time through daylight-saving changes (§14.11).

**2026-11-16, decided:** no card fee on invoices; an invoice stays one amount.
The card-fee build is dropped. Bank (ACH) payments stay planned, on a separate
ACH merchant ID, for the same total as a card (§13).

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
| `refund(account, transaction_id, amount_cents)` | A whole or partial refund. Called by "Refund or cancel this payment" (§11) |
| `void(account, transaction_id)` | Cancel a sale not yet settled (2026-11-16, §11) |
| `test_mode(account)` | Whether the account is in the processor's own Test Mode: the Query API's `test_mode_status` (2026-11-16, §12) |
| `actions_for_reference(account, reference)` | Every action on the transactions carrying our reference (the sale, a void, each refund): the lookup of a lost refund answer (§11) |
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

### 1.4 The gateway's host, the card form, and pausing (2026-11-10)

The processor (Vaultix) says production goes through its white-label host
for the same NMI gateway, `secure.vaultixpay.com`, not `secure.nmi.com`.

**The host.** `NMI_API_HOST` picks a live account's host, and it can only be
one of two values written in code (`gateway.API_HOSTS`): `secure.nmi.com`
(the default) or `secure.vaultixpay.com`. Settings refuse anything else at
start, and the gateway refuses it again before sending. Every live call
uses it: v5 REST (sales, the connection test, the Customer Vault, refunds),
and the Query API (the lookup of a lost answer and the daily read-back).
`nmi_check` prints it. **A sandbox account always uses `sandbox.nmi.com`.**
That was proved with the sandbox keys: `secure.nmi.com` answers "Sandbox
accounts must use a sandbox domain", and `secure.vaultixpay.com` answers
"User not found".

**The card form.** NMI's Payment Component (`@nmipayments/nmi-pay` 1.1.1,
the latest) cannot be pointed at another host. Its card frames, its token
calls and its message-origin checks all name `secure.nmi.com`, and it has no
option to change that. So the form follows the host for a live account:
- On `secure.nmi.com`, the Payment Component, as before.
- On any other host, **Collect.js loaded from that host**
  (`https://<host>/token/Collect.js`, the practice's tokenization key on its
  script tag, inline fields). Its one-time token goes to the same pay path
  and the same v5 sale (`payment_details.payment_token`).

A sandbox account keeps the Payment Component whatever the host.

**Proved against the sandbox** (`scripts/nmi_token_proof.py --collect HOST`):
- Collect.js from `secure.nmi.com` with the sandbox key gave two tokens.
  They ran the full path on the sandbox's v5: a sale, a partial and a full
  refund, the sale read back, a card stored in the vault, a sale on it, its
  refund, and the record deleted.
- Collect.js from `secure.vaultixpay.com` loads, and its token API answers.
  A made-up key gets 401, as on NMI's host, but the sandbox key gets 404
  because the sandbox's merchants are not on that host.
- So the white-label path is proved up to the token. The token and the sale
  there are proved only with Vaultix's own keys, at the first live check.

**2026-11-13: the live pay page failed, and why.** With
`NMI_API_HOST=secure.vaultixpay.com` the pay page said "The card form could
not be loaded" and the console "You provided too many fields. Unexpected
fields for collectJs". Collect.js builds its configuration from **every**
data attribute on its own script tag and refuses any it does not know
(`acceptableProperties` in its `Config.js`); our loader had added a
`data-collect-js` marker to find the tag again. The file is byte for byte the
same on both hosts, so it failed on NMI's host too; the sandbox proof above
had used its own page with a plain tag and never ran our loader. Now:
- **The tag carries only `data-tokenization-key` and `data-variant`**
  (`COLLECT_TAG_DATA`), found again by its address. The frontend tests' stand-in
  Collect.js applies the real script's check, so any other attribute fails them.
- **Collect.js is one per page.** The form opened last owns it; an earlier one
  (a client paying while "Save a card" is open) says "Another card form is
  open on this page" and takes it back when the later one closes.
- **A form that can't load is never silent.** The script not fetched, a
  refusal as it starts, `configure()` throwing, or no fields within 20
  seconds: the payer reads that nothing was charged (or saved), that the
  practice has been told, and, on an invoice, its "How to pay"; the browser
  reports it (`…/form-failed`, on the pay link, the portal's Pay, auto-pay's
  card and the subscription card), which writes an audit row and gives the
  practice owner one Notice a day per place (kind "payments", the owner's
  alone). A subscription card's failure goes to the platform owner, since
  that form is the platform's. What the browser sends is only text: cut to
  300 characters, anything key-shaped removed, rate-limited.
- **Proved in headless Chrome** (`scripts/nmi_token_proof.py --link-collect
  HOST`, the real pay page built from the tree, `NMI_SANDBOX_CARD_FORM_HOST`
  giving the sandbox account Collect.js, laptop only): from `secure.nmi.com`,
  a real token, a sandbox sale, the Paid page, the receipt and the payment on
  the invoice; from `secure.vaultixpay.com`, the script loaded and the
  configuration accepted, then its token API answered 404 for the sandbox key
  (no fields), and the page told the payer and the owner. `--form-host HOST`
  runs the portal, auto-pay and subscription proofs the same way.
- **Still unproved until a live payment:** the live public key on Vaultix's
  token API (`/token/api/create`), the fields drawn from Vaultix's
  `inline.php`, a token, and the v5 sale with it.

**2026-11-14: the Apple Pay console error.** The live pay page's console
showed "Could not create PaymentRequestAbstraction. Please verify the
provided options are valid." twice (`ApplePayRequest.js:114`) while the card
fields worked. Collect.js's own source (its source map,
`secure.nmi.com/token/Collect.js.map`) shows why. The file is the same on
secure.nmi.com, sandbox.nmi.com and secure.vaultixpay.com.
- Each time Collect.js gets a token (on load, on every `configure()`, and
  again after every token it hands back), it builds an Apple Pay field. It
  does this whether or not the page has an Apple Pay button. Its factory looks
  for the button (`#applepaybutton`) only to report problems with it. With no
  button, it builds the field and mounts it nowhere.
- The field's constructor calls `ApplePayRequest.create`. That logs the error
  and returns nothing unless `currency` (three uppercase letters), `price` (a
  numeric string) and `country` (two uppercase letters) are set.
- **So the error was harmless.** Nothing is mounted, and the card frames are
  built separately (`buildInlineIframes`).
- **The setting that stops it:** `currency`, `country` and `price`, all on
  Collect.js's accepted list. They go in `configure()`
  (`collectWalletSettings` in `NmiCardForm.tsx`: USD, US, and the form's
  amount, `0.00` for a card being saved). They are not put on the tag, which
  keeps its two attributes. The fields, the token and the sale are unchanged.
- **One side effect:** `price` and `currency` also go to Collect.js's token
  lookup as Surcharge Plus inputs. On an account enrolled in Surcharge Plus,
  that lookup would quote a surcharge for the amount. This form reads no
  quote, and the server still sets the sale's amount.
- **Proved in headless Chrome on the sandbox.**
  - Before the change, `--link-collect secure.nmi.com` logged the error three
    times (twice on load, once after paying), and the card still paid.
  - After the change, the same run logged nothing, paid ($33.18 approved, the
    invoice paid, the receipt and the owner's notice sent, Paid on reopening).
  - `--autopay --form-host secure.nmi.com` saved a card through Collect.js
    and auto-pay charged it.
  - `--bank-fees` counted two errors per page without the settings and none
    with them. The token answers were identical either way.

**2026-11-14: "Field is empty".** A payer on the live pay page saw a red
banner reading only "Field is empty" above the card boxes, and took it for a
box they couldn't type in. That was Collect.js's own text, put in the banner by
the form's `validationCallback`. What the sandbox shows of those checks:
- Collect.js checks a box when the payer leaves it, and every box when Pay
  is pressed; it says nothing while a box is being typed in. Its words are
  "Field is empty", "Card number must be 13-19 digits and a recognizable
  card format", "Expiration date must be a present or future month and
  year" and "CVV must be 3 or 4 digits".
- Pay with a box that fails is **held**: Collect.js ignores Pay until its own
  timeout (15 s here), and then calls the timeout callback. So a payer who
  pressed Pay on empty boxes saw "Working…" for 15 s, and then "The card
  processor did not answer".

Now (`NmiCardForm.tsx`, the Collect.js form, which all four card screens use):
- **Each box says what it needs beside it**, in plain words
  (`FIELD_WORDS`): "Enter your card number", "That card number doesn't look
  right", "Enter the expiry date as MM/YY", "Enter the security code".
  - A box speaks only once the payer has left it (the blur Collect.js
    marks on its frame) or has pressed Pay.
  - The words clear when Collect.js passes the box.
  - Collect.js's own text is read only to tell an empty box from a wrong
    one, and is never shown.
- **A failed attempt is ended at once.** The form ends it the way the
  timeout would (`inSubmission`, `responseTimeout` in Collect.js's
  `startPaymentRequest`), so Pay works again straight away.
  - If a later Collect.js lacks those, Pay pressed meanwhile waits for the
    timeout and then goes.
  - That timeout is never reported as the processor's.
- **The banner is for real failures only:** the form not loading, the
  processor not answering, a decline, or a payment or card that could not
  be recorded, each in our own or the server's words.
- NMI's Payment Component (NMI's own host, and the sandbox) already shows
  its own message beside each box, inside its widget; it is unchanged.
- **Proved in headless Chrome on the sandbox:** `--link-collect
  secure.nmi.com`, which now checks the boxes before paying. It leaves the
  number empty, presses Pay with every box empty, then leaves a wrong number.
  Each time it reads what is said beside each box, and finds no banner and
  none of Collect.js's own words. Then the test card pays.

### 1.5 Bank payments and card fees: what the sandbox shows (2026-11-14)

**2026-11-16: no card fee will be built (§13).** Rows C1–C3 stay as findings
only. The B rows still serve the planned bank payments.

`scripts/nmi_token_proof.py --bank-fees`, against the platform's sandbox
account only. It uses its own page with Collect.js from secure.nmi.com, and
NMI's published test bank account (routing 490000018, account 24413815). No
app code was changed for it. Each result is **proved** (on the sandbox, by
that run), **not provable on the sandbox**, or **needs the processor** (only a
live account, NMI or Vaultix can answer it).

| # | Question | Status | What was found |
|---|---|---|---|
| B1 | A bank account tokenized through Collect.js | **Proved** | Collect.js takes inline `checkname`, `checkaba` and `checkaccount` fields. It makes a token only when all three are filled. The answer is `check: {name, account: "*******5", aba: "490000018", transit: null, institution: null, hash: ""}`, with every `card` field null. The account shows only its **last digit** here. |
| B2 | A bank sale from that token, no SEC code | **Proved** | `payment_details.payment_token` alone was approved (`response` 1, 100 SUCCESS, `type` "ck", `pendingsettlement`). NMI filled in **WEB**, checking, personal. |
| B3 | With a SEC code: WEB and CCD | **Proved** | `payment_details.sec_code` beside the token: WEB and CCD were both approved. For CCD, NMI set `account_holder_type` to **business** by itself. A top-level `sec_code` is refused (400, `extraParameters`). The Query API reads each sale back as `transaction_type` ck, with its `sec_code`, `account_holder_type` and `account_type`, `check_account` "2xxxxx15", `check_aba` and `check_name`. |
| B4 | A bank account in the Customer Vault, charged | **Proved** | `POST /customers` with the bank token stores it. The answer shows `check_account` "\*\*\*\*3815", which is the **only place the last four appear**. A sale with `customer_vault.id` was approved as WEB and personal, and the Query API shows its `customerid`. The record was deleted (204). |
| B5 | CCD on a stored bank account | **Proved** | `payment_details: {sec_code: "CCD"}` beside `customer_vault` was approved as CCD and business, though NMI's reference says not to send `payment_details` with a vault charge. A top-level `sec_code` is refused. A record stored with `sec_code` CCD and `account_holder_type` business was accepted, but the record keeps neither, and a sale on it went through as WEB and personal. **CCD has to be sent on every vault sale.** |
| B6 | Can the sandbox make a return? | **Not provable on the sandbox** | The sandbox **settles nothing**. All 53 approved sales since 10/21 are still `pendingsettlement`, with no `settle` action, and a return comes only after settlement. The account's 19 bank transactions (all from 11/14) have only `sale` actions. The one trigger it has is the card one: a bank sale under $1.00 is **declined at once** (HTTP 200, `response` 2, "FAILED"). That is a decline, not a return. |
| B7 | How the Query API reports a return | **Partly proved; the rest needs the processor** | Proved: `return` is the only return-like action type the Query API recognizes. Filtering on it returned 0 transactions, while a made-up name returns all 78. It ignores `check_return`, `check_late_return` and **`chargeback`** (78 of 78 each, the same as a made-up name). Still open: whether a return is an action on the original sale or a transaction of its own, its date, the sign of its amount, and the R-code text. **`apps/billing/readback.py` expects `chargeback`.** A `return` would reach it as "other": recorded and shown to the owner as needing a look, never dropped. Mapping `return` is a follow-up, not made here. |
| B8 | A return on a sale older than 7 days | **Not provable for a return; proved for a refund** | A $0.01 refund made on 11/14 against a sale from 10/21 is a **transaction of its own**: a new id, with `original_transaction_id` set to the sale and the sale's `order_id` carried over. The read-back's 7-day window lists it, and it matches by the original id. The 10/21 sale itself is not listed in that window. If a return is instead an action on the original sale, a query by date might not find a sale older than the window. That needs the first live return, or NMI's answer. |
| C1 | The credit/debit category for test cards | **Proved for the field; the values need the processor** | This sandbox account publishes `category` both in `lookUpCallback(card)` (`{number, bin, exp: null, type, category, hash}`, once the number is valid) and in the token answer's `card` (the same, plus `exp`). The values do not match the card networks: 4111… unknown, 5431… unknown, 6011 6011… credit (with `type` null), 3411… credit, 400005… (a debit BIN) unknown, 520082… (a debit BIN) **credit**, 510510… (a prepaid BIN) unknown. "debit" and "prepaid" never appeared. The sandbox's BIN data is not real, so whether live BINs read right is for the processor. Also: a second card typed on the same page is looked up against Collect.js's fresh token and answers empty or with the card before, so a lookup is good once per token. |
| C2 | Surcharge Plus's quote (`card.surcharge`) | **Needs the processor** | It was absent from every lookup and token, with or without `price` and `currency`. The sandbox account is not enrolled. |
| C3 | Where a surcharge goes on a v5 sale | **Proved** | **A top-level `surcharge`** (`"0.30"` or `0.30`) is accepted. **`amount` is the total including it**: $15.07 was sent with 0.30 and read back as $15.07. It is reported in the sale's answer and in `GET /payments/{id}` as `order_details.surcharge` "0.30", and in the Query API as `<surcharge>0.30</surcharge>`. A request with `order_details.surcharge`, where NMI's own surcharge guide puts it, is **refused** (400, `extraParameters`): that is where v5 reports it, not where it takes it. Each sale was refunded. Still for the processor: whether a live account may surcharge, its caps, and how settlement reports it. |

Also seen: an unknown field is now refused with **400** `E_INVALID_SUBMISSION`
(A10 saw 422 on 10/21). The gateway treats any refusal the same way, so
nothing depends on the code.

**Paused.** In production the stub never answers. With `NMI_LIVE_CALLS` off,
every gateway call is refused (`CardPaymentsPaused`), and card payments are
paused:
- pay buttons and pay links say "Card payments are paused";
- no card is saved;
- auto-pay and practice subscriptions wait, with no try counted, nothing
  past due and no notice;
- lookups and the read-back settle nothing;
- the connection test says real calls are off.

The platform owner's **"Pause card payments"** switch (the Practices area,
`card_payment_hold`) does the same while real calls stay on. Then a sale or a
stored card is refused before it leaves, and reads go on: the connection
test, lookups, the read-back, Test Mode, and deleting a card. **A refund or a
void still goes** (2026-11-16, §11): the pause stops money coming in, not
going back. A pause that
lands between the check and the sale removes the attempt it had written,
because nothing left for the processor. Tests:
`tests/test_card_payments_paused.py`, including that no path marks anything
paid without a real gateway answer when the environment is live.

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

**As built (2026-10-24, `apps/billing/readback.py`, job `billing.read_back_nmi`
at the practice's 6:00).** v5 has no search, so the read-back lists the last
seven days of actions through the classic Query API (`start_date`/`end_date`,
read-only, the same private key, as A13's lookup). Each action the app did not
make becomes one `nmi_event` (once: transaction, action and time): a refund,
void or chargeback is matched to its payment by NMI's transaction id (or the
original one, for a refund NMI lists as its own transaction), then by our
reference, and recorded against it; anything unmatched, a charge made in NMI's
portal included, is flagged. The practice owner sees them on Invoices ("From
NMI: please look", Mark as seen) and on the invoice. **It changes no invoice's
money:** what a refund or chargeback means for the balance is recorded by hand.
Subscription charges ("sub-…") are the platform's and are left out even where
a practice shares the platform's keys. Only practice accounts are read so far;
the platform account's own read-back is not built. **Not proved against NMI:**
the sandbox cannot make a chargeback, so the action names a live account uses
for one (`chargeback` is assumed) are checked at the first real one.
*(2026-11-14: the Query API does not recognize `chargeback` as an action type,
and does recognize `return`; see §1.5, B7.)* *(2026-11-16: refunds and voids
the app made itself are never flagged, and one made in the portal that
matches a payment gets "Record this refund"; §11.)*

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
| `nmi_event` *(built 2026-10-24 as a practice table, `tenant_id` and fail-closed, since only practice accounts are read back; see §4)* | `id`, `event_id` (unique with the account), `account` (`platform` or a practice id), `type`, `reference`, `received_at`, `processed_at`, `outcome`, `error`. **No card data and no body beyond what is listed.** |
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
| **5. Practice subscriptions** | §2 on v5. The platform account is the NMI_* environment keys (`gateway.platform_account()`). The practice owner saves the practice's card under Settings → Billing, "Your subscription", into the **platform's** vault (NMI's fields with the platform's public key). `billing.charge_subscription`, daily at 7:00, a no-op for the owner's own practice: from the card's first 1st (no part-month), the month's `practice_invoice` (number `ENH-YYYYMM-<slug>`, base or the owner's override plus add-ons charged from that period, tax line zero) with its PDF, then one sale on the vault carrying `sub-<invoice id>`; a missed day catches up; twice in a day is one charge. Approved: paid, the PDF remade with the payment on it, a receipt with the PDF attached sent through the platform owner's practice's Outbox. Declined: open, past due, the owner told with a link to Settings → Billing, no retry by itself; **Pay now** pays what is open. A lost answer is "unknown" and looked up by its reference (Query API), never charged again blind. Beta at $20.00 (`billing_plan` seeded), adjustable per practice by the platform owner on the Practices screen, from the next period. Thirty days unpaid: "Overdue 30+ days: suspend?" on the Practices screen; **Suspend** by hand only; a suspended practice's staff get only the billing screen (server and screen), its jobs stop but this one, its clients still read, no data changes; paying lifts it at once (Pay now, the 1st's charge, or the lookup), and the owner can lift it by hand. Archiving cancels; unarchiving starts from the next 1st. **Separation:** each side settles only from a sale carrying its own reference, so a client payment never marks a subscription invoice paid nor the reverse. Agreement v4 (v3 with v2's clause 3) in the same release. Not built: `nmi_event` and the daily read-back of refunds and chargebacks (§4); `nmi_subscription_id` and `current_period_end` (NMI's recurring is not used) | **Built 2026-10-21** |

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

---

## 11. Void and refund from the app (2026-11-16)

**Built 2026-11-16; live since Release 44 the same day.** Migrations `billing 0013` and
`finance 0018`, both additive. Code: `apps/billing/refunds.py`; screens: the
invoice page, Invoices ("From NMI: please look"), Practices.

### What the owner sees and does

- **"Refund or cancel this payment"**, on any card payment the app took (the
  pay link, the portal's Pay, auto-pay), for the **practice owner** only: an
  amount (all that is left, unless changed) and a **required reason**. A card
  payment the app took has no "Remove" any more: money that went through the
  processor comes back through it. A payment recorded by hand keeps "Remove".
- **"Refund or cancel this charge"**, the same for the **platform owner** on a
  practice's subscription charge (Practices, under each practice's
  "Subscription charges"), on the platform's account.
- **The processor is asked for the sale's state first** (`GET /payments/{id}`).
  A sale `pendingsettlement`, given back **in full** and never refunded before,
  is **voided**: nothing reaches the payer's statement. Anything else (settled,
  or a part, or the rest after an earlier refund) is **refunded**.
- **One at a time, recorded before the call.** The `card_refund` row is written
  with the payment locked; the database allows one in flight per payment (and
  per subscription invoice). One call, never retried. **Never more than was
  paid**: what is left is the payment less every refund done or under way,
  checked under the lock; the processor refuses more too.
- **A lost answer** is "unknown" and the ten-minute job
  (`billing.resolve_card_payments`) finds what the processor did by our
  reference on the sale (a refund is its own transaction carrying the sale's
  order id; a void is a "void" action on the sale). None after an hour: "not
  done". A subscription refund's lost answer is found by the same job of the
  practice it belongs to.
- **Refused by the processor:** "not done", with its words; nothing changes.
  If a void is refused because the sale settled in between, the owner is told
  to try again, and it is then a refund.

### Once done

| | A client's payment | A practice's subscription charge |
|---|---|---|
| The record | a `card_refund` row on the invoice, with the processor's id (a refund's own; a void's is the sale's) | the same, on the subscription invoice |
| The invoice | paid less by that amount, so its balance reopens (Paid → Partly paid or Sent); **"and void the invoice"** offered only with a full refund that leaves nothing paid | `amount_paid_cents` less by that amount, Open again; or Void, if chosen on a full refund |
| The books | **a void takes the payment's entry out** (removed, with the reason); **a refund is its own entry**: income going out, the payment's category, dated the day of the refund (tax held back out in the payment's proportion) | none: subscriptions are in no books |
| Mail | a receipt to whoever paid (the portal's payer, or the invoice's address), a notice to each practice owner | a receipt to the practice's billing email, a notice to the platform owner (platform mail) |

If the books refuse (a closed month), a void is entered as a refund dated
today instead; if that is refused too, the refund stands and the row and the
notice say "Given back at the card processor, but not in the books: … Enter it
by hand." A payment with a refund on it can no longer be removed by hand, and
the books' backfill (F13) never re-enters a voided or test payment.

### The read-back and the portal

- The morning read-back (practice and platform) **recognises the app's own**
  refunds (by the refund's transaction id) and voids (by the sale, with a void
  done or under way); one under way whose id is not known yet is left for the
  lookup. None of them is flagged.
- A refund or void **made in the processor's portal** is still flagged. When it
  matches a payment (or a subscription invoice), the flag has **"Record this
  refund"**: the same bookkeeping as one made here (a void takes the entry out;
  a refund is entered on the day the portal made it), with "and void the
  invoice" when it leaves nothing paid. It calls nothing and emails no one,
  and marks the flag seen. An unmatched one is still recorded by hand.

### While card payments are paused

**Refunds and voids still go** (owner's expectation, 2026-11-16): the pause
switch refuses sales and saved cards only. With real calls off in production
(`NMI_LIVE_CALLS`), nothing reaches the processor, refunds included.

### Proved

- **NMI's sandbox, by hand, 2026-11-16** (a probe, no app code): `POST
  /api/v5/payments/{id}/void` with `{}` answers the sale with `status`
  "canceled" and a "void" action; voiding again is 400 "Only transactions
  pending settlement can be voided"; refunding a voided sale is 400 "Voided
  Transaction Cannot be Refunded"; voiding a partly refunded one is 400
  "Refunded transactions may not be voided"; a cent more than what is left is
  400 "Refund amount may not exceed the transaction balance". Each refund is a
  transaction of its own, `original_transaction_id` the sale's, the sale's
  order id carried over; the Query API lists them all by that order id.
- **Headless Chrome on the sandbox** (`scripts/nmi_token_proof.py --refunds`,
  2026-11-16, the real pages built from the tree): paid by the pay link;
  "Refund or cancel this payment" for the whole amount → **voided** ("Cancelled
  before it settled"), the entry taken out, the invoice Sent again; paid again
  (NMI's Mastercard test card: the same card and amount within minutes is a
  duplicate); **$2.00 refunded**, then **the rest refunded with "and void the
  invoice"**: two refund entries dated that day, the invoice Void; the
  receipts and notices sent; the read-back run next: **none of this run's
  transactions flagged**. Then a second invoice paid, $1.00 refunded straight
  at NMI (the portal's stand-in), the read-back flagged it matched, and
  **"Record this refund"** pressed in the browser: a portal-sourced refund with
  its entry. The run reads the sandbox's Test Mode as off
  (`NMI_SANDBOX_IGNORE_TEST_MODE`, laptop only, §12) to take the books path.
- **Tests:** `tests/test_card_refunds.py` (void or refund, never more than paid,
  one at a time, the lost answer found, refused changes nothing, void the
  invoice, refunds while paused, role boundaries, practice isolation, the
  read-back and "Record this refund", subscriptions).

### Not proved

- **A settled sale's refund at the processor.** The sandbox settles nothing
  (§1.5 B6), so every refund there was of an unsettled sale; the code path for
  a settled one is the same call, proved only by the tests' stand-in.
- **A live account's void and refund**, and Vaultix's host for them: first at
  the first real one.
- **The portal's own refund as a live account lists it.** The stand-in is a v5
  refund made outside the app, which the sandbox lists as its own transaction.

## 12. Knowing when the processor is in Test Mode (2026-11-16)

**Built 2026-11-16; live since Release 44 the same day.** Code: `apps/billing/gateway_mode.py`,
`apps/billing/testmode.py`.

### The reading

- The Query API's **`report_type=test_mode_status`** answers
  `<nm_response><test_mode_enabled>true</test_mode_enabled></nm_response>`.
  The account profile (`report_type=profile`) carries the same tag under
  `account_details`; the app reads either. **The sandbox answers true for every
  account.** Secure.vaultixpay.com answers the Query API in the same shape (a
  bad key: "Specified API key not found"); **what it answers for the live key
  is production's to show.**
- Read on **Test connection** (and on saving keys), and **before each sale,
  card save and refund**, for a practice's account; before each subscription
  charge and card save, and on "Read Test Mode now" (Practices), for the
  platform's. The last answer is kept (`payment_account.gateway_test_mode`,
  `platform_gateway_mode`).
- **Unreadable** (no answer, or no tag): card payments behave as before (as if
  not in Test Mode), and Billing says "Couldn't read whether the card
  processor is in Test Mode, so card payments work as before" and why.

### While it is on

- **"The card processor is in Test Mode: no money moves."** for the practice
  owner on Billing and Invoices, and for the platform owner on Practices.
- **Pay pages and receipts** carry the sandbox's wording ("Test mode" on the
  pay page; "(test mode: no real money moved)" in the receipt and notice).
- **Every attempt, payment, refund and saved card** made then is marked a test
  (`is_test`) and shown with the **Test** pill. A test payment counts on its
  invoice (so the payer's pages read as they will: Paid) and **nowhere else**:
  no entry in the books (so not in the P&L, reports or CPA export), not in the
  Invoices totals (paid, outstanding, overdue), not in the cash forecast (the
  invoice is still expected), not in the practice KPI feeds (invoices paid,
  days to pay). `client_invoice.test_paid_cents` holds the test part.
- **Refunds:** a test payment is given back only while the processor is in
  Test Mode (a test refund, no books); a real payment is not given back while
  it is (nothing would move). Afterwards a test payment is cleared, not
  refunded.

### Back in live mode

The owner sees **"N test payments"** with one action, **Clear test payments**
(on Billing and Invoices for a practice; on Practices for the platform's
subscription charges), offered only once the last reading is "live"; it reads
again first and refuses while it still says Test Mode. It:

- removes each test payment from its invoice (kept, marked removed, with the
  reason) and clears its test refunds;
- **reopens or voids** their invoices, as chosen (one that also has real money
  is reopened, never voided); a reopened subscription invoice is charged again
  by the next daily run once a real card is on file;
- **deletes test cards from the vault** (which turns their auto-pay off; a
  test subscription card leaves the practice "Needs a card").

### Proved

- **Headless Chrome on the sandbox** (`scripts/nmi_token_proof.py --test-mode`,
  2026-11-16): the sandbox's own answer (true): the banner on Billing and on
  Invoices; a payment by the pay link marked a test with no entry in the books
  and `test_paid_cents` equal to what was paid; a $1.00 refund "(a test: no
  money moved)" with no entry; the client's saved card a test card; receipts
  worded as tests. Then the server restarted reading the sandbox as live, the
  owner pressed Test connection, saw "1 test payment" and pressed **Clear test
  payments**: the payment removed, its refund cleared, the invoice reopened,
  the card deleted from the sandbox's vault (it answers 404 after).
- **Tests:** `tests/test_gateway_test_mode.py` (the reading and its banner, the
  unreadable case, the laptop switch, test payments out of the books, totals,
  forecast and KPIs, test cards, the refund rules, clearing reopen and void,
  real money never voided, role boundaries, isolation, subscriptions).

### Only production can show

- What **secure.vaultixpay.com answers for the live key** while the account is
  in Test Mode and after (the sandbox always says true). Until a reading is
  seen there, it is assumed to be the same tag. To look, with the owner's yes
  (read-only):
  `railway ssh --service qcluster -- "python manage.py shell -c \"from apps.billing import gateway as gw; print(gw.gateway().test_mode(gw.platform_account()))\""`
- A live account switched **into and out of** Test Mode, so the banner, the
  test payments and "Clear test payments" are seen on real answers.
- Whether simulated sales appear in the Query API at all (the lookup and the
  read-back): the sandbox's own Test Mode lists them, a live account's may not.

### `NMI_SANDBOX_IGNORE_TEST_MODE` (laptop only)

True reads a sandbox account's Test Mode as off, so a proof can take the books
path with real sandbox answers. Refused at start anywhere but a localhost
server; never applies to a live account.

---

## 13. Decision, 2026-11-16: no card fee on invoices; bank payments stay planned

Bryan and the processor agreed on 2026-11-16. Recorded as decided; no code
changed.

**No card fee line or fee option on invoices.**
- A practice discusses any card fee with its client beforehand and puts it in
  the price. **An invoice stays one amount.**
- The app adds no fee line and shows no second total. It neither detects
  credit or debit nor sends a surcharge.

**The card-fee build is dropped:**
- the fee line on an invoice;
- two totals (by card, and by bank);
- credit/debit detection (§1.5 C1);
- the surcharge field on a sale (§1.5 C3).

§1.5's C rows stay as what the sandbox showed, not as a plan. The pay form
still passes `price` and `currency` to Collect.js (§1.4, to quiet the Apple
Pay error), and nothing reads a surcharge quote.

**Bank account (ACH) payments stay planned. Nothing is built yet.**
- The payer chooses **card or bank** for the **same total**.
- The processor is setting up a **separate ACH merchant ID**.
- §1.5's B rows are what the sandbox has shown for bank payments so far:
  - tokenizing through Collect.js;
  - WEB and CCD;
  - the vault;
  - CCD sent on every vault sale.
- Still open, for when it is built:
  - how the ACH merchant ID reaches the app: its own keys, or a second
    processor on the same gateway account;
  - how a return is reported (§1.5 B6–B8).

---

## 14. Automatic recurring billing (2026-11-17)

Bryan's request, for real clients the next day: simple and correct first,
month to month. Code: `apps/billing/recurring.py` (the flow),
`apps/billing/timing.py` (the dates), `apps/billing/worker_state.py` (§14.1).
Migrations `billing 0014_automatic_billing` and `notify 0006_payments_notices`
(choices only), both additive.

### 14.1 First: never passed over silently

**What skipped INV-0004 (2026-11-16).** `NMI_LIVE_CALLS` was true on web and
not on the worker (`qcluster`), so every scheduled job that calls the
processor was refused in the worker, and auto-pay passed the invoice over
without a word. **The fix is a Railway variable, which waits on the owner:**
`NMI_LIVE_CALLS=true` on `qcluster`, as on web. Nothing here changes it. What
the code now does:

- **Every pass-over is recorded and told.** When auto-pay (or automatic
  billing) does not charge an invoice that is due, for any reason but "nothing
  owed" or the try rule's own (already tried today, one in flight, both tries
  used, each already told), the reason goes on the invoice's history ("Not
  charged", once a day for each reason) and its practice owner gets a Notice
  and an email, once for the invoice. The client is not emailed. Reasons
  named: no card on file; real calls off in the worker; payments paused by
  the platform owner; the card account not ready; the card saved in the other
  environment; a card saved in Test Mode once the processor is live; sent
  before auto-pay was on; auto-pay turned off since (recorded once).
- **A card saved in Test Mode is never charged once the processor is live**
  (`card_payments.charge_on_file`, and the platform's subscription charge):
  refused before anything is written or asked, with the plain reason, and no
  decline email to the client. If the mode can't be read, the test card is
  not charged either.
- **Each service reports itself.** The start scripts set `APP_SERVICE` (web or
  worker; not a Railway variable) and run `manage.py report_service`; the
  worker's billing jobs report again on each run, so the ten-minute lookup
  keeps it fresh. Rows: `service_report`.
- **A red warning in production** on Practices (Card payments; with what each
  service said and today's refused jobs) and on Settings → Billing (plainer
  words for the practice owner) when the worker has real calls off, when web
  and the worker disagree, or when the worker has not reported for 30
  minutes.
- **Refused jobs are recorded** (`refused_job`: job, practice, day, a count)
  when a scheduled job that needs the processor runs where real calls are off,
  for a practice that takes cards (auto-pay and automatic billing's charges,
  lookups with something waiting, the read-back, subscription charges); the
  platform owner gets a Notice and an email once a day.
- **`manage.py nmi_check`** prints this process's real calls and both
  services' last reports, and fails when the worker's are off or the two
  disagree.

### 14.2 Two kinds of recurring invoice

**You send each invoice** is unchanged: a draft on its day, made ready and
sent by a person. **Bill automatically** is new, the practice owner's alone
to set up or change (it charges a card), chosen when the recurring invoice is
made (its kind never changes after).

**Timing.** Monthly on one or more days of the month, 1 to 28 (the 1st and the
15th in one recurring invoice), from a **first billing date** on one of those
days and not in the past; an optional **contract end date** (after it, month
to month); and **how many days before each date** the invoice is emailed
(default 3, 0 to 14). The model holds `cadence` (only `monthly`), `every`
(only 1) and `days_of_month`; weekly, every two weeks, quarterly, yearly and
every-N are meant to be added as cadences in `timing.py`, which is the only
place billing dates are worked out. A day 29 to 31 can't be chosen, so no month
is short of one.

### 14.3 The client's agreement

Nothing bills until the client owner agrees in the portal (Invoices,
"Automatic billing"), with a card saved in the same flow (NMI's own fields,
the practice's vault, as for auto-pay). The terms, in short plain words: what
is billed and the total each time; the days; the start; "Term ends <date>,
then month to month" or "Month to month"; how paying works (emailed N days
before, charged on the date, one retry); how to stop; and when billing ends
after stopping. Kept like the auto-pay consent (`billing_agreement`): who,
when, the exact words, their version (`2026-11-17`), the address and the
browser, and the card. The words agreed to are checked against what was shown
(a short hash), so terms changed while the client read them are read again.
Until then the practice owner sees **"Waiting for <client> to agree"** and
**"Email <client> the link to agree"**, which emails each client owner with
portal access. While an agreement is in force the card can be replaced, never
removed (the only card).

### 14.4 From invoice to charge

- **Made and emailed by itself** at the 5:00 job (`run_invoice_schedules`),
  `lead_days` before each billing date: written, numbered, its PDF stored and
  its email sent with no approval step (the Outbox's own checks still apply).
  The email says the amount and "will be charged to the card ending NNNN on
  <date>". The invoice is due on its billing date. A missed day is made up.
  One invoice per billing date (a database constraint).
- **With no usable card** (none, the other environment, expiring before the
  date, a test card once live) it still goes, with its pay link and no charge
  line, and the practice owner is told.
- **Charged on the billing date** at the 9:00 job (auto-pay's), and the
  receipt sent; the owner gets the usual card payment notice. A decline
  follows auto-pay's rule: one more try on a later day, never a third, the
  client and the owner told each time. Anything else that stops a charge is
  §14.1's pass-over.
- If an invoice can't be made or emailed (say, no "how to pay" in the
  practice's settings), nothing is charged and the owner is told; one that
  was made but not emailed stays ready for the owner to send.

### 14.5 Stopping

In the portal the client owner presses **Stop automatic billing** and first
reads: "Billing continues through <date>. Your last charge will be on <date>.
For an exception, contact <practice owner's name and email>." **The rule:**
billing ends on the last day of the calendar month after the month notice is
given; every billing date up to and including that day is billed, none
after (notice on November 16: the rest of November and all of December,
nothing after December 31). A contract end date later than that wins; an
earlier one does not shorten it. On confirming, the client is emailed the
dates and the practice owner gets a Notice and an email. **The client can
withdraw their own notice** before the end (the owner gets a Notice). **The
practice owner** can bring the end earlier with a date (never later, never
in the past) or **stop now**; invoices already made for dates after the new
end are voided; the client is emailed the new date; and a client can't
withdraw an end the owner set. Stopped now, nothing more is charged, even an
invoice already made for today. **After the end it is Ended**; billing again
needs a new agreement, offered in the portal once the owner emails the link
again.

### 14.6 Changes

A change of lines or price while an agreement is in force applies from the
first billing date **at least 7 days out that has no invoice yet**, and the
client is emailed the new total and the date. The billing days, the first
date and the contract end can't change while an agreement is in force (the
client agreed to them); end it and ask for a new agreement instead.

### 14.7 What the practice owner sees

Invoices → Recurring invoices: each row's kind ("You send each" or "Bills
automatically"), when, its state (**Waiting for <client> to agree**,
**Active**, **Notice given, ending <date>**, **Ended**), the next billing
date, the last one billed, and the amount. **Details** shows the timeline
(agreed, first billing date, contract ends, month to month since, notice
given, billing ends, last billing date, ended) and the actions: email the
link; set an earlier end; stop now (asked twice); and, **only while the
processor last said Test Mode, "Run the next billing now"**: it reads Test
Mode again, then makes, sends and charges the next billing date's invoice at
once, so the whole path can be proved without waiting for the clock. It
refuses for 20 minutes after a charge of the same amount under the same
recurring invoice: on the sandbox, NMI refused the same card for the same
amount seconds later as a duplicate, and that decline emails the client.

### 14.8 Choices made (the simplest reading)

- Invoices made at 5:00 and charged at 9:00, by the existing jobs: no new
  scheduled job, nothing to register on release.
- The agreement covers one recurring invoice; a company can have several
  (each agreed on its own) and they share the company's one card on file.
- Charges are auto-pay attempts (`via` autopay), so the retry rule, the
  receipt and the decline emails are auto-pay's own words.
- The kind is fixed once made. Pause is not offered for automatic billing:
  it is ended instead.
- Billing dates before the day the client agreed are never billed.
- Only the practice owner sets up or acts on automatic billing; an associate
  keeps "You send each invoice" as before.
- After Ended, a new agreement is offered only once the owner sends the link
  again; a recurring invoice never agreed to can be agreed to at once.
- Bank accounts later: the agreement's `card` is where a bank account would
  go; cards only now.

### 14.9 Proved

- **Tests:** `tests/test_automatic_billing.py` (48: the date rules, notice in
  November, December, January, February and a leap year, a contract end later
  and earlier than the rule; set-up and its refusals; nothing before the
  agreement; the agreement as kept, changed terms read again, roles and
  companies; the card not removable; made lead days before and emailed with
  no approval; charged on the date and never twice; lead days 0; no card;
  a decline and its one retry; a price change from 7 days out; agreed days
  fixed; notice, withdrawal; the owner moving the end earlier and refused
  later or in the past; voiding a made invoice past the new end; stop now;
  Ended and a new agreement; test cards once live, for automatic billing and
  auto-pay; Run the next billing now only in Test Mode; "You send each
  invoice" unchanged); `tests/test_worker_state.py` (9);
  `tests/test_card_payments_paused.py` (paused auto-pay now tells the owner);
  `frontend/src/screens/AutomaticBilling.test.tsx` (8).
- **On NMI's sandbox, in headless Chrome** (`scripts/nmi_token_proof.py
  --automatic`, read as live): set up on the 1st and 15th, the link emailed,
  agreed in the portal with NMI's test card, the invoice made and emailed by
  itself three days before, the card charged on the date (a real vault sale),
  the price changed (from the next date), Stop automatic billing with the
  dates read first, the last charge at the new price, nothing after the end,
  Ended on both pages. `--run-now` presses Run the next billing now with the
  sandbox's own Test Mode on: the first press made, sent and charged the next
  invoice at once, a test payment; a second press seconds later was refused
  by NMI as a duplicate (same card, same amount), which is why it now waits
  20 minutes after a charge of the same amount.

### 14.10 Not proved

- **Production with the worker's `NMI_LIVE_CALLS` still off** charges
  nothing by schedule, exactly as on 2026-11-16, until the owner sets it; the
  red warning and the daily notice are what change.
- A live card charged by the worker, a live decline and its retry, and the
  invoice email through the practice's real mailbox: only the first real one.
- The clock moved in the proof is the app's own (`timezone.now`); a real
  month of 5:00 and 9:00 runs has not passed.

### 14.11 Auto-pay beside automatic billing, and the box's words (2026-11-17)

The rules did not change; what the client owner reads did. On production a
client had agreed to automatic billing and, on the same page, also turned on
auto-pay, whose offer appeared as soon as the card was saved to agree.

- **Agreeing never turns auto-pay on**, as before: a consent is made only by
  the auto-pay button. Beside automatic billing (waiting to be agreed, or
  still billing), the card is titled **Card on file** and auto-pay is a
  section of its own, **Auto-pay for other invoices**: "Automatic billing is
  charged under its own agreement, in the Automatic billing box above, and
  isn't changed here." Its offer shows only when the client presses **Also
  pay other invoices automatically?**, with "This doesn't cover automatic
  billing, which is charged under its own agreement." Without automatic
  billing the card is as it was.
- **What keeps running is said.** On: "Other invoices from <practice> are
  charged to the card on file on their due dates." Under **Turn auto-pay off
  for other invoices**: "Automatic billing keeps running under its agreement;
  to end it, press Stop automatic billing above", or, once notice is given,
  "Automatic billing continues through <end>." Turning auto-pay off never
  touched an agreement's invoices (they are never tied to a consent), and
  still does not.
- **Remove the card** is off, with the reason under it, while automatic
  billing is still billing, **judged by the end date itself** (`autopay.card_hold`):
  "Automatic billing is on, so the card on file can't be removed. Replace it
  with another card, or stop automatic billing first", or after notice
  "Automatic billing continues through <end>, so the card stays on file until
  then. You can replace it with another card." The day after the end date it
  can go, whether or not the 5:00 job has closed the agreement yet. The
  practice owner's Stop now frees it at once, as before.
- **The box and the terms** put the schedule on its own line ("Billed on the
  1st and 15th of each month") and say, before anyone presses Stop, "If you
  stop, billing continues through the end of the following month." With a
  contract's end still to come: "If the term ends later than that, on <date>,
  billing continues through the term's end." The terms' wording is version
  `2026-11-17.2`; agreements already given keep the words they agreed to.
- **The practice owner**, once notice is given, sees "Billing ends <end>.
  Last charge <date>." under the state in the list and in the details.

Tests: `tests/test_automatic_billing.py` (agreeing makes no consent; auto-pay
off leaves automatic billing charging; the card held through the end date and
free the day after, before the job closes it; a one-off invoice charged only
under a consent given separately; the box's words; the owner's last charge)
and `frontend/src/screens/AutomaticBilling.test.tsx`. Proved in a real
browser on the sandbox as a client owner: `scripts/nmi_token_proof.py
--beside`, with the server's clock moved to the day after the end date by
`scripts/moved_clock.py` (proof databases only).

**Also, 2026-11-17: the daily jobs keep practice time.** Django-Q moves a
daily job's next run by 24 hours in UTC (its own daylight-saving correction
reads `TIME_ZONE`, which is UTC), so after the clocks went back on November 1
the 5:00, 7:00 and 9:00 jobs ran at 4:00, 6:00 and 8:00. An hourly job per
practice, `tenancy.keep_local_hours`, moves each daily job with a practice-time
hour back onto that hour (the nearest occurrence, so a run is never skipped or
doubled; one due within five minutes is left to the scheduler), and
`ensure_schedules` does the same when it runs. It needs `ensure_schedules` once
after release to register the new job (runbook R5b).
