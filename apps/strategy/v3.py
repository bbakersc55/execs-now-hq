"""Session v3 (P3, 2026-10-03): what a session started from a builder template
does differently.

The flow is pre-call questions, ratings on the call, a short diagnostic
proposed from the pre-call answers, the mirror with its own questions, the map,
what they value (if the template has it), two paths and scope. Most of that is
the code every session already runs, reading a v3 snapshot by the section codes
it has always used. This module holds only the differences:

- what Claude is given, which in v3 includes what they wrote before the call
  and how they rated themselves;
- how Claude is told who it is drafting for (`advisor_role`, from the template,
  where the older prompts say "fractional operations executive");
- the diagnostic's rules, its size, and a question added by hand;
- keeping duplicate and already-rejected rows out of the map's tray.

**Every function here is reached only for a v3 session.** A classic or focused
session takes none of these branches, which is what
`tests/test_strategy_v2_golden.py` holds the code to.

The rule that runs through the whole module is unchanged: Claude proposes, a
person disposes. Everything drafted here lands `proposed`.
"""

from __future__ import annotations

import json
import re

from django.db import transaction

from apps.strategy import services
from apps.strategy.models import StrategyDiagnosticProposal, StrategyMapRow

#: The most diagnostic questions one session holds, whatever the template's
#: own number: the template says where a session starts, not where it stops.
DIAGNOSTIC_CEILING = 8
MAP_CAP = 5
PROMPT_MOST = 500

R = StrategyDiagnosticProposal.Rule
P = StrategyDiagnosticProposal.State


# ----------------------------------------------------------- the snapshot

def settings_of(session) -> dict:
    """The template's settings as the session froze them, over the defaults."""
    from apps.strategy import builder

    frozen = (session.template_snapshot.get("template") or {}).get("settings") or {}
    return {**builder.default_settings(), **frozen}


def section_of(session, kind) -> dict | None:
    for section in session.template_snapshot.get("sections", []):
        if section.get("kind") == kind:
            return section
    return None


def label_of(session, key: str) -> str:
    question = services.question_in(session.template_snapshot, key)
    return ((question or {}).get("label") or "").strip() or key


# ------------------------------------------------------------- the prompts

_ROLE = "fractional operations executive"


def system(text: str, session) -> str:
    """A drafting prompt, addressed to this practice's own kind of advisor.

    The prompts were written for an operations fractional. In v3 the template
    says who the practice is (`advisor_role`), and nothing else in the prompt
    changes: the rules about asserting nothing beyond the input are the same
    words for every practice."""
    role = settings_of(session)["advisor_role"]
    article = "an" if role[:1].lower() in "aeiou" else "a"
    text = text.replace(f"a {_ROLE}", f"{article} {role}").replace(_ROLE, role)
    # The v3 mirror is read back after the diagnostic, not before it.
    return text.replace("near the start of a strategy session", "in a strategy session")


# ----------------------------------------------- what Claude is given

def _said(value: dict) -> str:
    return "; ".join(str(v).strip() for v in (value or {}).values()
                     if isinstance(v, str) and v.strip())


def precall_answers(session) -> list:
    """[(question, rendered prompt, value)] for what they wrote before the
    call, in order, answered only. Never a private note."""
    answers = services.answers_of(session)
    context = services.merge_context(session)
    out = []
    for _section, question in services.questions_in(session.template_snapshot,
                                                    ask_when="precall"):
        answer = answers.get(question["key"])
        if answer is None or not _said(answer.value):
            continue
        out.append((question, services.render_prompt(question["prompt"], context),
                    answer.value))
    return out


def ratings(session) -> list:
    """The rated items that have a number, each under its label."""
    return [{**row, "label": label_of(session, row["key"])}
            for row in services.six_key_components(session)["scores"]]


def _precall_block() -> str:
    return "Before the call, they wrote:"


def drafting_input(session) -> str:
    """What the map rows, the mirror and the pros and cons are drafted from:
    what they wrote before the call, how they rated themselves, where they want
    to go, and the diagnostic as captured.

    Never the practice's private notes, never Scope, never anything about
    money — private from the model as it is from the PDF.
    """
    from apps.strategy import ai, builder

    lines = []
    before = precall_answers(session)
    if before:
        lines.append(_precall_block())
        lines += [f"{prompt}\n  {_said(value)}" for _q, prompt, value in before]
    rated = ratings(session)
    if rated:
        lines.append(f"\nHow they rated themselves, 1 to 10 "
                     f"({settings_of(session)['rating_scale']}):")
        for row in rated:
            comment = f" — \"{row['comment']}\"" if row["comment"] else ""
            lines.append(f"  {row['label']}: {row['rating']}{comment}")
    mirror = section_of(session, builder.MIRROR)
    going = [(prompt, (value.get("text") or "").strip())
             for _q, prompt, value in ai._answered(session, mirror["code"])] if mirror else []
    going = [(prompt, text) for prompt, text in going if text]
    if going:
        lines.append("\nWhere they want to go:")
        lines += [f"{prompt}\n  {text}" for prompt, text in going]
    diagnostic = ai._answered(session, ai.DIAGNOSTIC_SECTION)
    if diagnostic:
        lines.append("\nDiagnostic — what is breaking:")
    for _question, prompt, value in diagnostic:
        lines.append(prompt)
        for field, label in (("said", "they said"), ("cause", "who or what causes it"),
                             ("tried", "what they tried, and why it did not stick")):
            said = (value.get(field) or "").strip()
            if said:
                lines.append(f"  {label}: {said}")
    return "\n".join(lines).strip()


