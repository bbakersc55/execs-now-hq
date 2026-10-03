# P1 — Vocabulary, roles, branding

**Practices beta program, phase 1 of 4 · spec for owner review · 2026-10-02**

This spec covers P1 only. It is written from an audit of the code as of
`2e5e717`. Nothing in it is built yet. Decisions marked **D1–D7** need the
owner's answer before the build starts. Each has a recommendation.

---

## 0. What the audit found

| Area | Finding |
|---|---|
| Role codes on screen | **15 places**: the Staff screen's two role pickers (bare `FF`/`CF`/`VA`), the portal-role pickers ("Founder (FCC)", "Employee (ECC)"), help text on Add company and Pipeline, and two fallbacks that print the raw code. Three separate label maps disagree: `ROLE_LABELS` (App.tsx), `ROLE_WORD` (ActAs.tsx), `PORTAL_ROLES` (PortalAccessCard.tsx). |
| Role words in prose | "founder fractional" ×15 in backend messages and ×7 in screens; "contractor fractional", "a fractional", "your fractional", "founder user / employee user". |
| Role codes in API messages | **14** shown to users, e.g. "A VA cannot approve a digest.", "Portal access is FCC or ECC." |
| "tenant" visible | **0** on screens. **7** in API messages ("No membership for this tenant." ×5, "This tenant has no strategy template to run.", "{field} belongs to a different tenant."). |
| Emails (13 producers) | No role codes or "tenant". The pre-call invite's button is hard-coded `#F58220` instead of the practice accent. |
| PDFs (2) | The strategy PDF is branded. **The value report is not**: Executives Now colors are hard-coded, it has no logo or practice name, and it prints raw codes (`changed_course`, `ahead`/`late`). |
| Raw codes in client text | The digest's deterministic body writes "in_progress → done" (`work/digests.py:247-266`). That reaches clients when a digest falls back to it. |
| Other abbreviations | About 18 distinct ones. See §1.4. |
| Docs | 316 "tenant" and 768 role codes, mostly in `01_prd.md` (119 / 353) and `03_access_matrix.md` (30 / 218). |
| Branding today | Name, header color, accent color, logo (260×84) and mark (56×56 sign-off) already exist on `tenant`. They're used by emails, the strategy PDF and the portal's sign-in, cadence and sidebar pages. They're set only by `manage.py set_email_logo` and by hand; **there is no screen**. |
| Portal theming | The portal sets only `--blue`/`--orange`, but the stylesheet uses `var(--navy)` 39 times and `var(--blue)` never. **A practice's colors don't reach the portal today.** |
| Favicon | None anywhere. `<title>` is "Portal", then replaced at runtime. |
| Contrast checking | None. |

---

## 1. Vocabulary

### 1.1 The words

| Code (stays in code and data) | Shown to people |
|---|---|
| tenant | **Practice** |
| FF | **Practice owner** |
| CF | **Associate** |
| VA | **Assistant** |
| FCC | **Client owner** |
| ECC | **Client team member** |

Prose follows the same words: "the practice owner", "an associate", "your
practice". Client-facing prose never says "fractional" on its own. It uses the
practice's display name, e.g. "Ask Executives Now", not "ask your fractional".

### 1.2 One source of truth

- **Backend:** `Membership.Role` choice labels become the names above, and
  `role_label(code)` in `apps/tenancy/roles.py` returns them. `/api/me` and the
  staff list gain `role_label` next to `role`.
- **Frontend:** a single `frontend/src/lib/roles.ts` exports `ROLE_LABEL` and
  `roleLabel(code)`. `ROLE_LABELS`, `ROLE_WORD` and the labels in `PORTAL_ROLES`
  are deleted and replaced with imports. Every role picker gets its option text
  from it. **No component may print `me.role` or any role code directly.** An
  unknown code shows "Team member", never the code.

### 1.3 What changes (complete list from the audit)

**Screens:** Staff.tsx:62, 73–77, 95–98 · AddCompany.tsx:115–116, 123, 139 ·
Pipeline.tsx:88, 131 · PortalAccessCard.tsx:8–11, 78–80, 125, 183–184 ·
GrantPortalAccess.tsx:96–97 · ActAs.tsx:8, 49 · App.tsx:69–72, 242 ·
Meetings.tsx:270–271 · SessionTemplate.tsx:112, 452 · EmailSettings.tsx:272 ·
PinDialog.tsx:47 · Digests.tsx:126 · SendingQueue.tsx:213 · Outbox.tsx:125 ·
PortalCreate.tsx:158.

