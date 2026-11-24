"""The owner's personal link, and the message staff send it in.

ENHQ never emails an owner (owner, 2026-11-19). Staff copy the link, copy a
short message, or open it in their own email (a mailto with the owner's
address, a subject and the message filled in); each is recorded.

Addresses: on the form's own domain when one is set (the slug leaves the
path), otherwise ENHQ's host with the slug, for testing until a domain is set.
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from apps.crm.services import secrets as cipher
from apps.tenancy.models import CLIENT_ROLES

from .models import Submission, SubmissionEvent


def issue(submission: Submission) -> str:
    """A new random token for `submission` (set, not saved). Returns it."""
    raw = Submission.new_token()
    submission.token_hash = Submission.hash_token(raw)
    submission.token_ciphertext = cipher.encrypt(raw)
    return raw


def token_of(submission) -> str:
    return cipher.decrypt(submission.token_ciphertext)


def resolve(raw: str):
    """The submission for a token, or None. Expiry and status are the
    caller's to check, so an expired link can say it expired."""
    if not raw or len(raw) > 100:
        return None
    return (Submission.all_objects.select_related("form", "company")
            .filter(token_hash=Submission.hash_token(raw)).first())


def form_base(form) -> str:
    """Where the form's pages live: its own domain, or ENHQ's host + slug."""
    if form.domain:
        return f"https://{form.domain}"
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/forms/{form.slug}"


def url_for(submission) -> str:
    return f"{form_base(submission.form)}/{token_of(submission)}"


def signature(user, membership, form) -> str:
    """Signed by the staff member and the company. A practice user's name never
    reaches an owner (white label): their message is signed by the company."""
    if membership is not None and membership.role in CLIENT_ROLES and user is not None:
        name = (getattr(user, "full_name", "") or "").strip()
        if name:
            return f"{name}\n{form.brand_name}"
    return form.brand_name


def message(submission, *, reminder: bool, user, membership) -> dict:
    """{subject, body, mailto} for the invite or a reminder."""
    form = submission.form
    from .defaults import MESSAGE_INVITE, MESSAGE_REMINDER, modernised

    template = modernised(form.settings or {}).get("message_reminder" if reminder
                                                   else "message_invite") or {}

    fallback = MESSAGE_REMINDER if reminder else MESSAGE_INVITE
    values = {"first_name": submission.invite_first_name or "there", "link": url_for(submission),
              "signature": signature(user, membership, form), "brand": form.brand_name}
    subject = _fill(template.get("subject") or fallback["subject"], values)
    body = _fill(template.get("body") or fallback["body"], values)
    to = submission.invite_email or ""
    mailto = f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}"
    return {"subject": subject, "body": body, "mailto": mailto, "to": to}


def _fill(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


ACTIONS = {"link": SubmissionEvent.Kind.LINK_COPIED, "message": SubmissionEvent.Kind.MESSAGE_COPIED,
           "email": SubmissionEvent.Kind.EMAIL_OPENED}


def record(submission, action: str, *, reminder: bool, actor):
    """Record that the link was copied, the message copied, or the email opened."""
    kind = ACTIONS[action]
    what = "reminder" if reminder else "invite"
    words = {"link": "Copied the link", "message": f"Copied the {what} message",
             "email": f"Opened the {what} in email"}[action]
    SubmissionEvent.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                       kind=kind, actor=actor, detail=words)


def reopen(submission, actor):
    """A manager reopens an expired link: good for 30 days from now."""
    submission.last_activity_at = timezone.now()
    submission.save(update_fields=["last_activity_at"])
    SubmissionEvent.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                       kind=SubmissionEvent.Kind.REOPENED, actor=actor,
                                       detail="Reopened the link for 30 days")
