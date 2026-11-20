# P14 — Intake forms (built 2026-11-19, branch `intake-forms`)

First use: SkyRun Park City's new-owner and property intake, written into
SkyRun's Track. One form type, "New owner and property", built so other
types can follow. Not a general form builder. Code: `apps/intake/`, the owner's
bundle `frontend/src/forms/` (built on its own by `vite.forms.config.ts`), the
staff screens `frontend/src/screens/Intake*.tsx`.

## The flow

1. A company manager (or the practice owner) starts an intake with the owner's
   name and email. ENHQ makes a personal link. **ENHQ never emails an owner:**
   staff use Copy link, Copy message, or Open in my email (a `mailto:` with the
   owner's address, a subject and the message from the form's template), for
   the first invite and for a reminder. Each copy or open is recorded.
2. The owner fills it in, phone first, with no account. Answers save as they
   go; the same link brings them back. Links expire 30 days after the last
   activity (a manager can reopen one) and are rate limited.
3. On submit, the company's managers and above and the practice owner are told
   in the app and by email (`intake_notice`, direct to sent). The email carries
   no answers.
4. A manager or the practice owner opens it, edits any answer (live on the
   welcome call), makes the staff-only choices, sees the warnings and "What will
   be sent", and presses Send to Track.
5. The worker writes it to Track step by step, saving every id as it comes;
   on success ENHQ makes the onboarding project and tasks, holds the owner's
   dates, deletes what Track now holds, and locks the record. Later changes
   are made in Track.

A manager can fill the whole form in on the owner's behalf from the review
screen (same sections, same saving).

**Who:** the practice owner, and the client company's Client owner, anyone with
Senior leadership of all its teams, and anyone at Manager or Senior leadership
on one of its teams. Nobody else (not associates or assistants; owner,
2026-11-19). Note: ENHQ puts a new portal user on the company's default team
**at Manager** unless the client owner lowers it (`work.teams.UNCHOSEN_LEVEL`),
so every SkyRun portal user still at that default counts as a manager here.

The feature is switched on per company by the practice owner (company page,
"Owner intake forms"), and needs the company's Track connection.

## The owner's form

Sections, one per screen: Welcome · About you · Tax details · The property ·
Bedrooms · Other places people sleep · Bathrooms · Amenities · Home details ·
Getting in · Your own stays · Documents · Review and submit · Thank you (with
"Add another property", which starts a new submission with the owner's
details, and tax id, carried over; one property per submission).

