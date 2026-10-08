"""The template builder (P3, 2026-10-03): a practice's own v3 templates.

A v3 template is eight parts in the session's order. Each section carries a
`kind`, which is what it does, and — for the parts the rest of the module
already knows — the `code` that code is keyed on, so the shared engine (the
scores, the tray, the PDF context, the pros and cons) reads a v3 session
without being rewritten.

Three rules this module keeps:

- **It touches v3 templates only.** Every verb refuses a classic or focused
  template: those keep today's editor and today's behavior, and none of the
  builder's columns can ever be set on one.
- **Nothing here can reach a session.** A session renders from the snapshot it
  took when it was created (FR-4.5), as with every other template edit.
- **Each kind asks one shape of question.** A rated item is a statement scored
  1–10, a diagnostic question is said / cause / tried, and so on. The builder
  sets the shape from the section; the practice writes the words.

`docs/p3_strategy_templates_session_v3.md` is the spec.
"""

from __future__ import annotations

import re
import uuid

from django.db import transaction
from django.utils import timezone

from apps.strategy import rewording, seed, services, template_admin
from apps.strategy.models import (
    AskWhen, ResponseSchema, StrategyQuestion, StrategySection, StrategyTemplate,
)
from apps.strategy.services import SessionError

V3 = StrategyTemplate.Format.V3
SNAPSHOT_VERSION = 2

PRECALL, RATINGS, DIAGNOSTIC, MIRROR = "precall", "ratings", "diagnostic", "mirror"
MAP, VALUES, PATHS, SCOPE = "map", "values", "paths", "scope"
#: A section the practice adds (P3 part two §3): captured and nothing else,
#: unless the practice owner says it prints.
CUSTOM = "custom"

#: The eight parts, in session order: (kind, code, title, live minutes).
#: 5 / 15 / 10 / 10 / 5 / 5 / 5 = 55 minutes on the call.
PARTS = (
    (PRECALL, "snapshot", "Before the call", None),
    (RATINGS, "six_key_components", "Ratings", 5),
    (DIAGNOSTIC, "diagnostic", "Diagnostic", 15),
    (MIRROR, "mirror", "The mirror and where they want to go", 10),
    (MAP, "strategy_map", "Strategy Map", 10),
    (VALUES, "what_they_value", "What they value", 5),
    (PATHS, "two_paths", "Two paths", 5),
    (SCOPE, "scope_agreement", "Scope", 5),
)
KINDS = tuple(part[0] for part in PARTS)

#: The only part a template can switch off in the first cut (D1).
OPTIONAL_KINDS = (VALUES,)

#: What a question in each kind is: its shape, when it is asked, how many the
#: section holds, and the flags the builder sets rather than the practice.
RULES = {
    PRECALL: {"schema": ResponseSchema.FREE_TEXT, "ask_when": AskWhen.PRECALL, "most": 20,
              "fixed": {"has_fractional_note": True}},
    RATINGS: {"schema": ResponseSchema.RATING_1_10, "ask_when": AskWhen.LIVE, "most": 8,
              "needs_label": True, "fixed": {}},
    DIAGNOSTIC: {"schema": ResponseSchema.DIAGNOSTIC_TRIPLE, "ask_when": AskWhen.LIVE,
                 "most": 8,
                 "fixed": {"is_diagnostic_fallback": True, "has_fractional_note": True}},
    MIRROR: {"schema": ResponseSchema.FREE_TEXT, "ask_when": AskWhen.LIVE, "most": 5,
             "fixed": {}},
    VALUES: {"schema": ResponseSchema.VALUE_PAIR, "ask_when": AskWhen.LIVE, "most": 5,
             "fixed": {}},
    PATHS: {"schema": ResponseSchema.PATH_REACTION, "ask_when": AskWhen.LIVE, "most": 2,
            "exactly": 2, "fixed": {}},
    SCOPE: {"schema": ResponseSchema.AGREED_NOTE, "ask_when": AskWhen.LIVE, "most": 12,
            "fixed": {}},
    # The one kind where the practice chooses the shape, per question, from
    # three (part two D4). No rating, value, path or money item: those belong
    # to the parts that know what to do with them.
    CUSTOM: {"schema": ResponseSchema.FREE_TEXT, "ask_when": AskWhen.LIVE, "most": 12,
             "schemas": (ResponseSchema.FREE_TEXT, ResponseSchema.DIAGNOSTIC_TRIPLE,
                         ResponseSchema.AGREED_NOTE),
             "fixed": {"has_fractional_note": True}},
}

