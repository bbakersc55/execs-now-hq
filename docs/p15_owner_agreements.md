# P15 — Owner agreements (built 2026-11-23/24, branch `owner-agreements`)

SkyRun Park City's new property owners sign SkyRun's Rental Management
Agreement electronically, SkyRun countersigns it, and the owner's answers
start the owner's intake (docs/p14_intake_forms.md). Code: `apps/agreements/`,
the owner's pages in the form bundle (`frontend/src/forms/AgreementApp.tsx`),
the staff screens `frontend/src/screens/Agreement*.tsx`. Plan and the Track
read: the "Owner agreements: plan and Track read" doc (2026-11-23).

## Ground rules (owner, 2026-11-23)

- **SkyRun only.** Switched on per company in the Railway shell, like intake:

      python manage.py owner_agreements <company-id>          says whether it's on
      python manage.py owner_agreements <company-id> on|off

  On needs intake forms on for the company. Off hides everything (menu item,
  screens, notification choice, owner links and pages); signed agreements and
  their PDFs are kept. Audit `agreements.switched`. No trace for any other
  company, practice or the demo.
- **Owners see nothing of Execs NOW HQ, Executives Now or Noble Rose**, except
  while the owner-email sender is "ENHQ's own sender (testing)".
- **No Social Security numbers, no bank details, no text messages.**
- **No new writes to Track.** Square footage, the emergency contact and the
  two new fields ride in bodies Track already receives.
- **No real email from a laptop.** The two new Outbox producers never send for
  real from a laptop, whatever the allow-list says; the domain sender never
  calls Postmark outside production.
