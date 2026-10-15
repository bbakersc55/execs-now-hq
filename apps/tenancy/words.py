"""What a practice calls its goals, projects, tasks and steps (Melissa's
feedback, 2026-10-15).

Each practice names the four levels of its work itself, singular and plural.
The words show wherever the practice and its portal read them: screens,
read-only lines, Activity, digests, emails and PDFs. They are never applied to
the platform owner's pages, the code, the API's field names, or stored data:
changing a word changes what is shown from then on and nothing else.

The frontend twin is `frontend/src/lib/words.ts`; the defaults must match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The four levels, in the order Settings lists them.
KINDS = ("goal", "project", "task", "step")

DEFAULTS: dict[str, tuple[str, str]] = {
    "goal": ("goal", "goals"),
    "project": ("project", "projects"),
    "task": ("task", "tasks"),
    "step": ("step", "steps"),
}

MAX_LENGTH = 30
_ALLOWED = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")


class WordsInvalid(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("Each word is one to three words of letters, at most "
                         f"{MAX_LENGTH} characters.")
        self.errors = errors


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _norm(word: str) -> str:
    """Lower case for the middle of a sentence, except a word with a capital
    after its first letter ("OKR", "eNPS"), which is kept as typed."""
    word = " ".join(word.split())
    return word if any(ch.isupper() for ch in word[1:]) else word.lower()


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:]


@dataclass(frozen=True)
class Words:
    """The practice's words as a sentence's middle reads them, with the forms a sentence
    needs. `w.task`, `w.tasks`, `w.Task`, `w.Tasks`, `w.a_task` ("an action")."""

    goal: str
    goals: str
    project: str
    projects: str
    task: str
    tasks: str
    step: str
    steps: str

    def __getattr__(self, name: str) -> str:
        # Capitalised forms (`Task`, `Goals`) and "a"/"an" forms (`a_task`).
        if name.startswith("a_") and name[2:] in KINDS:
            word = object.__getattribute__(self, name[2:])
            return f"{_article(word)} {word}"
        lower = name[:1].lower() + name[1:]
        if lower != name and lower in self.__dataclass_fields__:
            return _cap(object.__getattribute__(self, lower))
        raise AttributeError(name)

    def of(self, kind: str, plural: bool = False, capital: bool = False) -> str:
        """The word for `kind` (goal, project, task, step), as the place needs."""
        word = getattr(self, kind + ("s" if plural else ""))
        return _cap(word) if capital else word

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {kind: {"singular": getattr(self, kind), "plural": getattr(self, kind + "s")}
                for kind in KINDS}


DEFAULT = Words(**{key: value for kind, (one, many) in DEFAULTS.items()
                   for key, value in ((kind, one), (kind + "s", many))})


def of(tenant) -> Words:
    """The words of `tenant`; the defaults with no practice (the platform
    owner's pages) or for any word it has not set."""
    stored = (getattr(tenant, "work_words", None) or {}) if tenant is not None else {}
    values = {}
    for kind, (one, many) in DEFAULTS.items():
        pair = stored.get(kind)
        ok = isinstance(pair, (list, tuple)) and len(pair) == 2 and all(
            isinstance(x, str) and x.strip() for x in pair)
        values[kind], values[kind + "s"] = (
            (_norm(pair[0]), _norm(pair[1])) if ok else (one, many))
    return Words(**values)


def for_request(request) -> Words:
    membership = getattr(request, "membership", None)
    return of(membership.tenant if membership is not None else getattr(request, "tenant", None))


def save(tenant, *, actor, data: dict) -> Words:
    """Settings → Branding → Wording. `data` is {kind: {"singular": .., "plural": ..}};
    an empty pair is the default. Audited. Changes nothing but the words."""
    from .models import AuditEvent

    errors: dict[str, str] = {}
    stored: dict[str, list[str]] = {}
    for kind in KINDS:
        pair = data.get(kind) or {}
        one = _norm(str(pair.get("singular", "")))
        many = _norm(str(pair.get("plural", "")))
        if not one and not many:
            continue
        for label, word in (("singular", one), ("plural", many)):
            if not word or len(word) > MAX_LENGTH or not _ALLOWED.match(word) \
                    or len(word.split()) > 3:
                errors[f"{kind}.{label}"] = (
                    f"One to three words of letters, at most {MAX_LENGTH} characters.")
        if (one, many) != DEFAULTS[kind]:
            stored[kind] = [one, many]
    if errors:
        raise WordsInvalid(errors)
    before = tenant.work_words or {}
    if stored != before:
        tenant.work_words = stored
        tenant.save(update_fields=["work_words"])
        AuditEvent.all_objects.create(
            tenant_id=tenant.pk, actor=actor, verb="practice.words_changed",
            target_type="tenant", target_id=tenant.pk,
            payload={"from": before, "to": stored})
    return of(tenant)