The fewest questions: a follow-up appears only when the answer before calls for
it; bedrooms, bathrooms, other owners, codes and date ranges are add-another
blocks. Running summaries on each room ("Bedroom 2: Queen x1, Twin x2, sleeps
4"). A bathroom's type is worked out from its fixtures: any tub makes it full,
a shower without a tub three-quarter, neither half.

**Tax:** the owner chooses a business Tax ID or a Social Security number. Tax
ID: collected (refused if it looks like an SSN), shown afterwards as its last
four. SSN and bank details: never collected; the form says they're added in
the owner portal later.

### Look (white label, owner 2026-11-19)

The owner sees nothing of Execs NOW HQ, Executives Now, Noble Rose, or any
practice user's name or email: not in the form, page titles, tab icon, error
and expired-link pages, upload answers, or the address. The footer is the
form's contact line only. `tests/test_intake_white_label.py` walks every
owner-facing page and response on ENHQ's host and on a form domain and fails
on any of those names; `frontend/src/forms/forms.test.tsx` scans the bundle's
source and fails on any import from the rest of the app.

- **Logo:** SkyRun's `logo.svg` (the plain mark): its charcoal lettering
  disappears on dark, so it sits on white or cream; the "Vacation Rentals"
  footer version is too wide for a phone header. Favicon: the SR circle.
  Uploaded per form in settings; an SVG is shown through `<img>` and served
  sandboxed.
- **Type:** Montserrat (skyrun.com's), free under the OFL, vendored
  (`frontend/src/forms/fonts/`).
- **Colours** (from skyrun.com's CSS and the logo; contrast checked), editable
  per form:

| Use | Hex | Note |
|---|---|---|
| Buttons, progress, selected | `#428227` | white text 4.7:1 |
| Hover, pressed, links on cream | `#356A1F` | the site's `#509E2F` hover fails with white text (3.4:1) |
| Headings / body | `#36424A` / `#4A4A4A` | 9.8:1 / 8.4:1 on cream |
| Page / cards / borders | `#FAF9F5` / `#FFFFFF` / `#DEE2E6` | |
| Notes | `#006BA6` | |
| Errors | `#B3261E` | the site's `#C89797` fails (2.5:1) |
| Decoration only | `#F6BC26` | logo gold; never text |

### Addresses and the form's own domain

Until a domain is set, links are `PUBLIC_BASE_URL/forms/<slug>/<token>`
(`https://app.getexecutivesnow.com/forms/skyrun-park-city/<token>`), and the
form's settings warn that owners would see getexecutivesnow.com. With a domain
set, links are `https://<domain>/<token>` and the slug leaves the path.

On a form's domain only the form answers (`apps/intake/hosts.py`, middleware
before WhiteNoise): its pages, its API (`/api/f/...`), its logo and icon, and
its own bundle (`/static/forms/...`). Everything else gets the form's own plain
not-found page. The page's policy allows nothing from any other origin.

**Adding a domain (Bryan, in Railway and DNS; nothing here does it):**

1. Pick a host name on a domain SkyRun controls, for example
   `owners.skyrunparkcity.com`.
2. Railway, project `execs-now-hq-live-app-no-testing`, service `execs-now-hq`
   (web): Settings → Networking → Custom Domain → add the host name (port 8080,
   as `app.getexecutivesnow.com`). Railway shows a CNAME target
   (`….up.railway.app`) and a TXT record (`_railway-verify.<subdomain>`).
3. At SkyRun's DNS provider: a CNAME from the host name to that target, and the
   TXT record. Wait for Railway to show the certificate as issued.
4. Railway variables on the web service: `INTAKE_FORM_HOSTS=<host name>`
   (comma-separated for more than one). It joins `ALLOWED_HOSTS` and the CSRF
   origins. Add it to the `mcp` service too, as a reference
   (`${{execs-now-hq.INTAKE_FORM_HOSTS}}`), as every web variable is. The
   variable change redeploys web.
5. In ENHQ: Owner intake → Form settings → "The form's own domain" → the host
   name → Save. The warning goes once the host is in `INTAKE_FORM_HOSTS`.
6. Check: `https://<host>/` shows the form's not-found page; a link opens the
   form.

## The CSV mapping (Tally export, 156 columns)

| CSV cols | Tally question | New form | Track home |
|---|---|---|---|
| 0–2 | Submission ID, Respondent ID, Submitted at | — | the submission record |
| 3, 4 | Owner name, last name | About you → first, last | primary contact first/last |
| 5 | Entity name | About you → name on the account | owner name, taxName |
| 6–9 | Mailing address | About you → mailing address | owner address and tax address; contact address |
| 10 | Mobile | About you → mobile | contact cellPhone; owner phone, taxPhone |
| 11 | Email | About you → email | contact primaryEmail; owner email |
| 138 | Preferred contact | About you → text, call or email | owner notes |
| 147 | How you heard | About you → how you heard (+ who) | owner notes |
| 134, 148–154 | Additional owners ×3 | About you → other owners (name, email, mobile, portal access) | contacts linked to the owner; shares by the reviewer |
| 135, 136 | "Portal Access?" | each other owner's "own login to the owner portal" | none; the portal-invite task |
| 12 | Tax ID or SSN | Tax details → the choice | decides whether taxId is sent |
| 13 | Tax ID number | Tax details → Tax ID | owner taxId |
| 14 | SSN | not asked | never sent |
| 15–19 | Bank fields | not asked | never sent; checklist task |
| 23–26 | Property address | The property → address | unit address; unit name and short name |
| 27 | Property type | The property → type | unit lodgingTypeId |
| 139, 140 | Ready + date | The property → ready | start date and Contract Effective Date defaults; task due dates |
| 141, 142 | Current bookings | The property → booked date ranges | ENHQ + checklist task |
| 43–115 | Bedrooms, sleeping surfaces, bed types | Bedrooms → beds with + / −, own bathroom | rooms (bedroom) with beds, sleeps; maxOccupancy |
| — | — | Other places people sleep | rooms (`common`) with beds, sleeps |
| 28–42 | Bathrooms, fixtures, sinks | Bathrooms → fixtures with counts | rooms with roomType and fixtures |
| 116, 117 | Amenities, workspace | Amenities → common list, gondola, anything more | amenitiesIds; per-unit rows for counts |
| 118 | Heating and cooling | Home details | HVAC Notes; Heating, Air Conditioning, Ceiling Fan |
| 119 | Parking | Home details | Parking Instructions; parking amenities; "Parking Pass" keyword |
| 120 | Wi-Fi and internet | Home details | Internet Service Provider, Wifi Network Name, Wifi Password, Wifi Router Location & Notes; Wifi amenities |
| 132 | TV | Home details (+ how many TVs) | Cable or Satellite TV Provider/Notes; TV amenities; per-unit TV count |
| 123 | Trash | Home details | Trash Service Provider, Trash Pickup Day (by handle), Trash Notes |
| 124 | HOA | Home details | the five HOA fields |
| 125, 126 | Heat tape | Home details | Heat Tape Notes; Heat Tape (internal amenity) |
| 127, 143, 144 | Snow removal | Home details | Snow Plowing/Shoveling Provider and Notes |
| 128, 145, 146 | Landscaping | Home details | Other Maintenance or Service Notes |
| 131 | Water softener | Home details | Other Maintenance or Service Notes; Water Softener (internal amenity) |
| 121, 122 | Rental permit | Home details | Nightly Rental Permit; none → checklist task |
| 20–22, 129, 130, 155 | Smart lock, door, owner closet, alarm codes | Getting in | security codes by type |
| 133 | Dates for own use | Your own stays | held in ENHQ; Owner Reservation blocks once bookable |
| 137 | Insurance declarations page | Documents (up to 5 files) | kept in ENHQ under the company; checklist task to upload it |

Custom fields fed by built-in questions are listed in `schema.BUILTIN_FIELDS`;
every other field is off, answered by the owner (generic input with the
manager's label, help and section), or filled in by staff at review.

## Track (what was proven live, 2026-11-19)

SkyRun's key is a server key. The first write test was refused by Track's
**firewall**, not the key: an AWS load balancer (`Server: awselb/2.0`) answers a
bare HTML 403 to a body with an **@example.com** email. 555 numbers, made-up
addresses and body size pass. Test records use plus-addresses on Bryan's own
mailbox. Track also answers 406 to a request with no `Accept` header.

Write behaviour (test records left inactive: unit 221 with rooms 1502–1507,
owner 265 / company 301, contacts 10919–10920, ownership 225):

- `PUT` and `PATCH /pms/units/{id}` change only the fields sent.
- With room configuration on (settable at create or later), the unit's bedroom
  and bath counts follow its rooms' types (a `PATCH` of a room's type moves
  them); a `PUT` of counts is ignored. Room `sleeps` and the unit's
  `maxOccupancy` are not worked out from beds: ENHQ sends them. A room posted
  without `roomType` is accepted with an empty one, so ENHQ always sends it.
  Beds are accepted in a `common` room and don't count as a bedroom.
- `amenitiesIds` replaces the unit's own list; a dropped amenity keeps its
  per-unit row with `isEnabled: null`. The area's (node's) amenities always
  stay. Every SkyRun area carries the same 65 (Wi-Fi and TV among them).
- Custom fields: an object keyed by the field's `reference`
  (`pms_units_…`); a choice takes the handle or the integer id. A name or a
  string id answers 200 and **clears** the field.
- Unit blocks need a bookable unit ("Unit was not found, or the unit is not
  bookable"); whether one works on a bookable but inactive unit is untested.
  An owner can be linked to an inactive unit.
- Search: contacts by email yes; owners by email no, units by street no (ENHQ
  pages through them).
- SkyRun's 224 owner-unit links are all `standard` / `pmc`; contract 1
  ("Standard 30") is on 212.
- Make's unit call sends no `isBookable`, and unit 211 (Make's) is not
  bookable: new units start not bookable until the form's setting says otherwise.
- The unit's `notes` reach booking channels (channel keys get every description
  field), so the "insurance page on file" note is not written; the checklist
  task covers it.

