# Microsoft 365 as a practice's mail and files

**Spec for owner review · no code · 2026-10-03**

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
