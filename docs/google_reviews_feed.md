# Google reviews feed, version one — as built (2026-11-04)

A client company's Google reviews, from its Google Business Profile, feeding
its scorecard. Built on `dev`; not released.

## Connecting (company page, "Google Business Profile")

- **The practice owner starts it** (an associate sees the connection but no
  controls; an assistant and client users see nothing). **Whoever manages the
  client's Business Profile signs in with Google**: the consent's account
  picker lets that be the client's own Google account.
- **Through the existing OAuth client**, with
  `https://www.googleapis.com/auth/business.manage` **requested incrementally**:
  on its own consent, only when a company's profile is connected, asking for
  `openid email business.manage` and nothing else (no
  `include_granted_scopes`, so the grant never carries anyone's mail or
  Drive). It comes back through the client's one redirect URI,
  `/accounts/gmail/callback`, told apart by this consent's own state, as the
  calendar's consent is; nothing new is registered with Google.
- The refresh token is **stored encrypted on the company's connection row**
  (Fernet under `FIELD_ENCRYPTION_KEY`, as Track's key, HubSpot's and Besty's
  tokens are), never sent to a browser.
- **The account and location are chosen** from Google's own lists: the Account
  Management API's `accounts` and the Business Information API's
  `accounts/*/locations` (title and address). The location's resource name
  and the account's are stored. Choosing reads the reviews at once.
- **Test connection** asks for one review and says how many there are and the
  average. **Change** chooses another account or location (another
  location's stored reviews are dropped), or signs in with another Google
  account. **Disconnect** removes the connection, its token and its stored
  reviews; every KPI reading already made is kept.

## Reading

- **Once a day per location**, on the scorecard's existing hourly feed job
  (`scorecard.read_feeds`; no new scheduled job), then each reviews KPI once
  a day, as Track's feeds run.
- `GET https://mybusiness.googleapis.com/v4/accounts/{a}/locations/{l}/reviews`,
  `orderBy=updateTime desc`, 50 a page, **paged until a review already stored
  and unchanged is reached** (or the last page; at most 200 pages). New
  reviews are stored; a changed one (stars, text, update time or reply) is
  updated in place, **never duplicated** (unique per connection and review id).
- Kept for each review: Google's review id, star rating (1–5), comment,
  reviewer's display name ("A Google user" when anonymous), create and update
  times, and the reply's time. Kept for the location, from the same answer:
  the average rating and the total review count.
- **Not yet approved.** Google gives a project the Business Profile APIs only
  after approving its access request; until then every call answers with a
  quota of 0 (a 429 naming a limit of 0) or a 403. That is shown as one plain
  line, "Google hasn't approved this app's access to Business Profile reviews
  yet. The connection stays, and reviews are read once Google approves it.",
  on the card, on Test connection and as a fed KPI's error. The connection
  stays. An ordinary rate limit (a 429 without a zero quota) is not called
  unapproved.

## Measures (a KPI's "Feed from Google reviews")

Worked out from the **stored** reviews, per period of the KPI's cadence, the
Track feed's window (the last 13 closed periods the first time, the last two
each day after, and the open one "so far" when chosen), by the Sheets feed's
rules (a reading typed by hand is never replaced, none is deleted). Dates are
the practice's own.

| Measure | Kind | For a period |
|---|---|---|
| New reviews | Count | Reviews created in it |
| Average rating of new reviews | Rating | Their average stars (none when there were none) |
| Five-star share of new reviews | Percent | The share of them with five stars |
| New reviews with a given number of stars | Count | Those with the chosen 1 to 5 stars |
| Unanswered reviews at the period's end | Count | Reviews created by its last day and not replied to by then |
| Median days to reply | Duration | Of the replies made in it, from review to reply (in the KPI's unit) |
| Total reviews (all time) | Count | Every review created by its last day (added 2026-11-12) |

A measure must fit the KPI's kind (as Track's do); a per-person KPI is refused.
**Total reviews (all time)** is a running total, so it needs a KPI that rolls
up by Last: weeks added up into a month would count every review again. It
counts the stored reviews. The read never deletes one, so a review taken down
on Google is still counted.

## The cards

- **Google Business Profile** (connection), beside Track, HubSpot and Besty.
- **Google reviews** (read-only): the location, its average and count, and the
  latest ten reviews with their stars, date, reviewer and replied or not.
  Replying is done in Google.

## The demo

Connecting is **refused** in the demo, and nothing there reads Google (the
feed job skips reading in the demo). The seed connects **Stark Tool & Die,
Long Island**: a year of reviews (about three a month, most replied to within
four days, the latest not yet) read **through the real sync code** from a
stand-in for Google, and a "Reputation" scorecard page with four KPIs worked
out **through the real feed code**:
- Google rating (monthly, average);
- New Google reviews (monthly);
- Five-star Google reviews (monthly, the open month read so far), which the
  "Five-star review bonus" pays $5 each on (`docs/p6_m5_kpi_scorecard.md`);
- Total Google reviews (monthly, Last; added 2026-11-12).

## Verification

`business.manage` is added, with its justification, to
`docs/google_verification.md`. It is believed sensitive (no security
assessment); the console will say. The Business Profile API access request is
a separate approval, and until it is granted the "not approved" line shows.
The privacy policy and homepage need a line for it before submission.

## Proven, and how

- Tests with a fake Google (`tests/test_google_reviews.py`): the consent asks
  for the one scope and stores the token encrypted; a consent without it
  stores nothing; Google's account and location lists; paging until stored
  reviews are reached (one page once nothing is new); de-duplication; an
  updated review; every measure; the feed's readings by cadence and the
  tile's source; a measure that doesn't fit; the menu without asking Google;
  not approved by 403 and by quota 0, and an ordinary rate limit that is not;
  practice isolation (routes, the read job, the stored reviews); the owner,
  an associate, an assistant and a client user; Disconnect; the demo.
- Screens (`frontend/src/components/ScorecardReviews.test.tsx`).
- Headless Chrome of the cards and a KPI tile at 1366 and 390, on a scratch
  demo.
- **Not exercised:** a real Google sign-in with `business.manage`, and the
  real APIs, which need Google's approval of the project first. The v4
  reviews endpoint's fields are as Google documents them; whether a reply
  alone changes a review's `updateTime` is not confirmed, so a reply made to
  an older review may not be seen until that review changes (version two's
  notifications close this).

## Version two

1. **Pub/Sub notifications** (`NEW_REVIEW`, `UPDATED_REVIEW`) instead of only
   the nightly read: the account's notification setting pointed at a topic,
   a push subscription to the app, verified.
2. **Replying from the app**, as a draft a person approves before it is posted
   (`reviews.updateReply`), in line with review queues over automation.
3. Per-location measures for a client with several locations.
