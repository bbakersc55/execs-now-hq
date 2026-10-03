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

import re

from django.conf import settings
from django.utils.html import escape

from apps.crm.models import OutboxMessage
from apps.crm.services import email_layout, html_clean, outbox
from apps.strategy import pdf as pdf_service
from apps.strategy import rewording, services
from apps.strategy.models import StrategySession
from apps.tenancy import contrast
from apps.tenancy.models import AuditEvent

INVITE_SUBJECT = "Before our strategy session"
QUESTIONS_SUBJECT = "A few questions before our strategy session"
PDF_SUBJECT = "Your strategy map"

#: Said once, above the six, rather than beside each of them. Held in
#: `rewording` so the form, this email and the PDF say the same thing.
RATING_SCALE = rewording.RATING_SCALE


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
    # The practice's accent, with whichever text color reads on it (P1, D4);
    # it was Executives Now's orange for every practice.
    brand = email_layout.branding(session.tenant)
    button = (f'<p><a href="{escape(url)}" style="display:inline-block;padding:10px 18px;'
              f'border-radius:6px;background:{brand.accent_color};'
              f'color:{contrast.text_on(brand.accent_color)};font-weight:700;'
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


def _pdf_body(session, note: str = "", body_html: str | None = None) -> tuple[str, str]:
    """The covering note the map travels with. Extracted so the send panel can
    show it before it goes (incident, 2026-09-22).

    `body_html` is the whole note as the fractional edited it (owner,
    2026-09-29), cleaned here whatever the browser sent. Without it, the
    one-line `note` form still works as it did.
    """
    if body_html is not None:
        content = html_clean.clean(body_html)
        return html_clean.to_text(content), email_layout.document(
            session.tenant, content_html=content, subject=PDF_SUBJECT,
            preheader="Your strategy map from today.")
    name = session.contact.first_name or "there"
    fractional = services.merge_context(session).get("Fractional name", "")
    lines = [f"Hi {name},", "",
             "Your strategy map from today is attached, along with the snapshot "
             "and the notes we took together."]
    if note.strip():
        lines += ["", note.strip()]
    if fractional:
        lines += ["", "Thanks,", fractional]
    return "\n".join(lines), email_layout.document(
        session.tenant,
        content_html="".join(f"<p>{escape(line)}</p>" for line in lines if line),
        subject=PDF_SUBJECT, preheader="Your strategy map from today.")


#: The agreed §9 items the covering note mentions, and how each reads in a
#: sentence. `{d}` is the fractional's own note on the item. **A sentence
#: appears only when that note reads as a date or a day** (owner, 2026-09-29):
#: "In general, no specific date set" in a date sentence is worse than no
#: sentence. "Who else weighs in" is not here: its note is people, not a date.
NEXT_STEP_LINES = (
    ("s9_follow_up_call", "We agreed to speak again on {d}."),
    ("s9_proposal_due", "You will have my proposal by {d}."),
    ("s9_start_date", "We talked about starting on {d}."),
)

_DAYS = ("monday tuesday wednesday thursday friday saturday sunday "
         "mon tue tues wed thu thur thurs fri sat sun").split()
_MONTHS = ("january february march april may june july august september october "
           "november december jan feb mar apr jun jul aug sep sept oct nov dec").split()
#: Words a date or a day may carry without being anything else.
_FILLER = {"next", "this", "on", "at", "the", "of", "by", "am", "pm", "a.m.", "p.m.",
           "noon", "midday", "morning", "afternoon", "evening", "mt", "mdt", "mst"}
_NUMERIC_DATE = re.compile(r"^\d{1,4}[/.-]\d{1,2}([/.-]\d{2,4})?$")
_ORDINAL = re.compile(r"^\d{1,2}(st|nd|rd|th)?$")
_YEAR = re.compile(r"^(19|20)\d{2}$")
_TIME = re.compile(r"^\d{1,2}([:.]\d{2})?(am|pm)?$")


def reads_as_date_or_day(text: str) -> bool:
    """True for "Next Tuesday", "10/1", "Tue 7 Oct, 10am", "October 7th",
    "tomorrow"; false for anything with a word that is not part of a date —
    "In general, no specific date set", "Once the board has met"."""
    words = re.findall(r"[a-z0-9:./-]+", (text or "").lower())
    if not words:
        return False
    anchored = month = day_number = False
    for word in words:
        word = word.strip(".-/")
        if not word:
            continue
        if word in _DAYS or word in ("today", "tomorrow") or _NUMERIC_DATE.match(word):
            anchored = True
        elif word in _MONTHS:
            month = True                 # a date only with a day beside it
        elif _ORDINAL.match(word):
            day_number = True
        elif word in _FILLER or _YEAR.match(word) or _TIME.match(word):
            continue
        else:
            return False
    return anchored or (month and day_number)


def default_pdf_cover(session) -> str:
    """The covering note, drafted from the session (owner, 2026-09-29): their
    name, the date, the goal they stated in the mirror, the two paths, and the
    next step they agreed with its date. Every part is left out when the
    session does not have it, rather than filled in. The fractional edits all
    of it before anything is sent."""
    ctx = pdf_service.context_for(session)
    e = escape
    name = session.contact.first_name or "there"
    company = ctx["company"]
    parts = [f"<p>Hi {e(name)},</p>",
             f"<p>Thank you for your time on {e(ctx['session_date'])}. I enjoyed "
             f"getting into how {e(company) if company else 'the business'} runs, and "
             "your strategy map is attached: what we found, what to fix first, and "
             "how we would measure it.</p>"]
    goal = (ctx["mirror_goal"] or "").strip().rstrip(".")
    if goal:
        parts.append(f"<p>You told me what you are aiming for: <strong>{e(goal)}</strong>. "
                     "Everything on the map is there because it stands between you "
                     "and that.</p>")
    paths = ctx["path_pair"]
    if paths:
        items = "".join(f"<li><strong>{e(p['label'])}</strong>: {e(p['title'])}</li>"
                        for p in paths)
        parts.append(f"<p>We looked at two ways forward:</p><ul>{items}</ul>"
                     "<p>Either way, the map is yours to use.</p>")
    by_key = {item["key"]: item for item in ctx["scope"] if not item["is_financial"]}
    steps = []
    for key, line in NEXT_STEP_LINES:
        value = (by_key.get(key) or {}).get("value") or {}
        detail = (value.get("notes") or "").strip()
        if value.get("agreed") and reads_as_date_or_day(detail):
            steps.append(line.format(d=e(detail.rstrip("."))))
    if steps:
        parts.append(f"<p>{' '.join(steps)}</p>")
    parts.append("<p>If anything in it raises a question, just reply to this email.</p>")
    fractional = ctx["fractional"]
    parts.append(f"<p>Thanks,<br>{e(fractional)}</p>" if fractional else "<p>Thanks,</p>")
    return "".join(parts)


def send_strategy_pdf(session, *, actor=None, role=None, note="", body_html=None):
    """Same-day: the map, as a PDF, to the prospect (R8, matrix 10.11).

    The file is stored first, so what was emailed can be re-read exactly as it
    was sent even after the session changes.
    """
    address = session.contact.primary_email
    if not address:
        raise services.SessionError(
            f"{session.contact.first_name} has no email address to send to.", status=400)
    if body_html is not None and not html_clean.to_text(html_clean.clean(body_html)).strip():
        raise services.SessionError("The email is empty. Write something, or reset it "
                                    "to the drafted one.", status=400)
    stored = pdf_service.store_pdf(session)
    text, html = _pdf_body(session, note, body_html)
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


# ------------------------------- the questions in the body (owner, 2026-09-21)
#
# The second way the pre-call goes out, for a prospect who will not click a
# link: the questions themselves, in an email they can reply to. There is no
# token, no form and nothing to sign in to — which is also why there is nothing
# here to redact from the stored copy, unlike the invite.


def default_intro(session) -> str:
    """The intro the fractional starts from and then makes their own."""
    merge = services.merge_context(session)
    name = session.contact.first_name or "there"
    when = merge.get("Session date", "")
    return (
        f"Hi {name},\n\n"
        f"Ahead of our session{f' on {when}' if when else ''}, here are a few "
        f"questions. Answer them straight back in a reply — no form, no login, "
        f"and rough numbers are fine. It means we spend the call on what is "
        f"actually in the way rather than on getting the background straight."
    )


def question_blocks(session):
    """The pre-call questions, by section, with merge fields resolved.

    **Nothing the fractional keeps to themselves goes in here.** A question
    marked as their own observation is one they never ask aloud (FR-4.17), and
    a financial question is a financial question (ruling 3) — neither belongs in
    a prospect's inbox, and the exclusion is applied while the content is built
    rather than hidden in the template.
    """
    merge = services.merge_context(session)
    blocks: list[dict] = []
    for section, question in services.questions_in(session.template_snapshot,
                                                   ask_when="precall"):
        if question.get("is_fractional_observation") or question.get("is_financial"):
            continue
        # Asked only if the call has time (owner, 2026-09-26): not something to
        # send a prospect ahead of it.
        if question.get("ask_if_time"):
            continue
        if not blocks or blocks[-1]["code"] != section["code"]:
            blocks.append({"code": section["code"], "title": section["title"],
                           "questions": [], "is_rating": False})
        blocks[-1]["questions"].append(
            services.render_prompt(question["prompt"], merge))
        if question["response_schema"] == "rating_1_10":
            blocks[-1]["is_rating"] = True
    return blocks


def _questions_body(session, intro: str) -> tuple[str, str]:
    """`(text, html)` — one set, because there is no credential to withhold."""
    merge = services.merge_context(session)
    fractional = merge.get("Fractional name", "")
    blocks = question_blocks(session)

    lines = [intro.strip(), ""]
    html = ["".join(f"<p>{escape(part)}</p>"
                    for part in intro.strip().split("\n\n") if part.strip())]
    for block in blocks:
        lines += [block["title"].upper(), ""]
        html.append(f"<h3 style=\"font-size:15px;margin:22px 0 6px;\">"
                    f"{escape(block['title'])}</h3>")
        if block["is_rating"]:
            lines += [RATING_SCALE, ""]
            html.append(f"<p style=\"margin:0 0 8px;\">{escape(RATING_SCALE)}</p>")
        items = []
        for index, prompt in enumerate(block["questions"], start=1):
            lines.append(f"{index}. {prompt}")
            items.append(f"<li style=\"margin:0 0 6px;\">{escape(prompt)}</li>")
        lines.append("")
        html.append(f"<ol style=\"margin:0 0 4px;padding-left:20px;\">"
                    f"{''.join(items)}</ol>")

    closing = "Just reply to this email with your answers."
    lines.append(closing)
    html.append(f"<p>{escape(closing)}</p>")
    if fractional:
        lines += ["", "Thanks,", fractional]
        html.append(f"<p>Thanks,<br>{escape(fractional)}</p>")
    return "\n".join(lines).strip(), "".join(html)


def send_precall_questions(session, *, actor=None, role=None, intro=""):
    """Send the questions themselves, from the fractional's own address.

    **Their own address, not the practice alias** (FR-1.15c's `self`): the
    prospect answers by hitting reply, and a reply has to land somewhere a
    person reads. If they have no verified address of their own the resolver
    falls back to the alias, which still reaches the practice.
    """
    from apps.crm.services import sender as sender_service
    from apps.crm.models import MailPreference
    from django.utils import timezone

    address = session.contact.primary_email
    if not address:
        raise services.SessionError(
            f"{session.contact.first_name} has no email address to send to.", status=400)
    body_text, content_html = _questions_body(session, intro or default_intro(session))
    message = outbox.create_message(
        tenant=session.tenant, producer=OutboxMessage.Producer.PRECALL_QUESTIONS,
        to_address=address, to_contact=session.contact, subject=QUESTIONS_SUBJECT,
        body_text=body_text,
        body_html=email_layout.document(
            session.tenant, content_html=content_html, subject=QUESTIONS_SUBJECT,
            preheader="A few questions before we talk — just reply."),
        from_address=sender_service.resolve_from(
            session.tenant, actor, OutboxMessage.Producer.PRECALL_QUESTIONS,
            override=MailPreference.Sender.SELF),
        actor=actor, role=role,
        source_type="strategy_session", source_id=session.pk,
    )
    session.precall_questions_sent_at = timezone.now()
    fields = ["precall_questions_sent_at", "updated_at"]
    if session.state == StrategySession.State.DRAFT:
        session.state = StrategySession.State.PRECALL_SENT
        fields.append("state")
    session.save(update_fields=fields)
    AuditEvent.all_objects.create(
        tenant=session.tenant, actor=actor, verb="strategy.precall_questions_sent",
        target_type="strategy_session", target_id=session.pk,
        payload={"to": address, "outbox_message": str(message.pk),
                 "from": message.from_address})
    return message


# --------------------------------- what will go out, before it goes out
#
# The incident of 2026-09-22: the send panel showed the fractional's opening
# line and not the questions beneath it, so six broken questions went to a
# prospect without anybody having seen them. **Nothing sends from a panel that
# has not shown the whole body first**, and these are what the panels show.

#: The link is issued when Send is pressed, not when the preview is drawn — a
#: preview that minted a token would leave a live credential behind every time
#: somebody looked.
PREVIEW_LINK = "https://…/strategy/precall/… (the link is created when you send)"


def _preview(session, *, subject, body_text, body_html, producer, actor):
    from apps.crm.models import MailPreference
    from apps.crm.services import sender as sender_service

    return {
        "subject": subject,
        "to_address": session.contact.primary_email or "",
        "from_address": sender_service.resolve_from(
            session.tenant, actor, producer,
            override=(MailPreference.Sender.SELF
                      if producer == OutboxMessage.Producer.PRECALL_QUESTIONS else "")),
        "body_text": body_text,
        "body_html": body_html,
    }


def preview_precall_invite(session, *, actor=None):
    _stored_text, _stored_html, sent_text, sent_html = _invite_body(session, PREVIEW_LINK)
    return _preview(session, subject=INVITE_SUBJECT, body_text=sent_text,
                    body_html=email_layout.document(
                        session.tenant, content_html=sent_html, subject=INVITE_SUBJECT,
                        preheader="A few questions before we talk."),
                    producer=OutboxMessage.Producer.PRECALL_INVITE, actor=actor)


def preview_precall_questions(session, *, intro="", actor=None):
    body_text, content_html = _questions_body(session, intro or default_intro(session))
    return _preview(session, subject=QUESTIONS_SUBJECT, body_text=body_text,
                    body_html=email_layout.document(
                        session.tenant, content_html=content_html,
                        subject=QUESTIONS_SUBJECT,
                        preheader="A few questions before we talk — just reply."),
                    producer=OutboxMessage.Producer.PRECALL_QUESTIONS, actor=actor)


def preview_strategy_pdf(session, *, note="", body_html=None, actor=None):
    """The covering note only. The document itself has had its own true preview
    since AC-4.10 — this is the email it travels in, which had none."""
    body_text, body_html = _pdf_body(session, note, body_html)
    # A browser cannot show the `cid:` logo a mail client resolves from the
    # attachment; the preview inlines it, as the PDF preview does.
    body_html, _ = email_layout.with_logo(body_html, session.tenant, as_data_uri=True)
    return _preview(session, subject=PDF_SUBJECT, body_text=body_text,
                    body_html=body_html,
                    producer=OutboxMessage.Producer.STRATEGY_PDF, actor=actor)
