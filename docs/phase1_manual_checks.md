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
mailpit --smtp localhost:1025 --listen localhost:8125   # terminal 4
```

Then open **http://localhost:5200** and sign in with Google.

**Two things to know before you begin.**

**Nothing you do here can email a real person.** `PUBLIC_BASE_URL` is localhost, so every message goes to Mailpit at **http://localhost:8125** unless the address is an exact match in `DEV_REAL_SEND_ALLOWLIST`. Keep Mailpit open in a second tab — several checks below are only meaningful if you look at it.

**Mail goes out through your own Gmail.** Beta has no Postmark: every app-originated message is sent by your connected Gmail account with `From` set to `info@getexecutivesnow.com`. **Step 0 below connects it** — do that first, because Check 4 sends. Until it is connected everything still lands in Mailpit and nothing is blocked.

Where a step says *"nothing arrives"*, **that is the thing being verified** — not a limitation.

---

## Step 0 — Connect Gmail and verify the alias

> Not from the build plan. It is first because every later check that sends mail depends on it, and because it is the one part of Beta where the app holds a credential that can send as you.

**Do this once, before Check 1.**

### 0a — One-time Google setup (skip if already done)

Two things must exist before the button will work. Both are in `docs/05_dev_environment.md`:

1. **The redirect URI is registered.** In the `execs-now-hq` GCP project → OAuth client → **Authorised redirect URIs**, `http://localhost:8100/accounts/gmail/callback` must be listed alongside the sign-in one (§5a). Without it Google refuses the consent with a `redirect_uri_mismatch` before you ever see a consent screen.
2. **`info@getexecutivesnow.com` is a confirmed send-as alias on your Gmail** — added in Gmail, *and* the confirmation link clicked (§5c). The app can check this for you but cannot do it for you.

### 0b — Connect

**0.1** Click **Email settings** in the sidebar. → The page shows **not connected**, and the practice alias reads **connect to check**.

**0.2** Read the **Transport in use** card before doing anything. It says `gmail` and names what that means. Below it, in red: *"No Gmail account is connected for this practice"* — that is the state every send is currently failing with, stated plainly rather than discovered later.

**0.3** Click **Connect Gmail**. → Google's consent screen. It asks for exactly two things: **send email on your behalf** and **see your email settings**. 

> **It does not ask to read your mail.** If the consent screen mentions reading your messages, stop and tell me — that is Tier 2 leaking into Tier 1 and it is a bug.

**0.4** Leave **every box ticked** and approve. Unticking one gets you a refused connection and an error naming the scope you dropped — nothing is stored in that case.

**0.5** → You land back on **Email settings**. Green banner: *"Connected bryan@getexecutivesnow.com."*

### 0c — Read the three things this page tells you

**0.6 — Your connection.** The card shows the address, **connected**, when, and what you granted in plain English. If it also carries a **practice sending account** tag, this is the connection all app mail goes through.

**0.7 — The practice alias.** `info@getexecutivesnow.com` shows one of three states, and they mean different things:

| Badge | What it means | What to do |
|---|---|---|
| **verified** | Gmail confirms you may send as it | Nothing — you are done |
| **listed, not confirmed** | The alias is on your account, but you never clicked Gmail's confirmation email | Find that email, click the link, then **Verify again** |
| **missing** | The alias is not on the account at all | `docs/05_dev_environment.md` §5c, then **Verify alias** |

**0.8 — The send-as list.** Every address Gmail says this account may send as, with Gmail's own status for each and the practice alias tagged. This is the list the app reads; if `info@` is not in it, that is *why* verification failed, visible rather than inferred.

**0.9 — If the alias is not verified,** the page says so in red and states the consequence: **nothing sends, and there is no fallback to your personal address.** That is deliberate — a client digest arriving from `bryan@…` instead of `info@…` is worse than a visible failure. Fix it here before continuing.

### 0d — Confirm the boundaries

