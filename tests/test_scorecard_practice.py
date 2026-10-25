"""The practice's own scorecard ("My practice") and its feed "From this app".

The measures against known data, per period; the practice's audiences
(everyone, the owner and associates, each their own, the owner only); the
money measures for the practice owner alone; the hidden company row never
showing as a company; the feed rules shared with Sheets and Track; and that
one practice's measures read nothing of another's.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone as tz
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.crm.models import Company, Referral, StageChange
from apps.crm.services import pipeline
from apps.scorecard import feeds, practice, setup
from apps.scorecard.models import Kpi, KpiAppFeed, KpiReading
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactFactory, ContactTypeLinkFactory, MembershipFactory,
    TenantFactory,
)

pytestmark = pytest.mark.django_db
OCT_1, OCT_31 = date(2026, 10, 1), date(2026, 10, 31)


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=tz.utc)


def move(contact, stage, when):
    pipeline.change_stage(contact, stage)
    StageChange.all_objects.filter(contact=contact, to_stage=stage).update(created_at=when)


@pytest.fixture
def books(seeded_tenant, sales, stages, types, ff):
    """October: three leads in, two proposals, one won and one lost, a
    partner added, two introductions; one move in September, one in November."""
    t = seeded_tenant
    t.timezone = "UTC"
    t.save(update_fields=["timezone"])
    people = [ContactFactory(tenant=t, first_name=f"P{i}") for i in range(5)]
    move(people[0], stages["initial_contact_made"], at(date(2026, 9, 20)))
    for p in people[1:4]:
        move(p, stages["initial_contact_made"], at(date(2026, 10, 3)))
    move(people[1], stages["proposal_given"], at(date(2026, 10, 10)))
    move(people[2], stages["proposal_given"], at(date(2026, 10, 12)))
    move(people[1], stages["closed_won"], at(date(2026, 10, 20)))
    move(people[2], stages["closed_lost"], at(date(2026, 10, 22)))
    move(people[4], stages["initial_contact_made"], at(date(2026, 11, 2)))
    partner = ContactFactory(tenant=t, first_name="Pat")
    link = ContactTypeLinkFactory(tenant=t, contact=partner, contact_type=types["referral_partner"])
    type(link).all_objects.filter(pk=link.pk).update(created_at=at(date(2026, 10, 15)))
    referral_pipeline = pipeline.referral_pipeline(t)
    for day in (date(2026, 10, 5), date(2026, 10, 25), date(2026, 9, 5)):
        Referral.all_objects.create(tenant=t, direction="outbound", referrer=partner,
                                    prospect=people[3], pipeline=referral_pipeline,
                                    referred_on=day)
    return {"t": t, "people": people, "stages": stages}


@pytest.mark.parametrize("measure,expected", [
    ("new_leads", Decimal("3")), ("proposals_given", Decimal("2")), ("won", Decimal("1")),
    ("lost", Decimal("1")), ("close_rate", Decimal("50.0")),
    ("partners_added", Decimal("1")), ("introductions_made", Decimal("2")),
])
def test_the_pipeline_measures_for_a_month(books, measure, expected):
    assert practice.value_for(measure, books["t"], OCT_1, OCT_31) == expected


def test_prospects_in_a_stage_at_the_periods_end(books):
    stages = books["stages"]
    t = books["t"]
    # At the end of October: P0 and P3 in Initial Contact Made (P4 joined in November).
    assert practice.value_for("prospects_in_stage", t, OCT_1, OCT_31,
                              param=str(stages["initial_contact_made"].pk)) == 2
    assert practice.value_for("prospects_in_stage", t, OCT_1, OCT_31,
                              param=str(stages["closed_won"].pk)) == 1
    with pytest.raises(practice.MeasureRefused):
        practice.value_for("prospects_in_stage", t, OCT_1, OCT_31)


def test_close_rate_over_nothing_is_no_reading(books):
    assert practice.value_for("close_rate", books["t"], date(2026, 8, 1), date(2026, 8, 31)) \
        is None


def test_tasks_completed_and_overdue(books, ff):
    from apps.crm.models import Task
    from apps.work.models import TaskUpdate

    t = books["t"]
    done = Task.all_objects.create(tenant=t, title="Done in October", status="done",
                                   due_date=date(2026, 10, 10))
    late_done = Task.all_objects.create(tenant=t, title="Done in November", status="done",
                                        due_date=date(2026, 10, 10))
    still = Task.all_objects.create(tenant=t, title="Still open", status="not_started",
                                    due_date=date(2026, 10, 12))
    Task.all_objects.filter(pk__in=[done.pk, late_done.pk, still.pk]).update(
        created_at=at(date(2026, 10, 1)))
    for task, day in ((done, date(2026, 10, 9)), (late_done, date(2026, 11, 3))):
        row = TaskUpdate.all_objects.create(tenant=t, task=task, kind="status_changed",
                                            to_value="done")
        TaskUpdate.all_objects.filter(pk=row.pk).update(created_at=at(day))
    assert practice.value_for("tasks_completed", t, OCT_1, OCT_31) == 1
    # At October's end: the one still open and the one done only in November.
    assert practice.value_for("tasks_overdue", t, OCT_1, OCT_31) == 2


def test_invoice_measures(books, ff, fcc):
    from apps.billing.models import ClientInvoice, ClientPayment

    t = books["t"]
    company = fcc.client_company
    payer = ContactFactory(tenant=t, company=company)

    def invoice(sent, due, total, payments=()):
        inv = ClientInvoice.all_objects.create(
            tenant=t, client_company=company, contact=payer, kind="one_off", status="sent",
            number=f"N{ClientInvoice.all_objects.count() + 1}", issue_date=sent, due_date=due,
            subtotal_cents=total, total_cents=total)
        ClientInvoice.all_objects.filter(pk=inv.pk).update(sent_at=at(sent))
        for day, cents in payments:
            ClientPayment.all_objects.create(tenant=t, invoice=inv, amount_cents=cents,
                                             paid_on=day)
        return inv

    invoice(date(2026, 10, 1), date(2026, 10, 15), 10000, [(date(2026, 10, 11), 10000)])
    invoice(date(2026, 10, 5), date(2026, 10, 20), 20000, [(date(2026, 10, 10), 5000),
                                                         (date(2026, 10, 26), 15000)])
    invoice(date(2026, 10, 8), date(2026, 10, 22), 30000)                  # overdue at the end
    invoice(date(2026, 9, 20), date(2026, 10, 5), 5000, [(date(2026, 11, 2), 5000)])  # overdue too
    assert practice.value_for("invoices_sent", t, OCT_1, OCT_31) == 3
    assert practice.value_for("invoices_paid", t, OCT_1, OCT_31) == 2
    # 10 days and 21 days to pay in full.
    assert practice.value_for("days_to_pay", t, OCT_1, OCT_31) == Decimal("15.5")
    assert practice.value_for("invoices_overdue", t, OCT_1, OCT_31) == 2


def test_cash_measures_need_the_forecast_and_say_so(books):
    with pytest.raises(practice.MeasureRefused, match="cash forecast"):
        practice.value_for("cash_on_hand", books["t"], OCT_1, OCT_31)


# ---------------------------------------------------------------- the scorecard

@pytest.fixture
def mine(books, ff, api):
    t = books["t"]
    cf = MembershipFactory(tenant=t, role="CF")
    va = MembershipFactory(tenant=t, role="VA")
    holder = practice.practice_company(t)
    with tenant_context(t.pk):
        card = setup.ensure(holder, ff.user)
        first = card.pages.get()
        leaders = setup.create_page(card, {"name": "Owner and associates", "audience": "leadership"},
                                    ff.user)
        owner_page = setup.create_page(card, {"name": "Mine", "audience": "owner"}, ff.user)

        def kpi(name, page, **extra):
            return setup.create_kpi(card, {"name": name, "kind": "count", "cadence": "monthly",
                                           "page": str(page.pk), **extra}, ff.user)

        kpis = {"leads": kpi("New leads", first), "won": kpi("Won", leaders),
                "private": kpi("Owner's", owner_page),
                "sent": kpi("Invoices sent", first),
                "calls": kpi("Calls", first, per_person=True, audience="each_person",
                             people=[str(cf.pk), str(va.pk)])}
    return {"t": t, "holder": holder, "card": card, "kpis": kpis, "ff": ff, "cf": cf, "va": va,
            "api": api}


def names(api, who, holder):
    data = api.as_(who).get(f"/api/scorecard/?company={holder.pk}&window=last_year").json()
    out = set()
    for page in data["pages"]:
        page_data = api.as_(who).get(
            f"/api/scorecard/?company={holder.pk}&window=last_year&page={page['id']}").json()
        out |= {t["name"] for t in page_data["kpis"]}
    return out


def put_app(m, who, kpi, measure, **extra):
    return m["api"].as_(who).put("/api/scorecard/app-feed/", json.dumps({
        "company": str(m["holder"].pk), "kpi": str(kpi.pk), "measure": measure, **extra}),
        content_type="application/json")


def test_every_practice_user_reaches_my_practice_and_sees_by_the_practices_audiences(mine, fcc):
    m = mine
    api = m["api"]
    assert api.as_(m["ff"]).get("/api/scorecard/practice/").json()["id"] == str(m["holder"].pk)
    assert put_app(m, m["ff"], m["kpis"]["sent"], "invoices_sent").status_code == 200
    every = {"New leads", "Won", "Owner's", "Invoices sent", "Calls"}
    assert names(api, m["ff"], m["holder"]) == every
    assert names(api, m["cf"], m["holder"]) == every - {"Owner's", "Invoices sent"}
    assert names(api, m["va"], m["holder"]) == {"New leads", "Calls"}
    # A client never reaches it.
    assert api.as_(fcc).get("/api/scorecard/practice/").status_code == 404
    assert api.as_(fcc).get(f"/api/scorecard/?company={m['holder'].pk}").status_code == 404


def test_an_assistant_is_sent_only_their_own_row(mine):
    m = mine
    with tenant_context(m["t"].pk):
        for who, value in ((m["cf"], 12), (m["va"], 7)):
            KpiReading.objects.create(tenant=m["t"], kpi=m["kpis"]["calls"],
                                      period_start=date(2026, 10, 1), membership=who,
                                      value=value, entered_at=timezone.now())
    data = m["api"].as_(m["va"]).get(
        f"/api/scorecard/?company={m['holder'].pk}&window=last_year").json()
    tile = next(t for t in data["kpis"] if t["name"] == "Calls")
    assert [r["membership"] for r in tile["rows"]] == [str(m["va"].pk)]


def test_the_hidden_company_is_never_a_company(mine, api):
    m = mine
    client = api.as_(m["ff"])
    listed = client.get("/api/companies/").json()
    rows = listed if isinstance(listed, list) else listed.get("results", [])
    assert str(m["holder"].pk) not in {r["id"] for r in rows}
    assert client.get(f"/api/companies/{m['holder'].pk}/").status_code == 404
    with tenant_context(m["t"].pk):
        assert not Company.objects.filter(is_practice=True).exists()
    # Typing the practice's name makes a real company, not the hidden row.
    made = client.post("/api/companies/", json.dumps({"name": m["t"].name}),
                       content_type="application/json")
    assert made.status_code == 201 and made.json()["id"] != str(m["holder"].pk)


def test_the_app_feed_writes_readings_by_the_feed_rules(mine):
    m = mine
    leads = m["kpis"]["leads"]
    with tenant_context(m["t"].pk):
        KpiReading.objects.create(tenant=m["t"], kpi=leads, period_start=date(2026, 9, 1),
                                  value=Decimal("9"), entered_at=timezone.now())
    from unittest import mock

    with mock.patch("apps.scorecard.views_app._today", return_value=date(2026, 11, 5)):
        saved = put_app(m, m["ff"], leads, "new_leads")
    assert saved.status_code == 200 and saved.json()["run"]["ok"], saved.content
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=leads)}
    assert got[OCT_1].value == 3 and got[OCT_1].source == "app"
    assert got[date(2026, 9, 1)].value == 9 and got[date(2026, 9, 1)].source == "hand"
    board = m["api"].as_(m["ff"]).get(
        f"/api/scorecard/?company={m['holder'].pk}&window=last_year").json()
    tile = next(t for t in board["kpis"] if t["name"] == "New leads")
    assert tile["feed"] == {"kind": "app", "text":
                            "From this app: New leads (entered Sales), worked out once a day",
                            "error": ""}


def test_what_the_app_feed_refuses(mine, ff, fcc, api):
    m = mine
    # The money measures are the owner's to set.
    assert "practice owner" in put_app(m, m["cf"], m["kpis"]["leads"], "invoices_sent").json()[
        "measure"]
    # The kind must fit; a stage measure needs a Sales stage.
    assert "fits a KPI of kind Percent" in put_app(m, m["ff"], m["kpis"]["won"],
                                                   "close_rate").json()["measure"]
    assert put_app(m, m["ff"], m["kpis"]["won"], "prospects_in_stage").status_code == 400
    # Never on a client's scorecard.
    with tenant_context(m["t"].pk):
        card = setup.ensure(fcc.client_company, ff.user)
        theirs = setup.create_kpi(card, {"name": "Leads", "kind": "count", "cadence": "monthly",
                                         "page": str(card.pages.get().pk)}, ff.user)
    response = api.as_(ff).put("/api/scorecard/app-feed/", json.dumps({
        "company": str(fcc.client_company_id), "kpi": str(theirs.pk), "measure": "new_leads"}),
        content_type="application/json")
    assert response.status_code == 404


def test_one_practices_measures_read_nothing_of_anothers(books, api):
    from apps.crm.seed import seed_tenant

    other = TenantFactory()
    seed_tenant(other)
    for measure in ("new_leads", "won", "partners_added", "introductions_made",
                    "invoices_sent", "tasks_completed"):
        assert practice.value_for(measure, other, OCT_1, OCT_31) == 0
    b = api.as_(MembershipFactory(tenant=other, role="FF"))
    theirs = b.get("/api/scorecard/practice/").json()["id"]
    assert theirs != str(practice.practice_company(books["t"]).pk)
    assert b.get(f"/api/scorecard/?company={practice.practice_company(books['t']).pk}"
                 ).status_code == 404
    assert feeds.run_due_app(other.pk, date(2026, 11, 5)) == {"ran": 0, "failed": 0}
