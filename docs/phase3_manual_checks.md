# Phase 3 — Manual Checks

**Module 3: Task engine + client portal · for the owner**

The six manual checks from `04_build_plan.md` Phase 3. Check 1 is the one that
matters most: it is the only way to find out whether a digest reads as value
delivered, and the only person who can judge it is you.

---

## Before you start

**Restart `qcluster`.** It is running code from before Module 3 existed and will
fail every digest job until it restarts. Then register the new schedule — once,
idempotent.

```bash
# Target: terminal, from ~/projects/execs-now-hq
gcloud config configurations activate execs-now-hq
./scripts/backup_db.sh

.venv/bin/python manage.py ensure_schedules     # adds work.tick (every minute)
.venv/bin/python manage.py runserver 8100       # terminal 1
.venv/bin/python manage.py qcluster             # terminal 2 — RESTART it
cd frontend && npm run dev                      # terminal 3
mailpit --smtp localhost:1025 --listen localhost:8125   # terminal 4
```

**What sends and what does not.** `hold_all_digests` is ON, which is the Beta
default, so **every** digest waits for you in **Digests**. Anything that does
send goes to Mailpit unless the address is in `DEV_REAL_SEND_ALLOWLIST` — so
put a real client's address nowhere near this until you mean it. To watch a
digest land in a real inbox, make **yourself** a stakeholder.

**A test client user.** Check 5 needs a client login. Grant portal access to a
contact whose email you control, either way round:

- **Company → Portal access** lists that company's people with a **Grant** button
  each. Nothing needs typing; the box only narrows a long list.
- **Contact → Portal access** grants the person you are already looking at.

Then open the sign-in link from Mailpit in a private window. Revoke it when you
are done. Anyone who cannot be granted stays on the list with the reason showing
rather than quietly vanishing.

---

## Check 1 — Read a real digest as your client would

1. Pick a live engagement. Create a **Goal**, a **Project** under it, and two or
   three real **Tasks** (Work → Add).
2. Add a stakeholder: on the goal, **Who hears about this** → find the contact →
   leave it weekly. Add **your own** contact too, so one digest reaches you.
3. Work the tasks as you normally would for a few days. When you change a status
   you will be asked for one line on what it means for the client. **Write it
   sometimes and skip it sometimes** — that contrast is what this check is for.
4. On Thursday morning the drafts appear in **Digests**. Read one end to end.

> **You do not have to wait for Thursday.** The **Digests** screen has a
> **Generate a digest now** card — development only, and it does not exist once
> the app is off this laptop. Choose the person, the period and the send window,
> and it runs the same generation the scheduler runs: same content, same hold
> rules, a draft and no email. If nothing is owed it says so, which is itself the
> right answer (FR-3.31).

> **Does it read as value delivered, or as a changelog?** If it reads as a
> changelog, tell me which parts felt mechanical. The two levers are the prompt
> in `apps/work/digests.py` (`AI_SYSTEM`) and how the client-facing lines are
> asked for.

Note whether the AI narrative said anything that was **not** in your lines or
the transitions. That is the one thing it must never do.

## Check 2 — Run one full weekly cycle on a real engagement

Thursday generation, Friday approval, on real work.

- Thursday: the draft is in **Digests**, marked pending. Nothing has been sent.
- Friday: approve it. It goes out through your Gmail; it lands in your inbox if
  you made yourself a stakeholder, and in Mailpit for everyone else.
- Open the task afterwards: the send shows in its history, and the stakeholder
  row shows when they were last told.

Links in a digest point at `localhost` and work only on your machine until the
Railway move.

## Check 3 — Leave a digest unapproved on purpose

Use **Generate a digest now** with the send window set to **in 2 minutes**, and
do not approve it. (Or let a real one reach its Friday window.)

- Nothing arrives. The digest shows as **expired**.
- Its content is **not lost**: next week's draft contains it again. Confirm that
  by reading next week's draft, or by making another change and regenerating.

## Check 4 — Be an every-update stakeholder for ten minutes

Set yourself to **On every update** on one task, then make four or five changes
over a few minutes.

- **One** digest appears, about 30 minutes after your last change — not five.
- With `hold_all_digests` ON it still waits for approval. That is the trade-off
  recorded in FR-3.28b: frequent small approvals are accepted rather than
  special-cased.

## Check 5 — Sign in to the portal as a real client user

In a private window, on a second device if you can.

- Create a task, create a project, comment on something.
- Confirm you see **nothing internal**: no internal comments, no hidden tasks,
  nothing from another client company.
- Confirm a task the practice is doing (assigned to you, the fractional) is
  **read-only** to them, and that commenting on it still works.
- Check the **Progress report** page: it renders immediately and sends nothing.
- Back as yourself: **Work** shows a "What your clients have done" panel, and a
  batched email arrives about 30 minutes after their last action.

## Check 6 — Grant a third seat with only two available

Set the company's `seat_count` to 2, use both, then try a third grant.

> Read the error. It should name the seat count and how many are in use, and no
> user or sign-in link should be created. Then lower `seat_count` to 1 and
> confirm **nobody loses access** — it only blocks the next grant.

---

## Worth knowing

- **A client company with no seat count cannot be granted access**, by design:
  `seat_count` is null until you set it up as a client. It now says so in those
  words. **SkyRun Park City** and **Academy of America** are both in that state.
- **The founder user is the company's `primary_contact`.** Acme Facilities has
  none set, so everyone there would be granted as an *employee* user. Set the
  primary contact on the company first if Check 5 needs an FCC.
- **A stakeholder is a contact, not a login.** Adding someone as a stakeholder
  consumes no seat and creates no user; they get the email and never need to
  sign in. Portal access is a separate thing you grant separately.
- **Every digest footer carries a cadence link.** The recipient can change how
  often they hear, or stop, without asking you — no sign-in needed. It can do
  nothing else.
- **Monthly digests** go out on the first send-day of the month and cover the
  previous calendar month (your decision).
- **Generate a digest now** is on the Digests screen, on this laptop only. It is
  the same code path as the scheduled run, so what you see there is what Thursday
  would have produced. Every generation is audited as
  `digest.generated_on_demand`.
- **A goal's status** is derived from the work underneath it unless you set it by
  hand: `waiting on client` beats `blocked` beats `in progress`.

## What to tell me afterwards

1. Check 1: does the digest read as value delivered? What felt mechanical, and
   did the narrative ever assert something you had not written?
2. Checks 2–4: pass or fail, and anything that surprised you.
3. Check 5: anything a client saw that they should not have.
4. Check 6: whether the seat message was clear enough to act on.
