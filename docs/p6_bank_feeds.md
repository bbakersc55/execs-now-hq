# Bank feeds, version one — as built (2026-11-04)

The practice owner's own bank accounts, connected through **Plaid** and feeding
Finance. Built on `dev`; not released. The owner's brief is the source; where
it left something undecided the simplest reading was taken, and each one is
listed under "Choices made" at the end, for a yes or a change.

## Scope

- **The practice's own accounts, the practice owner only**, as the rest of the
  books are. An associate or an assistant gets 403 on every route; a client
  user gets 404; another practice gets 404.
- A `bank_connection` belongs to the practice. It has a nullable `company`
  for the later CFO package (a client company's own bank); nothing sets it
  and no screen shows it.
- **Plaid only, behind a provider interface.** `apps/finance/bankfeeds/providers/`
  is the one place a provider is spoken to: `base.py` is the interface (link
  token, exchange, accounts, changes since a cursor, remove, read a webhook),
  `plaid.py` the implementation, `fake.py` the stand-in the tests and the demo
  seed use. A second provider is a module beside `plaid.py` and one line in
  `providers/__init__.py`; a connection remembers its provider's name, so both
  can run side by side.

## Settings

`PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENVIRONMENT` (`sandbox` |
`production`; anything else refuses to start). The same three names in both
environments. Only `providers/plaid.py` reads them; nothing logs or returns
them. Unset (either key empty), the feature is hidden: the Settings card does
not show, and the Import page says in one line that bank feeds are not set up
on this server.

**The webhook URL** is `PUBLIC_BASE_URL` + `/webhooks/plaid`; in production
`https://app.getexecutivesnow.com/webhooks/plaid`. It is sent to Plaid with
every link token, so a connection made in the app already carries it; enter
it in Plaid's dashboard as well.

## The data

- `bank_connection`: practice, `company` (empty), `provider` (`plaid`), Plaid's
  `item_id` (unique per provider), the institution's id and name, the access
  token **encrypted on the row with Fernet under `FIELD_ENCRYPTION_KEY`**, the
  key the practice's NMI keys are kept under (`crm.services.secrets`); status
  (`connected`, `needs_attention`, `disconnected`) with the code and detail
  that put it there; the sync cursor; last sync, last Check now, the last
  sync's counts and error; who connected and who disconnected, and when.
- `bank_feed_account`: one per account under a connection: Plaid's account id,
  name, official name, mask, type and subtype, **the ledger account it feeds**
  (one of the Finance accounts used on Reconcile) or `skipped` (not fed), the
  day the feed begins (`feed_from`), and the balance from /accounts/get (for a
  bank account what it holds, for a card what is owed) with when it was read.
- `bank_feed_transaction`: every transaction the feed has seen, by Plaid's id
  (unique per account): its date, amount, direction, description, Plaid's
  category, pending, **what became of it** (a new entry, a transfer by a rule,
  an invoice payment already recorded, the other side of a transfer, already
  in the books, ignored by a rule, before the feed began, in a closed month)
  and the entry it made or matched; `removed_at` when Plaid removed it.
- `finance_entry` gains `pending` and `bank_category`; its `source` gains
  `bank`, "From the bank feed".
- `notice.kind` gains `bank`, "A bank connection that needs you", offered in
  browser notifications to the practice owner only.

Migrations `finance 0016_bank_feeds` and `notify 0003_bank_feeds`, additive.

## Connecting

**Finance → Import** has a "Bank feeds" card with **Connect a bank**, the
connected banks in a line each, and a link to the full card. **Settings →
Finance → Bank connections** has Connect a bank too, and everything else.

1. The server makes a link token: products `transactions`, country `US`,
   365 days requested, our webhook URL, the client name from
   `config/branding.PRODUCT_NAME`.
2. The browser opens Plaid Link (Plaid's script, from its CDN, loaded only
   when Connect a bank is pressed).
3. The public token comes back to the server and is exchanged there; the
   institution's name is read (/item/get, /institutions/get_by_id) and the
   accounts and balances (/accounts/get) stored.
4. Each bank or card account **waits to be mapped** to a ledger account, or
   set to "Don't feed". Loan, investment and brokerage accounts arrive set to
   "Don't feed" (the owner can still map one). **No transaction is read while
   any account is undecided**, because reading moves the cursor past its lines.
5. Mapping an account sets where its feed begins: the day after the newest
   entry that ledger account already has from anywhere else (typed, imported,
   an invoice payment), never inside a closed month, never before the
   account's opening date. Lines before it are already in the books and are
   not brought in again. A ledger account is fed by one bank account at most.
   Mapping an account that was not fed starts the cursor over; lines already
   known are recognised by Plaid's id and not entered twice. An account whose
   feed has made entries keeps its ledger account; it can be stopped ("Don't
   feed"), and its entries stay.

The card lists each connection with its status, last sync, its accounts
(name, mask, balance, the ledger account it feeds, from when), and **Check
now**, **Reconnect** (shown when the connection needs attention; opens Link
in update mode with the connection's own token) and **Disconnect** (asks
first). It shows "5 bank connections included, then $0.50 a month each" and
how many the practice has. **Nothing is charged.**

## Sync

`/transactions/sync` from the stored cursor, every page, **applied in one
transaction, and only then is the new cursor stored**: a pass that fails
stores nothing, and the next reads the same changes again. When Plaid says
the data changed during paging (`TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`)
the pass starts over from its first cursor, three times at most.
**/transactions/refresh is never called.**

When it runs:

- **Nightly**, inside the existing daily Finance job
  (`finance.keep_month_forecast`, at the practice's midnight), before the
  month's forecast is kept. No new scheduled job.
- **Check now**, at most once an hour per connection (a second press within
  the hour is refused with the minutes to wait).
- **Plaid's `SYNC_UPDATES_AVAILABLE` webhook**, queued to the worker
  (`apps.finance.tasks.sync_bank_connection`).
- Once after mapping and after Reconnect.

What it does to the books (`bankfeeds/sync.py`):

- **Added** transactions are decided as a CSV import's lines are
  (`importer._Books` and the owner's rules): a line already typed in is not
  entered twice; a deposit for the amount of an invoice payment recorded
  within seven days places that payment in the account; a line that is the
  other side of a transfer already in the books is matched to it; a rule may
  ignore it, make it a transfer, or give it a category. Otherwise it becomes
  an entry marked "From the bank feed", in the category a rule gave it or in
  none, with **Plaid's category beside it as the suggestion** ("The bank
  suggests: Food and drink: coffee"). On a Mixed account (P6 M4) an
  uncategorized line waits in To sort.
- **Modified** transactions change their entry's date, amount and direction,
  and its description unless the owner has changed it. The category is the
  owner's and is never touched.
- **Removed** transactions remove their entry, with the reason "The bank
  removed this transaction (bank feed)", kept as every removed entry is.
- **Closed months.** A removal or a change of an entry dated in a closed
  month, or a new line dated in one, **raises a notice instead** and leaves
  the books alone; the same for an entry ticked in a finished reconciliation.
- **Pending** transactions are entries marked pending ("pending at the bank"
  on Entries). They are **never ticked or counted in a reconciliation until
  they post**. A posted transaction that names its pending one takes over
  that one's entry (its amount and date updated, the owner's category kept).
- Lines the feed brings in (and pending lines when they post) **arrive ticked**
  in the statement being worked on, as a bank file's do, and Reconcile marks
  them as from the bank.

**Balances.** Every sync reads /accounts/get. A fed account's balance is the
Forecast's **cash today** for that account while it is no more than 14 days
old (the Forecast says "from your bank feed on …"), and it is the bank's word
on Reconcile: offered as the month's ending balance when a reconciliation is
started in the month it was read ("Your bank feed said … on …"), and shown
beside the books in the balance view. The newer of a bank file's last balance
and the feed's is the one shown. The statement import stays for everything
else.

## Webhooks

`POST /webhooks/plaid`, public, CSRF-exempt, and **verified before anything
is read**: the `Plaid-Verification` header must be an ES256 JWT whose key id
names a key from /webhook_verification_key/get (cached; an expired key is
refused), signed by it, issued within five minutes, whose
`request_body_sha256` is the body's (compared in constant time). Anything
else is a 400 that changes nothing.

- `TRANSACTIONS` / `SYNC_UPDATES_AVAILABLE`: a sync is queued.
- `ITEM` / `ERROR` (for example `ITEM_LOGIN_REQUIRED`), `PENDING_DISCONNECT`,
  `PENDING_EXPIRATION`, `USER_PERMISSION_REVOKED`, `USER_ACCOUNT_REVOKED`:
  the connection **needs attention**, and the practice owner gets a notice
  (once a day per connection) that opens Settings → Finance with that
  connection outlined and **Reconnect** showing. A sync refused for a login
  reason does the same.
- `ITEM` / `LOGIN_REPAIRED`: back to connected.
- An item no connection has, or a disconnected one's: ignored.

## Disconnect

The item is removed at Plaid (/item/remove), the access token is destroyed,
the cursor cleared, and the connection kept as disconnected: the nightly job,
Check now and webhooks all leave it alone. **Every entry it brought in is
kept.** It no longer counts toward the five.

## The demo

Connecting is **refused** in the demo, as Gmail is, and so is everything that
would reach Plaid with the sample (Check now, mapping, Reconnect, Disconnect):
each says so. The seed makes one connection, **Front Range Bank**: Business
checking (fed to Front Range Bank checking), Business Visa (fed to the Visa)
and Business savings (not fed), and runs one sync **through the real sync
code** with the fake provider: five lines dated the day of the seed, two of
them pending, each with the bank's suggestion. Being dated today they fall
after the bank reconciliation in progress, which is unchanged. The nightly
job never syncs in the demo.

## Production with the keys unset

`/api/finance-bank/` says `available: false`; the Settings card is not shown;
the Import page shows one line: "Bank feeds aren't set up on this server yet,
so bring your bank's lines in with a file below." Every route that would
connect refuses.

## Proven, and how

- **Plaid's sandbox, end to end through the provider code:**
  `.venv/bin/python scripts/plaid_proof.py` makes a sandbox public token for
  First Platypus Bank with `user_good` / `pass_good` (the step Link does in
  the browser), exchanges it, reads the accounts, makes two sync passes and
  removes the item; it prints counts only. Run 2026-11-04: 14 accounts; first
  pass 16 added (after waiting for the sandbox's first pull); second pass, from
  the first's cursor, 176 added and 16 modified; item removed.
- **Tests with a fake provider** (`tests/test_bank_feeds.py`, 29 with their parameters): practice
  isolation (routes and webhooks), role boundaries (associate, assistant,
  client), the token encrypted and never in a response, the cursor across
  pages and passes, a failed pass keeping its cursor, rules, duplicates,
  modified and removed lines, pending lines kept out of a reconciliation and
  taking over their entry when posted, the closed-month rule, webhook
  verification (a real ES256 key made in the test; wrong key, old, altered
  body, unknown key id, HS256 and no header all refused), the item webhooks,
  Reconnect in update mode, a login error during sync, disconnect stopping
  the sync and keeping the entries, Check now once an hour, the nightly job,
  balances in the forecast and Reconcile, the demo's refusal, the feature
  hidden with the keys unset, and the Plaid provider's reading of amounts and
  categories and its restart on a mutation during paging.
- **Screens** (`frontend/src/components/BankConnections.test.tsx`): the card,
  mapping, Check now and its hour, Reconnect through Link in update mode,
  Connect through Link, the demo's refusal, Disconnect, hidden when not set
  up, and the Import page's card and its one line.
- **Headless Chrome** on a scratch demo, at 1366 and 390: Settings → Finance
  (the Bank connections card) and Finance → Import.
- **Not exercised:** Plaid Link in a real browser against the sandbox (the
  proof makes the public token the way Plaid documents for tests); a real
  webhook from Plaid (verification is tested with a key made in the test,
  in Plaid's scheme); production keys.

## Choices made (the simplest reading; each for a yes or a change)

1. **Nothing is read until every account is decided** (mapped or "Don't
   feed"). Loan, investment and brokerage accounts arrive as "Don't feed".
2. **The feed begins after the books' newest entry** for that ledger account
   (and after the lock), so an account with a year of imported statements
   does not get the year again. Plaid's 365 days are therefore used only for a
   ledger account with no history.
3. **A personal or split rule** (P6 M4) does not place a fed line on the
   personal side: the feed does not write the owner's ledger. Such a line is
   an uncategorized business line (To sort on a Mixed account). The Mixed
   account's small-line threshold is not applied to fed lines either.
4. **Plaid's category is shown, not applied.** Only the owner's rules set a
   category. A one-click "use the bank's category" is not built.
5. **Pending lines are in the books** (P&L and balance view) as entries
   marked pending; only Reconcile leaves them out until they post.
6. **A new line in a closed month is not entered**; the notice says to reopen
   the month and add it by hand. If the month is reopened later the line is
   not brought in again by itself.
7. **Check now's hour** is per connection and counts only Check now presses;
   the nightly sync, webhooks, mapping and Reconnect do not use it up.
8. **The count shown** is every connection not disconnected, including one
   that needs attention.
9. **The bank notice** goes to every practice owner of the practice, once a
   day per connection.
10. **Plaid's `name`** is the entry's description; its `merchant_name` only
    when there is no name.

## Next steps

1. **Client-company connections** (the CFO package): `bank_connection.company`
   is there; the work is the client's own books to feed, who may connect
   (the client owner from the portal, or the practice for them), and the
   screens.
2. **The per-connection charge**: beyond the five included, $0.50 a month
   each, on the practice's subscription (`apps/billing/subscriptions.py`),
   with the count taken on the 1st.
3. Later: Plaid Link in a real browser on production; a "use the bank's
   category" button and learning a rule from it; `NEW_ACCOUNTS_AVAILABLE`
   opening Link in update mode for account selection.
