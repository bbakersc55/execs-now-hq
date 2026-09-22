# Phase 4 — Manual Checks

**Module 4: the strategy session · for the owner**

The five manual checks from `04_build_plan.md` Phase 4. **Check 1 is the whole
thing**: everything else is a rehearsal for running a real session with a real
prospect, and the only person who can judge whether Claude's map rows are worth
having in front of you mid-call is you.

Everything in the automated suite passes (1088 backend, 234 frontend, AC-4.1 to
AC-4.19). None of that tells you whether the form is too long, whether the tray
helps or distracts, or whether the PDF is something you would actually send.

---

## Before you start

```bash
# Target: terminal, from ~/projects/execs-now-hq
gcloud config configurations activate execs-now-hq
./scripts/backup_db.sh

.venv/bin/pip install -r requirements.txt       # WeasyPrint is new
.venv/bin/python manage.py migrate              # strategy 0001-0006, crm 0021-0022, work 0004
.venv/bin/python manage.py runserver 8100       # terminal 1
.venv/bin/python manage.py qcluster             # terminal 2 — restart after any backend commit
cd frontend && npm run dev                      # terminal 3
mailpit --smtp localhost:1025 --listen localhost:8125   # terminal 4
```

**Where everything is.** A new **Strategy** entry in the left-hand navigation.
`/strategy` lists sessions and starts them; `/strategy/<id>` is the live view;
`/strategy/template` is the template editor (founder fractional only).

**Who can do what.** A VA can start a session, send the pre-call form and
preview the PDF. Running the call, drafting, accepting rows, toggling what the
PDF includes, sending it and converting are yours or a CF's. A VA never receives
§9's investment fields — not on screen, and not in the API response either.

**Nothing is sent by the app on its own.** The pre-call invite and the PDF each
go out on a click, and nothing else in this module emails anybody. Mail goes to
Mailpit unless the address is in `DEV_REAL_SEND_ALLOWLIST`.

**Claude costs money.** Both drafting buttons spend against the tenant key. The
spend is on **AI usage** (`/ai-usage`), per call, with tokens and cost.

---

## Check 1 — Run a real strategy session with a real prospect

Nothing else tests this module honestly. Do the whole thing, in order, on a real
call.

1. **Strategy → Start a session.** Type the prospect's name, pick them, set the
   date and time, **Start**.
2. **Send the form** — the pre-call card, **Send the form**. It goes out
   immediately; there is no approval step. Check Mailpit (or the real inbox) for
   *"Before our strategy session"*.
3. **Open the link yourself first**, in a private window, and read it as they
   will. Thirteen questions. If it is too long, that is Check 2 and worth saying
   out loud before you send another.
4. **On the call:** click a section header to start that section's clock — the
   pill counts minutes against the seed's budget and turns amber when you run
   over. Capture diagnostic answers in the three boxes: *what they said*, *who
   or what causes it*, *what they tried*.
5. **Watch the tray.** Rows appear when you click **Draft rows with Claude**,
   and automatically the first time every question in one area is answered.
   Accept, edit, or discard each one.
6. **The mirror:** **Draft it with Claude**, then edit it into your words and
   **Save the mirror**. The draft stays beside it so you can see what you changed.
7. **After the call:** the PDF card. Preview it, send it.
8. **If they sign:** **Convert to work**.

**What to tell me afterwards**, in your own words: whether the drafted rows were
usable or noise, whether the pacing helped or nagged, and whether the PDF is
something you would send without editing it first. *If you found yourself
ignoring the tray, say so — that is a prompt problem and a Phase 4 bug.*

---

## Check 2 — Fill in the pre-call form as a prospect would

> **Fixed 2026-09-19, found by this check.** The emailed link opened on "This
> link has expired" for a token that was valid and a session 30 days from
> expiry. The page was rendered outside a `<Route>`, so it never received the
> token from the URL and asked the server for `/api/strategy/precall/undefined`
> — which is, correctly, an unknown token. The cadence link in every digest
> footer had the same shape and the same fault. Both now render inside a route,
> and a test walks the real sequence: send the invite, take the URL out of the
> delivered mail, open it cold.

Before you send one to anybody real.

1. Start a session against **yourself** (or a test contact whose email you hold).
2. **Send the form**, open the link from Mailpit **in a private window**. It must
   work with no sign-in at all.
3. Answer half of Section 1 and the first two ratings. Watch the **"Saved at…"**
   line and the **"n of 13 answered"** counter after each field.
4. **Close the tab. Reopen the same link.** Your answers are still there.
5. Click **I'm done for now**. Check Mailpit for *"… finished the pre-call
   form"* — that notice goes to the session owner.

**The judgement to make:** thirteen questions is a real completion risk. If it
reads as long, tell me which ones to move into the call and I will flip their
`ask_when` — or do it yourself on `/strategy/template`.

---

## Check 3 — Watch whether the drafted map rows are usable

During Check 1, or on a session rebuilt from a real call's notes.

- **Draft rows with Claude** after four or five diagnostic answers. Three to five
  rows should appear in the tray.
