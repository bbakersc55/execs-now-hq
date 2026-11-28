"""Owner agreements: the staff side, the owner's side, the countersignature,
and the hand-off to the owner's intake (docs/p15_owner_agreements.md).

Nothing here writes to Track. The intake an agreement starts goes to Track
the usual way, after the agreement is countersigned.
"""

from __future__ import annotations

import hashlib
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

from . import access, consent, exhibit_a, render, texts
from .texts import rental_management_changes as changes
from .models import (
    AgreementEvent, AgreementSignature, AgreementVersion, CoOwner, CountersignAuthority,
    OwnerAgreement, Program,
)

log = logging.getLogger(__name__)

PERIOD_KEYS = ("winter", "summer", "fall")
MOST_ITEMS = 4000
MAX_DRAWN_BYTES = 300 * 1024
#: Owners 2 to 4 (owner, 2026-11-24).
MOST_CO_OWNERS = 3
MOST_SLEEPS = 40
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Refused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def not_while_acting():
    """Owner, 2026-11-24: while someone acts as another person, nothing that
    signs, authorizes or changes anything here goes through. Viewing does."""
    from apps.tenancy.context import acting_refusal

    if (message := acting_refusal()):
        raise Refused(message, 403)


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


def clean_co_owners(rows) -> list[dict]:
    """Owners 2 to 4 as staff entered them: a name and an email each, a title
    if they want one. Two owners may share an email (couples often do)."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("name") or "").split())[:200]
        email = str(row.get("email") or "").strip().lower()[:200]
        title = " ".join(str(row.get("title") or "").split())[:80]
        if not (name or email or title):
            continue
        if not name:
            raise Refused("Enter each owner's name.")
        if not email:
            raise Refused(f"Enter {name}'s email: each owner signs on their own link, sent "
                          "by email.")
        if not _EMAIL.match(email):
            raise Refused(f"{name}'s email doesn't look right.")
        out.append({"name": name, "email": email, "title": title})
    if len(out) > MOST_CO_OWNERS:
        raise Refused("An agreement can have up to four owners.")
    return out


def co_owners(agreement) -> list:
    return list(CoOwner.all_objects.filter(agreement=agreement).order_by("position"))


def _set_co_owners(agreement, rows):
    CoOwner.all_objects.filter(agreement=agreement).delete()
    for i, row in enumerate(rows, start=2):
        CoOwner.all_objects.create(tenant_id=agreement.tenant_id, agreement=agreement,
                                   position=i, **row)


def first_owner(agreement) -> dict:
    """The first owner as the agreement prints them: their name as they gave
    it on their page (the signer's, for a company or trust), with the title."""
    d = agreement.details or {}
    name = " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x).strip() \
        or agreement.owner_name
    title = d.get("signer_title", "") if d.get("owner_type") == "entity" else ""
    return {"position": 1, "name": name, "title": title,
            "email": (d.get("email") or agreement.owner_email or "").strip().lower(),
            "signed_at": agreement.owner_signed_at}


def owners(agreement) -> list[dict]:
    """Everyone who signs, in the order they sign: {position, name, title,
    email, signed_at}."""
    return [first_owner(agreement)] + [
        {"position": c.position, "name": c.name, "title": c.title, "email": c.email,
         "signed_at": c.signed_at} for c in co_owners(agreement)]


def signing_owners(agreement) -> list[dict]:
    return [{"name": o["name"], "title": o["title"]} for o in owners(agreement)]


def shared_email(agreement_or_rows) -> bool:
    rows = (owners(agreement_or_rows) if isinstance(agreement_or_rows, OwnerAgreement)
            else agreement_or_rows)
    emails = [o["email"] for o in rows if o.get("email")]
    return len(emails) != len(set(emails))


def turn(agreement) -> int | None:
    """Which owner signs next (1 to 4), or None: everyone has, or it is
    cancelled or countersigned."""
    if agreement.voided_at is not None or agreement.countersigned_at is not None:
        return None
    if agreement.owner_signed_at is None:
        return 1
    for c in co_owners(agreement):
        if c.signed_at is None:
            return c.position
    return None


def owner_at(agreement, position: int) -> dict:
    for o in owners(agreement):
        if o["position"] == position:
            return o
    raise Refused("There's no such owner on this agreement.", 404)


def words(agreement) -> str:
    """The words every owner signs, as they read now."""
    return render.signed_text(agreement.template_key, terms_for(agreement),
                              agreement.details or {}, signing_owners(agreement))


def current(agreement) -> AgreementVersion:
    return (AgreementVersion.all_objects.filter(agreement=agreement, replaced_at__isnull=True)
            .order_by("-revision").first())


def create(company, *, name, email="", phone="", terms=None, actor=None, co_owners=None,
           details=None, template_key=texts.DEFAULT, started_from=None) -> OwnerAgreement:
    from apps.crm.models import Company
    not_while_acting()

    if not access.is_on(company):
        raise Refused("Owner agreements aren't on for this company.", 404)
    name, email, phone = _contact(name, email, phone)
    cleaned = clean_terms(terms or {})
    others = clean_co_owners(co_owners)
    tpl = texts.get(template_key)
    with transaction.atomic():
        Company.all_objects.select_for_update().filter(pk=company.pk).first()
        number = (OwnerAgreement.all_objects.filter(company=company)
                  .aggregate(n=Max("number"))["n"] or 0) + 1
        first, _, last = name.partition(" ")
        agreement = OwnerAgreement.all_objects.create(
            tenant_id=company.tenant_id, company=company, number=number,
            template_key=tpl.key, owner_name=name, owner_email=email, owner_phone=phone,
            created_by=actor, started_from=started_from,
            # The owner's section starts with what staff entered; they can change it.
            details=clean_details(details if details is not None else
                                  {"first_name": first, "last_name": last, "email": email,
                                   "phone": phone}))
        AgreementVersion.all_objects.create(
            tenant_id=company.tenant_id, agreement=agreement, revision=1, template_key=tpl.key,
            template_version=tpl.version, template_sha256=tpl.sha256, terms=cleaned,
            created_by=actor)
        _set_co_owners(agreement, others)
    _event(agreement, "created", actor=actor, detail=f"Agreement #{number} created" + (
        f", {1 + len(others)} owners signing in order" if others else ""))
    return agreement


def _editable(agreement):
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    if agreement.owner_signed_at is not None:
        raise Refused("The owner has signed this agreement, so it can't be corrected. Cancel "
                      "it, then start a new agreement from it.", 409)


def update(agreement, *, name=None, email=None, phone=None, terms=None, actor=None,
           co_owners=None):
    """Staff correct an agreement the first owner hasn't signed, the owners
    included (owner, 2026-11-24). A change to the terms after it was sent
    replaces it with a new version: the owner's link opens the corrected one.
    After the first owner signs, nothing changes: cancel and start again."""
    not_while_acting()
    _editable(agreement)
    if co_owners is not None:
        rows = clean_co_owners(co_owners)
        before = [{"name": c.name, "email": c.email, "title": c.title}
                  for c in CoOwner.all_objects.filter(agreement=agreement).order_by("position")]
        if rows != before:
            with transaction.atomic():
                _set_co_owners(agreement, rows)
            _event(agreement, "owners_corrected", actor=actor,
                   detail="Owners corrected: " + (", ".join(
                       [agreement.owner_name] + [r["name"] for r in rows])) + (
                       ". Email it again so the first owner has the corrected agreement."
                       if agreement.sent_at else ""))
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


MOST_REASON = 300


def cancel(agreement, actor, reason=""):
    """Owner, 2026-11-24: any time until SkyRun has signed, with a reason.
    Every owner who already signed is told it was withdrawn; nobody else."""
    from . import mail

    not_while_acting()
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled already.", 409)
    if agreement.countersigned_at is not None:
        raise Refused("SkyRun has signed this agreement. A signed agreement can't be cancelled "
                      "or corrected.", 409)
    reason = " ".join(str(reason or "").split())[:MOST_REASON]
    if not reason:
        raise Refused("Give the reason for cancelling.")
    signed = [o["position"] for o in owners(agreement) if o["signed_at"]]
    with transaction.atomic():
        agreement.voided_at = timezone.now()
        agreement.cancel_reason = reason
        agreement.link_hash = ""
        agreement.save(update_fields=["voided_at", "cancel_reason", "link_hash"])
        CoOwner.all_objects.filter(agreement=agreement).update(link_hash="")
        _event(agreement, "cancelled", actor=actor,
               detail=f"Cancelled: {reason}. The owners' links no longer open")
    _audit(agreement.company, actor, "agreements.cancelled",
           {"agreement_id": str(agreement.pk), "number": agreement.number, "reason": reason,
            "owners_signed": len(signed)})
    if signed:
        with tenant_context(agreement.tenant_id):
            _quietly("the withdrawn emails", mail.to_owners, agreement, "withdrawn", signed)


def restart(agreement, actor):
    """"Start a new agreement from this one" (owner, 2026-11-24): a new draft
    with the same terms, owners and owner's answers, and the owner's intake
    moved to it with its answers. The intake is the same row: its encrypted
    values stay where they are, never copied or decrypted."""
    from apps.intake import services as intake
    from apps.intake.models import SubmissionEvent

    not_while_acting()
    if agreement.voided_at is None:
        raise Refused("Only a cancelled agreement can be started again.", 409)
    if OwnerAgreement.all_objects.filter(started_from=agreement).exists():
        raise Refused("A new agreement was already started from this one.", 409)
    terms = dict(terms_for(agreement))
    rows = [{"name": c.name, "email": c.email, "title": c.title} for c in co_owners(agreement)]
    with transaction.atomic():
        sub = agreement.submission
        new = create(agreement.company, name=agreement.owner_name, email=agreement.owner_email,
                     phone=agreement.owner_phone, terms=terms, actor=actor, co_owners=rows,
                     details=dict(agreement.details or {}), template_key=agreement.template_key,
                     started_from=agreement)
        if sub is not None:
            agreement.submission = None
            agreement.save(update_fields=["submission"])
            new.submission = sub
            new.save(update_fields=["submission"])
            intake._event(sub, SubmissionEvent.Kind.STARTED, actor,
                          f"Carried over to owner agreement #{new.number}, started from "
                          f"cancelled #{agreement.number}")
    _event(agreement, "restarted", actor=actor,
           detail=f"Agreement #{new.number} started from this one" +
                  (f"; intake #{sub.number} moved to it" if sub else ""))
    _event(new, "restarted", actor=actor,
           detail=f"Started from cancelled #{agreement.number}" +
                  (f"; its intake #{sub.number} moved here with its answers" if sub else ""))
    return new


def owner_link(agreement, position: int = 1) -> str:
    from apps.intake.services import form_for

    from . import links

    co = None
    if position != 1:
        co = CoOwner.all_objects.get(agreement=agreement, position=position)
    return links.url_for(agreement, form_for(agreement.company), co)


def _whose(agreement, position) -> str:
    n = 1 + len(co_owners(agreement))
    name = owner_at(agreement, position)["name"]
    return f"{name} (owner {position} of {n})" if n > 1 else name


def _sendable(agreement) -> int:
    """Whose turn it is, for Email it again and Copy the link."""
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    position = turn(agreement)
    if position is None:
        raise Refused("Every owner has signed this agreement.", 409)
    return position


def send_email(agreement, actor):
    """Email whoever's turn it is their own link (the program's sender)."""
    from . import mail
    not_while_acting()

    position = _sendable(agreement)
    if position == 1 and not agreement.owner_email:
        raise Refused("There's no email for this owner. Copy the link instead.")
    mail.to_owner(agreement, "invite", position=position)
    first = agreement.sent_at is None
    if first:
        agreement.sent_at = timezone.now()
        agreement.save(update_fields=["sent_at"])
    who = "" if position == 1 and not co_owners(agreement) else \
        f" to {_whose(agreement, position)}"
    _event(agreement, "emailed", actor=actor,
           detail=("Emailed the agreement" if first else "Emailed the agreement again") + who)


def copy_link(agreement, actor) -> str:
    """Staff send the link themselves, to whoever's turn it is. The first
    owner's counts as sent."""
    not_while_acting()
    position = _sendable(agreement)
    url = owner_link(agreement, position)
    if agreement.sent_at is None:
        agreement.sent_at = timezone.now()
        agreement.save(update_fields=["sent_at"])
    who = "" if position == 1 and not co_owners(agreement) else \
        f" for {_whose(agreement, position)}"
    _event(agreement, "link_copied", actor=actor, detail="Copied the link" + who)
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

    everyone = owners(agreement)
    if len(everyone) > 1:
        done = sum(1 for o in everyone if o["signed_at"])
        signed = {"key": "owner_signed", "label": f"Signed by owners ({done} of {len(everyone)})",
                  "at": iso(agreement.all_signed_at)}
    else:
        signed = {"key": "owner_signed", "label": "Signed by owner",
                  "at": iso(agreement.all_signed_at or agreement.owner_signed_at)}
    return [
        {"key": "sent", "label": "Sent", "at": iso(agreement.sent_at)},
        {"key": "opened", "label": "Opened", "at": iso(agreement.opened_at)},
        signed,
        {"key": "countersigned", "label": "Countersigned", "at": iso(agreement.countersigned_at)},
        {"key": "form_started", "label": "Form started", "at": iso(started)},
        {"key": "form_submitted", "label": "Form submitted",
         "at": iso(sub.submitted_at if sub else None)},
        {"key": "sent_to_track", "label": "Sent to Track", "at": iso(sent_to_track)},
    ]


def turn_text(agreement) -> str:
    """Whose turn it is, for the status line (owner, 2026-11-24)."""
    if agreement.voided_at is not None or agreement.countersigned_at is not None:
        return ""
    if agreement.sent_at is None:
        return "Not sent yet"
    position = turn(agreement)
    if position is not None:
        return f"Waiting for {_whose(agreement, position)} to sign"
    return "Waiting for SkyRun's signature"


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
        "sleeps": _sleeps(d.get("sleeps")),
        "emergency": {"name": _t(emergency.get("name"), 120),
                      "address": _t(emergency.get("address"), 300),
                      "phone": _t(emergency.get("phone"), 40)},
    }
    if isinstance(d.get("property_address"), dict):
        out["property_address"] = _clean_address(d["property_address"])
    return out


