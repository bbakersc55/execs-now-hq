# P12 — the worksheet engine, four Operations tools and the tool builder (as built, 2026-11-13; E, 2026-11-14)

**Available while the practice has any Command Center on** (P8). With none,
every tools route is 404 and no menu shows Tools. The plans engine's reach
rule decides who reaches a company (`apps.plans.access`).

## The engine

- **A tool is a definition** (`apps/tools/definition.py`): sections of fields.
  - **Field types:** text, long text, number, money, percent, date, choice, a
    person, people, and tables with typed columns.
  - **Computed fields and computed table columns.**
  - **Result cards.**
  - **Optional views:** an org chart, or a cadence on one page.
  - **Optional actions:** calendar events, or import from an SOP.
  - **Optional help (E):** "How to use this" steps (`how_to`), a sample to
    load (`sample`), and on each result card a sentence (`says`).
- **Formulas** (`apps/tools/formula.py`) use a small language that is parsed and
  evaluated in the app. Nothing is handed to Python's `eval`, and a name is
  only ever a field or a column.
  - **Arithmetic and logic:** + - * / ^ and parentheses; comparisons; and, or,
    not.
  - **Names:** a field's key; `table.column` as a list; and, inside a table's
    computed column, the row's own columns.
  - **Functions:** sum, average, min, max, count, if, round, abs, sumif,
    countif, argmax, argmin and filter.
  - `if` evaluates only the branch it takes.
  - A blank number counts as 0 in arithmetic and is skipped by sum, average,
    min and max.
  - Dividing by zero is an error said on the field ("Can't divide by zero."),
    never a crash.
  - A bad formula is refused in words as it is typed. That covers anything
    that looks like code (`__import__`, `open(…)`, `x.__class__`).
- **Evaluation** makes up to four passes, so a formula may read a computed value
  defined after it. Each computed value comes back with its text and any
  error.
- **A run** (`tool_run`) is a saved, named, dated copy of a tool for one company
  or for the practice's own row.
  - It is editable, and duplicable ("… (copy)").
  - **It keeps a snapshot of the definition,** so editing the tool later
    never changes an old run (tested).
  - Only inputs are stored; everything computed is worked out on read.
- **Exports:**
  - **PDF on the practice's letterhead,** through the e-signature letterhead;
  - **Word,** with the practice's name, the company and the date in the
    header, and tables as Word tables.
- **Hand-offs from a run:**
  - **tasks from flagged rows:** each row has a flag; a task's title is the
    row's first words plus the table's name, and its update source is "A
    tool";
  - **a computed value to a KPI,** as a reading marked "From a tool", through
    the scorecard's own entry rules;
  - **an item proposed to the client's plan,** into that horizon's tray,
    drawing on the run;
  - **an SOP brainstorm:** a note on the company titled "SOP brainstorm: …",
    with a purpose, roles, steps, measures and review-date frame and the run
    as its source.
- **The portal:** a run the practice shares ("Show to the client owner and
  senior leadership") shows there read only, under **Shared with you**.
  Nobody else on the client side sees it.
- **Where it shows:**
  - **Tools** in the staff menu, under Plans;
  - the Operations Command Center's **Tools** shelf (the tools and recent
    runs), in place of the placeholder;
  - a **Tools** card on each client company's page, with its runs and "Run a
    tool…".
- **MCP:** `list_tool_runs(company_id)` and `get_tool_run(run_id)`, read only,
  for the practice's people, within their reach.

## The four Operations tools (`apps/tools/shipped.py`)

1. **Bottleneck finder.**
   - **Each step:** who does it, capacity and demand a week, time per unit,
     wait before it, and rework percent.
   - **Load** is demand × (1 + rework) ÷ capacity.
   - **The constraint** is the step with the highest load.
   - **What the process can produce a week** is the smallest good-unit
     capacity, capacity ÷ (1 + rework).
   - **It also shows** the shortfall against demand and the hours of waiting.
   - **"Import steps from an SOP"** reads the numbered or bulleted lines of an
     SOP document's steps or of an unlocked SOP draft note.
2. **Capacity model.**
   - **Each role:** people, hours a week each, and productive percent.
   - **Each kind of work:** volume a week, hours per unit, and the role that
     does it.
   - **By role,** it works out capacity against demand, and the gap in hours
     and in people.
   - **The what-if** is a demand change of plus or minus a percent, and a
     "what if we hire" count on each role.
