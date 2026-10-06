# Beta feedback

Feedback from practices on the beta, as it arrives, with what was found and
what was decided. Newest first. Nothing here is built unless it says so.

---

## 2026-10-05 — Shawn, Blue Sky Business Consulting (first day on the beta)

### A. "Staff" on the sign-in page

**Feedback.** "Staff" confused Shawn; he thought it meant his client's staff.

**Status.** Bryan is choosing new wording. No code yet.

**Where "Staff" faces a person who is signing in** (two places):

1. **The sign-in page**, the heading over the Google sign-in box:
   `frontend/src/components/SignedOut.tsx`, line 70. The page has two headings,
   "Clients" (email me a sign-in link) and "Staff" (work email, Sign in with
   Google).
2. **The practice owner's invitation email**, which sends them to that
   heading: "To sign in, go to … Under Staff, enter <their address> and choose
   Sign in with Google" (`apps/platform/mail.py`, line 81). The same email
   later lists "your staff" among the setup steps (line 85).

Not affected: the "No access" page after a refused sign-in (it says "Ask the
practice owner to invite your address"), the client's sign-in link email, and
the beta agreement screen. After sign-in the word appears as the Staff settings
section and "Invite your staff" on the Getting started list; those are read by
someone already inside their own practice.

Whatever replaces it has to change in both places together, or the email will
point at a heading that no longer exists.

**Decided and built 2026-10-05 (on `dev`, not released).**

- The sign-in page: "Staff" is now **Practice sign-in**, with the line "For
  consultants and their team". "Clients" is now **Client sign-in**, with the
  line "For clients of a practice".
- The practice owner's invitation email says "Under Practice sign-in, enter…".
  A test reads the page and the email together, so one cannot be reworded
  without the other.
- Left as they are, and reported to Bryan: every other "staff" (the list is in
  the 10/5 chat and under "Other 'staff' wording" at the end of this entry).

### B. Practice email alias: let the practice choose it, and more than one account

**Feedback.** Let the practice pick its alias instead of being pushed to
info@; some will want help desk, customer service or something else. Add
instructions. Also offer connecting more than one account, since a practice's
customer-service address may already be a separate inbox.

**What the connect flow does today.**

1. When a practice is created in Practices, its alias is set to
   `info@<the practice's domain>` (`apps/platform/provisioning.py`). That is
   where info@ comes from. **Nothing in the app can change it afterward**: no
   screen and no endpoint writes it. The P2 spec says it is "editable in Email
   settings"; that part was not built.
2. The owner opens Settings → Email and presses Connect. Google asks them to
   sign in as their own account and grant sending (and, only if they ticked
   the box, reading replies).
3. On return the app stores the connection and at once asks Gmail for that
   account's "Send mail as" list, looking for the alias.
4. If the alias is there and confirmed, it is marked verified and app mail
   (digests, sign-in links, stage emails) sends from it through the owner's
   account. If not, the screen says the alias "is not a send-as address on
   <account>. Add it in Gmail under Settings → Accounts → 'Send mail as'…"
   and offers Verify alias to check again.
5. Until an alias is verified, app mail does not send. That is deliberate: it
   never falls back to the owner's personal address.

So a new owner is told to go and create an address they did not choose, with
one line of instruction, on Google's side.

**The smallest change that lets the owner choose it up front.**

- An editable "Practice address" on Settings → Email, practice owner only,
  shown **before** Connect, with the instructions beside it: what the address
  is for (clients see it as the sender of digests and sign-in links), that it
  can be any address they can send as (info@, helpdesk@, hello@, or their own),
  and the Gmail steps to add it as "Send mail as" with a link to Google's help.
- Saving a new address clears the verified mark and re-runs the same check.
- One new write endpoint for that one field. **No migration**: the column
  exists. Open question for Bryan: allow the owner's own address as the
  practice address (then there is nothing to set up in Gmail at all, at the
  cost of digests coming "from" a person).

**What connecting a second account would take.** Today there is one connection
per person, and all app mail goes through the practice owner's.

- *If the customer-service address only needs to be the sender:* no second
  connection is needed. Gmail's "Send mail as" can be another mailbox the
  owner has access to; with the change above they would pick it as the
  practice address.
- *If replies to that inbox must thread into client records* (the unified
  communication module), the app has to read that mailbox, which means a real
  second connection: a connection that belongs to the practice rather than to
  a person (a schema change), a connect flow that signs in as the other
  account, sending and reply-polling that choose the connection by address,
  and settings to manage it. Reading another mailbox is the restricted Google
  scope, so it also touches the verification Bryan is working through. That is
  a spec, not a tweak.

**Decided 2026-10-05, and built (on `dev`, not released).** Bryan's
decisions: the practice address is editable; **the owner's own email may be
the practice address**; a separate address is **recommended, not required**.
His reasoning: for less tech-savvy owners, adding an alias may be too much
friction.

*What was built.* Settings → Email now opens, for the practice owner, with a
"Practice address" card **above** Connect. Getting started's Gmail step is
renamed "Choose your practice address and connect Gmail" and leads there.

1. **"What is your email?"** Prefilled with their sign-in address; it is the
   Google account they will connect.
2. **"Do you want your practice address to be something different, like info@
   or helpdesk@, or do you want your own email to be the practice address?"**
   "A separate practice address" is marked recommended and suggests
   `info@<their domain>`; any address can be typed. "Use my own email" is the
   other choice and says there is nothing to set up in Gmail.
3. Only for a separate address: **"Do you want a separate inbox or an
   alias?"**, under the disclaimer that a separate inbox is an extra charge
   with Google or Microsoft and one more inbox to manage, while an alias costs
   nothing extra and is not a separate inbox to manage.
   - *Alias:* the steps, in order: add it in the Google Admin console
     (Directory → Users → the user → User information → Alternate email
     addresses); add it in Gmail (Settings → See all settings → Accounts →
     Send mail as → Add another email address, leaving "Treat as an alias"
     ticked); click Gmail's confirmation link if it sends one; save here. A
     note says an alias at their own domain needs Google Workspace, and that a
     free @gmail.com account should use its own email.
   - *Separate inbox:* what works today, plainly. The app can send from it
     once it is in their Gmail "Send mail as" list. Replies sent to that inbox
     will **not** appear in client records, because the app reads only the
     account that is connected; a second account is planned and not built. The
     app connects to Google only; a Microsoft 365 inbox cannot be connected.

- **Saving** stores the address and runs the existing "Send mail as" check
  again against it. A changed address never inherits the old one's verified
  mark. Before anything is connected, saving only stores it; connecting runs
  the check.
- **Existing practices keep their address.** Once connected and verified, the
  card is a one-line summary with "Change".
- **Who:** practice owner only (`POST /api/gmail-connection/practice-address/`).
  An associate sees no questions. Recorded in the audit trail as
  `practice.address_changed`, with the old and new address.
- The answers to questions 1 and 3 are not stored; they only decide which
  instructions show. **No migration.**
- With the owner's own email as the practice address, digests and sign-in
  links come from that person. Nothing else changes: per-person "send as
  myself" settings keep working, and resolve to the same address.

**Roadmap (needs its own spec): connect a second account or a separate
inbox.** Bryan's reason: not every fractional practice is a one- or two-person
shop. What it involves is listed above ("What connecting a second account
would take"): a connection that belongs to the practice rather than a person,
a connect flow for the other account, sending and reply-reading chosen by
address, and the Google verification consequences of reading another mailbox.

### C. "Google hasn't verified this app"

**Feedback.** Shawn saw Google's unverified-app warning.

**Status.** Known. Bryan is working through `docs/google_verification.md`.
Nothing to build.

### D. Goal screen: the company dropdown shows only "Internal"

**Feedback.** Possible bug: on the goal screen the dropdown shows only
Internal and not the client company, even though Shawn added a company.

**Finding: not a bug; the screen does not explain itself.** The "Client
company" dropdown on New goal, New project and New task (and the company
selector at the top of Work and Tasks) lists **client companies only**. A
company becomes a client company in exactly one way: **one of its contacts
reaches the won stage (Closed Won) on the sales pipeline**. Adding a company
does not make it a client, and nothing on the Company page or the Add company
form can set it; that was a deliberate rule (the flag is derived, never typed).
Shawn's company has no contact at Closed Won, so only Internal is offered.

**Proposed, for Bryan to choose (nothing built):**

1. *Explain it where it bites (smallest).* Under the dropdown, when the
   practice has companies that are not clients: "Only client companies are
   listed. A company becomes a client when one of its contacts reaches Closed
   Won on the Pipeline." with a link to the Pipeline. The same line on the
   Company page beside "Not a client company".
2. *Let the owner say so.* A "Mark as a client" action on the Company page,
   practice owner only, which does what the won stage does (flags the company
   and gives the chosen contact the client type) without requiring a pipeline
   move. This changes a deliberate rule, so it needs Bryan's yes; a practice
   that signs clients outside the pipeline, or imports existing clients, has no
   other way in.

Recommendation: do 1 now, and decide 2 separately. A new practice arriving
with existing clients will hit this on day one, as Shawn did.

**Decided 2026-10-05, and built (on `dev`, not released).** Both proposals.
Bryan's reason for the second: a client who comes from a referral should not
have to be pushed through the sales pipeline first.

*The explanation.* Under the "Client company" dropdown on New goal, New
project and New task, whenever the practice has a company that is not listed:
"Only client companies are listed. A company becomes a client when one of its
contacts reaches Closed Won on the Pipeline, or when the practice owner marks
it as a client on the company's page." On the Company page, a card headed
"Client company" or "Not a client company" says the same and what it means.

*Mark as a client.* On the Company page, practice owner only, with a
confirmation that says what it does. **What it sets, compared with reaching
Closed Won:**

| | Closed Won on the sales pipeline | Mark as a client |
|---|---|---|
| The company becomes a client company | yes | **yes** |
| The contact's stage changes, and the change is in their history | yes | no |
| The stage's automations run (a task, a draft email) | yes | **no: none run** |
| The contact gets the client type | yes | no |
| Recorded in the audit trail | yes (`company.flagged`, "stage=… (won)") | yes (`company.flagged`, "marked by the practice owner") |

So marking does one thing. No stage automation can fire, because no stage
changes: the code path that runs them is never called, and a test arms a rule
on Closed Won and shows it stays quiet. A contact's client type can still be
added by hand on the contact, as before.

*Undo.* "Marked as a client by mistake?" on the same card, practice owner
only: "Not a client after all", with a confirmation. It is for a mistake, so it
is allowed only while nothing has been built on the mark, and it never deletes
or detaches anything to make itself possible. **What blocks it**, each shown
as a sentence on the card instead of the button:

- a contact at the company has reached Closed Won on the sales pipeline (then
  it is a client by the pipeline's rule, not by a click);
- anyone at the company has portal access;
- any goal, project or task is filed under it;
- an associate is assigned to it;
- a value report has been exported for it.

Recorded as `company.unflagged`. Routes:
`POST /api/companies/<id>/mark-client/` and `/unmark-client/` (practice owner),
`GET /api/companies/<id>/client-status/` (staff who can see the company).
**No migration.**

### E. Digests: day, time and approval

**Feedback.** Bryan wants to confirm all digests go out Friday morning, wants
the day editable (set in the Digests screen on first use and in Settings
afterward), and wants confirmation that nothing is sent without approval.

**How digests behave today for a brand-new practice such as Blue Sky.**

- **Day and time.** Friday at 8:00 AM, in the practice's time zone. Both are
  stored per practice (`digest_send_day`, `digest_send_hour`) and **neither
  can be changed from any screen**. A new practice's time zone is
  America/Denver, also not editable from a screen; Friday 8:00 for Blue Sky is
  8:00 Mountain unless that is changed by hand.
- **Who gets one.** Each stakeholder on a task picks a cadence: weekly (the
  default), monthly, or on every update.
  - *Weekly:* written Thursday 8:00 AM (24 hours ahead), goes Friday 8:00 AM.
  - *Monthly:* the first Friday of the month, covering the previous calendar
    month; written the day before.
  - *Every update:* written once 30 minutes pass with no further change; then
    it has 24 hours to be approved and **sends as soon as it is approved**,
    whatever the day. So not every digest goes on Friday: these go when
    approved.
- **Nothing in a period means no digest and no email.**
- **Approval.** A new practice is created with `hold_all_digests` **on**.
  While it is on, **every** digest waits on the Digests screen (and in the
  Sending queue) for a person; none sends by itself. Only the practice owner
  or an associate can approve; an assistant cannot.
- **Unapproved by its time, it is never sent.** It expires, and its updates
  are carried into the next period, so nothing is lost and nothing goes late.
- **What `hold_all_digests` does.** On: everything waits for approval. Off:
  a plain (non-AI) digest is approved automatically when written and sends at
  its time with no person involved; an AI-written digest still waits. **No
  screen turns it off**; it can only be changed in the database, and the
  laptop's scrub turns it back on. For Blue Sky it is on.
- **Also required to send anything:** Gmail connected with a verified practice
  address (item B). Without it an approved digest cannot go.

**So, to Bryan's three points:** weekly and monthly digests go Friday 8:00 AM;
"every update" ones go when approved. The day is not editable today. Nothing is
sent without a person approving it while the hold is on, which it is for every
new practice.

**Smallest change for an editable day.**

- A "Digest day and time" control: day of week and hour, practice owner only.
  It lives in Settings (a Digests section), and the Digests screen shows it
  once, as a prompt, until the owner has confirmed it ("Your digests go out
  Fridays at 8:00 AM. Keep or change.").
- One read/write endpoint for the two existing fields. **No migration** for
  day and hour. Remembering that the owner has confirmed needs one small
  column, or the prompt can simply show until the first digest is approved,
  which needs none.
- Changing the day takes effect from the next digest written; one already
  waiting keeps the time it was written for.
- Worth adding the practice's time zone to the same control, since "8:00 AM"
  is currently Mountain for everyone.
- Not proposed: a switch for `hold_all_digests`. Turning approval off is a
  bigger decision than picking a day.

**Decided 2026-10-05, and built (on `dev`, not released).** "Digest day and
time" in Settings, practice owner only, with the time zone in the same
control, and a one-time prompt on the Digests screen. **No switch for
`hold_all_digests`**: it is not on the screen, and the endpoint refuses it by
name.

- **Settings → Digests** (a new section, practice owner only): Day, Time and
  Time zone, saved together, under a sentence that says the result ("Digests
  go out on Fridays at 8:00 AM Mountain (America/Denver)"). The common US zones
  are listed first by name; every other zone follows.
- **What the card tells the owner:** weekly digests are written 24 hours
  before the time and sent at it; monthly ones go on the first such day of the
  month; "every update" digests are not on this schedule and go when approved;
  a change applies to digests written from now on, and one already waiting
  keeps its time; every digest still waits for approval.
- **The prompt:** the first time the practice owner opens Digests, a card asks
  "When should your digests go out?", states the current answer, and offers
  "Keep Fridays at 8:00 AM" or "Change the day or time" (to Settings). Either
  answers it for good. An associate or assistant is never asked.
- **The time zone is the practice's**, not only the digests': changing it also
  moves the app's other daily jobs to their local hour in the new zone. The
  card says so.
- **Who:** every member of the practice's staff can read the schedule (they
  all see the Digests screen); only the practice owner changes or confirms it.
  `GET`/`PATCH /api/digests/schedule/`, `POST /api/digests/schedule/confirm/`.
- **Recorded:** `digest_schedule.confirmed` or `digest_schedule.changed` (with
  the before and after) in the audit trail. That record is also how the app
  knows the prompt has been answered, so **no migration** was needed.

### Other "staff" wording (reported 2026-10-05; changed to "team" the same evening)

**Built on `dev`, not released.** For consistency with "Practice sign-in — For
consultants and their team", all five below now say **team**: "…your
contacts, your team, your first client…"; "Invite your team"; the Settings
section and its page title are "Team"; the refusals read "…not invited to the
team." and "…not team roles."; and the platform owner sees a "Team" column and
"What practice teams sent with the Feedback button." **The address is still
`/staff`**, so links and bookmarks keep working, and nothing in the code or
the data was renamed.

As first reported:

Places where "staff" could still be read as the client's staff. None is seen
by someone who has not yet signed in.

1. **The practice owner's invitation email**, in its list of setup steps:
   "…your contacts, your staff, your first client…" (`apps/platform/mail.py`).
2. **Getting started**, on a new owner's dashboard: "Invite your staff".
3. **Settings → Staff**: the section name and the page title. Its subtitle
   does say "Your practice's own people".
4. **Two refusals on that page**: "Client users are granted portal access on a
   contact, not invited as staff." and "Client roles are managed through
   portal access, not staff roles."
5. Platform owner only, so Bryan alone: the "Staff" column on Practices, and
   "What practice staff sent with the Feedback button."

