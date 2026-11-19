"""Scorecard priority, the AI apps' scorecard_readings over every page, and a
new client's 25 seats (Bryan, 2026-11-18).

- **Priority**: a KPI is Top, Medium or Low, Medium unless set; a page sends
  its KPIs Top first, then Medium, then Low, each group in the KPIs' own
  order, to the practice and to the portal alike.
- **scorecard_readings**: every page the person can see when no page is
  named, each KPI naming its page; one page by id or name; a page they can't
  see is refused, never sent. Another practice reaches nothing.
- **Seats**: a company that becomes a client with no seat count gets 25;
  one with a count keeps it; nothing changes for a company already a client.
"""

from __future__ import annotations

import json

import pytest

from apps.aiconnect import tools as T
from apps.crm.models import Company
from apps.crm.services import clients
from apps.scorecard import setup
from apps.scorecard.models import Kpi
from apps.tenancy.context import tenant_context
from apps.work import teams
from apps.work.models import ClientTeamMember

from . import registry_config  # noqa: F401
from .factories import (
    AiAppConnectionFactory, ClientCompanyFactory, CompanyFactory, MembershipFactory,
)

B = "/api/scorecard/"
L = ClientTeamMember.Level


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


@pytest.fixture
def pr(seeded_tenant, ff, api):
    """A company with a page of six KPIs made in the order A..F, two of them
    Top and two Low, and a second page for leadership only."""
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Northwind Foods", seat_count=10)
    member = MembershipFactory(tenant=tenant, role="ECC", client_company=company)
    ClientTeamMember.all_objects.filter(membership=member).delete()
    teams.place(teams.default_team(tenant.pk, company.pk), member, L.MEMBER)
    with tenant_context(tenant.pk):
        card = setup.ensure(company, ff.user)
        first = card.pages.get()
        leaders = setup.create_page(card, {"name": "Leaders", "audience": "leadership"},
                                    ff.user)

        def kpi(name, page, priority=None):
            data = {"name": name, "kind": "count", "cadence": "weekly", "rollup": "sum",
                    "page": str(page.pk)}
            if priority:
                data["priority"] = priority
            return setup.create_kpi(card, data, ff.user)

        made = [kpi("A low", first, "low"), kpi("B plain", first), kpi("C top", first, "top"),
                kpi("D low", first, "low"), kpi("E top", first, "top"),
                kpi("F plain", first, "medium"), kpi("Cash", leaders, "top")]
    return {"tenant": tenant, "company": company, "ff": ff, "member": member, "api": api,
            "card": card, "pages": {"first": first, "leaders": leaders}, "kpis": made}


def names(board):
    return [k["name"] for k in board["kpis"]]


# ============================================================== priority

@pytest.mark.django_db
def test_a_kpi_is_medium_unless_set_and_only_top_medium_or_low(pr):
    with tenant_context(pr["tenant"].pk):
        assert Kpi.objects.get(name="B plain").priority == "medium"
        with pytest.raises(setup.SetupError) as refused:
            setup.create_kpi(pr["card"], {"name": "Urgent", "kind": "count",
                                          "page": str(pr["pages"]["first"].pk),
                                          "priority": "urgent"}, pr["ff"].user)
        assert refused.value.args[0] == "Choose Top, Medium or Low priority."


@pytest.mark.django_db
def test_the_setup_api_sets_and_changes_a_priority(pr):
    client = pr["api"].as_(pr["ff"])
    made = post(client, f"{B}kpis/", {"company": str(pr["company"].pk), "name": "New one",
                                      "kind": "count", "priority": "top",
                                      "page": str(pr["pages"]["first"].pk)})
    assert made.status_code == 201, made.content
    assert made.json()["priority"] == "top"
    changed = patch(client, f"{B}kpis/{made.json()['id']}/", {"priority": "low"})
    assert changed.status_code == 200, changed.content
    with tenant_context(pr["tenant"].pk):
        assert Kpi.objects.get(pk=made.json()["id"]).priority == "low"


@pytest.mark.django_db
def test_a_page_comes_top_then_medium_then_low_each_in_its_own_order(pr):
    client = pr["api"].as_(pr["ff"])
    got = client.get(f"{B}?company={pr['company'].pk}&window=this_week").json()
    assert names(got) == ["C top", "E top", "B plain", "F plain", "A low", "D low"]
    assert [k["priority"] for k in got["kpis"]] == ["top", "top", "medium", "medium",
                                                    "low", "low"]


@pytest.mark.django_db
def test_reordering_within_a_group_still_holds_the_groups(pr):
    client = pr["api"].as_(pr["ff"])
    ids = {k.name: str(k.pk) for k in pr["kpis"]}
    order = [ids[n] for n in ("F plain", "E top", "D low", "C top", "B plain", "A low")]
    moved = post(client, f"{B}kpis/order/", {"page": str(pr["pages"]["first"].pk),
                                             "ids": order})
    assert moved.status_code == 200, moved.content
    got = client.get(f"{B}?company={pr['company'].pk}&window=this_week").json()
    assert names(got) == ["E top", "C top", "F plain", "B plain", "D low", "A low"]


