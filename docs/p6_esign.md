# E-signature, version one — as built

Owner's brief, 2026-10-29. Code: `apps/esign/`; screens:
`frontend/src/components/Documents.tsx` (the company card),
`frontend/src/screens/SignDocument.tsx` (the signing page),
`DocumentTemplates.tsx` (Settings → Documents), `PortalDocuments.tsx` (the portal).
Tests: `tests/test_esign.py`, `frontend/src/screens/SignDocument.test.tsx`.

## Scope

One document, one client signer, one countersignature from the practice.
A document is a **proposal or engagement letter made from a document
template**, or **any PDF uploaded**. Multi-signer documents and an automatic
invoice on signing are version two.

## Settings → Documents

The practice owner's, like Email templates: the same editor and merge chips.
Two built-ins, **Proposal** and **Engagement letter**, each with
`{Scope}`, `{Fee}`, `{Term}` and `{StartDate}`, and "Restore the original".
Merge fields: `{FirstName}`, `{LastName}` (the signer's), `{Company}`,
`{FractionalName}` (who makes it), `{PracticeName}`, `{Today}`, and the four
document fields. A line starting `# ` is a heading. An unknown field is
refused when saved. The library is seeded on first sight, so a practice made
before e-signature has it the first time it opens the page.

## The company card

**Documents**, on every company page.

1. **New document**: a template (fill in the fields it uses) or an uploaded
   PDF (title and file; checked: a readable, unencrypted PDF, 15 MB at most),
   and the signer, one of the company's contacts with an email address.
2. **Preview**: the PDF as it will be, not yet kept.
3. **From** (a connected mailbox, or the usual for the company) and **Send for
   approval**: the document is made (Draft) and its email goes in the Outbox,
   waiting for approval like every other email, with a `{SignLink}` chip.
4. **Approval sends it.** The link is made at delivery and is never stored on
   the Outbox row (the row keeps the chip). If someone edits the chip out,
   the link is added at the end. Delivery makes the document **Sent** and
   starts its 30 days.

A draft made from a template can be **filled in again** (a new PDF and a new
hash) until its email is approved; a rule's draft starts with its fields
blank for exactly that. Each row shows the state and its dates, the PDFs
(as sent; signed by the client; the final signed copy), and **Countersign**
and **Void** where they apply. On the demo only, **Open the signing page**.

## Lifecycle

Draft → Sent → Viewed → Signed or Declined → Countersigned → Complete;
**Void** (the practice withdraws it: Draft, Sent, Viewed or Signed; a waiting
request email is rejected with it) and **Expired** (30 days after it was
sent, unsigned). Countersigned is passed through on the way to Complete: the
countersignature, the final PDF and its email happen in one step.

## The signing link and page

`/sign/<token>`, public, phone-first.

- **Token**: an HMAC of the document and the moment its link was issued,
  under the app's secret key (`links.py`, the pay link's pattern). Only its
  SHA-256 is stored. **One use**: signing or declining clears it, and so does
  voiding; it also stops at the document's expiry. A wrong, used, voided or
  expired link is the same 404. Requests are rate-limited per link and per
  address.
- **The page** shows the PDF (in a frame, and full size from its own link),
  the first part of its SHA-256, the consent line, and the signature: typed
  (shown in Dancing Script, the cursive face the PDF embeds) or drawn (a PNG
  of the pad). **Decline** needs a reason.
- **The first look** makes the document Viewed and tells the sender.

## The consent line

Kept by version in `apps/esign/consent.py`; each signature stores the version
and the words exactly as shown. Version `2026-10-29`:

> By signing electronically, I agree that my electronic signature is the legal
> equivalent of my handwritten signature on this document, and I consent to use
> electronic records and signatures for it under the U.S. ESIGN Act and UETA. I
> understand that I may ask {practice} for a paper copy at no charge; that I may
> withdraw this consent before I sign by choosing Decline instead, which ends
> electronic signing of this document but does not undo anything already signed;
> that I need a device that can open PDF files to read and keep this document;
> that a copy of the signed document will be emailed to {email}; and that I
> should tell {practice} if that email address changes.

