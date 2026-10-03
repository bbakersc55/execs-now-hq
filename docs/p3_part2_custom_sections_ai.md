# P3 part two — custom sections, AI per section, and an AI-drafted pre-questionnaire

**Practices beta program · spec for owner review · 2026-10-03**

**Approved 2026-10-03.** D1–D15 as recommended, with one change to D14: the
owner runs the one v3 and one v2 session **in production with a test contact**,
not on the demo, before phase 2 starts (production has the worker, the real
form link and his key). On D1 and D2, in his words: with customizable
sections, owners need to be able to say which sections are included in what
Claude contributes to the live map and which don't matter. On D6: owners turn
the switches on deliberately. On D12: custom sections take priority over the
pre-questionnaire. The owner also asked for a plain statement of what Prepare
already does, so nothing is built twice: §5.0. Build order: phase 1 (pin v3)
first, alone, with no schema change and no application code.

**Amended the same day, after §5.0 was read: the owner chooses the smaller
pre-questionnaire.** Accepted rewordings apply to **that session only**; there
are **no new-question proposals for now**. That replaces D10 and narrows D8
and D9, and it removes from this round: the `strategy_precall_proposal` table
(§2.2, and its `CREATE TABLE` in §2.3), the `precall_size` setting (§2.4), the
tray of §5.3 and guardrail 7 of §5.4, and matrix rows 10.3d–10.3f. What is
built instead is in §5.6. Where §5.1–§5.5 describe Claude proposing new
questions, they are the fuller version, kept for the record and **not built**.

**Phase 1 is done (2026-10-03):** `tests/test_strategy_v3_golden.py`, 43 golden
files for a v3 session as released. Phase 2 waits on D14.

It builds on
`docs/p3_strategy_templates_session_v3.md` (P3, released 2026-10-03 as
Release 4) and uses its words: *classic*, *v2* ("Operations — focused"), *v3*
(a template made in the builder), *part* (one of the eight sections a blank v3
template starts with).

What this round adds, in the owner's order:

1. **Custom sections.** The practice owner adds, removes, renames and reorders
   the sections of a template, not only the questions in them.
2. **AI for the map, chosen per section.** Which meaning is D1.
3. **An AI-drafted pre-questionnaire** for one prospect, from their website and
   whatever the practice already has.
4. **The items deferred from P3:** the pre-call form preview, starting from a
   copy, talk tracks, next-step sentences in the v3 covering note, and a v3
   PDF design.

---

## 0. Where P3 left things

| Fact | What it means here |
|---|---|
| A v3 section already has `kind`, `intro`, `show_in_pdf` and `deleted_at` columns (migration 0016). Only `kind` is used; `deleted_at` only for "What they value". | Custom sections, talk tracks and "prints on the PDF" need **no new column**. Two things do: the per-section AI switches, and the covering-note sentence (§2). |
| The eight parts keep the section codes the shared engine reads (`diagnostic`, `mirror`, `strategy_map` and so on). | A custom section gets a generated code (`custom_` plus eight hex characters), which no engine code looks for. It is rendered and answered like any section, and does nothing else unless the owner switches something on. |
| Claude's drafting input for a v3 session is built in one place (`v3.drafting_input`): pre-call answers, ratings, the mirror's questions, the diagnostic. Map rows, the mirror and the pros and cons all read that same input. | "Which sections Claude reads" is one switch per section, and it applies to all three drafts. |
| Prep (`prep.prepare`) makes one Claude call with web search: a summary, likely bottlenecks, a **rewording for each existing pre-call question**, and five extra live questions. A rewording is applied by copying it into the **template**. | Prospect-specific wording ends up in the template, where it changes every later session. §5 moves it to the session. |
| A session's questions can change only while it is a draft that has reached nobody (`reset_refusal`). An accepted diagnostic proposal joins the session's own snapshot under a new key. | The AI pre-questionnaire uses the same two mechanisms: a tray, and the session's own snapshot. |
| The v3 PDF prints on v2's two-page layout. A removed part is simply absent. | Custom sections have nowhere to print yet (§6). |
| v2 is pinned by golden files and the real-session fingerprints. **v3 is not pinned by anything.** | Phase 1 of this round pins v3 as released, before any new code (§8). |
| No v3 screen had been seen in a browser at release, and no real Claude call had been made on v3. | D14. |

