"""Setting a scorecard up: pages, KPIs, the week start, and the starter KPIs
an empty scorecard offers. Only the practice owner and associates do any of
this (decided after the mock-up); the route asks `Reader.sets_up` first.

Every change is in the audit trail with who made it, and shows in Activity
(spec, "Rules that hold everywhere"): a KPI or page created, changed,
archived or restored, and the week start changed.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Audience, Kpi, KpiMonthTarget, KpiPerson, Scorecard, ScorecardPage

FIRST_PAGE = "Weekly scorecard"


class SetupError(ValueError):
    """Something asked of the setup that cannot be, said in words."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def audit(company, actor, verb, **payload):
    from apps.tenancy.models import AuditEvent

    AuditEvent.objects.create(tenant_id=company.tenant_id, actor=actor, verb=verb,
                              target_type="company", target_id=company.pk, payload=payload)


def ensure(company, actor) -> Scorecard:
    """The company's scorecard, made with its first page if it has none."""
    found = Scorecard.objects.filter(company=company).first()
    if found is not None:
        return found
    scorecard = Scorecard.objects.create(tenant_id=company.tenant_id, company=company,
                                         created_by=actor)
    page = ScorecardPage.objects.create(tenant_id=company.tenant_id, scorecard=scorecard,
                                        name=FIRST_PAGE, created_by=actor)
    audit(company, actor, "scorecard.page_created", name=page.name, page=str(page.pk))
    return scorecard


def set_week_start(scorecard, value, actor):
    if value not in Scorecard.WeekStart.values:
        raise SetupError("A week starts on Monday or on Sunday.", "week_start")
    if value != scorecard.week_start:
        old, scorecard.week_start = scorecard.week_start, value
        scorecard.save(update_fields=["week_start", "updated_at"])
        audit(scorecard.company, actor, "scorecard.week_start_changed",
              **{"from": old, "to": value})
    return scorecard


# ------------------------------------------------------------------ pages

def _team(company, team_id):
    from apps.work import teams

    team = teams.team_of_company(company, team_id) if team_id else None
    if team is None:
        raise SetupError("Choose one of the company's teams.", "team")
    return team


def _page_fields(company, data, page=None) -> dict:
    out = {}
    if "name" in data or page is None:
        name = " ".join(str(data.get("name") or "").split())[:80]
        if not name:
            raise SetupError("A page needs a name.", "name")
        out["name"] = name
    if "audience" in data or page is None:
        audience = data.get("audience") or Audience.EVERYONE
        if audience not in Audience.values:
            raise SetupError("Choose who sees the page.", "audience")
        out["audience"] = audience
        out["team"] = _team(company, data.get("team")) if audience == Audience.TEAM else None
    return out


@transaction.atomic
def create_page(scorecard, data, actor) -> ScorecardPage:
    fields = _page_fields(scorecard.company, data)
    last = ScorecardPage.objects.filter(scorecard=scorecard).aggregate(n=Max("position"))["n"]
    page = ScorecardPage.objects.create(tenant_id=scorecard.tenant_id, scorecard=scorecard,
                                        position=(last or 0) + 1, created_by=actor, **fields)
    audit(scorecard.company, actor, "scorecard.page_created", name=page.name, page=str(page.pk))
    return page


@transaction.atomic
def update_page(page, data, actor) -> ScorecardPage:
    fields = _page_fields(page.scorecard.company, data, page)
    changed = {k: v for k, v in fields.items() if getattr(page, k) != v}
    if changed:
        for k, v in changed.items():
            setattr(page, k, v)
        page.save(update_fields=list(changed) + ["updated_at"])
        audit(page.scorecard.company, actor, "scorecard.page_changed", name=page.name,
              page=str(page.pk), fields=sorted(changed))
    return page


def archive_page(page, actor, *, restore=False) -> ScorecardPage:
    if restore == (page.archived_at is None):
        return page
    if not restore and page.kpis.filter(archived_at__isnull=True).exists():
        raise SetupError("Move or archive this page's KPIs first.")
    page.archived_at = None if restore else timezone.now()
    page.save(update_fields=["archived_at", "updated_at"])
    audit(page.scorecard.company, actor,
          "scorecard.page_restored" if restore else "scorecard.page_archived",
          name=page.name, page=str(page.pk))
    return page