3. **Meeting cadence builder.**
   - **Each standing meeting:** how often (weekly, every two weeks, monthly,
     quarterly), day, time, length, first date and who attends: several of the
     company's people and whole teams, as chips (E).
   - **Agendas** are in timed sections.
   - **It produces:**
     - the cadence on one page;
     - an agenda document (Word, one page a meeting, with clock times);
     - **recurring events on the person's connected calendar** (Google or
       Microsoft 365, through the calendar connection), or a **calendar file**
       (.ics) to download.
   - **On the demo** it shows the events it would make and makes none.
4. **Org chart by seat.**
   - **Seats first, people second:** each seat has a name, a department (E),
     the seat it reports to, up to five responsibilities (kept to five lines),
     and who is in it (blank is open).
   - **Three plain checks:** knows the job, wants the job, has the time and
     skill.
   - **It produces** the chart (drawn top-down, E), the open seats, and the
     seats with a no.

## The tool builder

- **"New tool"** (the practice owner):
  - the owner describes the worksheet;
  - Claude proposes the sections, fields and formulas, on the practice's key
    at the Deep tier (AI action `tool_builder`), with the price shown first,
    20 a day;
  - the proposal is checked against the engine and opens in the **form
    editor**, unsaved.
- **The form editor:**
  - sections, fields, table columns and result cards;
  - **formulas checked as they are typed,** with each error shown where it
    is;
  - a **preview with sample values,** worked out live;
  - **Save as our tool,** which stays off while anything is wrong.
- **Any shipped tool can be duplicated** ("… (our copy)") and edited the same
  way. The shipped one never changes.
- **A practice's own tools** (`practice_tool`) belong to it and never reach
  another practice (tested).

## 2026-11-14: the chart drawn, teams as attendees, how to use each tool (E)

Bryan could not tell how to run the Capacity model; the org chart was a
nested list; a meeting's attendees were one line of names.

- **E1, the org chart drawn** (`apps/tools/orgchart.py`):
  - **A conventional top-down chart,** drawn on the server as SVG: a box a
    seat, joined by elbow lines from the top seat down. Several top seats
    sit side by side.
  - **Each box** has a header band in the practice's header colour with the
    seat's title in white; beneath it the person (or "Open") and the
    department.
  - **What stands out:** an open seat is dashed in the practice's accent
    colour, with "Open" in that colour; a seat with any "No" has a red
    outline and an "A no" marker.
  - **One drawing everywhere:** every evaluation carries it (`views`, from
    `services.worked_out`), so the screen redraws it as seats are typed; the
    PDF prints the same SVG, scaled down to the page's width (never up); Word
    has a PNG of the same layout.
  - **On screen:** **Zoom out** (−), **Zoom in** (+) and **Fit**, with the
    zoom shown as a percent; drag or scroll to move around. It opens fitted
    to the width.
  - **Department** is a new column of the shipped tool's seats.
  - **It always ends:** a seat reporting to itself, to a seat that isn't
    there, or round a loop is drawn as a top seat.