#: Part two D5, and §6.2: what the two-page document has room for.
CUSTOM_MOST = 8
PRINTING_MOST = 2
PRINTING_QUESTIONS_MOST = 4

#: A new template is not blank inside the fixed-shape parts: the session and
#: the PDF need two paths and something to agree. Neutral words, no trade.
STARTER = {
    PATHS: (("Path A — Continue to run it yourselves", {}),
            ("Path B — Work with us", {})),
    SCOPE: (("Scope — what is in the first 90 days", {}),
            ("Start date", {}),
            ("Investment discussed", {"is_financial": True})),
}

MIN_RATED = 2
CHIPS_MOST = 3
DIAGNOSTIC_SIZE = (1, 8)

#: The templated portions (spec §2.3): key → (default, most characters).
TEXTS = {
    "advisor_role": ("advisor", 80),
    "rating_scale": (rewording.RATING_SCALE_MEANING, 160),
    "path_a_title": ("Continue to run it yourself", 80),
    "path_b_title": ("Work with {Practice}", 80),
}
#: Two lines each, under the path's title on the PDF's decision page.
POINTS = {
    "path_a_points": ("Use the map {Practice} handed you",
                      "Your team carries the work alongside the day job"),
    "path_b_points": ("{Practice} works the map with you, in priority order",
                      "Alongside your team, not a report handed over"),
}
POINT_MOST = 160

#: Every merge field a prompt or a templated text may use.
MERGE_FIELDS = frozenset(services.MISSING_NAME) | {"Practice"}


def default_settings() -> dict:
    return {**{key: default for key, (default, _most) in TEXTS.items()},
            **{key: list(lines) for key, lines in POINTS.items()},
            "diagnostic_size": 3}


# ------------------------------------------------------------------ guards

def is_v3(template) -> bool:
    return template.format == V3


def require_v3(template) -> None:
    if not is_v3(template):
        raise SessionError(f"“{template.name}” is not a builder template. It is edited "
                           "in the template editor, as before.", status=409)


def unknown_merge_fields(text: str) -> list[str]:
    return sorted({field for field in services.MERGE_FIELD.findall(text or "")
                   if field not in MERGE_FIELDS})


def _check_merge_fields(text: str) -> None:
    unknown = unknown_merge_fields(text)
    if unknown:
        raise SessionError(
            "There is no merge field called " + ", ".join(f"{{{f}}}" for f in unknown)
            + ". The ones you can use: "
            + ", ".join(f"{{{f}}}" for f in sorted(MERGE_FIELDS)) + ".")


def _sections(template, *, removed=False):
    sections = StrategySection.objects.filter(template=template)
    if not removed:
        sections = sections.filter(deleted_at__isnull=True)
    return sections.order_by("position", "created_at")


def _section(template, code, *, removed=False) -> StrategySection:
    section = _sections(template, removed=removed).filter(code=code).first()
    if section is None:
        raise SessionError("That section is not in this template.", status=404)
    return section


def _live_questions(section):
    return StrategyQuestion.objects.filter(section=section, deleted_at__isnull=True)


# ------------------------------------------------------------------ creating

