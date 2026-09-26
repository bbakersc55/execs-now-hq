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

from apps.strategy import seed
from apps.strategy.models import StrategyQuestion, StrategySection, StrategyTemplate
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
def restore_from_seed(tenant, *, name) -> StrategyTemplate:
    """The Operations template exactly as `strategy_session_seed.md` ships it,
    as a new template. Never overwrites."""
    name = _clean_name(name)
    _name_free(name)
    return seed.create_from_seed(tenant, name=name)


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