---

## 1. Assumptions

1. **None of this reaches classic or v2.** Every change is taken only for a
   v3 template or a v3 session. The v2 goldens stay byte-identical, the
   real-session fingerprints stay identical, and no existing strategy test is
   edited.
2. **Existing v3 templates and v3 sessions keep working unchanged.** New
   columns are nullable or defaulted, and "not set" means "as P3 behaves
   today". A session already created reads its own frozen snapshot, which has
   none of the new keys, and so takes the P3 behavior.
3. **The blank eight-part template stays the starting point.** Custom
   sections are added to it; nothing changes what "New template" makes.
4. **One of each built-in part.** A template has at most one pre-call part,
   one ratings part, one diagnostic, one mirror, one map, one "What they
   value", one "Two paths" and one scope, because each has behavior of its
   own. Custom sections are the ones a template can have several of.
5. **The map cannot be removed.** It is what the PDF is about and what
   converts to goals. Every other part can be (D3).
6. **The part asked before the call stays first.** It is not on the call, so
   it has no place in the call's order.
7. **Only the practice owner changes a template's sections** (matrix 10.1a,
   unchanged). Associates and assistants read.
8. **Every AI output still lands as proposed.** The pre-questionnaire is a
   tray; nothing in it reaches the prospect until a person accepts it, and
   nothing is sent without the full message on screen.
9. **AI cost is the practice's.** Every call goes through the existing
   Claude service, writes an `ai_call` row with its cost, and counts against
   the practice's credits and budget. Nothing in this round runs on the
   worker.
10. **Money, private notes and the reaction to a path never reach Claude or
    the PDF through a custom section.** A custom section cannot hold a money
    item; those stay in Scope.
11. **Migrations are additive, with the SQL shown first**, and applied to the
    laptop only when the suite is green.
12. **American English** in every screen, email and PDF.

---

## 2. Data model changes

One migration, `strategy 0017`: three columns and one table. Everything else
in this round uses columns that already exist or the template's `settings`.

### 2.1 Columns

| Table | Column | Meaning |
|---|---|---|
| `strategy_section` | `feeds_map` boolean, **null** | Whether Claude reads this section's answers when it drafts (D1). Null means "the default for its kind" (§4), which is what P3 does today. |
| `strategy_section` | `ai_drafts` boolean, **null** | Whether Claude drafts in this part at all (D2). Null means yes. Only meaningful on the four parts that draft. |
| `strategy_question` | `cover_line` varchar(200), default `''` | A scope item's sentence for the covering note, with `{date}` in it (§7.4). |

### 2.2 The pre-questionnaire tray

`strategy_precall_proposal`: one row per pre-call question Claude drafts for
one session. Practice-scoped like every other table, and registered in the
isolation family.

