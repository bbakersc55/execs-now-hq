Recorded answers for the HubSpot feed's tests (M5 part 5).

**Shaped from HubSpot's public API reference (developers.hubspot.com, read
2026-10-26, version 2026-09), not recorded from a live account.**
`pipelines.json` and `owners_page*.json` are whole answers. The object files
(`deals.json`, `contacts.json`, `calls.json`, `emails.json`,
`meetings.json`) are the records a search returns, as `results[]` items;
the test's stand-in applies the request's filters to them and pages them,
as the reference says search does, and answers `total`, `results` and
`paging.next.after`. The rate-limit bodies are the reference's 429 shape;
`TEN_SECONDLY_ROLLING` is the name its troubleshooting section gives the
ten-second limit. The values are invented. When a real account's answer is
first captured, replace these with it and see what breaks.
