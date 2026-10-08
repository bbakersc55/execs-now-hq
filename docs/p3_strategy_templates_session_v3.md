# P3 — Strategy template builder and session v3

**Practices beta program, phase 3 of 4 · spec for owner review · 2026-10-03**

**Approved 2026-10-03.** D1–D13 as recommended, with two amendments from the
owner: D4 (a practice sets its own diagnostic size, and a question can be added
during a session; §2.3, §3c, §4.2) and D13 (AI in the session is required; §3e
and §3g now say exactly what Claude proposes and how duplicates are kept out).
D12 adds the owner's own judgment after the dry run. The decisions are recorded
in §8. Build order: phase 1 (pin v2) first, alone, with no schema change and no
P3 code.

**Released 2026-10-03 without the demo dry run.** The owner waived that part
of D12 (one v3 and one v2 session completed on the demo before go/no-go) and
said "release" the same day phase 5 was finished. The other four conditions
held at the released commit: v2 goldens byte-identical, real-session
fingerprints identical, existing strategy tests unedited and green, both
suites green. **No v3 or v2 screen had been seen in a browser at release.**

Written from `docs/handoff.md`, `04_build_plan.md` (Phase 4 and "Strategy
session v2"), `01_prd.md` (FR-4.x, AC-4.x), `02_data_model.md` §6,
`03_access_matrix.md` §10, and the code under `apps/strategy/`,
`templates/strategy/` and `frontend/src/screens/Session*.tsx`.

**Added 2026-10-08, for owner review, not built: §9, a practice with no
template and "Start from the Operations example".** It reverses D3 and part
two's D13 in one narrow way, and says exactly how narrow (§9.2, E1).

**Words used here.** *Classic* is the original nine-section format. *v2* is
"Operations — focused" (`format = focused`). *v3* is the new format this spec
adds. *Builder* is the new screen where a practice owner makes a v3 template.

---

## 0. What the code does today, and what v3 runs into

| Finding | Consequence |
|---|---|
| **A session renders from its own frozen snapshot** (`template_snapshot`, taken when the session is created). Nothing in a session points at a live template row. | v3 can be added without touching any session that exists. This is the base of §6. |
| **Behavior is keyed on section codes written into the code**: `snapshot`, `six_key_components`, `what_you_need`, `where_they_want_to_go`, `diagnostic`, `mirror`, `strategy_map`, `what_they_value`, `two_paths`, `scope_agreement` (`ai.py`, `pdf.py`, `services.py`, `SessionDetail.tsx`). | A practice cannot add, remove or rename a section's role today. v3 gives each section a **kind** (§2). |
| **Today's editor edits questions only**: add, remove (archive), reorder within a section, reword, time budgets, rename, duplicate, set default, archive. It cannot add or remove a section. | The builder is a new screen (§4). Today's editor stays for classic and v2 templates. |
| **The only way to get a first template is "Restore from seed"**, which creates the owner's Operations template. Provisioning gives a new practice no template (P2 §3). | A new practice can only start from Executives Now's questions. See D3. |
| **Operations wording is in the code**: the three PDF header chips are tied to `s1_revenue`, `s1_team`, `s1_sites`; the rating names are tied to `s2_*` keys; the PDF's Path A/B copy says "Improve operations incrementally"; every Claude prompt says "fractional operations executive"; the cover email's next-step sentences are tied to `s9_*` keys. | These are the "custom templated portions" (§2.3). In v3 they come from the template. In classic and v2 they stay exactly as they are. |
| **v2's diagnostic rests on pre-call ratings** (two lowest, then third lowest), a growth mention, and Snapshot gaps. | In v3 the ratings are taken on the call, so they do not exist when the diagnostic is first proposed. §3c. |
| **The proposal after the pre-call form runs on the worker**; a button re-proposes. | The demo has no worker (§7, D10). |
| **Conversion to goals, Consolidate, pros and cons, prep, and "learn from my edits" do not depend on the question set.** They read map rows, path notes and pre-call questions. | v3 reuses them as they are. |
| **On the laptop's copy of production**, "Operations — focused" is the Executives Now default and **no session has been started from it yet**. The four sessions there are all classic. | v2 has not been run on a real session. Its proof (§6) has to rest on fixtures plus the real classic sessions. |

---

## 1. Assumptions

1. **v3 is a third format, beside classic and focused.** A template's format is
   fixed when it is created and frozen into each session's snapshot. Nothing
   converts a template or a session from one format to another.
2. **Only the practice owner builds templates** (matrix 10.1, unchanged).
   Associates and assistants can read them, as today.
3. **Templates never cross practices.** There is no shared library, no copy
   from another practice, and nothing for the platform owner to see.
4. **The builder makes v3 templates only.** Classic and v2 templates keep
   today's editor and today's rules. The builder's verbs refuse them.
5. **The eight parts have fixed behavior and a fixed order in the first cut**
   (a–h below). What a practice controls: every question, every title, the
   rated items, the templated text, and whether "What they value" is there.
   Adding, removing and reordering sections comes after Tuesday (§7, D1).
6. **Ratings are 1–10 and on the call in v3.** v3 does not offer ratings on
   the pre-call form. The 9/22 rule still holds: a rating's wording is a
   statement of a line, not an open question.
7. **v3 uses the v2 map**: cards with a header and a focus statement, at most
   five accepted rows, Consolidate aiming for three to five. And the v2 PDF
   layout (two pages).
8. **Every AI output still lands as proposed** and reaches the session, the
   PDF or an email only when a person accepts it. The builder itself makes no
   AI calls.
9. **AI calls keep their existing purposes** (`strategy_diagnostic_questions`,
   `strategy_rows`, `strategy_rows_consolidate`, `strategy_mirror`,
   `strategy_path_notes`, `session_prep`), so each writes an `ai_call` row
   with its cost, counts against the practice's credits and monthly budget, and
   the worker's one call counts against the daily unattended cap.
10. **Discipline stays out of sight.** Builder templates carry the existing
    `discipline` value, and "Set default" clears every other default in the
    practice, so "the default" means one template.
11. **A blank v3 template is not blank inside the fixed-shape parts.** Two
    paths starts with two neutral path items, and Scope with three neutral
    items, because the session and the PDF need them. Everything else starts
    empty (D2).
12. **Migrations are additive, with database defaults on every new column**,
    because the old web keeps serving for about two minutes against the new
    schema during a release.

---

## 2. Data model changes

No new table. Seven columns on three tables, one migration
(`strategy 0016`), plus two choice lists that change no SQL.

### 2.1 Columns

| Table | Column | Meaning |
|---|---|---|
| `strategy_template` | `settings` jsonb, default `{}` | The template's own text and limits (§2.3). Empty on every classic and v2 template, and never read for them. |
| `strategy_section` | `kind` varchar(16), default `''` | What the section does in v3: `precall`, `ratings`, `diagnostic`, `mirror`, `map`, `values`, `paths`, `scope`, `custom`. Empty on classic and v2. |
| `strategy_section` | `intro` text, default `''` | The practice's own talk track for the section, shown to staff in the live view. Never on the pre-call form, the email or the PDF. |
| `strategy_section` | `show_in_pdf` boolean, default false | A custom section's answers print on page two. Fixed-kind sections ignore it. |
| `strategy_section` | `deleted_at` timestamptz, null | A removed section. Kept so its code and its questions' keys stay spent. |
| `strategy_question` | `label` varchar(60), default `''` | A short name: the bar label for a rated item, the chip label for a pre-call question. |
| `strategy_question` | `pdf_chip` boolean, default false | Pre-call questions only: show the answer in the PDF header (three at most). |

Choice lists (Django records them; PostgreSQL does nothing):
`StrategyTemplate.format` gains `v3`; `StrategyDiagnosticProposal.rule` gains
`precall_gap` and `manual`.

**A v3 built-in section keeps the code the engine already knows**
(`snapshot`, `six_key_components`, `diagnostic`, `mirror`, `strategy_map`,
`what_they_value`, `two_paths`, `scope_agreement`), with its `kind` beside
it. That is deliberate: the shared code (scores, the tray, the PDF context,
pros and cons) keeps reading by code and is not rewritten. A custom section
gets a generated code (`custom_` plus eight hex characters).

### 2.2 Planned migration SQL

Expected output of `sqlmigrate strategy 0016`. The exact output is shown before
the migration is generated, as the rule requires.

```sql
BEGIN;
ALTER TABLE "strategy_template" ADD COLUMN "settings" jsonb DEFAULT '{}'::jsonb NOT NULL;

ALTER TABLE "strategy_section" ADD COLUMN "kind" varchar(16) DEFAULT '' NOT NULL;
ALTER TABLE "strategy_section" ADD COLUMN "intro" text DEFAULT '' NOT NULL;
ALTER TABLE "strategy_section" ADD COLUMN "show_in_pdf" boolean DEFAULT false NOT NULL;
ALTER TABLE "strategy_section" ADD COLUMN "deleted_at" timestamp with time zone NULL;

ALTER TABLE "strategy_question" ADD COLUMN "label" varchar(60) DEFAULT '' NOT NULL;
ALTER TABLE "strategy_question" ADD COLUMN "pdf_chip" boolean DEFAULT false NOT NULL;

-- AlterField strategy_template.format (choices): no SQL
-- AlterField strategy_diagnostic_proposal.rule (choices): no SQL
COMMIT;
```

Nothing is dropped, rewritten or backfilled. No row of any existing template,
question or session changes. `strategy_session`, `strategy_answer`,
`strategy_map_row` and `strategy_path_note` are not touched.

**Where it gets applied.** Laptop: by me, on `execsnowhq_local`, once the full
suite is green with the migration present. Demo: by itself at start, on the
push to `dev`. Production: only on your "release", by the runbook's
"Releasing a migration".

### 2.3 `settings`: the templated portions

Read only for v3, validated against this list on save, frozen into the
snapshot. Every text takes the existing merge fields plus `{Practice}`. A
merge field that does not exist is refused at save.

| Key | Used in | Default for a new template |
|---|---|---|
| `advisor_role` | Every Claude prompt for the session, where v2 says "fractional operations executive" | "advisor" |
| `rating_scale` | Above the rated items in the live view and under the PDF chart | "1 means not true today, 10 means completely true" |
| `path_a_title`, `path_a_points` (two lines) | PDF decision page | "Continue to run it yourself"; two neutral lines |
| `path_b_title`, `path_b_points` (two lines) | PDF decision page | "Work with {Practice}"; two neutral lines |
| `diagnostic_size` | How many diagnostic questions Claude proposes for and a session starts with. Set by the practice owner per template, **1 to 8** | 3 (D4) |
| `precall_intro` *(after Tuesday)* | The pre-call form and the questions email | today's wording |

### 2.4 The v3 snapshot

`snapshot_version` 2, same shape as today plus: `template.format = "v3"`,
`template.settings`, each section's `kind`, `intro`, `show_in_pdf`, and each
question's `label`, `pdf_chip`. **A classic or v2 snapshot is written exactly
as it is today, with no new key** (§6).

---

## 3. Session v3: the flow

| | Part | Section kind (code) | Where | What is new against v2 |
|---|---|---|---|---|
| a | Pre-call | `precall` (`snapshot`) | Form link, or questions by email, as today | About a dozen free-text questions, all the practice's own. No ratings on the form. |
| b | Ratings | `ratings` (`six_key_components`) | Live | Taken on the call. Two to eight rated items, each the practice's own statement with a short label. No Traction, because there is no built-in list at all. |
| c | Diagnostic | `diagnostic` | Live | Proposed from the pre-call answers. Holds three by default. |
| d | Mirror and where they want to go | `mirror` | Live | One section: the destination questions, then the mirror. |
| e | The map | `map` (`strategy_map`) | Live | As v2. |
| f | What they value | `values` (`what_they_value`) | Live | Optional per template. |
| g | Two paths | `paths` (`two_paths`) | Live | As v2, with the PDF copy from the template. |
| h | Scope | `scope` (`scope_agreement`) | Live | As v2. Money items keep `is_financial`. |

**a. Pre-call.** Same form, same token, same two ways to send, same
"nothing sends without the full body on screen". A template with no pre-call
questions sends no form, and the diagnostic uses its fixed questions.

**b. Ratings.** The live view shows the scale line once, then each item with
a 1–10 input and a comment. The average and "where to look first" work as
today. The PDF chart uses each item's `label`.

**c. Diagnostic.** What each proposed question is for is still decided in
code, and Claude only words it:

- one for a mention of growth or expansion in the pre-call answers (v2's rule);
- up to two for an evident gap in the pre-call answers (`precall_gap`), which
  is the one judgment Claude makes, and it may find none;
- once ratings are in, **"Propose from the ratings"** adds one each for the
  two lowest (v2's rule, moved to a button on the call).

The tray, accept, edit, discard and "take it back out" work as in v2.
Nothing is asked until a person accepts it. If nothing is accepted, the
template's fixed diagnostic questions are asked. The first proposal is queued
when the prospect completes the form (worker, daily cap); the button does the
same on demand.

**How many (D4, amended).** The number belongs to the practice, per template:
**"Diagnostic questions per session"** on the builder's Diagnostic card,
default 3, from 1 to 8. It is how many Claude proposes for and how many the
session starts with. The template's fixed fallback questions follow the same
range. I raised the top from 5 to 8: v2 holds five, and a practice that runs a
longer call should not hit Executives Now's number. Above eight the section
stops being the "much shorter diagnostic" v3 is for, and a practice that wants
that many can put them in a custom section once those exist (phase 6).

**Adding a question during a session (D4, amended).** The template's number
is where a session starts, not a wall. In the live view's diagnostic section:

- **"Add a question"**: the person on the call types one. It goes straight into
  the session, because a person wrote it (`rule = manual`), under a new key in
  the session's own snapshot, exactly as an accepted proposal does.
- **"Propose more"** and **"Propose from the ratings"**: Claude's, into the
  tray, accepted one at a time.

Either way a session holds at most **8** diagnostic questions; a ninth is
refused with a sentence saying to take one out first. An unanswered question
can be taken back out; an answered one stays (v2's rule). Nothing can be added
once the session is complete. Adding to a session never changes the template.

**d. Mirror.** The section asks its own questions first (for example a
three-year picture and what should be different in 90 days). "Draft the
mirror" then reads those answers and the diagnostic and proposes the goal in
their words and what unlocks it. Proposed, then accepted, as today
(`proposed_mirror_*`, `mirror_*`). On the PDF the mirror prints where it does
in v2.

**e. Map (D13a).** Claude proposes the map rows; each lands in the tray as
proposed, and the person accepts, edits or discards each one. Only an accepted
row is on the map, the PDF or a goal. Draft rows (button, and once when the
diagnostic is fully answered), Consolidate, cards, cap of five and learn from
my edits are v2's code. The drafting input for v3 also carries the pre-call
answers and the ratings with their comments, labeled as what they wrote before
the call. Private notes, Scope and money stay out, as today.

*Keeping duplicates out.* Today's code already does three things, and v3
keeps them: Claude is shown every row on the map and in the tray and told not
to repeat a theme; a proposal whose bottleneck matches an existing row word
for word is dropped; a run proposes five at most. **v3 adds three**, because
today a discarded theme can come back in other words:

1. Claude is also shown the rows that were **discarded**, as "already
   rejected, do not propose again".
2. The word-for-word check ignores case, punctuation and spacing, and covers
   the header as well as the bottleneck.
3. A run proposes no more rows than the map has room for (five less the
   accepted ones). When the map is full, Draft says so and makes no call.

What code cannot promise is that Claude never restates a theme in different
words; the prompt is what guards that, the tray is where a person catches it,
and Consolidate merges what is left. v2 sessions get none of these three
changes.

**f and h.** As v2. A template without "What they value" has no such section
in the live view, the pros-and-cons input or the PDF.

**g. Two paths (D13b).** Claude makes the first attempt at the pros and cons:
two to three pros and two to three cons **for each of the two paths**, from
this session's own material only. They land in the tray as proposed. The
person accepts, edits or discards each line, and can write their own. **Only
an accepted line reaches the PDF.** The draft runs once by itself when both
paths have a reaction captured, and on the "Draft pros and cons" button at
any time. A line identical to one already there is dropped. This is v2's
code and v2's rule, unchanged; the practice's own edits teach the next draft
(learn from my edits).

**After the call.** The 2-page PDF (v2 layout), the cover email with the full
body on screen, conversion to goals and projects, and the prep panel are the
existing code. Three v3 differences in the PDF: header chips are the
pre-call questions marked `pdf_chip` (three at most, labeled by `label`);
chart labels come from `label`; Path A/B copy comes from `settings`. In the
first cut a v3 cover email has no automatic "we agreed to speak again on…"
sentences (they are tied to `s9_*` keys); the practice writes them in the
body before sending.

---

## 4. Screens

### 4.1 Templates list (`/strategy/template`, existing screen)

- Shows every template, as today. A v3 template opens in the builder; a
  classic or v2 template opens in today's editor, unchanged.
- **New template** (practice owner): a name, then the builder.
- **A practice with no template** sees one sentence and the New template
  button. Whether it also sees "Restore from seed" is D3.
- Rename, duplicate, set default and archive work on v3 templates as on the
  others. Duplicating a v3 template gives a v3 template.

### 4.2 The builder (`/strategy/templates/<id>/build`, new)

One page, the eight parts in session order, each a card:

| Card | What the practice owner does |
|---|---|
| Header | Name; "Ready to run" checklist; Set as default; Preview the pre-call form |
| Before the call | Add, reword, reorder, remove questions. Per question: a short label and "Show in the PDF header" (three at most). |
| Ratings | Title; scale line; add, reword, reorder, remove rated items, each with a label. A wording that asks an open question is refused with the 9/22 explanation. |
| Diagnostic | **Diagnostic questions per session** (1 to 8, default 3); the fixed questions asked when nothing proposed is accepted. |
| Mirror and where they want to go | The destination questions. |
| The map | Time budget only. |
| What they value | **On / off.** When on: the value items. |
| Two paths | The wording of the two paths; the PDF's title and two lines for each. |
| Scope | The agreement items; which are money (hidden from assistants and from the PDF by default, as today). |
| Wording for Claude | How to describe the practice in prompts (`advisor_role`). |

Every card has a time budget for live sections. Saves are per card. Removing
a question archives it (its key stays spent), as today.

**Ready to run** is computed, not stored: at least two rated items, each with
a label; exactly two path items; a name. A template that is not ready can be
saved and edited, and **cannot start a session**: Start refuses and lists
what is missing.

**Editing a template never reaches a session already created.** The screen
says so in one line, as today's editor does.

After Tuesday (§7 phase 6): add a custom section anywhere among the live
parts, remove and reorder sections, a talk track per section, "start from a
copy of an existing template", and a read-only preview of the live view.

### 4.3 Starting and running a session

- The start form's template picker lists v3 templates beside the others. The
  default is whatever the practice set; **P3 changes no practice's default.**
- The live view is the existing screen. For a v3 session it shows the scale
  line and rating inputs in part b, the diagnostic tray with "Propose from
  the ratings", and the mirror under its questions. Classic and v2 sessions
  render through the same branches they do today.

---

## 5. Access matrix changes

No role gains or loses anything it has today. New rows for §10:

| # | Capability | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 10.1 | Edit a template's questions *(existing)* | ✅ | ❌ | ❌ | — | — | Unchanged |
| 10.1a | **Create a template; edit its sections, rated items and templated text** | ✅ | ❌ | ❌ | — | — | Builder verbs. 403 for everyone else |
| 10.1b | **Read templates** (list, picker, builder read-only) | ✅ | ✅ | ✅ | — | — | As the list does today |
| 10.5a | **Propose the diagnostic** (v3, including "from the ratings") | ✅ | 🔸 own prospects | ❌ | — | — | Same rule as 10.5: costs money against the practice key |
| 10.5b | **Add a diagnostic question by hand during a session** (v3) | ✅ | 🔸 own prospects | ❌ | — | — | Same rule as 10.4: running the call |
| 10.13 | Complete the pre-call form *(existing)* | — | — | — | — | — | Public token. Sees v3's pre-call questions only: never a talk track, a label-only field, or `settings` |

**Platform owner:** nothing. In the Practices area no practice is bound, so
every builder route returns 403 or 404. `apps/platform/stats.py` gains no
template data.

---

## 6. How v2 and v3 coexist, and how v2 is proved unchanged

### 6.1 Why they cannot collide

1. **Format is frozen per session.** A session created from "Operations —
   focused" carries `format: focused` in its own snapshot, and every branch
   reads the snapshot.
2. **No data changes.** The migration adds columns with defaults. No template,
   question, session, answer, row or note is rewritten. "Operations — focused"
   stays the Executives Now default until you change it.
3. **v3 code is added beside v2 code.** v3's differences live in new modules
   (`apps/strategy/v3.py`, `builder.py`) and new frontend components. Where a
   shared function needs a v3 branch, the branch is taken only when the
   snapshot says `v3`.
4. **Classic and v2 templates are closed to the builder.** Its verbs refuse
   them, so none of the new columns can ever be non-default on one.
5. **A classic or v2 snapshot and API payload gain no key.** New fields are
   emitted for v3 only.

### 6.2 The proof

**Phase 1, before any P3 code: golden files.** Written and committed against
today's `dev`, green there, and required to stay **byte-identical** through
every later phase. Two fixed sessions (one classic, one v2), fixed clock,
Claude stubbed:

| Golden | What it pins |
|---|---|
| Session payload as practice owner and as assistant | The live view's data, including the absent money fields |
| Template snapshot from each template | No new key reaches a v2 snapshot |
| Pre-call form payload and questions email body | What a prospect receives |
| Every prompt sent to Claude: diagnostic proposals, draft rows, Consolidate, mirror, pros and cons, prep (system and input text) | The AI behavior, word for word |
| Diagnostic slots and accept / remove results | The v2 diagnostic rules |
| PDF HTML and page count (two) | The sales PDF |
| Conversion preview and the goals and projects created | Conversion |
| Style examples reaching the prompt | Learn from my edits |

**Existing tests are not edited.** `tests/test_strategy_focused.py`,
`tests/test_module4_*.py` and `Strategy.test.tsx` must pass untouched. Each
phase report includes `git diff --stat` for those files, which must be empty.

**The real sessions.** A script hashes the payload and the PDF HTML of every
session on `execsnowhq_local` (the three live classic sessions and the
archived draft) at the pre-P3 commit and again at each phase's head. The
hashes must match. This runs on the laptop only.

**What tests cannot prove.** How the v2 live view looks and behaves in a
browser. That is a manual check: one full v2 session on the demo after P3 is
on `dev` (D11), before go/no-go.

### 6.3 The 10/8 session

- If Tuesday is **no-go**, nothing is released and production stays exactly
  as it is today.
- If Tuesday is **go**, the 10/8 session runs on v2 through the same code
  paths the goldens pin. I also recommend creating that session in production
  **before** the release (D9): its questions are then frozen before P3
  arrives.

---

## 7. Build phases

The goal of phases 1–5 is one thing: **the smallest complete v3 session you
can run end to end on the demo by Monday morning.**

| Phase | When | What | Tests | Not verifiable without a browser |
|---|---|---|---|---|
| **1. Pin v2** | Sat | Golden files and the real-session hash script. No product code. | The goldens themselves, green on today's `dev` | — |
| **2. Schema and template** | Sat | Migration 0016 (SQL shown first). `v3` format. Create a blank v3 template. Builder API: questions with label and chip, rated items, What they value on/off, `settings`, Ready to run. v3 snapshot. | **Isolation:** every builder route with another practice's template returns 404; platform owner 403/404. **Roles:** associate, assistant and client roles 403 on every builder verb. Builder verbs refuse classic and v2 templates. Rating wording rule. Unknown merge field refused. Start refuses a template that is not ready. Goldens unchanged. | — |
| **3. Session engine** | Sat–Sun | Pre-call form and email on v3 questions. Ratings live. Diagnostic from pre-call answers, and from the ratings on the button. Mirror with its questions. Rows input with pre-call answers and ratings. Cap and Consolidate. Values optional. | Proposals land proposed, never asked. Claude's input holds only this session's answers. Fallback questions when nothing is accepted. `diagnostic_size` and the ceiling of eight enforced. A hand-added question joins the session's snapshot and never the template. Discarded rows reach the prompt; a normalized duplicate is dropped; a full map makes no call. Mirror never overwrites accepted text. A session without What they value. Each call writes an `ai_call` against the right practice; the worker's call obeys the daily cap. Assistant payload has no money fields. Goldens unchanged. | — |
| **4. PDF and after** | Sun | v3 PDF context (chips, labels, path copy). Conversion and prep on a v3 session. | PDF is two pages; no private note, mechanics, observation or money without its flag (AC-4.9 on v3). Conversion creates the same goals and projects as for a v2 session with the same rows. Goldens unchanged. | **How the PDF looks**: spacing, wrapping of long labels, the chart with 2 and with 8 items |
| **5. Screens** | Sun | The builder screen. v3 branches in the live view. Template list and picker. Vocabulary and American English checks. | Frontend tests for each builder card and the v3 live view; vocabulary guard; `Strategy.test.tsx` untouched and green. Full suite green, then push to `dev`. | **Everything visual**: the builder's layout, save feedback, the live view on a call-sized window, pacing bar, tray behavior while typing |
| **Mon–Tue** | | Your dry run on the demo. I fix what it finds; nothing new is started unless the dry run is clean. | Regression test per fix | The dry run is the browser check |
| **6. After go/no-go** | later | Custom sections; add, remove, reorder sections; talk tracks; start from a copy; live-view preview; `precall_intro`. | Per item, plus isolation and role tests for each new verb | Section drag and drop; preview |

### As built

**Phase 1 (2026-10-03).** `tests/test_strategy_v2_golden.py` with 34 golden
files each for a classic and a v2 session; `scripts/strategy_session_fingerprints.py`
with its baseline of the four real sessions on the laptop.

**Phase 2 (2026-10-03).** Migration `strategy 0016_template_builder`, the SQL
of §2.2 (Django orders the statements alphabetically). `apps/strategy/builder.py`
and `views_builder.py`: `/api/strategy-template-builder/` creates a blank v3
template and edits its questions, section titles and budgets, "What they
value" on or off, and settings. Differences from the text above, all small:

- The blank template's two paths read "Continue to run it yourselves" and
  "Work with us". `{Practice}` becomes a merge field in phase 3, with the
  session engine that fills it; until then it is accepted in settings only.
- Part limits, enforced on save: 20 pre-call questions, 8 rated items (2 to be
  ready), 8 fixed diagnostic questions, 5 mirror questions, 5 values, 12 scope
  items, always 2 paths.
- The existing editor's question verbs refuse a v3 template (409), so a
  section can only ever hold its own shape of question. Rename, duplicate, set
  default and archive work on every template.
- D3 is enforced on the server: "Restore from seed" returns 403 for a practice
  with no classic or v2 template.
- The template list adds `format`, `ready` and `missing` to a v3 template's
  entry only.
- **Found, not changed:** duplicating "Operations — focused" in today's editor
  gives a *classic* copy (the copy does not carry the format). Fixing it would
  change v2 behavior, so it is left for the owner to decide.

**Phase 3 (2026-10-03).** `apps/strategy/v3.py`, and a v3-only branch at each
place the shared engine needed one (`services`, `ai`, `diagnostic`,
`serializers`, `session_admin`, `views`, `views_precall`). No schema change.
Differences from the text above:

- **Gap questions fill the template's number.** §3c said "up to two" for
  evident gaps. With a growth mention and the default of three that is still
  two; a template set to six gets up to six (or five and the growth one),
  otherwise "a practice sets its own number" would not hold. Claude may still
  find fewer, or none.
- The diagnostic prompt also lists every question already asked, proposed or
  rejected in the session, and a rejected question is not proposed again.
- `{Practice}` is a merge field in a v3 session (the practice's display name).
- A v3 draft session is reloaded from its own template; "Restore seed
  wording" refuses it (409), and so does reloading from a template that is no
  longer ready.
- A v3 session payload carries `rating_scale` and `diagnostic` (`size`,
  `most`). A classic or v2 payload is unchanged.
- "Draft rows" on a full v3 map answers with a sentence and makes no call.

**Phase 4 (2026-10-03).** The v3 PDF context (`v3.pdf_context`), two
conditionals in `templates/strategy/pdf.html` that leave a classic or v2
document byte-identical, and the prep prompt addressed to the template's
advisor. Conversion needed no change. Notes:

- The chart's heading is the ratings section's title; a label longer than 22
  characters is cut with an ellipsis and the label column widens to fit.
- Each path prints its title and its two lines from the template, in bold,
  with no second line under them.
- **The mechanics note does not print on a card map**, whatever its flag
  says, in v2 or v3: a card is a header and a focus statement. This is v2's
  behavior, found while testing, and left as it is.
- A prep rewording that uses a merge field which does not exist is dropped,
  as the builder would refuse it.

**Phase 5 (2026-10-03).** `frontend/src/screens/TemplateBuilder.tsx` (the
builder, at `/strategy/templates/<id>/build`), `SessionV3.tsx` (the live
view's v3 diagnostic tray and scale line), and v3-only branches in the
templates screen, the start form and the live view. Notes:

- Each field in the builder has its own Save, shown once it differs from what
  is stored, rather than one Save per card.
- A practice with no template now sees "Your first template" instead of a
  screen that stayed on "Loading the template…". "Restore from seed" is shown
  only where a classic or v2 template exists.
- Prep's suggested rewordings for a v3 session open in the builder, filled in
  and unsaved.
- **Not built:** "Preview the pre-call form" in the builder header (on the
  list of first things to go).

### What I would cut or defer to hit Tuesday, plainly

**Not in the Tuesday build:**

1. Custom sections, and adding, removing or reordering sections. Only "What
   they value" can be switched off. *This is the largest cut: "sections are
   customizable" is delivered as titles, content and one optional section,
   not as a free layout.*
2. Talk tracks per section, and the editable pre-call intro.
3. Starting a v3 template from a copy of a classic or v2 template. You type
   your questions into the builder on the demo, which is also its test.
4. Automatic next-step sentences in a v3 cover email.
5. Learn from my edits for diagnostic question wording (it keeps working for
   map rows and pros and cons).
6. A v3-specific PDF design. v3 prints on v2's layout.
7. A per-template map cap, rating scales other than 1–10, and moving a
   question between sections.

**First to go if the weekend runs short**, in this order: the PDF header
chips (v3 would print none), "Propose from the ratings", the pre-call form
preview in the builder.

**Not cut under any pressure:** phase 1, the two mandatory test families,
and review-before-it-lands on every AI output.

### Limits of a dry run on the demo

- **The demo has no Anthropic key.** Claude's buttons say so until you enter
  one on the demo's AI usage screen. It spends on that key.
- **The demo has no worker.** The automatic proposal after the pre-call form
  will not run there. The Propose button does the same work.
- **The demo sends no mail.** The pre-call form link exists only inside the
  unsent message. To be confirmed in phase 3: whether the link can be copied
  from the demo's Outbox entry. If not, that leg runs on the laptop (Mailpit),
  or the answers are typed into the session.
- **The demo's practice has no v2 template.** See D11.

---

## 8. Decisions for the owner

| # | Question | Recommendation | Owner, 2026-10-03 |
|---|---|---|---|
| **D1** | **Accept the Tuesday cut**: eight fixed parts in fixed order, only "What they value" optional, custom sections and section reordering after go/no-go? | **Yes.** It is the only version I would call safe for the 10/8 constraint in one weekend. | **Yes.** |
| D2 | A new template starts with the eight parts laid out, neutral wording in Two paths and Scope, and no questions anywhere else | Yes | **Yes.** Other practices build from the blank eight-part start, and it works for Executives Now too. |
| D3 | A practice that has never had a seeded template (Blue Sky, every new practice) does **not** see "Restore from seed", so your Operations questions stay yours | Yes: hide it. Executives Now keeps it. | **Yes.** |
| D4 | Diagnostic size in v3: a session holds **3** questions (template can set 2–5); up to 3 fixed questions as the fallback | 3 | **Yes, 3 by default, amended:** a practice sets its own number (1 to 8), and a question can be added during a session. §3c. |
| D5 | Diagnostic rules in v3: growth mention, up to two evident gaps in the pre-call answers, and "Propose from the ratings" (two lowest) once the ratings are taken on the call | Yes, all three | **Yes, all three.** |
| D6 | The mirror section asks its "where they want to go" questions first, then one Draft button; the PDF prints the mirror where v2 does | Yes | **Yes, exactly as described.** |
| D7 | v3 uses v2's map (cards, five at most) and v2's 2-page PDF layout; header chips are up to three pre-call questions you mark | Yes | **Yes.** |
| D8 | Templated text in the first cut: how Claude describes the practice, the rating scale line, and Path A/B title and two lines each | Yes; pre-call intro and talk tracks after go/no-go | **Yes.** |
| **D9** | **Create the 10/8 session in production on "Operations — focused" before any P3 release**, so its questions are frozen first | **Yes** | **Yes.** The owner creates it himself: Cory Muscato, 10/8. |
| **D10** | **Where the dry run happens.** Demo, with a key you enter on its AI usage screen, the Propose button standing in for the worker, and the pre-call leg on the laptop if the link cannot be copied from the demo's Outbox | Demo for the session; laptop for the pre-call leg if needed | **Yes.** Demo, with a separate Anthropic key that has a small spending limit. |
| D11 | Add "Operations — focused" to the demo's fictional practice (`add_focused_template`, dry run then `--apply`, in the demo's Railway shell) so you can rehearse a v2 session there on the P3 code | Yes. It is the only browser proof that v2 is unchanged. | **Yes.** Done in the demo's Railway shell when P3 reaches `dev`. |
| D12 | Go/no-go rule for Tuesday: goldens byte-identical, real-session hashes identical, existing strategy tests unedited and green, full suite green, one v3 and one v2 session completed on the demo | Yes, all five | **Yes, all five, plus the owner's own judgment after the dry run.** *Dry run waived by the owner at release, 2026-10-03.* |
| D13 | The builder makes no AI calls in P3 (no "draft my template") | Yes; revisit after Blue Sky has used it | **Yes for the builder.** AI in the session is required: Claude proposes the map without duplicates (§3e) and drafts the pros and cons for each path (§3g). |

---

## 9. A practice with no template: a guided start, and "Start from the Operations example"

**Spec for owner review · 2026-10-08 · no code, no schema change proposed.**
Asked for by the owner so that Shawn (Blue Sky) is not facing a blank page.
Sections 1 to 8 are built and released and are not respecified here.

### 9.0 What a new practice meets today

| As built | What it means for Shawn |
|---|---|
| Provisioning gives a practice no template (P2 §3). Getting started lists "Build your first strategy template" and links to Strategy → Manage the templates. | Correct, and it stays. |
| That screen shows **"Your first template"**: one paragraph, a name box, and New template. | The only way in. |
| New template makes the **eight blank parts** (`builder.create_blank`): Two paths and Scope hold neutral wording; **every other part has no questions**. | A page of empty cards. |
| A template is **ready to run** only with two rated items, each labeled, and two path items. A blank one is not, and Start refuses it. | He has to write rated items before he can run anything. This is the "needs two rated items" he was told about on 10/5. |
| "Restore from seed" is hidden from, and refused for, a practice with no classic or v2 template (D3). Part two's "start from a copy" (its §7.2) covers only a practice's own templates, and **is not in the code** (`apps/strategy/builder.py` has `create_blank` and `duplicate` and nothing else that creates a template). | Nothing of yours reaches him, by decision. Nothing else reaches him either. |
| Nothing imports a template or a list of questions. | Questions he already has in a document are retyped one at a time. |

### 9.1 What changes, in one paragraph

The first-template card, and New template for every practice, offer **two
starts**: "Start from the Operations example" and "Start blank". The example
is a complete, ready-to-run v3 template that becomes **the practice's own
copy**: every question, label and line of it is theirs to reword, reorder or
remove in the builder, exactly as if they had typed it. A builder card can
also take **several questions pasted at once**, which is the import (§9.5).

### 9.2 What "the Operations example" is, and is not

**It is a fixed example written into the code**, like the seed is
(`apps/strategy/seed.py`, from `docs/strategy_session_seed.md`). It is not a
row in Executives Now's practice, and creating from it reads nothing of
yours at the time: no template of yours, no session, no setting.

**Its wording is the industry-neutral Operations wording you approved on
2026-09-26** ("Operations — generic": plain language first, the EOS term in
brackets, "your second-in-command" for the Integrator), laid onto v3's eight
parts by the mapping part two §7.2 already describes:

| v3 part | From the Operations seed | In the example |
|---|---|---|
| Before the call | Snapshot (7 questions) | All 7, neutral wording. Three marked for the PDF header (revenue, team, sites), which a practice re-marks or relabels. |
| Ratings | Six Key Components (6 statements) | All 6 as rated items taken on the call, each with its component as the label. The scale line is the default. |
| Diagnostic | 14 questions | **3 fixed questions**, the fallback when nothing Claude proposes is accepted. Diagnostic questions per session stays at the default, 3. E3 asks which three. |
| The mirror and where they want to go | Where they want to go (4) | All 4. |
| The map | none | Time budget only, as in every v3 template. |
| What they value | 5 items | All 5, switched on. |
| Two paths | 2 | The neutral Path A and Path B, with the PDF title and two lines for each. |
| Scope | 9 items | All 9; the money items keep their money flag (hidden from assistants and from the PDF by default). |
| Wording for Claude | | "fractional operations executive". The practice changes it if that is not what they are. |

Time budgets are the builder's own (5 / 15 / 10 / 10 / 5 / 5 / 5, 55 minutes
on the call).

**What is not in it, and stays yours:**

| Stays with Executives Now | Why it is safe |
|---|---|
| Your classic template, "Operations — focused", and any v3 template you build | The example is not made from them. Your edits to them never flow anywhere. |
| **"Restore from seed"** and "Restore seed wording" on a session | Still hidden from and refused for a practice with no classic or v2 template. D3 holds for these. |
| The three questions written for a multi-site service business (`s4_done_right`, `s4_location_parity`, `s4_gross_margin`) and the verbatim EOS wording | Left out, as they are from "Operations — generic". |
| Your style examples ("learn from my edits"), talk tracks, prep briefs, sessions, maps, PDFs | Rows of your practice. Nothing here reads them. |
| Your name, logo and colors | The example carries no practice's name. The copy wears the practice that made it. |
| Fees | The scope items name "Investment discussed"; no amount is in the example. |

**So D3 and D13 are reversed in this and nothing else:** another practice can
now start from *your Operations questions in their neutral wording*. That is
the thing D3 said they could not have. E1 is that decision, and E2 is the
alternative that keeps D3 whole.

### 9.3 The screens

**"Your first template"** (a practice with no template; practice owner):

- One line: "A strategy session runs from a template: what you ask before
  the call, what you rate on it, and the words on the document your prospect
  keeps."
- **Start from the Operations example** (first, the primary button). Under
  it: "A complete template you can run today and change as you go. It is
  written for an operations practice; every question and label is yours to
  reword."
- **Start blank** (secondary). Under it: "The eight parts with nothing in
  them. You write every question."
- A name box shared by both, filled in with "Strategy session" so that
  neither button waits on typing. Any role but the practice owner reads the
  sentence and "Your practice owner builds the first template", as today.

**New template** on the templates list, for every practice: the same two
starts under **Start from**, plus the practice's own v3 templates (which is
Duplicate). Whether Executives Now is offered the example too is E4.

**In the builder, on a template made from the example:**

- A note at the top, until dismissed: "Made from the Operations example.
  Read it through once as if you were the prospect: change what does not
  sound like you."
- Each question, label and line **still exactly as the example has it**
  carries a quiet "from the example" tag. Reword it and the tag goes. This is
  computed by comparing with the example, so nothing is stored and nothing
  can drift (E6).
- **Ready to run** is true from the first second, because the example has six
  labeled rated items and two paths. The checklist adds one advisory line,
  never a block: "Wording for Claude still says *fractional operations
  executive*" while that is unchanged.

**Getting started** keeps its item and its link. It is done when a template
exists, as now.

### 9.4 What creating from the example does

- One request, practice owner only: `POST /api/strategy-templates/` with
  `start_from: "operations_example"` (today's create with one more field;
  absent means blank, so nothing that exists changes).
- It builds the template through the builder's own functions
  (`create_blank`, then `add_question`, `update_settings`), so **every rule
  the builder enforces is enforced on the example**: a rated item that reads
  as an open question, more than three PDF header questions, an unknown merge
  field. A test fails if the example itself would be refused.
- The template is v3, owned by the practice, not the default unless it is
  their first (today's rule), and editable at once.
- An audit event `strategy.template_created` records who, and
  `{"start_from": "operations_example", "example_version": 1}`.
- **The example is versioned and copies are not linked to it.** Improving the
  example later changes what the next practice starts from and nothing that
  already exists. "From the example" tags compare against the version the
  copy was made from.

**Schema: no change.** The example is code; the copy is ordinary template,
section and question rows; where it came from is in the audit event. If you
would rather see "made from the example" on the templates list for good, that
is one nullable column on `strategy_template` (E7), shown as SQL first.

### 9.5 Importing questions a practice already has

Most practices arrive with their questions in a document. In the builder,
each card that holds questions (Before the call, Ratings, Diagnostic, the
mirror, What they value, Scope) gains **"Paste several"**: a box that takes
one question per line and adds them in order, after showing the list back
with anything that would be refused marked and explained (a rated item
worded as an open question; a fourth PDF header question; a line over the
length limit). Nothing is added until the owner confirms the list. No file
upload, no AI, no schema change.

Not in this round: importing a whole template from a file, and exporting one
(E8). Claude drafting a template from a pasted document is the "draft my
template" D13 put off until Blue Sky has used the builder; it stays put off.

### 9.6 Access and isolation

| # | Action | Practice owner | Associate | Assistant | Client |
|---|---|---|---|---|---|
| 10.x | Create a template from the Operations example | ✅ | ❌ | ❌ | ❌ |
| 10.y | Paste several questions into a card | ✅ | ❌ | ❌ | ❌ |

Both are the existing "build a template" row; they add no new permission.

Tests this round must add, beside the two families that are not optional:

- **Isolation.** A template made from the example in practice A is invisible
  to practice B, by list and by id. Making one in B after Executives Now has
  edited every template it owns gives the same content as before: the example
  does not read Executives Now.
- **Roles.** An associate, an assistant and a client are each refused
  `start_from` and "Paste several", with the rows unchanged.
- **Restore from seed is still refused** for a practice whose only template
  came from the example (it is v3, so D3's rule does not see it as a seeded
  template).
- **The pins hold.** `tests/test_strategy_v2_golden.py` and
  `tests/test_strategy_v3_golden.py` stay byte-identical: a blank template is
  still what `start_from` absent makes. The example gets its own small pin
  (its questions, labels and settings), so a change to it is a decision, not
  an accident.
- **Ready to run.** A template made from the example starts a session with no
  edits; a session created from it freezes its snapshot like any v3 session.

### 9.7 What this is not

- Not V1's discipline presets (Marketing, Finance, HR). It is where they
  would go: a second example is one more entry beside this one. None is
  written in this round.
- Not a conversion of anything. No classic, v2 or v3 template or session is
  touched.
- Not a change for Shawn's template if he has already built one. He can make
  a second from the example and set either as the default.

### 9.8 Build phases, once approved

| Phase | What | Done when |
|---|---|---|
| 1 | The example's content as data, built through the builder's functions; `start_from` on create; the audit event; the example's pin; isolation, role and readiness tests. No screen. | Suites green; both goldens byte-identical. |
| 2 | "Your first template" and New template with the two starts; the builder's note and "from the example" tags; the advisory line. | A practice with no template reaches a runnable session in two clicks. |
| 3 | "Paste several" on the six cards. | A pasted list is shown back, refused lines explained, nothing added before confirming. |

No migration in any phase unless E7 is yes. Release is an ordinary one.

### 9.9 Decisions for the owner

| # | Question | Recommendation | Owner |
|---|---|---|---|
| **E1** | **Reverse D3 and part two's D13 this far: any practice may start from the Operations example, which is your Operations questions in their neutral wording.** "Restore from seed", your own templates and everything in §9.2's second table stay yours. | **Yes, if you are content for another fractional to run a session on these questions.** It is the only version of this that is not a blank page on day one. | |
| E2 | The alternative that keeps D3 whole: a **generic example written for the purpose**, none of it from your seed (invented pre-call questions, four or five plain rated items, neutral paths and scope). | No, unless E1 is no. It takes writing you would have to approve line by line, and it will be a weaker session than yours. | |
| E3 | Which three of the 14 diagnostic questions are the example's fixed fallback. | The three marked must-ask in the seed, in seed order; if more than three are marked, the first three. I will list them by wording in the phase 1 report before anything is built on them. | |
| E4 | Is the example offered to Executives Now as well, on New template? | Yes. It is the quickest way for you to get a v3 Operations template to work on, and it shows you exactly what Shawn sees. | |
| E5 | Name on the button and the default template name. | "Start from the Operations example"; the template is named "Strategy session" until renamed. The word "Operations" is on the button, not forced into their template's name. | |
| E6 | "From the example" tags on unchanged wording, computed, never stored. | Yes. It is how a practice sees what it has not yet made its own, and it costs no schema. | |
| E7 | Record where a template came from on the template itself (one nullable column), or only in the audit event. | Audit event only. No migration. | |
| E8 | Import in this round is "Paste several" per card. Whole-template file import and export wait. | Yes. Paste covers the document a practice arrives with; file import has no second practice to exchange with yet. | |
| E9 | The example is versioned and copies never follow it. | Yes. A practice's template must not change under it because the example improved. | |
| E10 | Order of work against part two (custom sections, AI per section), which is approved and, past its phase 1, not built. | This first. It is three small phases, it is what Blue Sky is waiting on, and it touches none of part two's ground. Say if part two should go first. | |
| E11 | Who tells Shawn, and what happens to a template he has already started. | You tell him. Nothing of his changes; the new start is offered beside it. | |

