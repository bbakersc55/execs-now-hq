# Google OAuth verification — the External app

**For the owner · started 2026-10-02 (P2 D1)**

P2 D1 puts outside practices on a **second OAuth client** in a **new GCP
project**, consent screen *External*, publishing status *Testing*, with each
practice's staff added as test users. Executives Now stays on its Internal
client, unchanged. This document covers taking that External app through
**Google's verification**, in parallel. Verification is what removes the 7-day
token expiry and the 100-test-user cap for outside practices.

**Mark-up:** **[you]** is a step only you can do. **[drafted]** is text below,
ready to paste. **[app]** is code; that's mine, in P2.

> **What I'm sure of and what I'm not.** Google changes this process often.
> The steps below are the standard shape. Two things to **check in the Cloud
> Console when you add each scope**, because it labels them: (a) whether each
> scope is *sensitive* or *restricted* (my understanding is below), and (b) the
> current security assessment provider and price. Treat my classification and
> cost notes as a starting point, not as fact.

---

## 1. The scopes, and what each costs to verify

| Scope | Used for | Classification (to confirm in the console) |
|---|---|---|
| `openid`, `email`, `profile` | Signing in | Non-sensitive: no review |
| `gmail.send` | Sending the practice's client mail from its own address | **Sensitive**: review, no security assessment |
| `gmail.settings.basic` | Reading the send-as list, to confirm the practice alias before any send | **Restricted**, I believe: annual security assessment |
| `gmail.readonly` | Collecting client replies to threads the app started (Module 6) | **Restricted**: annual security assessment |
| `drive.readonly` | Reading the meeting-notes folder (Module 5) | **Restricted**: annual security assessment |

**Disclosure the review will look for:** Drive meeting notes are sent to
Anthropic's Claude API for parsing. That is a transfer of Google user data to a
third party, allowed for a user-facing feature only if the privacy policy
says so (§5 does) and the data is never used to train models.

