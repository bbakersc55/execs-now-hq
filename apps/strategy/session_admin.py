"""Managing sessions themselves (owner, 2026-09-26): reset the questions while
nobody has been asked them, archive and restore, and — rarely — delete.

**The snapshot records what a real person was asked.** That is why a session's
questions can be reset only while it is a draft that has reached nobody: no
invite, no questions email, no answer from the prospect. After that the
answer is a new session from the template, never a rewritten old one.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.strategy import services
from apps.strategy.models import StrategyAnswer, StrategyMapRow, StrategySession
from apps.strategy.services import SessionError

WHY_FIXED = ("The questions on a session are a record of what a real person was "
             "asked, so they are fixed once it has reached anyone.")


def reset_refusal(session: StrategySession) -> str:
    """Why this session's questions cannot be reset — or "" when they can."""
    if session.archived_at is not None:
        return "This session is archived. Restore it first."
    if session.state != StrategySession.State.DRAFT:
        return (f"{WHY_FIXED} This one is "
                f"“{StrategySession.State(session.state).label.lower()}”.")
    if session.precall_token_hash or session.precall_questions_sent_at:
        return f"{WHY_FIXED} The pre-call questions have already gone to the prospect."
    if StrategyAnswer.objects.filter(
            session=session, answered_by=StrategyAnswer.AnsweredBy.PROSPECT).exists():
        return f"{WHY_FIXED} The prospect has already answered some of them."
    return ""


def _prompts(snapshot) -> dict:
    return {q["key"]: q["prompt"] for _s, q in services.questions_in(snapshot)}


def compare(session: StrategySession, snapshot: dict) -> dict:
    """What replacing this session's questions with `snapshot` would change,
    counted — so the confirm can say it in numbers rather than "are you sure"."""
    now, then = _prompts(session.template_snapshot), _prompts(snapshot)
    return {
        "source": (snapshot.get("template") or {}).get("name", ""),
        "changed_wording": sorted(k for k in now.keys() & then.keys()
                                  if now[k] != then[k]),
        "added": sorted(then.keys() - now.keys()),
        "removed": sorted(now.keys() - then.keys()),
    }


def seed_discipline(session) -> str:
    return (session.template_snapshot.get("template") or {}).get("discipline") \
        or (session.template.discipline if session.template_id else "operations")


def _check_template(template):
    if template.archived_at is not None:
        raise SessionError(f"“{template.name}” is archived. Restore it, or choose "
                           f"another template.", status=409)
    if template.format == template.Format.V3:
        from apps.strategy import builder

        missing = builder.readiness(template)
        if missing:
            raise SessionError(f"“{template.name}” is not ready to run. "
                               + " ".join(missing), status=409)


def _replace(session, snapshot, template) -> StrategySession:
    refusal = reset_refusal(session)
    if refusal:
        raise SessionError(refusal, status=409)
    session.template = template
    session.template_snapshot = snapshot
    session.current_section = ""
    session.current_section_at = None
    session.save(update_fields=["template", "template_snapshot", "current_section",
                                "current_section_at", "updated_at"])
    return session


@transaction.atomic
def reset_questions(session: StrategySession, template) -> StrategySession:
    """"Reload questions from template": re-snapshot from `template` as it
    stands today. Refused unless `reset_refusal` is empty."""
    _check_template(template)
    return _replace(session, services.snapshot_of(template), template)


@transaction.atomic
def restore_seed(session: StrategySession) -> StrategySession:
    """"Restore seed wording": the seed's questions for this session's
    discipline — not any template's edited version of them. The session no
    longer points at a template, because its questions are no template's."""
    from apps.strategy import seed

    # The seed is the Operations template. A session started from a builder
    # template (P3) reloads from its own template instead.
    if services.is_v3(session):
        raise SessionError("This session's questions come from a template made in "
                           "the builder. Reload them from that template instead.",
                           status=409)
    return _replace(session, seed.seed_snapshot(seed_discipline(session)), None)


def archive(session: StrategySession) -> StrategySession:
    session.archived_at = session.archived_at or timezone.now()
    session.save(update_fields=["archived_at", "updated_at"])
    return session


def unarchive(session: StrategySession) -> StrategySession:
    session.archived_at = None
    session.save(update_fields=["archived_at", "updated_at"])
    return session


def delete_refusal(session: StrategySession) -> str:
    if session.archived_at is None:
        return "Archive the session first. Permanent delete is only from Archived."
    if (session.state == StrategySession.State.CONVERTED or session.converted_at
            or _linked_work(session)):
        return ("This session was converted to work, and its goals, projects and "
                "tasks link back to its strategy map. It can be archived, not deleted.")
    return ""


def _linked_work(session) -> bool:
    from apps.crm.models import Task
    from apps.work.models import Goal, Project

    rows = StrategyMapRow.objects.filter(session=session).values("pk")
    return (Goal.objects.filter(source_map_row__in=rows).exists()
            or Project.objects.filter(source_map_row__in=rows).exists()
            or Task.objects.filter(source_map_row__in=rows).exists())


@transaction.atomic
def delete(session: StrategySession) -> dict:
    """Gone, with its answers, map, prep and notes. Returns what the audit
    event keeps of it, because afterwards that is all there is."""
    refusal = delete_refusal(session)
    if refusal:
        raise SessionError(refusal, status=409)
    record = {
        "contact": services._contact_name(session.contact),
        "company": session.company.name if session.company_id else "",
        "state": session.state,
        "template": (session.template_snapshot.get("template") or {}).get("name", ""),
        "created_at": session.created_at.isoformat(),
        "answers": StrategyAnswer.objects.filter(session=session).count(),
        "map_rows": StrategyMapRow.objects.filter(session=session).count(),
    }
    session.delete()
    return record