@transaction.atomic
def create_blank(tenant, *, name) -> StrategyTemplate:
    """The eight parts laid out, the two paths and three scope items in
    neutral words, and no question anywhere else (D2)."""
    name = template_admin._clean_name(name)
    template_admin._name_free(name)
    template = StrategyTemplate.objects.create(
        tenant=tenant, name=name, version=1, discipline=seed.DISCIPLINE,
        format=V3, is_default=False, settings=default_settings())
    for position, (kind, code, title, budget) in enumerate(PARTS):
        section = StrategySection.objects.create(
            tenant=tenant, template=template, code=code, kind=kind, title=title,
            position=position, time_budget_minutes=budget)
        for q_position, (prompt, flags) in enumerate(STARTER.get(kind, ())):
            rule = RULES[kind]
            StrategyQuestion.objects.create(
                tenant=tenant, template=template, section=section,
                key=template_admin._new_key(template, section), prompt=prompt,
                response_schema=rule["schema"], ask_when=rule["ask_when"],
                position=q_position, **{**rule["fixed"], **flags})
    return template


@transaction.atomic
def duplicate(source: StrategyTemplate, *, name) -> StrategyTemplate:
    """A full copy of a v3 template: its settings, every section (removed ones
    still removed) and every question with its key (archived ones still
    archived, so a spent key stays spent)."""
    require_v3(source)
    name = template_admin._clean_name(name)
    template_admin._name_free(name)
    copy = StrategyTemplate.objects.create(
        tenant=source.tenant, name=name, version=1, discipline=source.discipline,
        format=V3, is_default=False, settings=dict(source.settings or {}))
    sections = {}
    for section in StrategySection.objects.filter(template=source):
        sections[section.pk] = StrategySection.objects.create(
            tenant=source.tenant, template=copy, code=section.code, kind=section.kind,
            title=section.title, position=section.position, intro=section.intro,
            time_budget_minutes=section.time_budget_minutes,
            show_in_pdf=section.show_in_pdf, deleted_at=section.deleted_at)
    for question in StrategyQuestion.objects.filter(template=source):
        question.pk = None
        question.id = None
        question._state.adding = True
        question.template = copy
        question.section = sections[question.section_id]
        question.save()
    return copy


# ------------------------------------------------------------------ sections

def _renumber(sections) -> None:
    for position, section in enumerate(sections):
        if section.position != position:
            section.position = position
            section.save(update_fields=["position", "updated_at"])


@transaction.atomic
def add_section(template, *, title, time_budget_minutes=None, after=None) -> StrategySection:
    """A custom section among the parts asked on the call: after the one
    named, or last. It starts empty, and it does not print (part two D6)."""
    require_v3(template)
    title = " ".join(str(title or "").split())
    if not title:
        raise SessionError("A section needs a title.")
    if len(title) > 255:
        raise SessionError("A section's title is 255 characters at most.")
    if _sections(template).filter(kind=CUSTOM).count() >= CUSTOM_MOST:
        raise SessionError(f"A template holds {CUSTOM_MOST} sections of your own at "
                           "most. Remove one before adding another.")
    every = list(_sections(template, removed=True))
    at = len(every)
    if after not in (None, ""):
        # The part before the call is first by being named here, never moved.
        index = next((i for i, section in enumerate(every)
                      if section.code == after and section.deleted_at is None), None)
        if index is None:
            raise SessionError("That section is not in this template.", status=404)
        at = index + 1
    while True:
        code = f"{CUSTOM}_{uuid.uuid4().hex[:8]}"
        if not StrategySection.objects.filter(template=template, code=code).exists():
            break
    section = StrategySection.objects.create(
        tenant=template.tenant, template=template, code=code, kind=CUSTOM, title=title,
        position=len(every) + 1, time_budget_minutes=None)
    every.insert(at, section)
    _renumber(every)
    if time_budget_minutes not in (None, ""):
        section = template_admin.set_budget(template, section=code,
                                            minutes=time_budget_minutes)
    return section


