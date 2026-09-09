"""Single source of truth for the product's display name and palette.

`CLAUDE.md`: "Keep the display name in a single config constant."
Served to the frontend as data (FR-0.6, FR-G5) so V1 per-tenant white-labelling
is a data change, not a code change.
"""

PRODUCT_NAME = "Execs NOW HQ"
PRODUCT_OWNER = "Executives Now"

PALETTE = {
    "dark_blue": "#0A3A65",
    "orange": "#F58220",
    "gray_dark": "#6D6E71",
    "gray_light": "#939598",
}
