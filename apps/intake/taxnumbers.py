"""The tax number for the rental permit (owner, 2026-11-24). It replaced "no
Social Security number on the form": SkyRun needs the full number once, to
file the rental permit, and taking it by phone and writing it down was worse.
Bank details stay off the form, and nothing of this is on the agreement.

- **The choice:** the owner's business tax ID (EIN), their Social Security
  number or ITIN, or "I'd rather give it by phone" (nothing entered; the
  review says the owner asked for a call, staff type it in there after the
  call, and the onboarding checklist gets a task for it).
- **Kept** like the Tax ID always was (`vault`): Fernet-encrypted in
  `intake_submission_secret`, its last four the only part any screen shows.
- **Seen in full** only by someone ticked "See full tax numbers" on People and
  permissions, on the intake review, after a one-time code emailed to their
  own sign-in address: on screen for 60 seconds, then masked. Never while
  acting as someone. Each viewing is an audit event (who, when, which intake,
  never the number), a line in the intake's history, and a notice to the
  people who may change ticks.
- **Removed** when Track confirms it has it (as the Tax ID always was), when
  the intake is sent, 30 days after the owner submitted if it hasn't been
  sent, and 30 days after it was entered on a form never submitted. A test
  send removes nothing.
- **Nowhere else:** no email, PDF, copy of the form, export, log, error
  message, search, MCP tool or AI request (tests/test_tax_numbers.py).
"""

from __future__ import annotations

import re
import secrets as pysecrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

KINDS = ("tax_id", "ssn", "phone")
#: What a number is, for Track's format and for people.
LABEL = {"tax_id": "Business tax ID (EIN)", "ssn": "Social Security number or ITIN"}
NOUN = {"tax_id": "business tax ID (EIN)", "ssn": "Social Security number or ITIN",
        "phone": "tax number"}
#: Kept at most this long when it isn't sent (owner, 2026-11-24).
KEEP = timedelta(days=30)
CODE_LIFETIME = timedelta(minutes=10)
MOST_TRIES = 5
MOST_CODES_AN_HOUR = 5
SHOWN_SECONDS = 60
MASK = "[tax number]"
_SALT = "apps.intake.taxnumbers"
_EIN = re.compile(r"^\d{2}-\d{7}$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")


class Refused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------ the choice

def kind_of(answers) -> str:
    """"tax_id", "ssn", "phone" or "": what the owner chose."""
    kind = ((answers or {}).get("tax") or {}).get("kind") or ""
    return kind if kind in KINDS else ""


def number_kind(answers) -> str:
    """Which number is (or will be) held: "tax_id" or "ssn"; for the phone
    choice, what staff said the owner gave them; "" when not known yet."""
    tax = (answers or {}).get("tax") or {}
    kind = kind_of(answers)
    if kind == "phone":
        given = tax.get("phone_kind") or ""
        return given if given in LABEL else ""
    return kind


def check(kind: str, value: str) -> str:
    """The number in Track's usual form (12-3456789, 123-45-6789), or a
    refusal said for the person typing it."""
    from .vault import Refused as VaultRefused

    value = (value or "").strip()
    digits = re.sub(r"\D", "", value)
    if kind == "tax_id":
        if _SSN.match(value):
            raise VaultRefused("That looks like a Social Security number. Choose \"My Social "
                               "Security number or ITIN\" above if that's the one.")
        if len(digits) != 9 or digits == "0" * 9 or digits[:2] == "00":
            raise VaultRefused("A business tax ID (EIN) has 9 digits, like 12-3456789.")
        return f"{digits[:2]}-{digits[2:]}"
    if kind == "ssn":
        if _EIN.match(value):
            raise VaultRefused("That looks like a business tax ID (EIN). Choose \"My business "
                               "tax ID (EIN)\" above if that's the one.")
        if len(digits) != 9:
            raise VaultRefused("A Social Security number or ITIN has 9 digits, like "
                               "123-45-6789.")
        # ITINs start with 9 (owner, 2026-11-24: foreign owners have them).
        if digits[:3] in ("000", "666") or digits[3:5] == "00" or digits[5:] == "0000":
            raise VaultRefused("That isn't a Social Security number or ITIN that can be "
                               "issued. Please check it.")
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    raise VaultRefused("Choose which number goes on your rental permit first.")


def wording(brand: str) -> dict:
    """Why we ask, and how it is protected (owner, 2026-11-24, as written).
    Every word is meant to be true: see the module's docstring."""
    days = settings.INTAKE_TAX_BACKUP_DAYS
    return {
        "why": (f"{brand} needs this number once, to file your property's rental permit. It's "
                "also kept on your owner account with us, for your year-end tax forms."),
        "how": (f"It's encrypted as soon as you save it, and from then on this form shows only "
                f"its last four digits. Most of our team sees only the last four. The few "
                f"people {brand} authorizes can see the full number, and only after entering a "
                f"one-time code sent to their own email. Every viewing is recorded. It's never "
                f"emailed. It's deleted from our onboarding system as soon as it's on your "
                f"owner account, or 30 days after you submit if it isn't by then. Our "
                f"encrypted backups keep a copy for up to {days} days more."),
    }


