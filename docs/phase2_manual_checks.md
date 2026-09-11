# Phase 2 — Manual Checks

**Module 2: Notes · for the owner**

The four manual checks from `04_build_plan.md` Phase 2, as click paths through the actual
UI. Everything here needs your real calls, your real data, or your judgement — the
automated suite cannot tell you whether a summary is worth keeping.

---

## Before you start

**Restart the job worker first.** A `qcluster` started before today's changes is running
the old code and will fail on every note job. Then register the schedules — once; it is
idempotent.

```bash
# Target: terminal, from ~/projects/execs-now-hq
gcloud config configurations activate execs-now-hq
./scripts/backup_db.sh

.venv/bin/pip install -r requirements.txt              # anthropic + google-cloud-speech are new
.venv/bin/python manage.py ensure_schedules            # notes.process (1 min), notes.purge_expired_audio (daily)

.venv/bin/python manage.py runserver 8100              # terminal 1
.venv/bin/python manage.py qcluster                    # terminal 2 — RESTART it if it was already running
cd frontend && npm run dev                             # terminal 3
mailpit --smtp localhost:1025 --listen localhost:8125  # terminal 4
```

**Add your Anthropic key.** Sidebar → **AI usage** → *Anthropic API key*. It is checked
with Anthropic before it is saved; if the check fails nothing changes. Without a key,
recordings still transcribe, and their summaries show *"Claude could not draft a summary"*
with a button to try again once a key is in.

**For Check 2 you need a second person.** Google sign-in only admits accounts in your
Workspace (`@getexecutivesnow.com`). Invite one as a VA under **Staff**, and use a private
window for them. If you have no second account to spare, tell me and I will set up a
local-only way to sign in as a test VA.

---

## Check 1 — Record a real 20-minute call

1. Before the call, press **n** (or **+ New note** in the sidebar). The capture panel opens
   bottom-right. Optionally link it to the contact.
2. Click **● Record**. The consent reminder appears first. Tell the other person you are
   recording, then **Everyone has agreed — start recording**.
3. You can move around the app during the call; the panel stays put, and it will not close
   while recording.
4. **Stop recording** at the end. You should see *"Recording saved and transcribing."*
5. Open the note. It says *Transcribing…* and checks back every 15 seconds. A 20-minute call
   typically takes a few minutes. `qcluster` must be running.
6. When the transcript lands, the summary appears beside it, marked **Proposed by Claude —
   not attached until you accept it**.

**Then judge it.** Read the transcript for usability. Read the summary for accuracy against
what was actually said.

> **Would you keep this summary?** If not, tell me what was wrong — missed decisions,
> invented detail, wrong attribution, too long. The prompt is in `apps/notes/summary.py`
> and this is the moment to fix it, not after twenty more calls.

Accept it, edit and accept, or discard. Discarding keeps the transcript.

**What to report:** the call length, whether you would keep the transcript and summary,
and anything the summary got wrong. Quality is reported as *observed on N real
recordings* — this is recording 1.

## Check 2 — PIN a sensitive note, then try to find it as a VA

1. Write a note about something genuinely sensitive, with **no title**, and link it to a
   contact. Note a distinctive phrase from the body.
2. Open it → **Set a PIN**. The dialog should refuse to take a PIN until you type a title,
   and explain why: the title stays visible on a locked note, and right now the title *is*
   your first line. Give it a title that does not give the content away.
3. Set a 4–6 digit PIN.
4. In the private window, signed in as the VA:
   - open the contact — the timeline shows **🔒 Note (locked): your title**, nothing more;
   - search the phrase in **Contacts** and in **Notes** — nothing comes back;
   - open the note — a title, an unlock box, and no body.
5. Open DevTools (F12). In **Elements**, Ctrl+F for the phrase. In **Network**, click the
   `notes` and `timeline` requests and search each **Response**. It must be in neither.
   (View Source would not tell you anything: it shows the app's empty shell.)
6. As the VA, enter a wrong PIN five times. The fifth attempt locks the note for 15
   minutes, and even the right PIN is refused until then.

## Check 3 — Reset a PIN and confirm it clears rather than reveals

1. As yourself (FF), in a **new** session (sign out and back in, so you are not already
   unlocked), open the locked note. You see the stub, like everyone else — the PIN is not
   a role.
2. **Email me a link that clears it.** The link arrives in **Mailpit**
   (http://localhost:8125).
3. Read the email: it should name the note by its title, say the link **clears** the PIN,
   and contain neither the PIN nor any of the note's text.
4. Follow the link. The page describes what will happen and changes nothing until you
   click **Clear the PIN**.
5. The note opens with no PIN. Following the same link again is refused.

## Check 4 — The consent reminder wording

Start a recording and read the reminder as if you were relying on it in front of a client.

> *Before you record, tell everyone on the call and confirm they agree. Recording a
> conversation without the other people's consent can be unlawful, depending on where you
> and they are.*

Is that what you want it to say? It appears before the first recording of each sign-in
session; after you confirm it, it does not reappear until you next sign in. It lives in
`frontend/src/components/Recorder.tsx`.

---

## Worth knowing

- **Audio retention** is under **Notes** (FF only). Audio is deleted after the set number
  of days *once it has transcribed*; audio that never transcribed is kept and flagged on its
  note until someone retries or discards it. At **0**, audio goes as soon as its transcript
  exists, and cannot be re-transcribed.
- **Recordings are not in the nightly backup** (your decision). They rely on GCS durability
  and the bucket's 7-day soft delete. Transcripts and summaries are in the database and are
  backed up.
- **If an upload fails** (offline, bucket unreachable), the recording is kept in the browser
  that made it and a yellow banner offers **Retry upload now** and a **download** link. It
  is never discarded automatically.

## What to tell me afterwards

1. Check 1: call length, keep-or-not for transcript and summary, and what the summary got wrong.
2. Checks 2 and 3: pass or fail, and anything that surprised you.
3. Check 4: keep the wording, or your replacement.
4. Whether to turn on Module 1's scheduled jobs (see the Phase 2 report).
