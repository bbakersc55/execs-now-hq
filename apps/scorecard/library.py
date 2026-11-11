"""The KPI library (P8): every practice's, offered "From the library"
wherever a KPI is made. Four pages: Customers, Operations, Team, Money.

Three layers, read together:

1. **The base library**, here: the same for every practice.
2. **Each Command Center the practice has on** adds its own list on top
   (`apps/centers/content/<code>.py`, `KPIS`).
3. **The practice's own entries** (`KpiLibraryEntry`): new ones, or its edited
   copy of a shipped one (`source_key`), which then stands in for it.

Using an entry makes nothing: it fills in the KPI form, and the KPI is made
when the form is saved, as the practice's own. Existing KPIs are never
touched by any of this.
"""

from __future__ import annotations

PAGES = [("customers", "Customers"), ("operations", "Operations"), ("team", "Team"),
         ("money", "Money")]


def e(key, page, name, kind, direction, cadence, rollup, guidance, feeds, **more):
    return {"key": key, "page": page, "name": name, "kind": kind, "direction": direction,
            "cadence": cadence, "rollup": rollup, "guidance": guidance, "feeds": feeds, **more}


BASE = [
    # Customers
    e("customer_rating", "customers", "Customer rating", "rating", "higher", "monthly",
      "average", "On track at 4.6 or more out of 5; behind within 5%.", ["reviews", "sheet"],
      rating_scale=5, behind_band_pct=5, target_value="4.6"),
    e("review_count", "customers", "Review count", "count", "higher", "monthly", "sum",
      "On track at the month's target; behind within 20%.", ["reviews", "besty", "track"],
      behind_band_pct=20),
    e("five_star_share", "customers", "Five-star share", "percent", "higher", "monthly",
      "average", "On track at 85% or more; behind within 5 points.", ["reviews"],
      behind_band_pct=5),
    e("complaints_per_100", "customers", "Complaints per 100 jobs", "number", "lower",
      "monthly", "average", "On track at 2 or fewer; behind within 25%.", ["sheet"],
      behind_band_pct=25),
    e("retention_rate", "customers", "Renewal or retention rate", "percent", "higher",
      "quarterly", "last", "On track at 90% or more; behind within 5 points.",
      ["sheet", "hubspot"], behind_band_pct=5),
    e("nps", "customers", "Net promoter score", "number", "higher", "quarterly", "last",
      "On track at 50 or more; behind within 20%.", ["sheet"], behind_band_pct=20),
    # Operations
    e("on_time_completion", "operations", "On-time completion rate", "percent", "higher",
      "weekly", "average", "On track at 95% or more; behind within 5%.",
      ["sheet", "track", "besty"], behind_band_pct=5),
    e("jobs_per_week", "operations", "Jobs or units per week", "count", "higher", "weekly",
      "sum", "On track at the week's target; behind within 10%.", ["sheet", "track"]),
    e("rework_rate", "operations", "Rework or callback rate", "percent", "lower", "weekly",
      "average", "On track at 3% or less; behind within 25%.", ["sheet", "besty"],
      behind_band_pct=25),
    e("open_work_orders", "operations", "Open work orders", "count", "lower", "weekly", "last",
      "On track at or under the target; behind within 15%.", ["track", "besty", "sheet"],
      behind_band_pct=15),
    e("days_to_close_wo", "operations", "Days to close a work order", "duration", "lower",
      "weekly", "average", "On track at 3 days or fewer; behind within 25%.",
      ["track", "sheet"], duration_unit="days", behind_band_pct=25),
    e("utilization", "operations", "Utilization or occupancy", "percent", "higher", "weekly",
      "average", "On track at the target; behind within 5 points.", ["track", "sheet"],
      behind_band_pct=5),
    e("cycle_time", "operations", "Cycle time", "duration", "lower", "weekly", "average",
      "On track at or under the target; behind within 10%.", ["sheet"],
      duration_unit="days"),
    e("inspection_pass_rate", "operations", "Inspection pass rate", "percent", "higher",
      "weekly", "average", "On track at 98% or more; behind within 2 points.", ["sheet"],
      behind_band_pct=2),
    e("safety_incidents", "operations", "Safety incidents", "count", "lower", "monthly", "sum",
      "On track at zero; any one is off track.", ["sheet"], behind_band_pct=0,
      target_value="0"),
    # Team
    e("headcount_vs_plan", "team", "Headcount against plan", "count", "range", "monthly",
      "last", "Healthy within the plan's range.", ["sheet"]),
    e("voluntary_turnover", "team", "Voluntary turnover", "percent", "lower", "quarterly",
      "sum", "On track at 5% a quarter or less; behind within 20%.", ["sheet"],
      behind_band_pct=20),
    e("time_to_fill", "team", "Time to fill", "duration", "lower", "monthly", "average",
      "On track at 30 days or fewer; behind within 20%.", ["sheet"], duration_unit="days",
      behind_band_pct=20),
    e("overtime_hours", "team", "Overtime hours", "number", "lower", "weekly", "sum",
      "On track at or under the target; behind within 15%.", ["sheet"], behind_band_pct=15),
    e("absenteeism", "team", "No-shows or absenteeism", "count", "lower", "weekly", "sum",
      "On track at or under the target; behind within 25%.", ["sheet"], behind_band_pct=25),
    e("training_completion", "team", "Training completion", "percent", "higher", "monthly",
      "last", "On track at 100% of assigned training; behind within 10 points.", ["sheet"]),
    # Money
    e("revenue", "money", "Revenue", "money", "higher", "monthly", "sum",
      "On track at the month's target; behind within 10%.", ["sheet", "track", "hubspot"]),
    e("gross_margin", "money", "Gross margin", "percent", "higher", "monthly", "average",
      "On track at the target margin; behind within 3 points.", ["sheet"], behind_band_pct=3),
    e("net_margin", "money", "Net margin", "percent", "higher", "monthly", "average",
      "On track at the target margin; behind within 3 points.", ["sheet"], behind_band_pct=3),
    e("cash_on_hand", "money", "Cash on hand", "money", "higher", "weekly", "last",
      "On track at or above the cash floor; behind within 10%.", ["sheet"]),
    e("dso", "money", "Days sales outstanding", "duration", "lower", "monthly", "average",
      "On track at 35 days or fewer; behind within 15%.", ["sheet"], duration_unit="days",
      behind_band_pct=15),
    e("overdue_invoices", "money", "Overdue invoices", "money", "lower", "weekly", "last",
      "On track at or under the target; behind within 20%.", ["sheet"], behind_band_pct=20),
    e("labor_cost_pct", "money", "Labor cost percentage", "percent", "lower", "monthly",
      "average", "On track at or under the target; behind within 2 points.", ["sheet"],
      behind_band_pct=2),
    e("revenue_per_employee", "money", "Revenue per employee", "money", "higher", "quarterly",
      "last", "On track at the target; behind within 10%.", ["sheet"]),
]

