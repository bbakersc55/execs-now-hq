"""The federal figures the tax estimate is worked out with (P6 M4 decision 21):
data with a year on it, never a rule in code. A year that is not here says
so, and the last year that is here is used, with a note (`for_year`).

Sources, as published by the IRS: 2025 brackets from Rev. Proc. 2024-40 and
the standard deduction as raised for 2025 by the 2025 budget act (P.L.
119-21); 2026 from Rev. Proc. 2025-32. The Social Security wage base is the
Social Security Administration's for each year. Every figure is in cents.

Add a year by adding a key: nothing else changes.
"""

from __future__ import annotations

#: Filing statuses, in the order the screen offers them.
STATUSES = {
    "single": "Single",
    "joint": "Married filing jointly",
    "separate": "Married filing separately",
    "head": "Head of household",
}

#: Self-employment tax (decision 21): 15.3% of 92.35% of net profit, half of
#: it deductible. The 12.4% Social Security part stops at the wage base; the
#: 2.9% Medicare part does not.
SE_SHARE = 0.9235
SE_SOCIAL_SECURITY = 0.124
SE_MEDICARE = 0.029

#: Safe harbor: 100% of last year's tax, or 110% when last year's adjusted
#: gross income was over this ($75,000 married filing separately).
SAFE_HARBOR_OVER = {"single": 15_000_000, "joint": 15_000_000, "separate": 7_500_000,
                    "head": 15_000_000}

#: `{year: {"brackets": {status: [(up to, rate), ...]}, "standard": {status:
#: cents}, "wage_base": cents}}`. A bracket's "up to" is the top of its band
#: of taxable income; the last band has none.
YEARS = {
    2025: {
        "brackets": {
            "single": [(1_192_500, 0.10), (4_847_500, 0.12), (10_335_000, 0.22),
                       (19_730_000, 0.24), (25_052_500, 0.32), (62_635_000, 0.35),
                       (None, 0.37)],
            "joint": [(2_385_000, 0.10), (9_695_000, 0.12), (20_670_000, 0.22),
                      (39_460_000, 0.24), (50_105_000, 0.32), (75_160_000, 0.35),
                      (None, 0.37)],
            "separate": [(1_192_500, 0.10), (4_847_500, 0.12), (10_335_000, 0.22),
                         (19_730_000, 0.24), (25_052_500, 0.32), (37_580_000, 0.35),
                         (None, 0.37)],
            "head": [(1_700_000, 0.10), (6_485_000, 0.12), (10_335_000, 0.22),
                     (19_730_000, 0.24), (25_050_000, 0.32), (62_635_000, 0.35),
                     (None, 0.37)],
        },
        "standard": {"single": 1_575_000, "joint": 3_150_000, "separate": 1_575_000,
                     "head": 2_362_500},
        "wage_base": 17_610_000,
    },
    2026: {
        "brackets": {
            "single": [(1_240_000, 0.10), (5_040_000, 0.12), (10_570_000, 0.22),
                       (20_177_500, 0.24), (25_622_500, 0.32), (64_060_000, 0.35),
                       (None, 0.37)],
            "joint": [(2_480_000, 0.10), (10_080_000, 0.12), (21_140_000, 0.22),
                      (40_355_000, 0.24), (51_245_000, 0.32), (76_870_000, 0.35),
                      (None, 0.37)],
            "separate": [(1_240_000, 0.10), (5_040_000, 0.12), (10_570_000, 0.22),
                         (20_177_500, 0.24), (25_622_500, 0.32), (38_435_000, 0.35),
                         (None, 0.37)],
            "head": [(1_770_000, 0.10), (6_745_000, 0.12), (10_570_000, 0.22),
                     (20_175_000, 0.24), (25_620_000, 0.32), (64_060_000, 0.35),
                     (None, 0.37)],
        },
        "standard": {"single": 1_610_000, "joint": 3_220_000, "separate": 1_610_000,
                     "head": 2_415_000},
        "wage_base": 18_450_000,
    },
}


def for_year(year: int) -> tuple[dict, int, str]:
    """The figures for `year`: `(figures, the year they are, a note)`. The
    note is empty when the year is here; otherwise it names the year used."""
    if year in YEARS:
        return YEARS[year], year, ""
    known = sorted(YEARS)
    used = max((y for y in known if y < year), default=known[0])
    return YEARS[used], used, (f"This app has no {year} tax brackets yet, so {used}'s are "
                               f"used. The estimate will be off by however much they "
                               f"changed.")


def income_tax(taxable_cents: int, brackets: list) -> int:
    """Tax on `taxable_cents` at `brackets`, band by band."""
    tax, floor = 0.0, 0
    for top, rate in brackets:
        if taxable_cents <= floor:
            break
        band = (taxable_cents if top is None else min(taxable_cents, top)) - floor
        tax += band * rate
        if top is None:
            break
        floor = top
    return int(round(tax))