**0.10 — A VA cannot do any of this (H7).** If you have a VA account, sign in as them: **Email settings does not appear in the sidebar**, and the URL `/settings/email` returns *"A VA does not connect a mailbox."* A VA never holds a credential that can send as your practice.

**0.11 — A CF connects their own, not yours.** A CF sees this page for **their own** mailbox. Yours is not shown to them as theirs — but the practice sending status *is* visible to them, because a broken token of yours stops their mail too.

**0.12 — Disconnect is real.** Click **Disconnect**, confirm the page returns to **not connected**, then reconnect. The stored refresh token is deleted with the connection, not orphaned — the same cascade that runs when you remove a staff member.

**What you are checking:** that the app asked for the narrowest possible permission, that it tells you the truth about the alias before you rely on it, and that a VA cannot get near it.

> **If Check 4's send fails later with "Reconnect Gmail in Settings",** come back here — that is the token having been revoked, and this page is where it is fixed.

---

## Check 1 — Import your real book of business

> *Build plan: "the highest-consequence data event in Beta. Read the dry run before committing. Then roll it back, confirm the count returns, and import again."*

**1.1** Click **CSV import** in the sidebar.

**1.2** Choose your contacts CSV. → The wizard moves to **2. Map columns** and has guessed a mapping from your header names.

**1.3** Check every row of the mapping table. Anything you do not want imported, set to **— ignore —**. The right-hand column tells you what the non-obvious targets do.

> **Map your notes column to `notes`, not to `background`.** A `notes` column becomes a real note attached to the contact, which is searchable and appears on their timeline. `background` is the short "who this is / how we met" line on the record itself.

**1.3a — Your Phone, Status and Tags columns now have targets.** These were missing when you first ran this check:

| Your column | Map it to | What happens |
|---|---|---|
| Phone | **phone** | becomes the contact's **primary** number |
| Mobile (or a second phone column) | **phone** | imported as a **non-primary** number — the first phone column in your file wins |
| Tags | **tags** | split on commas *and* semicolons, trimmed, de-duplicated |
| Status | **contact_type** | you map each value by hand in step 2b |
| Stage | **pipeline_stage** | a *separate* column from Status — you pick its pipeline, then map each value |

> If a contact already has a primary number, the imported one lands **alongside** it as non-primary. Nothing you set by hand is displaced.

**1.3b — Your two pipelines.** Before mapping values, know what you are mapping into. The app now models **two pipelines**, seeded with your own stages:

| Pipeline | Stages |
|---|---|
| **Sales** | Initial Contact Made → Prospecting → Follow Up Needed → Qualified → Consult Given → Proposal Given → Decision Making → Negotiation → **Closed Won** → Closed Lost → Nurture |
| **Referral partners** | New Partner → Follow-up Sent → Flyer Sent → Nurturing → Active Referrer → Dormant |

> **These are yours to change.** Rename, reorder, add and remove them freely afterwards — nothing in the app keys on a stage's *name*. Each stage carries a hidden **meaning** (entry / working / qualified / won / lost / parked) and that is what the rules use. Rename "Closed Won" to "Signed" and the client invariant still works.

> **A contact can be in both pipelines at once.** A referral partner who becomes a prospect appears on both boards, with an independent stage in each. That is the whole reason for this change.

**1.3c — Step 2b: map your values.** Clicking **Next: map values** shows one section **per mapped column** — your Status column and your Stage column each get their own — listing **every distinct value with a row count**. Read those counts: they are a free audit of your own data.

- For a **Stage** column, pick **which pipeline the column is about** first. That choice applies to the whole column.
- For a **Status** column, map each value to a **contact type**, and optionally *also* place them at a stage in a pipeline of your choosing.
- Anything you do not want, tick **ignore**.

> **Values are matched trimmed and case-insensitively**, so `Client`, `client` and `client ` are one row here, not three.

**1.3d — Read this before mapping anything to Closed Won.** Mapping a value to the Sales pipeline's **Closed Won** does what moving that person by hand would do (FR-1.6a): it adds the **client** contact type *and* **flags their company as a client company**. The row says so underneath the dropdown, and the dry run warns you again before you commit.

