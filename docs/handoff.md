# Execs NOW HQ — handoff to the next chat

Written 2026-10-03, replacing the 2026-09-22 version; **last updated
2026-10-28 UTC**, after Release 26. **The next session starts at
"2026-10-28: Release 26, the scorecard's feeds and targets" just below**,
then "2026-10-27, late: Release 25, and where things stand", which sums up
everything from Release 23 to 25; the dated sections after it have the
detail. Then "2026-10-26: Release 23, and M5 part 5", "2026-10-24: catch-up
reach, and M5 part 3", "2026-10-23: Release 22", "2026-10-22: Release 21,
and M5 part 2", "Where things stand (2026-10-21)", and the older days in
order. Everything from "Next" down was last brought up to date on 10/5;
where it and a newer section disagree, the newer holds. Upload this at the
start of the next chat with: "Read this handoff, then pick up where it
leaves off." The specs in `docs/` are the source of truth; this covers what
they don't, and what changed since 9/30.

## 2026-10-28: Release 26, the scorecard's feeds and targets

- **Release 26 is live**: `main` at `606e0aa`, three additive migrations
  (`scorecard 0008`–`0010`) applied by the runbook in the waiting worker,
  all OK; no new scheduled job; web came up by itself; push to worker
  running 4 min 51 s. Runbook, "Observed at Release 26". `dev` is ahead of
  `main` only by this write-up.
- **Feeds read the open period so far** (`fdaa764`): Sheet, Track, HubSpot
  and app feeds each have "Also read the current period as it goes", on by
  default for a Last or Average KPI and off for a Sum. The open period gets
  a provisional reading, replaced at each refresh, marked "so far" on tiles
  and grids and never prompting the missing-reading reminder; after the
  close `feeds.finalise` (in `scorecard.read_feeds`) makes the last value
  final. A number typed by hand still wins. The tile's front shows the open
  period; Details lists the closed ones below it. **On production this
  turns on for existing Last and Average feeds at their next refresh.**
- **A new cadence re-fits readings** (`readings.refit`): each reading lands
  in the period holding its date (a quarter-end date in that quarter),
  readings sharing a period combine by the KPI's roll-up, history moves with
  them, hand wins. A source KPI's cadence change offers to move its computed
  KPIs in the same save. The computed picker lists KPIs on the form's
  cadence; the Window dropdown offers all six windows.
- **Live targets, operands, helpers** (`ec73e31`): a target can be typed,
  per month, or live from another KPI's latest reading, a column or cell of
  the KPI's own sheet, or a Track or HubSpot field (`refs.py`,
  `KpiFeedValue`); the tile, Details and status bands use it, and a reader
  who can't see the source KPI doesn't get the target. A computed KPI's
  operands can be a KPI, the KPI's own target, or a feed column, cell or
  field. "Helper: not shown as a tile" keeps a KPI off the board. Progress
  tiles read "102 of 108 · 94%". The demo's example is Hooli Field
  Services' "Homeowner contacts" page (fictional, at the owner's choice).
- **Sheet feed by row** (`606e0aa`): a third layout, "By row (a column per
  period)": click the dates row and the numbers row, same preview; month
  names, quarter labels (2-digit years too) and "Oct '24" parse,
  parentheses are negative, "$1,101,321" parses, percentages go into
  Percent KPIs. A feed writes as far back as the sheet goes; January 2025 is
  only the period pickers' floor.
- **Only a real sheet can confirm:** a by-row feed on a live finance sheet,
  and a live target read from a real sheet column. Unchanged from Release
  25: the Microsoft 365 checks and the calendar checks. R1's listing worked
  again this time (gcloud signed in).

## 2026-10-27, late: Release 25, and where things stand

- **Release 25 is live**: `main` at `e25ba88`, eight migrations applied by
  the runbook in the waiting worker, all OK (`accounts 0005`, `tenancy
  0022`–`0023`, `crm 0052`–`0053`, `calendars 0001`, `meetings`
  `0009`–`0010`; additive or no-op); R5b created `calendars.sync` for both
  practices; web came up by itself; push to worker running 2 min 17 s. R1 was
  read from the backup service's log, gcloud's sign-in having expired.
  Runbook, "Observed at Release 25".
- **On production now, since Release 23:**
  - *Release 24:* the HubSpot feed (M5 part 5), the M5 ties into the rest of
    the app, the polish (figures as said, banners at phone width, one-email
    introductions, the platform's NMI read-back) and browser notifications
    with the Notices list.
  - *Release 25:* Microsoft 365 as a practice's mail transport; Sign in with
    Microsoft and meeting notes from OneDrive; the calendar (Home's "Today
    and tomorrow", a company's Meetings, Add to calendar, the stage rule's
    calendar event); practice sign-in straight to Google's account chooser
    with the address optional and remembered; and the four small things:
    one-click unsubscribe fixed (the `List-Unsubscribe` header was being
    folded into encoded-words, on Gmail's path too), "@" name suggestions in
    comment boxes, readings proposed from meeting notes, and the mail switch
    waiting for an empty Outbox.
- **Production's configuration:** the **VAPID keys and the Google
  `calendar.events` scope are already on production** (owner, 2026-10-27),
  so browser notifications and Google calendars can be used there.
  **Microsoft 365 is not yet**: mail, Sign in with Microsoft, OneDrive notes
  and Microsoft calendars all wait on the Entra app registration
  (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`; delegated `Mail.*` per
  `docs/m365_transport.md` §9, `Files.Read`, `Calendars.ReadWrite`,
  `User.Read`); unset, each screen says it isn't set up.
- **The demo fixes**, all on the demo since its 10/27 evening reseed: the
  demo refuses calendar connections, disconnects and reads for every
  practice, and never shows its seeded connection as anyone's (a Disconnect
  there had removed the seeded meetings); calendar matching counts a client
  with portal access as a client (the Acme check-in and review prep had
  matched nothing); Acme Fasteners has a small scorecard, and its weekly
  operations review proposes last week's scrap rate in the meeting queue.
- **Only a real account can confirm:** the Microsoft side, `docs/m365_
  transport.md` §10; the calendar, `docs/calendar.md` (11 points); a
  reading proposed from a real meeting's notes (Claude's extraction is
  untested against live notes); Gmail and Outlook showing one-click
  unsubscribe on a real marketing send.
- **Housekeeping:** `gcloud auth login` on the laptop, so the next R1 can
  use the listing as written. The laptop's `execsnowhq_local` keeps an
  archived "Contoso (check)" practice from the OneDrive check.

## 2026-10-27, late night: one-click unsubscribe, @ suggestions, readings from meetings (released at Release 25)

- **List-Unsubscribe** goes out on one line, as given: Python had folded a
  long one-click URL into encoded-words, which Gmail and Outlook do not read,
  so neither showed one-click unsubscribe. Both transports send the same
  MIME (`transport.MAIL_POLICY`); tests read the raw header as sent.
- **"@" suggestions** in a comment box on a task, project or goal (a report's
  goals included): only the people a mention would tell, for the
  visibility being written (`/api/comments/mentionable/`).
- **Readings from meetings** (`docs/p6_m5_kpi_scorecard.md`, last section):
  `meetings 0010`, no-op. The demo's Acme operations review proposes last
  week's scrap rate; Acme now has a small scorecard.
- **The mail switch waits for an empty Outbox**, refusing with the count, on
  Settings → Email and in the Practices area.

## 2026-10-27, night: the demo's calendar, and straight-to-Google sign-in (released at Release 25)

- **The demo's calendar** is never shown as connected, and Disconnect and
  reading are refused there for every practice (a read or a disconnect had
  removed the seeded meetings). The seed's connection carries no address.
- **Practice sign-in goes straight to Google's account chooser** (no
  "Sign In Via Google, Continue" page): `/accounts/google/start` starts
  allauth's flow itself; `LOGIN_URL` is that start. The address is optional
  (a login hint only) and the last one used is remembered in the browser. A
  practice outside the Workspace still needs its address the first time,
  since the address picks its Google client.
- **Calendar matching**: a client with portal access is matched as a client.

## 2026-10-27, evening: Calendar (released at Release 25)

- **Calendar** (`docs/calendar.md`; migrations `calendars 0001`, four
  tables, `crm 0053`, one column, `tenancy 0023`, no-op; all additive). One
  calendar per team member, Google or Microsoft by the practice's provider;
  Home's "Today and tomorrow"; a company's Meetings; Add to calendar on a
  dated task and a follow-up's next step; the stage rule "Offer a calendar
  event", asked on the board's move. Event bodies are never read; attendee
  addresses only match. **New schedule `calendars.sync`** (every 15 minutes):
  R5b at the release. **Needs** `calendar.events` on both Google OAuth
  clients (and the Calendar API enabled) and `Calendars.ReadWrite` on the
  Entra registration.

## 2026-10-27, later: Sign in with Microsoft, and OneDrive notes (released at Release 25)

- **Sign in with Microsoft** (`accounts 0005`, additive: two columns on
  `app_user` binding the work account) for staff of a practice on Microsoft
  365: invite-only like Google's, an address believed only on a verified
  domain of the signer's own directory, one work account per user. The
  sign-in page shows the second button where it applies. **The Practices
  area now sets "Mail and sign-in"** per practice, so a Microsoft-only owner
  can sign in from day one. Spec §9, "Sign in with Microsoft and OneDrive
  notes, as built".
- **Meeting notes from OneDrive** (`meetings 0009`, additive: `provider` on
  `drive_watch` and `meeting_source_file`): the same pipeline through a
  `OneDriveClient`; a folder picker on the meeting queue; Loop, Word, text and
  `.vtt` read. **Needs `Files.Read`** on the app registration. §10 items
  15–23 are what only a real tenant can confirm.

## 2026-10-27: Release 24, and Microsoft 365 mail (mail released at Release 25)

- **Release 24 is live**: `main` at `778a72e`, seven additive migrations
  applied by the runbook in the waiting worker, all OK (`scorecard 0007`,
  `crm 0050`–`0051`, `work 0011`, `strategy 0020`, `billing 0011`,
  `notify 0001`); no new scheduled job, so no R5b; web came up by itself;
  push to worker running 2 min 30 s. It carried the HubSpot feed, the M5
  ties, the polish and browser notifications below. Production had no
  VAPID keys at the time; **they are set now** (owner, 2026-10-27). Runbook, "Observed at Release 24".
- **Microsoft 365 as a practice's mail transport** (migrations `tenancy
  0022`, `crm 0052`, additive: `tenant.mail_provider`, the
  `microsoft_connection` table, a `graph_conversation_id` column on
  `email_thread` and `unmatched_inbound`; on `dev`, not released). Built to
  `docs/m365_transport.md` §§2–5 and 7, as built in its new §9, with every
  assumption only a real Microsoft 365 tenant can confirm in §10. **One
  transport a practice**, switched by the practice owner on Settings →
  Email ("Mail goes through"); switching deletes nothing. Gmail's path is
  unchanged (`tests/test_microsoft_transport.py`, last section). Not built:
  OneDrive notes (§6), Sign in with Microsoft (D1). **Needs the Entra app
  registration** (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`;
  `.env.example`) before anyone can connect; unset, the screen says
  Microsoft 365 isn't set up. **Found, not fixed:** `transport.build_mime`
  folds a long `List-Unsubscribe` into RFC 2047 encoded-words, so the header
  every marketing email carries may not be read as one by Gmail or Outlook
  (the one-click unsubscribe button). It is Gmail's path too, so it waits for
  the owner's word. *(Fixed in Release 25, at the owner's word.)*

## 2026-10-26: Release 23, and M5 part 5 (M5 part 5 released at Release 24)

- **Release 23 is live**: `main` at `32479ca`, nine additive migrations
  applied by the runbook in the waiting worker, all OK (`billing 0010`,
  `crm 0045`–`0049`, `scorecard 0004`–`0006`); the three new jobs made by
  `ensure_schedules`; web came up by itself; push to worker running 4 min
  20 s. It carried everything from stage rules part 2 to the phone top bar
  below. Runbook, "Observed at Release 23".
- **M5 part 5, the HubSpot feed (migration `scorecard 0007`, additive: two
  tables, `hubspot_connection` and `kpi_hubspot_feed`; on `dev`, not
  released).** Spec, "Part 5 as built", has the arithmetic and what is
  unverified against a live HubSpot account. No new schedule: it rides the
  hourly `scorecard.read_feeds`, once a day per measure. **One feed a KPI is
  now kept in one place** (`feeds.stop_other_feeds`): before, setting a
  sheet or a Track measure left a "From this app" feed running beside it.
- **M5 ties (migrations `crm 0050`, `work 0011`, `strategy 0020`, additive:
  one nullable column each, `kpi_id`; on `dev`, not released).** Spec, "The
  ties as built". A goal's KPI on its card and in the portal, the scorecard
  grouped by component, a map row's KPI carried to its goal, the digest's
  Scorecard section, "Make a task" and the nudge after three periods Off
  track, and Claude's "Explain this scorecard" and "Draft the weekly note".
  The demo seed links "Deliver the next day" to On-time delivery, has
  Overtime Off track the last three weeks, and drafts Michael Scott's weekly
  digest after the scorecard, so its Scorecard section shows on Digests.

## 2026-10-26, later: polish, and browser notifications (released at Release 24)

- **Polish.** A goal's figures read as said ("54% → 90%", "$1,200", "1,250.5";
  `apps/work/figures.py` and `lib/figures.ts`; the API keeps its decimals),
  and the sheet preview shows readings by the KPI's kind. A banner's words
  are one body, so a link in its sentence no longer breaks into fragments at
  phone width (every banner; the acting bar keeps its sentence and button).
  The demo seeds Dunder Mifflin's quarterly review, whose map names
  Overtime and On-time delivery. **An introduction can be one email to both**
  (the Introduce form's "Send it as"; library template "Introduction, one
  email to both"): the outbox carries a second recipient (`crm 0051`), and
  every check is made per address: the dev allow-list (real only when both
  are listed), unsubscribes (either stops it), and the demo, which sends only
  to its redirect and whose Gmail transport refuses a second address.
  **The platform's NMI read-back** (`billing 0011`): the practice owner's own
  practice's daily `read_back_nmi` also reads the platform account; a refund,
  void or chargeback of a subscription charge lands on that practice's row
  against its subscription invoice, a "sub-" action matching none on the
  platform owner's practice; both in the Practices area with Mark as seen,
  never in a practice's own list.
- **Browser notifications** (`apps/notify`, `notify 0001`: `notice`,
  `push_subscription`, `push_preference`). **The Notices list (the bell in
  the top bar, practice and portal) is the source of truth**: a stage rule's
  notice, a reading waiting on someone, a message on work shared with the
  client (the practice's to the client's people who see it; a client's to
  the practice people on the work, else the owner and assigned associates),
  and a mention ("@Full Name", or "@First" when one person has it, told only
  to someone who can see the comment). Profile, "Notify me in the browser":
  one Web Push subscription per browser, only to a browser push service's
  own address; every kind a switch; pushed at once after commit (the demo has
  no worker), never on a demo visitor's copy, never while acting. **New
  dependency `pywebpush==1.14.1`** (with `http_ece`, `py-vapid`, `six`):
  1.14 is the last on `requests` rather than `aiohttp`. **Needs VAPID keys per
  environment** (`manage.py make_vapid_keys`; `.env.example`); unset, Profile
  says it isn't set up and the Notices list works regardless. The laptop's
  `.env` has its own pair. "@" name suggestions came in Release 25. **The
  VAPID keys are on production** (owner, 2026-10-27).

## 2026-10-24: catch-up reach, and M5 part 3 (released at Release 23)

- **Catch-up reach (`a9c4e94`).** The May 2026 limit seen on production was
  not reproduced: production's bundle is `dev`'s, and locally a monthly KPI's
  From reached November 2024. The pickers now reach back to the earlier of
  two years and January 2025, the table has Earlier and Later, and the
  single-period dropdown groups its weeks by month. Bryan to say whether
  production still stops at May 2026 after the next release.
- **M5 part 3, the Google Sheet feed (migration `scorecard 0004`, additive:
  one table, `kpi_feed`).** `sheets.py` (reading a grid), `feeds.py` (the
  connection, preview, run, notices), `views_feeds.py` (routes under
  `/api/scorecard/feeds/`). Spec, "Part 3 as built", has the choices. **At
  the release:** the migration by the runbook, then R5b (`ensure_schedules`:
  one new job, `scorecard.read_feeds`). **Before anyone uses it:** the scope
  `https://www.googleapis.com/auth/spreadsheets.readonly` added to both OAuth
  clients' consent screens (Internal and External), then "Reconnect Google"
  on a scorecard tile.
- **Stage rules, part 2 (pipeline plan of 10/20; migration `crm 0045`,
  additive: two tables, `stage_rule_firing` and `pipeline_notice`; new
  columns on `stage_automation` and `contact_pipeline_position`; and
  `stage_automation.to_stage_id` loses NOT NULL, because won and lost rules
  have no stage).** Settings → Stage rules is one card per stage: rename,
  reorder, add, remove (refused while it holds contacts), and the stage's
  rules; won and lost are the pipeline's own card. Triggers: enters (from
  any or a named stage), sat N days with no activity (`crm.stage_rules_daily`
  at 7:00, once per stay), won, lost. Actions: a task (merge fields, due in N
  days, for the contact's owner, the practice owner or a named member), a
  draft email, a move, referral touches at a cadence, a notice (Home, and one
  email a day). Loop guard: a rule's move runs the next stage's rules but not
  their moves. `apps/crm/services/stage_rules.py` holds it all;
  `stage_entered_at` and `last_activity_at` are kept by `change_stage` and by
  signals on email, notes, meetings and finished tasks (older positions fall
  back to their last move into the stage, so there is no backfill). The
  starter rules are one-click examples on the screen, found by the seeded
  stage codes; **the plan of 10/20 was not in the repo, so the examples are
  proposed afresh** (listed in `stage_rules.EXAMPLES`). At the release:
  `crm 0045` by the runbook, then R5b (`crm.stage_rules_daily` is new).
- **Pipeline part 3, a stage's follow-up (migration `crm 0046`, additive:
  four tables).** `apps/crm/services/follow_ups.py`. A stage carries one
  follow-up of two or three steps (library template, N days after the one
  before was sent); the move asks "Start the <stage> follow-up?" (No first),
  and a rule action starts it without asking. Each step is drafted once
  (`follow_up_run_step` unique pair) on its day by `crm.stage_rules_daily`,
  into the Outbox for approval (producer `follow_up`, marketing). It stops on
  an inbound email, a move, an unsubscribe, a step expired or refused, or
  Stop on the contact's page, withdrawing a waiting draft. Starters: Proposal
  Given (3, 7 days) and New Partner (5, 20), each adding two templates to
  the library. No new schedule.
