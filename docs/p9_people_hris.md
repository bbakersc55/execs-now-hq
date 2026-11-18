# P9 — the People Command Center, with an HRIS (decided 2026-11-12)

**Status: the security foundation and the employee records are built on
branch `people-hris` (2026-11-17), not merged.** See "Built 2026-11-17: the
security foundation" and "Built 2026-11-17: the employee records" at the end.
Still to build: the state rules library, the six rated areas and pulse
surveys. Bryan decided the scope on
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

## Built 2026-11-17: the employee records

On branch `people-hris`, on the foundation above; not merged into `dev`.
Migration `people 0002_employee_records` (additive: nine columns on
`person_record` and six new tables; its only `ALTER COLUMN` drops the default
Django adds to fill `custom_values` on existing rows). Code:
`apps/people/services.py` (the record, its sections, the directory, exports),
`checklists.py` (checklists, the access list), `hiring.py` (offer letters and
documents to sign), `files.py` (documents), `apps/centers/content/people.py`
(what People ships), `apps/tenancy/demo/people.py` (the demo).

### The record

- **Per client company, and for the practice's own team.** A record links to
  the person's portal sign-in where they have one; people without one still
  have a record.
- **Directory fields** (anyone who reaches the person): name, title,
  department, team, work email, work phone, manager.
- **Employment fields** (HR permissions and the person themself, unmasked):
  status (offer out, onboarding, active, on leave, offboarding, ended),
  employment type (employee full-time or part-time, contractor), work state,
  start date, the company's own fields, the access list, the checklists.
- **Sensitive fields** (encrypted together; an HR Director and the person in
  full, an HR Generalist masked, every view logged): pay rate with its unit
  and effective date, home address, date of birth (optional), personal phone
  and email, emergency contact, and documents (offer letter, handbook
  acknowledgment, reviews, exit interview, other).
- **Never stored, and no field for them**: Social Security numbers, bank
  details, I-9 documents, medical and leave paperwork, background checks and
  benefits. The record says these are held in payroll; the upload says not
  to add them; a custom field whose label names one is refused.
- **Custom fields per client**, on the record, on onboarding and on
  offboarding; added, renamed, reordered and archived by an HR Director.
- By hand, a status moves between active and on leave; offer out follows its
  letter, and onboarding, offboarding and ended follow their checklists.
- **Client users**: a company's portal sign-ins and its employee records,
  each person once, ended records not counted, in blocks of 25 at $10. The
  practice owner sees the count on People.

### The People page

- **The directory** with search and filters (status, department, type, work
  state); nothing sensitive is in it, at any level.
- **The org chart**, drawn from managers by the tools' own drawing
  (`apps/tools/orgchart.py`, joined by id, not by title).
- **Headcount by status**, for HR permissions.
- **The next 30 days**: work anniversaries and birthdays, a birthday as its
  day and month only, for HR permissions and senior leadership.
- **A person's page** by section: directory, employment, pay, personal,
  documents, access list, checklists, each following the HR permission rules,
  with every unmasked view in the access log.

### Hiring

