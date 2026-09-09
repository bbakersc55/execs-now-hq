# Phase 1 — Manual Checks

**Module 1: Contacts & pipeline · for the owner**

The five manual checks from `04_build_plan.md` Phase 1, as click paths through the actual UI. Everything here is something I cannot verify for you: it needs your real data, or it needs your judgement.

---

## Before you start

Four terminals, from `~/projects/execs-now-hq`:

```bash
gcloud config configurations activate execs-now-hq
./scripts/backup_db.sh                              # back up before touching real data

.venv/bin/python manage.py runserver 8100           # terminal 1
.venv/bin/python manage.py qcluster                 # terminal 2
cd frontend && npm run dev                          # terminal 3
mailpit --smtp-bind-addr localhost:1025 --listen localhost:8125   # terminal 4
```

Then open **http://localhost:5200** and sign in with Google.

**Two things to know before you begin.**

**Nothing you do here can email a real person.** `PUBLIC_BASE_URL` is localhost, so every message goes to Mailpit at **http://localhost:8125** unless the address is an exact match in `DEV_REAL_SEND_ALLOWLIST`. Keep Mailpit open in a second tab — several checks below are only meaningful if you look at it.

**Postmark is not configured**, so AC-1.6 and AC-1.20's delivery half cannot be checked yet. Where a step says *"nothing arrives"*, that is the thing being verified — not a limitation.

---

## Check 1 — Import your real book of business

> *Build plan: "the highest-consequence data event in Beta. Read the dry run before committing. Then roll it back, confirm the count returns, and import again."*

**1.1** Click **CSV import** in the sidebar.

**1.2** Choose your contacts CSV. → The wizard moves to **2. Map columns** and has guessed a mapping from your header names.

**1.3** Check every row of the mapping table. Anything you do not want imported, set to **— ignore —**.

> **Map your notes column to `notes`, not to `background`.** A `notes` column becomes a real note attached to the contact, which is searchable and appears on their timeline. `background` is the short "who this is / how we met" line on the record itself.

**1.4** Click **Run dry run**. → **Nothing has been written yet.** You get five counts: create, update, skip, needs-a-decision, error.

**1.5** **Read the counts before doing anything else.** Expect roughly as many creates as rows in your file. A large `update` count means the app matched more of your rows to existing contacts than you expected — stop and look at why.

**1.6** Scroll to **Rows needing attention**. Every error names its row number and the offending column. Every "needs a decision" is a row where more than one existing contact matched the same name at the same company — the app will not guess between them.

**1.7** Scroll to **First 20 rows as they will be written** and read them as data, not as a spreadsheet. This is your last look before commit.

**1.8** Click **Commit import**. → Step 4 shows **Committed**.

**1.9** Click **Contacts**. Confirm the count went up by the number the dry run predicted.

**1.10 — Now roll it back.** Return to **CSV import**, find the batch in **Import history**, click **Roll back**. → A banner reports how many were deleted, how many reverted to pre-import values, and how many were **skipped because they were edited after the import**.

**1.11** Click **Contacts** and confirm the count is back where it started.

**1.12** Import the same file again and commit. This is the one you keep.

**What you are checking:** that the dry run told you the truth, and that rollback is real. A backup you have never restored is a hypothesis; so is a rollback you have never run.

---

## Check 2 — Confirm the ambiguous-match list

> *Build plan: "Confirm the ambiguous-match list contains the duplicates you already know about."*

**2.1** On the dry run from Check 1, look for the **Duplicates to resolve** panel. It appears above *Rows needing attention* whenever the dry run's *needs-a-decision* count is greater than zero.

**2.2** Each entry shows the CSV row that could not be placed, and underneath it every existing contact that matched. The import will not guess between them.

**2.3** For each one, ask: *do I already know these two people are the same person?*

**2.4 — If they are the same, merge them here.** Click **Merge these two…** on the entry.

**2.5** The merge screen opens with both records side by side.

