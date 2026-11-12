# P8 — Command Centers, version one (as built, 2026-11-10)

A **Command Center** is a module for one discipline. A practice turns one on,
and the module then offers what it brings: session templates, KPI library
entries, playbooks, document and email templates, recommended feeds and AI
actions. This build adds the frame and the **Operations Command Center**.

## The catalog and the switch

- **The catalog** is the platform's `command_center` table, seeded by
  migration (`centers 0002`). Each row has a code, a full name, a short name,
  a discipline, the price ($50 a month), a description and a status.
  - Operations is **available**.
  - People and Technology are **coming** and marked "Next".
  - Finance, Sales, Marketing, Projects and Training are **coming**.
- **The switch** is in Settings → Command Centers (`/settings/command-centers`,
  for the practice owner). Turning one on asks first, and says what is added:
  - "$50 a month is added to your subscription from {the next 1st}; the rest
    of this month is included. All Command Centers together are capped at
    $150 a month."
  - For the platform owner's own practice: "Included for your practice."
- **What turning on does.** It writes `practice_command_center` and one
  `practice_subscription_addon` on the platform's `billing_addon`
  `center_<code>`, charged from the next 1st, as P4's D4 has it.
  - Turning it off sets the line's `removed_at`.
  - The platform owner's practice gets no line.
- **The cap.** `subscriptions.lines_for` bills each line, then adds one
  credit, "Command Centers capped at $150 a month", when there are more than
  three.
- **The demo** refuses every change with a sentence. The page shows it, and
  the seed turns Operations on directly.
- **Names.** The app's navigation shows only the discipline, "Operations",
  which links to the module card at `/centers/operations`. The full name is
  on the card, in Settings and on the site.
  - **Where (2026-11-12):** second in the list, under its own "Command
    Centers" heading after Today. Eighteenth, after Finance, it was below the
    fold at 1366 and the owner looked for it and did not find it.
- **Turning one on only offers.** It changes no client's scorecard,
  templates or goals (tested). Each piece is copied into the practice on
  first use and edited there. Edits never reach the catalog or another
  practice (tested).

## The shelves

1. **Session template.** "Start from the Operations Command Center" sits
   with the existing choices for a new strategy template, and on the module
   card. It is shown only while the module is on, and the API refuses it
   otherwise. Since 2026-11-12 it is the first start and the primary one, and
   the New template card is above Manage templates: second, in the third card
   down, it was below the fold at 1366.
   - It is the Operations example (version 2) in plain words: quarterly
     priorities, the weekly leadership meeting, second-in-command, owner, org
     chart, and the six areas (vision, people, data, issues, process,
     results).
   - It adds a merge field, `{Owner}`, for the person `{Visionary}` names.
   - The copy is made by `strategy.examples.create`, like the example.
2. **KPI library** (`apps/scorecard/library.py`). Every practice has the base
   library: four pages (Customers, Operations, Team, Money) and the 29
   entries asked for.
   - Each entry has a unit (kind), a direction, a default cadence, a roll-up,
     status-band guidance and suggested feeds.
   - A module adds its list on top. Operations adds six: first-time fix rate,
     schedule adherence, backlog in weeks of work, preventive maintenance
     done on time, quality escapes, and output per labor hour.
   - A practice adds its own entries (`kpi_library_entry`). "Edit for my
     practice" on a shipped entry makes the practice's own copy, which then
     stands in for it there.
   - "From the library" sits beside "Add a KPI" on every scorecard's setup
     card, and on the empty card. Picking an entry fills in the KPI form, and
     nothing is made until Save. The guidance goes on the tile's back, and
     the band becomes "Behind within (%)".
   - Existing KPIs are never touched.
3. **Playbooks.** A playbook is an outline: "Goal:", "Why:", "## project |
   weeks a-b", "- task | week n | owner, second-in-command or practice".
   - **Starting one.** "Start a playbook" is on a client company's page. It
     takes a start date (default next Monday) and names the client's owner
     and second-in-command from the company's contacts. It then makes the
     goal, its projects and their tasks:
     - a task is due on day 5 of its week;
     - a project runs from its first week to day 5 of its last;
     - the goal ends with the last project.
   - **What was started** is listed on the company's page, on the Playbooks
     card (2026-11-12): each run with its goal as a link, the start date and
     what it made; a run whose goal was deleted is listed without one.
     `GET /api/playbooks/?company=<id>` adds `runs`, for staff who can see
     that company (an associate only an assigned one); otherwise 404.
   - **Owners.** The person starting it owns every item. A task for the
     owner or the second-in-command carries that contact as its client
     owner. Each task's update source is `playbook`.
   - **Drafts.** Six shipped playbooks arrive as drafts, "Draft, edit before
     first use". A draft is not started until it is saved or marked ready.
   - **The six:** the 90-day operations reset, install the management
     cadence, owner steps away from the day to day, process mapping and SOP
     sprint, software consolidation, and a hiring round.