- **E2, who attends:** a chips control. It offers the company's people and
  its teams, shown as "Team: Sales", and takes free text.
  - **What is kept** is still a list of strings ("Team: Sales" among them).
  - **Wherever attendees are listed** (the cadence on one page, the calendar
    preview, the agenda document, each event's notes and the .ics file), a
    team is spelled out: "Sales team (Sam Sales, Sue Seller)".
  - **The run** brings the company's teams with it (`teams`).
- **E3, how to use, samples, sentences:**
  - **A definition may carry** `how_to` (three or four plain steps),
    `sample` (input values) and, on each result, `says` (a sentence with
    `{result_key}` placeholders). `definition.check` checks all three.
  - **The evaluation fills each sentence** with the results' texts. A
    sentence one of whose results has no value or an error is left out,
    never shown half-filled.
  - **All four shipped tools** have all three. The Capacity model's steps
    are: fill in the roles; fill in the work, with which role does it; read
    the gap; try the what-ifs.
  - **The run's screen:**
    - a **How to use this** panel, open while the run is empty and folded
      once it has values;
    - **Load sample values**. On a run with values it first asks, in the
      page, "Replace what's here with the sample?" (**Replace** / **Keep
      what's here**). What it loads stays unsaved until **Save**.
  - **Each result card** shows its sentence under its value; the PDF and
    Word do too.
  - **A run made before E** takes the how-to, sample and sentences of its
    shipped tool by its key (`services.definition_for`). Only what fits the
    snapshot is taken, and the snapshot itself never changes.
  - **The form editor** edits the how-to (one step a line) and each result's
    sentence. "Keep these as the sample" keeps the preview's values;
    "Remove the sample" drops it.
  - **The tool builder's prompt** asks Claude for all three.
- **No migration:** definitions live in code and runs in JSON.

## Data (migrations, additive)

- **`tools 0001`:**
  - `practice_tool`: name, description, definition, source key, from AI,
    archived;
  - `tool_run`: company, tool or shipped key, tool name, name, date,
    definition snapshot, values, shared with the client, archived.
- **Choices only, no SQL:**
  - `work 0014`: a task update's source "A tool";
  - `scorecard 0016`: a reading's source "From a tool";
  - `plans 0002`: a plan item's source "From a tool".

## Also in this change: Home

**"This week, by client"** is no longer one of Home's arranged panels. It
sits first, above Getting started and the notices, while some client has a
plan this week. It is in view at 1366×768 and near the top on a phone.

## Choices made where the brief was open

1. **Field types:** "people" (several names) was added beside "a person", for
   a meeting's attendees.
2. **"A person" and "people"** are names chosen from the company's contacts
   and the practice's staff, with free text allowed: the person in a seat
   need not have a sign-in.
3. **No string joining in formulas.** Lists come from `filter`, and a
   result's format says how it is shown (number, money, percent, text, list,
   hours, people).
4. **Flags are ticked by hand.** The demo has some ticked.
5. **The SOP brainstorm is a note:** there is no SOP studio yet. It moves to
   the studio when that is built.
6. **The meeting cadence's events invite nobody.** The app has never invited
   people from a person's calendar, so each event names its attendees in its
   notes. Monthly and quarterly meetings fall on the first chosen weekday of
   the month.
7. **Who:**
   - the practice owner and associates (for their companies) run tools and
     use the hand-offs;
   - an assistant reads runs;
   - only the practice owner builds, edits and duplicates the practice's
     tools.
8. **The builder is on the Deep tier,** like the plans engine's drafts.
9. **Tools run for client companies and for the practice itself.** The
   portal shows only runs that are shared.
10. **A run's values are saved with Save,** not on every keystroke. The
    results recalculate as you type.

**Added with E (2026-11-14):**

11. **A team is kept as "Team: <name>"** among the attendee strings. It is
    matched to the company's live teams, ignoring case, whenever it is read.
    - **Spelled out** as "Shipping team (Ana Ruiz, Bo Chen)". A team whose
      name ends in "team", and the default team "Everyone", keep their
      names: "Everyone (…)".
    - **A team's people** are its client users whose sign-in isn't revoked,
      by name or email. Being read each time, a later member shows in an old
      run's agenda.
    - **A "Team: …" the company hasn't** is shown as written.
12. **The chips:**
    - picking from the browser's list adds a name at once; typing adds it on
      Enter, a comma or leaving the field;
    - Backspace in an empty field removes the last;
    - the same name twice is kept once;
    - free text is fine.
13. **The chart on screen is an `<img>` of the SVG,** as the SOP process map
    is, so nothing in it can run.
    - **Zoom** goes from 25% to 250% in steps of a quarter.
    - **Fit** fits the width and never enlarges past 100%. The chart opens
      fitted.
    - **No mouse-wheel zoom:** it would fight the page's own scrolling.
14. **The accent marks open seats; red (#C0392B) marks a no,** so the two
    never look alike. A seat that is open and has a no is dashed and red. An
    open seat's box is tinted with the accent.
15. **Seats are matched by name, ignoring case.** Of two seats with the same
    name, the first is the one reported to.
16. **A long seat title** wraps to two lines in the band, then ends in "…";
    a long name or department is cut to one line.
17. **The PDF's width** is 720px, US Letter less the letterhead's margins.
    **Word's picture** is at most 6.5 inches wide.
18. **What is checked:**
    - `how_to` is three or four steps when given, each up to 300 characters;
    - `says` names results only (not fields), is up to 300 characters, and
      has no brace outside a placeholder;
    - `sample` has only the tool's own fields and columns, numbers that are
      numbers and choices from the list. Blanks are allowed and not every
      field need be filled; the shipped samples fill every input (tested).
19. **An empty list counts as a value** in a sentence ("Seats nobody is in
    yet: none."). The Capacity model's sentences keep the cards' own "a
    minus means spare"; they don't change their words with the sign.
20. **A sample's dates become the run's date** when the run is shown, so the
    cadence's sample never starts in the past. The editor's preview keeps
    the dates as written.
21. **The how-to panel also shows in the editor's preview and in the
    client's read-only view.** Load sample values shows only where the form
    can be changed. A note after loading says nothing is saved until Save.
22. **The sample's people** are made up or are roles ("The owner", "Jordan
    Lee"), plainly placeholders.
23. **The demo's whole team is Acme's default team, Everyone.** No new team
    was made, since one would change what Acme's portal people see.
24. **The MCP read of a run (`get_tool_run`)** is unchanged, without the
    sentences.

## Proof

- **`tests/test_tools.py`** has 52 tests (37, and 15 for E):
  - the language: precedence, every function, the lazy `if`, division by
    zero, nine bad formulas including code-like ones;
  - the definition checks, and an error landing on its field;
  - each tool's arithmetic against hand-worked numbers:
    - bottleneck: the Form step at 146.7%, output 54.5, shortfall 25.5,
      14 hours of waiting;
    - capacity: 152 against 190 hours, 1.25 people short, and both
      what-ifs;
    - cadence: 5.8 hours a month, one agenda running over;
    - org chart: open seats and nos;
  - the five-line limit;
  - snapshots surviving tool edits;
  - duplicate, rename and redate a run;
  - the hand-offs: a KPI reading from a tool, refusing a non-number, tasks
    from flagged rows only, a plan proposal, the SOP brainstorm;
  - SOP import, refusing a locked note and the wrong tool;
  - the calendar: the rules, the first dates, the agenda clock, the .ics file,
    no connection, and the demo;
  - Word and PDF;
  - practice isolation;
  - no Command Center;
  - the portal: shared only, owner and senior leadership only, read only;
  - owner-only building, and duplicate and edit;
  - the builder with a fake Claude (the price first, Deep, nothing saved,
    problems listed);
  - MCP scope;
  - the EOS-term check, including GWC and Level 10;
  - **E:**
    - the chart's SVG: a box a seat, header bands in the practice's colour,
      Open and the department, open and no styled, two top seats side by
      side;
    - a loop, a seat reporting to itself and a 200-deep chain all end;
    - the chart in the run, in live evaluation, in the PDF scaled to 720px
      (its text read back) and as Word's picture;
    - the department column;
    - a team spelled out in the calendar preview, an event's notes, the .ics
      file and the agenda document, while the stored value stays strings;
    - how a team is spelled;
    - each shipped tool's how-to, full sample (worked out with no errors)
      and filled sentences;
    - the Capacity model's how-to;
    - a sentence left out when a result has no value;
    - how-to, sample and sentence checks, a bad placeholder among them;
    - an older run's snapshot taking all three from the shipped tool;
    - a sample's dates on the run's date.
- **`frontend/src/screens/Tools.test.tsx`** has 14 tests:
  - a run's results, table and save;
  - a KPI reading offering only numbers;
  - the SOP brainstorm and SOP import (P10);
  - the client's read-only view;
  - the shelf;
  - the builder's price first and its proposal in the editor;
  - a bad formula marked where it is;
  - the demo's calendar;
  - **E:**
    - How to use this, open on an empty run and folded on one with values,
      and a result's sentence;
    - Load sample values on an empty run, unsaved until Save;
    - the inline ask on a run with values, both ways, never
      `window.confirm`;
    - the chart's Zoom in, Zoom out and Fit;
    - a team and a typed name added as chips, spelled out in the cadence,
      and saved as strings.
- **`tests/test_demo_seed.py`** checks:
  - the four Acme runs worked out, the shelf, the calendar's four events,
    and what Wiley and Marvin see;
  - **E:** the drawn chart with its departments; the monthly review's
    "Everyone (…)" spelled out; every run with its how-to, sample and
    sentences.

## The demo

- **Acme Fasteners:** one run of each tool, from the reset's discovery weeks.
  The org chart and the bottleneck finder are shared with Wiley. The seats
  have departments, and the monthly review is attended by the whole
  "Everyone" team (E).
- **Summit:** its own tool, "Client health check", with one run on the
  practice.
- **No Claude in the seed.**
