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

## Tier 2 (after the call)

- **Dashboard** as the landing page: four stat tiles (tasks due this week, pending digests, pipeline movement this week, open goals), then panels: tasks due (by day), pending digests with approve, pipeline changes, client cards (one per client company, click to drill in). Calendar panel wired when Google Calendar integration lands.
- **Contacts and Companies**: keep tables (they are records), add avatars, sortable headers, chip filters, instant search, row hover actions, and a right-side detail sheet on click before the full page.
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
