# P2 — Practices admin and onboarding

**Practices beta program, phase 2 of 4 · spec for owner review · 2026-10-02**

Covers program items 4–8. Settled before writing: the platform owner is the
owner's own Google sign-in with two areas and a switch (no second login); new
practices get a $50 monthly AI budget and a $5 daily unattended cap; Blue Sky's
display name is "Blue Sky Business Consulting"; signed-out practice resolution
as in §2 (owner, 2026-10-02); per-practice subdomains are V1.

**Approved 2026-10-02.** D1 **A**: a second OAuth client in a new GCP project,
External/Testing, outside practices' staff added as test users, Executives Now
unchanged; Google verification of that app started in parallel
(`docs/google_verification.md`). D2–D9 as recommended. Agreement text
received: `docs/legal/beta_agreement_v1.md`, with the server-access sentence
added to clause 2. **Build now everything that does not need Shawn's email;**
Blue Sky is created when it arrives.

---

## 0. What the code does today, and what a second practice breaks

| Finding | Consequence |
|---|---|
| **No code creates a practice.** Executives Now's row came from migrations and seeds; the strategy template was seeded by a migration for that one row. | Provisioning (§3) is new code, not a wrapper. |
| **Google sign-in accepts only `@getexecutivesnow.com`.** The OAuth consent screen is *Internal* (`05_dev_environment.md` §5a). | **Shawn cannot sign in with Google, and cannot connect Blue Sky's Gmail.** See D1. |
| **All app mail goes through the practice's connected Gmail** (magic links, digests, touches). | Without a Gmail connection, Blue Sky's clients cannot even receive a sign-in link. D1 again. |
| **Signed-out pages find their practice only because exactly one exists** (`_branding_tenant`): `/api/branding`, `/api/branding/mark`, the server-filled tab (P1), the "refused" page. | Settled in §2. |
| **Magic links already resolve correctly:** the entered email finds the membership, and the token carries its practice. | §2 keeps this, and makes the landing pages say so. |
| **One membership per user** (B4). | The platform owner is a flag on the user, not a second membership (§1). |
| **Schedules are per practice** (`ensure_schedules` loops over practices). | Provisioning registers the new practice's schedules; archiving stops them. |
| **No stage automations are seeded.** | "Stage rules off" needs nothing. |
| `tenant.from_address` defaults to `info@getexecutivesnow.com`; `inbound_domain` to Executives Now's. | A new practice must never inherit them (§3). |

---

## 1. The platform owner and the Practices area

**Who:** a flag on the user, `user.is_platform_owner`. It's set only by
`manage.py set_platform_owner <email>` (with `--remove`). No screen or API
can set it. One person in Beta: you.

**Two areas, one sign-in.** A switch at the top of the sidebar reads
**Executives Now ▾**. Its menu has your practice and **Practices**. The choice
is kept in the session (`area = practice | platform`) and changes the whole app:

- **In "Executives Now"**: you're the practice owner of Executives Now, exactly
  as today.
- **In "Practices"**: no practice is bound to the request. `request.tenant` and
  `request.membership` are `None`, so **every practice-scoped query fails
  closed** through the existing tenant manager. The nav shows only Practices
  and Feedback, and the staff wordmark reads "Practices".

**What the Practices list shows:**

