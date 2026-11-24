"""The agreement as a PDF, in the 2014 original's style and order: sections 1
to 30, the owner's section, SkyRun's signature, the owner's, Exhibit A; the
footer "V.2 – November 2026 · page · © Park City Ski Chalets, LLC" (change
A10). Then, on its own page after Exhibit A, the signing record (A11): not
part of the agreement's terms.

- The owner's copy, made when they sign, says on every page that it is
  awaiting SkyRun's signature.
- The final copy, made on countersigning, carries both signatures and the
  agreement's date.
- The signing record names who signed and who applied SkyRun's signature,
  when, from what IP address and device, the consent words, the template
  version, the hash of the words the owner signed, and the hash of the
  agreement's pages. SkyRun's side is named, never with an email.

White label: nothing names the product or the practice.
"""

from __future__ import annotations

import base64
import hashlib
import io
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.template.loader import render_to_string

from . import render, texts
from .models import AgreementSignature

SCRIPT_FONT = (texts.HERE.parent.parent / "esign" / "fonts" / "DancingScript-Medium.ttf")

#: Under the two fingerprints on the signing record (owner, 2026-11-24, as written),
#: with the form's brand name for {brand} (owner, 2026-11-24, later), so they always match
#: the signing words; on SkyRun's form it is "SkyRun Park City".
FINGERPRINTS = (
    "Words signed is the fingerprint of the full text of the agreement as the Owner saw and "
    "signed it: every section, the terms set for this Owner, the property address and the "
    "Owner's answers. In that text the agreement date read 'on the date of Manager's "
    "signature below', and it contains no signatures.",
    "Agreement pages is the fingerprint of the finished pages above, which add the agreement "
    "date and both signatures. The agreement date was filled in when {brand} signed.",
    "{brand} keeps the exact text the Owner signed and can provide it on request.",
)
#: The owner's copy, before SkyRun signs: the second sentence would not be true yet.
FINGERPRINTS_AWAITING = (
    FINGERPRINTS[0],
    "Agreement pages is the fingerprint of the pages above, signed by the Owner. {brand} "
    "has not signed yet; its signature and the agreement date are added when it does.",
    FINGERPRINTS[2],
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _png(sig) -> str:
    if sig is not None and sig.method == "drawn" and sig.drawn_png:
        return "data:image/png;base64," + base64.b64encode(bytes(sig.drawn_png)).decode()
    return ""


def _when(moment, company) -> str:
    if moment is None:
        return ""
    tz = ZoneInfo(getattr(company.tenant, "timezone", "") or "UTC")
    local = moment.astimezone(tz)
    utc = moment.astimezone(dt_timezone.utc)
    return (f"{local:%B} {local.day}, {local.year} at {local:%-I:%M:%S %p %Z} "
            f"({utc:%Y-%m-%d %H:%M:%S} UTC)")


def _date(day) -> str:
    return f"{day:%B} {day.day}, {day.year}" if day else ""


def _sig(agreement, role, position=1):
    return AgreementSignature.all_objects.filter(agreement=agreement, role=role,
                                                 position=position).first()


def _owner_sigs(agreement) -> dict:
    return {s.position: s for s in
            AgreementSignature.all_objects.filter(agreement=agreement, role="owner")}


def _write(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=str(texts.HERE)).write_pdf()


def _signature_block(agreement, sig, *, owner: bool) -> dict:
    if sig is None:
        return {"signed": False}
    out = {"signed": True, "png": _png(sig), "typed": sig.typed_text,
           "date": _date(sig.signed_at.astimezone(ZoneInfo(
               getattr(agreement.company.tenant, "timezone", "") or "UTC")).date()
               if owner else agreement.agreement_date)}
    # Who applied SkyRun's signature, and under what, is on the signing record
    # only (owner, 2026-11-24), never under the signature.
    return out


def pages(agreement, *, final: bool, preview_terms=None, preview_details=None) -> bytes:
    """The agreement's pages (no signing record)."""
    from . import services

    tpl = texts.get(agreement.template_key if agreement else texts.DEFAULT)
    if preview_terms is not None:
        terms, details, day = preview_terms, preview_details or {}, None
    else:
        terms, details = services.terms_for(agreement), agreement.details or {}
        day = agreement.agreement_date if final else None
    names = services.signing_owners(agreement) if agreement else None
    blocks = render.document(tpl.key, terms, details, agreement_date=day, owners=names)
    sigs = _owner_sigs(agreement) if preview_terms is None else {}
    owner_blocks = [{**_signature_block(agreement, sigs.get(i + 1), owner=True),
                     "name": render.owner_name_line(o)}
                    for i, o in enumerate(names or render.UNNAMED)]
    manager_sig = _sig(agreement, "manager") if (final and preview_terms is None) else None
    banner = ("Preview: not for signing" if preview_terms is not None else
              "" if final else "Awaiting SkyRun Park City’s signature")
    html = render_to_string("agreements/agreement_pdf.html", {
        "blocks": blocks, "tpl": tpl, "banner": banner, "script_font": SCRIPT_FONT.as_uri(),
        # The terms are highlighted in the staff's preview only, never in a signed copy.
        "highlight": preview_terms is not None,
        "owners": owner_blocks, "compact": len(owner_blocks) > 2,
        "manager": _signature_block(agreement, manager_sig, owner=False),
    })
    return _write(html)


def record(agreement, *, final: bool, pages_sha256: str) -> bytes:
    company = agreement.company
    tpl = texts.get(agreement.template_key)
    sigs = _owner_sigs(agreement)
    owner_sig = sigs.get(1)
    manager_sig = _sig(agreement, "manager") if final else None
    rows = [("Agreement", f"{tpl.title}, #{agreement.number}, for "
                          f"{render.one_line(_terms(agreement).get('property_address'))}"),
            ("Template", f"{tpl.version}; template SHA-256 {tpl.sha256}"),
            ("Sent", _when(agreement.sent_at, company)),
            ("Opened", _when(agreement.opened_at, company))]
    from .services import _brand, authority_by
    from .services import owners as owners_of

    signers = []
    everyone = owners_of(agreement)
    for o in everyone:
        sig = sigs.get(o["position"])
        if sig is None:
            continue
        signers.append({
            "role": "Owner" if len(everyone) == 1 else f"Owner {o['position']} of {len(everyone)}",
            "png": _png(sig), "typed": sig.typed_text,
            "rows": [("Name", sig.printed_name + (f", {sig.printed_title}"
                                                 if sig.printed_title else "")),
                     ("Email", o["email"]),
                     ("Signed", _when(sig.signed_at, company)),
                     ("IP address", sig.ip_address or "not recorded"),
                     ("Device", sig.user_agent or "not recorded"),
                     ("Signature", "Typed" if sig.method == "typed" else "Drawn")]
            + ([("Words signed", "the same as the first owner's (SHA-256 below)"
                 if sig.text_sha256 == owner_sig.text_sha256 else
                 f"DIFFERENT: SHA-256 {sig.text_sha256}")] if o["position"] > 1 else []),
            "consent": sig.consent_text,
            "consent_label": f"Consent to sign electronically (version "
                             f"{sig.consent_version}), ticked before signing"})
    if manager_sig:
        authority = manager_sig.authority
        block = (f"{manager_sig.printed_name}, {manager_sig.printed_title} "
                 "(as printed in the agreement)")
        # Owner, 2026-11-24: who did it is the signed-in account's own name.
        how = ([("Signature block", block),
                ("Signed personally by", manager_sig.applied_by_name)]
               if authority is None else
               [("Signature block", block),
                ("Applied by", manager_sig.applied_by_name),
                ("Under", f"the standing authorization recorded by {authority_by(authority)} "
                          f"on {_when(authority.recorded_at, company)} from IP address "
                          f"{authority.ip_address or 'not recorded'}")])
        signers.append({
            "role": "Manager, SkyRun Park City", "png": _png(manager_sig),
            "typed": manager_sig.typed_text,
            "rows": how + [("Applied" if authority else "Signed",
                            _when(manager_sig.signed_at, company)),
                           ("IP address", manager_sig.ip_address or "not recorded"),
                           ("Device", manager_sig.user_agent or "not recorded"),
                           ("Agreement date", _date(agreement.agreement_date))],
            "consent": manager_sig.consent_text,
            "consent_label": "The words agreed when it was applied" if authority
            else "The words agreed when signing",
            "authorization": authority.wording if authority else ""})
    html = render_to_string("agreements/record_pdf.html", {
        "rows": rows, "signers": signers, "pages_sha256": pages_sha256, "final": final,
        "words_sha256": owner_sig.text_sha256 if owner_sig else "",
        "explain": [sentence.replace("{brand}", _brand(company))
                    for sentence in (FINGERPRINTS if final else FINGERPRINTS_AWAITING)],
        "script_font": SCRIPT_FONT.as_uri()})
    return _write(html)


def _terms(agreement):
    from . import services

    return services.terms_for(agreement)


def joined(first: bytes, second: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(first)))
    writer.append(PdfReader(io.BytesIO(second)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build(agreement, *, final: bool) -> tuple[bytes, str]:
    """(the PDF, the hash of its agreement pages)."""
    body = pages(agreement, final=final)
    body_sha = sha256(body)
    return joined(body, record(agreement, final=final, pages_sha256=body_sha)), body_sha


def _store(agreement, content: bytes, name: str):
    from apps.tenancy import storage

    return storage.save(tenant=agreement.company.tenant, content=content,
                        object_key=storage.object_key("owner-agreements", name),
                        purpose="owner_agreement", content_type="application/pdf")


def store_owner_copy(agreement):
    content, _ = build(agreement, final=False)
    stored = _store(agreement, content, f"agreement-{agreement.number}-owner-signed.pdf")
    agreement.owner_pdf, agreement.owner_pdf_sha256 = stored, sha256(content)
    agreement.save(update_fields=["owner_pdf", "owner_pdf_sha256"])
    return stored


def store_final(agreement):
    content, _ = build(agreement, final=True)
    stored = _store(agreement, content, f"agreement-{agreement.number}-final.pdf")
    agreement.final_pdf, agreement.final_pdf_sha256 = stored, sha256(content)
    agreement.save(update_fields=["final_pdf", "final_pdf_sha256"])
    return stored


def preview(agreement, terms=None) -> bytes:
    """Staff's preview of the exact agreement, marked as a preview."""
    from . import services

    return pages(agreement, final=False,
                 preview_terms=terms if terms is not None else services.terms_for(agreement),
                 preview_details=agreement.details or {})