def _sleeps(value):
    try:
        n = int(str(value or "").strip())
    except ValueError:
        return ""
    return n if 1 <= n <= MOST_SLEEPS else ""


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
    if d.get("sleeps") in (None, ""):
        out.append("how many guests the property sleeps")
    e = d.get("emergency") or {}
    # "If only one owner" (owner, 2026-11-24): with more, it is optional.
    if not co_owners(agreement) and not (e.get("name") and e.get("phone")):
        out.append("an emergency contact's name and phone")
    address = d.get("property_address") or (current(agreement).terms or {}).get(
        "property_address") or {}
    if not (address.get("street") and address.get("city")):
        out.append("the property's address")
    return out


def opened(agreement, *, ip=None, user_agent="", position=1):
    now = timezone.now()
    fields = ["last_activity_at"]
    agreement.last_activity_at = now
    if position != 1:
        co = CoOwner.all_objects.filter(agreement=agreement, position=position).first()
        if co is not None and co.opened_at is None and co.turn_started_at is not None:
            co.opened_at = now
            co.save(update_fields=["opened_at"])
            _event(agreement, "opened", detail=f"{co.name} opened the agreement", ip=ip,
                   user_agent=user_agent)
        agreement.save(update_fields=fields)
        return
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

    from apps.esign.drawing import is_png

    prefix = "data:image/png;base64,"
    if not (data_url or "").startswith(prefix):
        raise Refused("Draw your signature, or type it instead.")
    try:
        content = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise Refused("That drawing could not be read. Try again.") from None
    if len(content) > MAX_DRAWN_BYTES:
        raise Refused("That drawing is too large. Clear it and draw it again.")
    # A PNG by its own first bytes, opened by Pillow's PNG reader alone
    # (apps/esign/drawing.py).
    if not is_png(content):
        raise Refused("That drawing could not be read. Try again.")
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


