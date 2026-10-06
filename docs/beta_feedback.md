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
