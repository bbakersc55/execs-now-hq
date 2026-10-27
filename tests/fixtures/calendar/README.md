# Calendar fixtures

Shapes from Google Calendar API v3 (`events.list` with `singleEvents=true` and a
`fields` mask, `events.insert`) and Microsoft Graph v1.0 (`/me/calendarView`
with `$select` and `Prefer: outlook.timezone="UTC"`, `POST /me/events`), and
their OAuth token responses. **None captured from a real account.** Addresses
use `acme.invalid`, `initech.invalid` and `contoso.example`. What only real
accounts can confirm is listed in `docs/calendar.md`. Used by
`tests/test_calendar.py`.
