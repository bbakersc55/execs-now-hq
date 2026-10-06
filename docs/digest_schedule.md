# Digest schedule: "Draft on" and "Send on"

**Spec for owner review · 2026-10-05 · no digest code and no migration until approved**

Decisions for the owner are numbered D1–D13 in §10, each with a recommended
default. Everything below assumes the defaults.

## 1. Why

Bryan moved his practice's digests to Monday 8:00 AM in production. Today a
weekly digest is written exactly 24 hours before it is sent, so his are now
written Sunday 8:00 AM and expire unsent if nobody approves them by Monday
8:00 AM. What he wants is different, and is not "a lead time":

> Monday 8 AM, work completed by 3 PM Friday and approved.

He also expects "24 hours before" to confuse people. So the practice gets two
plain settings, a way to act on a digest by hand, and reminders by email.

**Already decided (2026-10-05):** yes to reminder emails; associates get them
for their own clients' digests; the approval cutoff stays the send time; no
lead time in hours; `hold_all_digests` is unchanged and still has no switch.

## 2. What exists today (so nothing is built twice)

- One setting pair per practice: send day and send hour (Settings → Digests),
  plus the practice's time zone. The draft time is fixed in code at 24 hours
  before.
- A waiting digest that is not approved by its send time **expires**: it is
  never sent, and its updates are owed again and appear in the next digest.
- **"Regenerate"** already rebuilds a waiting digest with everything owed up to
  that moment. It is offered only when the digest carries the out-of-date flag
  ("Overtaken by events"), which is set when work lands after the draft was
  written.
- What makes "never twice" true: when a digest is written, each update in it
  is recorded against that recipient (`digest_item`). An update with such a
  record is not owed to that person again. Sending keeps the records for good;
  expiring or skipping deletes them, which is the single act that hands the
  updates to the next digest.
- Nothing tells anyone a digest is waiting except the Dashboard tile, the
  Digests screen and the Sending queue. There is no email.

## 3. The two settings

Settings → Digests, practice owner only (as now), time zone in the same card:

| Setting | Meaning | Default |
|---|---|---|
| **Draft on** (day, time) | When each week's digests are written. Work finished before this is in them. | Thursday 8:00 AM |
| **Send on** (day, time) | When approved digests go out. Also the approval cutoff. | Friday 8:00 AM |

The default reproduces today exactly. Bryan's intended setting is Draft on
Friday 3:00 PM, Send on Monday 8:00 AM.

- Times are whole hours (D1). "Draft on" must fall before "Send on" in the
  same week's cycle by at least two hours and less than seven days (D2); the
  card refuses the same day and time for both.
- **One sentence states the result**, updating as the controls change:
  *"Work finished by Friday 3:00 PM is included. Approve any time until Monday
  8:00 AM, when approved digests are sent."*
- **A gentle warning**, not a refusal, when no part of the time between Draft
  and Send falls on Monday to Friday, 9:00 AM to 5:00 PM: *"All of the time to
  approve these falls outside working hours (Monday to Friday, 9 to 5).
  Digests nobody approves are not sent."* Bryan's current Sunday-to-Monday
  window would show it; Thursday 8:00 AM to Friday 8:00 AM does not.

**Each cadence a stakeholder can choose:**

- **Weekly:** drafted at Draft on, sent at Send on. Each digest holds
  everything owed to that person up to the draft time.
- **Monthly:** sent at the **first Send on of the month**, drafted at the
  Draft on immediately before it (so Friday 3:00 PM, for a first-Monday send,
  even if that Friday is in the previous month). It is headed with the
  previous calendar month, as today, and holds everything owed up to its draft
  time.
- **Every update:** not on this schedule, as today. It is drafted once 30
  minutes pass with no further change, has 24 hours to be approved, and is
  sent the moment it is approved. The settings card says so in one line (D3).

Changing either setting applies to digests drafted from then on. A digest
already waiting keeps the send time it was written with.

## 4. "Update this draft"

Today's Regenerate, renamed and always available on a digest that has not been
sent: waiting for approval, or past its send time (§5).

- It rebuilds the digest with everything owed to that person **up to now**, so
  work finished after the draft time is included. It then needs approving like
  any other; **it still sends on the timer**, at its original send time.
