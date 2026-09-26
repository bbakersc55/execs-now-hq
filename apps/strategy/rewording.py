"""What a rewording may and may not do (incident, 2026-09-22).

A prospect received a pre-call email in which the six Six Key Components sat
under *"Rate each one from 1 to 10"* as six open questions. Prep had suggested
essay wordings for them, the suggestions were applied to the template, and
nothing between the suggestion and the send asked whether the question was
still the kind of question it had been.

**A rewording changes the words, never the shape.** That is the rule this
module holds, in one place, so the prep service and the template editor cannot
disagree about it.
"""

from __future__ import annotations

import re

#: The six, and the thing each one rates. A rating's wording has to *start*
#: with its component's name: what is being rated is not a detail of the
#: phrasing, and it is the first thing the prospect reads.
RATING_COMPONENTS = {
    "s2_vision": "Vision",
    "s2_people": "People",
    "s2_data": "Data",
    "s2_issues": "Issues",
    "s2_process": "Process",
    "s2_traction": "Traction",
}

#: A rating's lead-in is a line, not a paragraph. The broken ones ran to 180
#: characters.
MAX_RATING_PROMPT = 120

#: What makes a question ask for an explanation rather than a score (owner,
#: 2026-09-26). A yes/no-shaped question of any length under the cap scores on
#: a scale — "Is the 3-year picture clear and shared?" — and one that asks
#: *what* or *how* does not: "What does your 3-year picture look like?". Every
#: one of the six sent on 22 September carries at least one of these, or
#: dropped its component's name. `who`, `where` and `when` added 2026-09-26:
#: without them "People — Who runs each division, and where is the gap?" passed.
OPEN_ENDED_CUES = ("how", "what", "why", "which", "who", "where", "when",
                   "describe", "tell me", "walk me through", "explain", "list")
_OPEN_ENDED = re.compile(r"\b(" + "|".join(re.escape(cue) for cue in OPEN_ENDED_CUES)
                         + r")\b", re.IGNORECASE)

#: The scale, said once above the six. `RATING_SCALE_MEANING` is the half that
#: still reads right on a page reporting the scores rather than asking for them.
RATING_SCALE_MEANING = "1 means it barely works today, 10 means it could not be better"
RATING_SCALE = f"Rate each one from 1 to 10 — {RATING_SCALE_MEANING}."

RATING_SCHEMA = "rating_1_10"


def component_of(key: str) -> str:
    return RATING_COMPONENTS.get(key, "")


def refusal(key: str, schema: str, prompt: str) -> str:
    """Why this wording cannot stand, in the words the refusal is read in —
    or "" when it is fine.

    Applies to a rating question and nothing else: every other schema is free
    text of one shape or another, and rewording those is what prep is for.
    """
    if schema != RATING_SCHEMA:
        return ""
    text = (prompt or "").strip()
    if not text:
        return "A question needs a prompt."
    component = component_of(key)
    if component and not text.lower().startswith(component.lower()):
        return (f"This one is rated 1–10, and {component} is the thing being rated — "
                f"the wording has to start with “{component}”. "
                f"You can change the lead-in after it.")
    if len(text) > MAX_RATING_PROMPT:
        return (f"This one is rated 1–10, so its wording is a lead-in of a line, not "
                f"a question of its own ({len(text)} characters; {MAX_RATING_PROMPT} "
                f"is the most). Asking something open under “rate it 1 to 10” "
                f"is what went wrong on 22 September.")
    cue = _OPEN_ENDED.search(text)
    if cue:
        return (f"This one is rated 1–10. “{cue.group(0)}” asks for an explanation, "
                f"which is answered in prose — what the prospect did last time. Ask "
                f"something a score can answer: “Is it clear…?”, “Do you…?”.")
    return ""


def is_allowed(key: str, schema: str, prompt: str) -> bool:
    return not refusal(key, schema, prompt)
