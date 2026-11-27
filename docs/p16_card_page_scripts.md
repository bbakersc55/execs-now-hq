# P16 — Script controls on the card pages (2026-11-25, branch `card-page-scripts`)

Why (Bryan, 2026-11-24): the card processor's PCI questionnaire asks whether
the payment page scripts are monitored and protected. Until this, nothing
limited which scripts loaded on the card screens and nothing detected a
changed script. This build makes the answer true, in the spirit of PCI DSS
v4 requirements **6.4.3** (payment page scripts authorized, integrity
assured, inventoried with a reason each) and **11.6.1** (unauthorized changes
to the payment page's security headers and scripts detected and alerted, at
least weekly). For the whole platform, every practice.

The card screens (five) and their routes (three):

| Screen | Route | Component |
|---|---|---|
| Pay link | `/pay/<token>` | `PayLink` |
| In-app invoice payment | `/invoices` (client user) | `ClientInvoices` |
| Saving a card (card on file) | `/invoices` (client user) | `ClientAutopay` |
| Auto-pay setup (automatic billing's card) | `/invoices` (client user) | `ClientBilling` |
| A practice's own subscription card | `/settings/billing` (practice owner); any page of a suspended practice | `YourSubscription` |

Both card forms: NMI's Payment Component (npm `@nmipayments/nmi-pay`,
bundled into ENHQ's own scripts) and Collect.js from the processor's
white-label host (`https://<host>/token/Collect.js`). Their card fields are
the gateway's own frames on every screen (unchanged).

## The plan

1. **One policy for the app's pages, chosen by the server per page.** The
   React app is one document per page load, so a policy only on card routes
   would not hold after moving around inside the app. So every page of the
   app is served with the **card policy** (scripts from ENHQ and the gateway
   only), except the three bank-connection pages, which get the **bank
   policy** (the card policy plus Plaid's one script). The page tells the app
   which policy it was served with (`<meta name="enhq-page-policy">`).
   Moving inside the app from a card-policy page to a bank page, or back,
   reloads the page, so the server applies the other policy. A card form
   refuses to show on a page that isn't a card-policy page (it reloads into
   one), and also refuses if any script from anywhere else is on the page.
   Plaid can't load on a card-policy page: the policy blocks it, and the
   loader refuses first.
2. **Integrity.** The Payment Component is pinned to an exact version and
   npm checks its published hash on install (the lockfile); it ships inside
   ENHQ's own scripts. ENHQ's entry script carries a Subresource Integrity
   hash in the built page. Collect.js can't: NMI serves one unversioned file
   and changes it in place, so an integrity hash would stop every payment the
   day it changed. It is covered by the policy (that exact URL and nothing
   else from that host) and by the daily check (its content hashed and
   compared, any change alerted).
3. **Inventory.** `docs/card_page_scripts.md` lists every script that can run
   on a card page and why. `tests/test_card_pages_inventory.py` fails if the
   policy allows a script source the list doesn't have, if the list has one
   the code doesn't, if the app's code gains a new way to load a script, or
   if the Payment Component stops being pinned.
4. **Change and tamper detection.** A daily job (production) loads each card
   route as a browser gets it, records the security headers and every script
   (which, and a SHA-256 of each one's content, the bundle's own lazily loaded
   parts and Collect.js included), and compares them with the last approved
   state. Any difference alerts the platform owner (a Notice in the app and
   an email). Browsers report every policy violation to `/csp-report`; each
   new kind is stored and alerts the platform owner too. At release, after
   the deploy, `manage.py card_pages approve --note "Release N"` shows what
   changed and records it as approved: the deliberate step, so a release
   raises no false alarm.
5. **No broken payments.** `scripts/card_pages_proof.py` proves on the laptop
   sandbox, with the policy enforced, that both card forms load and produce a
   token on all five screens, that moving into a card screen from a bank page
   inside the app lands on a card-policy page, and that a script from
   anywhere else (Plaid's) is blocked there. No sale and no vault record: the
   token is caught on its way to the server. The switch to report-only is
   `manage.py card_pages mode report-only` (instant, no deploy).
6. **The record for Bryan's files**: `docs/pci_card_page_scripts.md`, one page.

## Questions, and the default taken (Bryan was away; each can be changed)

1. *Policy on card routes only, or every page?* **Every page of the app**,
   except the three bank pages (bank policy), as above: the only way it holds
   inside a one-page app.
2. *Which parts of the policy?* **Scripts** (`script-src`: ENHQ, the gateway's
   Collect.js URL(s) in use, nothing else; no inline, no eval), **frames**
   (`frame-src`: ENHQ, blob previews, the gateway's hosts), `object-src
   'none'`, `base-uri 'self'`, `worker-src 'self'`, `frame-ancestors 'none'`,
   and reporting. Images, styles, fonts and connections are left open: files
   go to and come from cloud storage, and nothing that isn't approved can run
   to use them.
3. *Exact script URLs or whole hosts for the gateway?* **Exact URLs**
   (`https://<host>/token/Collect.js`), only the ones this server's settings
   can use.
4. *Bank pages*: `/finance/import`, `/finance/personal/import`,
   `/settings/finance` (where "Connect a bank" is). Moving in or out of them
   reloads the page once.
5. *The report-only switch*: a management command, effective at the next page
   load, no deploy: `card_pages mode report-only` and `card_pages mode
   enforce`. It applies to both policies. The daily check reports the change
   (the header changes), so it can't be left on unseen.
6. *Daily check*: **13:00 UTC** (6:00 in Utah in winter), production only (the
   demo has no worker, the laptop is not live). Loads `/pay/…`, `/invoices`,
   `/settings/billing` signed out: the page and its scripts are the same for
   everyone, so no robot sign-in.
7. *Alerts*: the platform owner(s), a Notice (kind "Card payments that need
   you") and an email (platform mail, new Outbox producer `card_page_alert`).
   A change alerts when it is new, and again weekly while it stands
   unapproved. A violation alerts the first time its kind is seen, at most 20
   alerts a day; reports caused by browser extensions are kept but don't alert.
8. *What a violation report keeps*: the page's path with tokens and ids
   masked, no query strings, the directive, what was blocked (address without
   its query), the script file and line, the first 80 characters the browser
   sampled, the browser's user agent (cut to 200), counts and dates. No IP
   address.
9. *Approving*: `card_pages approve --note "…"` after each release; it prints
   the differences first. The first approval happens at the release of this
   build. Until then the daily check says there is no approved state.
10. *SRI on ENHQ's own scripts*: the entry script only. Browsers have no
    integrity check for lazily loaded parts; those are covered by the policy
    (ENHQ's own origin) and the daily content hashes.
11. *Demo*: the policies apply there too (same code). No daily check (no worker).
12. *Found while proving it*: Collect.js adds Apple's Apple Pay script
    (`applepay.cdn-apple.com`) every time it starts, whatever its settings.
    **Default: keep it blocked** (it isn't the gateway's, and Apple Pay isn't
    offered); the card fields work without it on every screen. Browsers report
    the block on each Collect.js page load; those reports are kept as expected
    (`reports.EXPECTED`) and never alert. If Apple Pay is ever wanted, it is a
    new entry in the inventory and the policy, decided then.

## What was built

**The policy** (`apps/cardpages/policy.py`, applied in `config/spa.py`'s
`app_shell`, which serves every page of the app). The card policy, with
production's settings (white-label host):

    script-src 'self' 'report-sample' https://secure.vaultixpay.com/token/Collect.js;
    frame-src 'self' blob: https://secure.nmi.com https://secure.vaultixpay.com;
    worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none';
    report-uri https://<app host>/csp-report; report-to card-pages

with `Reporting-Endpoints: card-pages="https://<app host>/csp-report"`. The
bank policy adds `https://cdn.plaid.com/link/v2/stable/link-initialize.js` to
`script-src` and `https://cdn.plaid.com` to `frame-src`. Each page carries
`<meta name="enhq-page-policy" content="card|bank">`. The laptop's dev
server (APP_ROOT_URL on port 5200) is redirected to as before, without a
policy; production, the demo and a laptop serving the built bundle get it.

**In the app** (`frontend/src/lib/pagePolicy.ts`): the app's root
(`usePagePolicy` in `App.tsx`) reloads the page whenever the address needs the
other policy, once per address (a second try for the same address is refused,
so a disagreement can never loop). `NmiCardForm` shows its fields only when
`cardFormRefusal()` is empty: the page was served with the card policy and no
script element from anywhere but ENHQ and the gateway's Collect.js is on it.
On a bank page it reloads as a card page (the address itself, or the app's
start for a suspended practice's owner on a bank address); otherwise the payer
reads that nothing was charged or saved, and the form-failed report tells the
practice owner (or the platform owner, for a subscription card).
`loadPlaidLink` refuses on a card page.

**Integrity.** `frontend/vite.config.ts`, `subresourceIntegrity()`: after the
build writes its files, each `<script src="/static/…">` in `dist/index.html`
gets `integrity="sha384-…"` from the file as written. Static files are copied
unchanged by `collectstatic` (no manifest storage), so the hash holds.

**Reports** (`apps/cardpages/views.py`, `reports.py`): `POST /csp-report`,
outside `/api/`, CSRF-exempt, 16 KB at most, 120 an hour per address. Both
report shapes are read. Kept as one row per kind (`card_page_violation`),
counted. Alerts: first sight of a kind, not an extension's, at most 20 a day.

**The daily check** (`apps/cardpages/check.py`, `tasks.py`): the platform
schedule `platform.card_pages_check` (`ensure_schedules`, new
`PLATFORM_SCHEDULES`), 13:00 UTC, production only. Reads `/pay/card-page-check`,
`/invoices`, `/settings/billing` at `PUBLIC_BASE_URL` with a browser's
headers; records the security headers (`content-security-policy`, its
report-only form, `reporting-endpoints`, `x-frame-options`,
`x-content-type-options`, `referrer-policy`, `strict-transport-security`,
`permissions-policy`, `cross-origin-opener-policy`), each page's script and
module-preload addresses and their integrity attributes, any inline script's
hash, and then every script: the bundle's lazily loaded parts are found by
following its imports, and Collect.js's address comes from the policy. Each
is hashed (SHA-256). Compared with the newest approval (`card_page_baseline`);
each look is kept (`card_page_check`). A changed ENHQ script is said to be
either exactly the release's own file (a deploy not yet approved) or no file of
the running release. Alerts: a finding new since the last alert, and the same
finding again after a week; a page that can't be read, once a day.

**Alerts** (`apps/cardpages/alerts.py`): every platform owner, a Notice in
their own practice (kind "Card payments that need you", no link) and an email
by platform mail (Outbox producer `card_page_alert`, `crm 0064`, no SQL).

**The command** (`manage.py card_pages`): `status`, `mode enforce|report-only`
(the quick switch), `check`, `approve --note`, `state` (what a check reads, as
JSON). `--base URL` reads another server (the laptop proof).

**Data and migrations.** `cardpages 0001` (four new tables:
`card_page_setting`, `card_page_baseline`, `card_page_check`,
`card_page_violation`; nothing else touched), `crm 0064` (the new producer,
no SQL). Platform tables, no practice in them.

## The switch, if a real payer is ever blocked

    railway ssh --service qcluster -- python manage.py card_pages mode report-only --by "Bryan" --note "why"

From the next page load every app page sends `Content-Security-Policy-Report-Only`
instead: nothing is blocked, every violation is still reported (and alerts).
The card form's own check (a card page, nothing from elsewhere on it) stays on.
Back: `card_pages mode enforce`. The daily check reports the changed header
until it is approved, so report-only can't be forgotten.

## At release

1. Migrations `cardpages 0001` and `crm 0064`, by the runbook's sequence.
2. `ensure_schedules` (R5b): creates `platform.card_pages_check` once.
3. No new variable. The policy follows `NMI_API_HOST` (production:
   `secure.vaultixpay.com`, so its Collect.js is the one allowed).
4. Check the live headers:
   `curl -sI https://<app host>/invoices | grep -i -E "content-security|reporting"` shows
   the card policy above, enforced; the same for `/pay/x` and
   `/settings/billing`; `/finance/import` shows the bank policy.
5. Open a live card form without paying, with the browser's console open.
   Two ways in:
   - **A practice that isn't billed** (Executives Now: Settings, Billing has no
     "Replace the card"). Go to a test client's company page; in its portal
     access, click "Act as" on that client's Client owner. Go to Invoices; in
     the "Card on file and auto-pay" box, click "Save a card" (or "Replace
     the card"); then Cancel. Stop acting from the banner. This is how
     Release 54 did it, acting as the Client owner of Acme Facilities.
   - **A billed practice**: its own subscription card in Settings, Billing,
     "Replace the card", then Cancel.

   What passes: the card number, expiry and security code fields appear,
   served from the gateway's host (`secure.vaultixpay.com`), and you type
   nothing. The only policy line is the expected one: Collect.js's Apple Pay
   script refused. There is no other "Refused to" or "Content Security
   Policy" line.

   Starting "Act as" also logs a burst of 403 and 404 answers in the console.
   They predate P16 and are harmless; see the handoff's cleanup list.

   The laptop proof tokenized on NMI's sandbox; with sandbox keys, Collect.js
   from the white-label host is proven only to load under the policy, not to
   tokenize. `card_pages status` shows any violation browsers have reported
   since.
6. The first approval: `card_pages approve --note "Release N: P16, the first"`
   (runbook R6b), then `card_pages check` says "As approved".
7. From then on, R6b at every release.

## Limits (what this doesn't do)

- The check reads the pages; it doesn't run them. A script added at run time
  by another script is caught by the policy (blocked) and the browser's
  report, not by the check.
- The gateway's own frames are the gateway's; what runs inside them is NMI's,
  under NMI's PCI compliance.
- `connect-src`, `img-src`, `style-src`, `font-src` are open (question 2).
- Browsers can't check the integrity of the bundle's lazily loaded parts, nor
  of Collect.js; both are allowed only from their exact origin/address and
  hashed daily.
- A browser extension a payer installed can still run in its own isolated
  world; that is the payer's browser, outside any page's control.

## Proof (2026-11-25, laptop, NMI's sandbox)

`scripts/card_pages_proof.py`, built from this tree as production builds it
(the entry script's integrity hash in the page), its own throwaway database,
headless Chrome. Results and a screenshot of each screen:
`~/enhq-walks/card-page-scripts/` (`proof.json`). With the policy enforced:

| Screen | Payment Component | Collect.js (secure.nmi.com) |
|---|---|---|
| 1. Pay link | token, no violation | token; only Apple's script blocked (expected) |
| 2. In-app invoice payment | token, no violation | token; only Apple's script blocked |
| 3. Saving a card (card on file) | token, no violation | token; only Apple's script blocked |
| 4. Auto-pay setup (automatic billing's card) | token, no violation | token; only Apple's script blocked |
| 5. Subscription card, reached by moving inside the app from a bank page | token, no violation | token; only Apple's script blocked |

Also proved, both runs: every page answered with the enforced policy (not
report-only) and said "card"; Plaid's script, put on a card page, was blocked
and never ran; on the bank page the bank policy allowed Plaid and it loaded;
moving inside the app from there to Settings, Billing reloaded the page as a
card page, Plaid gone, and the card form worked. Collect.js from the
white-label host (secure.vaultixpay.com) loaded under the policy with no
violation but Apple's (the sandbox key is unknown on that host, so it drew no
fields: proven to load, not to tokenize). The daily check read the built
pages (the entry script, its integrity hash, the Payment Component's chunk)
and found them as approved. No sale and no vault record: no payment attempt,
payment, card on file or subscription card in the database afterwards; each
token was caught on its way to the server.
