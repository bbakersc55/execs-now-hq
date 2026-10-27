# Microsoft 365 as a practice's mail and files

**Spec for owner review · 2026-10-03 · the transport built 2026-10-27 (§9;
what only a real tenant can confirm, §10)**

A practice on Microsoft 365 (Outlook, OneDrive, Teams) has no Google account.
Today it couldn't sign in, send, collect replies or ingest meeting notes. This
spec adds **Microsoft Graph** as a second provider, **chosen per practice**,
beside Gmail and Drive. Decisions are **D1–D7** in §8.

> **What I'm sure of and what I'm not.** The Graph endpoints below are the
> documented ones. Four things are marked **[verify]** because Microsoft's
> behavior or policy is the kind that changes or differs by tenant
> configuration. Each gets a proof-of-concept call against a real Microsoft 365
> account before its part is built.

---

## 1. What stays exactly as it is

The provider is plumbing. Everything that decides what happens is untouched:

- **The Outbox**: the one send queue and send log, approvals, the review
  queues, dev-mode routing to Mailpit and the allow-list.
- **What a reply means** (`apps/crm/services/inbound.py`): matching a reply to
  its thread and contact, unmatched handling, the Replies screen.
- **Meeting ingestion's logic** (`apps/meetings/ingest.py` from "here is a
  document's text" onward): dedupe by meeting, exclusions, Claude parsing,
  proposals, the review queue, nothing created without approval.
- Digests, referral touches, the strategy PDF, magic links: they ask the
  Outbox to send, and don't know who carries it.
- Branding (P1), the Practices area (P2), roles, isolation.

## 2. What changes

| Today (Google) | Added (Microsoft) | Where |
|---|---|---|
| `GmailTransport.send` (raw MIME) | `GraphTransport.send` | `apps/crm/services/transport.py`, chosen by `tenant.mail_provider` |
| `verify_send_as` (Gmail send-as list) | alias check by test send (§4) | same |
| `GmailReader.thread(id)` | `GraphReader.conversation(id)` | same; `inbound_poll.py` unchanged apart from the reader it is handed |
| `EmailThread.gmail_thread_id` | `EmailThread.graph_conversation_id` | new column |
| `GmailConnection` + token refresh | `MicrosoftConnection` + Entra token refresh | new table |
| `DriveClient` (a Drive folder) | `OneDriveClient` (a OneDrive folder) | `apps/meetings/`; `ingest.py` takes either |
| Google sign-in | **Sign in with Microsoft** for staff of a Microsoft practice (D1) | `apps/accounts/` |
| Settings → Email: Connect Gmail | Connect Microsoft 365 | the same screen, by provider |
| Meetings: watch a Drive folder | watch a OneDrive folder | the same screen, by provider |

**One provider per practice** (`tenant.mail_provider = google | microsoft`),
set when the practice is created (the Practices area gains the choice) and
changeable only by you (**D6**).

## 3. Sending

- **Graph:** create the message as a draft (`POST /me/messages`), then send it
  (`POST /me/messages/{id}/send`). Two calls instead of one, because the draft
  returns the **`conversationId`** and **`internetMessageId`** before sending.
  The app stores those, as it stores Gmail's `threadId` today.
  `/me/sendMail` returns nothing, so a sent message couldn't be tracked.
- **Threading.** Today the thread token rides in the Message-ID we set.
  **[verify]** whether Exchange keeps a Message-ID the app supplies. If it
  doesn't, nothing breaks: replies are matched by `conversationId` (§5), and
  the token stays the fallback for replies from other clients.
- **Attachments** (the strategy PDF, the flyer): inline in the draft up to
  3 MB; larger ones through an upload session.
- **Sent Items:** Graph sends save a copy, as Gmail does today.
- **Limits:** Exchange Online allows 10,000 recipients a day and 30 messages a
  minute per mailbox, far above a practice's volume. A 429 is retried after
  the time Graph says.

## 4. The practice's alias (info@…)