- Read each one as a row you would put in front of the prospect: is the
  bottleneck theirs or Claude's invention? Is the measurable something they
  already count?
- Complete every question in one area and confirm a **second** draft run fires on
  its own, that rows already in the tray are unchanged, and that a row you
  already accepted is untouched.
- Check `/ai-usage`: one `ai_call` per run, with tokens and cost.

**If the rows are noise, that is a bug in my prompt, not a fact about AI.** Tell
me what was wrong with them — invented numbers, generic fixes, wrong owner — and
I will fix the prompt.

---

## Check 4 — Read the PDF as the prospect

This is the check where a mistake is expensive: the PDF goes to someone who is
not yet a client.

1. On a session with content, put something distinctive in **every** private
   field: a note under a Snapshot answer, a note under a diagnostic answer, the
   §3 alignment observation, a row's **mechanics** column, and §9's investment
   range.
2. **Preview it** (the PDF card). Read every page. **None of those five things may
   appear.**
3. Turn on **Include Notes / mechanics from experience** only. Preview again:
   that column appears and the other four still do not.
4. Turn it back off.
5. **Download the file** and read it as a file — the preview and the attachment
   are built from the same content, and this is the one that gets sent.

**Then send it** and confirm it lands, that the Outbox row says `sent`, and that
it shows on the contact's timeline.

---

## Check 5 — Convert a session and check the work before the engagement starts

> **Fixed 2026-09-21, found by this check.** "Create the work" appeared to do
> nothing. It had reached the API every time and been refused every time, for two
> reasons — all nine of Noble Baker's rows carry a measurable and none had a
> baseline, and one row set to **Leave it out** was a word the server did not
> know — and the refusal was drawn in the page's banner, at the top, three
> screens above the button that caused it. Three things changed: **Leave it out
> now works** (it is what AC-4.11 calls de-selecting, and it leaves the map row
> accepted and unconverted); **the refusal appears in the card**, beside the
> button, with every row it names marked **not ready**; and **one press now names
> every row that is not ready**, rather than refusing on the first one it meets —
> nine rows used to be nine presses to learn nine things. The baseline and target
> boxes are number fields now: "7 a week" reaching a decimal column used to be a
> 500 with nothing in it you could act on.

1. Accept three or four map rows, with a measurable and a 30/60/90 on each.
2. **Convert to work.** Choose **a goal** for some and **a project** for others;
   leave one out. The line under the button says what the press will do —
   *"Creates 2 goals and 1 project, leaving 1 out"* — before you press it.
3. A goal carrying a measurable **will not convert without a baseline** — either
   type today's reading or tick **Not measured yet**. That refusal is deliberate:
   a measurable with no starting reading cannot be reported against later. The
   baseline is the **figure only**; its unit belongs in the measurable.
4. Confirm. Then open **Work** and read what was created: title, owner, target
   date, measurable, and the goal's baseline and target.
5. Check the owner mapping: a row whose owner text is exactly a contact's name at
   that company resolves to that person; *"Maria in dispatch"* and an ambiguous
   first name stay as text with nobody assigned. That is correct — guessing an
   accountable person is worse than leaving it to you.
6. Check the prospect is now a client: their contact type, and the company's
   client flag.

**Edit anything that reads wrong before the engagement starts.** That is the
point of doing this before day one rather than after.

---

## Also worth a look, though not a numbered check

**The template editor** (`/strategy/template`, founder fractional only). Change a
question's wording, move one between the form and the call, clear a must-ask,
**Save**. Then open a session you had already started: it is **unchanged**. A
session renders from the copy of the template it took when it started, so an edit
mid-engagement can never move anything under you mid-call. Reordering, adding and
deleting questions are not in Beta's editor — they come with V1's
multi-discipline work.

---

## Preparing for a session

On a Draft session, **Prepare for this session**: their website, and anything you
already know pasted in — old emails, call notes, whatever. One Claude call with
the web open reads the site and comes back with what they do and how they sell,
where a business of that shape usually breaks, a rewording of **each** pre-call
question in their own words, and **five extra questions** to ask live.

**Nothing it suggests is applied.** Tick the rewordings you want — **edit any of
them in the box first** if you want it simpler — and **Apply selected to the
template**. They all arrive in the template editor as unsaved changes, and you
press Save **once**. A single one can still be copied on its own, and it carries
your edit with it. The usual order applies either way: edit the template, *then*
start his session. An extra question shows in the live view only
once you **pin** it, under **Your questions**, as a prompt with a note field of
your own. It is never scored and never joins the template.

**It marks what it read.** A line beginning *"Their site says"* is the website
talking; one beginning *"Likely"* is Claude guessing. Outside those two it is
told to assert nothing your inputs do not carry, and specifically not to invent
revenue, headcount, customer counts, locations, names or dates.

**It is yours.** The brief reaches no prospect surface — not the form, not the
questions email, not the PDF — and a VA does not see it at all. Cost shows on
**AI usage** as one call, with the number of web searches beside it; **searches
are billed on top of tokens**, so the dollar figure there is the token cost and
the search count is what tells you the rest.