class WordsChanged(Refused):
    """The words no longer match what an owner signed."""


def owner_sign(agreement, *, method, typed="", drawn="", agreed=False, ip=None,
               user_agent="", position=1):
    """An owner signs, in their turn. The first owner's page is fixed from
    then on; every later owner signs exactly the words the first signed
    (owner, 2026-11-24). When the last owner has signed: their copy marked as
    awaiting SkyRun's signature, the countersign request, the team told."""
    if agreement.voided_at is not None:
        raise Refused("This agreement was cancelled.", 409)
    if position == 1:
        return _first_signs(agreement, method=method, typed=typed, drawn=drawn,
                            agreed=agreed, ip=ip, user_agent=user_agent)
    return _co_owner_signs(agreement, position, method=method, typed=typed, drawn=drawn,
                           agreed=agreed, ip=ip, user_agent=user_agent)


def _signature(agreement, *, version, position, name, title, email, mark, text, ip,
               user_agent, now):
    method, typed, png = mark
    AgreementSignature.all_objects.create(
        tenant_id=agreement.tenant_id, agreement=agreement, version=version,
        role=AgreementSignature.Role.OWNER, position=position, printed_name=name,
        printed_title=title, method=method, typed_text=typed, drawn_png=png,
        consent_version=consent.CURRENT,
        consent_text=consent.owner(company=_brand(agreement.company), email=email),
        signed_at=now, ip_address=ip or None, user_agent=(user_agent or "")[:500],
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), signed_text=text,
        exhibit_a=exhibit_a.numbers((agreement.details or {}).get("sleeps")) or {})