def scrub(text: str, number: str | None) -> str:
    """`text` with the number taken out, however it is written: for anything
    that came back from Track before it is saved or shown."""
    if not text or not number:
        return text
    digits = re.sub(r"\D", "", number)
    if len(digits) < 9:
        return text
    pattern = r"(?<!\d)" + r"[\s.-]?".join(re.escape(d) for d in digits) + r"(?!\d)"
    return re.sub(pattern, MASK, text)


# ------------------------------------------------------------ who may see it

def may_see(membership, company) -> bool:
    """Ticked "See full tax numbers" for the company (nobody to start, the
    practice owner included), and able to open its intakes."""
    from apps.agreements import access

    from .models import TaxNumberAccess

    if membership is None or company is None:
        return False
    if not access.may_intake(membership, company):
        return False
    return TaxNumberAccess.all_objects.filter(company=company,
                                              user_id=membership.user_id).exists()


def ticked(company) -> set[str]:
    from .models import TaxNumberAccess

    return {str(u) for u in TaxNumberAccess.all_objects.filter(company=company)
            .values_list("user_id", flat=True)}


def set_ticks(company, wanted: dict, actor) -> list[dict]:
    """{user_id: bool} from People and permissions; returns what changed."""
    from .models import TaxNumberAccess

    have = ticked(company)
    changed = []
    for user_id, on in wanted.items():
        if on and user_id not in have:
            TaxNumberAccess.all_objects.create(tenant_id=company.tenant_id, company=company,
                                               user_id=user_id, granted_by=actor)
            changed.append({"user_id": user_id, "tax_numbers": True})
        elif not on and user_id in have:
            TaxNumberAccess.all_objects.filter(company=company, user_id=user_id).delete()
            changed.append({"user_id": user_id, "tax_numbers": False})
    return changed


def editors(company) -> list:
    """The people who may change ticks: the practice owner(s) and the
    company's Client owner(s). They are told of every viewing."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    from apps.tenancy.models import Membership, Role

    ids = (Membership.all_objects.filter(tenant_id=company.tenant_id, revoked_at__isnull=True)
           .filter(Q(role=Role.FF) | Q(role=Role.FCC, client_company=company))
           .values_list("user_id", flat=True))
    return list(get_user_model().objects.filter(pk__in=list(ids), is_active=True)
                .order_by("full_name"))


# ------------------------------------------------------------ the one-time code

def _hash(code_id, code: str) -> str:
    return salted_hmac(_SALT, f"{code_id}:{code}", algorithm="sha256").hexdigest()


def request_code(submission, user) -> str:
    """Email a one-time code to the person's own sign-in address. Returns
    that address. The stored copy of the email never holds the code."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from django.utils.html import escape

    from . import vault
    from .models import SubmissionEvent, TaxCode

    _not_while_acting()
    if not _held(submission):
        raise Refused("There's no tax number held for this intake.", 404)
    if not (user.email or "").strip():
        raise Refused("Your sign-in has no email address for the code.", 409)
    hour = timezone.now() - timedelta(hours=1)
    if TaxCode.all_objects.filter(user=user, created_at__gte=hour).count() >= MOST_CODES_AN_HOUR:
        raise Refused("That's the most codes for an hour. Try again later.", 429)
    code = f"{pysecrets.randbelow(10 ** 6):06d}"
    row = TaxCode.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                     user=user, code_hash="",
                                     expires_at=timezone.now() + CODE_LIFETIME)
    row.code_hash = _hash(row.pk, code)
    row.save(update_fields=["code_hash"])
    subject = f"Your code to see a tax number (intake #{submission.number})"

    def text(shown):
        return (f"Your one-time code to see the full tax number on owner intake "
                f"#{submission.number} is {shown}. It works once, for the next 10 minutes.\n\n"
                "If you didn't ask for it, tell your practice owner: someone may be using "
                "your sign-in.")
    stored = "[the code, put in when sent]"
    outbox.create_message(
        tenant=submission.tenant, producer=OutboxMessage.Producer.TAX_NUMBER_CODE,
        to_address=user.email, subject=subject, body_text=text(stored),
        body_html=email_layout.document(submission.tenant, subject=subject,
                                        preheader="Your one-time code", internal=True,
                                        content_html=f"<p>{escape(text(stored))}</p>"),
        deliver_body_text=text(code),
        deliver_body_html=email_layout.document(
            submission.tenant, subject=subject, preheader="Your one-time code", internal=True,
            content_html=f"<p>{escape(text(code))}</p>"),
        source_type="intake_tax_code", source_id=submission.pk)
    SubmissionEvent.all_objects.create(
        tenant_id=submission.tenant_id, submission=submission,
        kind=SubmissionEvent.Kind.TAX_CODE_SENT, actor=user,
        detail="Asked for a code to see the full tax number; emailed to their sign-in address")
    return user.email