@transaction.atomic
def move_section(template, *, code, by) -> StrategySection:
    """One place up or down among the sections asked on the call. The part
    before the call is not on the call, and stays first (part two §1.6)."""
    require_v3(template)
    section = _section(template, code)
    if by not in (-1, 1):
        raise SessionError("by is -1 (up) or 1 (down).")
    if section.kind == PRECALL:
        raise SessionError("The part before the call stays first: it is not on the call.")
    every = list(_sections(template, removed=True))
    movable = [i for i, other in enumerate(every)
               if other.deleted_at is None and other.kind != PRECALL]
    here = next(i for i in movable if every[i].pk == section.pk)
    place = movable.index(here) + by
    if not 0 <= place < len(movable):
        raise SessionError(f"“{section.title}” is already "
                           f"{'first' if by < 0 else 'last'} on the call.")
    there = movable[place]
    every[here], every[there] = every[there], every[here]
    _renumber(every)
    return section


def _check_printing(template, section, *, questions) -> None:
    if section.kind != CUSTOM:
        raise SessionError("Only a section of your own is switched on or off the "
                           "document. The eight parts print as they always have.")
    printing = _sections(template).filter(show_in_pdf=True).exclude(pk=section.pk).count()
    if printing >= PRINTING_MOST:
        raise SessionError(f"The document has room for {PRINTING_MOST} sections of your "
                           "own. Take one off before printing another.")
    if questions > PRINTING_QUESTIONS_MOST:
        raise SessionError(
            f"The document has room for {PRINTING_QUESTIONS_MOST} questions from a "
            f"section; “{section.title}” has {questions}.")


def update_section(template, *, code, title=None, time_budget_minutes=...,
                   show_in_pdf=None) -> StrategySection:
    require_v3(template)
    section = _section(template, code)
    if show_in_pdf is not None:
        if not isinstance(show_in_pdf, bool):
            raise SessionError("show_in_pdf is true or false.")
        if show_in_pdf:
            _check_printing(template, section,
                            questions=_live_questions(section).count())
        elif section.kind != CUSTOM:
            _check_printing(template, section, questions=0)
        section.show_in_pdf = show_in_pdf
        section.save(update_fields=["show_in_pdf", "updated_at"])
    if title is not None:
        title = " ".join(str(title).split())
        if not title:
            raise SessionError("A section needs a title.")
        if len(title) > 255:
            raise SessionError("A section's title is 255 characters at most.")
        section.title = title
        section.save(update_fields=["title", "updated_at"])
    if time_budget_minutes is not ...:
        if section.kind == PRECALL:
            raise SessionError("The part before the call has no time budget.")
        section = template_admin.set_budget(template, section=code,
                                            minutes=time_budget_minutes)
    return section


def set_included(template, *, kind=None, included: bool, code=None) -> StrategySection:
    """Switch an optional part off or back on. Off is a removal that keeps the
    row: its code and its questions' keys stay spent, and switching it back on
    brings its questions back as they were. "What they value" is named by its
    kind, as before; a section of the practice's own by its code."""
    require_v3(template)
    if code:
        section = _sections(template, removed=True).filter(code=code).first()
        if section is None:
            raise SessionError("That section is not in this template.", status=404)
        if section.kind != CUSTOM and section.kind not in OPTIONAL_KINDS:
            raise SessionError(f"“{section.title}” cannot be taken out of a template.")
        if included and section.deleted_at is not None and section.kind == CUSTOM:
            if _sections(template).filter(kind=CUSTOM).count() >= CUSTOM_MOST:
                raise SessionError(f"A template holds {CUSTOM_MOST} sections of your "
                                   "own at most. Remove one before putting this back.")
            if section.show_in_pdf:
                _check_printing(template, section,
                                questions=_live_questions(section).count())
    elif kind not in OPTIONAL_KINDS:
        raise SessionError("Only “What they value” and sections of your own can be "
                           "taken out of a template.")
    else:
        section = _sections(template, removed=True).filter(kind=kind).first()
    if section is None:
        raise SessionError("That section is not in this template.", status=404)
    section.deleted_at = None if included else (section.deleted_at or timezone.now())
    section.save(update_fields=["deleted_at", "updated_at"])
    return section


# ----------------------------------------------------------------- questions

def _clean_label(label) -> str:
    label = " ".join(str(label or "").split())
    if len(label) > 60:
        raise SessionError("A label is 60 characters at most.")
    return label


