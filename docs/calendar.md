# Calendar

**Built 2026-10-27, on `dev`.** From the post-beta list; the stage rule is the
owner's Prospecting → Follow Up Needed example (2026-10-05,
`docs/ui1_pipeline_board.md` §8).

## What it does

- **One calendar per person.** Each member of the practice's team (practice
  owner, associate, assistant) connects their own, on their Profile ("Your calendar"; not Settings, which an assistant does not have):
  Google Calendar through the practice's own Google OAuth client, or, for a
  practice on Microsoft 365, their Microsoft 365 calendar through Graph and the
  same Entra app registration as mail. Clients never connect one and never see
  any of it.
- **Home: Today and tomorrow.** A panel first on the dashboard (first for a
  layout saved before it existed, too): each meeting's time, title (linking to
  it in the calendar), and the contacts and companies its attendees matched,
  each linking to its record. In the person's own time zone.
- **A company's page: Meetings.** Meetings whose attendees matched the
  company, on anyone's calendar in the practice, the last 30 days and the next
  14, with whose calendar each is on. Shown only to someone who may see the
  company (an associate, once assigned), and only the contacts they may see.
- **Add to calendar** on a task with a due date and on a follow-up's next step
  (the contact's page): a title, day, time and length, then an event on the
  person's own calendar. Nobody is invited.
- **A stage rule: "Offer a calendar event, at a time I pick".** For a contact
  entering a stage. When someone moves a card there on the board, the move
  asks "Put it on your calendar?" with the rule's title (merge fields work),
  a suggested day N days ahead and the rule's length; they pick the time, or
  Not now. A move with nobody to ask (an import, another rule, the contact
  page's stage change) adds nothing.

## What is read, kept and never read

- **Read:** each event's id, title, start and end, all-day, link, whether it is
  cancelled or private, and attendees' and the organizer's addresses. Named
  field by field: Google's `fields` mask (`providers.GOOGLE_FIELDS`), Graph's
  `$select` (`providers.GRAPH_SELECT`).
- **Never read:** an event's description or body. It is not in either list, so
  it cannot reach a prompt; nothing in the calendar feeds Claude at all.
- **Kept:** title, times, link, and the matches. **Attendees' addresses are
  used only for matching and are not stored.** Private and cancelled events
  are not kept.
- **Matching:** an address held by a contact (and that contact's company);
  otherwise a company by the address's domain, never the practice's own
  domain, a team member's, or a public mail domain (gmail.com, outlook.com and
  the like).
- **The window:** a day back to two weeks ahead, read whole every 15 minutes
  by the worker (`calendars.sync`, a new schedule) and by Home itself when the
  last read is over 30 minutes old (the demo has no worker). An event gone
  from the calendar within the window is removed; one that has passed stays,
  for the company page.

## Consent

Each provider's consent comes back to the redirect URI its client already
has (Google: `/accounts/gmail/callback`; Microsoft:
`/accounts/microsoft/callback`), told apart by its state, so **no new
redirect URI is needed**. The calendar's token is stored apart from mail's
(`tenant_secret` kind `calendar_refresh`), so connecting a calendar never
changes what mail or Drive can do. Disconnecting deletes the token and every
event read from it. Removing a member removes their calendar.

**Scopes to add:**

| Provider | Scope | Where |
|---|---|---|
| Google | `https://www.googleapis.com/auth/calendar.events` | Both OAuth clients' consent screens (Internal and External): Google Cloud console → APIs & Services → OAuth consent screen → Data access → Add scope. **Enable the Google Calendar API** in each client's project. `calendar.events` is a sensitive scope: the External client's verification adds it. |
| Microsoft | `Calendars.ReadWrite` (delegated) | The Entra app registration → API permissions → Microsoft Graph → Delegated. User consent; admin consent only where a directory requires it. |

## As built

`apps/calendars/` (models, `providers.py`, `sync.py`, `views.py`,
`tasks.py`), migrations `calendars 0001` (four tables), `crm 0053` (one
column, `stage_automation.event_minutes`), `tenancy 0023` (a choice, no-op).
Screens: `CalendarCard.tsx` (on Profile), `AddToCalendar.tsx`, `MeetingList.tsx`, the
Home panel in `Dashboard.tsx`, the company page's Meetings, the rule editor's
new action, the board's question. The demo seeds the owner's calendar with
four meetings today and tomorrow and one last week, matched to the cast, and
connects nothing.

Tests: `tests/test_calendar.py` (35): roles, isolation (one's own calendar,
matching inside the practice, a company one may see, a task in another
practice, the callback's practice), reading (kept and dropped, matching,
nothing of an address kept, the body never asked for, removal, a refused
read), Home's two days in one's own zone and an associate's narrower view,
Graph's reading and adding, adding a task and a follow-up step, the rule's
offer and its validation, the demo, disconnecting, removing a member. Plus
the frontend's.

## What only real accounts can confirm

Built to Google Calendar API v3 and Microsoft Graph v1.0; the fixtures in
`tests/fixtures/calendar/` are shaped from their references, not captured.

1. **Google's token holds only `calendar.events`.** Asked without
   `include_granted_scopes`, a calendar consent from the same Google account
   as mail is assumed to return a token scoped to the calendar alone. If
   Google folds mail's scopes in, nothing breaks, but the calendar token
   could do more than it needs.
2. **The `fields` mask** is honoured as written, so no `description` arrives.
3. **Recurring events** come back one by one with `singleEvents=true` (Google)
   and through `calendarView` (Graph), each with its own id.
4. **All-day events:** Google's `date`, and Graph's all-day start at midnight
   in the zone asked for (UTC here), are kept as midnight UTC and shown on
   their own date. A Graph all-day event in another zone may differ.
5. **`Prefer: outlook.timezone="UTC"`** makes Graph return every time in UTC.
6. **`$orderby=start/dateTime` with `calendarView`** is accepted.
7. **Private and confidential:** Google's `visibility` and Graph's
   `sensitivity` are what mark an event to leave out; an event shared from
   someone else's calendar may carry neither.
8. **Creating an event with a `timeZone`** of the practice's IANA name
   (`America/Denver`): Google accepts IANA names; Graph accepts IANA names as
   well as Windows ones (the reference says both).
9. **`calendar.events` verification** for the External client: a sensitive
   scope, which Google reviews; until then only test users can consent.
10. **Admin consent** for `Calendars.ReadWrite` in a directory that limits user
    consent, as for mail.
11. **Rate limits** for a practice of a few people reading every 15 minutes are
    far under both providers' quotas; not measured.

**The first real run:** connect a Google calendar and a Microsoft one, put a
meeting with a client contact's address on each (one recurring, one all day,
one private), open Home and the client's company page, then Add to calendar
on a dated task (1–8).
