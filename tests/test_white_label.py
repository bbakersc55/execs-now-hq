"""White-label — the product never brands a client's view (owner ruling, 2026-09-15).

Every surface a client can reach wears the **tenant's** name, colours and logo:
the portal shell, the sign-in page, the refused page, the cadence page, and
every email. "Execs NOW HQ" belongs on staff screens only, and "Executives Now"
is one tenant's data like any other practice's — never a default baked into the
code, or a V1 tenant would inherit it.

Beta serves one tenant on one domain; V1 gives each practice its own portal
domain and resolves the tenant by hostname. Both are the same rule.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import MagicLinkToken
from apps.crm.models import OutboxMessage
from apps.crm.services import email_layout, outbox
from apps.tenancy.models import Tenant
from config.branding import PRODUCT_NAME

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactFactory, MembershipFactory, ProjectFactory, TenantFactory,
)

BETA = {"name": "Executives Now", "email_display_name": "Executives Now",
        "email_header_color": "#0A3A65", "email_accent_color": "#F58220"}


@pytest.fixture
def practice(seeded_tenant):
    """Beta's tenant, branded from its own row — not from the code."""
    for field, value in BETA.items():
        setattr(seeded_tenant, field, value)
    seeded_tenant.save()
    return seeded_tenant


@pytest.fixture
def company(practice):
    return ClientCompanyFactory(tenant=practice, name="Northwind Foods", seat_count=3)


@pytest.mark.django_db
def test_the_code_brands_nothing_a_new_practice_gets_its_own_name_on_neutral_greys():
    """The defect this guards: Executives Now's palette as the code default,
    which every V1 tenant would have inherited."""
    fresh = TenantFactory(name="Northwind Advisory")
    brand = email_layout.branding(fresh)
    assert brand.display_name == "Northwind Advisory"
    assert brand.header_color == email_layout.DEFAULT_HEADER_COLOR
    assert brand.accent_color == email_layout.DEFAULT_ACCENT_COLOR
    for value in ("#0A3A65", "#F58220", "Executives Now", PRODUCT_NAME):
        assert value not in email_layout.document(fresh, content_html="<p>Hi</p>"), value


@pytest.mark.django_db
def test_branding_is_the_practices_and_the_product_name_is_staff_only(
    practice, ff, api, company, in_tenant_a
):
    client_user = MembershipFactory(tenant=practice, role="ECC", client_company=company)

    as_client = api.as_(client_user).get("/api/branding").json()
    assert as_client["display_name"] == "Executives Now"
    assert as_client["palette"]["header"] == "#0A3A65"
    assert as_client["product_name"] is None, "A client is never told the product's name."

    as_staff = api.as_(ff).get("/api/branding").json()
    assert as_staff["product_name"] == PRODUCT_NAME
    assert as_staff["display_name"] == "Executives Now"


@pytest.mark.django_db
def test_a_signed_out_visitor_gets_neither_a_practice_nor_the_product(practice, client):
    """P2 (owner, 2026-10-02): the sign-in page needs no practice; the email
    entered finds it. So, signed out, nothing names one, and still nothing
    names the product."""
    body = client.get("/api/branding").json()
    assert body["display_name"] == "" and body["product_name"] is None
    assert body["mark_url"] == ""
    assert client.get("/api/branding/mark").status_code == 404


@pytest.mark.django_db
def test_no_client_facing_page_names_the_product(practice, company, client, in_tenant_a):
    member = MembershipFactory(tenant=practice, role="ECC", client_company=company)
    _, raw = MagicLinkToken.issue(tenant=practice, user=member.user)

    pages = [
        client.get("/accounts/refused"),
        client.get(f"/auth/magic/{raw}"),          # a live link, tenant known from the token
        client.get("/auth/magic/not-a-real-token"),  # expired: tenant from the hostname rule
    ]

    for page in pages:
        assert PRODUCT_NAME not in page.content.decode(), page.request["PATH_INFO"]
    # The live link names its practice, from the token. The other two know of
    # no practice and name none (P2: no "the one practice" fallback).
    assert "Executives Now" in pages[1].content.decode()
    for page in (pages[0], pages[2]):
        assert "Executives Now" not in page.content.decode(), page.request["PATH_INFO"]


@pytest.mark.django_db
def test_the_logo_endpoint_serves_only_the_requesters_own_practice(practice, tmp_path, client):
    from django.core.management import call_command

    from tests.test_email_presentation import png

    path = tmp_path / "logo.png"
    path.write_bytes(png(440, 100))
    call_command("set_email_logo", str(path), "--tenant", practice.slug)

    # Signed out with no link: no practice, so no logo (P2).
    assert client.get("/api/branding/logo").status_code == 404

    # An emailed link names its practice; its logo is served through it.
    from apps.crm.services import unsubscribe

    token = unsubscribe.token_for(tenant_id=practice.pk, category="updates",
                                  address="dana@client.invalid")
    response = client.get(f"/api/branding/logo?via=unsubscribe:{token}")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content == png(440, 100)

    # Another practice's link never reaches this practice's logo.
    other = TenantFactory(name="Northwind Advisory")
    theirs = unsubscribe.token_for(tenant_id=other.pk, category="updates",
                                   address="dana@client.invalid")
    assert client.get(f"/api/branding/logo?via=unsubscribe:{theirs}").status_code == 404
    assert client.get("/api/branding/logo?via=unsubscribe:forged").status_code == 404