def _first_signs(agreement, *, method, typed, drawn, agreed, ip, user_agent):
    if agreement.owner_signed_at is not None:
        raise Refused("You've signed this agreement already. Thank you!", 409)
    missing = missing_details(agreement)
    if missing:
        raise Refused("Before you sign, please add " + ", ".join(missing) + ".")
    if agreed is not True:
        raise Refused("Tick the box to agree to sign electronically.")
    mark = _mark(method, typed, drawn)
    version = current(agreement)
    # The words as the owner signed them, kept exactly (owner, 2026-11-24).
    text = words(agreement)
    alone = not co_owners(agreement)
    with transaction.atomic():
        locked = OwnerAgreement.all_objects.select_for_update().get(pk=agreement.pk)
        if locked.owner_signed_at is not None:
            raise Refused("You've signed this agreement already. Thank you!", 409)
        now = timezone.now()
        me = first_owner(agreement)
        _signature(agreement, version=version, position=1, name=me["name"], title=me["title"],
                   email=me["email"], mark=mark, text=text, ip=ip, user_agent=user_agent,
                   now=now)
        agreement.owner_signed_at = now
        agreement.last_activity_at = now
        fields = ["owner_signed_at", "last_activity_at"]
        if alone:
            agreement.all_signed_at = now
            fields.append("all_signed_at")
        agreement.save(update_fields=fields)
        _event(agreement, "owner_signed",
               detail=f"Signed by the owner, {me['name']}" if alone else
               f"Signed by {_whose(agreement, 1)}", ip=ip, user_agent=user_agent)
    _after_owner_signed(agreement, 1)
    return agreement