def order_pages(scorecard, ids, actor):
    pages = {str(p.pk): p for p in ScorecardPage.objects.filter(scorecard=scorecard)}
    if sorted(ids) != sorted(k for k, p in pages.items() if p.archived_at is None):
        raise SetupError("Give every live page once.")
    for i, pk in enumerate(ids):
        ScorecardPage.objects.filter(pk=pk).update(position=i + 1)
    audit(scorecard.company, actor, "scorecard.pages_reordered")


# ------------------------------------------------------------------- KPIs

def _decimal(data, key, *, required=False, label="a number"):
    raw = data.get(key)
    if raw is None or str(raw).strip() == "":
        if required:
            raise SetupError(f"Give {label}.", key)
        return None
    try:
        value = Decimal(str(raw).replace(",", "").replace("$", "").rstrip("%").strip())
    except InvalidOperation:
        raise SetupError(f"That isn't {label}.", key) from None
    if not value.is_finite() or abs(value) >= Decimal("1e12"):
        raise SetupError("That number is too large.", key)
    return value.quantize(Decimal("0.0001"))


def _choice(data, key, choices, default, label):
    value = data.get(key, default)
    if value in ("", None):
        value = default
    if value not in choices:
        raise SetupError(f"Choose {label}.", key)
    return value


def _owner(company, user_id):
    """A reading owner is someone at the practice or a portal user of the
    company."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if not user_id:
        return None
    rows = Membership.objects.filter(user_id=user_id, revoked_at__isnull=True)
    for m in rows:
        if m.role not in CLIENT_ROLES or m.client_company_id == company.pk:
            return m.user
    raise SetupError("The reading owner is someone at the practice or at the company.",
                     "reading_owner")


def _people(company, ids):
    from apps.tenancy.models import CLIENT_ROLES, Membership

    ids = [str(i) for i in (ids or [])]
    found = list(Membership.objects.filter(pk__in=ids, client_company=company,
                                           role__in=CLIENT_ROLES, revoked_at__isnull=True))
    if len(found) != len(set(ids)):
        raise SetupError("Each person tracked is a portal user of the company.", "people")
    return found


def clean_kpi(scorecard, data, kpi=None) -> dict:
    """The fields of a KPI from what was sent, checked together. With `kpi`,
    the fields not sent keep their values."""
    company = scorecard.company

    def current(key, fallback=None):
        return getattr(kpi, key) if kpi is not None else fallback

    merged = {}
    keys = ("name", "kind", "direction", "cadence", "rollup", "target_value", "range_low",
            "range_high", "behind_band_pct", "duration_unit", "rating_scale",
            "reading_owner", "per_person", "person_total", "leaderboard", "tile",
            "audience", "audience_team", "note", "strategy_component", "page")
    for key in keys:
        if key in data:
            merged[key] = data[key]
    out = {}
    name = " ".join(str(merged.get("name", current("name", "")) or "").split())[:120]
    if not name:
        raise SetupError("A KPI needs a name.", "name")
    out["name"] = name
    out["kind"] = _choice(merged, "kind", Kpi.Kind.values, current("kind", "number"),
                          "what kind of number it is")
    out["direction"] = _choice(merged, "direction", Kpi.Direction.values,
                               current("direction", "higher"), "which way is better")
    out["cadence"] = _choice(merged, "cadence", Kpi.Cadence.values,
                             current("cadence", "weekly"), "how often it is entered")
    out["rollup"] = _choice(merged, "rollup", Kpi.Rollup.values, current("rollup", "sum"),
                            "how readings combine")
    out["tile"] = _choice(merged, "tile", Kpi.Tile.values, current("tile", "number_trend"),
                          "a tile")
    for key in ("target_value", "range_low", "range_high", "behind_band_pct"):
        out[key] = _decimal(merged, key) if key in merged else current(key)
    if out["behind_band_pct"] is None:
        out["behind_band_pct"] = Decimal(10)
    if not (0 <= out["behind_band_pct"] <= 100):
        raise SetupError("Behind is a percent from 0 to 100.", "behind_band_pct")
    if out["direction"] == "range":
        if out["range_low"] is None or out["range_high"] is None:
            raise SetupError("A range needs a low and a high.", "range_low")
        if out["range_low"] > out["range_high"]:
            raise SetupError("The low end of the range comes before the high end.",
                             "range_low")
    else:
        out["range_low"] = out["range_high"] = None
    if out["kind"] == "duration":
        out["duration_unit"] = _choice(merged, "duration_unit", Kpi.DurationUnit.values,
                                       current("duration_unit") or "hours", "hours or minutes")
    else:
        out["duration_unit"] = ""
    if out["kind"] == "rating":
        scale = merged.get("rating_scale", current("rating_scale") or 5)
        if str(scale) not in ("5", "10"):
            raise SetupError("A rating is out of 5 or out of 10.", "rating_scale")
        out["rating_scale"] = int(scale)
    else:
        out["rating_scale"] = None
    out["per_person"] = bool(merged.get("per_person", current("per_person", False)))
    out["person_total"] = _choice(merged, "person_total", Kpi.PersonTotal.values,
                                  current("person_total", "sum"), "sum or average")
    out["leaderboard"] = bool(merged.get("leaderboard", current("leaderboard", False))) \
        and out["per_person"]
    if not out["per_person"] and out["tile"] in ("leaderboard", "my_row"):
        raise SetupError("The Leaderboard and My row tiles are for per-person KPIs.", "tile")
    audience = _choice(merged, "audience", Kpi.KpiAudience.values,
                       current("audience", "page"), "who sees it")
    if audience == "each_person" and not out["per_person"]:
        raise SetupError("Each person sees their own is for per-person KPIs.", "audience")
    out["audience"] = audience
    if audience == "team":
        team_id = merged.get("audience_team", current("audience_team_id"))
        out["audience_team"] = _team(company, team_id)
    else:
        out["audience_team"] = None
    if "reading_owner" in merged:
        out["reading_owner"] = _owner(company, merged.get("reading_owner"))
    elif kpi is None:
        out["reading_owner"] = None
    out["note"] = str(merged.get("note", current("note", "")) or "").strip()[:200]
    component = merged.get("strategy_component", current("strategy_component", "")) or ""
    if component and component not in Kpi.Component.values:
        raise SetupError("Choose one of the six components.", "strategy_component")
    out["strategy_component"] = component
    page_id = merged.get("page", current("page_id"))
    page = ScorecardPage.objects.filter(scorecard=scorecard, pk=page_id,
                                        archived_at__isnull=True).first() \
        if page_id and _is_uuid(page_id) else None
    if page is None:
        raise SetupError("Choose a page of this scorecard.", "page")
    out["page"] = page
    return out


def _is_uuid(value) -> bool:
    from apps.work.views import _is_uuid as check

    return check(str(value))


def _months(data):
    """{"1": "70", ...} or [{"month": 1, "value": 70}]: month targets."""
    raw = data.get("month_targets")
    if raw is None:
        return None
    items = raw.items() if isinstance(raw, dict) else [
        (r.get("month"), r.get("value")) for r in raw if isinstance(r, dict)]
    out = {}
    for month, value in items:
        try:
            month = int(month)
        except (TypeError, ValueError):
            raise SetupError("A month is 1 to 12.", "month_targets") from None
        if not 1 <= month <= 12:
            raise SetupError("A month is 1 to 12.", "month_targets")
        if value is None or str(value).strip() == "":
            continue
        out[month] = _decimal({"v": value}, "v", label="a target")
    return out


def _set_months(kpi, months):
    if months is None:
        return False
    before = {t.month: t.value for t in kpi.month_targets.all()}
    if before == months:
        return False
    kpi.month_targets.all().delete()
    KpiMonthTarget.objects.bulk_create([
        KpiMonthTarget(tenant_id=kpi.tenant_id, kpi=kpi, month=m, value=v)
        for m, v in sorted(months.items())])
    return True


def _set_people(kpi, people):
    if people is None:
        return False
    before = set(kpi.people.values_list("membership_id", flat=True))
    after = {m.pk for m in people}
    if before == after:
        return False
    kpi.people.exclude(membership_id__in=after).delete()
    KpiPerson.objects.bulk_create([KpiPerson(tenant_id=kpi.tenant_id, kpi=kpi, membership=m)
                                   for m in people if m.pk not in before])
    return True


@transaction.atomic
def create_kpi(scorecard, data, actor) -> Kpi:
    fields = clean_kpi(scorecard, data)
    months = _months(data)
    people = _people(scorecard.company, data.get("people")) if fields["per_person"] else []
    last = Kpi.objects.filter(page=fields["page"]).aggregate(n=Max("position"))["n"]
    kpi = Kpi.objects.create(tenant_id=scorecard.tenant_id, scorecard=scorecard,
                             position=(last or 0) + 1, created_by=actor, **fields)
    _set_months(kpi, months)
    _set_people(kpi, people)
    audit(scorecard.company, actor, "scorecard.kpi_created", name=kpi.name, kpi=str(kpi.pk))
    return kpi


@transaction.atomic
def update_kpi(kpi, data, actor) -> Kpi:
    fields = clean_kpi(kpi.scorecard, data, kpi)
    changed = [k for k, v in fields.items()
               if getattr(kpi, k if k not in ("page", "audience_team", "reading_owner")
                          else k + "_id") != (v.pk if hasattr(v, "pk") else v)]
    for k in changed:
        setattr(kpi, k, fields[k])
    if "page" in changed:
        last = Kpi.objects.filter(page=fields["page"]).aggregate(n=Max("position"))["n"]
        kpi.position = (last or 0) + 1
        changed.append("position")
    if changed:
        kpi.save(update_fields=changed + ["updated_at"])
    people = None
    if "people" in data:
        people = _people(kpi.scorecard.company, data.get("people")) if kpi.per_person else []
    elif not kpi.per_person:
        people = []
    touched = _set_months(kpi, _months(data)) | _set_people(kpi, people)
    if changed or touched:
        audit(kpi.scorecard.company, actor, "scorecard.kpi_changed", name=kpi.name,
              kpi=str(kpi.pk), fields=sorted(set(changed) - {"position"})
              + (["targets or people"] if touched else []))
    return kpi


def archive_kpi(kpi, actor, *, restore=False) -> Kpi:
    """Archived: its readings kept, its tile gone. Restored: back on its page,
    or the first live page when its own is archived."""
    if restore == (kpi.archived_at is None):
        return kpi
    if restore and kpi.page.archived_at is not None:
        page = ScorecardPage.objects.filter(scorecard=kpi.scorecard,
                                            archived_at__isnull=True).first()
        if page is None:
            raise SetupError("Restore a page first.")
        kpi.page = page
    kpi.archived_at = None if restore else timezone.now()
    kpi.save(update_fields=["archived_at", "page", "updated_at"])
    audit(kpi.scorecard.company, actor,
          "scorecard.kpi_restored" if restore else "scorecard.kpi_archived",
          name=kpi.name, kpi=str(kpi.pk))
    return kpi


def order_kpis(page, ids, actor):
    live = {str(k.pk) for k in page.kpis.filter(archived_at__isnull=True)}
    if sorted(ids) != sorted(live):
        raise SetupError("Give every KPI on the page once.")
    for i, pk in enumerate(ids):
        Kpi.objects.filter(pk=pk, page=page).update(position=i + 1)
    audit(page.scorecard.company, actor, "scorecard.kpis_reordered", name=page.name,
          page=str(page.pk))


def describe(kpi) -> dict:
    """A KPI's whole definition, for the practice's editor."""
    from .board import definition, num

    return {**definition(kpi),
            "position": kpi.position, "archived": kpi.archived_at is not None,
            "audience": kpi.audience,
            "audience_team": str(kpi.audience_team_id) if kpi.audience_team_id else None,
            "person_total": kpi.person_total, "target_value": num(kpi.target_value),
            "behind_band_pct": num(kpi.behind_band_pct),
            "reading_owner": str(kpi.reading_owner_id) if kpi.reading_owner_id else None,
            "strategy_component": kpi.strategy_component,
            "month_targets": {str(t.month): num(t.value) for t in kpi.month_targets.all()},
            "people": [str(p.membership_id) for p in kpi.people.all()]}


# ------------------------------------------------------- the starter KPIs

#: Decided after the mock-up: three per discipline, in Bryan's words.
STARTERS = {
    "operations": ("Operations", [
        ("on_time_delivery", {"name": "On-time delivery", "kind": "percent",
                              "direction": "higher", "cadence": "weekly",
                              "rollup": "average", "target_value": 95, "tile": "gauge",
                              "strategy_component": "process"}),
        ("cycle_time", {"name": "Cycle time", "kind": "duration", "duration_unit": "days",
                        "direction": "lower", "cadence": "weekly", "rollup": "average",
                        "target_value": 5, "tile": "line",
                        "strategy_component": "process"}),
        ("overtime_hours", {"name": "Overtime hours", "kind": "duration",
                            "duration_unit": "hours", "direction": "lower",
                            "cadence": "weekly", "rollup": "sum", "target_value": 40,
                            "tile": "number_trend", "strategy_component": "people"}),
    ]),
    "sales": ("Sales", [
        ("new_leads", {"name": "New leads", "kind": "count", "direction": "higher",
                       "cadence": "weekly", "rollup": "sum", "target_value": 25,
                       "tile": "bars", "strategy_component": "traction"}),
        ("proposals_sent", {"name": "Proposals sent", "kind": "count", "direction": "higher",
                            "cadence": "weekly", "rollup": "sum", "target_value": 5,
                            "tile": "bars", "strategy_component": "traction"}),
        ("close_rate", {"name": "Close rate", "kind": "percent", "direction": "higher",
                        "cadence": "monthly", "rollup": "average", "target_value": 30,
                        "tile": "gauge", "strategy_component": "traction"}),
    ]),
    "finance": ("Finance", [
        ("cash_on_hand", {"name": "Cash on hand", "kind": "money", "direction": "higher",
                          "cadence": "weekly", "rollup": "last", "target_value": 100000,
                          "tile": "line", "strategy_component": "data"}),
        ("days_sales_outstanding", {"name": "Days sales outstanding", "kind": "duration",
                                    "duration_unit": "days", "direction": "lower",
                                    "cadence": "monthly", "rollup": "last",
                                    "target_value": 45, "tile": "number_trend",
                                    "strategy_component": "data"}),
        ("gross_margin", {"name": "Gross margin", "kind": "percent", "direction": "higher",
                          "cadence": "monthly", "rollup": "average", "target_value": 40,
                          "tile": "gauge", "strategy_component": "data"}),
    ]),
    "service": ("Service", [
        ("response_time", {"name": "Response time", "kind": "duration",
                           "duration_unit": "minutes", "direction": "lower",
                           "cadence": "weekly", "rollup": "average", "target_value": 15,
                           "tile": "number_trend", "strategy_component": "process"}),
        ("customer_rating", {"name": "Customer rating", "kind": "rating", "rating_scale": 5,
                             "direction": "higher", "cadence": "weekly",
                             "rollup": "average", "target_value": "4.5", "tile": "gauge",
                             "strategy_component": "people"}),
        ("first_contact_resolution", {"name": "First-contact resolution", "kind": "percent",
                                      "direction": "higher", "cadence": "weekly",
                                      "rollup": "average", "target_value": 75,
                                      "tile": "number_trend",
                                      "strategy_component": "process"}),
    ]),
}


def starters() -> list:
    return [{"discipline": key, "name": name,
             "kpis": [{"key": k, **{f: v for f, v in d.items()}} for k, d in kpis]}
            for key, (name, kpis) in STARTERS.items()]


def create_starter(company, key, actor) -> Kpi:
    for _, kpis in STARTERS.values():
        for k, data in kpis:
            if k == key:
                scorecard = ensure(company, actor)
                page = ScorecardPage.objects.filter(scorecard=scorecard,
                                                    archived_at__isnull=True).first()
                if page is None:
                    page = create_page(scorecard, {"name": FIRST_PAGE}, actor)
                return create_kpi(scorecard, {**data, "page": str(page.pk)}, actor)
    raise SetupError("Not one of the starter KPIs.", "key")
