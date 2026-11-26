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
- **No Social Security numbers, no bank details, no text messages.** The
  agreement still asks for none. Since 2026-11-24 the owner's intake form takes
  the tax number for the rental permit, an SSN or ITIN included (p14, "Tax
  numbers on the form"); bank details stay off it.
- **No new writes to Track.** Square footage, the emergency contact and the
  two new fields ride in bodies Track already receives.
- **No real email from a laptop.** The two new Outbox producers never send for
  real from a laptop, whatever the allow-list says; the domain sender never
  calls Postmark outside production.
- **No domain is hard-coded** (Bryan is checking SkyRun's franchise agreement).
  Here the form's domain is written `<forms domain>`.

## The flow

1. Staff (ticked "Owner agreements") press **New owner**: a name, an email
   and/or a phone, up to three more owners (name and email each, title
   optional; a shared email is allowed and warned about), then the variables: the property address, the split
   (owner % + manager % = 100, up to two decimals, default 70/30), the minimum
   revenue management fee (three periods, threshold + fee, default $0), and
   additional items. **Preview** shows the exact agreement. **Send by email**
   (the program's sender) or **Copy the link** (for a phone-only owner).
2. The owner opens one link, phone first, the intake form's look:
   welcome → their section (page 8) → the agreement in full, with their
   answers in it ("Your terms" card, terms highlighted; Exhibit A shows the
   numbers worked out from Sleeps) → consent → sign (type or draw). The
   details come first since 2026-11-24, so the owner reads the numbers they
   sign.
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

A correction before the first owner signs is a new version (the owners
included); the same link opens it. Once the first owner has signed nothing can
be corrected. See "Cancelling and starting again" for the rest.

**Status line per owner:** sent · opened · signed by owner (with several:
"signed by owners (2 of 3)") · countersigned · form started · form submitted ·
sent to Track, and under it whose turn it is ("Waiting for Pat Sample (owner 2
of 3) to sign", "Waiting for SkyRun's signature").

**Reminders** (hourly job `agreements.tick`): to whoever's turn it is, on days
3 and 7 counted from when their turn began (the first owner's from sending),
from 9:00 practice time; an unfinished form on days 3 and 7 after it was made,
from 9:00; countersigners 24 and 72 hours after the last owner signed, between
8:00 and 18:00.

## More than one owner (owner, 2026-11-24, later)

- Up to four owners (`owner_agreement_co_owner` holds 2 to 4). They sign in
  the order listed. Each later owner has their own link, issued and emailed
  when the owner before them signs; before that, the link says who signs
  first and shows nothing else. Staff "Email again" and "Copy the link" act on
  whoever's turn it is. Two owners may share an email; each still gets their
  own link, in turn, and the screen says "These owners share an email
  address. Each gets their own link."
- Only the first owner fills in the owner's page. Later owners read the whole
  agreement with those answers and sign; they can't change anything (the
  page's PATCH and the onboarding choice answer 403 for them).
- **The same words for everyone.** Every owner's signature stores the words
  and their SHA-256; a later owner can sign only if the words still hash to
  the first owner's, and countersigning checks every owner's. The signing
  record shows one "Words signed" and, for each later owner, that theirs is
  the same.
- One signature block per owner on the signature page, each with "NAME:" and
  the owner's name (and title); the record has a section per owner.
- The list of owners is fixed once the first owner signs.
- SkyRun's signature unlocks after the last owner signs; Send to Track waits
  for it as before.
- The first owner still gets **Complete onboarding now / Later** as soon as
  they sign; the intake is made then. Later owners get a thank-you page.
- Copies: nothing to the owners until the last one signs; then each address
  gets the "awaiting SkyRun's signature" copy, and later the final copy, once
  per address, greeting everyone who shares it. The team gets an email (no
  PDF) as each owner but the last signs, and today's email (with the copy for
  the signed-PDF people) and the countersign request when all have. With one
  owner nothing changed.

## Cancelling and starting again (owner, 2026-11-24, later)

- **Cancel** any time until SkyRun has signed, including after every owner
  has signed. A reason is required; it is recorded on the agreement, in its
  history and in the audit log. Every owner who already signed is emailed,
  once per address: subject "Your rental management agreement with {brand}
  was withdrawn", saying the agreement they signed for the property was
  withdrawn, won't take effect, nothing is needed from them, and {brand} will
  be in touch. Nobody else is emailed. After SkyRun has signed nothing can be
  cancelled or corrected.
- **Start a new agreement from this one**, on a cancelled agreement, once:
  a new draft (next number) with the same terms (the owner's corrected
  address included), the same owners and the first owner's answers, marked
  "Started from cancelled #N". The owner's intake **moves** to it: the same
  intake row, so its encrypted values (codes, the Wi-Fi password, a tax
  number) stay where they are, never copied, decrypted or re-encrypted. The
  intake's history says so, and Send to Track waits for the new agreement's
  countersignature. Every owner signs the new one.
- **When the words change after owners signed** (a change to Exhibit A's
  table, say), SkyRun can't sign. The agreement's screen says why in plain
  words: for Exhibit A, what the owners signed and what the table gives now,
  and to cancel (reason "Exhibit A changed"), start a new agreement from it
  and send it. Countersigning refuses with the same words.

## While acting as someone (owner, 2026-11-24)

While a person acts as another (FR-3.42), owner agreements refuses everything
that signs, authorizes or changes anything: recording or withdrawing the
authorization, applying the company signature, signing personally, creating,
correcting, sending (email or Copy link) or cancelling an agreement, changing
"Who signs for the company" or the sender, changing ticks on People and
permissions, and changing intake's test mode. The message: "You're acting as
[name]. Stop acting as them to do this." Viewing still works. The check is in
the views and again in the services (`services.not_while_acting`).

Intake's Send to Track and "Try the rest again", real sends and test sends,
are refused the same way while acting (owner, 2026-11-24, later; in the view
and in `intake.services.start_send`). Before that, a send while acting would
have recorded the person acted as in the intake's history, since acting
replaces `request.user`. The message comes from one place,
`apps.tenancy.context.acting_refusal`.

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
  **Result (2026-11-24, later): all 60 finds applied, none missing, no other
  difference.** Set `AGREEMENT_TEXT_OUT` to keep the table.
- **The owner's page** (A8, 2026-11-24, later), in two headed parts on one
  page: "Unit Information" (the property address from the opening, never
  typed again; # Bedrooms, # Bathrooms, Sq Footage, Sleeps) and "Owner
  Information" (as before; MAILING ADDRESS, ALTERNATE PHONE (optional)); the
  emergency block's sentence stays, with MAILING ADDRESS and PHONE. The
  emergency contact is required only with one owner.
- **Exhibit A from Sleeps** (A12 to A15): place settings P = 1.5 × Sleeps
  when Sleeps is 10 or fewer, 2 × Sleeps when it is 11 or more (decided
  2026-11-24, later), rounded up to a multiple of 4, at least 8 (Sleeps 10:
  16; 11: 24; 16: 32); dinnerware "P place settings (5 × P pieces)"; flatware
  "P place settings"; teaspoons P + 4; the four glasses P each; place mats a
  set of M, Sleeps rounded up to even, at least 4. One line each in
  `apps/agreements/exhibit_a.py`. Before Sleeps is answered each number reads
  "[from Sleeps]". They replace C38 and C41. A16 is the new "Other Features"
  paragraph. Each owner signature keeps the numbers it was signed with.
- **The fee clause** (change B), in section 30 before the additional items,
  word for word, one line per period with a fee above $0; a fee above $0 with
  a $0 threshold is refused (it is never due). "None." when section 30 is empty.
- **Before countersigning** the date line reads "on the date of Manager's
  signature below"; the hash of the words the owner signed leaves it out.
- **Up to four owners sign** ("(ALL owners of Unit must sign)", 2026-11-24).
  The "Applied by … under …'s authorization" and "Signed personally by" lines
  are on the signing record only, no longer under SkyRun's signature.

## Countersigning (truthful record)

- SkyRun's block reads **Michael LeClerc, President** (template). "Who signs
  for the company" (Settings, practice owner only) names Michael's ENHQ user.
- Michael records a **standing authorization**, signed in as himself: he adopts
  his signature (typed or drawn) and names who may apply it to new-owner
  agreements, from the company's people (start: Michael, Jackie, Bryan). A new
  record each change; Withdraw ends it. Until one is recorded, only Michael can
  countersign.
- Anyone named countersigns with one tap (in ENHQ; the email's button opens
  ENHQ, signed in).
- **Names come from the account, never the template** (owner, 2026-11-24).
  Every line about SkyRun's signature or the authorization prints the full
  name of the signed-in account that did it: "Signed personally by [account]",
  "Applied by [account] under the authorization [account] recorded on
  [date]", and the authorization's own words ("I, [account], adopt the
  signature shown here as SkyRun Park City's signature in the block that reads
  “Michael LeClerc, President”…", wording version 2026-11-24; the 2026-11-23
  words are kept for anything signed under them). The name is kept as it was
  that day (`AgreementSignature.applied_by_name`,
  `CountersignAuthority.recorded_by_name`). The agreement's signature block
  still reads "Michael LeClerc, President". The audit log keeps the account's
  id and email (`agreements.countersigned`, `agreements.authority_recorded`);
  the PDF prints names only, no staff email and never an Executives Now address.
- **The words on the screen are the words recorded** (owner, 2026-11-25). The
  authorization screen shows its consent from the same function the record
  keeps it from (`services.authorization_words`), the signed-in account's name
  in it ("I, Michael LeClerc, adopt…"). Until then the screen showed "I, ,
  adopt…" while the record held the name.
- Before countersigning, the words are re-hashed: if they no longer match what
  the owner signed, nothing is countersigned.
- Owner-facing records print names only, never an email (Bryan has two
  accounts, practice owner and SkyRun Client owner; both may appear).
- **Two people of one name** (owner, 2026-11-25): wherever a list on screen
  holds both, each says its role by name. The authorization in force reads
  "Bryan Baker (Practice owner), Bryan Baker (Client owner)"; so do the
  signer picker and the app's people pickers (`frontend/src/lib/people.ts`).
  Everyone else keeps their plain name. The record itself keeps ids and names.

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

**The two fingerprints** (owner, 2026-11-24) sit together under "Fingerprints"
on the record, with these sentences under them, as written. Where they say
"SkyRun Park City" they use the intake form's brand name (owner, 2026-11-24,
later), the same name the signing words use, so the two always match; on
SkyRun's form it is "SkyRun Park City". The record's other mentions (its
opening line, "Manager, SkyRun Park City", the awaiting stamp) are unchanged.

> Words signed is the fingerprint of the full text of the agreement as the Owner
> saw and signed it: every section, the terms set for this Owner, the property
> address and the Owner's answers. In that text the agreement date read 'on the
> date of Manager's signature below', and it contains no signatures.
>
> Agreement pages is the fingerprint of the finished pages above, which add the
> agreement date and both signatures. The agreement date was filled in when
> SkyRun Park City signed.
>
> SkyRun Park City keeps the exact text the Owner signed and can provide it on
> request.

On the owner's copy, before SkyRun signs, the second sentence would not be true
yet, so it reads: "Agreement pages is the fingerprint of the pages above, signed
by the Owner. SkyRun Park City has not signed yet; its signature and the
agreement date are added when it does."

**The exact signed text is kept**, unchanged, on the owner's signature
(`AgreementSignature.signed_text`, written once at signing); its SHA-256 is
"Words signed". People ticked "Receives signed agreement PDFs" download it as
plain text (`GET /api/agreements/<id>/signed-text`, from the agreement page and
the company's Documents).

## People and permissions (owner, 2026-11-23)

One screen, `/permissions/<company id>` ("People and permissions"), edited by
the practice owner and the company's Client owner (Bryan and Michael). It is
reachable whenever intake forms **or** owner agreements are on for the company
(owner, 2026-11-24), and shows only the columns for what is on: a and b with
owner agreements, c with intake. Form settings, the intake list and agreement
Settings link to it. Every active user of the company, plus the practice
owner, with up to three ticks:

a. Owner agreements: create, send, see agreements and their documents.
b. Receives signed agreement PDFs.
c. Owner intake: review, edit, send to Track, and the team notices.

The practice owner always has a and c. A new user starts with nothing ticked.
**Tick c replaced intake's "Manager or above" rule**; intake no longer looks at
team levels. Migration `agreements 0002` ticks c for everyone the old rule let
in (adds rows only). Final agreements in Documents: a or b, plus the practice
owner and the Client owner. Starting ticks to set at release: a for Sandra,
Jackie, Kendra, Michael and Bryan; b for Jackie (c comes from the migration).

**The send log** (owner, 2026-11-24, after the demo walk): owner agreement mail
(producers `owner_agreement`, `owner_agreement_notice`) shows only to someone
ticked a for that company, intake notices (`intake_notice`) only to someone
ticked c, and a code to see a tax number (`tax_number_code`) only to the person
it went to; the practice owner sees all of it. The same rule
(`crm.permissions.without_owner_mail`) holds wherever those rows show: the
Outbox send log, the Sending queue (and the AI apps' sending_queue tool), the
Activity feed, and the shared email history (the thread each message is on,
with any reply). Mail that can't be traced to a company is shown to nobody but
the practice owner. Today only company users can be ticked and only the
practice's staff have a send log, so in practice the practice owner is the one
who sees it; an Assistant or an Associate sees none of it.

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

- **From the agreement** (2026-11-24, later): bedrooms, bathrooms and square
  footage as before, and now Sleeps, as the staff's "Total sleeps" (what goes
  to Track as the unit's occupancy); the review shows "On the agreement: N"
  beside what the beds add up to. The other owners prefill the intake's
  additional owners (name and email).
- **Bed types:** King Sofa Sleeper (Track id 20) sleeps 2, Roll Away Bed (21)
  sleeps 1, both offered in "Other places people sleep". A new bed type whose
  name the rules know arrives confirmed; unknown names start at 2, flagged.
- **Fields:** water softener → Water Softener (199, text), landscaping →
  Landscaping (200, text), "No" included. Other Maintenance or Service Notes
  (141) is switched off once when they move (it carried them).
- **The new-submission notice** (in ENHQ and by email) names the owner and the
  property's address. Task titles don't.
- **Test mode** (Form settings, on to start; missing means on). Only the people
  who may change People and permissions (the practice owner and the Client
  owner) turn it on or off (`POST /api/intake/companies/<id>/test-mode`); Form
  settings' own Save can't change it. Everyone else sees its state. Each change
  is its own audit event (`intake.test_mode_changed`, with who, when, from and
  to), and Form settings shows the latest ("Test mode turned off by [name] on
  [date]"). Never while acting as someone. With it on, Send to Track
  runs every check (the plan's problems, the sensitive values, Track read for
  a matching owner, contact or unit), shows each step as what it would create
  or set in plain words ("Would be created in Track", "Would be set on the
  unit in Track"; owner, 2026-11-25), writes nothing to Track and changes
  nothing in ENHQ (no tasks, no dates held, nothing deleted, not locked). The
  call each step would make stays out of sight, in the saved run's `request`
  ("POST /pms/units"). The run and the intake are marked Test. A banner shows
  on the list, the review and Form settings.
- **Square footage** ("The property") → the unit's `area`. **Emergency
  contact** ("About you") → a new owner's `notes`; for an existing owner, a
  checklist task ("Add the emergency contact from the intake to the owner's
  notes in Track"), offered once to existing forms.

## Data and migrations

`agreements` 0001 (`agreement_program`, `agreement_staff_access`,
`owner_agreement`, `owner_agreement_version`, `owner_agreement_signature`,
`owner_agreement_authority`, `owner_agreement_event`, `owner_agreement_email`)
and 0002 (intake ticks from the old rule; data, adds rows only); `intake` 0002
(`send_run.test`); `crm` 0062 and `notify` 0008 (choices only, no SQL);
`agreements` 0003 (2026-11-24: `owner_agreement_signature.signed_text` and
`owner_agreement_authority.recorded_by_name`, both text with a default '');
`agreements` 0004 (2026-11-24, later: the table `owner_agreement_co_owner`;
`owner_agreement.all_signed_at`, `cancel_reason`, `started_from_id`;
`owner_agreement_signature.position` and `exhibit_a`, and its one-per-role
constraint becomes one per role and position; `owner_agreement_email.position`;
a data step setting `all_signed_at` from `owner_signed_at` for agreements
already signed by their one owner).
Schedule `agreements.tick` (hourly) needs `ensure_schedules` at release.
Templates: `templates/agreements/agreement_pdf.html`, `record_pdf.html`.

## Proof (2026-11-24, laptop, fake Track)

- Tests: `tests/test_agreement_text.py` (the words), `tests/test_agreements.py`
  (the whole way, permissions, the switch, senders, reminders, white label, no
  Track writes), `tests/test_intake_p15_changes.py`, `tests/test_agreements_browser.py`
  (Chrome), `tests/test_agreements_owners.py` (several owners in order,
  the same words, reminders by turn, corrections, cancelling with a reason
  and who is told, starting again with the intake carried over, an Exhibit A
  change named, both pages on one page, what the intake is given),
  `frontend/src/forms/agreement.test.tsx`,
  `frontend/src/screens/Agreements.test.tsx`.
- Added 2026-11-24: `tests/test_agreements_fixes.py` (acting as someone, names
  from the account, the fingerprints and the signed text, the permissions
  screen with intake alone and with both, test mode, stored Outbox copies, no
  trace when off) and `tests/test_agreements_ai_sweep.py` (every MCP tool and
  prompt, the in-app AI features that take company data, and a check of every
  module that calls Claude: no owner's name, email, address, the agreement's
  title or a link reaches any of them). `frontend/src/screens/IntakeSettings.test.tsx`
  (test mode's latest change and who may change it; the links to People and
  permissions from Form settings and the intake list).
- Browser walks (screenshots and a sample signed PDF in
  `~/enhq-walks/owner-agreements/`): staff send at phone width; owner signs and
  chooses Now, the intake opens prefilled; Michael records his authorization;
  Jackie applies his signature; a second owner chooses Later.
- **Unproven:** anything against SkyRun's real Track (the `area` field's unit
  is not stated in Track's reference: read a unit back after the first real
  send); Postmark (no account yet); a real phone's drawing pad (Chrome's touch
  emulation only).