4. **Document and email templates.** A module's templates are added
   alongside the built-ins the first time a practice with it on opens
   Settings → Documents or Email templates.
   - They are marked with the module's name and are restorable.
   - Operations ships three document templates: an SOP (purpose, roles,
     steps, measures, review date), a weekly note and a quarterly review.
   - Every document template now downloads as Word (`…/docx/`).
   - Operations also ships one email template, "Weekly note (Operations)".
5. **Tools.** A placeholder. The card names the four coming tools: the
   bottleneck finder, the process map worksheet, the org chart builder, and
   the capacity and utilization calculator.
6. **Integrations.** The module names its recommended feeds: Sheets, Track,
   Besty, HubSpot, Google reviews and bank feeds.
   - With the module on, a tile's feed buttons show those first, in that
     order, after "Recommended:" (`/api/me` `recommended_feeds`).
   - Bank feeds feed the practice's books, not a KPI, so the card lists them
     but the feed picker can't.
7. **AI actions.** Three actions are in Settings → AI's Actions table, listed
   only while the module is on, and are also MCP prompts:
   - "Draft an SOP from a note" (Standard);
   - "Map rows from a meeting proposal" (Deep);
   - "Weekly note from the scorecard" (Standard).

## The practice library

`practice_library_record`: one record per source, with its structure pulled
out.

- **What it keeps:** notes (never a PIN-locked one, and a note locked later
  leaves), map rows accepted and discarded, finished documents (an SOP when
  made from an SOP template), and playbook runs.
- **When:** only while the practice has a Command Center on.
- **Nothing generates from it yet.** It is visible only as a count on
  Settings → Command Centers, where the practice owner can export it as JSON
  or delete it all.

## The site

"Discipline modules" is now "Command Centers" throughout the site:
- the pricing card;
- a new "Command Centers" section on /pricing, listing all eight;
- the "Coming next" row;
- the FAQ, with a new "What is a Command Center?";
- About;
- the demo form.

## Choices made where the brief was open

- **The catalog is a table with no editing screen yet.** A status changes by
  migration or the admin shell.
- **Billing reuses P4's add-on tables.** A module turned on is charged from
  the next 1st, the rest of the month included, as any add-on. The cap is a
  credit line rather than fewer lines.
- **The demo practice** is the platform owner's there, so it is never billed.
- **The session template's `{Owner}`** is a new merge field. The existing
  `{Visionary}` stays for the templates that already use it.
- **The weekly note** is shipped both as a document template (Word) and as
  an email template. The SOP and the quarterly review are document templates
  only.
- **The Operations KPI list and the four tools' names** were not given, so
  they are chosen above.
- **Playbook roles** map to people at start. The practice side is the person
  starting it; per-task reassignment is the ordinary task edit. There is no
  lead picker.
- **A draft playbook can't be started**, which is the literal reading of
  "edit before first use". The demo's is marked ready.
- **Playbooks are edited as an outline in a text box**, not a form per item.
- **The three AI actions have no in-app button yet.** Each is fixed to "In my
  AI app" and lands in an approval place where one exists:
  - map rows go into the session's tray;
  - the weekly note becomes a digest draft awaiting approval;
  - the SOP becomes a note marked as the AI app's. Notes have no approval
    queue.

  The MCP prompts are registered for every practice; the Actions table lists
  them only while the module is on.
- **The practice library records nothing while no Command Center is on.**
  Strategy templates themselves are not recorded, only the accepted and
  discarded rows.

## Proof

- `tests/test_command_centers.py` has 27 tests:
  - the catalog;
  - a line from the next 1st, and its removal;
  - four on billed at $150;
  - the owner's exemption;
  - the owner-only switch, a coming module refused, and the demo's refusal;
  - nothing of a client's changed by turning one on;
  - no EOS term in anything shipped, with a test that the check catches each
    term;
  - the template offered only when on;
  - copies kept apart between practices for playbooks and documents;
  - Word and restore;
  - the module's email template;
  - the library's pages, module entries, "From the library" to a saved KPI,
    and the practice's own entries;
  - outline reading;
  - start a playbook, with dates, owners and source checked;
  - the AI actions shown only when on;
  - the practice library recording, PIN exclusion, export and delete, and
    isolation;
  - `/api/me`.
- `tests/test_demo_seed.py` checks the demo practice has Operations on, a
  22-task reset started at Acme Fasteners, and three library KPIs there.
  Since 2026-11-12 also: each of the three has its target (95%, 3% or less,
  90%, from its guidance; the library entries carry none) and thirteen closed
  weeks of readings, so the tiles show Behind, On track and On track; the
  reset is Acme's first goal; and Acme's page lists it.
- **The demo walk (2026-11-12):** seven checks in headless Chrome at 1366, on
  a scratch database seeded by the real `seed_demo`, signed in as the seeded
  owner with every API answer real. Four had failed for the owner: the
  sidebar entry and the template start were there but below the fold, the
  reset was on no company page and fourth at Acme, and the library KPIs had
  no readings.
- `frontend/src/screens/Settings.test.tsx` covers the new Settings entry.
- Screenshots at 1366 and 390: Settings → Command Centers, the module card,
  the KPI library picker, and Start a playbook.