**API messages (21):** the 14 role-code messages in `crm/permissions.py`,
`crm/serializers.py`, `crm/services/merge.py`, `notes/views.py`,
`work/portal.py`, `work/digests.py`, `work/views.py` and `strategy/views.py`,
plus the 7 "tenant" messages. Examples:

| Now | After |
|---|---|
| A VA cannot approve a digest. | Assistants can't approve digests. Ask the practice owner. |
| Portal access is FCC or ECC. | Portal access is for client owners and client team members. |
| No membership for this tenant. | You're not a member of this practice. |
| This tenant has no strategy template to run. | This practice has no strategy template yet. |

**Choice labels:** `crm/models.py:272` "FF-written template" → "Written by the
practice owner".

**Raw codes shown as text:** the digest's deterministic body (`_describe`), the
value report's `resolution` and milestone `state`, and ten
`{x.state}`-style messages in `crm/views.py`, `crm/services/outbox.py`,
`work/digests.py` and `work/views.py` all switch to display labels ("In
progress → Done", "Changed course", "Ahead").

`merge.py:30` raises an uncaught error that would show as a server error. It is
fixed to return its message.

### 1.4 Other abbreviations — **D3**

The request says to remove abbreviations. Some are ordinary words to anyone
using the app, so I recommend a keep list:

| Keep (well-known words) | Replace |
|---|---|
| PIN, AI, PDF, CSV, PNG/JPEG (upload hints), KB/MB (file sizes), "1–10", "API key" (Anthropic's own term), Gmail, Drive | "FR-1.6a", "§3.4", "§9", "§5a", "assumption H6", "Tier 2" → removed; "e.g." → "for example"; "● REC" → "● Recording"; "min" → "minutes"; "Beta" / "V1" in messages → removed; environment-variable names and doc paths shown in Email settings and Meetings (`GOOGLE_OAUTH_CLIENT_ID`, `APP_MAIL_TRANSPORT`, "docs/05… §5a") → "Google sign-in isn't configured on this server. Contact support." (a practice owner can't set server variables); raw import field names (`first_name`) → "First name" |

The localhost-only developer screens (Dev allow-list, `.env` pills) stay as
they are; no practice ever sees them. The "{field} must be an id." validation
messages only fire on malformed requests, so they stay.

### 1.5 Docs — **D1**

The audit counts 316 "tenant" and 768 role codes across 17 docs. Recommendation:

- **Owner-facing docs** (`00`–`04`, the `phaseN_manual_checks`, the Google
  setup docs): prose says Practice and the role names. Code identifiers keep
  code font: `tenant_id`, the `Tenant` model, `FF` inside a code block.
  `03_access_matrix.md` gets name-headed columns with the code underneath.
  `01_prd.md` gets a two-line glossary at the top.
- **Engineering records** (`05_dev_environment.md`, `phase7_cutover_runbook.md`,
  `incident_*`, `handoff.md`, `design_brief.md`): new text uses the new words.
  Existing text is history and isn't rewritten.
- CLAUDE.md gets a vocabulary line, and its roles table gains the names.

### 1.6 Keeping it that way (tests)

- **Backend source guard:** a test scans every literal passed to
  `PermissionDenied`, `ValidationError`, `Response({"detail": …})` and email
  subjects in `apps/`, and fails on `\b(FF|CF|VA|FCC|ECC)\b` or `tenant`.
- **Frontend render guard:** a vitest renders each staff screen as each staff
  role, and each portal screen as both client roles. It fails if the page text
  matches `\b(FF|CF|VA|FCC|ECC)\b` or `/tenant/i`. It also checks every role
  `<option>` against `ROLE_LABEL`.
- **Existing tests updated:** `test_module3_portal.py:603` asserts "FCC or
  ECC"; 7 frontend tests assert on "founder fractional" / "founder" /
  "employee"; abbreviation tests on "● REC", "§9", "min".

---

## 2. Branding per practice

### 2.1 What a practice owner sets (Settings → Branding)

| Field | Stored in | Rule |
|---|---|---|
| Display name | `tenant.email_display_name` (exists) | 1–80 characters. Blank falls back to the practice name. |
| Logo | `tenant.email_logo` + display size (exists) | PNG or JPEG, ≤ 500 KB, fitted to 260 × 84 (never enlarged) |
| Mark (sign-off image and favicon) | `tenant.email_mark` + display size (exists) | PNG, **square**, at least 64 × 64 (180+ recommended, 512 ideal), ≤ 500 KB |
| Primary color | `tenant.email_header_color` (exists) | Hex `#RRGGBB`; contrast rules in §2.3 |
| Accent color | `tenant.email_accent_color` (exists) | Hex; §2.3 |
| Email footer | **new** `tenant.brand_footer_text` | Plain text, ≤ 500 characters, ≤ 6 lines; URLs and email addresses become links |
| (set or not) | **new** `tenant.branding_updated_at` | Written on each save. Null means "never set", which drives the defaults (§2.2) and P2's "Set branding" checklist tick. |

Only the **practice owner** can open or change it. Associates, assistants and
client users get 403 from the API, and the nav item isn't shown to them.
`set_email_logo` stays as a script and calls the same service as the screen.

The screen shows a **live preview**: the portal sidebar, an email header and
footer, a button, and the favicon at tab size. Contrast results show as each
color is chosen. "Reset to default" clears everything back to the default
brand, after a confirmation.

SVG is not accepted. It can carry script, and email clients handle it
inconsistently.

### 2.2 Defaults until set — **D2 (contradiction with the current design)**

The request says a practice "defaults to the platform brand until set", and P1
item 3 makes the Executives Now mark "the default tenant mark".

The code was built the other way on purpose. `tenancy/models.py:119-127` says
the defaults are "a practice's own name over neutral greys, never the product's
name or palette". The platform brand *is* Executives Now's brand, which is also
your practice's. So under the new rule, Blue Sky's clients would get emails,
PDFs and a portal in Executives Now's navy and orange, with your mark in the
browser tab, until Shawn uploads his own. That reads as "Executives Now's
client".

| Option | Unbranded practice's clients see |
|---|---|
| **A (as requested)** | Executives Now colors and mark, with the practice's name |
| **B (recommended)** | The practice's name over neutral grays, and a plain lettered mark (the practice's initials on gray) as the favicon. The staff side shows the product brand either way. |

The resolver reads one constant, so either option is a one-line change. P2's
checklist puts "Set branding" first in both cases.

### 2.3 Contrast rules — **D4 (your own orange fails one)**

Measured with the WCAG relative-luminance formula:

| Pair | Executives Now | Proposed rule |
|---|---|---|
| Primary vs white | `#0A3A65`: **11.6 : 1** | **Block below 4.5 : 1.** White text sits on the primary color (email header, portal sidebar, buttons). |
| Accent vs primary | **4.48 : 1** | **Block below 3 : 1.** The accent sits on the primary color (active-nav rail, header bars). |
| Accent vs white | `#F58220`: **2.6 : 1** | **Warn only, don't block.** |

A hard 3 : 1 or 4.5 : 1 rule on accent-against-white would reject Executives
Now's own orange. So the accent is used **only** as fill and decoration, never
as text on white. Where text sits on an accent fill (a button), the app picks
white or near-black, whichever contrasts more. The warning tells the owner that
the color is decoration-only. One shared contrast function: Python validates,
and TypeScript mirrors it for the live preview, tested against the same table
of reference pairs.

### 2.4 Where the brand applies

| Surface | Practice brand | Product brand |
|---|---|---|
| Client portal (sidebar, colors, `<title>`, favicon) | ✔ | |
| Portal sign-in, magic-link landing, cadence and pre-call pages (public token pages) | ✔ | |
| Every client-facing email (13 producers): header, colors, buttons, **footer** | ✔ | |
| Strategy PDF | ✔ (already) | |
| **Value report PDF**: logo, practice name, colors | ✔ (new) | |
| Staff sidebar | **practice display name** under the product wordmark | ✔ wordmark, colors |
| Staff `<title>` and favicon | | ✔ |
| Staff-only emails (client-activity notice, pre-call finished, PIN reset) | unchanged (practice header) | |

**Portal colors:** the portal derives the whole token family (`--navy`,
`--navy-700/300`, `--orange`, `--orange-600/050`) from the two practice colors
by mixing with white and black. Today only `--blue`/`--orange` are set, and
nothing reads `--blue`. Staff screens never get practice colors.

**Footer:** shown at the bottom of branded emails (`base.html`, replacing the
bare practice-name line) and under the person's own sign-off in personal emails
(`personal.html`). **D5:** I recommend both. The person's signature (Settings →
Sender) stays per-person; the footer is practice-wide (address, phone, website).