| Column | Meaning |
|---|---|
| `session` | The session it was drafted for |
| `source` | `template` (one of the template's own questions, kept or reworded) or `new` (one Claude added for this prospect) |
| `template_key` | For `template`: the key of the question it stands for |
| `prompt`, `proposed_prompt` | The wording now, and the wording Claude drafted |
| `basis` | What it rests on, marked as prep marks it: "Their site says…", "From your notes…" |
| `state` | `proposed`, `accepted`, `discarded` |
| `position` | Order in the questionnaire |
| `question_key` | The key it has in the session's snapshot once accepted |
| `ai_call` | The call that drafted it |

### 2.3 Planned migration SQL

Expected output of `sqlmigrate strategy 0017`. The exact output is shown
before the migration is generated.

```sql
BEGIN;
ALTER TABLE "strategy_section" ADD COLUMN "feeds_map" boolean NULL;
ALTER TABLE "strategy_section" ADD COLUMN "ai_drafts" boolean NULL;
ALTER TABLE "strategy_question" ADD COLUMN "cover_line" varchar(200) DEFAULT '' NOT NULL;

CREATE TABLE "strategy_precall_proposal" (
  "id" uuid NOT NULL PRIMARY KEY,
  "created_at" timestamp with time zone NOT NULL,
  "updated_at" timestamp with time zone NOT NULL,
  "source" varchar(10) NOT NULL,
  "template_key" varchar(80) DEFAULT '' NOT NULL,
  "prompt" text NOT NULL,
  "proposed_prompt" text DEFAULT '' NOT NULL,
  "basis" text DEFAULT '' NOT NULL,
  "state" varchar(10) NOT NULL,
  "position" smallint NOT NULL CHECK ("position" >= 0),
  "question_key" varchar(80) DEFAULT '' NOT NULL,
  "ai_call_id" uuid NULL REFERENCES "ai_call" ("id") DEFERRABLE INITIALLY DEFERRED,
  "session_id" uuid NOT NULL REFERENCES "strategy_session" ("id") DEFERRABLE INITIALLY DEFERRED,
  "tenant_id" uuid NOT NULL REFERENCES "tenant" ("id") DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX ON "strategy_precall_proposal" ("state");
CREATE INDEX ON "strategy_precall_proposal" ("ai_call_id");
CREATE INDEX ON "strategy_precall_proposal" ("session_id");
CREATE INDEX ON "strategy_precall_proposal" ("tenant_id");
CREATE INDEX ON "strategy_precall_proposal" ("tenant_id", "session_id", "state");
COMMIT;
```

Nothing is dropped, rewritten or backfilled. No existing row of any template,
section, question or session changes. If D2 is "no", the `ai_drafts` column is
left out.

### 2.4 Settings and the snapshot

New keys in a v3 template's `settings` (no schema change; validated on save;
a template without them reads the default):

