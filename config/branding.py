"""Single source of truth for the product's display name and palette.

`CLAUDE.md`: "Keep the display name in a single config constant."
Served to the frontend as data (FR-0.6, FR-G5) so V1 per-tenant white-labelling
is a data change, not a code change.
"""

PRODUCT_NAME = "Execs NOW HQ"
PRODUCT_OWNER = "Executives Now"

PALETTE = {
    # The logo's palette since 2026-11-09 (was #0A3A65 / #F58220). The product's
    # own chrome only; a practice's brand is its own (Branding settings).
    "dark_blue": "#0D2C54",
    "orange": "#E87722",
    "gray_dark": "#6D6E71",
    "gray_light": "#939598",
}