**No favicon flash:** `config/spa.py` serves `index.html` and fills in the
favicon link and `<title>` on the server from the session's membership. Staff
get the product mark; client users get their practice's. A client never sees
the product's mark for a moment while the app loads.

### 2.5 API

| Method · path | Who | Does |
|---|---|---|
| `GET /api/settings/branding` | Practice owner | Current values, `branding_updated_at`, contrast results |
| `PUT /api/settings/branding` | Practice owner | Name, colors, footer. 400 names the failing contrast rule. |
| `POST`/`DELETE /api/settings/branding/logo` and `/mark` | Practice owner | Upload (multipart) or clear |
| `GET /api/branding` (exists) | Everyone signed in | Gains `mark_url`, `footer_text`, `practice_display_name` (staff) |
| `GET /api/branding/mark` | Members of that practice, and public token pages for that practice | Serves only the requester's own practice's mark |

Every change writes an `audit_event` (`branding.updated`, `.logo_set`,
`.mark_set`, `.reset`).

---

## 3. The platform favicon

**Please add:** `assets/brand/mark.png`, square, transparent background,
**at least 512 × 512** (1024 × 1024 better). Also `assets/brand/mark.svg` if
you have one; it's optional. The current `email-mark.png` is 112 × 112, which
is too small to make the larger icons cleanly.