| Key | Meaning | Default |
|---|---|---|
| `precall_size` | How many pre-call questions Claude aims for when it drafts a questionnaire | the number the template has, or 12 if it has none |
| `pdf_layout` | `two_page` (today's) or `flowing` (§6) | `two_page` |

A new v3 snapshot carries each section's `feeds_map`, `ai_drafts` and
`intro`, and each question's `cover_line`. **A snapshot taken before this
round has none of them and is read as P3 reads it today.**

---

## 3. Custom sections

### 3.1 What the owner can do

| Action | Rule |
|---|---|
| **Add a section** | A custom section, anywhere among the parts asked on the call. It gets a title, a time budget and, optionally, a talk track. Up to 8 custom sections in a template (D5). |
| **Rename** | Any section. (P3 already allows this.) |
| **Reorder** | Any section asked on the call, by moving it up or down. The part before the call stays first. |
| **Remove** | Any section except the map. A removed built-in part can be put back, with its questions as they were. A removed custom section can be put back from a "Removed sections" list. Nothing is deleted, so no question key is ever reused. |

### 3.2 What a custom section holds

Each question in a custom section takes one of three kinds of answer, chosen
per question (D4):

- a **written answer**;
- **said / cause / tried**, as a diagnostic question does;
- **agreed, with a note**, as a scope item does.

Up to 12 questions in a section. A question can be marked must-ask. A custom
section cannot hold a rated item, a value, a path or a money item: those
belong to the parts that know what to do with them.

### 3.3 What a custom section does, and does not do

By default a custom section is **captured and nothing else**: its answers are
saved with the session, shown in the live view, visible to an assistant like
sections 1–8, and that is all. Two switches, each off until the owner turns it
on:

- **Claude reads this section when drafting** (§4).
- **Print this section on the document** (§6).

It is never part of the pre-call form, the diagnostic tray, the ratings chart
or the next-steps list.

### 3.4 Removing a built-in part

A session started from a template without a part runs without it:

| Removed | What the session does |
|---|---|
| Before the call | No form and no questions email. The diagnostic uses its fixed questions; "Propose" has nothing to read and says so. |
| Ratings | No ratings, no summary card, no chart on the PDF, no "Propose from the ratings". |
| Diagnostic | No tray and no proposals. Map rows are drafted on the button, from whatever sections feed it. |
| Mirror | No mirror in the live view or on the PDF. |
| What they value | As P3 today. |
| Two paths | No paths, no pros and cons, no decision block on the PDF or in the covering note. |
| Scope | No next steps, and no money items. |
| The map | Cannot be removed. |

**Ready to run** changes to match: a template needs a name and the map. If it
has a ratings part, that part needs at least two rated items, each with a
label; if it has "Two paths", that part has exactly two. A template made
before this round has all eight parts and is judged exactly as it is today.

### 3.5 What feeds what

```
answers in a section ──(only if "Claude reads this section")──▶ Claude's drafting input
Claude's drafting input ──▶ proposed map rows, the proposed mirror, proposed pros and cons
a person accepts ──▶ the map, the mirror, the pros and cons
accepted map rows ──(conversion)──▶ goals and projects
```

- **The map:** a custom section reaches the map only through Claude's
  drafting input, and only when its switch is on. It never adds a row itself.
- **Conversion to goals:** unchanged. Only accepted map rows convert. An
  answer in a custom section never becomes a goal, a project or a task.
- **The PDF:** §6.

---

## 4. AI for the map, chosen per section

The owner's words were "what sections they want to be AI driven for the live
session map". Two readings, and they are different features:

| | (a) What Claude reads | (b) What Claude drafts |
|---|---|---|
| The switch | Per section: "Claude reads this section when drafting" | Per drafting part: "Claude drafts here" |
| Applies to | Every section, custom ones included | The four parts that draft: diagnostic (proposed questions), mirror (the draft), map (proposed rows), two paths (pros and cons) |
| Off means | Its answers are left out of the input for rows, the mirror and the pros and cons | No Draft button and no automatic draft in that part; the practice writes it by hand |
| Cost effect | Smaller or larger prompts | Fewer calls |

**Recommendation (D1): (a) is what "AI driven for the map" most plainly asks
for, and it is the one custom sections need**: a section the practice adds
has to be able to feed the map or it is only a notepad. I would build (b) as
well (D2), because it is one more switch on four cards and some practices will
want a part with no AI in it.

**Defaults for (a)**, which are exactly what P3 does today:

| Section | Claude reads it |
|---|---|
| Before the call, Ratings, Mirror questions, Diagnostic | Yes |
| What they value, Two paths | No for map rows and the mirror. The pros-and-cons draft keeps reading them, as today, because they are what that draft is about. |
| Scope | **Never.** Not switchable: it holds the money. |
| A custom section | No, until the owner switches it on |

**What never changes, whatever the switches say:** a private note, a money
item, and anything from another session or another practice stay out of every
prompt. Claude is told only what the session holds. Every draft lands as
proposed.

---

## 5. The AI-drafted pre-questionnaire

### 5.0 What Prepare already does, and what this round adds

**Today, in production, for every session (classic, v2 and v3):** you give
Prepare the prospect's website and paste in any correspondence or notes. One
Claude call, with web search, comes back with:

1. A two-to-three-sentence summary of the company.
2. Three to five likely bottlenecks for a business of that shape.
3. **A rewording of each of the template's own pre-call questions, one for
   one, in the prospect's vocabulary.** "Operations — focused" has twelve
   pre-call questions (seven Snapshot, five ratings), which is why Prepare
   shows about a dozen. A rating stays a rating.
4. Five extra questions to ask on the call, which you can pin. These are
   never sent to the prospect.

You tick the rewordings you want, edit them, and apply them. Applying copies
them into the **template editor**, unsaved; you save the template, go back,
and reset the draft session to pick them up.

**So the pre-questionnaire is largely built.** Reading the site and the
correspondence, wording the questions for this prospect, and reviewing and
editing before anything is sent all exist. What does **not** exist:

| Gap today | What part two adds |
|---|---|
| Prepare only rewords the questions the template already has. It never writes a new pre-call question, and a template with no pre-call questions gets none. | Claude may also propose **new** pre-call questions for this prospect, up to the template's number (D10). |
| An applied rewording changes the **template**, so wording written for one prospect is what every later prospect is asked, until someone changes it back. | Accepted wording goes into **that session only** (D8). The template is untouched. |
| Applying is a round trip: session, template editor, Save, back, reset. | Accept in place, then **Use this questionnaire**. |
| The form cannot be seen before it is sent. | **Preview the form** (§7.1). |

**This is smaller than "a new AI feature".** It is the same Prepare run and
the same call, with one more thing asked of Claude (new questions), a
different place for the accepted wording to go (the session), and a tray in
place of the tick-list. If new questions are not wanted, and one-for-one
rewording is enough, the addition shrinks to "apply to this session only":
no new table, and phase 4 is about half the size. That choice is the owner's;
the spec below describes the fuller version he approved in D8–D10.

Nothing here changes Prepare on a classic or v2 session.

### 5.1 What it is

For one session, before anything has gone to the prospect: Claude reads the
prospect's website and whatever the practice gives it (pasted emails, call
notes), and drafts **the pre-call questions for this prospect**. The owner
reviews each one and edits it. Only what is accepted is asked.

