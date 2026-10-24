# KPI Scorecard (M5) Spec

Oct 21, 2026 · @Bryan

## What it is

A scorecard inside the client portal: the handful of numbers a company runs on, shown as tiles the team looks at every week, under the practice's brand, in the portal they already sign into. The practice builds it on the company's page; the client's team reads it, and the people allowed to can type the week's numbers in. Numbers are typed in at first; a Google Sheet, HubSpot and other systems feed them later without changing anything the reader sees.

It replaces the chain one client runs today (a spreadsheet for input, Data Studio for charts, a Google Site to show them) with one page, and it is standard for every practice, not built for one client.

**Who does what**

| Person | Does |
| --- | --- |
| Practice owner or associate | Defines KPIs, cadence, targets, who may enter readings, who may see what; builds bonus plans; sees everything |
| Practice assistant | Sees the scorecard, enters readings when named as a KPI's owner, changes nothing else |
| Client owner | Sees every KPI and every bonus; may enter any reading; may be given the right to edit KPIs later |
| Senior leadership (client) | Sees every KPI; enters readings where named; sees bonuses only when granted |
| Manager (client) | Sees company-wide KPIs and the team's; sees own team's bonus progress |
| Member (client) | Sees company-wide KPIs and their own row on per-person KPIs; enters readings where named |
| Viewer (client) | Looks, changes nothing, as everywhere in the portal |

**What it is not.** Not a BI tool: no free formulas, no pivot tables, no drag-and-drop dashboards. A curated set of KPIs with a few tile shapes done well, which is what a weekly leadership meeting needs and what Data Studio makes tedious.

## Decisions for Bryan

Decided by Bryan on October 21, 2026. Items 3, 7 and 10 changed from the recommendation; the rest stand as recommended.

1. **One scorecard per company, with named pages.** A company has one scorecard split into pages the practice names ("Weekly scorecard", "Sales", "Bonus"). Each page has its own audience. Decided.
2. **KPIs are separate from goals, with a link.** Goals are about future actions; KPIs show what already happened. A goal can point at a KPI and show its latest reading. Decided.
3. **Cadence for entering, any window for viewing.** Each KPI is daily, weekly, monthly or quarterly for its readings; months are calendar months, and the week start is a setting per company, Monday to Sunday by default with Sunday to Saturday available. The scorecard view has a window control: This week, This month, This quarter, Year to date, Last year, or custom dates on a calendar. Readings roll up over the window by a rule on the KPI: Sum, Average or Last. Decided, with the window control added.
4. **Who enters a reading.** Each KPI has a named reading owner who gets the reminder; the client owner and senior leadership can enter any reading; practice owners and associates always can. Decided.
5. **Status bands.** Within 10% short is Behind, worse is Off track, at or past target is On track, flipped for lower-is-better; defaults per KPI, editable. Decided.
6. **Audiences, four kinds.** Everyone at the company; Senior leadership and up; one team; Each person sees their own. Practice users always see everything. Decided.
7. **Bonus visibility by level.** A person always sees their own; a manager sees their own and their team's; senior leadership and the client owner see everyone's on every team. No separate grant. Decided, changed from a named grant.
8. **Bonus plans show, they don't pay.** The plan computes achievement and the amount earned so far; nothing flows into finance, payroll or invoices. When a period closes, the owner sees one list of people and the dollar amount each earned, and downloads it as a spreadsheet, so whoever runs payroll keys it in from the sheet or the screen. Decided.
9. **Leaderboard as a toggle per KPI**, off by default, on for the teams that want it (call centers will). Decided.
10. **Feeds in this order:** by hand first; Google Sheets second, with a cell mode for messy sheets; Track PMS third; HubSpot fourth; Besty.ai fifth; others as needed. Sheets reads through the practice's Google connection. Decided.

## A KPI

A KPI is a definition; its numbers are readings, one per period. Defining one takes under a minute on the company's page.

