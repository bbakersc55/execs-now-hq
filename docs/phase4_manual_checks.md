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

1. Accept three or four map rows, with a measurable and a 30/60/90 on each.
2. **Convert to work.** Choose **a goal** for some and **a project** for others;
   leave one out.
3. A goal carrying a measurable **will not convert without a baseline** — either
   type today's reading or tick **Not measured yet**. That refusal is deliberate:
   a measurable with no starting reading cannot be reported against later.
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

## What I would like back

For each check: passed, or what it showed. For Check 1 and Check 3 especially,
your judgement in your own words — I will record the AI's quality as *what you
said about N real sessions*, with N, and not as a pass.
