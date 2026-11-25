# Payment page scripts: what is in place (PCI DSS 6.4.3 and 11.6.1)

Execs NOW HQ, for every practice on the platform. Built 2026-11-25
(docs/p16_card_page_scripts.md); in force from the release that carries it.

**The payment pages.** Five screens take a card: the pay link, paying an
invoice in the client portal, saving a card on file, automatic billing's
card, and a practice's own subscription card. On all five the card number,
expiry and security code are typed into the card gateway's (NMI's) own
frames, through NMI's Payment Component or NMI's Collect.js from the
processor's host. ENHQ's pages, servers, logs, emails and database never
receive them; ENHQ receives a one-time token.

**What is in place**

| Control | How | PCI DSS |
|---|---|---|
| Only authorized scripts run | Every page of the app is served with an enforced Content Security Policy allowing scripts only from ENHQ's own address and the gateway's exact Collect.js address; no inline script, no eval. The three bank-connection pages add Plaid's script and never show a card form; moving between the two kinds of page reloads it, so the policy holds however a payer reaches a card screen. A card form also refuses to show if any other script is on the page. | 6.4.3 (authorized) |
| Integrity of each script | ENHQ's scripts come only from ENHQ's own address; the entry script carries an integrity hash (SRI); NMI's Payment Component is pinned to an exact version whose published hash npm verifies at build. Collect.js can't carry a hash (the gateway changes the file in place): only its exact address is allowed, and its content is hashed daily. | 6.4.3 (integrity) |
| Written inventory, with why | docs/card_page_scripts.md: each script source, where, when and why. An automated test fails the build if the policy and the inventory differ, or the code gains a new way to load a script. | 6.4.3 (inventory) |
| Change and tamper detection | Daily, an automated job loads each payment page as a browser does and compares its security headers and every script (which ones, and a SHA-256 of each one's content) with the approved state. Any difference alerts. Each release's changes are approved as a deliberate step after deploying. | 11.6.1 |
| Browser reports | Every browser that blocks a script on these pages reports it; each new kind is recorded and alerts (extensions' reports are kept, not alerted). | 11.6.1, 6.4.3 |
| Emergency switch | One command turns the policy to report-only (scripts still reported, not blocked) if a real payer were ever blocked; the daily check flags the change until approved. | — |

One known block: the gateway's Collect.js asks for Apple's Apple Pay script
each time it starts. It is not on the inventory, so the policy blocks it;
Apple Pay is not offered and the card fields work without it (proved on the
gateway's sandbox). Those reports are kept and marked expected.

**What is checked, how often, and who is told**

| Check | When | Alert |
|---|---|---|
| Security headers and scripts of the three payment routes, against the approved state | daily, 13:00 UTC (PCI asks at least weekly) | the platform owner: a notice in the app and an email; again weekly while a change stands unapproved |
| A browser reports a blocked script | as it happens | the platform owner, the first time each kind is seen (at most 20 a day) |
| The policy and the inventory agree | every build (the test suite) | the build fails |
| Changes by a release | each release, after deploying | approved by the platform owner (`card_pages approve`), recorded with who, when and why |

**Who is responsible.** The platform owner (Bryan Baker) approves each
release's script changes, receives every alert, and reviews them. Records:
approvals, every daily check and every reported violation are kept in ENHQ's
database (`card_pages status` shows them).