FIELDS = ("name", "kind", "direction", "cadence", "rollup", "duration_unit", "rating_scale",
          "behind_band_pct", "guidance", "feeds", "target_value", "range_low", "range_high")


def _row(entry, *, source, center="", center_name="", entry_id=None) -> dict:
    return {"id": entry_id, "key": entry.get("key", ""), "page": entry["page"],
            "source": source, "center": center, "center_name": center_name,
            **{f: entry.get(f) for f in FIELDS}}


def entries(tenant) -> list[dict]:
    """Every entry this practice is offered, by page, shipped first."""
    from apps.centers import catalog, services
    from apps.scorecard.models import KpiLibraryEntry

    own = list(KpiLibraryEntry.all_objects.filter(tenant=tenant, archived_at__isnull=True)
               .order_by("name"))
    replaced = {row.source_key for row in own if row.source_key}
    on = set(services.enabled(tenant.pk))
    out = [_row(entry, source="base") for entry in BASE if entry["key"] not in replaced]
    out += [_row(entry, source="center", center=entry["center"],
                 center_name=catalog.NAMES[entry["center"]])
            for entry in catalog.shipped_kpis()
            if entry["center"] in on and entry["key"] not in replaced]
    out += [_row({"key": row.source_key, "page": row.page,
                  **{f: getattr(row, f, None) for f in FIELDS}},
                 source="practice", entry_id=str(row.pk)) for row in own]
    return out


def shipped(key: str) -> dict | None:
    from apps.centers import catalog

    return next((entry for entry in BASE + catalog.shipped_kpis() if entry["key"] == key),
                None)


def kpi_fields(entry: dict) -> dict:
    """What the KPI form is filled with from an entry: `setup.clean_kpi`'s
    names. The guidance goes on the tile's back ("How it's measured")."""
    out = {f: entry[f] for f in ("name", "kind", "direction", "cadence", "rollup")}
    for f in ("duration_unit", "rating_scale", "target_value", "range_low", "range_high"):
        if entry.get(f) not in (None, ""):
            out[f] = entry[f]
    out["behind_band_pct"] = entry.get("behind_band_pct", 10)
    if entry.get("guidance"):
        out["note"] = entry["guidance"][:200]
    return out