`manage.py build_favicons` (using Pillow, already installed) writes
`favicon.ico` (16/32/48), `favicon-32.png`, `apple-touch-icon.png` (180) and
`icon-192.png`/`icon-512.png` into `frontend/public/brand/`. The outputs are
committed, so builds don't need the source. Staff pages link them. Under D2-A
they're also the default practice mark.

---

## 4. Schema

**Additive only:** two new columns on `tenant`, nothing dropped or rewritten.
Existing columns keep their `email_` names; the API and screen call them by
their new names. Renaming the columns would be a production rewrite for no
user-visible gain.

```sql
ALTER TABLE "tenant" ADD COLUMN "brand_footer_text" text DEFAULT '' NOT NULL;
ALTER TABLE "tenant" ADD COLUMN "branding_updated_at" timestamp with time zone NULL;
```

That's the expected SQL. The exact `sqlmigrate` output is shown before the
migration is generated (CLAUDE.md). It reaches production only by "Releasing a
migration".

Under D2-B the resolver checks `branding_updated_at` before the stored colors.
Executives Now's row (colors set in tenancy 0005, logo and mark set) gets
`branding_updated_at` set when you first save the Branding screen. Until then,
the existing logo and mark keep being used, and so do the stored colors, which
are already Executives Now's. **No data migration.**

---

## 5. Tests

| Family | Tests |
|---|---|
| **Role boundaries** | Branding endpoints: practice owner 200; associate, assistant, client owner, client team member 403. Branding is added to `MODULE1_ENDPOINTS`-style matrix. |
| **Practice isolation** | `/api/branding/mark` and `/logo` never serve another practice's file: by session, by token page, or by guessed ID. Saving branding in practice A changes nothing in B. Practice B's portal `index.html` carries B's favicon and title. |
| **White-label** (existing `test_white_label.py`, extended) | Client pages, emails and PDFs never contain the product name. Under D2-B, they also never carry Executives Now's colors or mark for another practice. |
| Contrast | The shared table of reference pairs passes in both Python and TypeScript. Saves are blocked or warned as in §2.3. |
| Uploads | Wrong type, oversize, non-square mark and SVG are rejected with a reason. |
| Emails and PDFs | The footer appears in branded and personal emails. The pre-call button uses the accent. The value report carries logo, name and colors, and no raw codes. |
| Vocabulary guards | §1.6. |

---

## 6. Build order (after approval)

1. Shared roles source and the vocabulary pass (screens, API messages, raw codes), with the guard tests.
2. Contrast function, schema, branding service and API, with boundary and isolation tests.
3. Branding screen and live preview.
4. Portal token family, staff sidebar practice name, server-filled favicon and title.
5. Emails (footer, pre-call button) and the value report.
6. Platform favicons, once `mark.png` is in.
7. Docs pass per D1.

The full suite is green at each step. Committed on `dev`; I stop at the end of P1.

---

## 7. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| **D1** | Docs scope | Owner-facing docs fully renamed; engineering records only going forward (§1.5) |
| **D2** | Unbranded practice's default | **B**: neutral grays and initials mark for clients, product brand on the staff side only (§2.2) |
| **D3** | Abbreviation keep list | As in §1.4 |
| **D4** | Contrast rules | Primary vs white ≥ 4.5 (block); accent vs primary ≥ 3 (block); accent vs white warn only (§2.3) |
| **D5** | Footer in personal emails too | Yes, under the person's sign-off |
| **D6** | Mark minimum | Square, ≥ 64 px, 180+ recommended |
| **D7** | Role names | As given: Practice owner, Associate, Assistant, Client owner, Client team member. In client-facing prose, the practice's display name rather than "your fractional". |

Not in P1: the Practices area, the platform owner, provisioning, the checklist
and feedback (P2).
