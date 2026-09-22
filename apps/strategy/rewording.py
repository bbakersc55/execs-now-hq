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

#: The six, and the thing each one rates. The seed's wording *is* the component
#: name, so a reworded lead-in has to keep it: what is being rated is not a
#: detail of the phrasing.
RATING_COMPONENTS = {
    "s2_vision": "Vision",
    "s2_people": "People",
    "s2_data": "Data",
    "s2_issues": "Issues",
    "s2_process": "Process",
    "s2_traction": "Traction",
}

#: A rating's lead-in is a line, not a paragraph. The broken ones ran to 180
#: characters and asked three things.
MAX_RATING_PROMPT = 120

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
    if component and component.lower() not in text.lower():
        return (f"This one is rated 1–10, and {component} is the thing being rated — "
                f"the wording has to keep the word “{component}” in it. "
                f"You can change the lead-in around it.")
    if len(text) > MAX_RATING_PROMPT:
        return (f"This one is rated 1–10, so its wording is a lead-in of a line, not "
                f"a question of its own ({len(text)} characters; {MAX_RATING_PROMPT} "
                f"is the most). Asking something open under “rate it 1 to 10” "
                f"is what went wrong on 22 September.")
    if "?" in text and len(text.split()) > 12:
        return ("This one is rated 1–10. A question mark on a long line reads as "
                "something to answer in prose, which is what the prospect did last "
                "time. Keep it a short lead-in.")
    return ""


def is_allowed(key: str, schema: str, prompt: str) -> bool:
    return not refusal(key, schema, prompt)