- **No domain is hard-coded** (Bryan is checking SkyRun's franchise agreement).
  Here the form's domain is written `<forms domain>`.

## The flow

1. Staff (ticked "Owner agreements") press **New owner**: a name, an email
   and/or a phone, then the variables: the property address, the split
   (owner % + manager % = 100, up to two decimals, default 70/30), the minimum
   revenue management fee (three periods, threshold + fee, default $0), and
   additional items. **Preview** shows the exact agreement. **Send by email**
   (the program's sender) or **Copy the link** (for a phone-only owner).
2. The owner opens one link, phone first, the intake form's look:
   welcome → the agreement in full ("Your terms" card, terms highlighted) →
   their section (page 8) → consent → sign (type or draw).
3. Then **Complete onboarding now** (the intake opens at once) or **Later**
   (the link by email). Either way the intake already exists, prefilled.
4. On signing: the owner is emailed a PDF marked "Awaiting SkyRun Park City's
   signature"; everyone who may countersign gets a request (email + in ENHQ),
   reminded after 24 h and 72 h; the team (ticked "Owner agreements", and the
   practice owner) is told, naming the owner and the property; people ticked
   "Receives signed PDFs" get the PDF.
5. Countersigning (below). The agreement's date is that day (practice time).
   The final PDF goes to the owner, to the signed-PDF people, and into the
   company's Documents.
6. The intake review shows the agreement's status and link; the Track
   contract is preselected from the split; the Contract Effective Date is
   preset to the countersigning date; **Send to Track stays off until the
   agreement is countersigned.** Intakes started without an agreement are not
   held back.

A correction before the owner signs is a new version; the same link opens it.
A signed agreement can't be edited. An unsigned one can be cancelled (its link
stops working).

**Status line per owner:** sent · opened · signed by owner · countersigned ·
form started · form submitted · sent to Track.

**Reminders** (hourly job `agreements.tick`): an unsigned agreement on days 3
and 7 after sending, from 9:00 practice time; an unfinished form on days 3
and 7 after it was made, from 9:00; countersigners 24 and 72 hours after the
owner signed, between 8:00 and 18:00.

## The agreement's words

- **One template now**, `apps/agreements/texts/rental_management_v2.txt`
  ("Rental Management Agreement", V.2 – November 2026), registered with its
  SHA-256 in `apps/agreements/texts/__init__.py`. A flat-fee "white glove"
  agreement is a second file and entry.
- **Locked.** The words change only by a commit through the gate;
  `tests/test_agreement_text.py` fails when the file and its pin disagree.
- **Against the 2014 PDF.** The blank PDF is in
  `tests/fixtures/agreements/` (SHA-256 pinned). The test reads its text with
  pypdf, applies the approved change list
  (`texts/rental_management_changes.py`) and compares word by word with the
  template rendered with bracketed variables. Any other difference fails; an
  entry the PDF doesn't have is listed and not applied. Matching ignores quote
  style, spacing and line breaks (owner); the page furniture (DocuSign line,
  footer), list bullets and dashed rules are dropped from the PDF's text.
  **Result (2026-11-24): all 53 finds applied, none missing, no other
  difference.** Set `AGREEMENT_TEXT_OUT` to keep the table.
- **The fee clause** (change B), in section 30 before the additional items,
  word for word, one line per period with a fee above $0; a fee above $0 with
  a $0 threshold is refused (it is never due). "None." when section 30 is empty.
- **Before countersigning** the date line reads "on the date of Manager's
  signature below"; the hash of the words the owner signed leaves it out.
- **One owner signs** for now ("ALL owners of condo must sign" stays).

## Countersigning (truthful record)

- SkyRun's block reads **Michael LeClerc, President** (template). "Who signs
  for the company" (Settings, practice owner only) names Michael's ENHQ user.
- Michael records a **standing authorization**, signed in as himself: he adopts
  his signature (typed or drawn) and names who may apply it to new-owner
  agreements, from the company's people (start: Michael, Jackie, Bryan). A new
  record each change; Withdraw ends it. Until one is recorded, only Michael can
  countersign.
- Anyone named countersigns with one tap (in ENHQ; the email's button opens
  ENHQ, signed in). The record shows Michael's signature **applied by** that
  person, **under his authorization of** its date, with their name, time, IP
  address and device; a line under the signature says so too. Michael's own
  countersignature says he signed personally. Never as if Michael pressed it.
- Before countersigning, the words are re-hashed: if they no longer match what
  the owner signed, nothing is countersigned.
- Owner-facing records print names only, never an email (Bryan has two
  accounts, practice owner and SkyRun Client owner; both may appear).

## The PDF

The 2014 original's order and style (Liberation Serif / Tinos): sections 1–30,
the owner's section, SkyRun's signature, the owner's, Exhibit A; footer
"V.2 – November 2026 · page · © Park City Ski Chalets, LLC". Then a
**signing record** (not part of the terms): template version and hash, sent
and opened times, each signer's name, time (practice and UTC), IP, device,
method, the consent words, the hash of the words signed, the agreement pages'
hash; for SkyRun, who applied it and under which authorization (with the
authorization's own words). The owner's copy says "Awaiting SkyRun Park City's
signature" on every page. Terms are highlighted only in staff's preview.

## People and permissions (owner, 2026-11-23)

One screen (Owner agreements → Settings), edited by the practice owner and the
company's Client owner (Bryan and Michael). Every active user of the company,
plus the practice owner, with three ticks:

a. Owner agreements: create, send, see agreements and their documents.
b. Receives signed agreement PDFs.
c. Owner intake: review, edit, send to Track, and the team notices.

The practice owner always has a and c. A new user starts with nothing ticked.
**Tick c replaced intake's "Manager or above" rule**; intake no longer looks at
team levels. Migration `agreements 0002` ticks c for everyone the old rule let
in (adds rows only). Final agreements in Documents: a or b, plus the practice
owner and the Client owner. Starting ticks to set at release: a for Sandra,
Jackie, Kendra, Michael and Bryan; b for Jackie (c comes from the migration).

## Owner email

Settings → Owner email, two values:

- **ENHQ's own sender (testing)** — the start. The practice's outbound mail
  (Outbox producer `owner_agreement`); owners would see Executives Now, and
  the screens say so.
- **Our own domain** — Postmark, from an address on a domain we control, with
  replies to the reply-to address. The domain, from-address, from-name and
  reply-to are settings. It can be chosen only after **Send a test to me**
  worked for that domain and address, in production.

If a send fails, owner emails **pause** (each held), the people ticked a and
the practice owner are told in ENHQ and by email, and **nothing goes out
another way**. Resume sends the held ones. A refusal about one recipient
(Postmark 300, 406) fails that email only and tells the same people.

**Postmark, what to do:** sign up at postmarkapp.com; create a Server (e.g.
"SkyRun owner emails"), its Transactional stream ("outbound"); Sender
Signatures → Add Domain → `<domain>`; add the DNS records it shows; Verify;
request account approval (until approved Postmark only sends to addresses on
the From domain, error 412). Railway variable (web and qcluster):
`OWNER_EMAIL_POSTMARK_TOKEN` (the Server API token).

**DNS for the sending domain:** a DKIM TXT record at
`<selector>pm._domainkey.<domain>` (the value Postmark shows, `k=rsa; p=…`); a
Return-Path CNAME `pm-bounces.<domain>` → `pm.mtasv.net` (use the host name
Postmark's DNS Settings page shows); a DMARC TXT at `_dmarc.<domain>`,
`v=DMARC1; p=none` to start. No SPF record is needed for Postmark.

**Later option: Kendra's Google mailbox.** Not built. Executives Now's Google
sign-in is the Internal client (getexecutivesnow.com accounts only); a
skyrun.com account is refused (`org_internal`). It needs the External client
per mailbox, send-only scopes, and Google's verification of that app (until
then a weekly reconnect), and possibly SkyRun's Workspace admin trusting the
client ID (Security → API controls → App access control).

## The form's address

Agreement pages live on the form's own domain at `/a/<token>`
(`https://<forms domain>/a/<token>`), or `PUBLIC_BASE_URL/forms/<slug>/a/<token>`
until a domain is set. Nothing beyond the intake form's domain setup
(docs/p14_intake_forms.md, "Adding a domain"); a domain at the root needs a DNS
host with CNAME flattening or ALIAS (Cloudflare, DNS only).

## Intake changes in this build

- **Bed types:** King Sofa Sleeper (Track id 20) sleeps 2, Roll Away Bed (21)
  sleeps 1, both offered in "Other places people sleep". A new bed type whose
  name the rules know arrives confirmed; unknown names start at 2, flagged.
- **Fields:** water softener → Water Softener (199, text), landscaping →
  Landscaping (200, text), "No" included. Other Maintenance or Service Notes
  (141) is switched off once when they move (it carried them).
- **The new-submission notice** (in ENHQ and by email) names the owner and the
  property's address. Task titles don't.
- **Test mode** (Form settings, on to start; missing means on): Send to Track
  runs every check (the plan's problems, the sensitive values, Track read for
  a matching owner, contact or unit), shows each step as "would send", writes
  nothing to Track and changes nothing in ENHQ (no tasks, no dates held,
  nothing deleted, not locked). The run and the intake are marked Test. A
  banner shows on the list, the review and Form settings.
- **Square footage** ("The property") → the unit's `area`. **Emergency
  contact** ("About you") → a new owner's `notes`; for an existing owner, a
  checklist task ("Add the emergency contact from the intake to the owner's
  notes in Track"), offered once to existing forms.

## Data and migrations

`agreements` 0001 (`agreement_program`, `agreement_staff_access`,
`owner_agreement`, `owner_agreement_version`, `owner_agreement_signature`,
`owner_agreement_authority`, `owner_agreement_event`, `owner_agreement_email`)
and 0002 (intake ticks from the old rule; data, adds rows only); `intake` 0002
(`send_run.test`); `crm` 0062 and `notify` 0008 (choices only, no SQL).
Schedule `agreements.tick` (hourly) needs `ensure_schedules` at release.
Templates: `templates/agreements/agreement_pdf.html`, `record_pdf.html`.

## Proof (2026-11-24, laptop, fake Track)

- Tests: `tests/test_agreement_text.py` (the words), `tests/test_agreements.py`
  (the whole way, permissions, the switch, senders, reminders, white label, no
  Track writes), `tests/test_intake_p15_changes.py`, `tests/test_agreements_browser.py`
  (Chrome), `frontend/src/forms/agreement.test.tsx`,
  `frontend/src/screens/Agreements.test.tsx`.
- Browser walks (screenshots and a sample signed PDF in
  `~/enhq-walks/owner-agreements/`): staff send at phone width; owner signs and
  chooses Now, the intake opens prefilled; Michael records his authorization;
  Jackie applies his signature; a second owner chooses Later.
- **Unproven:** anything against SkyRun's real Track (the `area` field's unit
  is not stated in Track's reference: read a unit back after the first real
  send); Postmark (no account yet); a real phone's drawing pad (Chrome's touch
  emulation only).
