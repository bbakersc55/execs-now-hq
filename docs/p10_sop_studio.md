# P10 — the SOP studio (as built, 2026-11-13)

A company's standard operating procedures, written with Claude, published in
numbered versions to the people who do the work, and read and acknowledged in
the portal. Available to a practice while **any Command Center is on** (the
plans engine's rule); with none, every route is 404 and nothing is listed.

Code: `apps/sops/` — `models.py`, `access.py` (who), `services.py` (the record,
versions, reading, Remind, suggestions, the digest line), `flow.py` (the
process map), `exports.py` (PDF and Word), `brainstorm.py` (Claude),
`media.py` (Gemini), `pack.py` (the Notebook pack), `views.py` (the routes,
listed in its docstring). Frontend: `screens/Sops.tsx`,
`screens/SopBrainstorm.tsx`, `components/SopsForKpi.tsx`, `lib/sops.ts`.

## The record

An SOP belongs to a client company or to the practice's own row, and holds:

- title, purpose, when it applies;
- roles (a name and what they do);
- ordered steps, each with its text, an optional role, an optional warning
  and optional images (up to six a step);
- an owner (someone at the practice or a portal user of the company);
- a category, the company KPIs it should move, a review date;
- attachments: images and PDFs, 10 MB each;
- a process map;
- a status: **Draft**, **Published** or **Archived**.

**New SOPs start from the Operations Command Center's SOP template**: the
practice's copy of it (Settings → Documents) if it has one, else the shipped
one. A template heading that matches a field (Purpose, Roles, Steps,
Measures, Review date) gives that field its hint; any other heading becomes a
section of the SOP.

**Publishing** freezes the working copy into the next numbered version, with
a change note (the first is "First version."; after that a note is
required). A version marked **minor change** keeps the read requests of the
one before; any other version asks the audience again. The first version
always asks. The portal shows only the latest published version, never the
working copy; the editor says "Changes not published yet" when they differ.

**Export** as PDF (the e-signature's letterhead, the map drawn inline) and as
Word (the practice's name, the company and the date in the header, the map as
a picture). The practice exports the working copy or any version; a client
gets the version published to them.

### The process map

Kept as text, in a small part of Mermaid's flowchart language that Claude
writes well and a person can edit:

    flowchart TD
      start([Order arrives]) --> check{In stock?}
      check -->|Yes| pick[Pick and pack]
      check -- No --> back[Back-order]

Steps `id[text]`, decisions `id{text}`, starts and ends `id([text])`, arrows
with optional labels, chains. The app draws it itself (`flow.py`: ranks top
to bottom, loops round the right-hand side), the same drawing as SVG in the
app and the PDF and as PNG in Word. A line it can't read is named by number.
**Start from the steps** draws a straight-line map from the steps with no AI.

## Where it lives

- **The Operations Command Center page:** an "SOPs" shelf, first on the
  page, every SOP by client, with search and filters (client, status,
  category); "All SOPs" opens the same list as a page.
- **The menu:** "SOPs" for the practice, beside Plans and Tools.
- **Each client company's page:** an SOPs card ("New SOP", "Brainstorm a
  process", "Notebook pack").
- **A KPI's Details:** "SOPs for this number", the SOPs linked to that KPI.
- **The client portal:** an "SOPs" page, once something is published to the
  person.

## Publishing and acknowledgment

- **The audience** is the whole company, chosen teams, or named people (live
  portal users of the company).
- **In the portal**, each person in the audience reads the latest version
  (steps, images, warnings, the process map, the numbers it should move,
  PDFs), phone-friendly, and ticks **Read and understood**. The tick records
  who, when and which version.
- **A new version that isn't minor asks again:** "What changed" is shown, and
  the button comes back.
- **Each version's read-by day** is a week after it is published. A tick
  after it is late: the version's publisher and the client owner get a
  Notice (a new Notice kind, "An SOP read late, or a change suggested").
- **The practice and the client owner** see "7 of 12 read", the names
  outstanding, and the readers with when, which version, and "late".
- **Remind** drafts one email to each person who hasn't read it ("Please
  read: …", with the link) into the **Sending queue**, waiting for approval
  (a new producer, "SOP reminder"). Someone with a reminder already waiting
  gets no second one. The client owner may press it too; the draft goes from
  the practice and still waits for the practice's approval.
- **The weekly digest** gets an "SOPs to read" section: "New: …" or "Updated
  to version N: … <change note>", for SOPs published since the last digest
  that person was sent, only if they are asked to read them (or own the
  company). Minor versions get no line. A weekly draft already waiting is
  marked out of date, so its Update button adds the line.
- **Suggest a change**, from anyone who reads it, lands on the SOP as a
  comment for the practice (with a Notice to the version's publisher). The
  practice marks it resolved.

### Who

- **The practice owner**, and **an associate** for a company assigned to them:
  create, edit, publish, archive, remind, build the Notebook pack.
- **An assistant:** reads every SOP, drafts and edits, brainstorms; never
  publishes, archives, reminds or builds a pack.
- **The client owner** opens every published SOP of their company and sees
  who has read it; is asked to read (and counted) only when the audience
  includes them.
- **Anyone else in the portal:** a published SOP only when they are in its
  audience. **Outside it, the SOP can't be fetched at all**: the list leaves
  it out, and its page, files, images and acknowledgment are 404. Drafts and
  the working copy never reach the portal.

## Brainstorm mode

A saved conversation with Claude about one process (`Brainstorm`), on the
practice's own key.

- **The tier** starts at the practice's choice for the AI action "SOP
  brainstorm" (Settings → AI; Standard unless changed), and is switchable to
  Deep per brainstorm.
- **The price is shown before each send** and before each action, from what
  that send would carry: the sources' text, the conversation (the last 20
  turns), the newest six images at about 1,600 tokens each, and the action's
  output. A running total ("Spent so far") is the sum of the brainstorm's AI
  calls.
- **Inside the practice's AI caps:** a key must be set; the month's AI budget
  not spent; a demo visitor's allowance not used; 60 brainstorm sends a day
  for the practice.
- **Inputs:**
  - typed descriptions (the conversation);
  - pasted text (a notebook summary, a transcript);
  - screenshots and photos, which Claude reads as images (resized to 1,568
    px, 10 MB each);
  - PDFs, with their text extracted (20 MB, 100 pages; a scan with no text is
    refused with what to do instead);
  - a video or audio file's transcript (below);
  - a note, a tool run, or another SOP.
- **The four actions**, each a proposal a person accepts, edits or discards;
  nothing applies before that:
  - **Draft the SOP** fills the record. Against an existing SOP it is shown
    as a **diff**: the fields from → to, and the steps added, removed and
    unchanged. A brainstorm with no SOP yet makes one, as a Draft, on the
    first accept.
  - **Draw the process map** proposes the map's text, checked before it is
    offered and editable before it is accepted.
  - **Make the checklist** proposes the tasks of putting the SOP in place
    (training, forms, a review), at most 12. The accepted ones are made in
    Work under the goal or project chosen, marked "From an SOP checklist".
  - **Suggest measures** proposes KPIs from the company's scorecard and the
    KPI library, by exact name. Accepting a library KPI adds it to the
    company's scorecard first; each is linked to the SOP.
- **Every accept and discard goes to the practice library** (`sop_ai_accepted`,
  `sop_ai_rejected`), with what was proposed and what it made. Each published
  SOP is kept there too (kind "A finished SOP"), updated on each publish.
- **"Draft an SOP from this" on a note** opens a brainstorm with the note
  (body, transcript and summary) as its first source. A PIN-locked note never
  is a source. The Operations AI action "Draft an SOP from a note" now runs in
  the app by default; set to "In my AI app", the button becomes "Do this in
  your AI", whose prompt saves with `draft_sop`.

## Video and audio

Settings → AI usage has a **Media key (Gemini)**, used only to read video and
audio in the SOP studio.

- **The key:** encrypted like the other keys; Test, Remove; off until
  entered. The screen says plainly that those files go to Google, under the
  practice's own agreement with Google. A demo visitor's copy takes none.
- **The model:** the platform owner's model table has a new row, "Media
  (Gemini)", `gemini-2.5-flash` at $1.00 in and $2.50 out per million tokens
  (audio's input price, so the estimate errs high), editable without a code
  change.
- **With a key:**
  - The **price is shown first**, from the file's length, which the browser
    reads: audio at 32 tokens a second, video at 300, plus the transcript out.
  - The file goes to Google's file store. The screen asks again every few
    seconds; once Google has it ready, one request asks for a transcript and
    a step-by-step summary, which become the source's text.
  - Google's copy is deleted as soon as the answer is back.
  - The cost is recorded as an AI call (purpose `sop_media`).
- **The original isn't kept** unless the person ticks "Keep the file"; it is
  never written to storage otherwise.
- **Limits:** audio up to 60 minutes and 50 MB; video up to 15 minutes and
  100 MB. Two steps (upload, then read) keep each request well inside the
  web server's 120 seconds.
- **Without a key** the upload is refused: "add a media key, or paste a
  transcript", with a button to paste one.

This is the one place a model other than Claude is used, at the owner's
request, and only to turn a recording into text: Claude does all the drafting.

## Notebook pack

On a client company's SOPs card, **Notebook pack** builds a zip for the
owner's own Gemini Notebook, numbered in reading order:

1. `00 README.md` — one page: creating the notebook, uploading, pasting the
   prompts, pasting the answers back into a brainstorm.
2. `01 prompts.md` — the prompt sets the Operations Command Center ships
   (find the handoffs and bottlenecks; the steps that depend on one person; an
   onboarding sequence from these SOPs; what is missing or contradictory; a
   training overview). The practice owner edits the practice's copy in the
   pack dialog, or goes back to the shipped ones.
3. `02 Goals outline.md`, `03 Plan by horizon.md` (this period of each
   horizon), `04 Scorecard.csv` (each KPI's last 13 readings).
4. Every SOP that isn't archived, as a PDF (drafts marked "(draft)").
5. Strategy map PDFs (sessions with accepted rows, newest five).
6. The tool runs and documents chosen (documents as finally signed, signed,
   or sent).
7. `Meeting summaries.md` — approved meeting proposals.

**Never in a pack:** mail of any kind, notes (so never a PIN-locked one), and
People data. Each pack is recorded in Activity ("built a Notebook pack for
…", with its files' names). The practice owner and associates build packs;
assistants don't.

## AI apps (MCP)

- **`list_sops`** — the SOPs you can see: the practice's across the companies
  it reaches, drafts included; a client user's only those published to them.
- **`read_sop`** — one SOP as text: the working copy for the practice, the
  published version for a client.
- **`draft_sop`** — the practice (owner, associates on assigned companies,
  assistants) drafts an SOP; it lands as a **Draft marked as made by an AI
  app**, read by nobody until a person publishes it.

## What was connected

- **Tools:** "Start an SOP brainstorm" on a run opens a real brainstorm with
  the run as its first source (it was a note). The Bottleneck finder's
  "Import from an SOP" lists the studio's SOPs first and imports their steps;
  the older kinds (a document from the SOP template, an "SOP draft" note) stay
  offered.
- **The plans engine:** "Draft from sources" offers each SOP that isn't
  archived, reading its published version (or a draft's working copy), for
  client companies and the practice's own plan.
- **Notes:** "Draft an SOP from this" (above).
- **The connector rails** had nothing stubbed for want of SOPs.

## Data (migrations, additive)

- **`sops` 0001_sop_studio:** `sop`, `sop_kpi`, `sop_audience_team`,
  `sop_audience_person`, `sop_version`, `sop_ack`, `sop_attachment`,
  `sop_comment`, `sop_brainstorm`, `sop_brainstorm_source`,
  `sop_brainstorm_message`, `sop_brainstorm_proposal`, `sop_pack_prompts`.
- **Choices only (no SQL):** `tenancy` 0025 (the Gemini key's kind),
  `aiconnect` 0002 (the media row's code), `centers` 0004 (two library
  kinds), `notify` 0004 (the SOP notice), `work` 0015 (the "SOP checklist"
  task source), `crm` 0059 (the "SOP reminder" producer).

No scheduled job and no environment variable. Reminder links use
`PUBLIC_BASE_URL`.

## Choices made where the brief was open

1. **The process map's text** is a small part of Mermaid's flowchart
   language, drawn by the app's own layout, so the app, the PDF and Word show
   the same drawing with nothing to install.
2. **Read-by:** a week after each version is published; later is late.
3. **The client owner** sees every published SOP of the company and its
   reads, but is counted only when in the audience.
4. **Remind** is one draft per unread person, never a second while one
   waits; the client owner may remind, and it goes from the practice.
5. **The first version always asks;** "minor change" is offered from version
   2, and a change note is required from version 2.
6. **Assistants** draft, edit and brainstorm; they don't publish, archive,
   remind or build packs.
7. **The brainstorm's caps:** the practice's key and month's budget, a demo
   visitor's allowance, and 60 sends a day.
8. **The checklist** is the work of adopting the SOP, not its steps again,
   under one goal or project.
9. **Measures** come from the company's KPIs and the library; a library one
   is added to the scorecard when accepted.
10. **A brainstorm with no SOP** makes it as a Draft on the first accept.
11. **Media limits:** audio 60 minutes and 50 MB, video 15 minutes and 100 MB,
    on `gemini-2.5-flash`.
12. **The Notebook pack** is for client companies, holds every SOP that isn't
    archived plus the newest five strategy maps, and is built by the practice
    owner and associates.
13. **The digest line** goes only to people asked to read the SOP, and never
    for a minor version.
14. **An attachment in a published version** can't be deleted.
15. **"SOPs" in the menu** as well as the shelf, as Plans and Tools are.

## Proof

- **`tests/test_sops.py`**:
  - isolation and every role;
  - versions, minor changes and reading again; a late read told;
  - audience by team and by person, and 404 outside it; step images only to
    the audience;
  - Remind once into the Sending queue; Suggest a change; the digest lines
    (and none outside the audience);
  - the template, owner, KPIs and map; the flowchart's parse and drawing; the
    exports carrying the map;
  - the brainstorm with a fake Claude: sources, an image sent as an image,
    the price before anything is spent, the Deep tier, a draft accepted then
    shown as a diff and discarded, a map, a checklist into Work, measures
    from the library, the caps; a note opening a brainstorm, never a locked
    one;
  - the media path with a fake Gemini: no key refused in words, limits, the
    price, reading in two steps, the file not kept unless ticked, Google's
    copy deleted;
  - the Notebook pack's files in order and its exclusions, and its Activity
    line;
  - the MCP tools' scope;
  - the tools hand-off and import, the plans engine's source;
  - Activity and the practice library.
- **`tests/test_demo_seed.py`** checks the demo's three SOPs (below), with no
  AI call.
- **Frontend:** `Sops.test.tsx`, `SopBrainstorm.test.tsx`, `SopsNav.test.tsx`,
  and additions to `Tools.test.tsx` and `AiUsage.test.tsx`.

## The demo

Acme Fasteners gains ten portal users (the floor, quality, shipping), so its
twelve are the audience of what is published to the whole company. No AI is
spent by the seed, and the demo has no media key, so a recording is pasted as
a transcript.

- **Header line changeover:** published, version 1, with a process map
  (decisions and a loop), warnings on steps, two KPIs, read by 7 of 12 (one
  late), and a suggested change from the floor.
- **Receiving a steel delivery:** version 2, which asks everyone again (a
  mill-certificate check added); three have read it, Marvin hasn't.
- **Quoting a custom fastener job:** a Draft, with a saved brainstorm: a
  pasted notebook summary and a pasted transcript, a four-turn conversation,
  and Claude's revised draft waiting as a diff.