| Column | Source | Notes |
|---|---|---|
| Practice | display name, legal name under it | |
| Status | `active` / `invited` (owner hasn't signed in) / `archived` | |
| Created | `tenant.created_at` | |
| Staff | count of live staff memberships | number only |
| Clients | count of client companies | number only |
| AI spend this month | sum of `ai_call` cost this calendar month | number only |
| Last activity | latest sign-in by any of its users (**D7**) | a date only |

**Create a practice:** legal name, display name, domain, owner email. Runs §3,
then sends the owner's invitation.

**Archive:** the practice's users can't sign in (staff or clients), its
scheduled jobs stop, nothing is sent, and **all data is kept**. Unarchiving
reverses it. P2 has no delete (**D4**).

**How "sees nothing inside a practice" is enforced:**

1. Platform endpoints (`/api/platform/…`) require `is_platform_owner` **and**
   the Practices area.
2. They read through **one module**, `apps/platform/stats.py`. It's the only
   platform code allowed to use `all_objects`, and it returns **numbers and
   dates only**, never a row, a name from inside a practice, or an id of a
   contact, task, note, email, meeting or session.
3. A source guard test fails if any other module under `apps/platform/`
   touches a practice-scoped model.
4. **The isolation family gains the platform owner** (§9). Every practice API
   route, requested in the Practices area, returns 403 or 404 with no practice
   data. In the Executives Now area, Blue Sky's rows return 404 like any other
   practice's.

**What the docs will say, honestly:** the app gives the platform owner no way
to see inside a practice, and there is no support-grant feature. Anyone who
operates the servers (Railway and the database, GCS and the backups) can still
read the database directly. Code can't remove that, and the beta agreement
should say so. This goes in `01_prd.md` and a short
`docs/data_and_the_platform_owner.md`.

---

## 2. Signed-out pages: which practice (owner, 2026-10-02)

- **The client sign-in page needs no practice.** It asks for an email. The
  email finds the person's membership, and through it the practice. The
  emailed link carries that practice. The page names no practice; **D9**
  covers what it does show.
- **Every link the app emails is practice-specific:**

  | Link | Practice comes from | Change in P2 |
  |---|---|---|
  | Magic link `/auth/magic/<token>` | the token's row | none (already does) |
  | Digest cadence `/cadence/<token>` | the stakeholder token | its payload gains `branding` |
  | Pre-call form `/precall/<token>` | the session token | its payload gains `branding` |
  | Unsubscribe `/unsubscribe/<token>` | the signed token's practice | the page uses it |
  | PIN reset (staff) | the token's row | none |

- **The browser tab on a signed-out page shows the product icon**, and switches
  to the practice's mark (or initials) once the practice is known: on sign-in,
  or when a token page's payload arrives. This replaces P1's "practice mark from
  the first byte" for signed-out visitors. **Signed-in client users still get
  their practice's mark from the first byte.**
- The single-practice fallback is **removed**. Signed out, `/api/branding`
  returns no practice. `/api/branding/mark` returns 404 unless a session or
  token names one. The "refused" page names no practice.
- Per-practice subdomains are V1.

**As built (step 2).** Instead of each token endpoint adding `branding` to its
payload, `/api/branding`, `/api/branding/mark` and `/api/branding/logo` accept
`?via=<kind>:<token>` for `cadence`, `precall` and `unsubscribe`. The token
resolves to its practice exactly as the page's own endpoint does, and an
invalid or another practice's token names nothing. The app's token pages wrap
in `LinkBranded`, which applies the practice's colors, tab icon and title once
the answer arrives. One mechanism serves the page, its images and its icon.

---

## 3. Provisioning a practice

`provision_practice(legal_name, display_name, domain, owner_email, actor)`
runs in **one transaction**; the invitation email goes after commit.

| What | Value |
|---|---|
| `tenant` | `legal_name`, `name` = display name, `email_display_name` = display name, `domain`, unique `slug` from the display name, `status = invited`, `created_by` |
| Safety | **`hold_all_digests = ON`**, `digest_ai_prose_default` as today |
| AI | `ai_monthly_budget_usd = 50`, `ai_unattended_daily_cap_usd = 5` |
| Mail | `from_address = info@<domain>`, editable in Email settings and verified by the existing send-as check; `inbound_domain` blank. **Never Executives Now's.** |
| Brand | P1's neutral default: the practice name over grays, initials mark, `branding_updated_at` null. *(The program note said "the platform brand as default"; P1 D2 replaced that with neutral, approved 2026-10-02.)* |
| CRM | `seed_tenant`: default pipelines and stages, contact types |
| Stage rules | none (none are seeded) |
| Strategy | **no template** |
| Owner | a user for `owner_email` and a practice-owner membership (`invited_at` set) |
| Schedules | `ensure_schedules` for this practice only |
| Audit | `practice.created` on the new practice, by the platform owner |

The invitation email says the practice is ready and how to sign in (§4/D1). It
is sent by the platform sender (**D2**).

---

## 4. Signing in and connecting Gmail — **D1, blocking for Blue Sky**

The Internal consent screen limits Google to Executives Now's Workspace. A
practice on another domain needs two things it can't have today: **a way to
sign in**, and **a Gmail connection** so its clients get sign-in links and
digests.

| Option | Sign-in | Gmail and Drive | Cost |
|---|---|---|---|
| **A (recommended for Beta)**: a **second OAuth client** in a new GCP project, consent screen *External, Testing*, with each practice's staff added as named test users (up to 100). Executives Now stays on the Internal client. | Google, any account on the test-user list | Works; **refresh tokens expire every 7 days** in Testing, so Blue Sky reconnects weekly (the app already shows Reconnect and says why). | A day to set up; weekly reconnect for non-Executives-Now practices; the app picks the OAuth client by practice. |
| B: magic-link sign-in for practice staff too | No Google needed | **Still blocked**; magic links themselves need a sender | Doesn't solve mail alone; can be combined with A or C |
| C: verify the External app with Google (CASA) | Any account | No expiry | Weeks to months, and costly; the V1 plan |
| D: Postmark for non-Executives-Now practices | (needs A or B) | App mail via Postmark from the practice's domain (Shawn adds DNS records); personal sends from his own address still need Gmail | Builds the V1 transport early |

Recommendation: **A now, C in V1.** Executives Now keeps its no-expiry Internal
setup. Under A, a practice's settings say which OAuth client it uses, chosen at
provisioning: Internal for `getexecutivesnow.com`, External for anything else.

---

## 5. Getting started checklist

A card on the **practice owner's** dashboard only. Each item is **computed
from the data on every load**; nothing is stored, so an item can't claim
something false. Each item links to its screen. The card disappears when all
seven are done.

| Item | Done when | Links to |
|---|---|---|
| Set your branding | `branding_updated_at` is set | Settings → Branding |
| Connect Gmail | a staff Gmail connection with a verified send-as alias | Email settings |
| Add your Anthropic key | a stored Anthropic key | AI usage |
| Import your contacts | a committed import, **or** any contact (**D5**) | CSV import |
| Invite your staff | a live associate or assistant | Staff |
| Add your first client | a client company exists | Companies |
| Build your first strategy template | a strategy template exists | the template editor |

The last item depends on P3's builder. Until then the template editor's
existing "start from the Operations template" is the way in, so the item
ticks as soon as one exists.

---

## 6. The beta agreement

- Shown to a **practice owner** on first sign-in, before anything else. The
  app is unusable until it's accepted. It's accepted once per version.
- The text lives in the repo (`docs/legal/beta_agreement_v1.md`, from you) and
  renders on the screen. Acceptance records user, practice, version,
  **SHA-256 of the exact text shown**, time and IP.
- **A new version needs acceptance again** (**D3**). The platform owner's own
  practice is exempt.

---

## 7. Feedback

- **A Feedback button on every staff screen** (practice owner, associate,
  assistant; not clients). It opens a short form: *What were you doing? What
  happened? What did you expect?* The current screen URL is captured
  automatically, and a screenshot upload is optional.
- **The form says plainly** that what you write and the screenshot go to the
  platform owner. That's the only way it crosses the practice boundary: because
  the person wrote it.
- **The record:** practice, the practice's display name at the time,
  submitter, role, the three answers, the URL, the screenshot, time, and a
  status (new / seen / closed).
- **Who sees it:** the platform owner reads all feedback in the Practices area.
  A practice's staff see only what they sent. **Nothing else about the practice
  is attached.**
- **Notification:** an email to the platform owner with the practice name and
  the text, sent by the platform sender (D2). The screenshot stays in the app.
- Rate-limited: 10 an hour per user.

---

## 8. Blue Sky

Created through §3 **once Shawn's email arrives and D1 is decided**:

- **Legal name:** Blue Sky Business Consulting LLC
- **Display name:** Blue Sky Business Consulting
- **Domain:** blueskybizconsulting.com

The invitation is not sent until you say so.

---

## 9. Schema (expected SQL; exact `sqlmigrate` output shown before generating)

```sql
ALTER TABLE "app_user" ADD COLUMN "is_platform_owner" boolean DEFAULT false NOT NULL;

ALTER TABLE "tenant" ADD COLUMN "legal_name" varchar(200) DEFAULT '' NOT NULL;
ALTER TABLE "tenant" ADD COLUMN "domain" varchar(253) DEFAULT '' NOT NULL;
ALTER TABLE "tenant" ADD COLUMN "status" varchar(12) DEFAULT 'active' NOT NULL;
ALTER TABLE "tenant" ADD COLUMN "archived_at" timestamp with time zone NULL;
ALTER TABLE "tenant" ADD COLUMN "created_by_id" uuid NULL REFERENCES "app_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "tenant" ADD COLUMN "oauth_client" varchar(12) DEFAULT 'internal' NOT NULL;  -- D1 option A only

CREATE TABLE "agreement_acceptance" (
  "id" uuid PRIMARY KEY, "tenant_id" uuid NOT NULL REFERENCES "tenant",
  "user_id" uuid NOT NULL REFERENCES "app_user", "version" varchar(32) NOT NULL,
  "text_sha256" char(64) NOT NULL, "accepted_at" timestamptz NOT NULL, "ip" inet NULL,
  UNIQUE ("user_id", "version"));

CREATE TABLE "feedback" (
  "id" uuid PRIMARY KEY, "tenant_id" uuid NOT NULL REFERENCES "tenant",
  "practice_name" varchar(200) NOT NULL, "submitted_by_id" uuid NULL REFERENCES "app_user",
  "role" varchar(3) NOT NULL, "doing" text NOT NULL, "happened" text NOT NULL,
  "expected" text NOT NULL, "page_url" varchar(500) NOT NULL,
  "screenshot_id" uuid NULL REFERENCES "stored_file", "status" varchar(8) NOT NULL,
  "created_at" timestamptz NOT NULL);
```

Everything is additive. Executives Now's row gets `status = active` and
`oauth_client = internal` from the defaults. Its legal name and domain are
filled in by you on the Practices screen; no data migration.

---

## 10. Tests

| Family | Tests |
|---|---|
| **Practice isolation, platform owner** | Every practice API route, in the Practices area, returns 403 or 404 and no practice data. In the Executives Now area, another practice's rows return 404. Stats responses contain only the documented keys, all numbers or dates. Source guard on `apps/platform/`. |
| **Role boundaries** | Practices endpoints: platform owner only; a practice owner who isn't the platform owner, associates, assistants and clients get 403. The flag can't be set through any API. Checklist: practice owner only. Feedback: staff only; each practice sees only its own submissions. |
| Provisioning | Every default in §3; a failure mid-way leaves nothing behind; no Executives Now address is inherited. |
| Archive | Members can't sign in; schedules stop; data is kept; unarchiving restores sign-in. |
| Signed-out resolution | The sign-in page names no practice. Each emailed link brands as its own practice, with two practices present. Signed-out `/api/branding` returns no practice. The tab icon changes on sign-in. |
| Agreement | The gate blocks until accepted; the hash matches the text shown; a new version asks again; the platform owner's practice is exempt. |
| Checklist | Each item ticks from real data, and only from its own practice's data. |

---

## 11. Build order (after approval)

1. Schema, the platform-owner flag and command, the area switch and fail-closed Practices area, the isolation family.
2. Signed-out resolution (§2).
3. Practices list and stats, create (provisioning), archive.
4. The D1 sign-in and Gmail route.
5. Invitation, agreement gate, checklist.
6. Feedback.
7. Docs (data and the platform owner), then Blue Sky when the email and D1 are in.

---

## 12. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| **D1** | **How a non-Executives-Now practice signs in and connects Gmail** (blocking) | **A**: a second OAuth client, External/Testing, weekly reconnect for those practices; CASA in V1 |
| D2 | Who sends platform mail (invitations, feedback notices) | Executives Now's Gmail connection, from `info@getexecutivesnow.com` |
| D3 | A new agreement version asks again; your practice exempt | Yes, both |
| D4 | Archive keeps all data and is reversible; no delete in P2 | Yes |
| D5 | "Import your contacts" ticks on a committed import or any contact | Yes |
| D6 | New practices start on P1's neutral brand, not the platform brand | Yes (already approved in P1) |
| D7 | "Last activity" = latest sign-in by any of its users | Yes |
| D8 | Platform owner set only by `manage.py set_platform_owner` | Yes |
| D9 | The signed-out sign-in page shows a plain "Sign in" heading and the product icon in the tab, with **no product name on the page** (white-label) and no practice name | Yes |