| Field | What it holds | Example |
| --- | --- | --- |
| Name | What it measures, in the company's words | Occupancy |
| Kind | Number, Percent, Money, Count, Duration, Rating | Percent |
| Direction | Higher is better, Lower is better, or Within a range | Higher |
| Cadence | Daily, Weekly, Monthly, Quarterly: how often a reading is entered | Weekly |
| Roll-up | How readings combine over a longer window: Sum, Average, Last | Average |
| Target | A fixed value, or a value per period for seasonal KPIs | 82%, or a table by month |
| Range | For "within a range": low and high | 48–72 hours |
| Status bands | How far short counts as Behind and Off track | Defaults from decision 5 |
| Reading owner | Who is asked for the number when a period closes | A named portal or practice user |
| Per person | Off, or on with the people it tracks, and whether a leaderboard is shown | On: the five guest-services agents, leaderboard off |
| Feed | By hand now; Google Sheet, Track, HubSpot and others later | By hand |
| Tile | Which shape the scorecard shows it as (next section) | Number with trend |
| Page and audience | Which scorecard page it sits on and who may see it | Weekly scorecard · Everyone at the company |
| Note | One line on how it's measured, shown on the tile's back | "Booked nights ÷ available nights, from the PMS report" |
| Strategy component | Optional: which of the six it serves | Operations |

KPIs can be reordered on a page by drag, archived (readings kept, tile gone) and restored. A KPI with a per-person switch holds one reading per person per period, plus a company total the tile can show (sum or average, chosen on the KPI).

**Computed KPIs**, one step only: a KPI can be the sum, difference, ratio or average of two other KPIs on the same cadence ("Revenue per booking" = Revenue ÷ Bookings). No formulas beyond that; anything cleverer belongs in the source system.

## Readings and entering them by hand

Entering a week's numbers takes one screen and about a minute, which is the bar: if it's slower than the spreadsheet, people go back to the spreadsheet.

**The entry screen.** "Enter readings" on the scorecard opens one form for the period: every KPI the person is allowed to enter, in page order, each a single field with the unit shown, last period's value beside it for sanity, and a Save at the bottom. Per-person KPIs show one field per person the entrant covers (a member sees their own; a manager, their team; the owner, everyone). Readings can be entered for the current period and for past periods; a future period is refused. Weekly periods follow the company's week start (Monday by default, Sunday if the company works that way).

**One value per period.** Saving again replaces the value and keeps the old one in the reading's history with who changed it and when. A tile shows a small "edited" mark for a changed reading, and the history is one click away for anyone who can enter readings.

**Missing readings.** When a period closes without a value, the KPI's reading owner gets one reminder (in-app notice, and in the next digest), and the tile shows the last known value greyed with "No reading for last week" rather than a false zero. Status is not computed from a missing reading; it holds at the last one.

**Bulk entry.** A table view, periods across, KPIs down, for catching up on several weeks at once; the same rules apply. This is also the shape a CSV paste will take when feeds arrive.

**Units and formats.** Money in the practice's currency, percent typed as 82 not 0.82, durations as hours or minutes per the KPI, ratings out of 5 or 10. The field refuses the wrong shape and says why.

**Who sees the entry button.** Only people who are a reading owner for at least one KPI, plus the client owner, senior leadership and practice staff. A Viewer never sees it.

## The scorecard page and the tiles

The page is a grid of tiles in the portal's card style, in the practice's brand colors, readable from across a room. It has to look like the third screenshot, not like a spreadsheet chart, and that is a design job done before CC builds it: a mock-up of the page, the tiles and the bonus view, approved first, as the strategy PDF was.

**Layout.** Pages as tabs across the top (Weekly scorecard · Sales · Bonus); a window control (This week, This month, This quarter, Year to date, Last year, or custom dates on a calendar; tiles roll readings up over the window by each KPI's roll-up rule, and the sparkline shows the periods inside it); "Enter readings" at the right for people who may. Tiles sit three across on a desktop, two on a tablet, one on a phone, in the order the practice set. Each tile: the KPI's name, the latest value large, the target small beside it, a status pill, the period it's for, and the shape chosen for it. The back of a tile (one click) shows the measurement note, the last 13 readings and who entered the latest.

**Three views of the same KPIs.** Tiles (the default); Grid, the classic weekly scorecard, KPIs down and the last 13 periods across with each cell colored by status, which is what a leadership meeting walks through; and Meeting, a full-screen tiles view with larger type for a TV or a shared screen, cycling pages if asked.

**The standard tiles**

| Tile | Shows | Best for |
| --- | --- | --- |
| Number with trend | The value, an up or down arrow against last period, a 13-period sparkline, the target | Most KPIs |
| Gauge | A half-dial from 0 to target or range, the value as the needle, status color | Percent and rating KPIs |
| Progress | A bar toward a target with the shortfall or surplus in words ("$12,400 to go") | Money and count KPIs with a period goal |
| Bars by period | The last 13 periods as bars, the target as a line across | KPIs that move week to week |
| Line | The last 13 or 52 periods as a line with the target band | Slow-moving KPIs, seasonal ones with a target per period |
| Status | Just the name and the pill, with the value small | Pages with many KPIs; the grid view's cousin |
| Leaderboard | Per-person KPIs: each person's value, ranked, with the target | Sales and service teams that want it (off by default) |
| My row | Per-person KPIs: the viewer's own value, trend and target, nothing about anyone else | What a member sees on a per-person KPI |

**Status colors** follow the app's existing pills (the strategy PDF's Strong / Watch / Fix): green, amber, red, with the words always beside the color. Brand colors carry the chrome and the charts; status colors are reserved for status so they mean one thing.