> **Reaching "Active Referrer" in the referral pipeline does none of that.** A nurture pipeline's end state is not a sale. Only a *won* stage in the *sales* pipeline makes someone a client.

> **It does not fire your stage automations.** A backfill of 40 existing clients will not create 40 follow-up tasks or queue 40 client-facing email drafts. An import is a statement about history; the automations exist for a prospect moving *today*. If you want a rule to fire for someone, move them by hand afterwards.

**1.3e — Anything you leave unmapped becomes a row error.** That is deliberate: silently dropping your Status column would lose exactly the distinction you were trying to import. The dry run names the value and the row. So does a Stage column whose pipeline you never chose.

**1.3f — Save the mapping.** In **Remember this mapping**, give it a name (e.g. `Outlook export`) and click **Save mapping**. It remembers the column mapping **and** every value mapping together, so your next export from the same system is one click. Saved mappings appear as buttons at the top of step 2.

**1.4** Click **Run dry run**. → **Nothing has been written yet.** You get five counts: create, update, skip, needs-a-decision, error.

**1.5** **Read the counts before doing anything else.** Expect roughly as many creates as rows in your file. A large `update` count means the app matched more of your rows to existing contacts than you expected — stop and look at why.

**1.6** Scroll to **Rows needing attention**. Every error names its row number and the offending column. Every "needs a decision" is a row where more than one existing contact matched the same name at the same company — the app will not guess between them.

**1.7** Scroll to **First 20 rows as they will be written** and read them as data, not as a spreadsheet. This is your last look before commit. Each row now shows what the three new mappings actually produced:

- **Phones** — both numbers, with one marked `primary`. Check the *right* one is primary; if not, your two phone columns are the other way round in the file.
- **Type** — what that row's Status value resolved to.
- **Pipelines** — every placement, each naming its pipeline. A row may show **two**: one in Sales and one in Referral partners. A stage that fires the client invariant is tagged amber, because it carries the company flag with it.
- **Tags** — as they will be stored, already split and de-duplicated. If you see one long tag instead of three, your separator is something other than a comma or semicolon.

> **A tag over 64 characters is reported as a row error** naming the column, rather than being truncated or failing the whole import. If you see that, a delimiter is wrong somewhere in that row.

**1.8** Click **Commit import**. → Step 4 shows **Committed**.

**1.9** Click **Contacts**. Confirm the count went up by the number the dry run predicted.

**1.9a — Spot-check one contact.** Open someone from the import who had a phone, a status and tags. Confirm: both numbers present with the right one primary, the tags on the record, the contact type set, and a **Pipelines** panel listing every pipeline they are in with the stage you mapped. If any placement is **Closed Won** in Sales, open their company and confirm it is flagged as a client company.

**1.9b — Check the boards.** Click **Pipeline**. There is a **selector at the top with one button per pipeline**. Switch between Sales and Referral partners and confirm the columns are your stages and the counts look right. A contact who is in both is marked *"also in …"* on their card.

**1.9c — Confirm the two pipelines are independent.** Find (or place) a contact who is in both. Move them one stage in **Sales**, then switch to **Referral partners** and confirm **their referral stage did not move**.

**1.10 — Now roll it back.** Return to **CSV import**, find the batch in **Import history**, click **Roll back**. → A banner reports how many were deleted, how many reverted to pre-import values, and how many were **skipped because they were edited after the import**.

> **What rollback undoes:** created contacts go entirely, and with them their phones, tags, type links **and pipeline positions**. For contacts that already existed, a position the import **created** is removed and a position it merely **moved** is put back where it was. **One thing it deliberately does not undo:** a company flagged as a client company stays flagged, because FR-1.6a never unwinds that automatically and the company may have other live client contacts. Unflag it by hand if you need to.

**1.11** Click **Contacts** and confirm the count is back where it started.

**1.12** Import the same file again and commit. This is the one you keep.

