"""Contrast rules for a practice's two brand colors (P1, D4, owner 2026-10-02).

WCAG 2.x relative luminance and contrast ratio. Three rules:

- **primary vs white >= 4.5** (block): white text sits on the primary color
  in the email header, the portal sidebar and buttons.
- **accent vs primary >= 3** (block): the accent sits on the primary color as
  the active-nav rail and header bars.
- **accent vs white >= 3** (warn only): Executives Now's own orange is 2.59, so
  a hard rule would refuse it. The accent is therefore only ever fill and
  decoration, never text on white; text placed on an accent fill uses
  `text_on()`.

`frontend/src/lib/contrast.ts` mirrors this for the live preview. Both are
tested against `frontend/src/lib/contrast-reference.json`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
WHITE = "#FFFFFF"
NEAR_BLACK = "#1F2933"


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def ratio(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def text_on(fill: str) -> str:
    """White or near-black, whichever reads better on `fill`."""
    return WHITE if ratio(fill, WHITE) >= ratio(fill, NEAR_BLACK) else NEAR_BLACK


@dataclass(frozen=True)
class Check:
    rule: str
    label: str
    ratio: float
    required: float
    blocks: bool

    @property
    def ok(self) -> bool:
        return self.ratio >= self.required

    def as_dict(self):
        return {**asdict(self), "ratio": round(self.ratio, 2), "ok": self.ok}


def check(primary: str, accent: str) -> list[Check]:
    return [
        Check("primary_on_white", "Primary color against white",
              ratio(primary, WHITE), 4.5, True),
        Check("accent_on_primary", "Accent against the primary color",
              ratio(accent, primary), 3.0, True),
        Check("accent_on_white", "Accent against white (used as decoration only)",
              ratio(accent, WHITE), 3.0, False),
    ]


def blocking_failures(primary: str, accent: str) -> list[Check]:
    return [c for c in check(primary, accent) if c.blocks and not c.ok]