def _co_owner_signs(agreement, position, *, method, typed, drawn, agreed, ip, user_agent):
    co = CoOwner.all_objects.filter(agreement=agreement, position=position).first()
    if co is None:
        raise Refused("This link isn't valid.", 404)
    if co.signed_at is not None:
        raise Refused("You've signed this agreement already. Thank you!", 409)
    if turn(agreement) != position:
        raise Refused(f"It isn't your turn to sign yet: {owner_at(agreement, turn(agreement) or 1)['name']} "
                      "signs first. We'll email you when it's your turn.", 409)
    if agreed is not True:
        raise Refused("Tick the box to agree to sign electronically.")
    mark = _mark(method, typed, drawn)
    first = AgreementSignature.all_objects.get(agreement=agreement, role="owner", position=1)
    text = words(agreement)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != first.text_sha256:
        # The same words for every owner, or nobody signs (owner, 2026-11-24).
        _quietly("the words-changed notice", _tell_words_changed, agreement)
        raise WordsChanged(f"This agreement changed after {first.printed_name} signed it, so it "
                           f"can't be signed now. {_brand(agreement.company)} has been told and "
                           "will be in touch.", 409)
    with transaction.atomic():
        locked = CoOwner.all_objects.select_for_update().get(pk=co.pk)
        if locked.signed_at is not None:
            raise Refused("You've signed this agreement already. Thank you!", 409)
        now = timezone.now()
        _signature(agreement, version=first.version, position=position, name=co.name,
                   title=co.title, email=co.email, mark=mark, text=text, ip=ip,
                   user_agent=user_agent, now=now)
        co.signed_at = now
        co.save(update_fields=["signed_at"])
        last = turn(agreement) is None
        agreement.last_activity_at = now
        fields = ["last_activity_at"]
        if last:
            agreement.all_signed_at = now
            fields.append("all_signed_at")
        agreement.save(update_fields=fields)
        _event(agreement, "owner_signed", detail=f"Signed by {_whose(agreement, position)}",
               ip=ip, user_agent=user_agent)
    _after_owner_signed(agreement, position)
    return agreement