**Empty and new.** A company with no KPIs yet sees a short "Start the scorecard" card for the practice with three suggested starting KPIs by discipline (operations, sales, finance), each one click to create and edit. A tile with no readings yet says so instead of drawing nothing.

## Who sees what

Audiences reuse the levels and teams already set on the company's Teams card; nothing new to administer. A page has an audience, and a KPI can narrow it further but never widen it.

| Audience | Who sees the KPI | Typical use |
| --- | --- | --- |
| Everyone at the company | Every portal user of the company, Viewers included | The weekly scorecard |
| Senior leadership and up | Senior leadership and the client owner | Cash, margin, payroll |
| A team | That team's members and manager, plus senior leadership and the owner | A sales team's pipeline numbers |
| Each person sees their own | Each tracked person sees their own row; their manager sees the team's rows; senior leadership and the owner see all | Per-person targets, bonus components |

Practice owners and associates see every KPI of every client they're assigned to; assistants see the scorecard but no bonus amounts.

**Rules that hold everywhere**

- A page a person can't see isn't listed for them; a KPI they can't see isn't on the page, and the API refuses it, not just the screen.
- A per-person KPI never leaks a colleague's value to a member, including in the sparkline, the company total's breakdown, or the entry form.
- Bonus amounts follow decision 7: a person sees their own; a manager sees their team's; senior leadership and the client owner see everyone's.
- Changing someone's level or team on the Teams card changes what they see on the scorecard at once; nothing is copied.
- Activity records who created, changed, archived a KPI or a bonus plan, and who granted bonus visibility, as it does for team changes.

## Per-person KPIs and bonus plans

A bonus plan turns a few per-person KPIs into one number a person can check any day: what they've earned so far this period and what it takes to earn the rest.

**A plan** belongs to a company and names: the period (monthly or quarterly), the people on it, the bonus amount per person for a full period (one amount for all, or per person), and two to five components. Each component is a per-person KPI with a weight, so the weights add to 100%. Each component has a tier table:

| Achievement of target | Share of this component's bonus |
| --- | --- |
| Under 80% | 0% |
| 80% to under 100% | 50% |
| 100% to under 110% | 100% |
| 110% and over | 120% |

