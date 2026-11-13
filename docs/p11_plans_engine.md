# P11 — the plans engine, version one (as built, 2026-11-13)

One plan per client company, and one for the practice itself, in five
horizons: the three-year picture, this year's goals, this quarter's
priorities, this month's plan and this week's sprint. **It links what already
exists and replaces nothing.** Goals, projects, tasks and strategy maps work
as before; an item on the plan points at them.

**Available while the practice has any Command Center on** (P8). With none,
every plan route is 404 and the menus show nothing.

## The plan

- **Five horizons**, top to bottom. Each item serves the item above it, so the
  page reads both ways.
  - The default names are "Three-year picture", "This year's goals", "This
    quarter's priorities", "This month's plan" and "This week's sprint".
  - Each name is editable under Settings → Branding → Wording, beside the
    work words: one label each, one to three words, letters only. No digits,
    so the default is "Three-year picture", not "3-year".
  - **No EOS terms anywhere** (tested against the Command Centers' ban list).
- **Periods.**
  - The year and quarter follow the company's **fiscal-year start month**
    (`company.fiscal_year_start`, default January), set at the top of the
    Plan page by the practice.
  - The month is the calendar month.
  - The week starts on the company's **existing week start**: the
    scorecard's, or Monday when there is no scorecard.
  - The picture runs three years from the fiscal year it was set in.
  - Each horizon steps to an earlier or later period with ‹ and ›.
- **An item** has:
  - a title, an owner (someone at the practice or one of the company's portal
    users), a "done means" sentence and a status (on track, off track, done,
    dropped);
  - its period, and the item above it that it serves;
  - optional links to a goal, a project, tasks and KPIs. **A linked KPI shows
    its current status** (its latest reading, target and band, read as the
    person may see the scorecard).
- **The picture** holds a few statements, plus measurable targets with a
  target value and a linked KPI.
- **A year's item is one of the company's goals.** It is linked to an
  existing goal or, when none is named, a goal is made from its title (ending
  at the year's end).
  - The practice's own plan uses the practice's own goals, those with no
    company.
- **A week's sprint** is one item per week: a sprint goal sentence plus a
  selection of tasks. They are existing tasks, or new ones made with it (due
  at the week's end).

## The page

- **The Plan page:** `/companies/:id/plan`, `/plans/practice` for the
  practice, and `/plan` in the portal.
  - It is reached from the company page ("Plan for this client"), the
    Operations Command Center ("Plans"), Work ("Plans"; "Our plan" in the
    portal), and the new **Plans** entry in the staff menu.
  - **Plans** (`/plans`) lists the practice's own plan and each client's, each
    with its week at a glance.
- **Layout:** the five horizons side by side. At 860 px and narrower they are
  tabs, which open on the week.
- **Each item card** shows:
  - what it serves ("Serves: …") above;
  - its status, owner, done means and links: the goal and project as links,
    the KPIs with their status pills, and the tasks done of total;
  - what serves it ("Served by") below.
- **Close the week** walks the sprint's tasks: done, not done or carried over.
  - Each task's suggested outcome follows its status. **"Carried over" is
    never suggested;** it is always chosen.
  - A carried task joins next week's sprint, which is made with the same
    sentence when there is none yet.
  - Closing records the outcomes. **It changes no task.**
  - While last week's sprint is unclosed, the button reads "Close last week".
- **Close the month and Close the quarter** do the same for their items: a
  done item is marked done, and a carried one is copied into the next period
  with its links.
  - Then the dialog offers "Draft {next period} from sources".
- **Into the weekly digest draft.** A digest is drafted per person, so the
  short summary goes into the weekly drafts of the company's people:
  - a draft made after the close carries it, under "From the plan";
  - a draft already waiting is marked out of date, so its "Update" button
    re-renders it with the summary. It is never rewritten behind whoever may
    have edited it.

  A digest still needs something owed to exist: the summary rides along, it
  doesn't make one.

## Drafts from sources

- **"Draft from sources"** is on every horizon (on the week, only while it has
  no sprint). **"Break this down"** is on every item above the week, and
  proposes the items on the horizon beneath it.
- **Who and how:** the practice owner and associates. It runs on the
  practice's own key at the **Deep** tier, registered as the AI action
  `plan_draft` and listed while any Command Center is on.
  - **The price is said first:** "Draft with Claude (about $0.12)".
  - Each practice gets 20 a day, refused when the month's AI budget is spent,
    as the scorecard's buttons are.
- **Sources:** the company's
  - strategy sessions, with their accepted map rows;
  - SOPs: documents made from an SOP template, and unlocked notes an AI app
    saved as "SOP draft: …";
  - approved meeting proposals: actioned or partly actioned, with their
    summary and approved action items and deliverables;
  - the scorecard, the KPIs behind or off track first;
  - documents: title and the fields they were filled with;
  - pasted text, such as a notebook's summary.

  The practice's own plan draws on its scorecard and pasted text.
- **Never sources:** mail of any kind, a PIN-locked note (or any note but an
  unlocked SOP draft), and People data. A chosen source that isn't one of the
  company's is refused before Claude is called (tested: a locked note,
  another company's session, "mail").
- **The tray.** Claude's proposals land in the horizon's tray, each naming
  what it drew on. A person accepts, edits or discards each, as with map rows.
  Accepting a year proposal makes its goal.
  - **Accepts and discards go to the practice library** (`plan_item_accepted`
    / `plan_item_rejected`), while a Command Center is on.
- **From a strategy session.** When a session converts to goals, its
  Converted card offers to put its 30/60/90 rows on the plan as this
  quarter's priorities.
  - Each priority's title is the row's fix, its done means the row's
    measurable, and it links the row's KPI and the goal or project it became.
  - Each serves the year's item for that goal, which is put on the year when
    it isn't there.
  - Asking again for the same rows is refused.
- **A playbook started** on a company puts its goal on that plan's year
  (`centers.playbooks.start`).

## Who sees and edits

- **The practice:**
  - the practice owner, and an associate for an assigned company, edit
    everything, the practice's own plan included;
  - an assistant reads.
- **The portal**, for the client's own company only:
  - **the client owner and senior leadership** (a Senior leadership level on
    any team, or "leads all teams") see every horizon;
  - **everyone else** (managers, members, viewers) sees this month and this
    week. A month's or week's item shows only when it is the whole company's
    or one of their teams'.
- **The sprint's tasks** show a client only where Work would show them:
  - a member sees their own (P7-5);
  - anyone above a member, and the owner, sees every client-visible task.
- **The portal's This week** (`/plan/week`) shows:
  - the sprint goal and tasks done of total;
  - the person's own tasks: theirs as client owner, or assigned to them;
  - their team's tasks;
  - what the week serves, as far up as they may see.
- **Adding from the client side** follows Work's own levels.
  - Someone who may create tasks in Work may add to the month and week, and
    edit those items for their teams.
  - At the year and quarter, the client owner and senior leadership propose.
    The proposal waits in the practice's tray (shown to its proposer as
    "Waiting for the practice") until the practice accepts or discards it, as
    client goal proposals do.
- **Closing, drafting and the tray** are the practice's.

## Elsewhere

- **Home:** each client's card shows the week at a glance: the sprint goal,
  tasks done of total, and how many current items are off track.
- **MCP**, two tools:
  - `company_plan(company_id, horizon)` reads a company's plan by horizon,
    for the practice's people;
  - `propose_plan_items(company_id, horizon, items)` puts items in the tray,
    marked as made by an AI app, for the practice owner and associates.

  Both reach only companies the person reaches. Neither reads People data.

## Data (migrations, additive)

- **`plans 0001`:**
  - `plan_item`: horizon, period start, title, done means, status, owner, the
    item it serves, goal, project, team, target, position, state (proposed,
    accepted, discarded), source, `drew_on`, the AI call, from an AI app,
    proposed by, decided by and when;
  - `plan_item_task` and `plan_item_kpi`;
  - `plan_close`: one per company, horizon and period, with each outcome and
    the summary.
- **`crm 0058`:** `company.fiscal_year_start`, default 1.
- **`centers 0003`:** two library kinds (choices only, no SQL).
- **Words:** the horizon names live in `tenant.work_words["horizons"]`, only
  where changed. No migration.

## Choices made where the brief was open

1. **The fiscal-year start is the company's own column**, set by the
   practice on the Plan page.
2. **One sprint a week**, not several. A second is refused; tasks are added
   to the first.
3. **A member's This week shows their team's sprint tasks only where Work
   already shows them,** which for a member is their own (P7-5). Managers
   and above see the team's. Say if members should see their teammates'
   sprint tasks.
4. **Viewers see the month and the week** (read only), like members.
5. **Client adding at the month and week = may create tasks in Work.**
   Clients don't close periods.
6. **The picture is the practice's to set.** Client proposals are at the year
   and quarter only.
7. **Closing never changes a task's status.** It records what became of each
   one.
8. **The summary reaches existing drafts by marking them out of date,** not by
   editing them.
9. **"Documents" as a source** are titles and filled-in fields (a document
   keeps no body). Other notes are not sources; only unlocked SOP drafts are.
10. **Break this down** is not offered on the week: a sprint breaks into its
    tasks.
11. **The practice's plan uses the practice's own goals** (no company). The
    MCP tools cover client companies only.
12. **An assistant reads plans** and edits nothing.
13. **The 30/60/90 offer** is made once, on the Converted card right after
    conversion. All three horizons go into the current quarter.
14. **Plans** got a staff menu entry, under Operations, as well as the links
    asked for.
15. **Home's week at a glance is a block of its own,** "This week, by
    client". Since 2026-11-13 it sits first, above Getting started and the
    notices, and is not one of the arranged panels. It is hidden while no
    client has a plan. The client cards in the Clients panel carry the same
    line.
16. **A horizon's tray sits under its items,** with "N proposed, waiting
    below" at the top of the column.

## Proof

- **`tests/test_plans.py`** has 38 tests, run against the real API:
  - practice isolation (another practice, an unassigned associate, a client of
    another company, no Command Center);
  - horizons by level in the portal (owner, senior leadership, leads all;
    member, manager, viewer) and the team filter;
  - the sprint's tasks only where Work shows them, and This week;
  - client proposals at the year and quarter, accepted by the practice, a
    year's becoming a goal;
  - client adding by Work's rule;
  - close the week: suggestions, nothing carried by itself, carried when
    chosen, closed once;
  - a month close carrying an item and offering a draft;
  - the summary in the weekly digest draft (stale flag and render);
  - the cascade: goals (and another company's refused), what an item serves
    and what serves it, the horizon-above rule, KPI status, one sprint a week;
  - drafts with a fake Claude:
    - the price first, and only this company's sources, without a locked note;
    - proposals naming their sources, the Deep model, no locked note's text
      sent;
    - accept and discard into the library;
    - the excluded sources refused before any call;
    - Break this down;
    - only the practice drafts;
  - the MCP tools' scope;
  - a playbook's goal on the year;
  - a session's 30/60/90 rows as the quarter's priorities;
  - Home's glance and the Plans index;
  - the horizon words;
  - the fiscal year;
  - no EOS term.
- **`frontend/src/screens/Plan.test.tsx`** has 8 tests:
  - five horizons side by side with serves and served-by;
  - the tray with its sources, and Accept;
  - the draft's price first and the sources sent;
  - the close walk with nothing carried unless chosen;
  - a member's month and week only;
  - the owner proposing at the quarter;
  - This week;
  - the horizon names saved.
- **`tests/test_demo_seed.py`** checks Acme's plan through the real API, as
  the owner, Wiley (the client owner) and Marvin (a team member), plus
  Summit's own plan and Home.

- **The walk (2026-11-13), as Bryan will see it:**
  - **Setup:**
    - a scratch database (`execsnowhq_plan_walk`) seeded by the real
      `seed_demo`;
    - the built bundle served by Django on 8199;
    - real Django sessions for the seeded owner, Wiley Coyote (Acme's client
      owner) and Marvin Martian (an Acme team member);
    - no canned API answers.
  - **The checklist** was walked in headless Chrome at 1366×768 and 390×844.
    **51 of 53 checks passed.** The two that did not were Home's "This week,
    by client" panel at both sizes:
    - it is the first block under the tiles;
    - on the demo, the Getting started card and the notices sit above it, so
      it is one scroll down (992 px at 1366).
  - **Fixed during the walk:**
    - the fifth column ran off the right edge at 1366;
    - a long "Serves" line wrapped to four lines on every card;
    - the tray pushed the quarter's KPI pill below the fold. It now sits
      under the items, with "1 proposed, waiting below" at the top of the
      column;
    - the horizon names were at the bottom of Settings. "Rename the horizons"
      on the Plan page now goes straight to them;
    - a phone opened Summit's plan on an empty week. It now opens on the
      lowest horizon with something on it;
    - Marvin had no task of his own in the sprint.

## The demo

- **Acme Fasteners**, tied to the 90-day operations reset and the scorecard:
  - **the picture:** two statements and two targets, on Scrap rate and
    On-time completion rate;
  - **the year:** the reset's goal (from the playbook) and two of Acme's
    goals;
  - **the quarter:** three priorities, one per stage of the reset still to
    come, each linking its project and KPIs, plus Wiley's proposal waiting
    in the tray;
  - **the month:** three items, one off track;
  - **last week's sprint**, closed on Monday, with its unfinished task carried
    over;
  - **this week's sprint** under way.
- **Summit itself:** a picture, two goals of its own for the year, a
  quarter's priority and a month's item.
- **No Claude in the seed.**

## Not in version one

- Reordering items by dragging.
- Comments on an item.
- A plan PDF.
- Notifications when an item changes.
- Clients closing a period.
- A draft that reads the whole map of every session at once.