def _tell_words_changed(agreement):
    from . import mail

    mail.to_staff(agreement, access.users_with(agreement.company, "agreements",
                                               practice_owner=True),
                  title=f"Owner agreement #{agreement.number} can't be signed",
                  text=words_problem(agreement) or "Its words no longer match what the first "
                  "owner signed.",
                  source_type=f"agreement_words_{timezone.now():%Y%m%d%H%M%S}")


def words_problem(agreement) -> str:
    """Why SkyRun can't sign: the words no longer match what an owner signed.
    A change to Exhibit A's table is named, with what to do (owner,
    2026-11-24). "" when the words match."""
    sigs = list(AgreementSignature.all_objects.filter(agreement=agreement, role="owner"))
    if not sigs:
        return ""
    now = hashlib.sha256(words(agreement).encode("utf-8")).hexdigest()
    changed = [s for s in sigs if s.text_sha256 != now]
    if not changed:
        return ""
    many = len(owners(agreement)) > 1
    who = "the owners" if many else "the owner"
    signed = changed[0].exhibit_a or {}
    today = exhibit_a.numbers(signed.get("sleeps")) if signed else None
    if signed and today and {k: signed.get(k) for k in exhibit_a.KEYS} != \
            {k: today[k] for k in exhibit_a.KEYS}:
        return (f"SkyRun can't sign this agreement: Exhibit A's quantities were changed after "
                f"{who} signed. {who.capitalize()} signed for {exhibit_a.said(signed)}; the "
                f"table now gives {exhibit_a.said(today)}. To put it right, cancel this "
                "agreement (the reason can be \"Exhibit A changed\"), then press \"Start a new "
                "agreement from this one\" and send it. Every owner signs the new one, and the "
                "owner's intake moves to it with its answers.")
    return (f"The agreement's words don't match what {who} signed. Nothing can be "
            "countersigned; tell the practice owner.")


def _quietly(what, fn, *args, **kwargs):
    """A follow-on step: if it fails it is logged and recorded, and the
    signature it follows stands."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("owner agreement: %s failed", what)
        return exc


def _after_owner_signed(agreement, position):
    """After one owner signs: the next owner's turn, or, after the last, the
    copies and SkyRun's signature."""
    from . import mail

    with tenant_context(agreement.tenant_id):
        agreement.refresh_from_db()
        if position == 1:
            _quietly("the intake", to_intake, agreement)
        nxt = turn(agreement)
        if nxt is not None:
            _start_turn(agreement, nxt)
            _quietly("the team notice", mail.owner_signed_notice, agreement, position)
            return
        _after_all_signed(agreement)