@pytest.mark.django_db
def test_the_portal_sees_the_same_order(pr):
    client = pr["api"].as_(pr["member"])
    got = client.get(f"{B}?company={pr['company'].pk}&window=this_week").json()
    assert names(got) == ["C top", "E top", "B plain", "F plain", "A low", "D low"]
    # Leadership's page isn't theirs to see.
    assert [p["name"] for p in got["pages"]] == [pr["pages"]["first"].name]


# ============================================================== AI apps

@pytest.mark.django_db
def test_scorecard_readings_gives_every_page_when_none_is_named(pr):
    p = T.Principal(AiAppConnectionFactory(tenant=pr["tenant"], membership=pr["ff"]))
    with tenant_context(pr["tenant"].pk):
        got = T.scorecard_readings(p, company_id=str(pr["company"].pk))
    assert names(got) == ["C top", "E top", "B plain", "F plain", "A low", "D low", "Cash"]
    assert {k["name"]: k["page_name"] for k in got["kpis"]}["Cash"] == "Leaders"
    assert got["page"] is None and got["counts"]["of"] == 7


@pytest.mark.django_db
def test_scorecard_readings_gives_one_page_by_name_or_id(pr):
    p = T.Principal(AiAppConnectionFactory(tenant=pr["tenant"], membership=pr["ff"]))
    with tenant_context(pr["tenant"].pk):
        by_name = T.scorecard_readings(p, company_id=str(pr["company"].pk), page="leaders")
        by_id = T.scorecard_readings(p, company_id=str(pr["company"].pk),
                                     page=str(pr["pages"]["first"].pk))
        with pytest.raises(T.ToolRefused) as refused:
            T.scorecard_readings(p, company_id=str(pr["company"].pk), page="Nowhere")
    assert names(by_name) == ["Cash"]
    assert names(by_id) == ["C top", "E top", "B plain", "F plain", "A low", "D low"]
    assert "No page called Nowhere" in str(refused.value)


@pytest.mark.django_db
def test_a_client_user_is_given_only_the_pages_they_can_see(pr):
    p = T.Principal(AiAppConnectionFactory(tenant=pr["tenant"], membership=pr["member"]))
    with tenant_context(pr["tenant"].pk):
        every = T.scorecard_readings(p, company_id=str(pr["company"].pk))
        with pytest.raises(T.ToolRefused):
            T.scorecard_readings(p, company_id=str(pr["company"].pk), page="Leaders")
    assert "Cash" not in names(every) and len(every["kpis"]) == 6


@pytest.mark.django_db
def test_another_practice_reaches_nothing(pr, tenant_b):
    stranger = MembershipFactory(tenant=tenant_b, role="FF")
    p = T.Principal(AiAppConnectionFactory(tenant=tenant_b, membership=stranger))
    with tenant_context(tenant_b.pk), pytest.raises(T.ToolRefused):
        T.scorecard_readings(p, company_id=str(pr["company"].pk))


# ============================================================== seats

@pytest.mark.django_db
def test_a_company_marked_a_client_starts_with_25_seats(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        new = CompanyFactory(tenant=seeded_tenant, name="Fresh Co")
        counted = CompanyFactory(tenant=seeded_tenant, name="Counted Co", seat_count=4)
        clients.mark(new, actor=ff.user)
        clients.mark(counted, actor=ff.user)
        new.refresh_from_db()
        counted.refresh_from_db()
    assert (new.is_client_company, new.seat_count) == (True, 25)
    assert (counted.is_client_company, counted.seat_count) == (True, 4)


@pytest.mark.django_db
def test_a_client_from_before_keeps_its_blank_count(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        old = ClientCompanyFactory(tenant=seeded_tenant, name="Old Client", seat_count=None)
        clients.mark(old, actor=ff.user)                 # already a client: nothing changes
        old.refresh_from_db()
    assert old.seat_count is None


@pytest.mark.django_db
def test_the_won_stage_gives_the_company_25_seats(seeded_tenant, ff, stages):
    from apps.crm.services import pipeline

    from .factories import ContactFactory

    with tenant_context(seeded_tenant.pk):
        company = CompanyFactory(tenant=seeded_tenant, name="Won Co")
        contact = ContactFactory(tenant=seeded_tenant, company=company)
        pipeline.change_stage(contact, stages["closed_won"], actor=ff.user)
        company.refresh_from_db()
    assert (company.is_client_company, company.seat_count) == (True, 25)
    assert Company.CLIENT_SEATS_INCLUDED == 25
