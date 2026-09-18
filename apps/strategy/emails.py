"""The module's two emails (Phase 4, done-means 9).

Both go through the shared base layout and the Outbox, like everything else
that leaves the app — no separate styling, a text/plain part on each, and a row
in the send log either way.

The invite carries a **credential**, so it follows the magic-link rule: the link
is in `deliver_body_text`/`deliver_body_html`, which is what the prospect
receives and is never stored. The Outbox copy every tenant user can read carries
the same words with the link removed (assumption C3).
"""

from __future__ import annotations

from django.conf import settings
from django.utils.html import escape

from apps.crm.models import OutboxMessage
from apps.crm.services import email_layout, outbox
from apps.strategy import pdf as pdf_service
from apps.strategy import services
from apps.strategy.models import StrategySession
from apps.tenancy.models import AuditEvent

INVITE_SUBJECT = "Before our strategy session"
PDF_SUBJECT = "Your strategy map"


def precall_url(raw_token: str) -> str:
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return f"{root.rstrip('/')}/strategy/precall/{raw_token}"


def _invite_body(session, url) -> tuple[str, str, str, str]:
    """`(stored_text, stored_html, sent_text, sent_html)`.

    The stored pair says the link was sent without carrying it; the sent pair is
    what lands in the prospect's inbox.
    """
    merge = services.merge_context(session)
    name = session.contact.first_name or "there"
    fractional = merge.get("Fractional name", "")
    when = merge.get("Session date", "")
    count = sum(1 for _s, q in services.questions_in(session.template_snapshot,
                                                     ask_when="precall"))
    opening = (f"Hi {name},\n\n"
               f"Ahead of our session{f' on {when}' if when else ''}, here are "
               f"{count} short questions. They take about ten minutes and they "
               f"mean we spend the call on what is actually in the way, rather "
               f"than on getting the background straight.\n\n")
    closing = f"\n\nThanks,\n{fractional}" if fractional else ""
    stored_text = f"{opening}[The form link was sent to {session.contact.primary_email}.]{closing}"
    sent_text = f"{opening}{url}{closing}"
    body = escape(opening).replace("\n\n", "</p><p>").replace("\n", "<br>")
    button = (f'<p><a href="{escape(url)}" style="display:inline-block;padding:10px 18px;'
              f'border-radius:6px;background:#F58220;color:#ffffff;font-weight:700;'
              f'text-decoration:none;">Open the form</a></p>')
    tail = escape(closing).replace("\n", "<br>")
    stored_html = f"<p>{body}</p><p><em>The form link was sent to the prospect.</em></p><p>{tail}</p>"
    sent_html = f"<p>{body}</p>{button}<p>{tail}</p>"
    return stored_text, stored_html, sent_text, sent_html


def send_precall_invite(session, *, actor=None, role=None):
    """Issue a fresh token and send the form (FR-4.6, matrix 10.3)."""
    address = session.contact.primary_email
    if not address:
        raise services.SessionError(
            f"{session.contact.first_name} has no email address to send to.", status=400)
    raw = services.issue_precall_token(session)
    url = precall_url(raw)
    stored_text, stored_html, sent_text, sent_html = _invite_body(session, url)
    message = outbox.create_message(
        tenant=session.tenant, producer=OutboxMessage.Producer.PRECALL_INVITE,
        to_address=address, to_contact=session.contact, subject=INVITE_SUBJECT,
        body_text=stored_text,
        body_html=email_layout.document(session.tenant, content_html=stored_html,
                                        subject=INVITE_SUBJECT,
                                        preheader="A few questions before we talk."),
        deliver_body_text=sent_text,
        deliver_body_html=email_layout.document(
            session.tenant, content_html=sent_html, subject=INVITE_SUBJECT,
            preheader="A few questions before we talk."),
        actor=actor, role=role,
        source_type="strategy_session", source_id=session.pk,
    )
    if session.state == StrategySession.State.DRAFT:
        session.state = StrategySession.State.PRECALL_SENT
        session.save(update_fields=["state", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=session.tenant, actor=actor, verb="strategy.precall_sent",
        target_type="strategy_session", target_id=session.pk,
        payload={"to": address, "outbox_message": str(message.pk)})
    return message


def send_strategy_pdf(session, *, actor=None, role=None, note=""):
    """Same-day: the map, as a PDF, to the prospect (R8, matrix 10.11).

    The file is stored first, so what was emailed can be re-read exactly as it
    was sent even after the session changes.
    """
    address = session.contact.primary_email
    if not address:
        raise services.SessionError(
            f"{session.contact.first_name} has no email address to send to.", status=400)
    stored = pdf_service.store_pdf(session)
    name = session.contact.first_name or "there"
    fractional = services.merge_context(session).get("Fractional name", "")
    lines = [f"Hi {name},", "",
             "Your strategy map from today is attached, along with the snapshot "
             "and the notes we took together."]
    if note.strip():
        lines += ["", note.strip()]
    if fractional:
        lines += ["", "Thanks,", fractional]
    text = "\n".join(lines)
    html = email_layout.document(
        session.tenant,
        content_html="".join(f"<p>{escape(line)}</p>" for line in lines if line),
        subject=PDF_SUBJECT, preheader="Your strategy map from today.")
    message = outbox.create_message(
        tenant=session.tenant, producer=OutboxMessage.Producer.STRATEGY_PDF,
        to_address=address, to_contact=session.contact, subject=PDF_SUBJECT,
        body_text=text, body_html=html, actor=actor, role=role,
        attachments=[(stored, "strategy-map.pdf")],
        source_type="strategy_session", source_id=session.pk,
    )
    AuditEvent.all_objects.create(
        tenant=session.tenant, actor=actor, verb="strategy.pdf_sent",
        target_type="strategy_session", target_id=session.pk,
        payload={"to": address, "outbox_message": str(message.pk),
                 "stored_file": str(stored.pk),
                 "include_flags": pdf_service.flags_of(session)})
    return message