# -------------------------------------------- the map: no duplicates (D13a)

def map_room(session) -> int:
    """How many more rows the map can take."""
    accepted = StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.ACCEPTED).count()
    return max(MAP_CAP - accepted, 0)


MAP_FULL = (f"The map holds {MAP_CAP} rows and it is full. Remove one, or Consolidate, "
            "before drafting more.")


def rejected(session) -> str:
    """The rows a person discarded, told to the model: a theme turned down once
    is not proposed again in other words."""
    rows = StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.DISCARDED
    ).order_by("position", "created_at")
    if not rows:
        return ""
    lines = ["\nRows already rejected for this map — do not propose these themes again:"]
    for row in rows:
        lines.append(f"- {row.bottleneck}" + (f" — fix: {row.the_fix}" if row.the_fix else ""))
    return "\n".join(lines)


def normalized(text: str) -> str:
    """Case, punctuation and spacing do not make a row a different row."""
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def seen_rows(session) -> set:
    """Every header and bottleneck this session has had, in any state."""
    seen = set()
    for row in StrategyMapRow.objects.filter(session=session):
        seen.update({normalized(row.bottleneck), normalized(row.header)})
    seen.discard("")
    return seen


def is_duplicate(row: dict, seen: set) -> bool:
    return bool({normalized(row.get("bottleneck")), normalized(row.get("header"))}
                & seen - {""})


# ------------------------------------------------------- the diagnostic

DIAGNOSTIC_SYSTEM = """\
You are writing diagnostic questions for a fractional operations executive to ask \
a prospect in a strategy session. You are given what the prospect wrote before the \
call, how they rated themselves on the call if that has happened, and a numbered \
list of slots. Each slot says what its question is for and what it rests on.

Write exactly one question for each numbered slot: open, specific to what they \
said, one sentence, in plain words, the kind an experienced practitioner asks to \
find where something is breaking. Then, for "gap", look at what they wrote before \
the call and write a question for each EVIDENT gap or deficiency in it (at most \
{gaps}) — something plainly missing, thin or out of line in what they wrote. If \
there is no evident gap, write none. Never invent one.

Assert nothing that is not in what you were given: no figures they did not give, \
no names, no causes, no industry assumptions. A question may quote them.

You may be given questions already asked, proposed or rejected. Do not write \
another on the same point.

Reply with JSON only: [{{"slot": 1, "question": "...", "basis": "..."}}], where \
"slot" is the slot's number or "gap", and "basis" is the short phrase from what \
they wrote that the question rests on. No prose, no markdown fence."""


def diagnostic_size(session) -> int:
    return int(settings_of(session)["diagnostic_size"])


def _proposals(session):
    return StrategyDiagnosticProposal.objects.filter(session=session)


def diagnostic_room(session) -> int:
    live = _proposals(session).filter(state__in=[P.PROPOSED, P.ACCEPTED]).count()
    return max(DIAGNOSTIC_CEILING - live, 0)


def slots(session, *, from_ratings=False) -> list[dict]:
    """What each proposed question is for, decided here from the answers.
    Claude words them; it does not choose them."""
    from apps.strategy import diagnostic

    if from_ratings:
        ranked = sorted(ratings(session), key=lambda row: row["rating"])   # stable
        return [{"rule": R.LOWEST_RATING,
                 "reason": f"{row['label']} is one of their two lowest ratings "
                           f"({row['rating']} of 10)",
                 "basis": f"{row['label']}: {row['rating']}/10"
                          + (f" — \"{row['comment']}\"" if row["comment"] else "")}
                for row in ranked[:2]] if len(ranked) >= 2 else []
    if _proposals(session).filter(rule=R.GROWTH).exclude(state=P.DISCARDED).exists():
        return []                        # one growth question is enough
    for _question, prompt, value in precall_answers(session):
        text = _said(value)
        match = diagnostic.GROWTH.search(text)
        if match:
            start = max(match.start() - 40, 0)
            return [{"rule": R.GROWTH, "reason": "They mentioned growth or expansion",
                     "basis": f"{prompt}: \"…{text[start:match.end() + 40].strip()}…\""}]
    return []


