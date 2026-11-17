# P9 — the People Command Center, with an HRIS (decided 2026-11-12, not built)

**Status: the security foundation is built on branch `people-hris`
(2026-11-17), not merged; the employee records come next.** See "Built
2026-11-17: the security foundation" at the end. Bryan decided the scope on
2026-11-12. It comes third in the build order:

1. the SkyRun bonus;
2. the rest of the Operations Command Center (the SOP studio, the plans
   engine, the worksheet engine with four tools and the tool builder, the
   connector rails);
3. **People, with the HRIS** (this spec);
4. Technology.

People is the second Command Center, in the frame `docs/p8_command_centers.md`
built (its catalog row is already there, "coming", marked "Next"). This takes
the place of the "simple HRIS" in `CLAUDE.md`'s post-Beta list.

## Who sees what

- **The practice manages the employee records** of each client company.
- On the client's side, in the portal:
  - **the client owner and senior leaders see everyone**;
  - **a manager sees their direct reports**;
  - **each employee sees their own record**.

## The employee record

A record holds:

- name;
- contact details;
- address;
- emergency contact;
- title;
- team;
- manager;
- employment type (**contractors included**);
- work state;
- start date;
- status;
- pay rate;
- documents.

### Offer letters

- Offer letters go through **the app's own e-signature** (`docs/p6_esign.md`).
- **A signed offer creates the employee record and starts onboarding.**

### Never stored

The app never stores any of these:

- bank details;
- Social Security numbers;
- I-9 documents;
- medical and leave paperwork;
- background checks;
- benefits.

The employee gives those to the payroll provider directly. Where the app shows
one at all, it shows **only the masked last four, read live** from the
provider and never kept.

## Onboarding and offboarding

- **Checklists in three sections: People, IT and Manager.** Each section has
  standard items, and each client adds **custom fields of its own**.
- **Each employee has an access list** of the systems they use.
- **Offboarding builds the revoke tasks from the access list.**
- **Offboarding never terminates anyone in payroll automatically.** Payroll
  is changed by a person, in the payroll provider.

## Security

- **Two-factor sign-in by authenticator app, with backup codes.** It is
  **required for anyone with an HR permission**.
- **Everyone is signed out after 12 hours.**
- **People screens ask for the code again after 4 hours.**
- **HR access is a permission, not a role.** Two to start:
  - **HR Director** sees everything the app holds;
  - **HR Generalist** sees the sensitive fields masked.
- **Pay and personal fields are encrypted.**
- **Every view and every export is logged.**
- **Connected AI apps never see People data.** No MCP tool reads it
  (`docs/p7_mcp.md`).

## The state rules library

- **The first five states:** Utah, California, Colorado, Arizona and Nevada.
- **Thirteen topics** per state.
- **Each rule links to the state's own source** and carries a **last-verified
  date**.
- **Re-checked every quarter**, with **Bryan approving any change** before
  it shows.
- **Every People screen says "HR guidance, not legal advice".**

## The six rated areas

1. Hiring
2. Onboarding and offboarding
3. Pay and benefits
4. Performance
5. Managers
6. Compliance

## Pulse surveys

- **Anonymous or named, chosen per survey.**
- **An anonymous survey's results show only after five responses.**

## Price

- **The HRIS is included in the People Command Center** at $50 a month.
- **Employees count as client users**, at **$10 per block of 25**.

## Later

- **Version two:** time off.
- **Version two or later:**
  - an applicant tracking system;
  - the Gusto connection;
  - the QuickBooks connection.
- **Gusto's partner program** needs a pre-approval and a security review. The
  security work above is built so it doubles as that paperwork.

## Open, to settle before the build

These are not decided. They are not guesses at answers, just the gaps.

1. **The thirteen topics.** The decision fixed how many there are, not their
   names. They are written here before the library is built.
2. **Where "the masked last four, read live" comes from in version one.**
   It is read from the payroll provider, but the Gusto connection is version
   two or later. Until a connection exists, version one either shows nothing
   there or reads from another provider; which one is not decided.
3. **"Everyone signed out after 12 hours."** *Decided 2026-11-17:* counted
   from sign-in, for everyone on both sides, every practice.
4. **Who holds the HR permissions.** *Decided 2026-11-17:* both sides (see
   below).
5. **The thirteen topics.** *Decided 2026-11-17:* minimum wage; overtime
   thresholds; pay frequency and final-pay deadlines; meal and rest breaks;
   paid sick leave and vacation payout; new-hire reporting; required
   postings; harassment-training mandates; pay transparency; non-compete
   limits; E-Verify; state family leave; record retention. (The library is a
   later build.)
6. **Social Security digits.** *Decided 2026-11-17:* none are shown or typed
   anywhere in version one; the app says "held in payroll".

## Built 2026-11-17: the security foundation

On branch `people-hris`, not merged into `dev`. The records themselves arrive
in the next build; a **placeholder person** stands in to prove every gate.
Migrations: `accounts 0007_two_factor`, `people 0001_security_foundation`
(both additive: new tables only) and `centers 0005_people_available` (one
row of the platform's catalog: People's status and description). Code:
`apps/accounts/two_factor.py`, `apps/accounts/totp.py`,
`apps/accounts/middleware.py`, `apps/people/`.

### Two-factor sign-in

