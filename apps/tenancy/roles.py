"""What each role is called wherever a person reads it (P1, owner 2026-10-02).

The codes stay in code and data. These names are the only thing shown. The
frontend's twin is `frontend/src/lib/roles.ts`, and
`tests/test_vocabulary.py` keeps the two identical.
"""

from __future__ import annotations

ROLE_LABEL = {
    "FF": "Practice owner",
    "CF": "Associate",
    "VA": "Assistant",
    "FCC": "Client owner",
    "ECC": "Client team member",
}

#: Shown for a code this list does not know: never the code itself.
UNKNOWN_ROLE = "Team member"


def role_label(code: str | None) -> str:
    return ROLE_LABEL.get(code or "", UNKNOWN_ROLE)
