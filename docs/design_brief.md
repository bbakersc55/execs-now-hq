# Design brief — Execs NOW HQ UI pass

Written 2026-09-21 from the owner's references and answers. This replaces "modernize it" with specifics. Tier 1 ships before the prospect call; Tier 2 follows. Nothing in the roadmap section is UI work.

## Direction, in one paragraph

Light content area on a dark navy sidebar. Clean modern sans (Inter). Cards for work, tables for records, and a clear hierarchy so a screen has one thing that matters most. Brand blue carries structure and headings, orange marks exactly one action or one highlight per screen, near-black text. Generous spacing on a fixed scale. The references the owner pointed at: Asana (board cards, list grouping, filter bar), HubSpot (sidebar with icons, collapse to icons, filter chips over a table), Trello (task editor opening as a focused panel with actions down the side), his own Academy of America app (sidebar icons, sectioned pages). Fask and Evernote for cleanliness, not for their dark theme; dark mode is shelved.

## Foundations (Tier 1)

**Type.** Load Inter from Google Fonts with a system fallback stack. Scale: 12 / 13 / 14 / 16 / 20 / 24 / 32 px. Body 14, table cells 13, page title 24, section title 16 semibold, labels 12 uppercase-tracked in muted gray. Line height 1.5 for body, 1.25 for headings. Tabular numerals wherever numbers align.

**Spacing.** 4-point scale: 4 / 8 / 12 / 16 / 24 / 32 / 48. Page gutter 32. Card padding 16 (compact) or 24 (primary). Gap between cards 16. Nothing sits on an arbitrary pixel value.

**Color tokens.** `--navy #0A3A65` (sidebar, headings, primary buttons), `--orange #F58220` (one primary action per screen, the active-nav rail, one highlight), text `#1F2937`, muted text `#6B7280`, borders `#E5E7EB`, surface white, page background `#F5F7FA`. Status colors: not started gray, in progress blue, waiting on client orange, blocked red, done green, cancelled gray-strikethrough. Priority: low gray, normal none, high orange, urgent red.

**Surfaces.** Two levels only. Page background → cards (white, 1px border, 8px radius, no shadow at rest). Elevation (a soft shadow) is reserved for the thing in focus: an open task editor, a dragged card, the current section in the live view. Everything else is flat. No nested cards: a card never contains another card.

**Icons.** Lucide, 18px in nav, 16px inline, stroke 1.75. Every nav item has one. Buttons with an icon put it before the label.

**Buttons.** Primary: orange fill, white text, 8px radius, 36px tall. Secondary: white with border. Tertiary: text only in navy. One primary per screen, top right of the page header ("New task", "Add contact", "Start a session"). Never a full-width orange bar.

**Filters.** Chips, not bare dropdowns. A filter bar under the page header: each active filter is a chip ("Client: Acme ×"), "Add filter" opens a small menu, and a clear-all appears when any are set. Search is a real search field with an icon and instant results, not a field plus a Search button.

## Shell (Tier 1)

- Sidebar stays dark navy, 240px, grouped as now (Accounts, The work, Elsewhere, Settings) with a 12px uppercase group label, each item with a Lucide icon and label, active item marked by a 3px orange rail on the left and a slightly lighter row background, never a filled orange bar.
- **Collapse to icons**: a toggle at the bottom of the sidebar collapses it to 56px showing icons only, with tooltips on hover. Manual only; remembered per user. Auto-collapse on narrow windows is Tier 2.
- Product name at top for staff; tenant display name and logo for client users (white-label rule).
- User block at the bottom: avatar (initials), name, role as a word.
- Page header on every screen: title (24), one-line subtitle in muted text, primary action top right. Breadcrumb above the title on detail pages.
- Client portal shell: same structure, tenant brand, three items (Our work, Tasks, Value report).

## Work screen (Tier 1)

