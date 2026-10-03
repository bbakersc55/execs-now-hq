"""The focused template's dynamic diagnostic (owner, 2026-09-29).

When the pre-call form is complete, Claude proposes three to five diagnostic
questions from the prospect's own answers, into a tray. **What each question is
for is decided here, in code**, from the answers; Claude only words it:

- the two lowest ratings get one question each;
- any mention of growth or expansion gets one;
- an evident gap in the Snapshot gets one (up to two), which is the one
  judgement Claude makes, and it may find none.

If that comes to fewer than three, the third-lowest rating gets one as well.

Three guardrails, each with a test:

1. **Proposed, never asked.** A proposal lands in the tray; only a person's
   accept puts it in the session, under a new key in the session's own
   snapshot. Nothing is asked automatically.
2. **Nothing beyond the input.** Claude is given the pre-call answers and the
   reason for each slot, and told to assert nothing else.
3. **The must-asks are never displaced.** Proposals only ever go into §2; §1's
   three must-asks are never touched, and §2 holds at most five.

If nothing is accepted (the form was not completed, or every proposal was
discarded), §2 asks the template's five fixed questions instead.
"""

from __future__ import annotations

import re
import uuid

from apps.strategy import rewording, services
from apps.strategy.models import StrategyDiagnosticProposal, StrategySession

PURPOSE = "strategy_diagnostic_questions"
MOST = 5
FEWEST = 3
DIAGNOSTIC = "diagnostic"
#: One area for every accepted question, so the map rows draft once, when all
#: of them are answered (the FR-4.18a trigger), not once per question.
AREA = "From the pre-call form"

R = StrategyDiagnosticProposal.Rule
P = StrategyDiagnosticProposal.State

GROWTH = re.compile(
    r"\b(grow\w*|growth|expan\w*|scal(e|ing)|doubl\w*|new (location|market|branch|site)s?|"
    r"acqui\w*|open(ing)? (a )?(second|another|new))\b", re.I)

SYSTEM = """\
You are writing diagnostic questions for a fractional operations executive to ask \
a prospect in a strategy session. You are given the prospect's own answers from a \
pre-call form, and a numbered list of slots. Each slot says what its question is \
for and what in the answers it rests on.

Write exactly one question for each numbered slot: open, specific to what they \
said, one sentence, in plain words, the kind an experienced operator asks to find \
where something is breaking. Then, for "snapshot", look at the Snapshot answers \
and write a question for each EVIDENT gap or deficiency in them (at most two) — \
something plainly missing, thin or out of line in what they wrote. If there is \
no evident gap, write none. Never invent one.

Assert nothing that is not in the answers: no figures they did not give, no \
names, no causes, no industry assumptions. A question may quote them.

Reply with JSON only: [{"slot": 1, "question": "...", "basis": "..."}], where \
"slot" is the slot's number or "snapshot", and "basis" is the short phrase from \
their answers the question rests on. No prose, no markdown fence."""


def _precall_answers(session):
    answers = services.answers_of(session)
    context = services.merge_context(session)
    rows = []
    for section, question in services.questions_in(session.template_snapshot,
                                                   ask_when="precall"):
        answer = answers.get(question["key"])
        if answer is None or not answer.value:
            continue
        rows.append((section["code"], question,
                     services.render_prompt(question["prompt"], context), answer.value))
    return rows


def slots(session) -> list[dict]:
    """What each proposed question is for, decided from the answers."""
    scores = services.six_key_components(session)["scores"]
    ranked = sorted(scores, key=lambda row: row["rating"])      # stable: form order
    out = []
    for row in ranked[:2]:
        name = rewording.component_of(row["key"]) or row["key"]
        out.append({"rule": R.LOWEST_RATING,
                    "reason": f"{name} is one of their two lowest ratings "
                              f"({row['rating']} of 10)",
                    "basis": f"{name}: {row['rating']}/10"
                             + (f" — \"{row['comment']}\"" if row["comment"] else "")})
    for _code, _question, prompt, value in _precall_answers(session):
        text = " ".join(str(v) for v in value.values() if isinstance(v, str))
        match = GROWTH.search(text)
        if match:
            start = max(match.start() - 40, 0)
            out.append({"rule": R.GROWTH, "reason": "They mentioned growth or expansion",
                        "basis": f"{prompt}: \"…{text[start:match.end() + 40].strip()}…\""})
            break
    if len(out) < FEWEST and len(ranked) > 2:
        # Claude may find no Snapshot gap, so the slots decided here make up
        # the three on their own.
        row = ranked[2]
        name = rewording.component_of(row["key"]) or row["key"]
        out.append({"rule": R.LOWEST_RATING,
                    "reason": f"{name} is their next-lowest rating ({row['rating']} of 10)",
                    "basis": f"{name}: {row['rating']}/10"})
    return out


def model_input(session, planned) -> str:
    lines = ["The prospect's pre-call answers:"]
    for code, _question, prompt, value in _precall_answers(session):
        said = "; ".join(f"{k}: {v}" for k, v in value.items()
                         if isinstance(v, (str, int)) and str(v).strip())
        lines.append(f"[{'Snapshot' if code == 'snapshot' else 'Rating'}] {prompt} — {said}")
    lines.append("\nSlots:")
    for number, slot in enumerate(planned, start=1):
        lines.append(f"{number}. {slot['reason']}. Rests on: {slot['basis']}")
    lines.append("snapshot. Any evident gap in the Snapshot answers (at most two, or none).")
    return "\n".join(lines)


