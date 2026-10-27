# Microsoft Graph fixtures

Shapes from Microsoft's Graph v1.0 and identity platform v2.0 reference pages
(message resource, create message in MIME format, send message, list messages
with `$filter`, get MIME content `$value`, attachment upload session, error
responses, OAuth 2.0 authorization code and refresh token responses).

**None of these were captured from a real Microsoft 365 tenant.** Addresses use
`contoso.example` and `acme.invalid`; ids are shortened placeholders in the
documented formats. Each behaviour only a real tenant can confirm is listed in
`docs/m365_transport.md` §10. Used by `tests/test_microsoft_transport.py`.

Sign in with Microsoft and OneDrive notes (2026-10-27): `organization*.json`,
`me_signin.json`, `token_signin.json` (its ID token built by the test), the
drive and folder listings, the delta pages, `meeting_notes.html` (the shape
Graph's `?format=html` conversion of a Loop page is assumed to have) and
`transcript.vtt` (Teams' WebVTT, voice-tagged). The Word document is made by
the test with python-docx. Used by `tests/test_microsoft_signin_onedrive.py`.