def _start_turn(agreement, position):
    """The next owner's turn: their own link, by email."""
    from . import mail

    co = CoOwner.all_objects.get(agreement=agreement, position=position)
    if co.turn_started_at is None:
        co.turn_started_at = timezone.now()
        co.save(update_fields=["turn_started_at"])
    _quietly("the next owner's email", mail.to_owner, agreement, "invite", position=position)
    _event(agreement, "turn", detail=f"{_whose(agreement, position)} was emailed their link")


def _after_all_signed(agreement):
    from . import mail, pdf

    with tenant_context(agreement.tenant_id):
        result = _quietly("the owner's PDF", pdf.store_owner_copy, agreement)
        agreement.refresh_from_db()
        if agreement.owner_pdf_id:
            _quietly("the owners' copies", mail.to_owners, agreement, "owner_copy")
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
    # The other owners, as the intake's additional owners (owner, 2026-11-24).
    extras = []
    for c in co_owners(agreement):
        given, _, family = c.name.partition(" ")
        extras.append({"first_name": given, "last_name": family, "email": c.email,
                       "mobile": "", "portal": False})
    if extras:
        about["has_extra_owners"] = "yes"
        about["extra_owners"] = extras
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
    # The owner's Sleeps (owner, 2026-11-24): what goes to Track as the unit's
    # occupancy, shown on the review beside what the beds add up to.
    if d.get("sleeps"):
        staff["sleeps_total"] = d["sleeps"]
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
    not_while_acting()
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
            recorded_by_name=account_name(user),
            principal_name=tpl.signer_name, principal_title=tpl.signer_title,
            method=method, typed_text=typed, drawn_png=png,
            people=[{"user_id": u, "name": allowed[u]} for u in chosen],
            wording_version=consent.CURRENT,
            wording=authorization_words(company, user),
            recorded_at=now, ip_address=ip or None, user_agent=(user_agent or "")[:500])
    # The event log keeps the account's id and email; the PDF prints names only.
    _audit(company, user, "agreements.authority_recorded",
           {"authority_id": str(row.pk), "user_id": str(user.pk), "email": user.email,
            "name": row.recorded_by_name, "people": [p["name"] for p in row.people]})
    return row


def withdraw_authority(company, user, *, ip=None, user_agent=""):
    not_while_acting()
    if not access.is_signer(user, company):
        raise Refused("Only the company's signer can withdraw this.", 403)
    row = access.authority_in_force(company)
    if row is None:
        raise Refused("There's no authorization to withdraw.", 409)
    row.ended_at, row.withdrawn = timezone.now(), True
    row.ended_ip, row.ended_user_agent = ip or None, (user_agent or "")[:500]
    row.save(update_fields=["ended_at", "withdrawn", "ended_ip", "ended_user_agent"])
    _audit(company, user, "agreements.authority_withdrawn",
           {"authority_id": str(row.pk), "user_id": str(user.pk), "email": user.email})
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
    not_while_acting()
    company = agreement.company
    if agreement.owner_signed_at is None:
        raise Refused("The owner hasn't signed yet.", 409)
    if agreement.all_signed_at is None:
        position = turn(agreement)
        raise Refused("Not every owner has signed yet: waiting for "
                      f"{_whose(agreement, position or 1)}. SkyRun signs after the last owner.",
                      409)
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
                                                    role=AgreementSignature.Role.OWNER,
                                                    position=1)
    problem = words_problem(agreement)
    if problem:
        raise WordsChanged(problem + (" Nothing was countersigned." if "Nothing" not in problem
                                      else ""), 409)
    now = timezone.now()
    day = practice_today(company)
    applied_by_name = account_name(user)
    with transaction.atomic():
        locked = OwnerAgreement.all_objects.select_for_update().get(pk=agreement.pk)
        if locked.countersigned_at is not None:
            raise Refused("This agreement is countersigned already.", 409)
        words = countersign_words(agreement, user, signer_self=signer_self,
                                  authority=authority)
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
               detail=(f"Signed personally by {applied_by_name}" if signer_self else
                       f"SkyRun's signature applied by {applied_by_name}, under the "
                       f"authorization {authority_by(authority)} recorded on "
                       f"{_day(authority.recorded_at, company)}"))
    _audit(company, user, "agreements.countersigned",
           {"agreement_id": str(agreement.pk), "number": agreement.number,
            "user_id": str(user.pk), "email": user.email, "name": applied_by_name,
            "how": "personally" if signer_self else "under_authorization",
            "authority_id": str(authority.pk) if authority and not signer_self else None})
    _after_countersigned(agreement)
    return agreement


