"""The pre-call form — a public page, authenticated by one token (FR-4.6).

Matrix 10.13: **the prospect has no role at all.** The token grants exactly one
capability — read the pre-call questions of one session and answer them — and
this module is written so that is all it can possibly do:

- only `precall` questions are ever put in the payload, so the live questions
  and §9 cannot be read here even by guessing a key;
- answers are written with `answered_by=prospect`, and the service refuses
  anything but a `precall` question and any attempt to write a fractional note;
- nothing about the practice, the pipeline, or any other session is reachable.

Autosave posts one answer at a time, so a half-filled form survives a closed
laptop: resuming is just loading the same link again.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.strategy import services
from apps.strategy.models import StrategyAnswer, StrategySession
from apps.tenancy.context import tenant_context

EXPIRED = {"detail": "This link has expired. Ask your contact at the practice for "
                     "a new one."}


def _payload(session):
    from apps.crm.services import email_layout

    merge = services.merge_context(session)
    answers = services.answers_of(session)
    sections = []
    answered = total = 0
    for section in session.template_snapshot.get("sections", []):
        questions = []
        for question in section.get("questions", []):
            if question["ask_when"] != services.AskWhen.PRECALL:
                continue
            total += 1
            answer = answers.get(question["key"])
            if answer is not None and answer.value:
                answered += 1
            questions.append({
                "key": question["key"],
                "prompt": services.render_prompt(question["prompt"], merge),
                "response_schema": question["response_schema"],
                # The prospect never sees the private side of a question.
                "value": (answer.value if answer is not None else None),
            })
        if questions:
            sections.append({"code": section["code"], "title": section["title"],
                             "questions": questions})
    return {
        "practice": email_layout.branding(session.tenant).display_name,
        "company": session.company.name if session.company_id else "",
        "first_name": session.contact.first_name,
        "sections": sections,
        "answered": answered,
        "of": total,
        "complete": session.state == StrategySession.State.PRECALL_COMPLETE,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def precall_form(request, token: str):
    session = services.session_for_precall_token(token)
    if session is None:
        return JsonResponse(EXPIRED, status=404)
    with tenant_context(session.tenant_id):
        if request.method == "GET":
            return JsonResponse(_payload(session))
        try:
            body = json.loads(request.body or "{}")
        except ValueError:
            return JsonResponse({"detail": "Unreadable request."}, status=400)
        try:
            services.save_answer(
                session, question_key=body.get("question_key", ""),
                value=body.get("value") or {},
                answered_by=StrategyAnswer.AnsweredBy.PROSPECT)
        except services.AnswerInvalid as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)
        payload = _payload(session)
        return JsonResponse({"saved_at": timezone.now().isoformat(),
                             "answered": payload["answered"], "of": payload["of"]})


@csrf_exempt
@require_http_methods(["POST"])
def precall_complete(request, token: str):
    """"I'm done" — which moves the session on, and nothing else. The form stays
    open afterwards: a prospect who remembers something should be able to add it.
    """
    session = services.session_for_precall_token(token)
    if session is None:
        return JsonResponse(EXPIRED, status=404)
    with tenant_context(session.tenant_id):
        if session.state in (StrategySession.State.DRAFT,
                             StrategySession.State.PRECALL_SENT):
            session.state = StrategySession.State.PRECALL_COMPLETE
            session.save(update_fields=["state", "updated_at"])
        from apps.tenancy.models import AuditEvent

        AuditEvent.all_objects.create(
            tenant=session.tenant, verb="strategy.precall_completed",
            target_type="strategy_session", target_id=session.pk, payload={})
        _notify_owner(session)
        return JsonResponse(_payload(session))


def _notify_owner(session):
    """AC-4.3 — "submit; the session owner is notified."

    Internal mail to the practice's own person, direct-to-sent like every other
    internal notice, and in the Outbox because everything that left is.
    """
    owner = session.owner
    if owner is None or not owner.email:
        return None
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from django.utils.html import escape

    name = f"{session.contact.first_name} {session.contact.last_name}".strip()
    company = session.company.name if session.company_id else ""
    payload = _payload(session)
    subject = f"{name} finished the pre-call form"
    lines = [f"{name}{f' at {company}' if company else ''} has completed the pre-call "
             f"form — {payload['answered']} of {payload['of']} answered.",
             "Their answers are on the session, ready for the call."]
    outbox.create_message(
        tenant=session.tenant, producer=OutboxMessage.Producer.PRECALL_COMPLETE,
        to_address=owner.email, subject=subject, body_text="\n\n".join(lines),
        body_html=email_layout.document(
            session.tenant,
            content_html="".join(f"<p>{escape(line)}</p>" for line in lines),
            subject=subject, preheader=lines[0][:140]),
        source_type="strategy_session", source_id=session.pk)
