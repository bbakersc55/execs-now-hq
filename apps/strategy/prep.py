"""Session prep — what the fractional knows before the call (owner, 2026-09-21).

One Claude call, with **web search on**, over two inputs: the company's website
and whatever the fractional pastes in — old emails, call notes, anything they
already know. It produces four things: what the company does and how it sells,
the ordinary bottlenecks for a business of that shape, a suggested rewording of
each pre-call question for this prospect, and five extra questions worth asking
live.

Three rules, and they are the reason this is safe to run before a real call:

1. **It is fractional-only, in every direction.** The brief never reaches the
   prospect — not the pre-call form, not the questions email, not the PDF. The
   only thing that crosses is a reworded question the fractional **copies into
   the template themselves**; nothing here edits the template.
2. **A fact read from the site is marked as one.** The brief says *"their site
   says"* when it is repeating the website, and says so plainly when it is
   inferring. Outside those two, it asserts nothing its inputs do not carry —
   the constraint every other Claude call in this product works under.
3. **One `ai_call` per run**, with its tokens, its cost, and the number of
   searches it ran.
"""

from __future__ import annotations

import json
import re

from apps.strategy import services
from apps.strategy.models import StrategyPrepQuestion, StrategySessionPrep

PREP_PURPOSE = "session_prep"

SYSTEM = """\
You are preparing a fractional operations executive for a strategy session with \
a prospect. You are given the prospect's website and whatever the fractional \
already knows, and you may search the web to read the site and anything public \
about the company.

Produce four things.

1. "summary": what the company does and how it sells — two or three sentences.
2. "bottlenecks": 3 to 5 of the ordinary operational bottlenecks for a business \
of this shape and size. These are the patterns of the trade, not claims about \
this company.
3. "rewordings": for EACH pre-call question you are given, a rewording in this \
prospect's own vocabulary — their words for their work, their units, their \
trade. Keep the question asking exactly what it asked before. If a question is \
already right for them, return it unchanged and say so in "why".
4. "questions": five extra questions worth asking live, that the template does \
not cover and that only make sense because of what you have read.

**Marking what you know.** Anything you took from the website or another source \
you read starts with "Their site says" or "Their <source> says". Anything you \
are inferring starts with "Likely" or "If that is right". Outside those two \
kinds of sentence, assert nothing that is not in the material you were given. \
**Do not invent** revenue, headcount, customer counts, locations, names or \
dates. If the site says little, say that — a short honest brief is worth more \
than a long invented one, and the fractional is about to be in the room.

Reply with JSON only: {"summary": "", "bottlenecks": [], "rewordings": \
[{"key": "", "suggested": "", "why": ""}], "questions": [{"text": "", "why": ""}]}. \
No prose around it, no markdown fence."""


def _payload(text: str):
    """The JSON, whether or not a fence or a sentence came with it."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def precall_questions(session):
    """[(key, rendered prompt)] — what the prospect is being asked today.

    The fractional's own observations are left out: they are not asked aloud,
    so there is nothing to reword for a prospect who never sees them.
    """
    merge = services.merge_context(session)
    out = []
    for _section, question in services.questions_in(session.template_snapshot,
                                                    ask_when="precall"):
        if question.get("is_fractional_observation"):
            continue
        out.append((question["key"], services.render_prompt(question["prompt"], merge)))
    return out


def prep_input(session, *, website_url: str, notes: str) -> str:
    company = session.company.name if session.company_id else ""
    name = f"{session.contact.first_name} {session.contact.last_name}".strip()
    lines = [f"PROSPECT: {name}"]
    if company:
        lines.append(f"COMPANY: {company}")
    if website_url:
        lines.append(f"WEBSITE: {website_url} — read this.")
    if notes.strip():
        lines += ["", "WHAT THE FRACTIONAL ALREADY KNOWS "
                      "(pasted emails, call notes, anything):", notes.strip()]
    lines += ["", "THE PRE-CALL QUESTIONS, to reword one for one:"]
    for key, prompt in precall_questions(session):
        lines.append(f"  {key}: {prompt}")
    return "\n".join(lines)


def prepare(session, *, website_url="", notes="", actor=None):
    """Run it, and keep what came back. One call, one `ai_call`."""
    from apps.tenancy import claude

    prep, _ = StrategySessionPrep.objects.get_or_create(
        session=session, defaults={"tenant": session.tenant})
    prep.website_url = (website_url or "").strip()
    prep.notes = notes or ""
    prep.state = StrategySessionPrep.State.DRAFTING
    prep.save(update_fields=["website_url", "notes", "state", "updated_at"])

    try:
        text, call = claude.complete_with_call(
            tenant=session.tenant, purpose=PREP_PURPOSE, system=SYSTEM,
            user_text=prep_input(session, website_url=prep.website_url, notes=prep.notes),
            target_type="strategy_session", target_id=session.pk, trigger="button",
            max_tokens=8000, tools=[claude.WEB_SEARCH_TOOL],
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        prep.state = StrategySessionPrep.State.FAILED
        prep.save(update_fields=["state", "updated_at"])
        return None

    payload = _payload(text)
    if not isinstance(payload, dict):
        prep.state = StrategySessionPrep.State.FAILED
        prep.ai_call = call
        prep.save(update_fields=["state", "ai_call", "updated_at"])
        return prep

    current = dict(precall_questions(session))
    rewordings = []
    for raw in payload.get("rewordings") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        suggested = str(raw.get("suggested") or "").strip()
        # A rewording of a question this session does not ask is a rewording of
        # nothing: the snapshot is what the prospect will see.
        if key not in current or not suggested:
            continue
        rewordings.append({"key": key, "current": current[key], "suggested": suggested,
                           "why": str(raw.get("why") or "").strip()})

    prep.summary = str(payload.get("summary") or "").strip()
    prep.bottlenecks = [str(item).strip() for item in (payload.get("bottlenecks") or [])
                        if str(item).strip()][:5]
    prep.rewordings = rewordings
    prep.ai_call = call
    prep.state = StrategySessionPrep.State.READY
    prep.save(update_fields=["summary", "bottlenecks", "rewordings", "ai_call", "state",
                             "updated_at"])

    # The five extra questions are rows, because each one is pinned, noted
    # against and read on its own. A re-run replaces the ones nobody pinned and
    # leaves the pinned ones alone — a fractional who has already chosen is not
    # overruled by a second opinion.
    StrategyPrepQuestion.objects.filter(prep=prep, is_pinned=False).delete()
    position = StrategyPrepQuestion.objects.filter(prep=prep).count()
    for raw in (payload.get("questions") or [])[:5]:
        text_value = str((raw or {}).get("text") or "").strip() if isinstance(raw, dict) \
            else str(raw or "").strip()
        if not text_value:
            continue
        StrategyPrepQuestion.objects.create(
            tenant=session.tenant, prep=prep, session=session, text=text_value,
            why=str(raw.get("why") or "").strip() if isinstance(raw, dict) else "",
            position=position)
        position += 1
    return prep