**The cost driver is the restricted scopes.** Any one of them means an annual
**CASA security assessment** (Tier 2) by a Google-authorized lab, paid by you.
Asked as a question, not a recommendation: **`gmail.settings.basic` exists only
for the alias check.** Dropping it for outside practices (trust the
configured alias, and catch the first send's refusal instead) would remove one
restricted scope. It wouldn't remove the assessment while `gmail.readonly`
and `drive.readonly` stay. Those two are Modules 5 and 6, so I'd keep them.

---

## 2. Your steps, in order

1. **[you] Create the GCP project** `execs-now-hq-external` (any name), under
   the same organization. Enable the Gmail API and the Google Drive API.
2. **[you] Verify the domain** `getexecutivesnow.com` in Google Search Console
   with the same Google account that owns the project. Verification needs every
   URL on the consent screen to be on a domain you've proved you own.
3. **[you] Publish two public pages on `getexecutivesnow.com`.** Not on the app,
   and not behind a sign-in. Google checks both:
   - **Homepage** for the app, e.g. `https://getexecutivesnow.com/hq`. Content is
     **[drafted]** in §4: what the app is, who it's for, that it uses Google
     data, and a visible link to the privacy policy.
   - **Privacy policy**, e.g. `https://getexecutivesnow.com/hq/privacy`.
     **[drafted]** in §5. It must include the *Google API Services User Data
     Policy, Limited Use* statement word for word, or the review is refused.
   - Optional but recommended: terms of service (the beta agreement can serve
     while in beta).
4. **[you] Configure the OAuth consent screen** in the new project: *External*;
   app name **Execs NOW HQ**; support email; **app logo** (the logo itself is
   reviewed); homepage, privacy and terms URLs from step 3; authorized domain
   `getexecutivesnow.com`; developer contact. Add the scopes in §1.
5. **[you] Create the OAuth client** (Web application) with these redirect URIs:
   - `https://app.getexecutivesnow.com/accounts/google/login/callback/`
   - `https://app.getexecutivesnow.com/accounts/gmail/callback`

   Add the client ID and secret to Railway as
   `GOOGLE_OAUTH_EXTERNAL_CLIENT_ID` and `GOOGLE_OAUTH_EXTERNAL_CLIENT_SECRET`
   (the names **[app]** will read).
6. **[you] Add test users:** Shawn's address once you have it, and each of his
   staff. This is the Testing state D1 runs on while verification proceeds.
7. **[you] Record the demo video** (§6), upload it to YouTube as **Unlisted**,
   and keep the link.
8. **[you] Submit for verification** ("Prepare for verification" on the consent
   screen). Paste the **[drafted]** justifications from §3 into each scope's box,
   add the video link, and answer the questionnaire.
9. **[you] Answer Google's emails.** The review comes back by email, often with
   questions or requests to change the policy or video. Reply in the same
   thread. Expect a few rounds over several weeks.
10. **[you] The security assessment**, for the restricted scopes. Google emails
    instructions once the sensitive-scope review passes. You engage an
    authorized assessor (Tier 2 is largely a self-scan plus their review), fix
    findings, and the lab reports to Google. It's annual. **I'll prepare the
    technical answers and fix findings [app]**: data flows, encryption at rest
    (tenant secrets are encrypted), access control, logging.
11. **[you] Publish the app** (Testing → In production) once approved. Outside
    practices then stop expiring every 7 days.

---

## 3. Scope justifications [drafted]

Paste one into each scope's justification box. Each says what the scope does
in the app, why nothing narrower works, and what the user sees.

**`gmail.send`**
> Execs NOW HQ is a practice-management app for fractional executives. The app
> sends the practice's client email — sign-in links for the client portal,
> progress updates, and follow-ups a staff member writes and approves — from
> the practice's own Gmail address, so clients receive it from the person or
> practice they work with and replies come back to that mailbox. Every message
> is created as a draft and sent only after a person approves it, or is a
> sign-in link the recipient requested. gmail.send is the narrowest scope that
> sends mail; the app does not read, modify or delete mail with it.

**`gmail.settings.basic`**
> Before the app sends any client email, it reads the user's "Send mail as"
> list to confirm that the practice's alias (for example, info@theirpractice.com)
> is present and verified by Gmail. If it is not, the app refuses to send and
> tells the user which addresses are available, rather than silently sending
> from a personal address. The app reads only the send-as list; it never
> changes settings, filters, forwarding or any other configuration.

**`gmail.readonly`**
> Optional, and requested separately only when the user turns on "Also collect
> replies". The app sends client emails on threads it starts and stores the
> Gmail thread id of each. It reads only those stored threads, to file a
> client's reply against the right client record, so the whole practice sees
> the same history. Gmail offers no scope limited to threads an app started;
> gmail.readonly is the narrowest available. The app never lists, searches or
> reads any other thread, and the consent screen inside the app states this
> before the user grants it.

**`drive.readonly`**
> Optional, and requested separately only when the user turns on meeting
> ingestion. Google Meet saves "Notes by Gemini" documents into the user's
> Drive. The app reads one folder the user chooses, finds new meeting-notes
> documents in it, and turns each into proposed contacts, action items and
> tasks that a person reviews before anything is created. The document's text
> is processed by Anthropic's Claude API under the practice's own account,
> only to produce those proposals, as the privacy policy discloses. The files are created
> by Google Meet, not by the app, so drive.file cannot reach them, and the
> Picker would require the user to select every meeting by hand. The app reads
> only the chosen folder and never writes, moves or deletes anything in Drive.

**Sign-in (`openid`, `email`, `profile`)**: no justification is needed for
non-sensitive scopes; if asked: "Used to sign the user in and show their name
and email address."

---

## 4. Homepage [drafted]

At `https://getexecutivesnow.com/hq`, public, no sign-in:

> **Execs NOW HQ**
> The practice-management workspace for fractional executives — contacts and
> pipeline, client goals and progress updates, strategy sessions, meeting notes
> and client communication in one place, with a portal for your clients.
>
> **How it uses your Google account.** You sign in with Google. If you choose,
> Execs NOW HQ sends your client email from your Gmail address (only after you
> approve each message), confirms your send-as address, collects client replies
> on threads it started, and reads a Drive folder of meeting notes you choose.
> Each of these is turned on separately, and you can disconnect at any time.
>
> Execs NOW HQ is a product of Executives Now (Noble Rose LLC).
> [Privacy policy](https://getexecutivesnow.com/hq/privacy) ·
> Contact: bryan.baker@getexecutivesnow.com

---

## 5. Privacy policy [drafted]

**Have a lawyer read it before publishing.** It's written to match what the
app actually does and the beta agreement, and to include the statement Google
requires.

> **Execs NOW HQ Privacy Policy** — effective [date]
>
> Execs NOW HQ is provided by Noble Rose LLC, doing business as Executives Now
> and Execs NOW HQ ("we"). This policy covers the Execs NOW HQ application at
> app.getexecutivesnow.com.
>
> **Who uses it.** Fractional-executive practices ("practices"), their staff,
> and the clients they invite. Each practice's data is kept separate from every
> other practice's.
>
> **What we collect.** Account details (name, email address); the data a
> practice enters or imports (contacts, companies, tasks, notes, strategy
> sessions, meeting notes); email the app sends for the practice, and replies to
> it if the practice turns reply collection on; recordings a user chooses to
> make, and their transcripts; usage and cost totals needed to run the service.
>
> **Google user data.** With the user's permission, the app uses Google data
> only to: sign the user in (name and email address); send the practice's email
> from the user's Gmail address after a person approves each message, or when a
> client requests a sign-in link (gmail.send); read the user's Gmail "Send mail
> as" list to confirm the practice's address before sending
> (gmail.settings.basic); if the user turns it on, read replies on email threads
> the app itself started, to file them on the right client record
> (gmail.readonly); and, if the user turns it on, read meeting-notes documents
> in one Google Drive folder the user chooses (drive.readonly). The app does not
> read other email or other Drive files, does not change Gmail settings, and does
> not write to or delete anything in Gmail or Drive.
>
> **Limited Use.** Execs NOW HQ's use and transfer to any other app of
> information received from Google APIs will adhere to the
> [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
> including the Limited Use requirements.
>
> **AI processing.** When a practice uses AI features, the relevant text is
> sent to Anthropic's Claude API under the practice's own Anthropic account, to
> produce summaries and drafts that a person reviews. **This includes the
> meeting-notes documents the app reads from the chosen Drive folder**, as well
> as transcripts and notes the practice creates in the app. Google user data is
> sent to Anthropic only to provide that feature to the user, and is not used
> to develop, improve or train AI models.
>
> **Who can see it.** A practice's data is visible only to that practice's
> users, according to their role, and to the clients the practice invites (who
> see only their own company's work). We do not look inside a practice. People
> who operate the servers can technically access the database and its backups;
> we restrict that access to what is needed to run and back up the service.
>
> **Sharing.** We do not sell data or use it for advertising. We use these
> service providers to run the app: Railway (hosting and database), Google Cloud
> (file storage, backups, speech-to-text), Anthropic (AI, under the practice's
> own account), and Google (Gmail and Drive, under the user's own account).
>
> **Security.** Data is encrypted in transit. Stored credentials (for example a
> practice's API key and Google connection tokens) are encrypted in the
> database. Access is limited by practice and by role.
>
> **Retention and deletion.** Data is kept while the practice uses the service.
> Recording audio is deleted after the practice's retention period. A user can
> disconnect Google at any time in the app or at
> myaccount.google.com/permissions; the app then stops using Google data. On a
> practice's request we export its data and delete the practice; nightly backups
> roll off within 30 days.
>
> **Contact.** bryan.baker@getexecutivesnow.com

---

## 6. The demo video [script]

Google wants to see the **OAuth consent screen with the client ID visible in
the browser's address bar**, then each scope in use. Record it on the
production app, signed in as a test account of an outside practice, 3–5
minutes, no sound needed (captions help).

1. Show the homepage and the privacy policy link (getexecutivesnow.com/hq).
2. Sign in with Google: pause on the consent screen with the URL bar visible
   (it contains `client_id=…`). Show the app name and logo.
3. **gmail.send / gmail.settings.basic:** Email settings → Connect Gmail →
   consent screen (URL bar visible) → Verify alias, showing the send-as list
   check. Then approve one draft in the Outbox and show it arriving in the
   recipient's inbox from the practice address.
4. **gmail.readonly:** tick "Also collect replies", reconnect, show the in-app
   statement about what is read, show the consent screen. Reply to the email
   from step 3 and show the reply filed on the client's record.
5. **drive.readonly:** turn on meeting ingestion, show the consent screen, pick
   the notes folder, and show a meeting-notes document becoming a review queue
   item.
6. Show Disconnect, and the account's permissions page with the app listed.

---

## 7. What I'll build for this [app]

- The second OAuth client, chosen per practice (`tenant.oauth_client`),
  reading the two `GOOGLE_OAUTH_EXTERNAL_*` variables (P2 step 4).
- Whatever the review or the assessment turns up.
