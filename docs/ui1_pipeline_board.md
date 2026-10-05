# UI 1 — the Pipeline board, redesigned

**Spec · 2026-10-05 · frontend on `dev`, not released until the owner says so**

## 1. What changes

The board today is a bare list of names with "Move…" under each. It becomes a
board of cards with room around them.

**The card.** One contact, one card: white, 1px border, 8px corners, 12px
padding, 8px between cards. It shows, top to bottom:

- name (semibold)
- company
- primary email (the first one if none is marked primary)
- primary phone (same rule)
- the tag "also in Referral partners" when they sit in another pipeline

A line with nothing to show is left out; there are no dashes. **Job title comes
off the card**: it is not in the owner's list, and it is one click away on the
contact.

**Grabbing it.** The whole card is the handle. Grab cursor at rest; the card
lifts (shadow, border) on hover and press; while it is being dragged the card
left behind fades to a dashed outline, every column it could land in gets a
gray dashed outline, and the one under the pointer turns orange with a light
orange wash. The column it came from does not light up.

**Opening the contact.** A click anywhere on the card except the menu opens the
contact. The name stays a real link (not underlined) so the keyboard and
"open in new tab" still work.

**Moving without dragging.** The visible "Move…" is gone. Each card has a small
"…" button at its top right (always visible; 32px target) that opens a
two-item menu: **Move to another stage…** and **Open contact**. The menu works
by keyboard (Enter/Space opens, arrows move, Escape closes and returns focus)
and by touch, which matters because browser drag and drop does not work on
most phones and tablets.

**The move panel** is the same panel as today, with the same fields, wording
and warning. It now opens as a dialog over the board instead of as a card
below it, because below a full-height board it would be off screen.

## 2. Layout

- The board is as tall as the window allows (never under 420px). Each column
  scrolls on its own; its heading, count and hint stay pinned at the top.
- The board uses the full width of the area to the right of the sidebar, not
  the 1320px reading width the other screens keep *(owner, 2026-10-05, after
  seeing it use about half his screen)*. Columns are at least 300px and grow
  evenly to fill the space when the stages fit; when they do not, the board
  scrolls sideways, so every stage is reachable and none is cut off.
- Columns are light gray lanes, not cards (the design brief: a card never
  contains another card). An empty column says "No one here" and still accepts
  a drop.
- The explanatory text above the board is cut to one line.

## 3. Search on the board: recommended, and built

With 98 cards in one column, scrolling to find one person is the slow part. A
single "Find on this board" field above the columns filters the cards as you
type, on name, company, email and phone. While a search is on, each column's
count reads "3 of 98", and dragging and the menu work as usual.

*Owner, 2026-10-05: keep it, and make it cover contacts that are not loaded.*
The loaded cards narrow at once in the browser; a quarter of a second after
typing stops the same search runs on the server (`?q=` on the board endpoint,
the same four fields), so a match past a column's first 100 is found. Until
that answer is in, a column with cards not loaded says "Searching 43 more not
shown here…" rather than implying it has looked.

Filters (owner, contact type, tag) are **not** proposed now; the design brief
wants those as chips, and they belong with the Contacts filter bar when that is
reworked.


## 4. What does not change

- **Move rules.** A drop and the menu both end at the same
  `POST /api/contacts/:id/change-stage/` as today. A drop on a **lost** stage
  still opens the panel for a reason instead of moving. A drop on the same
  column does nothing. The won-stage warning in the panel is unchanged. Stage
  automations are server-side and untouched.
- **Who sees what.** The board endpoint's visibility rules are untouched.
- **No migration.** No model changes.
- **The Tasks board** shares some CSS class names with this one; the new
  styles are scoped to the Pipeline board so Tasks does not move.

## 5. Payload

The board payload already carries emails and phones. It does not carry the
company's name, only its id. The board endpoint adds one read-only field per
contact, `company_name` (empty string when there is no company), fetched in the
same query. The general contact serializer is not changed, so nothing else's
payload moves, the strategy goldens included.

Two things found while reading the endpoint, one fixed and one only surfaced:

- **Order.** Cards came back in no defined order. They now come back by last
  name, then first name.
