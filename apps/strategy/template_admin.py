"""More than one template (owner, 2026-09-26).

Duplicate, restore from seed, rename, set default, archive. Every one of them
works on template rows only: **a session renders from its own snapshot**
(FR-4.5, AC-4.12), so nothing here can reach a session already started — not a
rename, not an archive, not a change of default.

Two rules this module keeps:

- **Nothing overwrites.** Restore from seed and Duplicate both make a *new*
  template. A template somebody has edited is theirs.
- **"The default" always means one live template.** Setting a default clears
  the old one in the same transaction, and the default cannot be archived.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

import uuid

from apps.strategy import rewording, seed
from apps.strategy.models import (
    AskWhen, ResponseSchema, StrategyQuestion, StrategySection, StrategyTemplate,
)
from apps.strategy.services import SessionError


def _clean_name(name) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise SessionError("A template needs a name.")
    if len(name) > 200:
        raise SessionError("A template's name is 200 characters at most.")
    return name


def _name_free(name: str, *, exclude=None) -> None:
    taken = StrategyTemplate.objects.filter(name__iexact=name)
    if exclude is not None:
        taken = taken.exclude(pk=exclude.pk)
    if taken.exists():
        raise SessionError(f"There is already a template called “{name}”.", status=409)


def active():
    return StrategyTemplate.objects.filter(archived_at__isnull=True)


def default_template(discipline=seed.DISCIPLINE):
    return active().filter(is_default=True, discipline=discipline).first()


@transaction.atomic
def duplicate(source: StrategyTemplate, *, name) -> StrategyTemplate:
    """A full copy under a new name: every section with its budget, and every
    question with its key and flags — **archived questions included**, still
    archived, so a key spent in the original stays spent in the copy."""
    name = _clean_name(name)
    _name_free(name)
    copy = StrategyTemplate.objects.create(
        tenant=source.tenant, name=name, version=1, discipline=source.discipline,
        is_default=False)
    sections = {}
    for section in StrategySection.objects.filter(template=source):
        sections[section.pk] = StrategySection.objects.create(
            tenant=source.tenant, template=copy, code=section.code, title=section.title,
            position=section.position, time_budget_minutes=section.time_budget_minutes)
    for question in StrategyQuestion.objects.filter(template=source):
        question.pk = None
        question.id = None
        question._state.adding = True
        question.template = copy
        question.section = sections[question.section_id]
        question.save()
    return copy


@transaction.atomic
def restore_from_seed(tenant, *, name, variant="") -> StrategyTemplate:
    """The Operations template exactly as `strategy_session_seed.md` ships it,
    as a new template. Never overwrites. `variant="sixty"` is the 60-minute
    cut (`seed.create_from_seed`)."""
    if variant not in ("", seed.SIXTY_MINUTE):
        raise SessionError("variant is '' or 'sixty'.")
    name = _clean_name(name)
    _name_free(name)
    return seed.create_from_seed(tenant, name=name, variant=variant)


def rename(template: StrategyTemplate, *, name) -> StrategyTemplate:
    name = _clean_name(name)
    _name_free(name, exclude=template)
    template.name = name
    template.save(update_fields=["name", "updated_at"])
    return template


@transaction.atomic
def set_default(template: StrategyTemplate) -> StrategyTemplate:
    if template.archived_at is not None:
        raise SessionError("An archived template cannot be the default. Restore it "
                           "first.")
    # Cleared first: the one-default-per-discipline constraint is checked per
    # statement, and two defaults for a moment is two defaults.
    (StrategyTemplate.objects.filter(discipline=template.discipline, is_default=True)
     .exclude(pk=template.pk).update(is_default=False, updated_at=timezone.now()))
    template.is_default = True
    template.save(update_fields=["is_default", "updated_at"])
    return template


def archive(template: StrategyTemplate) -> StrategyTemplate:
    if template.is_default:
        raise SessionError("This is the practice default. Set another template as "
                           "the default first, then archive this one.")
    template.archived_at = template.archived_at or timezone.now()
    template.save(update_fields=["archived_at", "updated_at"])
    return template


def unarchive(template: StrategyTemplate) -> StrategyTemplate:
    template.archived_at = None
    template.save(update_fields=["archived_at", "updated_at"])
    return template


# ------------------------------------------------ questions and sections
#
# Adding, removing and reordering (owner, 2026-09-26). None of it can reach a
# session: each renders from the snapshot it took at start.

QUESTION_FLAGS = ("must_ask", "is_financial", "has_fractional_note", "ask_if_time")


def _section(template, code) -> StrategySection:
    section = StrategySection.objects.filter(template=template, code=code).first()
    if section is None:
        raise SessionError("That section is not in this template.", status=404)
    return section


def _new_key(template, section) -> str:
    """Never reused: checked against every key the template has ever had,
    archived ones included, because a historical answer resolves by key."""
    while True:
        key = f"{section.code[:40]}_{uuid.uuid4().hex[:8]}"
        if not StrategyQuestion.objects.filter(template=template, key=key).exists():
            return key


@transaction.atomic
def add_question(template, *, section, prompt, response_schema=ResponseSchema.FREE_TEXT,
                 ask_when=AskWhen.LIVE, area="", **flags) -> StrategyQuestion:
    section = _section(template, section)
    prompt = (prompt or "").strip()
    if not prompt:
        raise SessionError("A question needs a prompt.")
    if response_schema not in ResponseSchema.values:
        raise SessionError(f"response_schema is one of {', '.join(ResponseSchema.values)}.")
    if ask_when not in AskWhen.values:
        raise SessionError("ask_when is 'precall' or 'live'.")
    unknown = set(flags) - set(QUESTION_FLAGS)
    if unknown:
        raise SessionError(f"Unknown flag: {', '.join(sorted(unknown))}.")
    key = _new_key(template, section)
    # The same rule a rewording is held to: a new rating is a lead-in to a
    # number, not an essay question (incident, 2026-09-22).
    refusal = rewording.refusal(key, response_schema, prompt)
    if refusal:
        raise SessionError(refusal)
    last = (StrategyQuestion.objects.filter(section=section, deleted_at__isnull=True)
            .order_by("-position").values_list("position", flat=True).first())
    return StrategyQuestion.objects.create(
        tenant=template.tenant, template=template, section=section, key=key,
        prompt=prompt, response_schema=response_schema, ask_when=ask_when,
        area=(area or "").strip()[:80], position=(last + 1) if last is not None else 0,
        **{flag: bool(value) for flag, value in flags.items()})


def remove_question(template, *, key) -> StrategyQuestion:
    """Archived, never deleted: the key stays spent, and every snapshot that
    asked it still does."""
    question = StrategyQuestion.objects.filter(template=template, key=key,
                                               deleted_at__isnull=True).first()
    if question is None:
        raise SessionError("That question is not in this template.", status=404)
    question.deleted_at = timezone.now()
    question.save(update_fields=["deleted_at", "updated_at"])
    return question


@transaction.atomic
def reorder(template, *, section, keys) -> list[str]:
    """Within one section. The list has to name every live question in it,
    once — a partial list would leave the rest in an order nobody chose."""
    section = _section(template, section)
    live = list(StrategyQuestion.objects.filter(section=section, deleted_at__isnull=True))
    if sorted(keys or []) != sorted(q.key for q in live):
        raise SessionError("Send every question in the section, once each, in the "
                           "order you want.")
    by_key = {q.key: q for q in live}
    for position, key in enumerate(keys):
        question = by_key[key]
        if question.position != position:
            question.position = position
            question.save(update_fields=["position", "updated_at"])
    return list(keys)


def set_budget(template, *, section, minutes) -> StrategySection:
    section = _section(template, section)
    if minutes in ("", None):
        minutes = None
    else:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise SessionError("A time budget is a whole number of minutes.") from None
        if not 0 <= minutes <= 240:
            raise SessionError("A time budget is between 0 and 240 minutes.")
    section.time_budget_minutes = minutes
    section.save(update_fields=["time_budget_minutes", "updated_at"])
    return section