def _clean_prompt(question_key, schema, prompt) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise SessionError("A question needs a prompt.")
    _check_merge_fields(prompt)
    # A rated item is a statement of a line, not an open question (incident,
    # 2026-09-22): the same rule the editor and prep are held to.
    refusal = rewording.refusal(question_key, schema, prompt)
    if refusal:
        raise SessionError(refusal)
    return prompt


def _check_chips(template, *, adding: StrategyQuestion | None = None) -> None:
    chips = StrategyQuestion.objects.filter(template=template, pdf_chip=True,
                                            deleted_at__isnull=True,
                                            section__deleted_at__isnull=True)
    if adding is not None:
        chips = chips.exclude(pk=adding.pk)
    if chips.count() >= CHIPS_MOST:
        raise SessionError(f"The PDF header shows {CHIPS_MOST} answers at most. Take one "
                           "off before adding another.")


@transaction.atomic
def add_question(template, *, section, prompt, label="", pdf_chip=False,
                 is_financial=False, must_ask=False, observation=False,
                 response_schema=None) -> StrategyQuestion:
    require_v3(template)
    section = _section(template, section)
    rule = RULES.get(section.kind)
    if rule is None:
        raise SessionError(f"“{section.title}” holds no questions of its own.")
    if rule.get("exactly"):
        raise SessionError("There are always two paths. Reword them; they cannot be "
                           "added to or removed.")
    live = _live_questions(section)
    if live.count() >= rule["most"]:
        raise SessionError(f"“{section.title}” holds {rule['most']} at most. Remove one "
                           "before adding another.")
    if section.show_in_pdf and live.count() >= PRINTING_QUESTIONS_MOST:
        raise SessionError(
            f"“{section.title}” prints on the document, which has room for "
            f"{PRINTING_QUESTIONS_MOST} of its questions. Take it off the document "
            "before adding another.")
    schema = rule["schema"]
    # Only a section of the practice's own has a choice; one of the eight
    # parts gives its questions its own shape whatever is asked for.
    if "schemas" in rule and response_schema not in (None, "", schema):
        if response_schema not in rule["schemas"]:
            raise SessionError("A section of your own takes a written answer, said / "
                               "cause / tried, or agreed with a note.")
        schema = response_schema
    key = template_admin._new_key(template, section)
    prompt = _clean_prompt(key, schema, prompt)
    label = _clean_label(label)
    if rule.get("needs_label") and not label:
        raise SessionError("A rated item needs a short label: it is what the chart "
                           "and the diagnostic call it.")
    flags = dict(rule["fixed"])
    if pdf_chip:
        if section.kind != PRECALL:
            raise SessionError("Only a question asked before the call can show in the "
                               "PDF header.")
        if not label:
            raise SessionError("An answer shown in the PDF header needs a short label.")
        _check_chips(template)
        flags["pdf_chip"] = True
    if is_financial:
        if section.kind != SCOPE:
            raise SessionError("Only a scope item can be marked as money.")
        flags["is_financial"] = True
    if must_ask:
        if rule["ask_when"] != AskWhen.LIVE or section.kind == RATINGS:
            raise SessionError("Only a question asked in the call can be a must-ask.")
        flags["must_ask"] = True
    # The advisor's own observation: never asked aloud, and off the PDF, the
    # emails and prep unless its flag is on (FR-4.17). Set by an example
    # (`examples.py`); the builder's API does not offer it.
    if observation:
        if section.kind != MIRROR:
            raise SessionError("Only a question in the mirror's section can be your "
                               "own observation.")
        flags["is_fractional_observation"] = True
    last = live.order_by("-position").values_list("position", flat=True).first()
    return StrategyQuestion.objects.create(
        tenant=template.tenant, template=template, section=section, key=key,
        prompt=prompt, label=label, response_schema=schema,
        ask_when=rule["ask_when"], position=(last + 1) if last is not None else 0,
        **flags)


# ------------------------------------------------------------ paste several

