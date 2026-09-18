"""What Module 4 puts on the wire.

The one rule that is load-bearing here is **matrix 10.8**: a VA must not receive
the §9 investment questions or their answers *in the payload*. Hiding them on a
screen is not the same thing, so the filtering happens in `represent_session`,
once, and every caller inherits it.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.strategy import services
from apps.strategy.models import StrategyAnswer, StrategyMapRow, StrategySession


def _contact(contact):
    if contact is None:
        return None
    return {"id": str(contact.pk),
            "name": f"{contact.first_name} {contact.last_name}".strip()}


def represent_map_row(row) -> dict:
    return {
        "id": str(row.pk),
        "position": row.position,
        "bottleneck": row.bottleneck,
        "root_cause": row.root_cause,
        "the_fix": row.the_fix,
        "owner_text": row.owner_text,
        "horizon": row.horizon,
        "measurable": row.measurable,
        "mechanics_note": row.mechanics_note,
        "state": row.state,
        "converted_to": row.converted_to,
        "from_ai": row.ai_call_id is not None,
    }


def represent_answer(answer) -> dict:
    return {
        "question_key": answer.question_key,
        "value": answer.value,
        "fractional_note": answer.fractional_note,
        "answered_by": answer.answered_by,
        "updated_at": answer.updated_at.isoformat(),
    }


def represent_session(session, *, include_financial=True, full=False) -> dict:
    """`include_financial=False` is matrix 10.8, applied to questions *and*
    answers — a VA's payload does not contain the numbers at all."""
    merge = services.merge_context(session)
    payload = {
        "id": str(session.pk),
        "state": session.state,
        "contact": _contact(session.contact),
        "company": ({"id": str(session.company_id), "name": session.company.name}
                    if session.company_id else None),
        "visionary": _contact(session.visionary_contact),
        "integrator": _contact(session.integrator_contact),
        "owner": ((session.owner.full_name or "").strip() or session.owner.email)
        if session.owner_id else "",
        "scheduled_at": session.scheduled_at.isoformat() if session.scheduled_at else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        # The seed's own pacing, totalled: what "on time" means for this call.
        "budget_minutes": sum(s.get("time_budget_minutes") or 0
                              for s in session.template_snapshot.get("sections", [])),
        "precall_sent": bool(session.precall_token_hash),
        "precall_expires_at": (session.precall_expires_at.isoformat()
                               if session.precall_expires_at else None),
        "mirror": {"goal": session.mirror_goal, "unlocks": session.mirror_unlocks},
        "proposed_mirror": {"goal": session.proposed_mirror_goal,
                            "unlocks": session.proposed_mirror_unlocks},
        "pdf_include_flags": session.pdf_include_flags,
        "has_pdf": session.pdf_file_id is not None,
        "converted_at": session.converted_at.isoformat() if session.converted_at else None,
        "created_at": session.created_at.isoformat(),
    }
    if not full:
        return payload

    answers = services.answers_of(session)
    allowed = set()
    sections = []
    for section in session.template_snapshot.get("sections", []):
        questions = []
        for question in section.get("questions", []):
            if not include_financial and question.get("is_financial"):
                continue
            allowed.add(question["key"])
            questions.append({**question,
                              "prompt": services.render_prompt(question["prompt"], merge),
                              "prompt_template": question["prompt"]})
        sections.append({**section, "questions": questions})
    payload["sections"] = sections
    payload["answers"] = [represent_answer(a) for a in answers.values()
                          if a.question_key in allowed]
    payload["six_key_components"] = services.six_key_components(session)
    payload["must_ask"] = services.must_ask_outstanding(session)
    payload["map_rows"] = [represent_map_row(row) for row in
                           StrategyMapRow.objects.filter(session=session)
                           .order_by("position", "created_at")]
    return payload


class SessionCreateSerializer(serializers.Serializer):
    contact = serializers.UUIDField()
    company = serializers.UUIDField(required=False, allow_null=True)
    template = serializers.UUIDField(required=False, allow_null=True)
    visionary_contact = serializers.UUIDField(required=False, allow_null=True)
    integrator_contact = serializers.UUIDField(required=False, allow_null=True)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)


class AnswerSerializer(serializers.Serializer):
    question_key = serializers.CharField(max_length=80)
    value = serializers.JSONField()
    fractional_note = serializers.CharField(required=False, allow_blank=True)


class MapRowSerializer(serializers.Serializer):
    bottleneck = serializers.CharField(required=False, allow_blank=True)
    root_cause = serializers.CharField(required=False, allow_blank=True)
    the_fix = serializers.CharField(required=False, allow_blank=True)
    owner_text = serializers.CharField(required=False, allow_blank=True, max_length=200)
    horizon = serializers.ChoiceField(choices=[30, 60, 90], required=False,
                                      allow_null=True)
    measurable = serializers.CharField(required=False, allow_blank=True, max_length=255)
    mechanics_note = serializers.CharField(required=False, allow_blank=True)
    position = serializers.IntegerField(required=False, min_value=0)


ANSWER_FIELDS = ("question_key", "value", "fractional_note")
SESSION_PATCH_FIELDS = ("scheduled_at", "visionary_contact", "integrator_contact",
                        "mirror_goal", "mirror_unlocks", "state")