- **By authenticator app only** (RFC 6238: six digits, a 30-second step, one
  step either side, never the same step twice). No text messages.
- **Anyone may turn it on under Profile**: a QR code and the same key to
  type, confirmed with a code; then **ten single-use backup codes**, shown
  once (only their hashes are kept) and replaceable with a code. Turning it
  off takes a code, and is refused to anyone holding an HR permission.
- **After any sign-in method** (Google, Microsoft, an emailed link), a person
  with it on reaches nothing but who they are, the branding, the code prompt
  and signing out until a code (or a backup code, once) is entered
  (`TwoFactorGate`). An AI app's consent page waits too.
- **Required for anyone holding an HR permission**: People screens refuse
  them (`two_factor: "enroll"`) until they have set it up.
- **The key is encrypted** like the other secrets (Fernet, the key in the
  environment). **Codes are rate limited**: five tries in five minutes per
  person, the enrolling one included, and twenty per address.
- **A lost phone**: a practice owner resets it for their team and their
  clients' users (on Staff), a client owner for their own people (on Your
  team), the platform owner for a practice owner (on Practices). Each reset
  is an audit event and the person is told by email; they set it up again.

### Sessions

- **Everyone is signed out 12 hours after signing in**, staff and client users
  alike (`SignInLifetime`), whatever the sign-in method. A client's session,
  30 days before, is 12 hours. Staff's still ends when the browser closes.
- **A warning** shows in the last ten minutes: when, and to save. What is
  saved, drafts included, is kept; the app keeps no browser copy of unsaved
  text, so the warning says to save.
- **What it does not touch**: connected AI apps (they hold OAuth tokens, not
  sessions: they keep working; only the consent page, a session, asks for the
  code); the public pay and signing links (no session); the mobile install (a
  browser session like any other: it signs in again after 12 hours).

### The People re-check

People screens ask for the code again when this session's last one was
entered more than **four hours** ago (`two_factor: "recheck"`). Only People
asks; the rest of the app does not.

### HR permissions

- **By person, not role.** **HR Director** sees everything the app holds;
  **HR Generalist** sees the sensitive fields masked.
- **The practice owner** is HR Director for the practice and every client, and
  grants either level to anyone on the practice team (associates and
  assistants), for one client company, the practice's own people, or all.
- **A client owner** is HR Director for their own company and grants either
  level to their own people (client team members), for that company only.
- **Without an HR permission:** the client's senior leadership (a team
  leader, or someone who leads every team) sees the directory fields of
  everyone; a manager the directory fields of their direct reports and their
  own record; an employee their own record. **Nobody else gets People data at
  all, and the answer is 404, not 403.**
- **Sensitive fields:** pay rate, home address, date of birth, personal phone
  and email, emergency contact, and documents. Directory fields: name, title,
  team, work email, manager.

### Encryption and the access log

- **Sensitive fields are encrypted at rest**, together, as one Fernet token.
- **The access log** records every view, change and export of a person's
  sensitive data, unmasked: who, when, whose, which fields, and from where
  (address and browser). The practice owner and the client owner read it for
  their scope under **People → Access log**. **Nobody can edit it**: no route
  changes it, and the database layer refuses a change or a delete.

### Connected AI apps and in-app AI

- **No AI app tool returns People data**, and search leaves it out
  (`tests/test_people_security.py` calls every read tool with People data in
  place and finds none of it). No AI code imports People, and People imports
  no AI: in-app AI touches a record only when a person presses an action on
  it (none exists yet).

### The Command Center

People is **available** in the catalog at $50 a month, **free for the platform
owner's practice**. Turned on, the app shows **People**: a page per company
(and the practice's own people) at the person's level, with **Permissions** and
**Access log** for the practice owner and the client owner, and **"HR
guidance, not legal advice"** on every People screen.

### The demo

Visitors can set up two-factor under Profile and try it, and are **never
locked out**: in the demo (`APP_ENVIRONMENT=demo`) the code is never asked for
at sign-in, People never requires it and never re-checks. Profile says so.

### Choices made (the simplest reading)

- Two-factor is per person, across practices: one reset clears it wherever
  they sign in.
- A person's own record is shown to them in full; it is theirs.
- An HR Generalist's masked view is not logged (no sensitive data shown); an
  HR Generalist exports masked.
- Only an HR Director adds or changes a placeholder person.
- The rate limit counts every try, a right one included.
- Practice owners and client owners count as holding an HR permission only in
  a practice that has People on: elsewhere two-factor stays optional for them.

### What changes for existing users at release

- Everyone signed in is signed out at most 12 hours after their first request
  after the release (a session from before is given its 12 hours from then).
  **Client users, used to 30 days, sign in again each day they use it.**
- Nobody is asked for a code until they turn two-factor on; nobody is made to
  turn it on until People is on and they open a People screen holding an HR
  permission.
- The practice owner and client owners of a practice that turns People on
  must set up two-factor before People opens for them.

### To check once it is merged

- Turn People on for the owner's practice; set up two-factor on a phone's
  authenticator app; sign out and in: the code is asked for.
- Sign in as a client owner by emailed link: the session ends 12 hours later.
- An AI app (Claude) still answers through its connection after the release.
- A pay link and a signing link still open with no sign-in.
- Install the app on a phone: after 12 hours it asks to sign in again.

