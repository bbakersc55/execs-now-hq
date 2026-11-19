"""Company lists say which companies are clients (Bryan, 2026-11-18): every
picker lists clients first, so the lists not built from /api/companies/
carry the flag themselves. The notes filter, the SOP rows and a meeting's
company candidates; each read as it is now, and only within the practice.
"""

from __future__ import annotations

import pytest

from apps.meetings.models import ProposalItem
from apps.meetings.serializers import represent_item
from apps.sops import services as sop_services
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CompanyFactory, NoteFactory, ProposalItemFactory, SopFactory,
)


@pytest.mark.django_db
def test_the_notes_filter_says_which_companies_are_clients(seeded_tenant, ff, api):
    client_co = ClientCompanyFactory(tenant=seeded_tenant, name="Beacon Labs")
    other = CompanyFactory(tenant=seeded_tenant, name="acme Vendor", is_client_company=False)
    NoteFactory(tenant=seeded_tenant, company=client_co, created_by=ff.user)
    NoteFactory(tenant=seeded_tenant, company=other, created_by=ff.user)
    got = api.as_(ff).get("/api/notes/browse/")
    assert got.status_code == 200, got.content
    assert {c["name"]: c["is_client_company"] for c in got.json()["companies"]} == {
        "Beacon Labs": True, "acme Vendor": False}


@pytest.mark.django_db
def test_an_sop_row_says_whether_its_company_is_a_client(seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        sop = SopFactory(tenant=seeded_tenant)
        assert sop_services.summary(sop)["company"]["is_client_company"] is True


@pytest.mark.django_db
def test_a_meetings_company_candidates_name_the_clients_now(seeded_tenant, tenant_b):
    client_co = ClientCompanyFactory(tenant=seeded_tenant, name="Beacon Labs")
    other = CompanyFactory(tenant=seeded_tenant, name="Beacon Supply", is_client_company=False)
    elsewhere = ClientCompanyFactory(tenant=tenant_b, name="Beacon Elsewhere")
    with tenant_context(seeded_tenant.pk):
        item = ProposalItemFactory(
            tenant=seeded_tenant, kind=ProposalItem.Kind.PARTICIPANT,
            payload={"parsed_name": "Dana", "company_candidates": [
                {"company_id": str(c.pk), "name": c.name, "match_reason": "company_name",
                 "confidence": 0.5, "rank": i + 1}
                for i, c in enumerate((other, client_co, elsewhere))]})
        assert represent_item(item)["client_company_ids"] == [str(client_co.pk)]