#: "Paste several" (P3 §9.5): one question per line, from the document a
#: practice arrives with.
PASTE_MOST = 50
PASTE_LINE_MOST = 500
#: A list marker at the start of a line — "1.", "2)", "-", "•" — is the
#: document's, not the question's.
_LIST_MARKER = re.compile(r"^\s*(?:[-*•·▪◦–—]+|\(?\d{1,3}[.)])\s+")
#: "Plan — Our plan is written down.": a rated item's label is what comes
#: before the dash or colon.
_LABEL_BREAK = re.compile(r"\s+[—–-]\s+|:\s+")


def _same(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def paste_lines(text) -> list[str]:
    """What was pasted, as lines: blank ones dropped, list markers taken off."""
    if isinstance(text, (list, tuple)):
        text = "\n".join(str(line) for line in text)
    if not isinstance(text, str):
        raise SessionError("Paste the questions as text, one to a line.")
    lines = [" ".join(_LIST_MARKER.sub("", line).split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise SessionError("There is nothing to add: paste one question to a line.")
    if len(lines) > PASTE_MOST:
        raise SessionError(f"That is {len(lines)} lines. Paste {PASTE_MOST} at most at "
                           "a time.")
    return lines


def paste(template, *, section, text, confirmed=None) -> dict:
    """Several questions into one part, in the order pasted, each through
    `add_question` so that nothing gets in this way that could not get in one
    at a time.

    **Nothing is added unless `confirmed` is the list that was shown back**:
    without it this is the list, with each refused line and why; with it, the
    lines are added only if what would be added is still exactly that list
    (the template may have changed since it was shown). A refused line never
    stops the others.
    """
    require_v3(template)
    part = _section(template, section)
    rule = RULES.get(part.kind)
    if rule is None or rule.get("exactly"):
        raise SessionError(f"“{part.title}” does not take a pasted list.")
    lines = paste_lines(text)
    held = {_same(prompt) for prompt in
            _live_questions(part).values_list("prompt", flat=True)}
    shown, added = [], []
    with transaction.atomic():
        for line in lines:
            label = ""
            if rule.get("needs_label"):
                pieces = _LABEL_BREAK.split(line, 1)
                label = pieces[0] if len(pieces) == 2 else ""
            entry = {"prompt": line, "label": label, "ok": False, "why": ""}
            shown.append(entry)
            if len(line) > PASTE_LINE_MOST:
                entry["why"] = (f"This line is {len(line)} characters; {PASTE_LINE_MOST} "
                                "is the most. Is it more than one question?")
                continue
            if _same(line) in held:
                entry["why"] = "This is already in this part, word for word."
                continue
            if rule.get("needs_label") and not label:
                entry["why"] = ("A rated item needs a short label. Start the line with "
                                "it, as in “Plan — Our plan is written down.”")
                continue
            try:
                with transaction.atomic():
                    question = add_question(template, section=part.code, prompt=line,
                                            label=label)
            except SessionError as exc:
                entry["why"] = str(exc)
                continue
            entry["ok"] = True
            held.add(_same(line))
            added.append(question)
        wanted = [entry["prompt"] for entry in shown if entry["ok"]]
        if confirmed is None or list(confirmed) != wanted or not added:
            transaction.set_rollback(True)
            added = []
    return {"section": part.code, "lines": shown, "adding": len(wanted),
            "added": [question.key for question in added],
            "stale": confirmed is not None and list(confirmed) != wanted}


EDITABLE = ("prompt", "label", "pdf_chip", "is_financial", "must_ask")


@transaction.atomic
def edit_question(template, *, key, **changes) -> StrategyQuestion:
    require_v3(template)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise SessionError(f"Not editable here: {', '.join(sorted(unknown))}.")
    question = (StrategyQuestion.objects.select_related("section")
                .filter(template=template, key=key, deleted_at__isnull=True,
                        section__deleted_at__isnull=True).first())
    if question is None:
        raise SessionError("That question is not in this template.", status=404)
    section, rule = question.section, RULES[question.section.kind]
    if "prompt" in changes:
        question.prompt = _clean_prompt(question.key, question.response_schema,
                                        changes["prompt"])
    if "label" in changes:
        question.label = _clean_label(changes["label"])
    if "pdf_chip" in changes:
        question.pdf_chip = bool(changes["pdf_chip"])
        if question.pdf_chip:
            if section.kind != PRECALL:
                raise SessionError("Only a question asked before the call can show in "
                                   "the PDF header.")
            _check_chips(template, adding=question)
    if "is_financial" in changes:
        if section.kind != SCOPE:
            raise SessionError("Only a scope item can be marked as money.")
        question.is_financial = bool(changes["is_financial"])
    if "must_ask" in changes:
        if bool(changes["must_ask"]) and (rule["ask_when"] != AskWhen.LIVE
                                          or section.kind == RATINGS):
            raise SessionError("Only a question asked in the call can be a must-ask.")
        question.must_ask = bool(changes["must_ask"])
    # Checked on what the question is about to be, whichever field changed.
    if rule.get("needs_label") and not question.label:
        raise SessionError("A rated item needs a short label: it is what the chart "
                           "and the diagnostic call it.")
    if question.pdf_chip and not question.label:
        raise SessionError("An answer shown in the PDF header needs a short label.")
    question.save()
    return question


def remove_question(template, *, key) -> StrategyQuestion:
    require_v3(template)
    question = (StrategyQuestion.objects.select_related("section")
                .filter(template=template, key=key, deleted_at__isnull=True).first())
    if question is not None and RULES.get(question.section.kind, {}).get("exactly"):
        raise SessionError("There are always two paths. Reword them; they cannot be "
                           "added to or removed.")
    return template_admin.remove_question(template, key=key)


def reorder(template, *, section, keys) -> list[str]:
    require_v3(template)
    _section(template, section)
    return template_admin.reorder(template, section=section, keys=keys)


# ------------------------------------------------------------------ settings

def clean_settings(settings: dict) -> dict:
    """The whole settings object, validated against the fixed list. An unknown
    key is refused rather than stored: this is frozen into every session."""
    if not isinstance(settings, dict):
        raise SessionError("settings must be an object.")
    known = set(TEXTS) | set(POINTS) | {"diagnostic_size"}
    unknown = set(settings) - known
    if unknown:
        raise SessionError(f"Unknown setting: {', '.join(sorted(unknown))}.")
    out = default_settings()
    for key, (_default, most) in TEXTS.items():
        if key not in settings:
            continue
        text = " ".join(str(settings[key] or "").split())
        if not text:
            raise SessionError(f"{key} cannot be empty.")
        if len(text) > most:
            raise SessionError(f"{key} is {most} characters at most.")
        _check_merge_fields(text)
        out[key] = text
    for key in POINTS:
        if key not in settings:
            continue
        lines = settings[key]
        if not isinstance(lines, list) or len(lines) != 2:
            raise SessionError(f"{key} is exactly two lines.")
        cleaned = [" ".join(str(line or "").split()) for line in lines]
        for line in cleaned:
            if not line:
                raise SessionError(f"{key} cannot have an empty line.")
            if len(line) > POINT_MOST:
                raise SessionError(f"A line of {key} is {POINT_MOST} characters at most.")
            _check_merge_fields(line)
        out[key] = cleaned
    if "diagnostic_size" in settings:
        size = settings["diagnostic_size"]
        low, high = DIAGNOSTIC_SIZE
        if isinstance(size, bool) or not isinstance(size, int) or not low <= size <= high:
            raise SessionError(f"Diagnostic questions per session is a whole number "
                               f"from {low} to {high}.")
        out["diagnostic_size"] = size
    return out


def settings_of(template) -> dict:
    """What the template has, over the defaults — so a template made before a
    setting existed reads as if it had the default."""
    return {**default_settings(), **(template.settings or {})}


def update_settings(template, changes: dict) -> StrategyTemplate:
    require_v3(template)
    if not isinstance(changes, dict):
        raise SessionError("settings must be an object.")
    template.settings = clean_settings({**(template.settings or {}), **changes})
    template.save(update_fields=["settings", "updated_at"])
    return template


# ------------------------------------------------------------- ready to run

def readiness(template) -> list[str]:
    """What stands between this template and a session. Computed, never
    stored, so it cannot claim something that has stopped being true."""
    missing = []
    by_kind = {section.kind: section for section in _sections(template)}
    for kind, _code, title, _budget in PARTS:
        if kind not in by_kind and kind not in OPTIONAL_KINDS:
            missing.append(f"The “{title}” section is missing.")
    ratings = by_kind.get(RATINGS)
    if ratings is not None:
        rated = list(_live_questions(ratings))
        if len(rated) < MIN_RATED:
            missing.append(f"Ratings needs at least {MIN_RATED} rated items "
                           f"(it has {len(rated)}).")
        if any(not question.label for question in rated):
            missing.append("Every rated item needs a short label.")
    paths = by_kind.get(PATHS)
    if paths is not None and _live_questions(paths).count() != 2:
        missing.append("Two paths needs exactly two paths.")
    return missing


# ------------------------------------------------------------------ snapshot

def snapshot(template) -> dict:
    """A v3 template, frozen (snapshot version 2): the shape every snapshot
    has, plus each section's kind and each question's label and chip, and the
    template's settings. Removed sections and archived questions were not
    asked, and are left out."""
    questions = (StrategyQuestion.objects.filter(template=template, deleted_at__isnull=True)
                 .order_by("position", "created_at"))
    by_section: dict = {}
    for question in questions:
        by_section.setdefault(question.section_id, []).append({
            "key": question.key,
            "prompt": question.prompt,
            "ask_when": question.ask_when,
            "must_ask": question.must_ask,
            "area": question.area,
            "response_schema": question.response_schema,
            "is_fractional_observation": question.is_fractional_observation,
            "has_fractional_note": question.has_fractional_note,
            "is_financial": question.is_financial,
            "ask_if_time": question.ask_if_time,
            "is_diagnostic_fallback": question.is_diagnostic_fallback,
            "label": question.label,
            "pdf_chip": question.pdf_chip,
            "position": question.position,
        })
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "taken_at": timezone.now().isoformat(),
        "template": {"id": str(template.pk), "name": template.name,
                     "discipline": template.discipline, "version": template.version,
                     "format": template.format, "settings": settings_of(template)},
        "sections": [{
            "code": section.code,
            "kind": section.kind,
            "title": section.title,
            "position": section.position,
            "time_budget_minutes": section.time_budget_minutes,
            "intro": section.intro,
            "show_in_pdf": section.show_in_pdf,
            "questions": by_section.get(section.pk, []),
        } for section in _sections(template)],
    }


# -------------------------------------------------------------- on the wire

def represent(template) -> dict:
    """The builder's own view of a template: every part, including one that is
    switched off, with what each may hold."""
    frozen = {section["code"]: section for section in snapshot(template)["sections"]}
    sections = []
    for section in _sections(template, removed=True):
        rule = RULES.get(section.kind, {})
        sections.append({
            "code": section.code, "kind": section.kind, "title": section.title,
            "time_budget_minutes": section.time_budget_minutes,
            "included": section.deleted_at is None,
            "optional": section.kind in OPTIONAL_KINDS,
            "response_schema": rule.get("schema"),
            "most": rule.get("most", 0),
            "fixed_count": bool(rule.get("exactly")),
            "questions": frozen.get(section.code, {}).get("questions", []),
        })
        # A section of the practice's own says what else it can do. The eight
        # parts' entries are as they were.
        if section.kind == CUSTOM:
            sections[-1].update({
                "optional": True, "custom": True, "show_in_pdf": section.show_in_pdf,
                "schemas": list(rule["schemas"]),
            })
    missing = readiness(template)
    return {
        "id": str(template.pk), "name": template.name, "format": template.format,
        "is_default": template.is_default,
        "archived_at": template.archived_at.isoformat() if template.archived_at else None,
        "settings": settings_of(template),
        "ready": not missing, "missing": missing,
        "merge_fields": sorted(MERGE_FIELDS),
        "sections": sections,
    }
