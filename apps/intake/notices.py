"""Telling a company's managers (and the practice owner) about its intakes:
in the app always, and by email where the owner asked for it. ENHQ email goes
only to these staff, never to an owner, and never carries an answer.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils.html import escape

from . import access

log = logging.getLogger(__name__)


def app_url(path: str) -> str:
    base = settings.APP_ROOT_URL if settings.IS_LOCAL else settings.PUBLIC_BASE_URL
    return f"{base.rstrip('/')}{path}"


def review_path(submission) -> str:
    return f"/intake/{submission.pk}"


def tell(submission, *, source_type, title, text, source_id=None, email=False, users=None):
    """Tell everyone who runs this company's intakes (or just `users`)."""
    from apps.notify.models import Kind
    from apps.notify.service import tell as notify

    people = users if users is not None else access.recipients(submission.company)
    path = review_path(submission)
    for user in people:
        notify(tenant_id=submission.tenant_id, recipient_id=user.pk, kind=Kind.INTAKE,
               title=title, text=text, url=path, source_type=source_type,
               source_id=source_id)
        if email and user.email:
            _email(submission, user, title, text, path)


def _email(submission, user, subject, text, path):
    """A notice's email. If it can't go, the notice in the app stands and the
    thing that caused it (an owner's submit) is never undone."""
    try:
        _send(submission, user, subject, text, path)
    except Exception:                                   # noqa: BLE001
        log.exception("intake notice email to user %s not sent", user.pk)


def _send(submission, user, subject, text, path):
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox

    link = app_url(path)
    lines = [text, f"Open it in the app: {link}"]
    html = (f"<p>{escape(text)}</p>"
            f'<p><a href="{escape(link)}">Open it in the app</a></p>')
    outbox.create_message(
        tenant=submission.tenant, producer=OutboxMessage.Producer.INTAKE_NOTICE,
        to_address=user.email, subject=subject, body_text="\n\n".join(lines),
        body_html=email_layout.document(submission.tenant, content_html=html, subject=subject,
                                        preheader=text[:140], internal=True),
        source_type="intake_submission", source_id=submission.pk)


def submitted(submission):
    """Owner, 2026-11-19: managers and above and the practice owner, in the
    app and by email. The email carries no answers."""
    tell(submission, source_type="intake_submitted", source_id=submission.pk, email=True,
         title=f"New owner intake #{submission.number} submitted",
         text=(f"An owner finished the {submission.form.title.lower()} form for "
               f"{submission.company.name}. Review it and send it to Track."))