### 5.2 How it relates to the prep panel

It **is** the prep panel, for a v3 session. Prep already takes the website
and the notes, reads the site once, and writes the brief. Today it then
suggests a rewording for each of the template's pre-call questions. In a v3
session that step becomes the questionnaire:

| | Prep today | Prep in a v3 session after this round |
|---|---|---|
| Brief (summary, likely bottlenecks) | Yes | Unchanged |
| Five extra questions for the call, to pin | Yes | Unchanged |
| The pre-call questions | A suggested rewording of each template question | **A drafted questionnaire**: each template question kept or reworded in the prospect's words, plus new questions for this prospect, up to `precall_size` |
| Where an accepted wording goes | Copied into the **template**, then the session reloaded | **Into this session only** (D8). The template is not touched. |
| Calls | One, with web search | One, with web search (D9) |

"Copy into the builder" stays, as the way to keep a wording for every later
session. Prep on a classic or v2 session is unchanged, prompt and all.

### 5.3 The tray

On the session's "Prepare for this session" card, after Prepare:

- The proposed questionnaire, in order. Each question shows what it rests on
  ("Their site says…", "From your notes…") and whether it is one of the
  template's own or new for this prospect.
- Per question: **Accept**, edit then accept, **Discard**. "Accept all" for
  the whole list. The owner can add a question by hand and reorder.
- **Use this questionnaire** replaces the session's pre-call questions with
  the accepted ones, in the session's own snapshot. Until then the session
  asks the template's questions.
- **Preview the form** shows the prospect's form exactly as it will open
  (§7.1), before "Send the form link" or "Email the questions", which work as
  they do today with the full message on screen.

### 5.4 Guardrails, each with a test

1. **Proposed, never asked.** Nothing joins the session until a person
   accepts it and presses "Use this questionnaire".
2. **Draft sessions only.** Once the form or the questions have gone out, or
   the prospect has answered anything, the questionnaire is fixed (the
   existing `reset_refusal` rule). The tray then says so.
3. **Questions, not claims.** Claude is told to ask, and to assert nothing
   about the prospect that is not in the material. A proposed question that
   states a figure, a name or a cause as fact is the owner's to catch, and
   the basis line is there so it can be checked.
4. **Shape.** Every question is a written-answer question. No ratings (those
   are on the call), no money, at most 20, no merge field that does not exist.
5. **Nothing private reaches the prospect.** The brief, the notes and the
   basis lines stay with the practice. Only the accepted wording is on the
   form and in the email.
6. **Not on the worker.** It runs only when a person presses Prepare, so it
   is never an unattended call.