---

## When the prospect will not click a link: email the questions

**The session runs on the laptop, so the form's link only works on this
machine.** For a prospect who will not click a link — or cannot reach one — the
questions go in the body of an email instead.

On the session, under **The pre-call questions**: *Or email the questions
instead*. Edit the opening line, **Send the questions**.

- It goes **from your own address**, not the practice alias, so their reply
  lands in your inbox. If your send-as is not verified it falls back to the
  alias, and the banner names the address it actually used.
- It carries **every pre-call question** with the merge fields resolved, and the
  **1–10 scale explained once** above the six components.
- It carries **nothing you keep to yourself**: not the §3 alignment observation
  you never ask aloud, and not §9's money.
- **A VA cannot send this one**, though they can still send the form link. The
  link is template-only; this has your words in it and goes from your address.

**When the answers come back, type them into the live view** — the pre-call
questions are editable there. They save as **yours** (`answered_by =
fractional`), and each one is marked **"typed in · questions emailed"**. Read
that marker as a fact about the session, not the sentence: it says the pre-call
came back by email and you typed it. It does not claim a given line was copied
out of a reply.

---

## Customising the questions for one prospect, before his session

**Read this first: in Beta there is one template for the whole practice.** There is
no per-prospect template and no per-session override. "Customising it for him" means
**editing the practice's template and then starting his session** — and the edit stays
in force for **every session started after his** until you change it back. The snapshot
protects sessions that already exist; it does not un-edit the template.

**The order is the whole trick.** The snapshot is taken at the moment you press
**Start**. Edit first, start second.

1. **Strategy** in the left-hand navigation.
2. **"Edit the template"** — the link under the heading, founder fractional only.
3. Find the question. The cards are the nine sections in their running order, and each
   question shows its key (`s3_three_year_picture`), its diagnostic area, and a red
   **financial** chip on the two §9 money items.
4. Change any of **three things, and only three**: the **wording** (the box itself),
   **When to ask** — *On the pre-call form* or *In the call* — and **Must ask**.
5. **Save N changes**, at the top of the page. It answers *"Saved N questions. Sessions
   already under way are untouched."*
6. Back to **Strategy** → **Start a session** → type his name, pick him from the
   results, set the date and time, **Start**.
7. Open the session and **Send the form**. The form renders from his snapshot, so it
   carries the wording you just saved.

**What you cannot change in Beta**, and the editor refuses rather than quietly
ignoring: reordering, adding or deleting a question, the privacy flags
(`is_financial`, `has_fractional_note`), and the section time budgets. All V1.

**If you start the session and then edit the template**, his session keeps the old
wording — there is no way to re-snapshot it and no way to delete a session. The clean
recovery is to **start a second session for the same prospect** after the edit and run
that one; the first sits in the list as a Draft and harms nothing.

**Before editing anything, check whether you need to.** The merge fields already
personalise every prompt that uses one — `{Company}`, `{Visionary}`, `{Integrator}`,
`{Location A}`, `{Location B}`, `{Session date}`, `{Fractional name}` — so a question
that reads generically on the template often reads specifically to him on the form.

### The snapshot rule, confirmed

**A later edit cannot reach his session.** `services.start` freezes the whole template
into `strategy_session.template_snapshot` — sections, questions, wording, `ask_when`,
`must_ask`, the schemas — and the live view, the pre-call form and the PDF all render
from that copy. Nothing in a running session points at the template rows, which is what
makes this structural rather than a promise.

Two tests hold it:

- **AC-4.2** — flip a question to the pre-call form: it appears on a **new** session's
  form and **not** on one already under way.
- **AC-4.12 / AC-4.19** — delete a section, reword questions, change a response schema,
  then read a completed session's payload: **identical**. A soft-deleted question is
  still a row in its snapshot, because it was asked.

---

## Where the five checks stand, 2026-09-21

| Check | Ran | Outcome |
|---|---|---|
| 1 — a real session with a real prospect | **not yet** | **Open.** The only honest test of this module |
| 2 — the pre-call form as a prospect | 2026-09-19 | Passed, after the emailed link was fixed |
| 3 — are the drafted rows usable | 2026-09-19 | *"Viable — I would use them on a real call."* **N = 1** |
| 4 — the PDF read as the prospect | 2026-09-19 | Passed, after ratings, comments and the merge field were fixed |
| 5 — convert and check the work | 2026-09-21 | Passed on the re-run: work created per row, Noble at Closed Won, the session converted |

**Module 4 is signed off with Check 1 open.** Two judgements from the Check 5 run are
recorded in the build plan rather than carried in anyone's head: nine "Not measured
yet" ticks is acceptable friction for now and gets revisited after a real session, and
an owner that lands as text with nobody assigned is correct.

---

## What I would like back

For each check: passed, or what it showed. For Check 1 and Check 3 especially,
your judgement in your own words — I will record the AI's quality as *what you
said about N real sessions*, with N, and not as a pass.