**What you are checking:** that the dry run told you the truth, and that rollback is real. A backup you have never restored is a hypothesis; so is a rollback you have never run. **And that no column in your real file was left with nowhere to go** — if one still is, tell me: that is the same gap as before, not a limitation to work around.

---

## Check 2 — Confirm the ambiguous-match list

> *Build plan: "Confirm the ambiguous-match list contains the duplicates you already know about."*

### 2a — Add a contact and a company by hand

> Not from the build plan. It is here because Check 2 is about duplicates, and **the fastest way to make one is to type a person who is already in the file.** Until now there was no way to add anyone by hand at all.

**2.0a** Click **Contacts** → **Add contact** (top right).

**2.0b** Fill in the person as you actually hold them: first and last name, title, **email** (click *Add another email* for a second one — the **primary** radio decides which is the primary, and only one can be), **phone**, **source**, **tags** (comma or semicolon separated), and the short **background** line.

> **Owner defaults to you.** The form says so at the bottom. That default is what drives a CF's own visibility later (FR-1.9c), so leave it alone unless you are entering someone else's contact.

**2.0c — Company: pick or create.** The **Company** dropdown lists every company you have. If theirs is not there, leave the dropdown on *none* and type the name in **…or a new company** — it is created on save. Typing a name that already exists (any capitalisation) **attaches them to the existing company** rather than creating a second one; that is the same duplicate the merge screen exists to clean up.

**2.0d — Types.** Tick any that apply; a person can be several. **Ticking *Referral partner* shows a warning**: saving will queue their onboarding email in the Outbox *for approval* and place them in the referral pipeline. It sends nothing. That is FR-1.23 firing through the same path the contact page uses.

**2.0e — Optional pipeline placement.** Choose a **Pipeline** and then a **Stage** to put them straight onto a board. Leave it on *not yet* and they are created with no pipeline position at all — which is fine, and honest, for someone you have only just met.

**2.0f** Click **Save contact**. → You land on their contact page. Check the **Pipelines** panel matches what you chose, and **Details** shows both email addresses with the right one primary.

**2.0g — Now add a company directly.** Click **Companies** → **Add company**. Name, industry, **email domains** (used to match imported contacts to this company by their address), and address.

> **There is no "client company" checkbox, deliberately.** That flag is derived when one of their contacts reaches the sales pipeline's **Closed Won** stage (FR-1.6a). One answer to "is this a client", not two that can disagree.

**2.0h** If you are the FF you also get **Client seat count**. A VA does not see the field at all — matrix 4.12 — and the API refuses it from them even if they try.

**2.0i — Confirm the duplicate guard.** Try to add a second company with a name you already have. → **Refused**, naming the existing one and telling you to open it instead.

**2.0j — Now edit what you just added.** Open the contact → **Edit contact** (top right). Every field from the add form is here and prefilled. Change the title, **remove one email address**, add a phone, and use the **primary** radio to move the primary to the new number. Save, and confirm the **Details** panel matches.

> **Only an FF sees the Owner field.** Ownership drives a CF's entire visible universe (FR-1.9c), so reassigning it is not CRM hygiene. A VA editing the same contact does not see the field at all.

**2.0k** Open a company → **Edit company**. Same thing: name, industry, domains, address, and (FF only) the seat count.

**What you are checking:** that you can get a real person into the system without a CSV, that one primary email is genuinely enforced, that typing an existing company name attaches rather than duplicates, and that everything you can add you can also change.

---

### 2b — The ambiguous-match list

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

> **Duplicates are now collapsed.** You reported the survivor carrying the same phone number twice. Emails match case-insensitively and phone numbers match on their digits, so `+1 555-0100` and `15550100` are recognised as one number and only one row survives — with exactly one primary. Genuinely different numbers are both kept.

**2.8** Re-run the dry run for the same CSV. → The row that was *needs-a-decision* now resolves to a single contact and counts as an **update**.

**Making a duplicate on purpose.** If your dry run produced no ambiguous rows, use **Add contact** (2a) to type someone who is already in your book — same name, same company — then open either record and use **Find duplicates**. That exercises the same matching rules without needing a second CSV.