7. **A template question is never dropped silently.** If Claude leaves one
   out, it shows in the tray as "not included, because…" for the owner to
   put back.

### 5.5 What the pasted material is

The website and the notes go to Claude under the practice's own Anthropic
key, as prep's do today. Nothing new leaves the practice. The notes may hold
other people's emails; the screen already says what is sent and to whom, and
that sentence stays.

---

### 5.6 What is built: the smaller version (owner, 2026-10-03)

Prepare is unchanged: one call, the same brief, the same one-for-one
rewordings of the template's own pre-call questions, the same five extra
questions for the call. One thing changes, for a v3 session only:

- Beside the ticked rewordings, **"Use for this session"** writes the accepted
  wording into **this session's own questions**. The template is not touched,
  and no reset is needed.
- It is offered only while the session is a draft that has reached nobody
  (the existing `reset_refusal` rule). After that the questions are fixed and
  the button says why.
- A rewording still cannot change a question's shape, or use a merge field
  that does not exist.
- "Copy into the builder" stays, for wording the practice wants to keep for
  every later session.
- **Preview the form** (§7.1) stays in this phase.

**Schema:** nothing. The accepted wording lives in the session's snapshot and
the suggestions stay where they are, on the prep row. Migration 0017 is then
the three columns of §2.1 only.

**Tests:** the template is byte-for-byte unchanged by "Use for this session";
another session from the same template still asks the template's wording;
refused once the form or the questions have gone out, or the prospect has
answered; an assistant cannot do it (403); another practice cannot reach it
(404); nothing from the prep brief reaches the form or the email; classic and
v2 prep unchanged (v2 goldens).

## 6. The PDF

### 6.1 What prints

| Content | Prints |
|---|---|
| The eight parts | As today, each only if the template has it |
| A custom section with "Print this section on the document" on | Its title, then each question with its answer. Only written answers and agreed-with-a-note items. |
| A custom section with the switch off (the default) | Nothing |
| A said / cause / tried answer in a custom section | **Never**, as the diagnostic's answers never print: the document is what to do, not the interview |
| A private note beside any answer | Only with its existing flag, as today |
| Money | Only from Scope, only with the investment flag, as today |
| A talk track | Never |

### 6.2 A v3 design

Today's layout is v2's: two fixed pages. With custom sections a session can
have more to print than two pages hold. Two layouts, chosen per template
(`pdf_layout`, D7):