- **The 100-card cap.** The endpoint returned at most 100 contacts per column
  while the count showed the true total, silently hiding the rest. A column
  still opens with its first 100, and now says "Showing 100 of 143" with a
  **Show more** button under the last card *(owner, 2026-10-05)*. Show more
  loads the rest of that column in one go (`?expand=<stage ids>` on the board
  endpoint) and stays in force until the pipeline is switched or the page is
  reloaded, including across a move. "The rest" is not paged: a column of
  several thousand would be one large response, which is not a Beta problem
  and is the thing to revisit if it becomes one.

Each column also returns `matched`, the number of its contacts that match the
search (equal to `count` when there is none), and the board returns the `q` it
answered, so the screen knows whether what it holds is the answer to what is
typed. Search and Show more go through the same visibility rule as the board.

## 6. Tests

- Frontend (`Pipeline.test.tsx`): the existing six behaviors kept (open by
  name, drop moves, same-column drop does nothing, lost opens the panel, the
  keyboard path, the won warning), reached through the menu where they used to
  use "Move…". New: the card shows company, email and phone; empty lines are
  left out with no dash; clicking the card opens the contact; clicking the menu
  does not; no visible "Move…" text; the "also in" tag; search narrows the
  cards and the count; Show more loads the rest of a long column; a search
  reaches a card that was not loaded, and says it is still searching until it
  has.
- Backend (`tests/test_pipelines.py`): `company_name` is on board contacts and
  empty without a company; cards are ordered by name; a long column is capped
  until expanded; search finds an unloaded card, matches each of the four
  fields, and stays inside what the role may see. The two existing board
  tests (one column per stage; a role sees only its own) are unchanged.
- Full backend and frontend suites green; v2 and v3 goldens untouched.

## 7. UI backlog (recorded, not built)

In the owner's words:

1. **Contacts and Companies:** no underlined name links, which look dated. The
   whole row is clickable and opens the contact or company.
2. **Notes:** each note is a card showing only its name and date. Show the
   latest twenty in a few columns without searching. A search shows every
   match. Add dropdown filters: company, contact, date, name.
3. **Top bar:** move settings and profile out of the bottom of the sidebar into
   a bar across the top, with the profile picture at the top right. Clicking it
   opens a dropdown with Settings and Profile. Settings shows the options that
   person's permissions allow. Profile is where they change personal
   information and their profile picture.

## 8. Roadmap (recorded, not built)

**Automation for each stage, offered when a card moves.** In the owner's words
(2026-10-05):

> Automation for each stage. For example, moving from Prospecting to Follow Up
> Needed automatically creates a calendar event where you can pick the time for
> a follow-up. Or moving from Prospecting to Qualified puts them in a new
> campaign that nurtures them. We would have to build out the automations and
> their copy. The idea is that moving a card gives a prompt: "Do you want to
> enroll them in X automation?" The user can decide right there, or enroll them
> later.

How it relates to what exists:

- **The Stage automations screen** (`/rules`) already runs rules when a contact
  enters a stage, with two actions: create a task, and draft an email into the
  Outbox. Those fire **silently and every time**, on the server, for every
  route into the stage (drag, menu, import, the contact page). This item
  differs in two ways: it adds **new kinds of action** (a calendar event, a
  campaign enrollment), and it makes them an **offer the person accepts,
  declines or defers** at the moment of the move, rather than something that
  just happens. The natural home is the same rules model with more action
  types and an "ask first" switch per rule, so there is one place that says
  what a stage does. Whether today's two actions also become askable is a
  decision for that spec. "Enroll them later" needs somewhere to wait: a
  declined-for-now offer that stays on the contact.
- **Campaigns** exist, but a campaign today is one marketing email written
  once and sent to many, each copy approved in the Outbox before it leaves. A
  contact can be enrolled in one, so the enrollment half is built. A campaign
  that *nurtures* (several emails over time) is not: the sequence, its timing
  and its copy are the new work, and the approve-before-send rule would apply
  to every step.
- **Google Calendar** is already a roadmap item (design brief: read
  appointments, create strategy sessions from events, drive session-related
  automation) and is not built. The calendar-event action **depends on it**:
  creating an event needs calendar write access, which is a new Google scope
  and its verification. The campaign half of this item does not depend on it
  and could ship first.