def account_name(user) -> str:
    """The signed-in account's full name, as the record prints it (owner,
    2026-11-24): from the account, never from the template, never an email."""
    return (getattr(user, "full_name", "") or "").strip() or "(an account with no name)"


def authorization_words(company, user) -> str:
    """The standing authorization's consent, with the signed-in account's name
    in it ("I, Michael LeClerc, adopt…"). The screen shows these words and the
    record keeps them: one function for both, so the words ticked are the
    words recorded (owner, 2026-11-25, after the screen showed "I, , adopt")."""
    tpl = texts.get(texts.DEFAULT)
    return consent.authorization(company=_brand(company), principal=tpl.signer_name,
                                 title=tpl.signer_title, recorded_by=account_name(user))


def authority_by(authority) -> str:
    """Who recorded an authorization: the account's name as it was that day."""
    if authority is None:
        return ""
    return authority.recorded_by_name or account_name(authority.principal)


def countersign_words(agreement, user, *, signer_self, authority) -> str:
    """The words the person agrees to when they countersign."""
    tpl = texts.get(agreement.template_key)
    company = agreement.company
    if signer_self:
        return consent.signer(company=_brand(company))
    return consent.apply(company=_brand(company),
                         principal=f"{tpl.signer_name}, {tpl.signer_title}",
                         authorized_on=_day(authority.recorded_at, company),
                         recorded_by=authority_by(authority))


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
            _quietly("the owners' final copies", mail.to_owners, agreement, "final_copy")
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
            for a in rows.filter(all_signed_at__isnull=True, sent_at__isnull=False):
                _remind_owner(a, company, local)
            for a in rows.filter(all_signed_at__isnull=False, countersigned_at__isnull=True):
                done = set((a.reminders or {}).get("countersign", []))
                hours = (timezone.now() - a.all_signed_at).total_seconds() / 3600
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


def _remind_owner(a, company, local):
    """Owner, 2026-11-24: reminders go to whoever's turn it is, on days 3 and
    7 counted from when their turn began."""
    from . import mail

    position = turn(a)
    if position is None or local.hour < 9:
        return
    if position == 1:
        if not a.owner_email:
            return
        done = set((a.reminders or {}).get("owner", []))
        due = [d for d in OWNER_DAYS if d not in done and _days_since(a.sent_at, company) >= d]
        if due:
            _quietly("an owner reminder", mail.to_owner, a, "reminder")
            _remember(a, "owner", due)
        return
    co = CoOwner.all_objects.get(agreement=a, position=position)
    if co.turn_started_at is None:
        return
    done = set(co.reminders or [])
    due = [d for d in OWNER_DAYS if d not in done and _days_since(co.turn_started_at, company) >= d]
    if due:
        _quietly("an owner reminder", mail.to_owner, a, "reminder", position=position)
        co.reminders = sorted(done | set(due))
        co.save(update_fields=["reminders"])
        _event(a, "reminded", detail=f"Reminded {_whose(a, position)} to sign")


def _remember(agreement, key, days):
    reminders = dict(agreement.reminders or {})
    reminders[key] = sorted(set(reminders.get(key, [])) | set(days))
    agreement.reminders = reminders
    agreement.save(update_fields=["reminders"])
    _event(agreement, "reminded", detail={"owner": "Reminded the owner to sign",
                                          "countersign": "Reminded the countersigners",
                                          "form": "Reminded the owner to finish the form"}[key])
