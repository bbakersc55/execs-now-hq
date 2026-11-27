# Card page scripts: the inventory

Every script that can run on a page of the app that shows a card form, and
why it is needed (PCI DSS 6.4.3). The card pages are every page of the app
except the three bank pages; see docs/p16_card_page_scripts.md. The policy
in force allows exactly these sources and nothing else
(`apps/cardpages/policy.py`, `SCRIPTS`). `tests/test_card_pages_inventory.py`
fails if this table and the code part, so a new script source can't be
added to the pages without being added here.

Keep the table's form: one row per source, the source in backticks in the
first column.

| Source | On | When | What it is, and why it is needed |
|---|---|---|---|
| `'self'` | card and bank pages | always | ENHQ's own scripts, served from ENHQ's own address under `/static/assets/`: the app itself, and NMI's Payment Component (npm `@nmipayments/nmi-pay`, pinned at 1.1.1, its published hash checked by npm on install), which is built into it and draws NMI's card frames. The entry script carries an integrity hash (SRI). |
| `https://secure.vaultixpay.com/token/Collect.js` | card and bank pages | when `NMI_API_HOST` is `secure.vaultixpay.com` (the processor's white-label host) | Collect.js, the gateway's own script, which draws the card fields in the gateway's frames for accounts on the white-label host. The gateway requires it be loaded from its host. No integrity hash: the gateway serves one unversioned file and changes it in place; the daily check hashes it and alerts on any change. |
| `https://secure.nmi.com/token/Collect.js` | card and bank pages | only when `NMI_SANDBOX_CARD_FORM_HOST` is `secure.nmi.com` (the laptop's sandbox proof) | The same Collect.js from NMI's own host, so the laptop can prove the form a white-label account gets with NMI's sandbox keys. Not in production's policy. |
| `https://cdn.plaid.com/link/v2/stable/link-initialize.js` | bank pages only | always | Plaid Link, which connects a bank account for bank feeds. Plaid requires its own script. Never on a card page: the card policy blocks it, the bank pages never show a card form, and moving between the two reloads the page. |

## What else is on a card page, and is not a script of ours

- **The gateway's frames**: the card number, expiry and security code are
  typed into NMI's own frames (`https://secure.nmi.com/...` for the Payment
  Component, the Collect.js host's for Collect.js). What runs inside them is
  the gateway's, in the gateway's own page; the card policy allows frames
  from those hosts only (and ENHQ's own, for PDF previews).
- **Apple's Apple Pay script** (`https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js`):
  Collect.js adds it to the page every time it starts, whatever its settings.
  It is **not** allowed: the card policy blocks it, Apple Pay is not offered,
  and the card fields work without it (proved on the sandbox,
  scripts/card_pages_proof.py). Browsers report the block each time; those
  reports are kept as expected and never alert (`reports.EXPECTED`).
- **Browser extensions** a payer has installed can run their own code; the
  policy blocks the scripts they add to the page, and browsers report it
  (kept, not alerted: docs/p16_card_page_scripts.md).

## How each is kept as approved

| Source | Authorized by | Integrity | Watched |
|---|---|---|---|
| ENHQ's own | the release (code review, the gate) | entry script: SRI; every script: hashed daily | daily check, against the approval made at release |
| Collect.js | this list, exact address in the policy | can't be pinned (changed in place by the gateway) | daily check: its content hash; a change alerts |
| Plaid Link | this list, bank pages only | can't be pinned (Plaid's "stable" file) | not on card pages; blocked there and reported if tried |