The table is editable per component, and a plan can use a straight line instead of tiers (achievement % = share %, capped). Earned so far = bonus amount × Σ (weight × share for that component's achievement to date). Achievement to date uses the readings in the period so far against the target prorated to the same point, so a person mid-month sees a fair number, not a scary one.

**My bonus**, the view a member sees: the period and days left; earned so far, large; the full-period amount; then one line per component with its weight, their value, the target, achievement and the share earned, with a plain sentence of what reaches the next tier ("4 more five-star reviews this month moves Reviews to 100%"). Nothing about anyone else.

**Team bonus**, the view a manager sees: a row per person with achievement % per component and overall; with dollar amounts, since a manager sees their own team's bonuses (decision 7).

**All bonuses**, the view for senior leadership and the client owner: every person, every plan, with totals per plan for the period. Once the period closes, a Payroll list: one row per person with the plan, the period and the amount earned, on screen and as a spreadsheet download (a second sheet carries the readings and tiers it was computed from), so whoever runs payroll keys it in from either.

**Rules.** A plan's readings and targets are frozen when the period closes; a later correction to a reading reopens that period's amounts only with the client owner's confirmation, and the change is recorded. A person added mid-period is prorated by days. Plans can be copied forward to the next period in one click.

## Feeds, built after the manual version

A feed is where a KPI's readings come from. By hand is a feed. The shape is fixed now so that adding a source later touches nothing a reader sees: every feed produces readings of the same kind (KPI, period, person if any, value, source, fetched at), and a KPI can switch feeds without losing history.

| Feed | How it connects | What the practice sets up | Order |
| --- | --- | --- | --- |
| By hand | The entry screen | Nothing | Part 1 |
| Google Sheet | The practice's Google connection with one added read-only Sheets permission; the client shares the sheet with that account | Column mode: the tab, the date column, the value column, and for per-person KPIs the name column matched to portal users. Cell mode: the one cell that holds the current value, snapshotted each period. Hourly or daily refresh | Part 3 |
| CSV paste | The bulk-entry table accepts pasted rows | Nothing | Part 3 |
| Track PMS | Track's API, per company, key stored encrypted | Pick a report: occupancy, ADR, RevPAR, bookings, revenue, reviews, by property or total | Part 4 |
| HubSpot | A private app token, per company, stored encrypted | Pick a report: deals created, won, pipeline value by stage, calls logged, per rep or total | Part 5 |
| Besty.ai | Its API, per company, key stored encrypted | Guest-messaging measures: response time, conversations handled, per agent or total | Part 6 |
| Others (QuickBooks, another PMS) | Each a small adapter, added as clients need them | Per adapter | Later |

**How a feed behaves.** It runs on the worker on its schedule and writes readings for closed periods, never overwriting a reading someone entered by hand (the hand value wins and is marked). A reading from a feed shows the source on the tile's back. A feed that fails leaves the last readings in place and tells the reading owner once, with what went wrong in plain words ("The sheet 'Weekly numbers' has no column called Occupancy"). A feed never deletes readings.

**The Sheets mapping** is the part to get right, because it is the one clients will use first, and most sheets are a mess of unrelated data. Column mode shows a preview of the tab's first rows; the practice clicks the date column and the value column, and the preview shows which readings would be created for which periods before anything is saved. Cell mode is for the dashboard-style sheet where this week's number is always in the same cell: the practice clicks that cell, and the app reads it at each period's close and stores it as that period's reading. Neither mode needs the sheet cleaned up. The Google verification scope list grows by one (spreadsheets.readonly), which goes into the next verification submission.

## How it ties into the rest of the app

- **Goals.** A goal can show a KPI's latest reading and status on its card and in the portal, by link (decision 2). The strategy map's 30/60/90 moves can name the KPI they're meant to move.
- **Strategy components.** A KPI can be tagged with one of the six components, so the scorecard can be grouped by component and the next strategy session starts from what the numbers say.
- **Digests.** The client digest gets a Scorecard section: the period's readings, status changes since last time, and missing readings, within the audience rules, so a member's digest never carries a colleague's row.
- **Tasks.** From a tile, "Make a task" creates a task that references the KPI; a KPI that has been Off track for three periods offers it unprompted.
- **Meeting queue.** A meeting's notes that mention a KPI by name can propose a reading ("occupancy was 78% last week") for someone to confirm, a later pass.
- **Claude.** "Explain this scorecard" (a short read of what moved and why it might have, from the readings and notes, with the usual estimate wording) and "Draft the weekly note" for the meeting; both after part 1, both using the practice's key, and both silent on bonus amounts.
- **Wording.** The words "KPI" and "Scorecard" join the Wording settings, since some practices will say "metrics" or "numbers".

## Build order

Four parts, each reviewed on the demo before the next, after the billing module's part 5.

| Part | Builds | Proves |
| --- | --- | --- |
| 0, design | A mock-up of the scorecard page, the tiles, the grid view and the My bonus view, in a practice's brand, approved before code | The look, so CC builds to a picture |
| 1, manual | KPIs with roll-up, pages, audiences, the window control, readings by hand with history and reminders, per-person readings, the eight tiles, the three views, the empty state, Activity, the Wording entries | A practice sets up a client's scorecard and the team enters a week's numbers in a minute |
| 2, bonus | Bonus plans, tiers, My bonus, Team bonus, All bonuses by level, the period close and download | A member sees their bonus; a manager their team's; the owner all |
| 3, Sheets | The Google Sheet feed in column and cell modes with the mapping preview, CSV paste, the Sheets scope on the Google client | A client's existing sheet drives the tiles with no retyping and no cleanup |
| 4, Track | The Track PMS feed with its standard reports | Occupancy and revenue arrive from the PMS |
| 5, HubSpot | The HubSpot feed with a handful of reports, per rep and total | Sales numbers arrive without a sheet |
| 6, Besty | The Besty.ai feed | Guest-messaging numbers per agent |
| Later | The practice's own scorecard (its pipeline, billable hours, cash) on the same tables |  |

Migrations are additive throughout (new tables for KPIs, pages, readings, feeds, plans, components, grants). The demo seed gets a Summit scorecard for one client with 13 weeks of readings and a bonus plan, so visitors see a real one.

## Open questions and what's left out

- [x] A scorecard for the practice itself: a later phase, after the client scorecards (decided October 21).
- [ ] Period targets for seasonal KPIs: a table by month in part 1, or a fixed target only until a client asks? Recommended: in part 1, since occupancy-style KPIs are seasonal from day one.
- [ ] Does the client owner get to create and edit KPIs, or only the practice? Recommended: practice only to start, with the right grantable later.
- [ ] The three suggested starter KPIs per discipline: which ones, in your words. The mock-up will propose a set.

**Left out on purpose:** free formulas and pivot tables; forecasting on KPIs (M2 forecasts cash, not KPIs); alerts by text message; public or shareable scorecard links; a second currency; anything that pays a bonus rather than showing it.

## Decided October 21, 2026, after the mock-up

- Seasonal targets (a target per month) are in part 1.
- Only the practice creates and edits KPIs to start; the client owner's right to do so comes later as a grant.
- Starter KPIs offered on an empty scorecard, three per discipline: Operations: On-time delivery %, Cycle time (days), Overtime hours. Sales: New leads, Proposals sent, Close rate %. Finance: Cash on hand, Days sales outstanding, Gross margin %. Service: Response time (minutes), Customer rating, First-contact resolution %.
- Week start is a setting per company: Monday to Sunday by default, Sunday to Saturday available.
- The bonus payroll list: on screen and as a spreadsheet, one row per person with the amount earned for the closed period.
- The approved mock-up is in docs/design/kpi_scorecard/: Main (tiles view as a manager), Grid (13 weeks), Entry (enter readings), Bonus (My bonus as a member; part 2). Build part 1 to it: same layout, tiles, spacing and status colors; the practice's brand colors where the mock uses Summit's green and gold; the app's own UI font rather than the mock's.

## Part 2 as built (October 22, 2026)

Choices the spec left open, made in the build, for Bryan to confirm or change:

- **A plan is one period.** "Copy forward" makes the next period's plan with the same people, amounts, components, weights, targets and tiers; earlier periods are the earlier plans of the same series. Someone who left part-way is not copied.
- **A week belongs to the month it starts in** when a weekly KPI feeds a monthly plan; a quarterly KPI can't feed a monthly plan.
- **A component's period target** is the plan's own when one is typed, else what the KPI's targets add up to over the period (summed KPIs) or their average (averaged ones). A KPI judged within a range can't be a component.
- **Averaged KPIs aren't prorated**: an average doesn't build up over a month, so mid-month it is judged against the target as it stands.
- **The straight line caps at 120% by default**, matching the default table's top tier; the cap is editable per plan.
- **Closing** is for the practice owner, associates and the client owner, once the period's last day is over. Confirming a recompute after a correction is the client owner's alone.
- **Assistants** see the bonus tables with achievement and no dollar amounts.
- **The spreadsheet** is an .xlsx with two sheets, "Payroll" and "Readings and tiers", written without a new dependency.

## Part 3 as built (October 24, 2026)

The Google Sheet feed and CSV paste, built to "Feeds" above. Choices the spec left open, made in the build, for Bryan to confirm or change:

- **Setting a feed up** is on the tile: Details, then "Feed from a sheet" (practice owner and associates, as for the rest of setup). The spreadsheet is picked by pasting its address, then its tab from a list; listing a person's spreadsheets would need Drive's permission, and the Sheets permission alone can't.
- **A column is remembered by its heading and its letter.** It is found by its heading, so a column inserted in the sheet moves nothing; a heading that disappears fails the read with its name ("The sheet 'Weekly numbers' (tab 'Data') has no column called Occupancy"). The heading row is found by itself (the first of the top 20 rows with two words in it and a date below) and can be changed on the screen.
- **What a row must hold:** a date in the date column (typed as people type them: 10/19/2026, 2026-10-19, Oct 19, 2026, October 2026, Q4 2026, "Week of 10/19/2026", or a spreadsheet's day number) and a number in the value column ($1,234, (1,200), 82%, 3.5 hrs). Blank rows are skipped silently; a row with words where the date or number should be is listed in the preview as left out, and why. The number is checked against the KPI's kind as a typed one is.
- **Several rows in one period** (daily rows feeding a weekly KPI) combine by the KPI's roll-up: summed, averaged, or the last.
- **Per person:** the name column is matched to the people the KPI tracks by full name, email, or a first name only one of them has; names that match no one are listed in the preview, where each can be pointed at a person or left out.
- **Cell mode** reads its cell at each period's close: the first read after a period has ended stores that period's reading, and it is not changed by later reads. A period that had already closed when the feed was set up is not given the cell's number. Consequence to know: a client who types last week's number on Monday morning, after the close, has it read before they type it if the feed reads at midnight; column mode does not have this problem.
- **Updates:** a feed's own reading follows the sheet when the sheet's number changes (the history keeps every value); one typed by hand is never touched, and a feed's reading corrected by hand becomes a hand reading from then on. A feed never deletes.
- **A failed read** keeps every reading and shows the reading owner one notice ("Occupancy's sheet couldn't be read", with the reason), on the scorecard, until a read succeeds; the practice sees the reason on the tile's back. It is not emailed or put in a digest.
- **The schedule** is one hourly job per practice (`scorecard.read_feeds`); a daily feed is read when its last read is 23 hours old, and a cell feed as soon as a period has closed without its reading.
- **CSV paste:** rows copied from a spreadsheet or a CSV file can be pasted into any cell of the catch-up table. A row starting with a KPI's name goes to that KPI; a heading row of period labels places the columns; otherwise the values fill right and down from the cell.
- **The demo** never reads a Google account, so its feed screen says so; CSV paste works there.

## Part 4 as built (October 24, 2026): Track PMS

Built to Track's public API reference (developer.trackhs.com, read on 10/24), not against a live account. `apps/scorecard/track.py` holds the client and the arithmetic; `views_track.py` the routes under `/api/scorecard/track/`.

- **The connection** is on the company page (Track PMS), the practice owner's only: the Track address, the API key and the secret. Key and secret are encrypted with the environment's key on the connection's own row (`track_connection`), not in `tenant_secret`, which holds one secret of a kind per practice; nobody sees them again, only the key's last four. Test connection makes one read-only call (`GET /pms/units?size=1&isActive=1`).
- **A KPI's Track measure** is set from its tile (Details, "Feed from Track"), by the practice owner or an associate: a measure from the fixed menu, for the total, one property, or (work orders) one Track user. The KPI's kind must fit (occupancy a Percent, revenue Money, counts a Count or Number). A per-person KPI is refused. A KPI has one feed: choosing Track stops its sheet, and the reverse, the readings kept.
- **The numbers, per closed period:** nights booked are the nights of non-cancelled, non-held stays inside the period; revenue is each stay's gross rent spread evenly over its nights; ADR is revenue over nights; occupancy is nights over active units times days; RevPAR is revenue over the same. Bookings created counts stays booked in the period. Reviews are dated by their first review's created (else submitted) time; the average is of `overAllRating`. Work orders: open and overdue at the period's end (overdue: past `scheduledAt`), closed in it, average days from received to closed; cancelled ones never count.
- **On the worker**, on the hourly feed pass, each Track measure is worked out once a day: the last two closed periods (so late changes in Track follow), and the last 13 the first time. Same rules as Sheets: a reading typed by hand is kept, nothing is deleted, a failure keeps the readings and tells the reading owner once, the tile's back says where it came from.
- **Rate limit:** Track allows 10,000 requests in five minutes per IP; one read uses at most 2,000 of them per five minutes and stops in words if that is nearly used, waits on a 429 for its Retry-After (60 s if none) up to three times.
- **Unverified until a real account answers:** every field name and value shape (fixtures are built from the reference, `tests/fixtures/track/`); whether an account's key is a "server key" with PMS access; what Track answers when the rate limit is reached; maintenance `scheduledAt` (a sort column in the reference, not in its response schema), so maintenance "overdue" may read 0; work orders' `userId` as the assignee (the reference also has an undocumented `assignees` list), and assignees are shown by Track user number because no users list is documented; reviews' dates (the reference warns `createdAt` is the checkout date).
- **The demo** never connects to Track.