**Merging outside an import.** You do not need a CSV to merge. Open any contact, and in the **Possible duplicates** panel click **Find duplicates**. It looks for contacts sharing an email address, then the same name at the same company, then the same name anywhere — each result shows *why* it matched, ranked with the strongest first. Click **Merge…** on any of them to open the same screen.

**What you are checking:** that the matching rules — exact email, then name + company — catch the duplicates you already know about, and that they refused to guess on the rest. **A short ambiguous list is only good news if it matches your own knowledge of your data.** If you know of duplicates that did not appear here, tell me: the matching order needs work.

---

## Check 3 — Move a real prospect through the pipeline

> ### 📬 Mailpit is at **http://localhost:8125**
> It is a **separate program in your browser**, not a screen inside the app. Keep it open
> in its own tab for this check and the next — several steps are only meaningful if you
> look at it. If the page does not load, terminal 4 is not running.

> *Build plan: "Move a real prospect through the pipeline and watch the follow-up task appear and the email draft queue."*

**First, set up a rule to watch.**

**3.1** Click **Stage automations** → **Add a rule**.

**3.2** Set *When a contact becomes* = **Qualified lead**, *Then* = **Create a task**, *Task title* = `Book strategy session`, *Due in* = `3`. Click **Add rule**.

**3.3 — First create a template, then the email rule.** This is the step that was missing: a *draft an email* rule cannot be created without a template, and there were none, so the dropdown was empty and the rule was never made. That is why your Qualified move fired a task and no email — **the app was right; only one rule existed.**

- On **Stage automations**, use the **Email templates** card at the top. Name it `Qualified follow-up`, give it a subject and a couple of lines of body, click **Create template**.
- Now **Add a rule**: same stage (**Qualified**), *Then* = **Draft an email for approval**, and pick the template you just made.

**3.3a** Confirm the **Active rules** table now lists **two** rules on Qualified — one tagged *fires immediately*, one *queues for approval*.

**3.4** Read the **Active rules** table. Each rule is described in plain English, and tagged either **fires immediately** or **queues for approval**. Confirm that matches what you intended.

**Now move someone.**

**3.5** Click **Pipeline**. You get a column per stage with counts.

**3.6** Click a real prospect in the **Lead** column → a *Move* panel opens. Set *New stage* = **Qualified lead**, click **Move**.

**3.7** → A green banner confirms the move. Click **Contacts**, open that person, and look at the **Timeline** panel:
- a **stage** entry recording the move,
- a **task** entry: *Task: Book strategy session, due …*

**3.8** Click **Outbox**. The draft is here in **pending approval**, showing **"Expires … — if not approved by then it will not send."** Both rules fired: a task on the timeline *and* a draft here.

**3.9 — The important part.** Open **http://localhost:8125**. → **Mailpit is empty.** The rule created a task and queued a draft; it sent nothing.

**3.10 — Move someone by dragging.** Back on **Pipeline**, **drag a card from one column to another**. → It moves, and the same automations fire as the panel's *Move* button. Click a card's **name** to open the contact; use **Move…** on the card if you prefer the panel (that path stays for keyboard use).

> **Dropping onto a lost stage does not move them straight away** — it opens the move panel with that stage selected so you can type a reason. FR-1.7 asks for one there, and a drag that skipped the prompt would be a quieter way of doing the move that most deserves a note. The reason may still be skipped.

**What you are checking:** that a deterministic rule you configured fires immediately, and that anything bound for a client's inbox stops and waits for you.

---

## Check 4 — Read a generated referral touch

> ### 📬 Mailpit is at **http://localhost:8125**
> Again: a separate browser tab, not a screen in the app. Everything you approve lands
> there unless the recipient is on the dev allow-list (4.9b).

> *Build plan: "Read a generated referral touch. Does it sound like you, and would you send it to a real partner? If not, the template or the prompt is wrong and it is a Phase 1 bug."*

**4.1** Click **Referral settings**.