- **Step 1 — Which record survives?** Two cards, each showing emails, title, type count, stage, and creation date. The **older record is pre-selected**, since it usually carries more history — click the other card to switch. The cards relabel live: **survives** / **merged away**.
- **Step 2 — Resolve field conflicts.** Only fields where the two records actually *disagree* are listed. Each row shows the survivor's value beside the merged-away record's; click either cell to keep it. Everything defaults to the survivor's own value, and changing the survivor in step 1 resets the defaults. If the records agree on everything, this step says so and there is nothing to do.
- **Step 3 — What will happen.** Read it before clicking. It states plainly that notes, tasks, emails, stage history, types, and categories all move; that both email addresses keep working with only one marked primary; that the merged-away record is **soft-deleted, not destroyed**, and its link still resolves to the survivor; and that the merge is audited with your name on it.

**2.6** Click **Merge into <name>**. → You land on the **survivor's contact page** with a green banner confirming the merge.

**2.7 — Confirm the history actually moved.** On that page, look at the **Timeline** panel. Notes and tasks that belonged to the merged-away record are now listed there. Check the **Details** panel: both email addresses are present, one marked primary.

**2.8** Re-run the dry run for the same CSV. → The row that was *needs-a-decision* now resolves to a single contact and counts as an **update**.

**Merging outside an import.** You do not need a CSV to merge. Open any contact, and in the **Possible duplicates** panel click **Find duplicates**. It looks for contacts sharing an email address, then the same name at the same company, then the same name anywhere — each result shows *why* it matched, ranked with the strongest first. Click **Merge…** on any of them to open the same screen.

**What you are checking:** that the matching rules — exact email, then name + company — catch the duplicates you already know about, and that they refused to guess on the rest. **A short ambiguous list is only good news if it matches your own knowledge of your data.** If you know of duplicates that did not appear here, tell me: the matching order needs work.

---

## Check 3 — Move a real prospect through the pipeline

> *Build plan: "Move a real prospect through the pipeline and watch the follow-up task appear and the email draft queue."*

**First, set up a rule to watch.**

**3.1** Click **Stage automations** → **Add a rule**.

**3.2** Set *When a contact becomes* = **Qualified lead**, *Then* = **Create a task**, *Task title* = `Book strategy session`, *Due in* = `3`. Click **Add rule**.

**3.3** Add a second rule: same stage, *Then* = **Draft an email for approval**. If the template dropdown is empty, skip this rule and read the note under 3.7.

**3.4** Read the **Active rules** table. Each rule is described in plain English, and tagged either **fires immediately** or **queues for approval**. Confirm that matches what you intended.

**Now move someone.**

**3.5** Click **Pipeline**. You get a column per stage with counts.

**3.6** Click a real prospect in the **Lead** column → a *Move* panel opens. Set *New stage* = **Qualified lead**, click **Move**.

**3.7** → A green banner confirms the move. Click **Contacts**, open that person, and look at the **Timeline** panel:
- a **stage** entry recording the move,
- a **task** entry: *Task: Book strategy session, due …*

**3.8** Click **Outbox**. If you added the email rule, its draft is here in **pending approval**, showing **"Expires … — if not approved by then it will not send."**

**3.9 — The important part.** Open **http://localhost:8125**. → **Mailpit is empty.** The rule created a task and queued a draft; it sent nothing.

**What you are checking:** that a deterministic rule you configured fires immediately, and that anything bound for a client's inbox stops and waits for you.

---

## Check 4 — Read a generated referral touch

> *Build plan: "Read a generated referral touch. Does it sound like you, and would you send it to a real partner? If not, the template or the prompt is wrong and it is a Phase 1 bug."*

**4.1** Click **Referral settings**.

**4.2** In **What I'm working on lately**, write three to five lines about what you have actually been doing this month — in your own voice, as you would tell a peer. Click **Save blurb**.