- **P4 §4, the NMI read-back (migration `billing 0010`, additive: `nmi_event`).**
  See the billing spec §4, "As built". New daily job `billing.read_back_nmi`:
  R5b at the release.
- **R3, outbound introductions, and R3b's specialties (migration `crm 0047`,
  additive: columns on `contact` and `referral`).** `apps/crm/services/
  introductions.py`, routes `/api/introductions/`. An introduction is an
  outbound `referral` row (referrer = the partner, prospect = the other
  contact, on the referral pipeline) with date, note, who made it and the
  outcome the practice sets (no reply, met, became a client, not a fit). It
  drafts the library's new "Introduction" template (merge fields `{OtherName}`,
  `{OtherCompany}`, `{OtherDiscipline}`, `{OtherSpecialties}`, `{IntroNote}`)
  **to each of the two, as two drafts**: one email with both on it needs the
  send path to carry a second recipient past its guards (dev allowlist, demo
  redirect, each person's unsubscribes), which it does not yet. The template is
  seeded into a practice's library the first time it is wanted. Specialties:
  a discipline (fractional CMO, CFO, COO, CHRO, other) and free-text phrases,
  suggested from those used; Contacts filters by both and the search box finds
  them. Activity: introductions, outcomes, specialty changes, follow-ups.
- **M5 part 4, the Track PMS feed (migration `scorecard 0005`, additive: two
  tables).** Spec, "Part 4 as built", has the arithmetic and the list of what
  is unverified against a live Track account. No new schedule: it rides the
  hourly `scorecard.read_feeds`, once a day per measure.
- **My practice, and "From this app" (migrations `crm 0048`, additive: the
  `company.is_practice` flag and its one-per-practice index; `scorecard 0006`,
  additive: `kpi_app_feed`).** Spec, "My practice". `Company.objects` hides
  the practice's row; `all_objects` does not, and the three name lookups
  that use it skip it. The demo seed gives Summit one with seven KPIs.
- **Phone width (below 700px, `theme.css`):** every table in `main` scrolls
  inside its own box, keeping normal word breaks; single-column grids are
  `minmax(0, 1fr)` (plain `1fr` held the settings, contact and company pages
  open at their widest table); cards, sections and row children may shrink;
  tab bars scroll; long words outside tables break; the bulk-action bar's
  buttons wrap. Swept at 390 in headless Chrome over 72 views (every app
  route, a company, a contact, an invoice, both scorecards and their Grid
  view, the catch-up table, and the portal as a client owner): none scrolls
  sideways; 27 of them have tables.
- **Demo findings on the Oct 24 builds (migration `crm 0049`, additive: two
  columns on `contact`).** The demo was already on the tip of `dev`; the three
  missing seed items mean its last reseed never ran on that build.
  (1) Catch-up: the cadence menu offers only the cadences the person has KPIs
  in (`cadences` on `/api/scorecard/bulk/`), switching to the first if the
  one showing has none. Earlier itself was not reproduced blank: on the laptop
  and against the demo's own data it steps monthly and quarterly back with
  their rows. (2) A stage card's Remove refuses on the card itself, at once
  when it holds contacts; the server also refuses a stage people have moved
  through (its `stage_change` history protected it with a 500); a removal is
  on Activity (`pipeline.stage_removed`). (3) The contact owner picker sent the
  membership's id; it sends the person (`user`), and offers only current
  staff. (4) A follow-up drafts step 1 the moment it starts; step 1 has no
  days of its own (stored 0); the job drafts the rest. Starters: Proposal
  Given (at the start, then 7 days), New Partner (at the start, then 20).
  (5) Enter readings' side panel leaves computed KPIs out. (6) Below 700px,
  tables marked `cards-on-phone` show each row as a card with its facts
  labelled (`data-label`): Contacts, the company page's People, Portal access
  and Teams, both Invoices screens and Recurring invoices. Every other table
  that scrolls sideways gets a drawn bar above it (`components/
  TopScrollbars.tsx`, one instance in the shell; phones hide native
  scrollbars until a box moves). (7) Every contact has pronouns (he, she,
  unset reads as they) and "How I'd introduce them" on the "What they do"
  card, now on every contact page. Merge fields `{HeShe}` `{HimHer}`
  `{HisHer}` `{Specialties}` `{Blurb}` for the person written to and
  `{OtherHeShe}` `{OtherHimHer}` `{OtherHisHer}` `{OtherBlurb}` for who
  they're meeting; a pronoun starting a sentence is capitalised, and a
  pronoun no longer holds open a line whose facts are missing. The
  Introduction original is rewritten warmly; a practice's existing copy
  keeps its words (the library never rewrites one) and shows "Restore the
  original" for the new ones.
- **Phone top bar and drawer (860px and below, 2026-10-26).** The sidebar no
  longer stacks above the page: the top bar (navy, like the sidebar) holds the
  menu button, the practice's logo or name, Feedback and the profile menu, and
  the menu opens as a drawer over the page (`#app-menu`), closed by its ×,
  Escape, the gray, or choosing a page. Staff and portal alike. Swept at 390
  in headless Chrome as the practice owner (every nav screen, a contact, a
  company, Profile, Settings) and as a client owner (every portal screen):
  the page starts at 56px, under the bar, and none scrolls sideways. Seen
  there, not fixed: on the portal's Our work, a project row under a goal
  breaks its name one letter per line.
- **The scorecard pickers' two years, on a Monday.** The gate failed on
  Monday 10/26: 105 weekly periods back from a Monday is 728 days, so the
  week holding the date two years ago was not offered. `reach()` now always
  includes that period; a test runs it on every weekday and on February 29.
- **Digest race tests** add six days in local time; they had failed in UTC
  across the November 1 clock change.

## 2026-10-23: Release 22

- **Release 22 is live**: `main` at `708f85e`, `scorecard 0003` (bonus
  plans, additive) applied by hand in the waiting worker at 15:33 UTC on
  10/23, OK. The worker waited about 13 minutes; web's build timed out
  waiting and was deployed by commit; `/healthz` 200. No new scheduled
  jobs, so no `ensure_schedules`. It carried M5 part 2 (bonus plans) and
  the scorecard fixes (a KPI made only by Save, edit and archive from the
  tile, Percent ratios, catch up from any period). Runbook, "Observed at
  Release 22".

## 2026-10-22: Release 21, and M5 part 2

- **Release 21 is live** (22:18–22:46 UTC): `main` at `7285b6c`, fourteen
  migrations applied by the runbook, all OK: `tenancy 0020–0021`, `crm
  0040–0044`, `billing 0005–0009`, `scorecard 0001–0002`. It carried P4
  billing parts 2 to 5 (card payments, pay links, auto-pay, the practice's
  own subscription), the template library, M5 part 1 (the scorecard) and the
  demo fixes since. `crm 0041`'s data step had Bryan's yes on a dry run of
  the whole release on a scratch copy of the 22:04 dump (237 touch modes
  `ai` to `template`, 10 seeded templates, the $20.00 beta plan).
  Runbook, "Observed at Release 21", has the times.
- **Two lessons, now in the runbook's table.** The worker's `WAITING` list
  stops at ten migrations (`head -10`), so a bigger release looks short:
  check the rest against the plan order. And R4 goes to Bryan the moment
  `WAITING` shows: web's build waits only six minutes for it, and at Release
  21 it came ~24 minutes after the push, so web needed the hand deploy.
- **`ensure_schedules` was not run after the release.** Nothing runs it on
  its own. A read-only check in the worker found none of the four new jobs
  (`billing.resolve_card_payments`, `billing.run_autopay`,
  `billing.charge_subscription`, `scorecard.remind_missing`), and Bryan was
  given the line: `railway ssh --service qcluster -- python manage.py
  ensure_schedules`, which he ran at about 00:05 UTC on 10/23: all four
  created for both practices. It is R5b in the runbook from now on.
- **M5 part 2, bonus plans (on `dev`, not released; migration `scorecard
  0003`, additive: five new tables).** `apps/scorecard/bonus.py` holds the
  arithmetic, who sees whose and the close; `views_bonus.py` the routes
  under `/api/scorecard/bonus/`; `payroll.py` the two-sheet .xlsx, written
  with the standard library. A plan is one period of one company (monthly
  or quarterly) with its people, an amount per person (or their own), and
  two to five weighted per-person KPIs, each with a tier table, or a
  straight line for the whole plan. Copy forward makes the next period's
  plan in the same `series`. Achievement to date is against the target
  prorated to today for a summed KPI, the target as it stands for an
  averaged one, flipped for lower is better; someone added part-way is
  prorated by days, amount and target, and only their periods count.
  Decision 7: My bonus (a person on a plan), Team bonus (a manager: their
  own and their teams'), All bonuses (senior leadership, the client owner,
  the practice owner and associates; assistants without dollars). Closing
  (practice or client owner, once the period has ended) writes
  `BonusResult` rows with every reading, target, weight and tier, and shows
  them ever after; a reading changed later is listed against the frozen one,
  and only the client owner can confirm working the amounts out again
  (`BonusReopen`, audited). The Payroll list is on All bonuses for a closed
  period, with "Download spreadsheet". The demo seed now starts its readings
  three months back and adds Revenue per order (computed), each rep's Sales
  booked, and the Sales floor bonus for Dunder Mifflin: July to September
  closed, October copied forward, Andy joining July part-way.

## Where things stand (2026-10-21 UTC): Release 20 is live

- **The template library (10/21 UTC, on `dev`, not released; migrations `crm
  0040`, additive, and `crm 0041`, data: it adds rows and rewrites one
  column's value).** Backlog S4 part 1, from the plan Bryan approved on
  10/20 with his five choices. `EmailTemplate` gains `original` (a built-in
  one's key) and `first_name_fallback`; `EmailTemplateUse` says which
  template each practice-wide email uses (the default touch, onboarding, the
  three thank-yous). `apps/crm/template_seed.py` holds the old wording and
  seeds every practice (0041 for existing ones, `crm.seed` for new ones; it
  never rewrites a template, and keeps a practice's own onboarding template
  as its onboarding email). `apps/crm/services/templates.py` is the one
  renderer: `{FirstName}` and eight more fields, the fallback, a line of
  only empty fields left out, unknown fields refused on save, the signature
  added once by `compose`. Stage rules, touches, onboarding, thank-yous and
  bulk email go through it; campaigns merge the same seven general fields
  and copy a template with "Start from a template". Touch modes are now
  "template" and "claude": every old "ai" partner became "template" (the
  same words); "Draft with Claude" sends the partner's record, their last
  meeting and the template's shape (purpose `referral_touch`) and falls back
  to the template, saying why, with no key. Invoices offer `{FirstName}`,
  `{DueDate}`, `{PaymentTerms}` and still merge the old spaced forms. The
  screens: Settings → Email templates (owner only), the stage rules screen
  no longer makes templates, Referral settings has "Which template each
  email uses", a partner's page has the two modes and their own template,
  and "Email these contacts" starts from a template with the chip editor.
  `manage.py seed_email_templates --dry-run` shows what 0041 will do, and
  needs 0040's columns. At the next release, in the waiting worker:
  `migrate crm 0040` (additive), the dry run, Bryan's yes on it (CLAUDE.md:
  data-rewriting), then `migrate`.

- **Release 20** (00:31–00:35 UTC, the evening of 10/20 Mountain): `main` at
  `936714f`, `tenancy 0019` and `crm 0039` applied by the runbook
  (00:34:15–20), both OK; `/healthz` 200. Railway built from the push this
  time, but web's own build had given up on the pending migrations a minute
  before they were applied, so web was deployed by commit (runbook,
  "Observed at Release 20"). The demo checks of the referrals passed before
  it (Bryan).
- **Web waits for a release's migrations (10/21, on `dev`, not released).**
  `migrate_if_empty --wait 360 --every 10` in `start_web.sh`: a `WAITING
  (Ns of 360s) for: …` line every 10 s, then it starts once they are
  applied, or refuses as before after six minutes. It never migrates. Web's
  health check timeout must be 480 s on Railway (`railway/web.json`;
  `serviceInstanceUpdate`, run by Bryan, since Claude's auto mode refuses a
  production setting). Runbook R6 is now "usually nothing to do". The worker
  is unchanged.
- **Inbound referrals (10/20, Release 20; migrations `tenancy
  0019` and `crm 0039`, both additive).** `apps/crm/services/referrals.py`:
  one `referral` row per prospect per pipeline (Sales), first recorded has
  the credit, changeable on the prospect's page ("Referred by", any contact,
  referral partners first; it does not make them a partner). Recording puts
  them in Sales at the first stage unless they are in it. `change_stage`
  records the outcome the first time they are won or lost (lost can become
  won; a late-recorded one is dated from the stage move). Thank-you drafts
  (`referral_thanks`, correspondence, from the person) at recorded, won and
  lost, each a switch in Referral settings (`tenant.referral_thanks_*`), once
  per referrer and moment; the lost one gives no reason; an approved one
  moves the referrer's next touch a cadence on (only if they have one). The
  referrer's page has a Referrals card; the board card says "via". A CSV
  "Referred by" column (email, then exact full name) records history without
  thanks and rolls back. Merges carry referrals both ways. `direction` is
  there for R3's outbound introductions; `fee_terms` copies the referrer's
  terms on the day, for referral fees later. The demo seeds five (Ben Wyatt:
  Wiley won, Eldon lost, Selina open with a thank-you waiting; Elle Woods:
  Lucille; Jessica Pearson: Harvey).
- **Meeting queue: a promise is a mark on a task (10/20, Release 19; migration `meetings 0008`, one added column).** The parse prompt
  asks for each thing once, a promise flagged `promised_to_client` on its
  action item; "What was promised" is gone for new proposals, and an older
  pending one folds a repeated line into its action item before it is shown
  (`apps/meetings/folding.py`). A task line's "Promised to <company>" tick
  (pre-ticked from Claude's flag) makes the task and a commitment with
  `side = ours`, outcome "Our task", done when the task is. It shows as
  "Waiting on us" on the company page, never on Waiting on others or its
  dashboard count; the portal lists no commitments, so it shows there only
  as the client-visible task. Every drafting prompt now ends "Use American
  spelling." (`claude.drafting`); the strategy goldens moved by that line
  only.
- **U2, one import door (10/20, Release 19):** Import in the
  sidebar (was "CSV import") is now a page at `/import` asking "What are you
  importing?": contacts and companies (CSV, owner and assistant), a business
  statement and meeting notes from Drive (owner), and a personal statement
  (owner, with Personal finance, not while acting). The contacts wizard moved
  to `/import/contacts`; Contacts gained an Import button; the Finance and
  Personal Import tabs are unchanged. Getting started's contacts line names
  the door.
- **Personal finance's legal texts (10/20, Release 19):** the
  privacy policy draft (`docs/google_verification.md` §5) gains a "Personal
  finance" paragraph, and the beta agreement is **v3**
  (`docs/legal/beta_agreement_v3.md`: v1 plus clause 8, estimates not tax
  advice, no real figures on a demo copy). v3, not v2: v2's card-on-file
  costs clause still waits for subscriptions, which will ship as v4 (v3 with
  v2's clause 3). Every practice owner and every demo visitor is asked once
  more at their next sign-in; a visitor's tick now counts only for the
  version ticked (`visitors.must_agree`). The privacy policy is published
  on the website, not by the app: Bryan updates getexecutivesnow.com/hq/privacy.
- **Release 19** (19:57–20:23 UTC): `main` at `2b1c257`, `meetings 0008`
  applied by the runbook, OK; `/healthz` 200. Railway built nothing from the
  push, so the worker and web were deployed by commit by hand (runbook,
  "Observed at Release 19"). Personal finance is still off for every
  practice; with v3 live it can be offered, after Bryan updates the
  website's privacy page.
- **Release 18** (04:30–04:32 UTC): `main` at `6af19f2`, `crm 0038` applied
  by the runbook, OK; R6 skipped (web's own deployment SUCCESS). It carries
  the campaign test copy (its files, bracketed placeholders, the test line)
  and the first-name fallback.
- The demo was reseeded from the terminal on 10/19, after stop 4.

## 2026-10-20, early: Release 17

- **Release 17 is live** (2026-10-20 03:36–03:38 UTC): `main` at `93bbd6a`,
  migrations `crm 0037` and `personal 0003–0006` applied by the runbook, all
  OK; `/healthz` 200 throughout. Details: the runbook's "Observed at Release
  17". Production now has M4 stops 2–4 (Personal finance is still off for
  every practice: the privacy policy and beta agreement come first),
  campaign follow-through and the editor's merge-field chips.
- Bryan kept every choice of stop 4 and C1 (10/19) and asked for the QBI
  choice (`9e3e703`) and the editor fix (`93bbd6a`), both in the release.
- **The demo still needs its reseed** to show stop 4's seeded data.

## 2026-10-19, evening: stop 4 and C1 built, then accepted

- **M4 stop 4 is built on `dev`** (decisions 20–23, the review's envelope,
  goal and set-aside proposals, the payoff orders renamed). As built and ten
  choices for Bryan: `docs/p6_m4_personal_finance.md`, "As built: stop 4".
  **Waiting on Bryan's acceptance on the demo**, after a reseed.
- **Release 17** (not yet released) carries `personal 0003`, `0004` and now
  **`0005`**: two new tables (`personal_tax_year`, `personal_tax_item`) and a
  nullable `personal_line.draw_entry_id`; additive, no data step. By the
  runbook, on Bryan's "release".
- **Backlog:** U3 (the payoff orders) done with stop 4; **D1, a module for
  your discipline**, added under "Spec first", status later.
- **Stop 4 is committed (`e03f884`) and pushed to `dev`**; the demo deployed
  it. **The demo was not reseeded:** the permission check refused the
  `railway ssh … seed_demo` call this time (classed as a production deploy).
  Bryan runs it, or allows it (see below).
- **Campaign follow-through (backlog C1) built on `dev`**, migration
  **`crm 0037`** (additive: two campaign columns, `email_message.leave_request`,
  a `campaign_attachment` table), applied on the laptop after a green suite.
  The next release carries it with `personal 0003–0005`.
- **Next:** Bryan's acceptance of stop 4 and C1 on the demo, after the
  reseed; then Melissa's Notion/ClickUp import, when her samples arrive.

## 2026-10-19, evening: campaign follow-through (C1, not released)

- **Built:** a campaign's files (three at most, within the Outbox's 10 MB per
  file, the same stored file on each draft); "When this campaign is sent", a
  stage and a referral-touch cadence, run by `campaigns.after_sent` from
  `outbox.approve` once the copy is sent (so a refused, deleted, expired or
  suppressed copy does nothing, and an unsubscribed person never moves);
  "Asked to leave" on Replies (`apps/crm/services/leaving.py`, flagged when a
  reply is stored or filed, from what the person wrote with the quote taken
  off); the audience count and "Select all shown".
- **Choices for Bryan:** a stage move from a campaign runs that stage's own
  rules, as a move by hand does; only referral partners are put on touches
  (anyone else is left off and their history says so); someone already on
  touches keeps their cadence; "Unsubscribe them" is for the practice owner
  or an associate, an assistant sees the list; a reply is read as answering
  the last email sent on its thread.
- **The demo has no campaign with follow-through, and no "asked to leave"
  reply,** until something is set up on it by hand: the seed is unchanged.

## 2026-10-19: M4 stop 4, taxes and the CPA (not released)

- **Built on `dev`:** the pay-yourself loop (draws matched to pay, "Pay from
  <practice>", the Overview's card that sets the business forecast's line),
  Personal → Taxes (the estimate, the four dates, the safe harbor, the
  set-aside and the Tax envelope), For your CPA with both sections and one
  PDF (the business CSV unchanged, checked line for line), standard against
  itemized, the personal facts, Review with Claude on envelopes, goals and
  the set-aside, and "Smallest balance first" / "Highest rate first".
- **Migration `personal 0005`**, additive, applied on the laptop
  (`execsnowhq_local`) after a green suite. **The next release carries it.**
  Until it was applied, the dev server on 8100 errored on personal pages
  (`runserver` reloads model edits before the migration exists).
- **The demo** must be **re-seeded** to show stop 4 (pushing `dev` migrates
  it). Seeding a scratch demo locally took 70 s. Things to look at are in the
  report of 10/19 and in "As built: stop 4", "The demo".
- **The demo's seed changed in the books too:** this year's last two state
  estimated payments are no longer the practice's (they are paid from joint
  savings), so the business worksheet for 2026 shows two fewer state lines.
- Headless Chrome on a scratch demo: Django on 8199 with a scratch database
  (`APP_ENVIRONMENT=demo`, `STORAGE_BACKEND=local`, a non-production
  `GCS_BUCKET_MEDIA`), the frontend started through Vite's JS API on 5299
  (a config file outside `frontend/` cannot resolve `react-refresh`), a
  `force_login` session cookie, and a CDP script. None of it is in the repo.

## 2026-10-17, night: M4 stop 3, the forecast and the rest (not released)

- **Stop 2 accepted on the demo** by Bryan, all six choices kept; the demo
  was reseeded first (Summit only).
- **Stop 3 built on `dev`:** decisions 15–19, the personal forecast's
  Explain and Review, Unassigned toward debts; open questions as recommended
  (Snowball the default, 6% assumed). New pages Forecast, Debts, Retirement,
  Household; the Overview gains both sides' cash in 90 days and net worth.
  As built and the choices for Bryan: `docs/p6_m4_personal_finance.md`,
  "As built: stop 3".
- **Migration `personal 0004`**: three new tables (`personal_asset`,
  `personal_forecast_snapshot`, `personal_forecast_adjustment`), nullable or
  defaulted columns, and `personal_balance`'s one check constraint dropped
  and put back to allow a third kind (an asset's value); no data step.
  Applied on the laptop after a green suite. **The next release carries it.**
- **The demo** must be **re-seeded** to show stop 3 (pushing `dev` migrates
  it). Seeding locally took 73 s.
- Gotcha: `pkill -f "runserver …"` in a command whose own text contains the
  pattern kills the shell running it (exit 144). Kill by port or pid.

## 2026-10-17, evening: M4 stop 2, the budget (not released)

- **Release 16** went out first, the same evening: demo visitors with Bryan's
  two changes (`0c1fd61`, `tenancy 0017–0018`), by the runbook, all OK.
- **Stop 2 built on `dev`:** decisions 9–14, the Cash flow table, Explain
  this budget; the Personal side opens on its Overview. As built and six
  choices for Bryan: `docs/p6_m4_personal_finance.md`, "As built: stop 2".
- **Migration `personal 0003`**, additive (four tables, two nullable goal
  columns), applied on the laptop after a green suite. **The next release
  carries it.**
- **The demo** has to be **re-seeded** to show the budget (pushing `dev`
  migrates it, and the reseed now leaves visitors' copies alone). A visitor's
  copy made before then has no budget until it is reset.

## 2026-10-17: the sign-off fix, Release 15, and demo visitors (not released)

- **The sign-off fix** (`00d5bac`): a strategy document shows Settings →
  Branding's closing line, email and website as they are now, unless the
  document has its own, written in "Change the words on the document"
  (marked "From Branding" until then). Pre-fix saved closings are Branding's
  copies and are not read. The "On the prospect's map" tick is gone for the
  pre-call and What they value.
- **Release 15**, the same day: `dev` → `main` at `00d5bac`, seven
  migrations by the runbook (`finance 0013–0015`, `personal 0001–0002`,
  `strategy 0019`, `tenancy 0016`), all OK; backup of 17:20 UTC; push to web
  live 3 min 11 s; `/healthz` 200 throughout, the old web serving meanwhile.
- **Demo visitors (W1)**, built on `dev`, not released (it is demo-only; the
  demo deploys from `dev`). Bryan's eight decisions as given, built as:
  - A visitor's copy is an ordinary practice made by the demo seed
    (`demo.build(visitor=…)`), the visitor its owner playing John Carter as
    the platform owner does in Summit. `demo_visitor` (migration
    `tenancy 0017`, a new table) is the platform's record of it.
  - **Setup runs as a process of its own**, `manage.py demo_visitors setup
    <id>`, started from the web request (`visitors.launch`), not in the
    request and not on a worker: Summit's seed took 185 s on Railway, the
    seed moves the process's clock (`clock.at`, a global mock), and the demo
    has no worker. The visitor sees "Your demo is being set up"; a setup
    killed part-way (a redeploy) rolls back whole and reads "did not finish"
    after 20 minutes; Reset tries again.
  - Each copy's fictional addresses carry its tag (`ellen.ripley+k3x9q2@…`),
    because a sign-in address is the whole database's.
  - Mail: a copy sends through the demo's own send-only Gmail connection
    (Summit's), from `DEMO_MAIL_FROM`, to the visitor's address only. **The
    invitation is sent only if that connection works;** otherwise the list
    says why and offers "Send the invitation".
  - AI: `DEMO_ANTHROPIC_API_KEY` if set, else the key Summit holds; hard stop
    at $2 a day and $10 in all (spend survives a reset), checked in
    `claude.complete_with_call`; every AI button shows the reason instead
    (`AiGate`).
  - Life: ends after its days, read-only a week, then deleted with its files
    and people by an hourly sweep that any demo request may start (no
    worker). Extend, Reset, Delete, and Send the invitation in Practices.
  - Not on the Practices list; no beta agreement, Gmail, Drive, Anthropic
    key or "Getting started" items for those.
- **Bryan's two changes, the same evening:** (1) `seed_demo` now empties and
  refills **Summit's own practice only** (`demo.reset_summit`); visitors'
  copies keep their sign-ins, data and end dates (tested in
  `test_demo_visitors_seed.py`). The old empty-every-table path is
  `--whole-database`, refused anywhere but a localhost build. (2) A visitor's
  first sign-in shows one screen: fictional data, the days it lasts, no
  warranty, a link to the beta agreement, one box; nothing else answers
  until it is ticked (`DemoVisitorGate`), recorded with its time and the
  agreement's version on `demo_visitor` (migration `tenancy 0018`), so a
  reset never asks again. The platform list shows when each visitor agreed.
- **Still open for Bryan:** an address that already signs in to a practice
  on the demo cannot be a visitor (use a plus address); a visitor plays John
  Carter.

## 2026-10-15, night: the strategy document redesigned (not released)

- **What:** beta feedback S2, from Bryan's approved mock. The strategy PDF is
  now the two-page design for every practice: headline, three stat tiles, the
  mirror as a dark callout with Working / Not yet, the components as cards
  with Strong / Watch / Fix pills; then the 30/60/90 boxes, the two paths
  with For / Against and Recommended, "Before we meet again", and the
  sign-off band. Lora and Lato are bundled (`apps/strategy/fonts/`). The
  Word file follows the same order. As built, and six things the two pages
  no longer carry for Bryan to keep or overrule: the P3 spec, §10.
- **Every line has a length**, and the page is measured as well: a save that
  would overrun a page is refused naming it, the editor warns, and **Send
  refuses** an overrunning document (409).
- **Words:** "Change the words on the document" edits every line; "Draft the
  words with Claude" (purpose `strategy_document`) proposes, a person saves.
  The sign-off's closing line, email and website are in Settings → Branding.
- **Migrations:** `strategy 0019` and `tenancy 0016`, both additive (new
  columns with defaults), applied on the laptop after a green suite. **The
  next release now carries seven:** `finance 0013–0015`, `personal 0001–0002`,
  `strategy 0019`, `tenancy 0016`, by the runbook.
- **Goldens:** only the PDF HTML files changed (six), rewritten on purpose;
  nothing else in them moved.
- **The demo:** Wayne Industries has a complete session whose document is the
  mock. Pushing `dev` migrates the demo; **re-seed it** to get the session.

## 2026-10-15, evening: M4 stop 1 finished (not released)

- **Bryan's rulings:** stop 1's five choices all stand; the demo seed's
  personal side is not a migration data step, so it was built.
- **Built:** rules by hand (Settings → Finance → Import rules: Add rule,
  Edit, with a side); "remember" for a hand split saves its percent;
  Personal → Import (CSV, OFX, PDF) with business lines **paid personally**
  (in the P&L and the CPA's worksheet, in no practice account); transfers
  between the household's accounts, paired on import; optional reconcile of
  a personal account; **Sort these with Claude** on To sort (priced, costed,
  on Finance's 20 a day and the monthly budget); the demo's personal side
  (`apps/tenancy/demo/household.py`). Details and six new choices for Bryan
  are in the spec's "As built: stop 1".
- **Migrations:** `finance 0015_paid_personally` (a wider `side` column and
  a looser check) and `personal 0002` (new tables, nullable columns), both
  additive, applied on the laptop after a green suite. **The next release
  carries five:** `finance 0013`, `0014`, `0015` and `personal 0001`, `0002`,
  by the runbook.
- **The demo seed takes longer:** about 50% more in the test (105 s to
  155 s), so expect about 4–5 minutes on Railway rather than 3. The demo
  must be **re-seeded** to show the personal side (pushing `dev` migrates it
  but does not seed it).

## 2026-10-15, later: M4 spec, and stop 1's first slice

- **"Words" is now "Wording"**, a section of Settings → Branding (`9920f2f`).
- **The M4 spec** is `docs/p6_m4_personal_finance.md` (`96428b1`), written
  from Bryan's draft (`docs/p6_m4_personal_finance_spec_draft.md`, verbatim)
  and the brief; three *Brief wins* points are marked in it.
- **M4 stop 1, first slice** (sides): see the spec's "Stop 1 as built".
  Migrations `finance 0013`, `personal 0001`, `finance 0014`, additive, on
  the laptop only. Production needs them at the next release, and the module
  switched on per practice. Not built yet: personal-account imports,
  transfers, personal reconcile, Sort these with Claude, the demo seed.

## 2026-10-15: Release 13, three jobs, Release 14

- **Release 14 is live: `84880d5`,** all of `dev`: the invoice modal (U1),
  the practice's words (W2) and the strategy map as Word (W3). `tenancy 0015`
  applied by the runbook (WAITING listed it alone; applied 18:43:51–57).
  Push to new code 2 min 22 s, `/healthz` 200 on all 47 samples, worker
  paused about 41 s, nothing unapplied. `python-docx` built and runs in
  production. Backup: the owner's run-now dump of 15:24:58 UTC. **The
  push's own web deployment went live by itself once the migration was in**,
  so the R6 redeploy was redundant this time (runbook, Release 14).
- **Release 13's open checks are closed:** its run-now backup was confirmed
  (15:24:58 UTC, 3.2 MB), and its worker was processing jobs at 18:42:13,
  just before Release 14's push.
- Demo checks of all three jobs passed (owner, 2026-10-15). **Not yet seen in
  production:** the practice's words with anything but the defaults (no
  practice has set any), and a Word file opened in Word itself.

- **Release 13 is live: `f91c08c`,** no migration: P7 phases 3 and 4 (the
  client owner's Your team page; what each level sees and may do), team
  changes on Activity, the Senior leadership labels, the Viewer's line and
  no comment box for a Viewer, and the company page's layout. Pushed 15:29:02
  UTC, new bundle served 15:32:33 (3 min 31 s), `/healthz` 200 on all 38
  samples. (Its two open checks were closed at Release 14, below.)
- **Layout is now looked at before it is committed,** in headless Chrome
  with a throwaway harness (the real app, canned API answers, a button
  clicked by name), at 1920 and 1366. The harness is not committed.
- **Job 1, U1: "New invoice", "New recurring invoice" and a schedule's "Edit"
  open as a modal** over a grayed-out page (`Modal` in `shell.tsx`): Esc, the
  close button, Cancel or a click on the gray close it with nothing saved.
  "New invoice"'s button is now "Save the draft" (it starts the draft and
  opens it). A sent invoice's page is unchanged. `e9e068c`.
- **Job 2, W2: each practice names its goals, projects, tasks and steps**
  (`3cd0deb`). **Settings → Branding → Wording** (practice owner; renamed
  from a "Words" page the same day); `tenant.work_words`
  (migration **tenancy 0015, additive, on the laptop; production needs it at
  the next release**). `apps/tenancy/words.py` and `frontend/src/lib/words.ts`
  (`useWords()`: `w.task`, `w.Tasks`, `w.aTask`, `w.count`, `w.counted`).
  Shown in the sidebar, screens, portal, read-only lines and refusals,
  Activity, digests (and the AI prompt, only when the words differ), the value
  report PDF, the meeting queue, stage automations and the map's conversion.
  Not on the platform owner's pages, the API's fields or stored data. **A new
  readable string with one of the four words must use them**; five test files
  (`tests/test_practice_words*.py`, `frontend/src/test/words_*.test.tsx`)
  hold it for what exists. W2's Getting started item was added after Release
  14 ("Choose your wording…", to Branding's Wording section, done once any
  word differs from the default).
- **Job 3, W3: the strategy map as Word.** "Download as Word" beside the
  map's PDF (`/api/strategy-sessions/<id>/docx/`, `apps/strategy/docx_export.py`):
  the PDF's sections and headings from the same filtered content, so the
  private-note flags hold; the practice's logo or name, header colour, accent
  on the lowest score, and footer. Text the PDF shortens is whole. New
  dependency **python-docx 1.1.2** (with lxml 6.1.3). Clients have no strategy
  screens, so there is no portal link. Looked at through LibreOffice; not yet
  opened in Word itself, and the logo path was not exercised (the sample
  practice had none).

## 2026-10-14: Release 12 is out

- **Release 12 is live: `bd6dceb`,** all of `dev` as planned, recorded step
  by step in the runbook. The dry run of P7 phase 1's data step was read from
  production first and Bryan said yes to it: 4 default teams, 6 portal users
  as Manager, 14 projects and 100 tasks given a team. `work` 0010 and `crm`
  0036 printed exactly those. A fresh backup was taken by Bryan first.
  `/healthz` 200 throughout; push to new code 3 min 18 s.
- **R1's check command was wrong:** `gcloud storage ls -l` ends in a `TOTAL:`
  line, which `sort -k2 | tail -1` showed in place of the newest dump. The
  runbook's R1 now drops it with `grep -v '^TOTAL'`.
- **The first real PDF statement was read on production by Bryan:** the
  beginning balance, the ending balance and every line correct. **Estimated
  $0.15, cost $0.08.** The estimate runs about double the actual: not a bug,
  something to tune later.
- **On production, set by Bryan:** payment terms, and both client invoice
  schedules. A schedule's day writes a draft only: it is numbered when a
  person makes it ready, and sent only when the send is approved in the
  Sending queue. There is no setting that sends one by itself.
- **Backlog U1** (a new "UI" section in `docs/beta_feedback_2026-10-12.md`):
  "New invoice" and a schedule's "Edit" open as a modal over a grayed-out
  page. Later.
- **P7 phase 3 is being built on `dev`** (the client owner's Teams card in
  the portal); see the spec's "As built: phase 3" once it is there.
- Still open from "After the release" below: the demo reseed for its PDF
  statement, if it has not been done; the laptop's `pip install` and qcluster
  restart.

## Release 12: the plan as it was (done 10/14; see above)

**Bryan, the evening of 10/13: Release 12 is all of `dev`, after the phase 1
dry run on production and his yes.** Not phase 1 alone, as first planned.
Production is `main` at `147087f` (Release 11). Nothing below has been
released, **and none of it has been seen in a browser by anyone.**

### In this order

1. **The dry run of P7 phase 1's data step, by Bryan, on production.**
   Production has no P7 code, so `manage.py client_teams_dry_run` is not
   there yet. `scripts/p7_phase1_dry_run.py` reads the same plan using only
   columns that exist today, writes nothing, and a test holds its words to
   the command's. Production reads are refused to Claude Code, so it is
   handed to Bryan as a paste block (Claude Code prompt, with `!`):

   ```
   ! cd ~/projects/execs-now-hq && railway ssh --service execs-now-hq -- "echo $(base64 -w0 scripts/p7_phase1_dry_run.py) | base64 -d | python manage.py shell"
   ```

   He pastes the output back. It lists, for every company that gets a
   default team: its portal users before, and the team, the people placed
   as Manager and the work given a team after. **The release waits for his
   yes on it.** For comparison, the laptop's copy of production (as of its
   last refresh): 4 default teams, 3 portal users placed as Manager, 12
   projects and 86 tasks given a team, 28 tasks left to follow their project.
   Production will have more portal users than the laptop's scrubbed copy
   shows if any were invited since the refresh.
2. **Confirm the backup** (R1). A fresh one before the release is Bryan's to
   run: the "run now" command was refused to Claude Code.
3. **Release, on the word "release":** `git push origin dev:main`, by
   "Releasing a migration". The commit to release is the head of `dev`, which
   must be a tree the gate passed.
4. **Six migrations will be listed as waiting, and no others:**

   | Migration | What | Data step |
   |---|---|---|
   | `tenancy` 0014 | `membership.may_create`, `leads_all_teams` | none |
   | `work` 0010 | client teams, a project's team, `goal.created_by_client` | **yes: default teams, people as Manager, projects.** Prints its counts |
   | `crm` 0036 | a task's team | **yes: tasks in no project.** Prints its count |
   | `billing` 0003 | payment terms on an invoice and a schedule | none |
   | `billing` 0004 | a schedule's own how-to-pay and covering email | none |
   | `finance` 0012 | an import's source, statement, period and the call that read it | none |

   Compare the two printed counts with the dry run's before going on.
5. **A new dependency, `pypdf`**, is in `requirements.txt`, so the build
   installs it. `config/startup.py` names it: a build without it refuses to
   start and says why.
6. **After:** no new schedule, so `ensure_schedules` is not needed.
   `/healthz`; a route that exists only in this release goes from 404 to 403
   (`/api/client-teams/`). Then the record in the runbook, as Release 12.

### What Release 12 carries, in the order it was built

| Commit | What |
|---|---|
| `31e13a8` | **P7 phase 1:** client teams, levels and may-create, everyone a Manager of their company's default team |
| `9645a16` | Strategy map: the model is told to write no em dashes (goldens regenerated on Bryan's yes) |
| `5285f41` | **P7 phase 2:** the practice's Teams card, the Team field and filter, the invitation's team, level and may-create |
| `6e42a15` | The dry-run script for a database without P7 |
| `a1dd5e6` | P7: the client owner may delete a colleague's task |
| `37661d3` | Invoicing: payment terms |
| `23faf54` | Invoicing: a recurring invoice can be edited |
| `235787e` | Bank import: OFX, QFX and QBO files |
| `6f17916` | Bank import: a PDF statement, read by Claude |
| the two after it | The demo's seed imports one PDF statement; this handoff |

### What changes for people on the day

- **Client users, two things** (Bryan's rulings): a client's project is
  deleted only by whoever made it or by the client owner, where any client
  user of the company could before; and the client owner may delete a task a
  colleague made. Nothing else about any portal user's reach changes: each is
  a Manager of a team called "Everyone".
- **A person invited to a portal from now on starts as a Member** (P7-9) and
  sees only work that is theirs, unless the form is set otherwise. In a
  company still on one team, that is less than the people already there see.
- **The practice** gains the Teams card, payment terms under Settings →
  Finance → Paid invoices, Edit on a recurring invoice, and OFX, QFX, QBO and
  PDF in the bank import.
- **A draft invoice's due date is no longer typed:** it is the issue date and
  the terms.

### Not proven, to check in a browser once it is out

- **No PDF statement has been read by a real key.** How well Claude copies a
  real bank's layout, and what a read really costs, are unknown. The first
  real one is the test: check its lines against the PDF, and that "the lines
  add up" says so.
- **No real OFX, QFX or QBO file has been tried.** The reader is tested on
  the two forms of the format, written by hand.
- **The em-dash sentence has not been through a real call.**
- **P7:** no level other than Manager has been held by a real person. Before
  setting anyone below Manager, know that the portal's own screens have not
  changed (phases 3 and 4): "New task" is still offered to someone who may
  not create, and answers with a sentence.
- Everything from Release 11 that was unseen is still unseen: the M2 fixes
  ("Explain this forecast" above all, whose fix rests on an inferred cause).

### After the release

- **Reseed the demo** (the three steps under "The demo as it is set up") to
  get the PDF statement there: last month's bank statement, fictional and
  saying so, imported, and shown on Reconcile for that month and under
  Earlier imports. The seed draws it without Claude, so it shows no cost.
- **The laptop:** `pip install -r requirements.txt` after a pull (for
  `pypdf`); every `dev` migration is applied to `execsnowhq_local`. Its
  qcluster still needs a restart and `ensure_schedules`.
- **Open with Bryan:** P7 phases 3 (the client owner's own Teams card) and 4
  (the portal for members, managers and senior leaders, and goals by a client
  user); M3's spec; §5.6's move of old invoice income; a smoke check of
  Releases 10 and 11; "the monthly AI budget can be set to stop, not warn".

## 2026-10-13: three M2 findings from the demo, Release 11, and P7 put to Bryan

**This section is the newest.** **Production is `main` at `147087f`: Release
11, 2026-10-14 00:05 UTC (10/13, 6:05 PM Mountain).** It carries everything
that was on `dev`: P6 M2 (the cash forecast, both stops), the ten fixes of
10/12, and the three below. Six migrations, all OK; the record is in the
runbook. Where the sections below say "not released" or "production is
unchanged", this is the newer.

- **The Cash forecast module is off for Executives Now** until Bryan switches
  it on in the Practices area (it needs Bookkeeping).
- `ensure_schedules` was run in production: `finance.keep_month_forecast`
  exists for both practices. **The laptop's qcluster still needs a restart
  and `ensure_schedules`.**
- **Nothing in Release 11 has been seen in a signed-in browser on
  production.** The smoke check is Bryan's: the Forecast tab once the module
  is on, Explain pressed once, Review run once, and one of the 10/12 fixes
  (Notes folders, the Tags setting).
- A fresh backup before a release is Bryan's to run: the "run now" command
  was refused to Claude Code by the permission check.

**Bryan looked at stop 2 on the demo** (queue item 2) and found three things.
Each is its own commit on a green gate; the detail is in the M2 spec, "As
built: after Bryan's look on the demo".

| Commit | What |
|---|---|
| `54b9d6c` | "Explain this forecast" was cut off every time: the output ceiling is 16,000 for the three pressed buttons, and Explain asks for low effort |
| `e4aa2df` | The form a review's proposal opens follows the proposal: its cadence, and the date it next falls. A planned line can repeat "Every year". **Migration `finance` 0011** (a new choice, no SQL), applied to `execsnowhq_local` |
| `147087f` | Review is sent a summary of the money in the forecast already has, by client, and told not to ask about it |

- **Not proven:** none of the three has been run with a real key or seen in
  a browser. The cause of the first is inferred from how the model is
  documented to behave; the demo's `ai_call` rows were not read. The first
  thing to do on the demo after its deploy is press Explain once.
- **The demo deploy of these commits was not checked.**
- **Still open behind this:** M3's spec (queue item 6); §5.6's move of old
  invoice income; the smoke check of Release 10; "the monthly AI budget can
  be set to stop, not warn".

**P7: Bryan answered all fifteen decisions as recommended (10/13)** and added
two things: a fourth level, **Viewer** (sees everything in the company
read-only; for a board member or an investor), and **"nothing"** as a
may-create choice. They are recorded in the spec, §10, and the task
migration is corrected to `crm` 0036.

**P7 phase 1 is built, committed and pushed (`31e13a8`), and not released.**
The tables, the three migrations (`tenancy` 0014, `work` 0010 with the data
step, `crm` 0036 with its task half), the rule in `apps/work/permissions.py`,
`manage.py client_teams_dry_run`, and `tests/test_client_teams.py`. The
spec's "As built: phase 1" says what is wired, what is ruled and not yet
opened, and the readings Bryan ruled on (1, 2, 4 and 5 stand; 3 overruled).

- **One release-day change, by Bryan's ruling:** a client's project is
  deleted only by whoever made it or by the client owner; anyone else who may
  change it sets it to cancelled.
- **Applied to the laptop's `execsnowhq_local`** after the gate was green: 4
  default teams, 3 portal users placed as Manager, 12 projects and 86 tasks
  given a team, as the dry run said. Not in production.
- **Golden files regenerated on Bryan's yes, twice, each for one cause:** in
  `31e13a8`, `converted_goals.json` and `converted_projects.json` gain the two
  new columns; in the commit after it, `claude_requests.json` and
  `prompt_constants.json` gain the no-em-dash sentence. The real-session
  fingerprints are still 4 identical.
- **The model is now told to write no em dashes** in the four drafting
  prompts (rows, consolidate, mirror, pros and cons). The filter stays. No
  real call has been made with the new prompts.
- **P7 phase 2 is built on `dev` and not released** (the commit after
  `9645a16`): the practice's Teams card on a client company's page, the Team
  field on projects and tasks with a filter by team, and the invitation's
  team, level and may-create. No migration. The spec's "As built: phase 2"
  has five readings for Bryan, the first being that **an assistant does not
  set teams up** (P7-8's two halves disagree). **Not seen in a browser.**
  Phases 3 (the client owner's card) and 4 (the portal for members, managers
  and senior leaders) are not started.
- **How phase 1 is released is now "Tomorrow: Release 12", at the top:** all
  of `dev`, after the dry run on production and Bryan's yes.

### Later on 10/14 UTC (the evening of 10/13 Mountain): one ruling and two invoicing fixes

All on `dev`, pushed, each on a green gate, **none released, none seen in a
browser.**

| Commit | What |
|---|---|
| `a1dd5e6` | P7: the client owner may delete a colleague's task, as a project. A task the practice made or assigned stays untouchable |
| `37661d3` | Invoicing: payment terms. The practice's default under Settings → Finance → Paid invoices; each schedule's and each invoice's own; the due date worked out from them; printed on the invoice. **Migration `billing` 0003** |
| `23faf54` | Invoicing: a recurring invoice can be edited (client, lines, day, terms, income category, how to pay, covering email), for the invoices it writes from then on; recorded from and to. **Migration `billing` 0004** |

- Both billing migrations are additive with no data step, applied to the
  laptop's `execsnowhq_local`, and not in production.
- **Then, the same evening, the bank import from statements:** OFX, QFX and
  QBO files (`235787e`, no migration), a PDF statement read by Claude
  (`6f17916`, **migration `finance` 0012**, and the new dependency `pypdf`),
  and one PDF statement in the demo's seed. The specs are the two sections
  added to `docs/p5_finance_accounting.md` on 2026-10-14.
- **The release carries six migrations:** see "Tomorrow: Release 12".
- Bryan accepted P7 phase 2 and its readings 1, 2 and 3 (an assistant does
  not set teams up). Phases 3 and 4 are not started.

## The night of 2026-10-12: the call's backlog, a spec, and ten fixes

**Read this after the section above, then "Tonight's state" below, which is
as it was on 10/10 except where this says otherwise.**

**Production is unchanged: `main` at `a4037fb`, Release 10.** Everything
below is on `dev`, pushed, and not released. The demo deploys from `dev` and
applies the three new migrations itself at start; **that deploy was not
checked.**

**Earlier on 10/12:** two M2 fixes (`c06279e`, empty forecast lists say
"None."; `82cffe4`, the month's forecast kept by a daily job,
`finance.keep_month_forecast`), and the demo was reseeded onto `82cffe4` by
Bryan, with the forecast data in it. Queue items 1, 3 and 4 below are done;
item 2, Bryan's look at stop 2, is still his.

**The record of the 10/12 call** (`61aef34`):

- `docs/beta_feedback_2026-10-12.md` is the backlog, each item with a status
  and, for tonight's, the commit that built it.
- `docs/p4_billing.md` §9 is the pricing heard on the call, not decided.
- `docs/p7_client_teams_permissions.md` is the **spec for client teams and
  permissions, with fifteen decisions open (§10). No code.** The one to
  read first is P7-1: "their current rights" is what a Manager of the
  default team has, not what a Member has.

**Ten quick fixes, each its own commit on a green gate:**

| Commit | What |
|---|---|
| `f86df49` | Portal "Where we are": goal cards stay in the current order while a client proposes another; the proposal is a list; the Goals box is full width |
| `4d43f57` | Work: a goal card in rows (title; status, date, owner; progress and bar) |
| `800987c` | Tasks: sorted by due date by default, with a sort control on board and list |
| `7a3f4b5` | Meeting queue: the practice by name; a practice task to anyone on the team; a client's task filed under goal, project and task, existing or new, keeping its assignee; portal seats read live |
| `0401a1a` | Contacts and companies: LinkedIn and Alignable links. Settings, Tags (rename, remove). **Migration `crm` 0035** |
| `891aa9c`, `67536fc` | Notes: search matches part of a word in the body; folders. **Migration `notes` 0003** |
| `ffd8ca0` | Template builder: any section can be taken out; "On the prospect's map" on each. **Migration `strategy` 0018** |
| `795f762` | Strategy map: no em dashes in drafted text; the mirror, values and next steps editable on the PDF card |
| `32daa97` | Replies: a sentence under the title |
| `562397a` | Test only: an invitation to an address outside the client's domain signs in by link |

- **The three migrations are additive, with no data step, and are applied to
  the laptop's `execsnowhq_local`.** None is in production. At the next
  release they ride with `finance` 0009 and 0010: five in all, none
  destructive, so no dry run is owed.
- **The laptop's qcluster needs a restart and `ensure_schedules`** to have
  `finance.keep_month_forecast`; production gets that schedule only when
  `ensure_schedules` is run there after the release.

**Open from tonight, each Bryan's:**

1. **Done 2026-10-13, on Bryan's yes (see the section above).** As it was
   written: **Telling the model not to write em dashes** changes the prompts, and the
   prompts are in the v2, classic and v3 golden files
   (`claude_requests.json`, `prompt_constants.json`). Goldens are regenerated
   only on his yes. Until then the filter (`apps/strategy/dashes.py`) is what
   keeps them out of drafted rows, mirrors and pros and cons.
2. **Melissa's assignment bug was not reproduced** from its one line. What
   was found and fixed is in `7a3f4b5`'s message. If it happens again: who
   was named, whether they had a portal sign-in at the time, and which
   button was pressed.
3. **Words on the PDF that still cannot be changed for one session:** the
   ones that come from the template (a next step's label, the two paths'
   titles and lines, the rated items' labels, the chart's heading, the header
   chips' labels, a custom section's questions). They are changed on the
   template, for sessions started after.
4. **"What you have changed" and "How good it has been"** on the Forecast tab
   still hide when empty; only the two lists he named say "None."
5. **Nothing built tonight has been seen in a browser by anyone.**

Tests at the last code commit, by `scripts/gate.sh`: **3051 backend passed
(3 skipped, 2 xfailed), 997 frontend**, migration check and type check clean,
the v2 and v3 golden files unchanged.

## Tonight's state (end of 2026-10-10 Mountain)

**Production is `main` at `a4037fb`: Release 10, 2026-10-11 01:28 UTC.** `dev`
is three commits ahead, at `0abb177`. The runbook has the observed record of
every release through 10 (`docs/phase7_cutover_runbook.md`, "Releasing a
migration").

**Release 10 put P6 M1, Bookkeeping, in production**
(`docs/p6_m1_reconciliation_month_close.md`): sub-categories with combine,
split, archive and remove; the CPA's chart as the starting chart (§5.4) and
the CPA's worksheet export; reconciliation, month close and guided mode with
"Explain this step"; the "Estimated tax payment" mark on an owner draw and
the year-end facts; bulk actions on entries; the Getting started dismissals;
and invoice income entered by the kind of invoice (§5.6). M1 was accepted by
Bryan on the demo before it went.

- **Nine migrations,** applied in the waiting worker, all OK: `tenancy` 0012
  and 0013, `finance` 0003 to 0008, `billing` 0002.
- `finance` 0008 was added at the release, on Bryan's choice: production's
  chart had no "Retainers", so it adds one under "Client fees" for Executives
  Now and points recurring invoices at it. From the release on, payments on
  recurring invoices go to Retainers and on one-off invoices to Project fees
  with no setting touched.
- **§5.6's move is specified and not built.** Every invoice payment
  Executives Now recorded before Release 10 still sits on the "Client fees"
  parent. The move (each to Retainers or Project fees by its invoice's kind,
  closed months included, totals asserted unchanged) is in the spec under
  "The move, for books that already have invoice income on the parent". It is
  built and run only on Bryan's word, as part of a release, after a dry run.
- **Not done at Release 10:** nothing in it had been seen in a signed-in
  browser on production when it went out; production's database was not read
  afterwards; `/healthz` was sampled only from R3 on; the backup relied on
  was the 08:03 UTC dump, 17 hours old, with no fresh one taken.
- Recorded for later, not built: **"the monthly AI budget can be set to stop,
  not warn"** (M1 §12). Until then a person pressing a button is held only by
  the 20 a day below and, on the demo, by the key's own limit in the
  Anthropic console.

**P6 M2, the cash forecast, is built on `dev` in two stops and not released**
(`docs/p6_m2_cash_forecast.md`; its decisions table §12, the brief beside it
§12a, and an "As built" section for each stop).

| Commit | What |
|---|---|
| `a94c74e` | The M2 spec, and the runbook's Release 10 record |
| `849f854` | **Stop 1:** the forecast from known and regular lines, the card, the floor, the screen with 30, 90 and 180 days by week and 12 months, the dashboard line, the download, and the `forecast` module ("Cash forecast"; needs Bookkeeping; off for existing practices). Migration `finance` 0009 |
| `0abb177` | **Stop 2:** planned lines and what-ifs, changes to a line with undo, "how good it has been", "Explain this forecast", "Review with Claude", the setting "Include client names in AI explanations", and the demo's forecast data. Migration `finance` 0010 |

- Both migrations are additive with no data step, and are applied to the
  laptop's `execsnowhq_local`. Neither is in production.
- **Stop 1 was on the demo and timed there:** Forecast tab 110 ms median,
  dashboard line 88 ms, so no cache was added.
- **Stop 2 is pushed and not yet on the demo in any way that can be looked
  at.** The push deploys the demo by itself and the demo applies 0010 at
  start, but **that deploy was not checked**, and until the reseed the demo
  has the module off and none of the seeded forecast data.
- **Pressed AI calls:** "Explain this step", "Explain this forecast" and
  "Review with Claude" share one limit of 20 a day per practice and never go
  past the monthly AI budget. The worker's daily cap counts only what nobody
  asked for (decided 10/10).
- **Not proven:** nobody has seen any M2 screen in a browser; no real key has
  answered Explain or Review (a fake answers in the tests); nothing in M2 has
  run on real books.
- Tests at `0abb177`, by `scripts/gate.sh`: **2975 backend passed (3 skipped,
  2 xfailed), 971 frontend**, migration check and type check clean.

**The brief for the rest of P6 is `docs/p6_finance_expansion_brief.md`,**
saved verbatim from Bryan on 10/10. **It is the source for M3 and M4.** Where
a recorded decision in a spec differs from it, the decision holds (M2 §12a
shows how that was done for M2). The CPA's chart note for M4 is in M1 §5.4.

### The demo as it is set up

- **demo.getexecutivesnow.com**, Railway project `execs-now-hq-demo` (id
  `792ddb0f-a2fb-45a0-9034-fafca1d4d81f`), environment `production`, web
  service `execs-now-hq`, database `railway`. It deploys from `dev` on every
  push, applies its own migrations at start, and has **no worker**.
- **The practice is Summit Operations Partners,** fictional, owned by "John
  Carter", who signs in as `bryan.baker@getexecutivesnow.com` with the
  Internal Google client. Its books run January 2025 to today: 21 months
  reconciled and closed through September 2026, October in progress.
- **Mail goes only through the redirect.** `DEMO_MAIL_REDIRECT` on the demo
  service replaces every recipient with one address before a message is
  built, and it goes out from `DEMO_MAIL_FROM`. Empty, the demo sends
  nothing. The setting refuses to exist anywhere but the demo. Because there
  is no worker, **approving a digest on the demo sends it at once**, inside
  the request, and a digest whose window has passed is marked expired at the
  next page load. Production is unchanged by either.
- **A reseed empties the demo's database and rebuilds it, and keeps three
  things:** Django's own tables (sites, migrations and the rest of
  `demo.DJANGOS_OWN`), the owner's **Gmail connection**, and the practice's
  **Anthropic key**. The key's own limit in the Anthropic console is the
  guard on the demo's AI spend.
- **Changing a variable on the demo service** was refused to Claude Code by
  the permission check; variable changes go to Bryan as a copy-paste block.

**Reseeding, in three steps, each a paste-back:**

1. **The pre-check, read-only, run by Bryan.** Claude Code's own run of it
   was refused twice by the permission check ("production reads"), so it is
   handed over. Save the script below to a file, then in the Claude Code
   prompt:

   ```
   ! cd ~/projects/execs-now-hq && railway ssh -p 792ddb0f-a2fb-45a0-9034-fafca1d4d81f -e production -s execs-now-hq -- "echo $(base64 -w0 <the file>) | base64 -d | python manage.py shell"
   ```

   ```python
   import os
   from django.conf import settings
   from django.db import connection
   from django.db.migrations.executor import MigrationExecutor
   from apps.crm.models import GmailConnection
   from apps.tenancy.models import Tenant, TenantSecret
   from apps.tenancy import demo
   print("ENV", settings.APP_ENVIRONMENT, "| DB", settings.DATABASES["default"]["NAME"])
   print("COMMIT", os.environ.get("RAILWAY_GIT_COMMIT_SHA"))
   ex = MigrationExecutor(connection)
   print("UNAPPLIED", [str(m[0]) for m in ex.migration_plan(ex.loader.graph.leaf_nodes())])
   for t in Tenant.objects.all():
       print("PRACTICE", t.pk, t.slug, "| oauth_client", t.oauth_client, "| from", t.from_address)
   k = demo.kept_mail_connection()
   print("WOULD_KEEP", None if k is None else {a: k[a] for a in ("user_email", "email_address", "send_as_address", "oauth_client")})
   print("SECRETS", TenantSecret.all_objects.count())
   with connection.cursor() as c:
       for t in demo.DJANGOS_OWN:
           c.execute(f'SELECT count(*) FROM "{t}"')
           print("OWN", t, c.fetchone()[0])
   k = demo.kept_ai_key()
   print("AI_KEY would keep", None if k is None else {"owner_emails": k["owner_emails"], "last4 set": bool(k["last4"]), "cipher bytes": len(k["ciphertext"]), "verified_at": k["verified_at"]})
   ```

   These lines are cut from the script used on 10/8 to 10/10, which lived in
   a session's scratch folder and is **not in the repo**; the cut-down copy
   here has not itself been run.
2. **Read what comes back. Reseed only if all of these hold;** otherwise stop
   and say which does not:
   - `ENV` is `demo` and the database is `railway`;
   - `COMMIT` is the commit meant to be looked at, and `UNAPPLIED` is empty;
   - `WOULD_KEEP` is not `None` (the Gmail connection will be kept), and its
     `oauth_client` is what the seed is given as `--oauth-client`;
   - `AI_KEY would keep` is not `None`;
   - Django's own tables are there, with their counts noted to compare after.
3. **The reseed,** which Claude Code has been allowed to run, about three
   minutes:

   ```
   railway ssh -p 792ddb0f-a2fb-45a0-9034-fafca1d4d81f -e production -s execs-now-hq -- python manage.py seed_demo --database railway --ff-email bryan.baker@getexecutivesnow.com --oauth-client internal
   ```

   It prints its counts, which are reported back; for the forecast they are
   under `forecast` (cash today, the floor, the 90-day low, the first week
   under the floor, lines by kind, planned, what-ifs, changes, not counted,
   likely annual, months kept).

## Tomorrow's queue

In this order.

1. **Reseed the demo** onto `0abb177` by the three steps above. Before
   reading anything else, confirm the deploy itself: `COMMIT` is `0abb177…`
   and `UNAPPLIED` is empty, which is the first evidence that `finance` 0010
   applied there.
2. **Bryan's look at stop 2 on the demo.** First time any of it is in a
   browser, and the first real answers from Explain and Review. What he
   finds is fixed in M2, each fix its own commit, gate green.
3. **Empty forecast lists say "None".** **Done 10/12 (`c06279e`)** for "Not
   counted" and "Likely annual, to confirm", the two Bryan named; "What you
   have changed" and "How good it has been" still hide when empty. As it
   was written: Bryan's ask, not built. Which lists
   are meant (Known, Regular, Planned, Changes, Not counted, Likely annual)
   and whether a list that hides itself when empty should show instead is to
   be settled with him or from his look; today "Likely annual" and some
   others are not drawn at all when empty.
4. **A first-of-the-month snapshot job.** **Done 10/12:**
   `finance.keep_month_forecast`, daily at the practice's midnight, a no-op
   once the month's is kept (M2 spec, "As built: after stop 2"). No
   migration; **production gets the schedule only when `ensure_schedules` is
   run there after the release**, and the laptop's qcluster needs a restart
   and `ensure_schedules` to have it. As it was written: today the month's forecast is kept
   the first time the forecast is worked out in that month, so a month the
   owner never opens the app has no row in "how good it has been". The job
   takes it on the 1st for every practice with the module. It goes in the
   worker's schedules (`ensure_schedules`); it calls no AI; the lazy snapshot
   stays as the fallback. The demo has no worker, so its seed keeps taking
   them itself.
5. **Release M2,** on the word "release", by "Releasing a migration":
   `finance` 0009 and 0010, both additive, nothing destructive, so no dry
   run is owed, and any migration item 4 adds rides along. The module stays
   off for Executives Now until Bryan switches it on in the Practices area.
6. **M3's spec,** from `docs/p6_finance_expansion_brief.md`, in the shape of
   M1's and M2's: what it proposes in plain terms and a decisions table with
   a recommendation on each. No code until Bryan answers.

Still open behind these, in no order: §5.6's move for production's old
invoice income (above); a smoke check of Release 10 in a signed-in browser on
production; "the monthly AI budget can be set to stop, not warn".

## Next (as of 10/5, updated after Release 7; older than the two sections above)

In this order.

**0. Release 7 went out 2026-10-08 03:03 UTC (`main` = `dev` = `6627b03`,
then documents).** It carried everything that was on `dev`: the digest
schedule below, the "team" wording, and two rounds of portal, Tasks and Value
report work (invitations, the open goal, goal order, goal proposals, width,
buttons, the logo fallback). Seven migrations, record in the runbook. **Item 1
below was released without its laptop checklist**, on the owner's yes to the
dry run: the checklist is now a production smoke check, and Bryan still sets
Draft on to Friday 3:00 PM himself. Reminder emails are live;
`DIGEST_REMINDERS_ENABLED=false` stops them without a release.

**1. The digest schedule: ~~check it on the laptop, then release it~~ released
in Release 7; check it in production.**
(`docs/digest_schedule.md`; §12 is the as-built record. Built on `dev` 10/5 in
three phases, not released.)

- **Restart the laptop's qcluster first.** It does not reload code, and the
  tick is what drafts, marks late and sends reminders.
- Bryan runs the checklist on localhost:5200 (it is in the 10/5 chat):
  Settings → Digests with Draft on and Send on; Digests → "Generate now" with
  the send time in 2 minutes; Update this draft; Send now… with the whole
  email shown first; a digest going "Not sent on time" and being sent by hand;
  an approved digest staying on the screen; and the three reminder emails in
  Mailpit at http://localhost:8125 (ready, last call, not sent), none of which
  contains a digest's text.
- **If it passes, release.** This one has a migration that writes data, so it
  goes by "Releasing a migration" in the runbook **with a dry run of the data
  step and Bryan's yes before "release"**. `tenancy 0011` adds two columns to
  the practice and runs one `UPDATE` that gives each practice the day before
  its send day at the same hour, which is exactly today's behavior. The dry
  run prints each practice's before and after. `work 0006` and `crm 0032` ride
  along and run no SQL, so the worker will list three migrations as waiting.
- **Then Bryan sets Draft on to Friday 3:00 PM on his own practice in
  production** (Settings → Digests). The release deliberately does not choose
  it for him; until he does, Executives Now is draft Sunday 8:00 AM, send
  Monday 8:00 AM.
- **The same release carries** the "staff" to "team" wording (`c075766`) and
  the flaky Strategy test fix (`f9e8e04`). Neither has a migration.
- `DIGEST_REMINDERS_ENABLED=false` stops the reminder emails without a release
  if they turn out to be noise.

**2. Finish the v2 test session in production, then run a v3 one.**
The v2 test session for **Test Prospect** is in production and has been taken
as far as the diagnostic. Finish it from the diagnostic onward: the call, the
map, the PDF, and converting to a client. Then run a **v3** test session. This
is the rehearsal for **Cory Muscato's session on Thursday 10/8 at 1:00 PM**,
and it gates P3 part two phase 2 (custom sections): no part two code until both
are done and anything they turn up is fixed. The first real Claude call on v3
happens here.

**3. The profile picture bug.** On `feature/profile-picture` (commit
`7094dcf`), not on `dev` and not released. Adding a picture failed for Bryan
with an error saying the file was not the correct type, when it was.
**Waiting on Bryan's details: the file's type, its rough size, and the exact
wording of the error.** Nothing has been investigated yet. Its migration is
numbered `tenancy 0011`, which **now clashes with the digest migration** of the
same number on `dev`: when the branch is rebased onto `dev` it must be
renumbered to follow it (the laptop's database already has both applied, under
their different names).

### Where things are at the end of 10/5

- **Releases 5 and 6 are live.** Production is `main` at `e4222f6`. Release 5
  (`31286cf`): the Pipeline board, clickable rows, the Notes grid, the top bar
  with Sign out and the staff session rules, Settings by role, and Profile
  with the editable name. Release 6: sign-in wording, the practice address
  chosen by the owner, "Mark as a client" with its undo, and the digest day
  and time. Both passed Bryan's production smoke checks. Neither had a
  migration.
- **Bryan's production digest schedule is send Monday 8:00 AM.** Production
  still drafts a fixed 24 hours before, so his weekly digests are written
  **Sunday 8:00 AM** and are not sent unless approved by Monday 8:00 AM. That
  holds until the digest release in item 1 and his change to Friday 3:00 PM.
- **Shawn (Blue Sky Business Consulting) is set up on the beta.** Bryan is
  telling him about the new sign-in wording ("Practice sign-in"), "Mark as a
  client", and that **his strategy template needs two rated items**. **Any
  staff Shawn invites must be added as Google test users first**, or Google
  will refuse their sign-in while the app is unverified
  (`docs/google_verification.md`). His feedback and what was done about each
  item is in `docs/beta_feedback.md`.
- **Still open:**
  - the `/hq` homepage copy, needed for Google verification;
  - connecting a second mail account or a separate inbox (roadmap; needs its
    own spec; `docs/beta_feedback.md`, item B);
  - stage automations offered as a prompt when a card moves (roadmap;
    `docs/ui1_pipeline_board.md` §8);
  - two-factor authentication (roadmap;
    `docs/ui3_top_bar_settings_profile.md` §10);
  - UI 3 phase 5, pictures wherever initials show (after the picture bug).

### Branches at the end of 10/5

| Branch | Holds | State |
|---|---|---|
| `main` | Releases 1–6 | Live in production, at `e4222f6` |
| `dev` | `main` plus: the "team" wording, the flaky test fix, the digest schedule (three phases, with `tenancy 0011`, `work 0006`, `crm 0032`), and documents | **Unreleased.** Pushed. The demo deploys from it, and applies these migrations to its fictional data when it starts |
| `feature/profile-picture` | The profile picture (UI 3 phase 4) and its own `tenancy 0011` | **Unreleased, held for the bug.** Pushed. One commit on top of `31286cf`; needs rebasing onto `dev` and its migration renumbered |
| `backup/dev-2026-10-05` | A copy of `dev` as it was before the picture was moved off it | Nothing that is not on the two branches above. Safe to delete once the picture is released |

The laptop's `execsnowhq_local` has every `dev` migration applied, **and** the
picture's column from when that branch was on `dev`; `dev`'s code ignores it.

## What this is, in one paragraph

Execs NOW HQ is a multi-tenant SaaS for fractional executives, built by the
owner (Bryan Baker, Executives Now, an operations fractional; Noble Rose LLC)
with Claude Code (CC) doing the coding and this chat doing product direction,
review and the prompts CC receives. Django 5.2 / DRF / Postgres / Django-Q2
(ORM broker, no Redis); React + Vite + TypeScript; WeasyPrint PDFs; the Claude
API; Google (Gmail send and read, Drive read, Speech-to-Text); GCS for files
and backups. **Production runs on Railway at app.getexecutivesnow.com since
the cutover on 9/30.** Repo github.com/bbakersc55/execs-now-hq: work on
`dev`, release to `main`.

## The three environments, and their rules

| | Production | Demo | Laptop |
|---|---|---|---|
| Where | app.getexecutivesnow.com (Railway project `execs-now-hq-live-app-no-testing`) | demo.getexecutivesnow.com (Railway project `execs-now-hq-demo`) | `~/projects/execs-now-hq` |
| Code | `main`, only on the word **"release"**, full suite green | `dev`, every push | `dev` |
| Data | the real practice | a fictional practice (Summit Operations Partners), seeded | **`execsnowhq_local`**: a scrubbed copy of production (B7) |
| Worker | the Railway `qcluster` service | **none**; the demo sends nothing and reads no mailbox or Drive | a local qcluster is fine on `execsnowhq_local`; never on `execsnowhq_dev` |
| Migrations | **only by "Releasing a migration"** (runbook): confirm the newest backup, release, apply in the waiting worker with `railway ssh --service qcluster -- python manage.py migrate`, redeploy web (`railway redeploy --service execs-now-hq -y`) | applied by web at start (`APP_ENVIRONMENT=demo` only) | CC applies when `.env` names `execsnowhq_local` and the suite is green; no backup needed |
| Backups | nightly 08:00 UTC (02:00 MT), Railway cron → `gs://execs-now-hq-db-backups/execsnowhq_prod_*` | none needed | none needed: `./scripts/refresh_dev_from_prod.sh` rebuilds it from the newest production dump, scrubbed |
| Files | `gs://execs-now-hq-media` | its own demo bucket (refuses production's) | `STORAGE_BACKEND=local` (`media/`): production's files are not on the laptop |

- **`execsnowhq_dev`** (the laptop's pre-cutover database) is the fallback until
  runbook **C12, about 10/14**. Then the owner says so and it's deleted (dry
  run first). Nothing points at it.
- **The release sequence is proven** (Release 2, 10/3, P1 + P2, 7
  migrations): push to new code serving took **4 min 22 s**, and the **old web
  kept serving throughout** (polled every 5 s, every response 200). The worker
  paused about 68 s. Releases 3 and 4 the same day took 2 min 10 s and 2 min
  28 s. Recorded in `docs/phase7_cutover_runbook.md`.
- **The demo is reached without relinking the CLI**, which stays linked to
  production: `railway ssh -p <demo project id> -e production -s execs-now-hq --
  <command>`. Check `$APP_ENVIRONMENT` is `demo` in the same command.
- Laptop session (five tabs): see `docs/05_dev_environment.md` §8. Tab 1 runs
  `gcloud config configurations activate execs-now-hq`, `git pull`, the
  installs, `migrate` and `ensure_schedules`; then runserver 8100, qcluster,
  Vite 5200 and Mailpit 8125. The old daily `backup_db.sh` is no longer part
  of it.

## Where it stands

| | State |
|---|---|
| Modules 0.5–6 | Built and in use; details below in "Open threads" |
| Phase 7 cutover | Done 9/30 (Release 1); B7 laptop move done 10/2 |
| **P1** vocabulary, roles, branding | **Released 10/3** |
| **P2** Practices admin and onboarding | **Released 10/3**; Blue Sky created and its owner invited 10/3 |
| **P3** strategy template builder and session v3 | **Released 10/3 (Release 4, `main` at `0a07322`)**, phases 1–5; **no screen seen in a browser yet**; the demo dry run was waived |
| **P3 part two** custom sections, AI per section, per-session rewordings | **Spec approved 10/3** (`docs/p3_part2_custom_sections_ai.md`); **phase 1 done** (v3 pinned by 43 golden files); phase 2 waits on the two test sessions |
| **UI 1** Pipeline board, clickable rows, Notes grid, Work outlines | **Released 10/5 (Release 5, `main` at `31286cf`, no migration)**. Spec and UI backlog: `docs/ui1_pipeline_board.md`. Seen by Bryan on the laptop; **not yet smoke-checked in production** |
| **UI 3** top bar, Sign out, staff session rules, Settings by role, Profile (name) | **Phases 1–3 released 10/5 (Release 5)**. Spec: `docs/ui3_top_bar_settings_profile.md`, D1–D12 accepted |
| **UI 3 phase 4** profile picture | **Built, NOT released.** Commit `7094dcf` is on the branch **`feature/profile-picture`** (on GitHub), one commit on top of `31286cf`. **It is not on `dev`**, which was rebuilt without it on 10/5 so the rest can be released and the demo never gets the broken control. Migration `tenancy 0011` (one nullable column, `membership.avatar_id`) is still applied to `execsnowhq_local`; `dev`'s code ignores the extra column. Held back for the upload bug. To bring it back once fixed: rebase the branch onto `dev`, and if `dev` has gained a `tenancy` migration by then, renumber 0011 to follow it. `backup/dev-2026-10-05` on GitHub is the old line of `dev`, kept as a copy |
| **Beta feedback, Shawn 10/5** (`docs/beta_feedback.md`) | **Released 10/5 (Release 6, `main` at `e4222f6`, no migration):** "Practice sign-in" / "Client sign-in"; the practice address chosen by the owner (own email allowed); "Mark as a client" and its undo; digest day, time and time zone with a one-time prompt. No migration |
| UI 3 phase 5 pictures wherever initials show | Not started |
| **Digest schedule** Draft on / Send on, Update this draft, Send now, late, reminder emails | **Built on `dev` 10/5 (`21a3be2`, `c37f101`, `9eac353`), NOT released.** Spec and as-built: `docs/digest_schedule.md`. Release needs the dry run of `tenancy 0011`'s data step and Bryan's yes. Not seen in a browser by anyone yet |
| "Staff" to "team" wording; flaky Strategy test fix | **On `dev` (`c075766`, `f9e8e04`), NOT released**; they go with the digest release |
| **P6 M1** Bookkeeping: sub-categories, the CPA's chart, reconciliation, month close | **Released 10/10 Mountain (Release 10, `main` at `a4037fb`, nine migrations).** §5.6's move of old invoice income not built. See "Tonight's state" |
| **P6 M2** cash forecast | **Both stops built on `dev` (`849f854`, `0abb177`), NOT released.** Stop 2 not yet looked at on the demo. See "Tonight's state" |
| **P6 M3** | Not specified. Source: `docs/p6_finance_expansion_brief.md` |
| **Strategy document redesign** (S2) | **Built on `dev`, NOT released** (needs `strategy 0019`, `tenancy 0016`). P3 spec §10 |
| **P6 M4** personal finance | **Spec** `docs/p6_m4_personal_finance.md`. **Stop 1 built on `dev`, NOT released** (needs `finance 0013–0015`, `personal 0001–0002`). Stops 2–4 not built |
| P4 billing | **Spec written** (`docs/p4_billing.md`), ten decisions open, no code |
| Microsoft 365 transport | **Mail transport built on `dev` 10/27** (`docs/m365_transport.md` §9–10); OneDrive notes and Microsoft sign-in not built |
| Backlog, built 10/3, **released 10/3 (Release 3)** | dashboard blocks drag across rows; "Not duplicates" on Merge duplicates (migration `crm 0031`); remove an accepted diagnostic question |

Tests on `dev` at the end of 10/5 (`9eac353`, with the digest schedule):
**2361 backend passed (3 skipped, 2 xfailed), 683 frontend**, goldens
unchanged, real-session fingerprints 4 identical.

Tests as of 10/5, on the released commit `e4222f6`: **2280 backend passed (3
skipped, 2 xfailed), 665 frontend**, goldens unchanged, real-session
fingerprints 4 identical. (`feature/profile-picture`, at `7094dcf`, was 2250
and 649 when it was built on the earlier base.)

Tests on `dev` as of 10/3, after P3: the backend suite green (P3 added 65
tests across four files), **566 frontend**. The
tenant-isolation and role-boundary families are registries that fail on an
unregistered model; the isolation family now includes the platform owner.

### P1 in brief (`docs/p1_practices_vocabulary_branding.md`)

- **Vocabulary:** a tenant is a **Practice**. Roles are shown by name:
  practice owner (FF), associate (CF), assistant (VA), client owner (FCC),
  client team member (ECC). Codes stay in code and data. Guard tests fail on a
  role code or "tenant" in readable text.
- **Branding per practice** (Settings → Branding, practice owner only): display
  name, logo, mark (favicon and email sign-off), primary and accent colors,
  email footer.
  - **Contrast rules:** primary vs white ≥ 4.5 and accent vs primary ≥ 3
    block a save; accent vs white only warns, and the accent is never used
    for text on white.
  - **Unbranded default:** an unbranded practice shows its name over neutral
    grays, with an initials mark.
  - **Where it applies:** the portal, client emails and PDFs. Staff screens
    keep the product look and show the practice name under the wordmark.
- **The product favicon** comes from `assets/brand/mark-transparent.png`,
  derived from the owner's `mark.png` (original kept).

### P2 in brief (`docs/p2_practices_admin_onboarding.md`)

- **Platform owner** = the owner's own sign-in (set in production 10/3 with
  `set_platform_owner`). The sidebar switch goes between "Executives Now" and
  "Practices". In the Practices area **no practice is bound**: it shows each
  practice's record and totals, and the feedback staff send, never anything
  inside a practice (`docs/data_and_the_platform_owner.md`).
- **Practices:**
  - **Create:** sets your defaults (AI $50 a month and $5 a day unattended,
    digests held, no strategy template, neutral brand, never Executives Now's
    addresses).
  - **Invite owner:** sends only when you press it, and is refused while the
    practice's Google client isn't set up.
  - **Archive / unarchive:** archiving signs everyone out, stops the jobs and
    keeps the data.
- **Signed-out pages** name no practice. Only an emailed link names one
  (`?via=` token), and the tab shows the product icon until the practice is
  known.
- **The beta agreement** (`docs/legal/beta_agreement_v1.md`) gates a practice
  owner on the server until accepted; the acceptance records a hash of the
  text.
- **Getting started:** a seven-item checklist on the practice owner's
  dashboard, computed from the practice's own data.
- **Feedback button** on every staff screen; it goes to the platform owner.
- **Two Google OAuth clients** (D1):
  - **Executives Now** keeps its Internal client.
  - **Outside practices** use a second client, External/Testing, in a new GCP
    project: staff are added as test users, and connections expire every 7
    days until Google verifies the app.
  - **Staff sign-in is email-first:** the address decides which client.

### P3 in brief (`docs/p3_strategy_templates_session_v3.md`)

- **Three template formats, side by side.** Classic, v2 ("Operations —
  focused") and **v3**, made in the builder. A session keeps the format it was
  created with, frozen in its snapshot. Nothing converts one into another.
- **The builder** (Strategy → Manage the templates → New template; practice
  owner only): eight parts in session order.
  - The practice's own pre-call questions, rated items with labels, fixed
    diagnostic questions, mirror questions, values, the two paths and scope.
  - Settings per template: diagnostic questions per session (1 to 8, default
    3), the rating scale line, each path's words on the PDF, and how Claude
    describes the practice.
  - "What they value" can be taken out. A template needs two rated items to be
    **ready to run**; one that is not ready cannot start a session.
- **A v3 session:** pre-call questions, ratings on the call, a diagnostic
  proposed from the pre-call answers (plus "Propose from the ratings" and "Add
  a question" by hand, eight at most), the mirror under its own questions, the
  five-row card map, the two-page PDF with the template's own chips, labels and
  path copy. Conversion and prep are the existing code.
- **Every AI output still lands as proposed.** A rejected map row or
  diagnostic question is told to Claude and not proposed again.
- **v2 is pinned.** `tests/test_strategy_v2_golden.py` holds 34 golden files
  each for a classic and a v2 session, and
  `scripts/strategy_session_fingerprints.py --check` compares the real sessions
  on the laptop against a baseline. **Both must stay identical; a golden is
  never regenerated to make a test pass.**
- **"Restore from seed" is refused** (and not shown) for a practice with no
  classic or v2 template, so another practice cannot take the Operations
  questions.
- **Deferred from P3, now in part two:** custom sections; adding, removing and
  reordering sections; talk tracks; starting from a copy of a classic or v2
  template; the pre-call form preview in the builder; next-step sentences in a
  v3 covering note.
- **v3 is pinned too** (part two, phase 1): `tests/test_strategy_v3_golden.py`,
  43 files for a builder template and one session from it. They must stay
  identical for a template that uses no part two feature.
- **Found and left alone, for the owner to decide:**
  - Duplicating "Operations — focused" in the old editor gives a *classic*
    copy. Do not duplicate it before 10/8.
  - On a card map (v2 and v3) the mechanics note never prints, whatever its
    PDF flag says.

## Blocked on the owner

1. **Blue Sky Business Consulting** (blueskybizconsulting.com, owner Shawn):
   **the practice is created and the owner invitation is sent (owner, 10/3).**
   **Bryan meets Shawn Monday 10/5 in the afternoon.** For that meeting:
   - Shawn signs in under Staff with Google, passes Google's unverified-app
     warning, and accepts the beta agreement.
   - Branding is Shawn's own to set (Settings → Branding); the mark must be a
     **square PNG, at least 64 × 64 px, up to 500 KB**.
   - He connects Gmail, enters his Anthropic key, and reconnects Google every
     7 days until the app is verified.
   - His first template is built in the builder (Strategy → Manage the
     templates → New template). "Restore from seed" is not offered to him.
   - Any staff he adds must be test users on the External client first.
2. **Google verification** (`docs/google_verification.md`), the owner's steps:
   - **Steps 4–6 are done (owner, 10/3):** the consent screen and the External
     client exist, its two variables are in production on web
     (`execs-now-hq`) and `qcluster`, and Shawn is a test user.
   - **Open before step 7** (the demo video, which opens on that page): the
     `/hq` homepage copy, and the privacy policy beside it (drafted; have a
     lawyer read the policy).
   - Then record the demo video (script drafted) and submit with the drafted
     scope justifications.
   - Answer Google's emails, then the annual CASA assessment for the
     restricted scopes, then publish.
   - Scope classifications and costs are marked to confirm in the console.
3. **P4 and Microsoft 365 decisions** (the tables at the end of each spec).
5. **C12** (about 10/14): say the word, and `execsnowhq_dev` is deleted with a
   dry run.

## Rules and decisions that live outside the repo docs (or are easy to miss)

- **Every AI output and every client email goes through a human.** Review
  queues everywhere; `hold_all_digests` ON; magic links and PIN resets are the
  deliberate direct sends. Platform mail (invitations, feedback notices) goes
  through Executives Now's Gmail and its Outbox.
- **Nothing sends without the full body on screen** (incident 9/22). **A
  rewording never changes a question's shape.**
- **White-label:** a client never sees the product's name. Signed-out pages
  show the product icon but no product name; a practice's own surfaces wear its
  brand.
- **Migrations:** SQL shown before generating, always.
  - **Laptop:** applied by CC on `execsnowhq_local` once the suite is green,
    destructive or not.
  - **Production:** only through the release sequence, after that day's
    backup.
  - **Demo:** migrates itself at start.
  - Never a migrating start command for production.
- **Branches:** work on `dev`; `main` only on "release" with the full suite
  green at the merged commit.
- **Snapshot rule:** a strategy session freezes its template at Start.
- **Goals → Projects → Tasks**, three levels; clients create tasks and projects,
  never goals. **Percent-of-tasks-done is never a headline.**
- **Stakeholders are contacts**, not users; digests reach contacts without
  logins.
- **AC-3.5 faithfulness:** every Claude narrative asserts nothing absent from
  its input.

## Gotchas that cost time before

- **qcluster does not reload** on code changes; restart it after a backend
  commit or migrate. `runserver` does reload: a model change breaks the dev
  server until its migration is applied.
- **Production's web service is named `execs-now-hq`**, not `web`.
- `railway ssh` reaches only an active instance. The waiting worker is how a
  migration reaches production; a shell in old web would run old code.
- **A refused web deployment shows FAILED, and the old one keeps serving** until
  web is redeployed after the migration.
- Hard-reload Vite before calling a frontend change broken. `pip install`
  after pulls.
- On the laptop, mail goes to Mailpit unless the address is on the dev
  allow-list (`.env` plus Email settings).
- **Google OAuth:** the Internal consent screen accepts getexecutivesnow.com
  only. The External client is for everyone else and has Testing mode's 7-day
  expiry until verified. `gmail.settings.basic`, `gmail.readonly` and
  `drive.readonly` are (to confirm) restricted scopes, which means CASA.
- **GCP** project `execs-now-hq`: buckets `execs-now-hq-db-backups` and
  `execs-now-hq-media`; the app uses the service-account key (Railway:
  `GOOGLE_SA_APP_JSON`), backups the backup service account. On the laptop,
  `gcloud auth login` expires: run `! gcloud auth login` when a gcloud step
  fails with "Reauthentication failed".
- **Secrets:** `FIELD_ENCRYPTION_KEY` is in the owner's password manager;
  losing it loses every stored token and key.
- **Test data:** Acme Facilities and Noble Baker are test rows in production;
  keep them out of external demos. "Fake Practice, LLC" exists only on the
  laptop and goes with the next refresh from production; leave it.

## Open threads

1. **Phase 6 live checks** wait on a real reply on an app-started thread.
   Confirm `gmail.readonly` was granted by reading `GmailConnection.scopes`, not
   by memory.
2. **Brett Murray, Grime Fighters:** the strategy session ran 9/29 as planned,
   and the map and PDF were sent the same day. **Proposal pending, no decision
   yet.** That is one of the two real sessions the exit criteria ask for.
   Module 4B's manual checks still need real goals with measurements (Brett, if
   he signs).
3. **Referral-touch drafts** were scheduled to appear on 10/7 for approval.
4. **Meeting ingestion:** live pickup of a brand-new Google Meet meeting had not
   been observed at last check.
5. **Not seen in a browser yet:** P1 (Branding screen, portal colors), P2
   (Practices, switcher fix, agreement, checklist, feedback), the three
   backlog items, and **all of P3** (the builder, the v3 live view, the v3
   PDF, and that the v2 screens look as they did). The click-by-click checklist
   for one v3 and one v2 session is in the 10/3 chat; the demo is ready for it
   ("Operations — focused" is its default, migration applied), and needs an
   Anthropic key entered on its AI usage screen.
6. **Cory Muscato, Thursday 10/8 at 1:00 PM:** his session is created in production on
   "Operations — focused", **with the form not sent**. It was created before P3
   was released, so its questions were frozen first. Bryan emailed Cory a
   questionnaire some time ago and has **no reply yet**. Run it on v2 as
   planned.
7. **No real Claude call has been made on v3.** Every P3 test scripts Claude;
   how the model words v3 diagnostic questions and rows is unseen until the
   two test sessions in production ("Next", above).
8. **Small items, open, each the owner's to decide:**
   - The v2 **"Six Key Components"** label wording (the live view's summary
     card and the PDF heading say six; "Operations — focused" rates five).
   - The **mechanics note does not print on a card map** (v2 and v3), whatever
     its PDF flag says.
   - **Duplicating "Operations — focused"** in the old editor gives a
     *classic* copy. Do not duplicate it before 10/8.
   - The **`/hq` homepage copy**, needed before Google verification step 7.
   Any change to the first three touches v2, so it moves the v2 goldens and
   needs the owner's yes before they are regenerated.

9. **From Release 5 (10/5):**
   - **Staff session rules are live:** quitting the browser signs staff out
     (not when the browser restores its last session), and 12 hours without a
     click, key or scroll signs them out; background refreshes do not count.
     **Client portal sessions are unchanged (30 days)**, waiting on Bryan's
     decision; the recommendation is to leave them.
   - **"Act as a colleague" is the client owner's control only.** Staff view a
     client's portal with "View portal as…". **Nobody can view the app as an
     associate or assistant**; that would be a new permission, not specced.
     The associate's and assistant's menus and Settings are covered by tests,
     not seen by eye.
   - **The flaky test below is fixed** (`f9e8e04`, 10/5): the same three
     steps now run before Apply. Kept here for the history.
   - **A flaky frontend test, not an app fault:** `session prep > ticks all,
     then unticks one, before applying` in `Strategy.test.tsx` failed once in
     a full run. Its last three lines act on the session screen after "Apply"
     has navigated away; the test's one-route router reopens the screen as a
     session called "template", and the control is briefly absent. Reproduced
     on demand, passes 15 of 15 alone. Fix when convenient: move those three
     lines before the Apply click. The test and the screen are unchanged from
     Release 4.
   - **Notes:** a locked note is found by every filter and by its typed title;
     its contents never match. The open-note page is two columns up to 1760px.
   - **Pipeline:** a column loads 100 cards, then "Show more" loads the rest
     in one response; fine for Beta, revisit for a column in the thousands.

## Roadmap (recorded, not scheduled)

- **From 10/5, recorded in the UI specs:** per-stage automations offered as a
  prompt when a card moves, including calendar events and nurture campaigns
  (`docs/ui1_pipeline_board.md` §8); two-factor authentication
  (`docs/ui3_top_bar_settings_profile.md` §10: staff get it from Google
  Workspace's 2-Step Verification; client users are the gap).

- **P3 part two** (`docs/p3_part2_custom_sections_ai.md`), which takes in the
  items P3 deferred: custom sections and talk tracks, AI per section,
  per-session rewordings and the form preview, the PDF and covering note,
  starting from a copy. Two releases.
- **Then**, in this order: P4 billing, Microsoft 365 transport per its spec,
  the campaign/sequence editor, task dependencies, private tasks, notes stacks,
  Google Calendar, an in-app AI helper (inbox triage first), other AI models
  through an integration layer, dark mode, per-practice labels for
  Goal/Project/Task, and a multi-site service-business strategy template.
- **Post-Beta modules**, in `CLAUDE.md`'s order: invoicing (P4 §2) → basic
  financials → e-signature → simple HRIS → connectors → product billing and
  self-serve onboarding.

## Beta exit criteria (from the build plan)

5 real digests approved and delivered, 2 real strategy sessions end to end
with a PDF sent, 10 real meeting proposals reviewed with the approve/reject
rate reported (27 reviewed on 9/26: 18 approved, 9 rejected), a backup
restored at least once (done), all mandatory test families green.

## How we work (keep this rhythm)

- The owner runs everything through copy-paste blocks with a stated target
  (terminal, Claude Code, Railway shell). A separate Aris project must never
  be touched.
- CC finishes a unit, commits on `dev`, pushes, and reports: what's tested
  end to end versus written but not exercised, and anything not seen in a
  browser. The owner reviews several units at once.
- Prompts to CC are specific: the gap, the rule, the test, "commit, stop".