def show(submission, user, code: str) -> str:
    """The full number, once, for a person ticked to see it who entered the
    code just emailed to them. Recorded, and the editors are told."""
    from apps.tenancy.models import AuditEvent

    from . import notices, vault
    from .models import SubmissionEvent, TaxCode

    _not_while_acting()
    row = (TaxCode.all_objects.filter(submission=submission, user=user, used_at__isnull=True)
           .order_by("-created_at").first())
    if row is None or row.expires_at <= timezone.now():
        raise Refused("That code has expired or was used. Ask for a new one.", 409)
    if row.tries >= MOST_TRIES:
        raise Refused("Too many wrong tries for that code. Ask for a new one.", 429)
    code = re.sub(r"\D", "", code or "")
    if not constant_time_compare(_hash(row.pk, code), row.code_hash):
        row.tries += 1
        row.save(update_fields=["tries"])
        left = MOST_TRIES - row.tries
        raise Refused("That code isn't right." + (f" {left} tries left." if left else
                                                  " Ask for a new one."), 400)
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])
    number = vault.value(submission, "tax_id")
    if number is None:
        raise Refused("The tax number isn't held any more.", 404)
    name = (getattr(user, "full_name", "") or "").strip() or user.email
    SubmissionEvent.all_objects.create(
        tenant_id=submission.tenant_id, submission=submission,
        kind=SubmissionEvent.Kind.TAX_SHOWN, actor=user,
        detail=f"{name} saw the full tax number (shown for {SHOWN_SECONDS} seconds)")
    AuditEvent.all_objects.create(
        tenant_id=submission.tenant_id, actor=user, verb="intake.tax_number_shown",
        target_type="intake_submission", target_id=submission.pk,
        payload={"intake": submission.number, "user_id": str(user.pk), "name": name})
    when = timezone.localtime(row.used_at, _zone(submission))
    notices.tell(submission, users=editors(submission.company), email=True,
                 source_type=f"intake_tax_shown_{row.used_at:%Y%m%d%H%M%S}", source_id=submission.pk,
                 title=f"Full tax number seen on owner intake #{submission.number}",
                 text=(f"{name} saw the full tax number on owner intake #{submission.number} "
                       f"on {when:%B} {when.day} at {when:%-I:%M %p}, after a one-time code "
                       "sent to their own email."))
    return number


def _held(submission) -> bool:
    from .models import SubmissionSecret

    return SubmissionSecret.all_objects.filter(submission=submission, kind="tax_id").exists()


def _zone(submission):
    from zoneinfo import ZoneInfo

    return ZoneInfo(getattr(submission.tenant, "timezone", "") or "UTC")


def _not_while_acting():
    from apps.tenancy.context import acting_refusal

    if (message := acting_refusal()):
        raise Refused(message, 403)


# ------------------------------------------------------------ kept as short as possible

REMOVED_AFTER_SUBMIT = ("Removed the tax number: 30 days after the owner submitted, and it "
                        "hadn't been sent to Track. Ask the owner for it again, or type it in "
                        "here.")
REMOVED_UNSUBMITTED = ("Removed the tax number: 30 days after it was entered, and the form "
                       "wasn't submitted.")


def purge(tenant_id) -> int:
    """Daily: a number held 30 days after the owner submitted (or after it
    was entered, if never submitted) without being sent is removed, and the
    intake says so."""
    from .models import Submission, SubmissionEvent, SubmissionSecret

    cutoff = timezone.now() - KEEP
    count = 0
    rows = (SubmissionSecret.all_objects.filter(tenant_id=tenant_id, kind="tax_id",
                                                updated_at__lt=cutoff)
            .select_related("submission"))
    for row in rows:
        sub = row.submission
        if sub.locked_at is not None or sub.status == Submission.Status.SENT:
            continue
        if sub.submitted_at is not None and sub.submitted_at >= cutoff:
            continue
        why = REMOVED_AFTER_SUBMIT if sub.submitted_at else REMOVED_UNSUBMITTED
        row.delete()
        SubmissionEvent.all_objects.create(tenant_id=sub.tenant_id, submission=sub,
                                           kind=SubmissionEvent.Kind.SECRETS_DELETED,
                                           detail=why)
        count += 1
    return count


def removed_note(submission) -> str:
    """What the intake says when the number was removed unsent."""
    from .models import SubmissionEvent

    if _held(submission):
        return ""
    event = (SubmissionEvent.all_objects.filter(
        submission=submission, kind=SubmissionEvent.Kind.SECRETS_DELETED,
        detail__startswith="Removed the tax number: 30 days").order_by("-created_at").first())
    if event is None:
        return ""
    when = timezone.localtime(event.created_at, _zone(submission))
    return f"{event.detail} (on {when:%B} {when.day})"