- Grouped by client company as now, each company as a section with its name as the section title and its own "New goal" tertiary action.
- Each goal is a card: title (16 semibold), measurable headline if numeric (baseline → current → target, tabular), completion bar subordinate beneath, client owner avatar and horizon chip on the right, an expand chevron. Expanded, projects nest as sub-rows with their own tiny completion bar, and tasks beneath as compact rows (status dot, title, assignee avatar, due date).
- "Projects with no goal" and "Tasks filed under nothing" remain as their own sections, styled the same.
- Empty states: a short sentence and the one action that fixes it, never a bare "None."

## Tasks: board and list (Tier 1)

- **Board is the default.** Columns by status, each with its count, collapsible (collapsed column becomes a vertical label with the count). Drag between columns as now, with the client-facing line prompt unchanged.
- **Card anatomy** (Asana-style): status stripe on the left edge in the status color; title; a row of small chips (priority when not normal, project name, due date colored red if overdue); assignee avatar bottom right; a small comment count and checklist progress ("2/5") bottom left when present. Nothing else on the card.
- **List** is the alternate view: grouped by project with collapsible group headers, rows with a check-circle, title, assignee avatar, due, priority chip, status chip. Sortable column headers.
- Filter bar with chips: Client, Project, Assignee, Status, Priority, Due. Board and list share it.

## Task editor (Tier 1)

- Opens as a focused panel over the board (right-side sheet, 640px, elevated), not a separate page, with a URL so it can be linked and deep-opened. Escape or the close button returns to the board where you were.
- Layout, Trello-style: header with title (editable inline), status chip and priority chip; left column: description (the rich editor already built for the Outbox), steps checklist, comments with the internal/shared control, history; right column: assignee, client owner, due date, project and goal, "who hears about this" stakeholders, client-visible toggle, then actions (mark as milestone, delete).
- The client-facing line prompt appears inline at the top when status changes, as now.

## Strategy session live view (Tier 1)

- Section navigation as a left rail inside the page (the nine sections with their time budgets and the pacing pill on the current one), content on the right, the Claude tray as a collapsible right-side drawer that slides in when candidates land.
- The current section is the one elevated surface. Answered pre-call questions show with a "from the form" chip. Must-ask questions carry a small orange marker, not a chip that shouts.
- Map rows render as cards grouped under 30/60/90 exactly as the PDF does, so what you see on screen is what he receives.

## Portal (Tier 1)

- Our work and the task pages get the same treatment as the staff side, in the tenant brand.
- The value report: goal cards with the measurable headline, chart when there are three readings, milestones on a horizontal timeline, narrative beneath, resolution history in a quiet list. The engagement timeline at the top as one horizontal axis.

## Tier 1 — built 2026-09-21

Everything above this line in Tier 1 is built, with three questions answered by
the owner before any of it was written:

- **The task editor replaces the page.** `/tasks/:id` renders the board with the
  sheet over it; there is one task editor, not two that drift.
- **The live view's rail navigates and nothing else.** Starting a section is its
  own control, so reading ahead mid-call cannot move the pacing under you.
- **Inter and Lucide are self-hosted.** Inter is vendored as one variable woff2
  with its OFL licence; the app is demonstrated on other people's wifi, and a
  `<link>` to Google falls back to system fonts silently.

**Three things the build decided**, stated here rather than left in the code:
avatars are initials with a tint derived from the name, because no photograph
exists in Beta and none is invented; "remembered per user" is remembered in that
browser, since the app has no per-user settings table, which is how FR-3.39a's
filter already works; and the Work screen keeps its client selector rather than
gaining a chip bar, because the brief gives the filter bar to Tasks.

**Not verified in a browser** — the Chrome extension is not connected in this
session. 264 frontend tests pass, which says the markup behaves, not that it
looks right.

### Findings, round 1 — fixed 2026-09-21

From the owner's browser pass. All four, and one thing the pass turned up that
was not a fault.

1. **The "+ New note" button did not collapse** and its text overflowed the
   56px rail. It is a sidebar control like the others now, and collapses like
   the others: the icon, and the tooltip.
2. **A stray bullet beside every goal card.** The `list-style: none` on
   `ul.work-tree` was lost in the Tier 1 rewrite and the browser's own marker
   came back.