def propose(session, *, trigger="button") -> list:
    """Claude's proposals, into the tray. Never touches one already there, and
    never proposes past five live (proposed or accepted) in all."""
    import json

    from apps.tenancy import claude

    if not services.is_focused(session):
        return []
    planned = slots(session)
    if not planned and not _precall_answers(session):
        return []
    live = StrategyDiagnosticProposal.objects.filter(
        session=session, state__in=[P.PROPOSED, P.ACCEPTED])
    room = MOST - live.count()
    if room <= 0:
        return []
    try:
        text, call = claude.complete_with_call(
            tenant=session.tenant, purpose=PURPOSE, system=SYSTEM,
            user_text=model_input(session, planned), target_type="strategy_session",
            target_id=session.pk, trigger=trigger, max_tokens=4000, effort="low")
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return []                        # the ai_call row records what happened
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        payload = json.loads(cleaned)
    except ValueError:
        return []
    if not isinstance(payload, list):
        return []

    seen = {p.prompt.strip().lower() for p in live}
    position = StrategyDiagnosticProposal.objects.filter(session=session).count()
    made, gaps = [], 0
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        question = " ".join(str(raw.get("question") or "").split())
        slot = raw.get("slot")
        if not question or question.lower() in seen:
            continue
        if str(slot).strip().lower() == "snapshot":
            if gaps >= 2:
                continue
            gaps += 1
            rule, basis = R.SNAPSHOT_GAP, str(raw.get("basis") or "").strip()
        else:
            try:
                planned_slot = planned[int(slot) - 1]
            except (TypeError, ValueError, IndexError):
                continue                 # a question for a slot nobody asked for
            rule, basis = planned_slot["rule"], planned_slot["basis"]
        seen.add(question.lower())
        made.append(StrategyDiagnosticProposal.objects.create(
            tenant=session.tenant, session=session, rule=rule, basis=basis[:500],
            prompt=question, proposed_prompt=question, position=position, ai_call=call))
        position += 1
        if len(made) >= room:
            break
    return made


class Refused(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def accept(proposal) -> StrategySession:
    """Into the session's own snapshot, under a new key. The §1 must-asks are
    in another section and are never touched; §2 holds at most five."""
    if proposal.state != P.PROPOSED:
        raise Refused("Only a proposed question can be accepted.")
    session = StrategySession.objects.select_for_update().get(pk=proposal.session_id)
    snapshot = session.template_snapshot
    section = next((s for s in snapshot.get("sections", []) if s["code"] == DIAGNOSTIC),
                   None)
    if section is None:
        raise Refused("This session has no diagnostic section.")
    dynamic = [q for q in section.get("questions", []) if q.get("dynamic")]
    if len(dynamic) >= MOST:
        raise Refused(f"The diagnostic holds {MOST} questions. Discard one before "
                      "accepting another.")
    key = f"dx_{uuid.uuid4().hex[:10]}"
    section.setdefault("questions", []).append({
        "key": key, "prompt": proposal.prompt.strip(), "ask_when": "live",
        "must_ask": False, "area": AREA, "response_schema": "diagnostic_triple",
        "is_fractional_observation": False, "has_fractional_note": True,
        "is_financial": False, "ask_if_time": False, "is_diagnostic_fallback": False,
        "dynamic": True, "position": len(section["questions"]),
        "proposal": str(proposal.pk), "rule": proposal.rule,
    })
    session.template_snapshot = snapshot
    session.save(update_fields=["template_snapshot", "updated_at"])
    proposal.state, proposal.question_key = P.ACCEPTED, key
    proposal.save(update_fields=["state", "question_key", "updated_at"])
    return session


#: A removed question can come out only before the session is finished.
CLOSED = {StrategySession.State.COMPLETE, StrategySession.State.CONVERTED,
          StrategySession.State.LOST}


def remove(proposal) -> StrategySession:
    """Take an accepted question back out of the session (backlog, 2026-10-03)
    and return it to the tray as proposed, so it can be accepted again or
    discarded. Refused once it has an answer, or once the session is done:
    a question someone already answered is part of the record."""
    from apps.strategy.models import StrategyAnswer

    if proposal.state != P.ACCEPTED or not proposal.question_key:
        raise Refused("Only an accepted question can be removed.")
    session = StrategySession.objects.select_for_update().get(pk=proposal.session_id)
    if session.state in CLOSED:
        raise Refused("This session is finished; its questions stay as they were asked.")
    answer = StrategyAnswer.objects.filter(session=session,
                                           question_key=proposal.question_key).first()
    if answer is not None and answer.value:
        raise Refused("This question has been answered, so it stays. Its answer is "
                      "part of the session.")
    snapshot = session.template_snapshot
    section = next((s for s in snapshot.get("sections", []) if s["code"] == DIAGNOSTIC),
                   None)
    if section is not None:
        section["questions"] = [q for q in section.get("questions", [])
                                if q.get("key") != proposal.question_key]
        for position, question in enumerate(section["questions"]):
            question["position"] = position
    if answer is not None:
        answer.delete()                      # an empty answer row, nothing in it
    session.template_snapshot = snapshot
    session.save(update_fields=["template_snapshot", "updated_at"])
    proposal.state, proposal.question_key = P.PROPOSED, ""
    proposal.save(update_fields=["state", "question_key", "updated_at"])
    return session


def represent(proposal) -> dict:
    return {"id": str(proposal.pk), "rule": proposal.rule,
            "rule_label": proposal.get_rule_display(), "basis": proposal.basis,
            "prompt": proposal.prompt, "state": proposal.state,
            "question_key": proposal.question_key, "from_ai": proposal.ai_call_id is not None}