The countersigner ticks a shorter line on the card (their signature is the
practice's own act), stored with the same version key and its own words.

## What is recorded

Per signature (`document_signature`): role, name, email, the user (for the
countersigner), typed text or drawn PNG, consent version and words, IP
address, user agent, the time, and **the SHA-256 of the exact PDF signed**.
Signing and countersigning first recompute the stored PDF's hash and refuse
if it differs from the one recorded when the document was made (logged as
`document.hash_mismatch`). Every step is an audit event.

## The letterhead

Done 2026-10-31. Documents made from a template, and the signature page on
every document, wear the strategy map PDF's letterhead (`templates/esign/pdf.html`,
with `strategy/pdf_brand.html` and the same images, faces and measurements): the
practice's mark beside its name, or its logo, or with neither the drawn mark in
its colors; its colors on the headings; "Prepared by … · Confidential to …" in
the footer; on every page, 48px at the sides, Lato and Lora. An uploaded PDF
stays as uploaded apart from its signature page. A PDF is rendered and hashed
once, when the document is made, so a later branding change never alters one
already made.

## The signature page

Appended after the last page: per signature, the name, the signature (typed
in the embedded cursive face, or the drawn image), the time in UTC, email,
IP, how it was signed, the consent version, and the document's SHA-256.
Signing appends it with the signer's; countersigning makes it again with both,
onto the PDF as sent, which is the **final PDF**: kept on the company and
emailed to the signer and the countersigner, attached. Its own SHA-256 is
shown on the card.

## Every day

In the existing daily stage-rules job (`crm.stage_rules_daily`, 7:00 at the
practice), so no new schedule: an unsigned document 30 days after it was sent
**expires**; one 7 days after, unsigned, gets **one reminder**, sent straight
away (fixed words, the same link, never stored on the row).

## Pipeline

- Action **"Send a document for signature"**, with a document template: the
  contact's document (their company's), fields blank, its email in the Outbox
  for approval. Skipped, and logged, for a contact with no company or email.
- Triggers **"Is sent a document to sign"** and **"Signs a document"**, for
  the signer, on the rule's pipeline. A move from either only goes forward:
  someone already past the stage it names stays where they are. "Send a
  document" on "is sent a document" is refused (it would never stop).
- **Defaults**, for new practices and on the demo: sent → Proposal Given;
  signed → Closed Won; and entering Closed Won drafts the Welcome letter into
  the Outbox for approval. Existing practices can add all three from the
  stage rules' examples.

## The welcome letter

A built-in email template, **Welcome letter**, with `{Scope}`, `{Fee}`,
`{Term}` and `{StartDate}` from the company's latest signed document and
`{Goals}` (the company's goals, one a line). Each of those lines drops out
when it has nothing to say. Any email template can use them.

## Notices

To the person who sent it (the practice owner if they have left): **viewed**,
**signed**, **declined**, and **countersign needed**, as a notice and a
browser push ("A document you sent for signature", a new kind people can turn
on).

## Who

| | Practice owner | Associate | Assistant | Client owner / team member |
|---|---|---|---|---|
| Settings → Documents | edits | reads (to make one) | reads | — |
| Make, send, void, countersign | yes | assigned companies | — | — |
| See documents | all | assigned companies | state, signer and dates only | their own company's, from Sent on, in the portal |
| PDFs | yes | assigned companies | — | their company's |

## The demo

Pied Piper's engagement letter, complete; Jack Donaghy's proposal at
Sheinhardt Wig Company, sent and opened, waiting. **Open the signing page**
(the demo only) lets a visitor be the signer too: signing it moves Jack to
Closed Won, and the visitor countersigns. Mail still goes only to the demo's
redirect, and the reminder and the signed copy with it.

## Decided here (simplest reading)

- The signer is chosen with the fields, before the preview, so the preview
  shows their name.
- Associates send and countersign (the brief says "owners and associates");
  the library is the practice owner's to edit, as Email templates are.
- "Their own" in the portal: their company's documents, as invoices are.
- The reminder reuses the one link rather than issuing a new one.
- Expiry and the reminder run in the existing daily job, not a new one.
- Countersigned and Complete happen in one step.

## Version two (not built)

- **Several signers** on one document, and **the invoice created on signing**
  (from the Scope 'Version one' leaves out).