3. **Every goal card printed its title twice.** The headline fell back to the
   goal's own title, and a goal converted from a map row has its bottleneck as
   its title and nothing written about it yet. **A headline that repeats the
   title is not a headline**: the server now returns `kind: "none"` and the
   card shows what it is waiting on — *"no measure recorded yet · no outcome
   statement yet"* — **to staff only**. A client is shown the goal, not the
   practice's unfinished admin. The same fix went into the PDF, which had the
   same double-print.
4. **Timeline labels overprinted** where marks bunched. They stagger above and
   below the line now, and a label that would still land on its neighbour
   leaves its **number** behind instead — the number the list under "Every
   mark, in words" now carries, so nothing on the axis is anonymous and
   nothing is lost.

**Not a fault:** the strategy PDF runs to three pages on Noble Baker's session.
Four of the five exclusion toggles are on there. Two pages is the rule *with the
exclusions where they ship*, which is what a prospect receives; turning one on
puts something private on the page that was not there, and that is the toggle's
cost. There is now a test that says exactly this.

## Tier 2 (after the call)

- ~~**Dashboard** as the landing page~~ — **built 2026-09-22.** Four tiles (tasks due, digests waiting, pipeline moves, open goals), then three panels (due by day, waiting for approval, pipeline this week) and a card per client company. Calendar panel still waiting on the Google Calendar integration.

  **One deviation from this line, deliberate.** The brief says "pending digests **with approve**". FR-3.29 says the approval screen exists because *approving something you have not read* is the failure it prevents, and a dashboard panel cannot show the whole rendered digest. So the panel lists what is waiting — recipient, cadence, period, whether it is AI-drafted or stale — and each row links to the digest screen. Approving is still one click away; it is just a click that happens where the thing being approved is visible. **Owner: say the word if you would rather have the button and accept the trade.**

  Three smaller decisions worth recording: the tile says how much of the total is **overdue** rather than folding it in silently; the by-day list shows **quiet days as zeros** rather than skipping them, because a list that skips them makes a light week look like a missing one; and "this week" is **the next seven days**, not the calendar week, so the number does not shrink as the week goes on.
- ~~**Contacts and Companies**~~ — **built 2026-09-22.** Tables kept, with avatars, sortable headers, chip filters, instant search, row hover actions and a peek sheet.

  **Instant search replaced type-then-press-Search**, debounced at 250ms so a five-letter name is one request and not five. The old pattern made every search two actions and made an empty result look like a slow one.

  **Two targets per row, on purpose.** The name opens the record; a *Peek* action opens a right-side sheet with enough to decide whether to open it, and a link that does. Row actions appear on hover **and on keyboard focus** — a control that exists only for a mouse is a control half the people cannot reach — and are always visible on touch.

  **Sorting: blanks last in both directions.** An empty cell is absent information, not a low value, so a contact with no title does not lead the ascending sort. The column header's accessible name stays the column's name; the arrow is decorative and `aria-sort` carries the state.

  One rule re-checked on a new surface: matrix 9.5 says seat usage is not a VA's to see, and the peek sheet is a new place that number could appear. It does not, and a test says so.
- **Notes**: panel layout (list on the left, note on the right). Stacks and notebooks are a data-model change and belong to the roadmap, not the pass.
- Settings screens, Outbox, Digests, Activity: same tokens and components, no structural change.
- Sidebar auto-collapse on narrow windows. Dark mode as an option.

## Recorded for the roadmap (not UI)

- Campaign / sequence editor: put referral partners and nurtured prospects on custom cadences with custom messaging, multi-step, per contact or per segment. Builds on the Outbox and referral touches.
- Task dependencies, with dependent tasks auto-collapsed until what they wait on is done.
- Private tasks (visible only to their creator) and task assignment to other users as a first-class action.
- Notes as a filing system: stacks → notebooks → notes, alongside the existing links to contacts, companies and tasks.
- Google Calendar integration: read appointments, create strategy sessions from events, drive session-related automation.
- In-app AI helper for tasks inside the app, starting with email inbox triage; features discussion pending.
- Additional AI models, via an integration layer (N8N or similar) if needed; features discussion pending.