- **How it relates to the out-of-date flag.** The flag stays and is unchanged
  in meaning: it appears on a waiting digest when work lands after it was
  drafted, saying what landed. Today it is the only thing that reveals the
  Regenerate button. After this change the flag is the *reason* and "Update
  this draft" is the *action*, and the action is there whether or not the flag
  is: an owner who knows more work is about to finish can update at 4:55 PM
  without waiting for the flag. Updating clears the flag.
- If nothing is owed any more (everything was sent another way), updating
  leaves no digest, as today.
- It replaces wording a person typed with "Edit the wording"; the button says
  so before it does, as Regenerate does today.
- An **approved** digest cannot be updated; it is a finished thing (D4). Work
  finished after approval goes in the next digest.
- Who: anyone on the practice's staff, as today (an assistant may prepare a
  digest and may never approve or send one).

## 5. "Send now"

A manual send by the practice owner or an associate (for their own clients),
never an assistant.

- **The full email is on screen first.** "Send now" opens the digest exactly
  as the recipient will receive it, with the recipient's name and address, and
  a second button, "Send to Dana Reyes now". Nothing is sent from a list row.
- **Before the send time** it works on a digest waiting for approval (it is
  that person's approval, recorded as theirs, followed at once by the send)
  and on one already approved (it just goes early).
- **After the send time.** Today an unapproved digest expires at its send time.
  Instead it becomes **late**: not sent, still on the Digests screen under
  "Not sent on time", and still sendable by hand. It stays that way **until
  the next digest for the same person and cadence is drafted**. At that moment
  it expires and its updates go into the new draft, which is today's
  roll-forward, one draft cycle later. A late digest can be updated (§4) and
  then sent now; it cannot be "approved" for a timer, because its time has
  passed.
- A stakeholder who has unsubscribed is not sent to, as today, and the screen
  says so.

**How "never reported twice" is guaranteed.** Four things, the first of which
is the existing mechanism:

1. **The record is the rule.** An update is left out of a person's next digest
   exactly while a record joins it to a live digest for that person. "Send
   now" goes down the same single send path as the timer, which never deletes
   those records. So once sent, by either route, those updates are never owed
   to that person again. There is no second bookkeeping to drift.
2. **One writer at a time.** Send now, Update this draft, the timer's send,
   and the expiry of a late digest each lock the digest's row first and
   re-read its state. Two cannot interleave. This is the same lock that fixed
   the double-click race on 2026-09-17.
3. **The one real race, and how it resolves.** A late digest is sent by hand
   in the same second the next draft is being written. Whichever commits first
   wins, and the other sees the result: if the send wins, the drafter finds
   the digest sent, leaves its records alone, and the new draft simply does
   not contain those updates; if the drafter wins, the late digest is expired,
   its updates are in the new draft, and Send now is refused with "This digest
   was folded into the next one", sending nothing.
4. **A test that states it outright:** across generated sequences of updates,
   drafts, updates-to-drafts, timer sends, manual sends and expiries, no update
   ever appears in two sent digests for the same recipient, and no update is
   lost (each ends in exactly one sent digest or is still owed).

## 6. Reminder emails

Internal mail to the practice's own people, sent through the practice's
connected mail like the existing client-activity notice. They name clients and
counts and link to the Digests screen. **They never contain a digest's text**
(D5), and they are never sent to a client.

| Email | When | Sent only if | To |
|---|---|---|---|
| **"Your digests are ready to approve"** | At Draft on, once that cycle's digests are written | at least one was written for that person to approve | practice owner: all. Each associate: their own clients' |
| **Last call** | Before Send on (timing below) | something is **still** waiting | the same people, each for what they can approve |
| **"Not sent"** (D6) | At Send on | something went late | the same people |

- "Their own clients'" is the rule the Digests screen already uses for an
  associate: digests for people at companies assigned to them. Assistants get
  none of these: they cannot approve (D7).
- Each says the send time in words and what happens otherwise: "Anything not
  approved by Monday 8:00 AM is not sent. You can still send it by hand until
  Friday 3:00 PM."
- One email per person per occasion, however many digests. Never repeated for
  the same cycle.
- **Every-update digests** are announced in the same "ready to approve" email,
  batched: at most one such email per person per hour (D8).

**Proposed last-call timing (D9).** Two hours before Send on, when that moment
falls in working hours (Monday to Friday, 9 to 5, practice time). Otherwise at
**4:00 PM on the last weekday before the send time**, provided that is after
the draft time; failing that, two hours before regardless. So:

- Draft Friday 3:00 PM, send Monday 8:00 AM: last call **Friday 4:00 PM**.
- Draft Thursday 8:00 AM, send Friday 8:00 AM: last call **Thursday 4:00 PM**.
- Draft Friday 9:00 AM, send Friday 3:00 PM: last call **Friday 1:00 PM**.

The point is that the last call arrives when someone is at work to act on it,
which a fixed "two hours before" does not do for an 8:00 AM send.

## 7. What does not change

- `hold_all_digests` is untouched and has no switch. A new practice has it on.
- **Nothing reaches a client without a person's approval.** The timer sends
  only approved digests. "Send now" is a person approving and sending, after
  reading the whole email. Reminders go to staff only.
- Who may approve (practice owner, associate; never an assistant), what an
  associate may see, and practice isolation.
- The content of a digest and how it is written.
- A period with nothing in it produces no digest and no email.

## 8. Data model

Two columns on the practice, and one new value for a digest's state.

```python
# apps/tenancy/models.py, Tenant
digest_draft_day = models.PositiveSmallIntegerField(default=4)    # Thursday
digest_draft_hour = models.PositiveSmallIntegerField(default=8)

# apps/work/models.py, Digest.State
LATE = "late", "Not sent on time"
```

Planned SQL (the real `sqlmigrate` output is shown before the migration is
generated, as always):

```sql
ALTER TABLE "tenant" ADD COLUMN "digest_draft_day" smallint DEFAULT 4 NOT NULL
  CHECK ("digest_draft_day" >= 0);
ALTER TABLE "tenant" ALTER COLUMN "digest_draft_day" DROP DEFAULT;
ALTER TABLE "tenant" ADD COLUMN "digest_draft_hour" smallint DEFAULT 8 NOT NULL
  CHECK ("digest_draft_hour" >= 0);
ALTER TABLE "tenant" ALTER COLUMN "digest_draft_hour" DROP DEFAULT;

-- Carry-over (§9): every existing practice keeps exactly today's behavior,
-- which is "drafted 24 hours before it is sent".
UPDATE "tenant"
   SET "digest_draft_day" = CASE WHEN "digest_send_day" = 1 THEN 7
                                 ELSE "digest_send_day" - 1 END,
       "digest_draft_hour" = "digest_send_hour";
```

- Additive columns, plus one `UPDATE` that writes only the two new columns.
  Nothing is dropped and no existing value is changed. Because it writes
  data, **in production it waits for Bryan's yes on the dry run** (which
  prints each practice's before and after) under the standing rule.
- The new state is a value, not a column: no SQL. The rule "one live digest
  per person, cadence and period" already treats everything except expired and
  skipped as live, so a late digest correctly holds its place.
- **Migration numbering:** this will be `tenancy 0011` on `dev`. The profile
  picture's migration on `feature/profile-picture` is also numbered 0011 and
  must be renumbered to follow this one when that branch comes back.
- Reminders need no table: "already sent for this cycle" is kept as an audit
  event per person and cycle, the way the client-activity notice keeps its
  place.

## 9. Carry-over

- **Existing practices:** the `UPDATE` above sets Draft on to one day before
  Send on at the same hour, so on the day of release nothing about anyone's
  schedule moves. **Bryan's practice (Send on Monday 8:00 AM) becomes Draft on
  Sunday 8:00 AM**, which is what it does today; he then sets Friday 3:00 PM
  himself in Settings (D10). The release does not choose a draft time for him.
- **Digests already waiting at release** keep the send time they were written
  with. The one difference they see: one that reaches its send time unapproved
  becomes late instead of expiring, and can be sent by hand until the next
  draft. Nothing waiting is rewritten, re-timed or sent by the release.
- **When a setting is changed mid-cycle:** waiting digests keep their send
  time; the next draft happens at the next Draft on. If moving Draft on
  earlier would skip a cycle or moving it later would draft twice in a week,
  the card says which before saving (it states the next draft and send dates
  in full).
- The one-time prompt on the Digests screen is asked again once, in the new
  wording, for practices that have never changed their schedule (D11).

## 10. Decisions for the owner

| # | Decision | Recommended default |
|---|---|---|
| D1 | Whole hours, or half hours too? | **Whole hours.** The send time is whole hours today; 3:00 PM and 8:00 AM both fit. |
| D2 | Smallest allowed gap between Draft on and Send on | **Two hours.** Enough for the last call to mean something. |
| D3 | Does "every update" stay off the schedule, with its 24 hours to approve? | **Yes, unchanged.** Its point is promptness. It gains Send now and the late state like the others. |
| D4 | Can an approved digest be updated or un-approved? | **No.** Approved is final; later work goes in the next digest. |
| D5 | Do reminder emails include the digests' text? | **No.** Client names, counts and a link only, so client material is read in the app, not forwarded around in mail. |
| D6 | A third email, "Not sent", at the send time when something went late? | **Yes.** It is the moment someone most needs to know, and it says by when it can still be sent by hand. |
| D7 | Do assistants get the reminders? | **No.** They cannot approve; a reminder they cannot act on is noise. |
| D8 | Are every-update digests announced by email? | **Yes, at most one email per person per hour.** |
| D9 | Last-call timing | **Two hours before the send time when that is in working hours; otherwise 4:00 PM on the last weekday before it.** Not a setting for now. |
| D10 | Does the release set Bryan's practice to Draft on Friday 3:00 PM? | **No.** It reproduces today for everyone; he sets it in Settings in a minute. A migration should not choose for one practice. |
| D11 | Ask the one-time Digests prompt again in the new wording? | **Yes, once, for practices still on the defaults.** |
| D12 | How long does a late digest stay sendable? | **Until the next digest for that person and cadence is drafted**, as Bryan described. No separate time limit. |
| D13 | Is "Send now" also offered in the Sending queue? | **Not in this round.** The Digests screen only, where the whole email is shown. |

## 11. Build phases

Each phase is finished, tested and shown before the next. Practice isolation
and role boundaries are tested in every phase that adds a route. v2 and v3
goldens and the real-session fingerprints untouched throughout.

1. **The two settings.** The migration (SQL first; the carry-over `UPDATE`
   dry-run), Draft on / Send on in Settings → Digests with the sentence and the
   working-hours warning, and drafting by the draft time instead of a fixed 24
   hours, for weekly and monthly.
   Tests: the default reproduces today's times exactly, to the minute, across
   a daylight-saving change; Friday 3:00 PM / Monday 8:00 AM drafts and sends
   when it says; work finished before the draft time is in and after it is
   not; monthly drafts on the Draft on before the first Send on of the month,
   including when that falls in the previous month; the carry-over leaves
   every practice's send and draft times as they were (Bryan's as Sunday 8:00
   AM / Monday 8:00 AM); a waiting digest keeps its time when settings change;
   the sentence and the warning for several pairs; bad pairs refused; only the
   practice owner changes them; one practice's settings never touch another's.
2. **Update this draft, Send now, and late.** The rename and the always-there
   button; the late state and its screen section; Send now with the full email
   first.
   Tests: the never-twice, never-lost property in §5; the send-versus-next-
   draft race, both orders; Send now refused for an assistant, for an
   associate on another's client, across practices, and for a client user;
   Send now on waiting, approved and late digests; a late digest expires into
   the next draft and not before; updating a late digest then sending it;
   an unsubscribed recipient is not sent to; `hold_all_digests` on and off
   both leave an unapproved digest unsent by the timer.
3. **Reminders.** The three emails and the last-call rule.
   Tests: who receives which (owner all, associate their own clients',
   assistant and client users none); nothing sent when nothing is waiting;
   never twice for a cycle; last-call times for the three examples in §6 and
   across a weekend; no digest text in any reminder; practice isolation; no
   reminder while acting as someone; the reminder is skipped, and the
   Dashboard still shows the count, when the practice has no working mail
   connection.