**The Track client** (`apps/scorecard/track.py`) gained `send()` for writes.
Every call sends `Accept: application/json` and a User-Agent naming ENHQ; a
firewall 403 is said as "Track's firewall refused the content"; Track's own
refusal messages are passed on; a 429 waits and tries again; logs carry the
method, the path with ids taken out, and the status.

## Sending

The plan (`apps/intake/plan.py`) and the writer (`track_writer.py`) are pure;
the worker runs them (`tasks.run_send`). Order, "the least mess when a step
fails": contacts first (deletable by API, and where the firewall refuses
content), then the owner and the unit (which can't be deleted by API), rooms,
amenities and custom fields, codes, and the owner-to-unit link last so the
owner's statements and portal never show a half-built unit. Then in ENHQ: the
tasks, the owner dates held, the secrets deleted, the record locked.

Every id is saved the moment Track gives it. "Try the rest again" skips what
is done and, for a step that was started but never recorded, looks for it in
Track first (contact by email, owner by name, unit by name and street, room by
name, code by type, the link by unit), so nothing is made twice.

**An existing owner is left untouched** (owner, change 4): only the unit and
the owner-to-unit link are written; the reviewer sees where the intake differs
from Track's record; new other owners become a checklist task.

Owner active (as Make does) and new units not bookable are the form's
defaults; the production proof keeps the owner inactive.

Staff-only choices: the area (must be picked; Make uses node 14), contract (by
id, "Standard 30" preselected), Management Agreement Type (Full Service), start
date and Contract Effective Date (both default to the ready date, set
separately), unit type (from the bedroom count), unit name and short name (the
street address), a bathroom's type, total sleeps, other owners' shares,
existing owner or reused contacts, the amenities worked out from other answers
(each tied to its answer, pre-ticked and untickable, skipped when the area
already has it), and the staff custom fields (Trigger/Automation Keywords
preset from the answers).

## After sending

- **Owner dates:** held in ENHQ. Every hour (`intake.place_owner_dates`) and
  with "Place owner dates now", once Track reports the unit bookable, each range
  is blocked with the reason Owner Reservation. "Not bookable" keeps them held;
  any other refusal goes to the managers with Track's words; a range whose end
  passes is marked expired and the managers told; held over 30 days, a weekly
  reminder; a manager can cancel.
- **Checklist:** one project per property ("New owner onboarding #N · street"),
  tasks from the form's template, assigned to whoever pressed Send, due from the
  ready date (or the send day when that is blank or past). Titles never carry
  the owner's name or contact details. Starting list in `defaults.CHECKLIST`,
  including "Right after the listing is made bookable, press Place owner dates
  now" and the four onboarding holds marked "(needs the unit bookable in Track)".

## Sensitive values

The tax id, every code and the Wi-Fi password are Fernet-encrypted in
`intake_submission_secret`. On screen the tax id shows its last four; a code or
the password shows nothing unless a reviewer reveals it, and each reveal is a
`SubmissionEvent` with who and when (written once, never changed). The owner's
link never shows any again once saved. Deleted when Track confirms it holds
one, last four included; for a submission never sent, 90 days after its last
change (`intake.purge`, daily) or at once on discard. Codes live in Track only.
Nothing from a submission is exposed to the MCP server or AI features (no tool
reads these models; task titles carry nothing from the answers but the street
in the project's name).

## Settings (managers and above, and the practice owner)

Look and address (brand name, title, colours, logo, icon, contact line, slug,
domain) · Track's lists, read about hourly and kept (`TrackListSnapshot`), with
"Refresh from Track now" · new units bookable or not; owners active or not ·
the common amenities and the groups owners see (Website Badges and Internal Use
hidden) · property and code types offered · every unit custom field off / owner
/ staff · the sleeps table (a bed type new in Track starts at 2, flagged) · the
checklist template · the invite and reminder messages.

## Data and migrations

`intake` 0001 (`intake_form`, `intake_submission`, `intake_submission_file`,
`intake_submission_secret`, `intake_submission_event`, `intake_send_run`,
`intake_owner_date`, `intake_track_list`); `crm` 0061 (`company.intake_forms_enabled`,
producer `intake_notice`); `notify` 0007 (kind `intake`); `work` 0016 (task
source `intake`). All additive. people-hris (accounts 0007, centers 0005,
people) and billing-cadences (billing 0015) use none of these apps or numbers,
and neither changes `crm/services/secrets.py`. Schedules `intake.place_owner_dates`
(hourly) and `intake.purge` (daily, 3:00) need `ensure_schedules` (R5b) at release.

## Proof

- Tests: `tests/test_intake_plan.py`, `test_intake_flow.py` (against the fake
  Track in `tests/intake_fake_track.py`, which has SkyRun's real lists, settings
  only, and the write behaviour above), `test_intake_white_label.py`, plus
  tenant isolation for all eight models and `frontend/src/forms/forms.test.tsx`.
- The production proof, prepared: `scripts/intake_track_proof.sh` sends one
  complete submission through this code to SkyRun's Track, creating a "ZZ TEST 2
  … DELETE ME" set (owner inactive, unit inactive and not bookable).
  It reads Track's lists, builds the plan with `plan.build`, and sends it with
  `track_writer.execute`: 2 contacts (`bryan.baker+zztest2-contact-one@…` and
  `…-two@…`), the owner (inactive, a made-up tax id), the two contact links,
  the unit "ZZ TEST 2 - ENHQ INTAKE PROOF - DELETE ME" (inactive, not
  bookable, area ZProperty Management, 2 Bedrooms, Condo), 5 rooms (King;
  Twin x2; a Queen sofa bed in the living room; a full and a half bath), its
  amenities and custom fields, a TV count of 2, a door and an alarm code, and
  the ownership on Standard 30 (standard/pmc). No blocks, nothing on any other
  record. Its guard refuses any write that isn't to skyrunparkcity.trackhs.com,
  to a ZZ TEST 2 name, or to an id this run created.
  - **Where it runs:** production's web container, under `manage.py shell`.
    The modules are unpacked into a new private folder
    (`mktemp -d /tmp/intake_proof.XXXXXXXX`), never the app's folder, and
    imported from the end of Python's path under the one name `intake_proof`,
    each checked to be this run's own copy, so nothing of the app's can be
    overwritten or shadowed.
  - **ENHQ's database:** one read (SkyRun's Track connection and its company,
    exactly one or it stops) in a `READ ONLY` transaction; then the connection
    is closed and any further query stops the proof. It writes nothing.
  - **Cleanup:** the remote shell removes the folder on any exit (success,
    failure, hangup, Ctrl-C, terminate), and the laptop's packing folder goes
    the same way. Progress (Track ids and step names, no values) is kept in
    `/tmp/zztest2_state.json` until the next deploy: a failed run carries on
    where it stopped, and a finished one stops before Track if run again.
  - **Checked on the laptop, 2026-11-19 (not against Track):** against the
    fake Track, a full run, a repeat (0 calls), a refusal at a code then a
    re-run (one set, no duplicates), no owner PUT or PATCH; the guard refused
    unit 221, owner 265, company 301, a non-ZZ unit and a block. Through a
    stand-in for `railway ssh` on a scratch database: the read-only read, the
    stop on a connection that isn't SkyRun's before any network call, and no
    folders left after a normal end, a hangup, Ctrl-C or terminate.
- The fake-Track run (2026-11-19, `INTAKE_FAKE_RUN_LOG`): a new owner, an
  existing owner (unit and ownership only, nothing on the owner), a refusal at
  the door code then "Try the rest again" (every earlier step found, none
  repeated), a lost answer found again, and owner dates held while the unit
  isn't bookable and placed once it is.
- The browser walk (2026-11-19): Playwright with the laptop's Chrome against a
  local server on a scratch copy of `execsnowhq_local`, the form on its own
  domain (`skyrun-forms.localhost`). The owner at 390 px (every section filled,
  submitted, the thank-you page) and at 1280 px; the expired, unknown-link and
  not-found pages; the reviewer's list, review (before and after picking the
  area), settings, and the practice owner's company card. Every request the
  owner's pages made went to the form's own domain. Two fixes came out of it:
  on a phone a focused field scrolls clear of the fixed step bar (WCAG 2.4.11),
  and the contact-preference cards wrap instead of squeezing three across.