- A new record can start as **offer out**. **Send the offer letter** (an HR
  Director's: it carries pay) merges People's offer template
  (`people_offer_letter`) with the record's title, pay, start date, type,
  work state and manager, and puts its request in the Outbox for approval, as
  every signature request is. The pay going into the letter is logged as
  exported.
- **When the candidate signs, the record moves to onboarding and the
  onboarding checklist starts**, as whoever sent the offer. Countersigning
  works as it does today, from Documents.
- The handbook acknowledgment goes the same way to an employee to sign.

### Checklists and the access list

- **Onboarding and offboarding**, each in three sections (People, IT,
  Manager), start as a copy of People's standard items and are each
  company's own to add to, edit, reorder and archive.
- **Starting one makes each item a task in Work**, its owner and due date
  set from the start date or the last day. Owners: People items go to
  whoever starts it, IT items to the IT owner chosen then, Manager items to
  the manager's sign-in, an item for the person to their own sign-in;
  without one, to whoever starts it. **Done in Work is done here.**
- **The access list**: every system, email account, phone number, piece of
  equipment and key given, with when and by whom.
- **Offboarding** takes a last day and a reason, builds a revoke task for
  every entry still given (and for one added while it is open), and **closes
  only when each item is done, or waived with a note**; then the person is
  ended. **It never ends anyone in a payroll system**, and says so.

### Who sees what People puts elsewhere

- **Checklist tasks** are the practice's: not client-visible in Work; to the
  practice owner, their owner or assignee, and HR permissions for that
  company. A client user owning one finishes it on People.
- **People's documents for signature** are in Documents only for an HR
  Director of that company; in the portal only for the client owner and the
  person they are for. Signing one moves nobody on a pipeline.
- **The contact an offer is sent to**, when People made it, is never in
  Contacts or search.
- **Their requests in the Sending queue** only for an HR Director there.
- **AI apps see none of it**: every AI app's request is marked (`ai_app`),
  and the shared scopers (tasks, documents, contacts, the Outbox) leave
  People's rows out; search leaves them out for everyone.

### The portal

- **An employee** sees their own record, their documents to sign and the
  checklist items assigned to them, and marks those done.
- **A manager** sees their direct reports' directory fields and checklist
  progress, and their own items.
- **The client owner** sees everything for their company.

### Exports

- **The directory as a spreadsheet** (CSV), for HR permissions; sensitive
  fields only when an HR Director asks for them. **Every export is in the
  access log**, person by person, with the fields it held.

### The demo (seeded once this is merged)

People on for Summit; Acme Fasteners' fifteen people as records with
managers and departments (twelve linked to their portal sign-ins); Lola
Bunny's offer out for signature; Bugs Bunny's onboarding about half done;
Sylvester Pussycat's offboarding with his access list being revoked (two of
five done); and Ted Lasso, an associate, HR Generalist for Acme.

### Proved

- **Tests**: `tests/test_people_records.py` (every permission level against
  every sensitive field; the record's rules; custom fields; the directory;
  hiring through a real signature and countersigning; the offer reaching only
  HR Directors; onboarding tasks with owners and due dates; tasks in Work by
  person; offboarding and revoke tasks; each company's items; exports and the
  log; documents; the portal; AI apps still seeing nothing; isolation; the
  foundation's gates on every new route), `tests/test_people_security.py`
  (Part 1's, updated where the directory no longer carries sensitive
  fields), `tests/test_demo_seed.py`, and the screens'
  (`frontend/src/screens/PeopleRecords.test.tsx`).
- **Headless Chrome on the real `seed_demo`**: `scripts/people_records_walk.py`
  (with `manage.py people_records_walk_setup`), at 1366 and 390, a real
  session for each level, two-factor set up with real codes, and Lola signing
  her offer from the link signed out.

### Choices made (the simplest reading)

- Employment fields (status, type, work state, start date, custom fields,
  access list, checklists) are not among the sensitive ones: HR permissions
  see them unmasked, and so does the person; managers and senior leadership
  do not.
- Pay is three fields (rate, unit, effective date); the emergency contact and
  the home address are one field each.
- Offer letters go from a client company's People page only: e-signature
  sends for a company, and the practice's own team has none.
- The signer of an offer is a contact of the company, as every signer is;
  one People makes is People's (above).
- An HR Generalist runs checklists and the access list (no sensitive data in
  them) but changes no record, sends no offer and adds no document.
- Checklists close by a press, not by themselves.
- Birthdays and anniversaries cover the next 30 days; a birthday's day and
  month are not logged as a view of the date of birth.
- The spreadsheet is CSV.
- Client users are counted and shown; there is no client-user charge in the
  billing code to add them to yet.

### To check once it is merged

- `people 0002` applied by the runbook's "Releasing a migration".
- Turn People on for the owner's practice; add a person, start an
  onboarding: its tasks are in Work, assigned and dated.
- Send an offer to an address of yours, approve it in the Sending queue,
  sign it: the record moves to onboarding; countersign it in Documents.
- An assistant opens Work, Documents and the Sending queue: none of it
  there. An AI app (Claude) asked about tasks and documents names none of it.
- Reseed the demo: Acme's People page as in "The demo" above.