**4.2** In **What I'm working on lately**, write three to five lines about what you have actually been doing this month — in your own voice, as you would tell a peer. Click **Save blurb**.

**4.3** Under **Marketing flyer**, upload your one-page PDF overview.

**4.4** Click **Contacts**, open a real referral partner, and in **Referral partner settings** click **Make a referral partner**.

**4.5** → A banner tells you a follow-up draft is waiting. Set *Cadence* and, if you have one, *Fee terms* (e.g. `10% of first 3 months`).

**4.6** Click **Outbox** in the sidebar — it is there for you, a CF and a VA. Filter **pending approval**, and open the **referral onboarding** draft. → It carries the **AI-drafted** tag and the flyer.

> **If the Outbox is empty, its empty state tells you what lands there and from where** — stage rules, referral touches, onboarding, and anything you send from a contact. Nothing in it ever sends itself.

**4.6a — Draft a touch on demand, without waiting for the cadence date.** Two click paths, both landing in the same place:

- **From the contact:** *Contacts* → open the partner → **Referral partner settings** panel → **Draft touch now**.
- **From the list:** *Referral settings* → the **Referral partners** table → **Draft touch now** on that partner's row.

→ A green banner: *"Touch drafted into the Outbox, pending approval. Nothing was sent."* Open **Outbox** → **pending approval** and it is there, tagged **AI-drafted**.

> **It uses the same composer the scheduled job uses**, so what you read here is what the automation would have produced. And it **does not move their next touch date** — an extra touch now is not a replacement for the one already due.

**4.6c — Draft touches for several partners at once.** *Referral settings* → tick partners in the table, or **Select all N shown**, deselect any you do not want, then **Draft touch for N selected**.

> **Each recipient gets its own Outbox row.** One row addressed to forty people would be a mailing list, and the approval step would stop being a per-recipient decision. Partners with no email, or who are not partners, are skipped and named in the banner.

**4.6d — One-off mail to a filtered group.** *Contacts* → the **Filter** card → pick a **Type** (e.g. Referral partner) or a **Pipeline stage** → **Select all N shown** → **Draft email**. Write a subject and body — `{first_name}` is replaced per recipient — and click **Draft for N recipients**.

> **"Select all" means all rows currently in view**, not everyone in the database. That is deliberate: selecting behind a filter you cannot see is how people mail the wrong list.

**4.6e — Approve a batch in one pass.** *Outbox* → **pending approval** → **Select all N shown**, untick anything you want to read again, then **Approve N selected**. Each one is still approved individually and the banner reports any that failed, with the reason.

**4.6b — Check the imported partners have a cadence at all.** *Referral settings* → the **Referral partners** table. Every row should show a **cadence** and a **next touch** date. A row reading **"none — scheduler will skip them"** is a partner the automation cannot see.

> All 40 of your imported partners arrived with no cadence and no next-touch date — the importer was writing the type directly and skipping the referral path entirely. They have been backfilled to **monthly**, next touch one month out, and no onboarding email was queued for any of them (they were met long before the import). Tell me if any of those 40 should be on a different cadence.

**4.6f — Who it comes from.** *Email settings* → **Who your mail comes from**. Four rows, one per kind of email:

| These emails | Default |
|---|---|
| Referral touches | **Your own address** — a partner asked for introductions should hear from a person, not `info@` |
| Referral onboarding | **Your own address** |
| Stage-rule emails | The practice alias |
| One-off and bulk emails | The practice alias |

> **Both options are limited to verified send-as addresses.** If your own address is not verified yet the option is disabled and everything goes from the alias — Gmail would refuse anything else, and a choice that failed at send time would be worse than no choice.

**4.6g — Your signature.** Same screen. Blank means *your full name over the practice name*. Set it to whatever you actually sign off with; it replaces the bare `Executives Now` line on every touch and one-off email.

**4.7 — Now read it as the recipient would.** Three questions:

