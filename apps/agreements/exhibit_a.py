"""Exhibit A's quantities, from the number of guests the Unit sleeps (owner,
2026-11-24). S is Sleeps, the owner's answer on the owner's page.

Each rule is one line of `RULES` below. The place settings rule was decided on
2026-11-24 (later): 1.5 × Sleeps up to 10, 2 × Sleeps from 11. Every other line
of Exhibit A stays as written, including the "per bedroom", "per bathroom" and
"per bed" lines.

Changing a rule changes the words of every agreement not yet signed. An
agreement whose owners signed under the old rule can't be countersigned
(its words no longer match theirs): the screen says so, and what to do.
"""

from __future__ import annotations

import math

#: quantity: (times S, by Sleeps: ((up to this Sleeps, times), ...; None = any more),
#:            rounded up to a multiple of, never fewer than)
RULES = {
    # P: 1.5 × S up to Sleeps 10, 2 × S from 11; up to a multiple of 4; at least 8
    "place_settings": (((10, 1.5), (None, 2)), 4, 8),
    # M: S, up to an even number; at least 4
    "place_mats": (((None, 1),), 2, 4),
}
#: Dinnerware: 5 × P pieces. Teaspoons: P + 4.
PIECES_PER_SETTING = 5
TEASPOONS_OVER = 4

#: Where the numbers go before the owner has answered Sleeps.
PLACEHOLDER = "[from Sleeps]"
#: The names the change list uses for them (texts/rental_management_changes.py).
COMPARE = {"place_settings": "[place settings]", "dinnerware_pieces": "[dinnerware pieces]",
           "teaspoons": "[teaspoons]", "place_mats": "[place mats]"}
KEYS = tuple(COMPARE)


def _rule(name: str, sleeps: int) -> int:
    bands, step, least = RULES[name]
    times = next(t for up_to, t in bands if up_to is None or sleeps <= up_to)
    return max(least, math.ceil(times * sleeps / step) * step)


def numbers(sleeps) -> dict | None:
    """{sleeps, place_settings, dinnerware_pieces, teaspoons, place_mats}, or
    None while Sleeps isn't answered."""
    try:
        s = int(str(sleeps).strip())
    except (TypeError, ValueError):
        return None
    if s < 1:
        return None
    p = _rule("place_settings", s)
    return {"sleeps": s, "place_settings": p, "dinnerware_pieces": PIECES_PER_SETTING * p,
            "teaspoons": p + TEASPOONS_OVER, "place_mats": _rule("place_mats", s)}


def values(sleeps) -> dict:
    """The template's variables: the numbers, or the placeholder."""
    found = numbers(sleeps)
    if found is None:
        return {k: PLACEHOLDER for k in KEYS}
    return {k: str(found[k]) for k in KEYS}


def said(found: dict) -> str:
    """"12 place settings and a set of 6 place mats", for a person."""
    return (f"{found['place_settings']} place settings, {found['teaspoons']} teaspoons and a "
            f"set of {found['place_mats']} place mats")