@pytest.mark.django_db
def test_no_email_a_client_receives_names_the_product(practice, ff, in_tenant_a):
    from apps.accounts.views import magic_link_email

    contact = ContactFactory(tenant=practice, first_name="Maria")
    drafts = [
        outbox.create_message(tenant=practice, producer=OutboxMessage.Producer.REFERRAL_TOUCH,
                              to_contact=contact, to_address="maria@partner.invalid",
                              subject="Checking in", body_text="Hi Maria", actor=ff.user),
        outbox.create_message(tenant=practice, producer=OutboxMessage.Producer.MANUAL,
                              to_address="maria@partner.invalid", subject="A note",
                              body_text="Hi Maria", actor=ff.user),
    ]
    for draft in drafts:
        html, text = email_layout.for_delivery(draft)
        assert PRODUCT_NAME not in html and PRODUCT_NAME not in text

    html, text = magic_link_email(practice, url="https://app.example.invalid/auth/magic/x")
    assert PRODUCT_NAME not in html and PRODUCT_NAME not in text
    assert "Executives Now" in html



@pytest.mark.django_db
def test_the_referral_flyer_is_named_for_the_practice(practice, ff, in_tenant_a):
    from django.utils.text import slugify

    from apps.tenancy import storage

    practice.marketing_flyer = storage.save(
        tenant=practice, content=b"%PDF-1.4 flyer",
        object_key=storage.object_key(f"flyers/{practice.slug}", "flyer.pdf"),
        content_type="application/pdf", purpose="marketing_flyer")
    practice.save(update_fields=["marketing_flyer", "updated_at"])

    contact = ContactFactory(tenant=practice, first_name="Maria")
    from apps.crm.services.referral import onboard_referral_partner

    message = onboard_referral_partner(contact, actor=ff.user)
    names = [a.filename for a in message.attachments.all()]
    assert names == [f"{slugify(practice.name)}.pdf"] == ["executives-now.pdf"]
    assert not any("Executives-Now.pdf" == n for n in names), "Not the product owner's name."


@pytest.mark.django_db
def test_the_cadence_page_says_which_practice_the_updates_are_from(practice, ff, company,
                                                                   client, in_tenant_a):
    from apps.work.models import Cadence, Stakeholder, StakeholderToken

    contact = ContactFactory(tenant=practice, first_name="Dana", last_name="Okafor",
                             company=company)
    # A stakeholder sits at exactly one level; this one watches a project.
    project = ProjectFactory(tenant=practice, title="Order-to-cash", client_company=company)
    row = Stakeholder.all_objects.create(tenant=practice, contact=contact, project=project,
                                         cadence=Cadence.WEEKLY)
    _, raw = StakeholderToken.issue(row)
    body = client.get(f"/api/cadence/{raw}").json()
    assert body["practice"] == "Executives Now"
    assert PRODUCT_NAME not in str(body)


@pytest.mark.django_db
def test_a_clients_email_carries_no_product_named_header(practice, ff, dev_outbox, in_tenant_a):
    contact = ContactFactory(tenant=practice, first_name="Maria")
    outbox.create_message(
        tenant=practice, producer=OutboxMessage.Producer.MANUAL, role="FF", actor=ff.user,
        to_contact=contact, to_address="maria@partner.invalid", subject="A note",
        body_text="Hi Maria")
    sent = dev_outbox[0]
    assert not any("ExecsNowHQ" in name for name in sent.extra_headers), sent.extra_headers
    assert "X-Thread-Token" in sent.extra_headers


@pytest.mark.django_db
def test_signed_out_only_an_emailed_link_names_a_practice(practice, client, in_tenant_a):
    """P2 (owner, 2026-10-02): with two practices, each link brands as its own
    practice and nothing else guesses. Per-practice subdomains are V1."""
    from apps.work.models import StakeholderToken

    from .factories import StakeholderFactory

    other = TenantFactory(name="Northwind Advisory", email_display_name="Northwind")
    assert Tenant.objects.count() == 2
    assert client.get("/api/branding").json()["display_name"] == ""

    _, mine = StakeholderToken.issue(StakeholderFactory(tenant=practice))
    _, theirs = StakeholderToken.issue(StakeholderFactory(tenant=other))
    assert client.get(f"/api/branding?via=cadence:{mine}").json()["display_name"] == \
        "Executives Now"
    body = client.get(f"/api/branding?via=cadence:{theirs}").json()
    assert body["display_name"] == "Northwind" and body["product_name"] is None
    assert body["mark_url"] == f"/api/branding/mark?via=cadence:{theirs}"
    mark = client.get(body["mark_url"])
    assert mark.status_code == 200 and b">N<" in mark.content
    assert client.get("/api/branding?via=cadence:not-a-token").json()["display_name"] == ""