def diagnostic_input(session, planned, *, gaps: int) -> str:
    lines = [_precall_block()]
    lines += [f"{prompt} — {_said(value)}" for _q, prompt, value in precall_answers(session)]
    rated = ratings(session)
    if rated:
        lines.append("\nHow they rated themselves on the call, 1 to 10:")
        lines += [f"{row['label']}: {row['rating']}"
                  + (f" — \"{row['comment']}\"" if row["comment"] else "") for row in rated]
    earlier = list(_proposals(session).order_by("position", "created_at"))
    if earlier:
        lines.append("\nQuestions already asked, proposed or rejected — do not repeat "
                     "their point:")
        lines += [f"- {proposal.prompt}" for proposal in earlier]
    lines.append("\nSlots:")
    for number, slot in enumerate(planned, start=1):
        lines.append(f"{number}. {slot['reason']}. Rests on: {slot['basis']}")
    lines.append(f"gap. Any evident gap in what they wrote before the call "
                 f"(at most {gaps}, or none)." if gaps
                 else "gap. None this time: write only the numbered slots.")
    return "\n".join(lines)


def propose(session, *, trigger="button", from_ratings=False) -> list:
    """Claude's proposed questions, into the tray. Never touches one already
    there. A run proposes up to the template's own number
    (`diagnostic_size`), and never past the session's ceiling of eight."""
    from apps.strategy import diagnostic
    from apps.tenancy import claude

    room = diagnostic_room(session)
    if room <= 0 or (not from_ratings and not precall_answers(session)):
        return []
    planned = slots(session, from_ratings=from_ratings)[:room]
    if from_ratings and not planned:
        return []
    most = len(planned) if from_ratings else min(diagnostic_size(session), room)
    gaps = max(most - len(planned), 0)
    if not planned and not gaps:
        return []
    try:
        text, call = claude.complete_with_call(
            tenant=session.tenant, purpose=diagnostic.PURPOSE,
            system=system(DIAGNOSTIC_SYSTEM.format(gaps=gaps or "none"), session),
            user_text=diagnostic_input(session, planned, gaps=gaps),
            target_type="strategy_session", target_id=session.pk, trigger=trigger,
            max_tokens=4000, effort="low")
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return []                        # the ai_call row records what happened
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        payload = json.loads(cleaned)
    except ValueError:
        return []
    if not isinstance(payload, list):
        return []

    # Rejected ones count: a question turned down is not proposed again.
    seen = {normalized(p.prompt) for p in _proposals(session)}
    position = _proposals(session).count()
    made, found_gaps, used = [], 0, set()
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        question = " ".join(str(raw.get("question") or "").split())[:PROMPT_MOST]
        slot = raw.get("slot")
        if not question or normalized(question) in seen:
            continue
        if str(slot).strip().lower() == "gap":
            if found_gaps >= gaps:
                continue
            found_gaps += 1
            rule, basis = R.PRECALL_GAP, str(raw.get("basis") or "").strip()
        else:
            try:
                index = int(slot) - 1
                planned_slot = planned[index]
            except (TypeError, ValueError, IndexError):
                continue                 # a question for a slot nobody asked for
            if index < 0 or index in used:
                continue                 # one question to a slot
            used.add(index)
            rule, basis = planned_slot["rule"], planned_slot["basis"]
        seen.add(normalized(question))
        made.append(StrategyDiagnosticProposal.objects.create(
            tenant=session.tenant, session=session, rule=rule, basis=basis[:500],
            prompt=question, proposed_prompt=question, position=position, ai_call=call))
        position += 1
        if len(made) >= most:
            break
    return made


@transaction.atomic
def add_question(session, *, prompt) -> StrategyDiagnosticProposal:
    """A diagnostic question the person on the call typed in (D4). It goes
    straight into the session, because a person wrote it: under a new key in
    the session's own snapshot, exactly as an accepted proposal does. The
    template is not touched."""
    from apps.strategy import diagnostic

    prompt = " ".join(str(prompt or "").split())
    if not prompt:
        raise diagnostic.Refused("A question needs some words.", status=400)
    if len(prompt) > PROMPT_MOST:
        raise diagnostic.Refused(f"A question is {PROMPT_MOST} characters at most.",
                                 status=400)
    if session.state in diagnostic.CLOSED:
        raise diagnostic.Refused("This session is finished; its questions stay as they "
                                 "were asked.")
    proposal = StrategyDiagnosticProposal.objects.create(
        tenant=session.tenant, session=session, rule=R.MANUAL, basis="", prompt=prompt,
        proposed_prompt="", position=_proposals(session).count())
    diagnostic.accept(proposal)
    return proposal


def accept_refusal(session, dynamic_count: int) -> str:
    """Why another question cannot join this session — or "" when it can."""
    if dynamic_count >= DIAGNOSTIC_CEILING:
        return (f"A session holds {DIAGNOSTIC_CEILING} diagnostic questions at most. "
                "Take one out before adding another.")
    return ""
