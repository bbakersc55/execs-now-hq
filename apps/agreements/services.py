"""Owner agreements: the staff side, the owner's side, the countersignature,
and the hand-off to the owner's intake (docs/p15_owner_agreements.md).

Nothing here writes to Track. The intake an agreement starts goes to Track
the usual way, after the agreement is countersigned.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.tenancy.context import tenant_context

from . import access, consent, render, texts
from .texts import rental_management_changes as changes
from .models import (
    AgreementEvent, AgreementSignature, AgreementVersion, CountersignAuthority, OwnerAgreement,
    Program,
)

log = logging.getLogger(__name__)

PERIOD_KEYS = ("winter", "summer", "fall")
MOST_ITEMS = 4000
MAX_DRAWN_BYTES = 300 * 1024
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Refused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------ the program

def program_for(company, *, create=False):
    program = Program.all_objects.filter(company=company).first()
    if program is None and create:
        program = Program.all_objects.create(tenant_id=company.tenant_id, company=company,
                                             from_name=company.name[:120])
    return program


def practice_today(company):
    from apps.scorecard import board

    return board.today_for(company.tenant)


def practice_now(company):
    tz = getattr(company.tenant, "timezone", "") or "UTC"
    return timezone.now().astimezone(ZoneInfo(tz))


# ------------------------------------------------------------ terms

def _money(value, what) -> str:
    try:
        d = Decimal(str(value if value not in (None, "") else 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise Refused(f"{what} isn't a number.") from None
    if d < 0 or d > Decimal("10000000"):
        raise Refused(f"{what} is out of range.")
    return format(d.normalize(), "f") if d == d.to_integral_value() else format(d, "f")


def _clean_address(data) -> dict:
    d = data if isinstance(data, dict) else {}
    out = {k: " ".join(str(d.get(k) or "").split())[:120] for k in
           ("street", "unit", "city", "state", "zip")}
    out["state"] = out["state"][:40]
    out["zip"] = out["zip"][:16]
    return out


def clean_terms(data) -> dict:
    """The variables staff set (owner, 2026-11-23): the split (owner and
    manager percent, totalling 100), the minimum revenue management fee per
    period (threshold and fee), the additional items, and the address."""
    d = data if isinstance(data, dict) else {}
    try:
        owner = Decimal(str(d.get("owner_percent", 70))).quantize(Decimal("0.01"))
        manager = Decimal(str(d.get("manager_percent", 30))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise Refused("The split needs two numbers.") from None
    if not (0 <= owner <= 100 and 0 <= manager <= 100) or owner + manager != 100:
        raise Refused("The owner's and the manager's percent must add up to 100.")
    fees = {}
    raw = d.get("fees") if isinstance(d.get("fees"), dict) else {}
    for key in PERIOD_KEYS:
        row = raw.get(key) if isinstance(raw.get(key), dict) else {}
        threshold = _money(row.get("threshold"), "A revenue threshold")
        fee = _money(row.get("fee"), "A fee")
        if Decimal(fee) > 0 and Decimal(threshold) <= 0:
            period = dict(changes.PERIODS)[key]
            raise Refused(f"{period}: a fee needs a revenue threshold above $0, or it is never "
                          "due.")
        fees[key] = {"threshold": threshold, "fee": fee}
    items = str(d.get("additional_items") or "").strip()[:MOST_ITEMS]

    def pct(x):
        return format(x.normalize(), "f") if x != x.to_integral_value() else str(int(x))

    return {"owner_percent": pct(owner), "manager_percent": pct(manager), "fees": fees,
            "additional_items": items,
            "property_address": _clean_address(d.get("property_address"))}


def default_terms() -> dict:
    return clean_terms({})


# ------------------------------------------------------------ staff: owners

def _event(agreement, kind, *, actor=None, detail="", ip=None, user_agent=""):
    AgreementEvent.all_objects.create(tenant_id=agreement.tenant_id, agreement=agreement,
                                      kind=kind, actor=actor, detail=detail[:300],
                                      ip_address=ip or None, user_agent=(user_agent or "")[:500])


def _contact(name, email, phone):
    name = " ".join(str(name or "").split())[:200]
    email = str(email or "").strip().lower()[:200]
    phone = " ".join(str(phone or "").split())[:40]
    if not name:
        raise Refused("Enter the owner's name.")
    if not email and not phone:
        raise Refused("Enter the owner's email, or a phone number, or both.")
    if email and not _EMAIL.match(email):
        raise Refused("That email doesn't look right.")
    return name, email, phone


def current(agreement) -> AgreementVersion:
    return (AgreementVersion.all_objects.filter(agreement=agreement, replaced_at__isnull=True)
            .order_by("-revision").first())


def create(company, *, name, email="", phone="", terms=None, actor=None,
           template_key=texts.DEFAULT) -> OwnerAgreement:
    from apps.crm.models import Company

    if not access.is_on(company):
        raise Refused("Owner agreements aren't on for this company.", 404)
    name, email, phone = _contact(name, email, phone)
    cleaned = clean_terms(terms or {})
    tpl = texts.get(template_key)
    with transaction.atomic():
        Company.all_objects.select_for_update().filter(pk=company.pk).first()
        number = (OwnerAgreement.all_objects.filter(company=company)
                  .aggregate(n=Max("number"))["n"] or 0) + 1
        first, _, last = name.partition(" ")
        agreement = OwnerAgreement.all_objects.create(
            tenant_id=company.tenant_id, company=company, number=number,
            template_key=tpl.key, owner_name=name, owner_email=email, owner_phone=phone,
            created_by=actor,
            # The owner's section starts with what staff entered; they can change it.
            details=clean_details({"first_name": first, "last_name": last, "email": email,
                                   "phone": phone}))
        AgreementVersion.all_objects.create(
            tenant_id=company.tenant_id, agreement=agreement, revision=1, template_key=tpl.key,
            template_version=tpl.version, template_sha256=tpl.sha256, terms=cleaned,
            created_by=actor)
    _event(agreement, "created", actor=actor, detail=f"Agreement #{number} created")
    return agreement


def _editable(agreement):
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    if agreement.owner_signed_at is not None:
        raise Refused("The owner has signed this agreement. A signed agreement can't be "
                      "edited.", 409)


def update(agreement, *, name=None, email=None, phone=None, terms=None, actor=None):
    """Staff correct an agreement the owner hasn't signed. A change to the
    terms after it was sent replaces it with a new version: the owner's link
    opens the corrected one."""
    _editable(agreement)
    if name is not None or email is not None or phone is not None:
        n, e, p = _contact(agreement.owner_name if name is None else name,
                           agreement.owner_email if email is None else email,
                           agreement.owner_phone if phone is None else phone)
        agreement.owner_name, agreement.owner_email, agreement.owner_phone = n, e, p
        agreement.save(update_fields=["owner_name", "owner_email", "owner_phone"])
    if terms is not None:
        cleaned = clean_terms(terms)
        version = current(agreement)
        if cleaned != version.terms:
            with transaction.atomic():
                if agreement.sent_at is None:
                    version.terms = cleaned
                    version.save(update_fields=["terms"])
                else:
                    version.replaced_at = timezone.now()
                    version.save(update_fields=["replaced_at"])
                    tpl = texts.get(agreement.template_key)
                    AgreementVersion.all_objects.create(
                        tenant_id=agreement.tenant_id, agreement=agreement,
                        revision=version.revision + 1, template_key=tpl.key,
                        template_version=tpl.version, template_sha256=tpl.sha256,
                        terms=cleaned, created_by=actor)
                    _event(agreement, "replaced", actor=actor,
                           detail=f"Corrected: version {version.revision + 1} replaces "
                                  f"version {version.revision}")
    return agreement


def cancel(agreement, actor):
    _editable(agreement)
    agreement.voided_at = timezone.now()
    agreement.link_hash = ""
    agreement.save(update_fields=["voided_at", "link_hash"])
    _event(agreement, "cancelled", actor=actor, detail="Cancelled; the link no longer opens")


def owner_link(agreement) -> str:
    from apps.intake.services import form_for

    from . import links

    return links.url_for(agreement, form_for(agreement.company))


def send_email(agreement, actor):
    """Email the owner their link (the program's sender)."""
    from . import mail

    _editable(agreement)
    if not agreement.owner_email:
        raise Refused("There's no email for this owner. Copy the link instead.")
    mail.to_owner(agreement, "invite")
    first = agreement.sent_at is None
    if first:
        agreement.sent_at = timezone.now()
        agreement.save(update_fields=["sent_at"])
    _event(agreement, "emailed", actor=actor,
           detail="Emailed the agreement" if first else "Emailed the agreement again")


def copy_link(agreement, actor) -> str:
    """Staff send the link themselves. Counts as sent."""
    _editable(agreement)
    url = owner_link(agreement)
    if agreement.sent_at is None:
        agreement.sent_at = timezone.now()
        agreement.save(update_fields=["sent_at"])
    _event(agreement, "link_copied", actor=actor, detail="Copied the link")
    return url


def status_line(agreement) -> list[dict]:
    """sent, opened, signed by owner, countersigned, form started, form
    submitted, sent to Track: each with its time, or None."""
    sub = agreement.submission
    started = None
    if sub is not None:
        if sub.status != "draft":
            started = sub.last_changed_at
    sent_to_track = sub.sent_at if sub is not None and sub.locked_at else None

    def iso(dt):
        return dt.isoformat() if dt else None

    return [
        {"key": "sent", "label": "Sent", "at": iso(agreement.sent_at)},
        {"key": "opened", "label": "Opened", "at": iso(agreement.opened_at)},
        {"key": "owner_signed", "label": "Signed by owner", "at": iso(agreement.owner_signed_at)},
        {"key": "countersigned", "label": "Countersigned", "at": iso(agreement.countersigned_at)},
        {"key": "form_started", "label": "Form started", "at": iso(started)},
        {"key": "form_submitted", "label": "Form submitted",
         "at": iso(sub.submitted_at if sub else None)},
        {"key": "sent_to_track", "label": "Sent to Track", "at": iso(sent_to_track)},
    ]


# ------------------------------------------------------------ owner: details

def _t(value, most=120) -> str:
    return " ".join(str(value or "").split())[:most]


def clean_details(data) -> dict:
    """The owner's section (page 8 of the 2014 PDF, as the brief keeps it).
    Never asked: Wi-Fi, Tax ID, Social Security number, bank details, fax."""
    d = data if isinstance(data, dict) else {}
    mailing = d.get("mailing") if isinstance(d.get("mailing"), dict) else {}
    emergency = d.get("emergency") if isinstance(d.get("emergency"), dict) else {}
    owner_type = "entity" if d.get("owner_type") == "entity" else "person"

    def count(value, half=False):
        try:
            n = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return ""
        if n < 0 or n > 30:
            return ""
        if half:
            n = (n * 2).to_integral_value() / 2
        else:
            n = n.to_integral_value()
        return format(n.normalize(), "f") if n != n.to_integral_value() else str(int(n))

    try:
        sqft = int(str(d.get("square_feet") or "").replace(",", "").strip() or 0)
    except ValueError:
        sqft = 0
    out = {
        "owner_type": owner_type,
        "first_name": _t(d.get("first_name"), 80), "last_name": _t(d.get("last_name"), 80),
        "entity_name": _t(d.get("entity_name"), 200) if owner_type == "entity" else "",
        "signer_title": _t(d.get("signer_title"), 80) if owner_type == "entity" else "",
        "phone": _t(d.get("phone"), 40), "email": _t(d.get("email"), 200).lower(),
        "business_phone": _t(d.get("business_phone"), 40),
        "mailing": {"street": _t(mailing.get("street")), "street2": _t(mailing.get("street2")),
                    "city": _t(mailing.get("city"), 80), "state": _t(mailing.get("state"), 40),
                    "zip": _t(mailing.get("zip"), 16)},
        "bedrooms": count(d.get("bedrooms")) if str(d.get("bedrooms") or "") != "" else "",
        "bathrooms": count(d.get("bathrooms"), half=True)
        if str(d.get("bathrooms") or "") != "" else "",
        "square_feet": max(0, min(sqft, 100000)) or "",
        "emergency": {"name": _t(emergency.get("name"), 120),
                      "address": _t(emergency.get("address"), 300),
                      "phone": _t(emergency.get("phone"), 40)},
    }
    if isinstance(d.get("property_address"), dict):
        out["property_address"] = _clean_address(d["property_address"])
    return out


def missing_details(agreement) -> list[str]:
    d = agreement.details or {}
    out = []
    if not d.get("first_name") or not d.get("last_name"):
        out.append("your first and last name" if d.get("owner_type") != "entity"
                   else "the signer's first and last name")
    if d.get("owner_type") == "entity" and (not d.get("entity_name") or
                                            not d.get("signer_title")):
        out.append("the owner of record and the signer's title")
    if not d.get("phone"):
        out.append("a phone number")
    if not _EMAIL.match(d.get("email") or ""):
        out.append("your email address")
    m = d.get("mailing") or {}
    if not (m.get("street") and m.get("city") and m.get("state") and m.get("zip")):
        out.append("your mailing address")
    if d.get("bedrooms") in (None, "") or d.get("bathrooms") in (None, ""):
        out.append("the number of bedrooms and bathrooms")
    e = d.get("emergency") or {}
    if not (e.get("name") and e.get("phone")):
        out.append("an emergency contact's name and phone")
    address = d.get("property_address") or (current(agreement).terms or {}).get(
        "property_address") or {}
    if not (address.get("street") and address.get("city")):
        out.append("the property's address")
    return out


def opened(agreement, *, ip=None, user_agent=""):
    now = timezone.now()
    fields = ["last_activity_at"]
    agreement.last_activity_at = now
    if agreement.opened_at is None:
        agreement.opened_at = now
        fields.append("opened_at")
        _event(agreement, "opened", detail="The owner opened the agreement", ip=ip,
               user_agent=user_agent)
    agreement.save(update_fields=fields)


def save_details(agreement, data):
    if agreement.owner_signed_at is not None:
        raise Refused("You've signed this agreement already. Thank you!", 409)
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    agreement.details = clean_details({**(agreement.details or {}), **(data or {})})
    agreement.last_activity_at = timezone.now()
    agreement.save(update_fields=["details", "last_activity_at"])
    return agreement


def terms_for(agreement) -> dict:
    """The current version's terms, with the address the owner confirmed."""
    terms = dict(current(agreement).terms or {})
    corrected = (agreement.details or {}).get("property_address")
    if corrected and any(corrected.values()):
        terms["property_address"] = corrected
    return terms


def address_changed(agreement) -> bool:
    staff = (current(agreement).terms or {}).get("property_address") or {}
    owner = (agreement.details or {}).get("property_address") or {}
    if not any(owner.values()):
        return False
    return render.one_line(staff) != render.one_line(owner)


# ------------------------------------------------------------ signatures

def drawn_png(data_url: str) -> bytes:
    import base64
    import binascii
    import io

    from PIL import Image

    prefix = "data:image/png;base64,"
    if not (data_url or "").startswith(prefix):
        raise Refused("Draw your signature, or type it instead.")
    try:
        content = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise Refused("That drawing could not be read. Try again.") from None
    if len(content) > MAX_DRAWN_BYTES:
        raise Refused("That drawing is too large. Clear it and draw it again.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            if image.format != "PNG":
                raise Refused("That drawing could not be read. Try again.")
    except Refused:
        raise
    except Exception:
        raise Refused("That drawing could not be read. Try again.") from None
    return content


def _mark(method, typed, drawn):
    if method == "typed":
        typed = " ".join((typed or "").split())[:200]
        if not typed:
            raise Refused("Type your name to sign.")
        return "typed", typed, None
    if method == "drawn":
        return "drawn", "", drawn_png(drawn)
    raise Refused("Type or draw your signature.")


def owner_sign(agreement, *, method, typed="", drawn="", agreed=False, ip=None,
               user_agent=""):
    """The owner signs. Then: their copy marked as awaiting SkyRun's signature,
    the countersign request, the team told, and their intake made."""
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    if agreement.owner_signed_at is not None:
        raise Refused("You've signed this agreement already. Thank you!", 409)
    missing = missing_details(agreement)
    if missing:
        raise Refused("Before you sign, please add " + ", ".join(missing) + ".")
    if agreed is not True:
        raise Refused("Tick the box to agree to sign electronically.")
    method, typed, png = _mark(method, typed, drawn)
    details = agreement.details or {}
    version = current(agreement)
    terms = terms_for(agreement)
    company = agreement.company
    with transaction.atomic():
        locked = OwnerAgreement.all_objects.select_for_update().get(pk=agreement.pk)
        if locked.owner_signed_at is not None:
            raise Refused("You've signed this agreement already. Thank you!", 409)
        now = timezone.now()
        name = " ".join(x for x in (details.get("first_name"), details.get("last_name")) if x)
        AgreementSignature.all_objects.create(
            tenant_id=agreement.tenant_id, agreement=agreement, version=version,
            role=AgreementSignature.Role.OWNER, printed_name=name,
            printed_title=details.get("signer_title", "") if details.get("owner_type") ==
            "entity" else "", method=method, typed_text=typed, drawn_png=png,
            consent_version=consent.CURRENT,
            consent_text=consent.owner(company=_brand(company), email=details.get("email", "")),
            signed_at=now, ip_address=ip or None, user_agent=(user_agent or "")[:500],
            text_sha256=render.signed_sha256(agreement.template_key, terms, details))
        agreement.owner_signed_at = now
        agreement.last_activity_at = now
        agreement.save(update_fields=["owner_signed_at", "last_activity_at"])
        _event(agreement, "owner_signed", detail=f"Signed by the owner, {name}", ip=ip,
               user_agent=user_agent)
    _after_owner_signed(agreement)
    return agreement


def _quietly(what, fn, *args, **kwargs):
    """A follow-on step: if it fails it is logged and recorded, and the
    signature it follows stands."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("owner agreement: %s failed", what)
        return exc


def _after_owner_signed(agreement):
    from . import mail, pdf

    with tenant_context(agreement.tenant_id):
        _quietly("the intake", to_intake, agreement)
        result = _quietly("the owner's PDF", pdf.store_owner_copy, agreement)
        agreement.refresh_from_db()
        if agreement.owner_pdf_id and agreement.details.get("email"):
            _quietly("the owner's copy", mail.to_owner, agreement, "owner_copy")
        _quietly("the countersign request", mail.countersign_request, agreement)
        _quietly("the team notice", mail.signed_notice, agreement)
        if isinstance(result, Exception):
            _event(agreement, "pdf_failed", detail=f"The owner's PDF wasn't made: {result}"[:300])


def choose(agreement, choice: str) -> str:
    """"Complete onboarding now" (the intake link, at once) or "Later" (the
    link by email). Either way the intake already exists."""
    from apps.intake import links as intake_links

    from . import mail

    if agreement.owner_signed_at is None:
        raise Refused("Sign the agreement first.", 409)
    if choice not in ("now", "later"):
        raise Refused("Choose now or later.")
    if agreement.submission is None:
        to_intake(agreement)
        agreement.refresh_from_db()
    if not agreement.onboarding_choice:
        agreement.onboarding_choice = choice
        agreement.save(update_fields=["onboarding_choice"])
        _event(agreement, f"chose_{choice}",
               detail="Chose to complete onboarding now" if choice == "now"
               else "Chose to complete onboarding later; the link was emailed")
        if choice == "later":
            mail.to_owner(agreement, "intake_link")
    return intake_links.url_for(agreement.submission)


# ------------------------------------------------------------ the intake

def _split_name(details):
    return details.get("first_name", ""), details.get("last_name", "")


def intake_answers(agreement) -> dict:
    """Everything the agreement knows, as the intake's answers: names, phone,
    email, mailing address, the property's address, bedrooms and bathrooms as
    that many empty rooms, square footage, the emergency contact."""
    d = agreement.details or {}
    terms = terms_for(agreement)
    address = terms.get("property_address") or {}
    mailing = d.get("mailing") or {}
    first, last = _split_name(d)

    def rooms(value):
        try:
            return max(0, min(30, math.ceil(Decimal(str(value or 0)))))
        except (InvalidOperation, ValueError):
            return 0

    about = {"first_name": first, "last_name": last, "email": d.get("email", ""),
             "mobile": d.get("phone", ""),
             "account_name": d.get("entity_name", "") if d.get("owner_type") == "entity" else "",
             "street": mailing.get("street", ""), "street2": mailing.get("street2", ""),
             "city": mailing.get("city", ""), "state": mailing.get("state", ""),
             "postal": mailing.get("zip", ""), "country": "US",
             "emergency": dict(d.get("emergency") or {})}
    prop = {"street": address.get("street", ""), "street2": address.get("unit", ""),
            "city": address.get("city", ""), "state": address.get("state", ""),
            "postal": address.get("zip", ""), "square_feet": d.get("square_feet") or None}
    return {"about": about, "property": prop,
            "bedrooms": [{"beds": [], "own_bath": False} for _ in range(rooms(d.get("bedrooms")))],
            "bathrooms": [{"fixtures": {}} for _ in range(rooms(d.get("bathrooms")))]}


def to_intake(agreement):
    """The owner's intake, prefilled. Made once."""
    from apps.intake import services as intake

    if agreement.submission_id:
        return agreement.submission
    form = intake.form_for(agreement.company)
    d = agreement.details or {}
    first, last = _split_name(d)
    sub = intake.start(form, first_name=first or agreement.owner_name,
                       last_name=last, email=d.get("email") or agreement.owner_email,
                       actor=None, answers=intake_answers(agreement),
                       detail=f"Started from owner agreement #{agreement.number}")
    staff = dict(sub.staff or {})
    contract = contract_for(agreement)
    if contract.get("contract_id"):
        staff["contract_id"] = contract["contract_id"]
    sub.staff = staff
    sub.save(update_fields=["staff"])
    agreement.submission = sub
    agreement.save(update_fields=["submission"])
    _event(agreement, "intake_made", detail=f"Owner intake #{sub.number} made, prefilled")
    return sub


def contract_for(agreement) -> dict:
    """The Track contract for the split, by its code (the manager's percent,
    without the point: 30 is Standard 30, 23.35 is "2335"). One match is
    preselected; none or several are flagged for staff."""
    from apps.intake import tracklists

    manager = str((current(agreement).terms or {}).get("manager_percent", "30"))
    code = manager.replace(".", "")
    lists, _ = tracklists.stored(agreement.company)
    matches = [c for c in lists.get("contracts") or []
               if str(c.get("code", "")).strip() == code and c.get("isActive", True) is not False]
    if len(matches) == 1:
        return {"contract_id": matches[0]["id"], "name": matches[0].get("name", ""),
                "flag": ""}
    if not matches:
        return {"contract_id": None, "name": "",
                "flag": f"No Track contract matches a {manager}% manager split (code {code}). "
                        "Create it in Track, refresh Track's lists, then pick it here."}
    names = ", ".join(c.get("name", "") for c in matches)
    return {"contract_id": None, "name": "",
            "flag": f"Track has {len(matches)} contracts with code {code} ({names}). Pick one."}


# ------------------------------------------------------------ the authorization

def record_authority(company, user, *, method, typed="", drawn="", people=(), agreed=False,
                     ip=None, user_agent=""):
    """The signer, signed in as themselves, adopts their signature and names
    who may apply it to new-owner agreements. A new row each time."""
    if not access.is_signer(user, company):
        raise Refused("Only the company's signer can record this.", 403)
    if agreed is not True:
        raise Refused("Tick the box to record the authorization.")
    method, typed, png = _mark(method, typed, drawn)
    allowed = {str(m.user_id): (m.user.full_name or m.user.email)
               for m, _ in access.company_users(company)}
    chosen = [str(p) for p in dict.fromkeys(people or []) if str(p) in allowed]
    tpl = texts.get(texts.DEFAULT)
    now = timezone.now()
    with transaction.atomic():
        CountersignAuthority.all_objects.filter(company=company, ended_at__isnull=True).update(
            ended_at=now, ended_ip=ip or None, ended_user_agent=(user_agent or "")[:500])
        row = CountersignAuthority.all_objects.create(
            tenant_id=company.tenant_id, company=company, principal=user,
            principal_name=tpl.signer_name or user.full_name, principal_title=tpl.signer_title,
            method=method, typed_text=typed, drawn_png=png,
            people=[{"user_id": u, "name": allowed[u]} for u in chosen],
            wording_version=consent.CURRENT,
            wording=consent.authorization(company=_brand(company),
                                          principal=tpl.signer_name or user.full_name,
                                          title=tpl.signer_title),
            recorded_at=now, ip_address=ip or None, user_agent=(user_agent or "")[:500])
    _audit(company, user, "agreements.authority_recorded",
           {"people": [p["name"] for p in row.people]})
    return row


def withdraw_authority(company, user, *, ip=None, user_agent=""):
    if not access.is_signer(user, company):
        raise Refused("Only the company's signer can withdraw this.", 403)
    row = access.authority_in_force(company)
    if row is None:
        raise Refused("There's no authorization to withdraw.", 409)
    row.ended_at, row.withdrawn = timezone.now(), True
    row.ended_ip, row.ended_user_agent = ip or None, (user_agent or "")[:500]
    row.save(update_fields=["ended_at", "withdrawn", "ended_ip", "ended_user_agent"])
    _audit(company, user, "agreements.authority_withdrawn", {})
    return row


def _audit(company, user, action, data):
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=user, verb=action,
                                  target_type="company", target_id=company.pk, payload=data)


# ------------------------------------------------------------ countersigning

def countersign(agreement, user, *, agreed=False, method="", typed="", drawn="", ip=None,
                user_agent=""):
    """SkyRun's signature. The signer signs as themselves (their adopted
    signature, or one made now). Anyone else on the authorization applies the
    signer's adopted signature, and the record says they did, under which
    authorization: never as if the signer pressed the button."""
    company = agreement.company
    if agreement.owner_signed_at is None:
        raise Refused("The owner hasn't signed yet.", 409)
    if agreement.countersigned_at is not None:
        raise Refused("This agreement is countersigned already.", 409)
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    may, authority = access.may_countersign(user, company)
    if not may:
        raise Refused("You aren't authorized to countersign for this company.", 403)
    if agreed is not True:
        raise Refused("Tick the box to countersign.")
    tpl = texts.get(agreement.template_key)
    signer_self = access.is_signer(user, company)
    if signer_self and method:
        mark = _mark(method, typed, drawn)
    elif authority is not None:
        mark = (authority.method, authority.typed_text,
                bytes(authority.drawn_png) if authority.drawn_png else None)
    elif signer_self:
        raise Refused("Type or draw your signature.")
    else:
        raise Refused("There's no authorization in force.", 403)
    owner_sig = AgreementSignature.all_objects.get(agreement=agreement,
                                                    role=AgreementSignature.Role.OWNER)
    terms = terms_for(agreement)
    if render.signed_sha256(agreement.template_key, terms, agreement.details or {}) \
            != owner_sig.text_sha256:
        raise Refused("The agreement's words don't match what the owner signed. Nothing was "
                      "countersigned; tell the practice owner.", 409)
    now = timezone.now()
    day = practice_today(company)
    applied_by_name = (user.full_name or "").strip() or "a SkyRun team member"
    with transaction.atomic():
        locked = OwnerAgreement.all_objects.select_for_update().get(pk=agreement.pk)
        if locked.countersigned_at is not None:
            raise Refused("This agreement is countersigned already.", 409)
        words = (consent.signer(company=_brand(company)) if signer_self else
                 consent.apply(company=_brand(company), principal=tpl.signer_name,
                               authorized_on=_day(authority.recorded_at, company)))
        AgreementSignature.all_objects.create(
            tenant_id=agreement.tenant_id, agreement=agreement, version=owner_sig.version,
            role=AgreementSignature.Role.MANAGER, printed_name=tpl.signer_name,
            printed_title=tpl.signer_title, method=mark[0], typed_text=mark[1] or "",
            drawn_png=mark[2], consent_version=consent.CURRENT, consent_text=words,
            signed_at=now, ip_address=ip or None, user_agent=(user_agent or "")[:500],
            text_sha256=owner_sig.text_sha256, applied_by=user,
            applied_by_name=applied_by_name,
            authority=None if signer_self else authority)
        agreement.countersigned_at, agreement.agreement_date = now, day
        agreement.save(update_fields=["countersigned_at", "agreement_date"])
        _event(agreement, "countersigned", actor=user, ip=ip, user_agent=user_agent,
               detail=(f"Countersigned by {tpl.signer_name}" if signer_self else
                       f"{tpl.signer_name}'s signature applied by {applied_by_name}, under the "
                       f"authorization of {_day(authority.recorded_at, company)}"))
    _after_countersigned(agreement)
    return agreement


def _day(dt, company) -> str:
    local = dt.astimezone(ZoneInfo(getattr(company.tenant, "timezone", "") or "UTC"))
    return f"{local:%B} {local.day}, {local.year}"


def _after_countersigned(agreement):
    from . import mail, pdf

    with tenant_context(agreement.tenant_id):
        result = _quietly("the final PDF", pdf.store_final, agreement)
        agreement.refresh_from_db()
        _quietly("the intake's dates", _preset_intake, agreement)
        if agreement.final_pdf_id:
            _quietly("the owner's final copy", mail.to_owner, agreement, "final_copy")
            _quietly("the signed PDF to staff", mail.final_notice, agreement)
        if isinstance(result, Exception):
            _event(agreement, "pdf_failed", detail=f"The final PDF wasn't made: {result}"[:300])


def _preset_intake(agreement):
    """The Contract Effective Date is the countersigning date; the contract
    is preselected from the split when one matches."""
    sub = agreement.submission or to_intake(agreement)
    if sub.locked_at:
        return
    staff = dict(sub.staff or {})
    staff["contract_effective_date"] = agreement.agreement_date.isoformat()
    contract = contract_for(agreement)
    if contract.get("contract_id") and not staff.get("contract_id"):
        staff["contract_id"] = contract["contract_id"]
    sub.staff = staff
    sub.save(update_fields=["staff"])


def _brand(company) -> str:
    from apps.intake.services import form_for

    form = form_for(company, create=False)
    return form.brand_name if form else company.name


# ------------------------------------------------------------ reminders

OWNER_DAYS = (3, 7)
FORM_DAYS = (3, 7)
COUNTERSIGN_HOURS = ((1, 24), (3, 72))


def _days_since(when, company) -> int:
    tz = ZoneInfo(getattr(company.tenant, "timezone", "") or "UTC")
    return (practice_now(company).date() - when.astimezone(tz).date()).days


def tick(tenant_id=None):
    """Hourly. Owner reminders at 9:00 on days 3 and 7 for an unsigned
    agreement and for an unfinished form; countersign reminders 24 and 72
    hours after the owner signed, sent between 8:00 and 18:00."""
    from . import mail

    programs = Program.all_objects.filter(enabled=True).select_related("company__tenant")
    if tenant_id is not None:
        programs = programs.filter(tenant_id=tenant_id)
    for program in programs:
        company = program.company
        if company.deleted_at is not None:
            continue
        with tenant_context(company.tenant_id):
            local = practice_now(company)
            rows = OwnerAgreement.all_objects.filter(company=company, voided_at__isnull=True)
            for a in rows.filter(owner_signed_at__isnull=True, sent_at__isnull=False) \
                    .exclude(owner_email=""):
                done = set((a.reminders or {}).get("owner", []))
                due = [d for d in OWNER_DAYS if d not in done and
                       _days_since(a.sent_at, company) >= d]
                if due and local.hour >= 9:
                    _quietly("an owner reminder", mail.to_owner, a, "reminder")
                    _remember(a, "owner", due)
            for a in rows.filter(owner_signed_at__isnull=False, countersigned_at__isnull=True):
                done = set((a.reminders or {}).get("countersign", []))
                hours = (timezone.now() - a.owner_signed_at).total_seconds() / 3600
                due = [n for n, h in COUNTERSIGN_HOURS if n not in done and hours >= h]
                if due and 8 <= local.hour < 18:
                    _quietly("a countersign reminder", mail.countersign_request, a, reminder=True)
                    _remember(a, "countersign", due)
            for a in rows.filter(submission__isnull=False).select_related("submission"):
                sub = a.submission
                if sub.submitted_at is not None or sub.discarded_at is not None \
                        or sub.status not in ("draft", "in_progress"):
                    continue
                if not ((a.details or {}).get("email") or a.owner_email):
                    continue
                done = set((a.reminders or {}).get("form", []))
                due = [d for d in FORM_DAYS if d not in done and
                       _days_since(sub.created_at, company) >= d]
                if due and local.hour >= 9:
                    _quietly("a form reminder", mail.to_owner, a, "intake_reminder")
                    _remember(a, "form", due)


def _remember(agreement, key, days):
    reminders = dict(agreement.reminders or {})
    reminders[key] = sorted(set(reminders.get(key, [])) | set(days))
    agreement.reminders = reminders
    agreement.save(update_fields=["reminders"])
    _event(agreement, "reminded", detail={"owner": "Reminded the owner to sign",
                                          "countersign": "Reminded the countersigners",
                                          "form": "Reminded the owner to finish the form"}[key])