**4.3** Under **Marketing flyer**, upload your one-page PDF overview.

**4.4** Click **Contacts**, open a real referral partner, and in **Referral partner settings** click **Make a referral partner**.

**4.5** → A banner tells you a follow-up draft is waiting. Set *Cadence* and, if you have one, *Fee terms* (e.g. `10% of first 3 months`).

**4.6** Click **Outbox**, filter **pending approval**, and open the **referral onboarding** draft. → It carries the **AI-drafted** tag and the flyer.

**4.7 — Now read it as the recipient would.** Three questions:

1. **Does it sound like you?** Not "is it grammatical" — would this partner recognise it as coming from you?
2. **Is the fee line right?** If you set fee terms, there is a line reminding them of the arrangement. If you left it blank, **there must be no fee language at all.** Check that.
3. **Is the reciprocal line useful?** Every touch says what you are looking for, so the partner can send referrals *and* knows what to send. Does it name something real?

**4.8** If any answer is no, **tell me** — that is a Phase 1 bug in the composition or the prompt, not something to fix by editing this one draft.

**4.9** Click **Review & edit**, make any change, then **Approve & send**. → Check Mailpit: the message is there, addressed to your partner, **not delivered to them**.

**4.10 — Check the staleness warning.** Come back in a month, or ask me to age the blurb. A touch drafted against a blurb older than the contact's cadence carries a visible warning naming its age. It still sends — sometimes last month's work is still this month's news — but you should never mail twelve partners the same stale paragraph without noticing.

**What you are checking:** the one thing I genuinely cannot judge. I can prove the three parts are present; only you can say whether it sounds like you.

---

## Check 5 — Flyer and onboarding timing

> *Build plan: "Confirm the flyer attaches and that an onboarding draft appeared the moment you tagged a referral partner."*

**5.1** You saw this in 4.6 — the draft appeared **immediately** on tagging, not on the next cadence date. That is deliberate: it is the first touch, sent while the meeting is fresh.

**5.2** On the contact, check **next touch** is one cadence period from **today**, not from when the contact was created.

**5.3 — Confirm it fires only once.** Remove the referral-partner type and add it again. → **No second onboarding draft appears** in the Outbox.

**5.4 — Confirm the no-flyer path.** Delete the flyer in **Referral settings**, tag a different contact as a referral partner, and open the draft. → It still exists, has no attachment, and carries the warning **"No marketing flyer is uploaded, so this draft has no attachment."** The draft is never suppressed for a missing flyer.

**Merging duplicates** is Check 2 above — it has its own screen now, reachable from both the import wizard and any contact's **Possible duplicates** panel.

---

## Extras worth ten minutes

These are not in the build plan, but they exercise the parts most likely to bite you later.

**Staff.** Sidebar → **Staff** → invite a colleague as a VA. They can now sign in with Google; an address without a membership is refused. Then remove them and read the banner: it names how many sessions were killed, how many client assignments were closed, and how many Gmail connections were removed — and says their work stays on the record.

**Vendors.** Sidebar → **Vendors** → add a category like `Commercial HVAC`, then tag two vendor contacts with it and search. This is the "a client just asked me who does X" path.

**AI usage.** Sidebar → **AI usage**. Empty for now — Module 1's AI drafting writes rows here once a tenant Anthropic key is configured. Worth knowing where it lives, because it is the only place your per-module Claude spend is visible.

---

## What to tell me afterwards

1. **Anything in Check 4 that did not sound like you.** Highest priority — it is the only judgement I cannot make.
2. **Duplicates from Check 2 that the ambiguous list missed.**
3. **Any count in Check 1's dry run that surprised you**, especially a high `update`.
4. **Anything that sent you to a terminal.** Every step in this document should be clickable; if one is not, that is a gap in the UI, not in the API.

Anything found here is a **Phase 1 bug and gets fixed before Phase 2 starts** (`CLAUDE.md`: bugs get fixed in the current module, not carried forward).