Gmail lists the send-as addresses; Graph has **no equivalent list**. Sending
from an alias in Microsoft 365 needs either *Send As* rights on a shared
mailbox, or the tenant setting that allows sending from a user's own proxy
addresses (**[verify]**: availability and default on the practice's plan).

**Recommendation (D3): Verify alias by a test send.** The app sends a short
message from the alias to the connected user's own address, then reads it back
from Sent Items (Mail.Read), and the alias is verified only if the copy shows
the alias as the sender. Until then, nothing sends: the same hard rule as
Gmail's ("no silent fallback to a personal address").

## 5. Collecting replies

- **Graph:** `GET /me/messages?$filter=conversationId eq '{id}'` for each
  thread the app started, least recently polled first, in the same batches
  and on the same tick as today.
- **The boundary is the same as Gmail's**, and the screen says so before
  consent: `Mail.Read` covers the whole mailbox, and Graph has no narrower
  scope. The app only ever asks for conversations it stored.
- **Change notifications** (Graph webhooks) are the later improvement. They
  need a public endpoint and renewal every ~3 days, and polling is what works
  today.

## 6. Meeting notes

Google Meet writes "Notes by Gemini" documents into Drive. Microsoft's
equivalents, in order of how reachable they are:

| Source | Reachable how | Recommendation |
|---|---|---|
| **A. A OneDrive folder** the practice saves notes or transcripts into (`.docx`, `.vtt`, `.txt`) | `Files.Read`, the folder's delta query | **Build first (D2).** The closest match to today's Drive watch. |
| B. Teams meeting transcripts | `GET /me/onlineMeetings/{id}/transcripts/{id}/content`; `OnlineMeetingTranscript.Read.All`, **which needs admin consent** | Second, as an option for practices whose admin consents |
| C. Copilot's "intelligent recap" notes | Loop components; no stable Graph read **[verify]** | Not until Microsoft exposes them |

A transcript is longer and rawer than Gemini's notes. Parsing gets a
**transcript-shaped prompt** (summarize, then extract) and the AI usage
screen shows its higher cost. Every result still lands in the review queue.

## 7. Sign-in, consent and Microsoft's verification

**The app registration** (Entra ID, in a Microsoft 365 tenant you control):
multi-tenant ("accounts in any organizational directory"), redirect URIs for
sign-in and for connecting, a client secret in env
(`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`).

**Delegated permissions**, each asked for only when its feature is turned on,
as with Google:

| Permission | For | Consent |
|---|---|---|
| `openid`, `email`, `profile`, `offline_access`, `User.Read` | sign-in, staying connected | user |
| `Mail.Send` | sending | user* |
| `Mail.Read` | replies, the alias check | user* |
| `Files.Read` | the notes folder | user* |
| `OnlineMeetingTranscript.Read.All` | Teams transcripts (§6B) | **admin** |

\* "User" if the practice's tenant allows users to consent to apps. **Many
tenants allow that only for apps from a *verified publisher*, and Microsoft
blocks user consent to unverified multi-tenant apps registered since late
2020.** So publisher verification is the step that matters.

**What Microsoft requires (your steps):**

1. **[you]** Enroll in the **Microsoft AI Cloud Partner Program** (free) and
   get a Partner ID (formerly MPN ID), in Noble Rose LLC's name.
2. **[you]** Add and verify `getexecutivesnow.com` as a custom domain in the
   Entra tenant that holds the app registration, and set it as the app's
   **publisher domain**.
3. **[you]** In the app registration, **add the Partner ID**. Once the
   Partner account and the domain line up, the app shows as a **verified
   publisher**, usually within hours.
4. **[you]** Privacy policy and terms URLs on the registration: the same pages
   as Google verification (`docs/google_verification.md` §4–5), with a
   Microsoft section added to the privacy policy (which Graph data, for what,
   and that meeting notes go to Claude under the practice's own Anthropic
   account).
5. **Not required:** there's no security assessment comparable to Google's
   CASA. Microsoft 365 Certification exists, but it's optional and only
   expected for AppSource or Teams store listings.
6. **[you, per practice]** If the practice's tenant requires admin consent,
   their admin approves the app once (a link the app produces). Teams
   transcripts always need this.

**Tokens:** refresh tokens last 90 days and renew with use. There's no
7-day expiry like Google's Testing mode. A revoked or expired connection
shows the same Reconnect state as Gmail.

## 8. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| D1 | Staff sign-in for a Microsoft practice | **Sign in with Microsoft** (same app registration), email-first like P2's Google routing |
| D2 | Meeting notes source to build first | **A OneDrive folder**; Teams transcripts second, for practices whose admin consents |
| D3 | Alias verification without a send-as list | **A test send read back from Sent Items** |
| D4 | Schema | **Additive:** `microsoft_connection` beside `gmail_connection`; new columns for `graph_conversation_id`, provider and OneDrive ids on the meeting tables; no rename of existing Gmail tables |
| D5 | Start publisher verification now | Yes: it's free, and it gates consent for every outside Microsoft practice |
| D6 | One provider per practice, set by you | Yes; no mixing Gmail sending with OneDrive notes |
| D7 | When to build | After Blue Sky is running on Google, unless a Microsoft practice is waiting |

**Build order once approved:** provider switch and connection model; sending
and alias check; reply collection; OneDrive notes; Microsoft sign-in. Each
step tested against Graph fakes at the boundary, like the Gmail and Drive
fakes, and proved once against a real Microsoft 365 account before it's
called done.

## 9. The transport as built (2026-10-27)

The owner's brief: the Microsoft 365 transport as a second mail transport
beside Gmail, with the same Outbox, replies, threading, unsubscribe and
allow-list rules, and one transport a practice with a clear switch. Built:
§2's provider switch and connection, §3 sending, §4 the address check, §5
replies. **Not built:** §6 OneDrive notes, D1 Sign in with Microsoft. A
Microsoft practice's staff still sign in as they do today; meeting notes and
Sheets feeds still come through a Google connection if one is there.

| Piece | Where |
|---|---|
| `tenant.mail_provider` (`google` default, `microsoft`) | `tenancy 0022` |
| `MicrosoftConnection` (one per person per practice, its refresh token in `tenant_secret` as `microsoft_refresh`), `graph_conversation_id` on `email_thread` and `unmatched_inbound` | `crm 0052` |
| Consent, token exchange and refresh, the admin-consent link | `apps/crm/services/microsoft_oauth.py` |
| `GraphTransport`, `GraphReader`, `verify_send_as`, `sending_connection_for` | `apps/crm/services/graph.py` |
| Which transport: `transport.get_transport(tenant=…)` | `outbox._deliver` |
| Settings → Email: "Mail goes through" and the Microsoft screen | `views_microsoft.py`, `MicrosoftEmail.tsx` |

**Decisions taken, where the spec left them open:**

- **D6, who switches:** the **practice owner**, on Settings → Email, not the
  platform owner. The brief asked for "a clear switch" on the practice; the
  spec recommended the platform owner. One permission to change if you want
  it the spec's way. The switch says what it means before it happens
  (nothing sends until the other is connected and its address passes;
  replies are collected only for conversations the new transport starts)
  and deletes nothing, so switching back needs no reconnect. The demo and a
  visitor's copy show the choice and refuse it: the demo's promise rides on
  its one Gmail connection.
- **D3, the address check:** as recommended, a test send read back from Sent
  Items, needing only **`Mail.ReadBasic`** (a message's envelope, no body)
  beside `Mail.Send`, so reading the whole mailbox stays opt-in ("Also
  collect replies", `Mail.Read`) as on Gmail. The account's own address
  passes without a send. A refusal and a quiet rewrite to the account's own
  address both fail it, and the screen says how an administrator allows the
  address (Send as on a shared mailbox, or sending from aliases).
- **Sending is MIME.** The same `build_mime` as Gmail builds the message; Graph
  takes it as a draft (`POST /me/messages`, the MIME base64 as `text/plain`),
  then `POST /me/messages/{id}/send`. So the headers (thread token,
  Message-ID, In-Reply-To, List-Unsubscribe), the HTML and text parts and
  the inline logo are what Gmail gets. A draft whose request would pass
  3.5 MB is made without its attachments, which follow one by one (a POST
  under 3 MB, an upload session above). A failed send deletes its draft.
- **Immutable ids** (`Prefer: IdType="ImmutableId"`) on every call, so the
  draft's id is the sent copy's.
- **Replies** read `GET /me/messages?$filter=conversationId eq '…'` for each
  conversation the app started, least recently polled first, on the same
  tick; a message already filed or sent by the app is recognised from the
  listing and its MIME is not fetched again. Each new one's MIME
  (`/$value`) is reshaped into the payload `inbound` already reads, so
  matching, unmatched handling, leave requests and attachments are Gmail's
  code. A new match rule sits after Gmail's thread id: the Graph
  conversation (`matched_by` `graph_conversation_id`).
- **Throttling:** a 429 or 503 is waited out when Graph asks for 10 seconds
  or less, twice at most; longer, the send fails with Graph's words.
- **Refresh tokens rotate**; each new one is stored.

**Tests** (`tests/test_microsoft_transport.py`, 72; fixtures in
`tests/fixtures/graph/`, shaped from Microsoft's reference, none captured):
role boundaries, isolation (connections, the switch, the conversations
polled, the callback's practice), connect and its refusals, the address
check's four outcomes, sending (MIME, headers, joint introductions, an
associate's own address, the allow-list, suppression, throttling, the three
attachment routes, the demo), replies (by conversation, by In-Reply-To,
unmatched and filed, re-polled, deleted), and **the Gmail path unchanged**:
a Gmail practice gets the Gmail transport, its send makes the same two
requests with the same body, its replies are read and filed as before, and
its settings payload has the same keys.

**Found, not fixed:** `build_mime` folds a `List-Unsubscribe` longer than 78
characters into RFC 2047 encoded-words (Python's default email policy). A
mail client reading RFC 2369 may not decode those, so the one-click
unsubscribe may not show, on Gmail as on Microsoft. A one-line fix
(serialising with a longer line limit) changes Gmail's bytes, so it waits for
the owner.

### Sign in with Microsoft and OneDrive notes, as built (2026-10-27)

The owner's brief: D1 (staff sign-in) and D2 (OneDrive notes), finishing the
Microsoft side.

**Sign in with Microsoft** (`apps/accounts/microsoft_signin.py`, migration
`accounts 0005`: two columns on `app_user`):

- **The same rules as Google sign-in:** invite-only, no sign-ups. An address
  must belong to a live staff member (practice owner, associate or assistant)
  of a practice that is not archived and whose mail runs through Microsoft 365.
  Clients keep magic links.
- **Email first**, as Google's: the sign-in page's one address field, and a
  second button beside "Sign in with Google", offered when the server has the
  registration and the practice the page is for (or, knowing none, any
  practice) is on Microsoft 365 (`/api/branding` `microsoft_sign_in`).
- **Which address is believed:** Microsoft's `email` claim is not verified,
  and any directory's administrator can put any address on their own user
  (the "nOAuth" problem). An address counts only when it is the account's
  mailbox address or sign-in name **and** its domain is a verified domain of
  the account's own directory (Graph `/organization`, readable with
  `User.Read`). The first sign-in binds the work account (directory and object
  id) to the user; a later one from another account with the same address is
  refused. Nothing is kept from a sign-in: no token, no connection.
- **The same registration and redirect URI** as connecting mail; the callback
  tells a sign-in from a connection by its state. Scopes: `openid email profile
  User.Read`, nothing that reads mail or files.
- **The Practices area** sets "Mail and sign-in" (Gmail or Microsoft 365) when
  a practice is added or edited, so an owner with no Google account signs in
  with Microsoft from the first day; the invitation names the right button and
  is refused while the registration is not configured. D6 now reads: the
  platform owner sets it at setup, and the practice owner can switch mail
  afterwards on Settings → Email.

**OneDrive notes** (`apps/meetings/onedrive.py`, migration `meetings 0009`:
`provider` on `drive_watch` and `meeting_source_file`):

- **The same pipeline.** `ingest.client_for` hands a Microsoft practice a
  `OneDriveClient` with the Drive client's methods, so the poller, the cursor
  discipline, exclusions, recording, the folder import, parsing (the same
  prompt) and the queue are Google's code. A Microsoft practice's connection
  needs `Files.Read`, asked for from the meeting queue's "Allow OneDrive
  access", which asks again for what the connection already holds so
  collecting replies is not dropped, and keeps a passed address check.
- **Chosen by browsing**, not by pasting a link: a OneDrive or SharePoint
  sharing link does not carry the folder's id. The picker walks from the root;
  "Use" checks the folder (the same counts as Drive's, one level down) and
  "Watch this folder" saves it.
- **What is read:** Teams and Copilot meeting notes in Loop (`.loop`,
  `.fluid`, converted by Graph's `?format=html`), Word (`.docx`, through
  python-docx), `.txt`, `.md`, and Teams transcripts (`.vtt`, as "Speaker:
  words"). PDFs, recordings, slides and spreadsheets are recorded as skipped
  with the reason, as on Drive.
- **The cursor** is the drive root's delta link: OneDrive for Business keeps
  delta for a drive's root, not for a folder. Changed files are kept when
  their parent is the watched folder or one below it.
- **Notes still being written:** a file changed in the last 20 minutes holds
  the cursor where it was, so the next poll reads it finished. A file edited
  after it was read is recorded as skipped ("Changed after it was read"), not
  read into a second proposal; Read again in the queue uses the new text.
- **One watch a practice, on its provider.** A Google watch is not read for a
  practice that moved to Microsoft 365, and choosing a OneDrive folder points
  the same watch there with a fresh cursor (the Google folder's id is in the
  audit event). Google Meet's extra folders stay as they were, for switching
  back.

**Tests** (`tests/test_microsoft_signin_onedrive.py`, 46): sign-in's rules
(verified domains, no sign-ups, live staff of a live Microsoft practice only,
one work account, one person), its isolation, and that Google's start and
adapter behave as before; OneDrive's picker, roles, choosing, polling
(recorded, skipped, outside the folder, deleted), the cursor held while notes
are written, no second read of an edited file, the folder import's order, each
format's text, a Loop page parsed into the same proposal, isolation between
practices, the consent round trip, and that a Drive file, a Google watch and
saving a Drive folder are as before.

## 10. What only a real Microsoft 365 tenant can confirm

Each was built to Microsoft's reference and tested against fixtures shaped
from it. None has been seen against a real tenant.

1. **The MIME draft.** Graph takes our MIME (multipart/alternative inside
   multipart/related with the inline logo, attachments) as a draft and
   sends it as built. The reference documents MIME drafts; our particular
   nesting is unproven.
2. **Our headers survive.** Exchange keeps `X-Thread-Token`,
   `List-Unsubscribe` and `List-Unsubscribe-Post` from the MIME. If it drops
   them, a reply still matches by conversation or In-Reply-To, but the
   one-click unsubscribe is lost on Microsoft.
3. **The Message-ID.** Whether Exchange keeps the one we set or assigns its
   own. Either works: the draft's `internetMessageId` is what is stored, and
   the fixture assumes Exchange's own.
4. **Threading.** A send carrying In-Reply-To and References joins its
   conversation in Outlook. Replies are matched either way.
5. **Immutable ids carry from draft to Sent Items**, so the read-back finds
   the sent copy by the draft's id.
6. **The `$filter` on `conversationId`** works without `$orderby` across all
   folders, and stays fast on a large mailbox.
7. **Sending as an alias.** The error code when it is refused
   (`ErrorSendAsDenied` or `ErrorFromAddressNotPermitted`), and whether a
   tenant without sending from aliases quietly rewrites the sender. The
   read-back fails both; only the words differ.
8. **The sent copy's timing.** Six looks a second apart is enough for the
   copy to leave Drafts. Slower, the check says "check again in a minute".
9. **The token response's `scope`.** Short names or full URLs; both are
   handled. Whether the OpenID scopes are listed.
10. **Consent.** The `AADSTS` errors for a directory that needs admin
    approval, and that the admin-consent link with `organizations` works.
    Until publisher verification (§7), most outside directories will need it.
11. **The upload session.** The URL takes chunks without a bearer token, in
    320 KiB multiples.
12. **Inbound MIME.** What `$value` returns for mail from other systems:
    character sets (windows-1252 is in the fixture), TNEF (`winmail.dat`)
    from Outlook senders, inline images.
13. **Throttling.** Graph's `Retry-After` on a 429 for one mailbox's send.
14. **Refresh-token lifetime and rotation** (90 days, rolling), and a
    revoked token's error (`invalid_grant`, AADSTS70000 in the fixture).

**The first real run:** connect one work account with "Also collect
replies", set the practice address to an alias, check it, approve one
Outbox message to an address on the laptop's allow-list, reply to it from
another mail client, press "Check now" on Replies. Items 1–9 and 13–14 show
on that one round; 10 needs an outside directory; 11 an attachment over
3 MB; 12 replies from several kinds of sender.

**Sign in with Microsoft and OneDrive notes (2026-10-27):**

15. **`/organization` with `User.Read`.** That an ordinary user's token reads
    their directory's `verifiedDomains` (the reference lists `User.Read` as
    enough). Without it, nobody signs in, which fails safe.
16. **The ID token's `oid` and `tid`** are present for every work account, so
    the first sign-in can bind one.
17. **One redirect URI for both flows.** That the registration accepts a
    sign-in consent and a connection consent at the same callback (the state
    tells them apart here).
18. **Root delta on OneDrive for Business** returns changed items with
    `parentReference.id` and `lastModifiedDateTime`, and `token=latest`
    returns a delta link with no backlog.
19. **Loop notes.** That Teams and Copilot meeting notes are `.loop` files in
    the organizer's OneDrive, which folder they land in, and that
    `GET /content?format=html` converts them (the reference lists HTML for
    Loop). The fixture assumes headings, paragraphs, lists and a table.
20. **How often a Loop page's `cTag` changes** while people type, and whether
    20 minutes is the right wait. Too short reads half a page; too long only
    delays the queue.
21. **A transcript as a file.** Teams keeps transcripts with the recording,
    not as a `.vtt` in a folder; a `.vtt` is read only when someone saves or
    downloads one there.
22. **Files.Read covers the folder chosen.** A folder shared with the owner
    from someone else's OneDrive is not in their drive's delta.
23. **Item ids** in `/me/drive/items/{id}` paths need no encoding for
    business ids; personal ids carry a `!`.

**The first real run for these:** sign in with Microsoft as a staff member of
a Microsoft practice (15–17); hold one Teams meeting with Loop notes, choose
its folder, wait for the poll (18–20); and save a `.vtt` there (21).