1. **Does it sound like you?** Not "is it grammatical" — would this partner recognise it as coming from you?
2. **Is the fee line right?** If you set fee terms, there is a line reminding them of the arrangement. If you left it blank, **there must be no fee language at all.** Check that.
3. **Is the reciprocal line useful?** Every touch says what you are looking for, so the partner can send referrals *and* knows what to send. Does it name something real?

**4.8** If any answer is no, **tell me** — that is a Phase 1 bug in the composition or the prompt, not something to fix by editing this one draft.

**4.9 — Read the delivery badge before you approve anything.** Every Outbox row now says where it will actually go, *before* approval:

| Badge | Meaning |
|---|---|
| **Dev mailbox (Mailpit)** | The recipient is not allow-listed. Approving sends it to Mailpit and it never reaches them. |
| **Real delivery** | The recipient **is** allow-listed. Approving sends a real email to a real person. |

**4.8a — Review & edit is a real editor now.** Open any pending draft and click **Review & edit**:

- **Send from** — override the sender for this one draft. Only verified addresses appear.
- **Subject** and a formatted body — bold, italic and lists. Pasting from Word or Gmail keeps the words and drops the styling, so the HTML stays clean. A plain-text alternative is generated alongside it.
- **Add an attachment** — any file up to 10 MB, and **Remove** on any attachment already there.

> Your edits are saved **before** the message is approved, so what you read is what goes out.

**4.9a** Click **Review & edit**, make any change, then **Approve & send**. → With a **Dev mailbox** badge, check Mailpit: the message is there, addressed to your partner, **not delivered to them**.

**4.9b — To send one for real, add yourself to the allow-list.** *Email settings* → **Dev builds — who may receive real mail** → type your own address → **Allow real delivery**. Go back to the Outbox: that row's badge flips to **Real delivery** immediately, no restart. Approve it and check your own inbox.

> **Exact addresses only.** Try `@getexecutivesnow.com` and it is refused, telling you why: one entry like that would put every colleague and client at that domain back in range (assumption H6). Addresses set in `.env` show as **locked** — the environment is the floor, and the app cannot lower it.

> **This whole section only exists on a localhost build.** On a deployed build it is not rendered and the API behind it returns 404.

**4.10 — Check the staleness warning.** Come back in a month, or ask me to age the blurb. A touch drafted against a blurb older than the contact's cadence carries a visible warning naming its age. It still sends — sometimes last month's work is still this month's news — but you should never mail twelve partners the same stale paragraph without noticing.

**What you are checking:** the one thing I genuinely cannot judge. I can prove the three parts are present; only you can say whether it sounds like you.

---

## Check 5 — Flyer and onboarding timing

> *Build plan: "Confirm the flyer attaches and that an onboarding draft appeared the moment you tagged a referral partner."*

**5.1** You saw this in 4.6 — the draft appeared **immediately** on tagging, not on the next cadence date. That is deliberate: it is the first touch, sent while the meeting is fresh.

**5.2** On the contact, check **next touch** is one cadence period from **today**, not from when the contact was created.

**5.3 — Confirm it fires only once.** Remove the referral-partner type and add it again. → **No second onboarding draft appears** in the Outbox.

**5.0 — Re-upload your flyer first. This is required.** *Referral settings* → **Marketing flyer**. If it shows **file missing**, the record exists but the file does not: the app was storing the *metadata* for uploads and throwing the bytes away, which is why your delivered attachment was 0 bytes. Choose the PDF again and upload it.

> → The badge turns green and shows the real size (about **395 KB**). **Every file uploaded before this fix is affected** — your flyer and two Outbox attachments. There is nothing to recover; they were never written anywhere.

**5.0a — Confirm the attachment is real this time.** Tag a partner, open the onboarding draft in the **Outbox**, and check the attachment line shows the filename *and a size in KB* with no red **file missing** badge. Approve it to your own allow-listed address and **open the PDF from Gmail** — it should be the full document.

> **A send that would attach an empty file is now refused**, naming the file and telling you to re-upload. That is deliberate: delivering a message that says "I've attached an overview" with a blank attachment is worse than not delivering it, because neither you nor the recipient can tell from the outside.

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