- **Two pages** (the default, today's layout). Printing custom sections are
  refused in the builder past what fits, by a simple count: at most two
  printing sections of up to four questions.
- **Flowing.** Page one is the header, the ratings and the mirror side by
  side, and the map. From page two the rest follows in the template's own
  order: paths, values, each printing custom section, next steps. It runs to
  as many pages as it needs, with a block never split across pages. The
  practice's own section titles are the headings.

Both layouts drop a part the template does not have and close the gap (no
ratings: the mirror takes the full width).

---

## 7. The items deferred from P3

### 7.1 Preview of the pre-call form

In the builder's "Before the call" card, and on a session before sending:
**Preview the form** opens the real form component, read-only, with the
practice's brand and sample or actual merge values. It makes no token and
sends nothing. No schema change.

### 7.2 Start from a copy

The "New template" card gains **Start from**: *The eight blank parts* (the
default), or a copy of any of the practice's templates.

- **A copy of a v3 template** is what Duplicate already does.
- **A copy of a classic or v2 template** is a new v3 template made from it:
  its pre-call questions become "Before the call", its ratings become rated
  items taken on the call (each labeled with its component), its destination
  or "What you need" questions become the mirror's, its diagnostic fixed
  questions, values, paths and scope carry over. The source is not touched.
  Only a practice that has a classic or v2 template can do this, which today
  is Executives Now alone.

No schema change.

### 7.3 Talk tracks

Each section's `intro` (the column exists) becomes editable in the builder:
a few lines the person running the call reads or keeps in mind. In the live
view it shows at the top of the section, to staff. It is never on the form,
in an email or on the PDF, and never sent to Claude.

### 7.4 Next-step sentences in the v3 covering note

v2's covering note writes "We agreed to speak again on Tuesday" from three
fixed scope items. In v3 each scope item can carry its own sentence
(`cover_line`), written by the practice with `{date}` where the date goes:
"You will have my proposal by {date}." It is used only when the item was
agreed and its note reads as a date or a day, the same rule v2 uses. The
whole note is still on screen, and editable, before it is sent.

---

## 8. Screens

| Screen | What changes |
|---|---|
| **Builder** | "Add a section" between the live parts; up, down and Remove on every section but the map and the pre-call part's position; "Removed sections" with Put back; per section: talk track, "Claude reads this section when drafting", "Print this section on the document"; on the four drafting parts: "Claude drafts here"; per custom question: its kind of answer; per scope item: the covering-note sentence; "Preview the form"; document layout (two pages or flowing); "Start from" on New template. |
| **Live view (v3)** | Sections in the template's order; custom sections as question lists; the talk track at the top of a section; no Draft controls in a part where drafting is off. |
| **Session, before the call (v3)** | The questionnaire tray on the Prepare card; "Use this questionnaire"; "Preview the form". |
| **Classic and v2 screens** | Nothing. |

**Access matrix additions (§10 of `03_access_matrix.md`):**

| # | Capability | Practice owner | Associate | Assistant | Clients |
|---|---|---|---|---|---|
| 10.1a | Add, remove, rename, reorder a template's sections; set its AI and print switches *(extends the existing row)* | ✅ | ❌ | ❌ | — |
| 10.3d | **Draft a pre-questionnaire** (Claude, with web search) | ✅ | 🔸 own prospects | ❌ | — |
| 10.3e | **Accept, edit or discard a proposed pre-call question; use the questionnaire** | ✅ | 🔸 own prospects | ❌ | — |
| 10.3f | Read the questionnaire tray | ✅ | 🔸 | ❌ (absent from the payload, as prep is) | — |

The platform owner sees none of it: no practice is bound in the Practices area.

---

## 9. Build phases

Proposed order (D12). Custom sections come first because the AI switches and
the PDF both depend on them. The pre-questionnaire is independent and could
move earlier if it matters more.

| Phase | What | Tests | Not verifiable without a browser |
|---|---|---|---|
| **1. Pin v3** | Golden files for one v3 session run end to end as released (snapshot, form, payloads, every prompt, PDF, conversion), beside the v2 goldens. No product code. | The goldens themselves, green on today's `dev` | — |
| **2. Custom sections and talk tracks** | Migration 0017 (SQL shown first). Add, remove, rename, reorder; the three answer kinds; removing built-in parts and the new ready-to-run rule; talk tracks; the live view in template order. | Isolation and role tests on every new verb. A template without each part starts and runs. A custom section's answers reach no prompt and no PDF by default. Key never reused after remove and put back. **v2 goldens identical; v3 goldens identical for a template that uses none of it.** | The builder's reordering; the live view with custom sections |
| **3. AI per section** | `feeds_map` and, if D2, `ai_drafts`: the switches, the drafting input, the controls hidden where drafting is off. | A switched-on custom section reaches the rows, mirror and pros-and-cons input, and a switched-off one does not. Scope never does. Money and private notes never do. Drafting off: no button, no automatic call, no `ai_call`. Defaults reproduce the v3 goldens exactly. | — |
| **4. Per-session rewordings and form preview** *(the smaller version, §5.6; no tray, no new questions, no new table)* | "Use for this session" on prep's rewordings, the form preview in the builder and on the session. | Proposed, never asked. Draft sessions only. Shape rules (written answers, 20 at most, known merge fields). Nothing private on the form or in the email. One `ai_call`, attended, against the right practice. Assistant: 403 and absent from the payload. Another practice: 404. The template is unchanged by anything a session accepts. Classic and v2 prep prompt unchanged (v2 goldens). | The tray; the preview |
| **5. PDF and covering note** | Printing custom sections; the flowing layout; parts that are absent; `cover_line`. | AC-4.9 on custom sections (no private note, no said/cause/tried, no money). Two-page layout still two pages. Flowing layout: every printing section present, in order. Cover sentence only when agreed and dated. v2 PDF golden identical. | **How both layouts look**, especially page breaks |
| **6. Start from a copy** | "Start from" on New template; the classic and v2 mapping. | The copy is v3 and ready or says what is missing; the source is byte-for-byte unchanged; each mapped part holds what the table in §7.2 says. | — |

**Every phase ends with:** both suites green, v2 goldens byte-identical,
real-session fingerprints identical, no existing strategy test edited, and
from phase 2 on, the v3 goldens identical for a template that uses no new
feature.

---

## 10. Decisions for the owner

| # | Question | Recommendation | Owner, 2026-10-03 |
|---|---|---|---|
| **D1** | **What "AI driven for the live session map" means.** (a) Which sections' answers Claude reads when it drafts map rows (and the mirror and pros and cons, which share that input); or (b) which parts Claude drafts in at all. | **(a).** It is the plain reading, and it is what makes a custom section able to feed the map. | **Yes.** |
| D2 | Also build (b): a "Claude drafts here" switch on the diagnostic, the mirror, the map and the two paths | Yes. It is small, and it lets a practice run a part with no AI. | **Yes.** Owners say which sections are included in what Claude contributes to the live map and which don't matter. |
| D3 | Every part can be removed except the map; the part before the call stays first; one of each built-in part | Yes | **Yes.** |
| D4 | A custom section's questions take a written answer, said / cause / tried, or agreed with a note, chosen per question. No ratings, values, paths or money in a custom section. | Yes | **Yes.** |
| D5 | Limits: 8 custom sections in a template, 12 questions in each | Yes; both are easy to raise | **Yes.** |
| D6 | A new custom section starts with both switches off: Claude does not read it and it does not print, until the owner turns each on | Yes: nothing a practice adds reaches Claude or a prospect by accident | **Yes.** Owners turn the switches on deliberately. |
| D7 | PDF: keep two pages as the default and add a "flowing" layout per template that follows the template's order and runs as long as it needs | Yes, both. A hard two-page limit and custom sections cannot both hold. | **Yes.** |
| **D8** | **A pre-questionnaire accepted for a prospect changes that session only, never the template.** "Copy into the builder" stays for wording you want to keep. | **Yes** | **Yes.** |
| D9 | One Prepare run drafts the brief and the questionnaire together (one call, one read of the site), rather than a second button and a second call | Yes | **Yes.** |
| D10 | Questionnaire size: Claude aims for the template's own number of pre-call questions (12 if it has none), 20 at most, and never drops a template question without showing it as "not included" | Yes | **Yes**, then **withdrawn the same day:** no new-question proposals for now; rewordings apply to that session only (§5.6). |
| D11 | Next-step sentences: the practice writes one per scope item, with `{date}`; none are written for it | Yes | **Yes.** |
| D12 | Phase order: pin v3, custom sections and talk tracks, AI per section, pre-questionnaire and form preview, PDF and covering note, start from a copy | Yes. Say if the pre-questionnaire should come before custom sections. | **Yes, as proposed.** Custom sections take priority over the pre-questionnaire. |
| D13 | "Start from a copy" of a classic or v2 template is offered only to a practice that has one (Executives Now) | Yes | **Yes.** |
| **D14** | **Before this round's release: one v3 and one v2 session run on the demo, and at least one real Claude draft looked at on v3.** P3 went out with neither. | **Yes.** I recommend the two demo sessions happen before phase 2 starts, so anything P3 got wrong is fixed before more is built on it. | **Yes, changed:** the owner runs one v3 and one v2 session **in production with a test contact**, not on the demo, before phase 2 starts. |
| D15 | Release in two parts (after phase 3, and at the end) or once | Two. Custom sections with their AI switches are useful by themselves, and smaller releases are easier to check. | **Yes, two releases.** |
