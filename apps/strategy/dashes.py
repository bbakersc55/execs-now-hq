"""No em dashes in the map text Claude drafts (owner, 2026-10-12).

Whatever the model is told, a dash can slip through, and this text goes on a
document a prospect keeps. So every drafted row, mirror and pro or con passes
through here on its way in: in a title a dash becomes a colon, and in a
sentence it becomes a comma, or a full stop when what follows starts a new
sentence. Only what Claude drafts: a person's own words are never touched.

An en dash is treated the same when it is used as a dash, with spaces round
it. Between two figures ("30–60 days") it is a range, and is left alone.
"""

from __future__ import annotations

import re

#: An em dash anywhere, or an en dash standing as one (spaces on both sides),
#: with whatever space surrounds it.
_DASH = re.compile(r"\s*—\s*|\s+–\s+")


def title(text: str) -> str:
    """A header: "Scheduling — one owner" reads "Scheduling: one owner"."""
    text = _DASH.sub(": ", (text or "").strip())
    return re.sub(r"^[:\s]+|[:\s]+$", "", re.sub(r":\s*:", ":", text))


def sentence(text: str) -> str:
    """Running text: a comma, or a full stop before a capital letter."""
    text = (text or "").strip()

    def swap(match: re.Match) -> str:
        before, after = text[:match.start()], text[match.end():]
        if not before.strip() or not after.strip():
            return " " if before.strip() and after.strip() else ""
        if before.rstrip()[-1] in ".!?:;,":
            return " "
        return ". " if after[0].isupper() else ", "

    return _DASH.sub(swap, text).strip()
