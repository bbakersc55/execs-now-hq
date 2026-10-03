"""Settings → Branding (P1, owner 2026-10-02).

The two non-negotiable families first: only the practice owner reaches it,
and nothing one practice saves or uploads is visible to another. Then the
rules: D2's neutral default, D4's contrast rules, D6's mark rules.
"""

from __future__ import annotations

import io
import json
import pathlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from PIL import Image

from apps.crm.services import email_layout
from apps.tenancy import branding, contrast
from apps.tenancy.models import AuditEvent, Tenant

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory

ROOT = pathlib.Path(__file__).resolve().parent.parent
REFERENCE = json.loads((ROOT / "frontend/src/lib/contrast-reference.json").read_text())
GOOD = {"display_name": "Acme Advisory", "primary_color": "#0A3A65",
        "accent_color": "#F58220", "footer_text": "12 Main St\nacme.example"}


def image(width, height, fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 58, 101)).save(buffer, fmt)
    return buffer.getvalue()


def upload(client, kind, content, name="mark.png"):
    return client.post(f"/api/settings/branding/{kind}",
                       {"file": SimpleUploadedFile(name, content)})


def put(client, body):
    return client.put("/api/settings/branding", json.dumps(body),
                      content_type="application/json")


@pytest.fixture
def ecc(seeded_tenant):
    return _member(seeded_tenant, "ECC", company=ClientCompanyFactory(tenant=seeded_tenant))


# ---------------------------------------------------------------- role boundaries

@pytest.mark.django_db
@pytest.mark.parametrize("who", ["cf", "va", "fcc", "ecc"])
def test_only_the_practice_owner_reaches_branding(request, api, who, ff):
    client = api.as_(request.getfixturevalue(who))
    assert client.get("/api/settings/branding").status_code == 403
    assert put(client, GOOD).status_code == 403
    assert upload(client, "mark", image(128, 128)).status_code == 403
    assert client.delete("/api/settings/branding/logo").status_code == 403
    assert client.post("/api/settings/branding/reset").status_code == 403
    assert api.as_(ff).get("/api/settings/branding").status_code == 200


@pytest.mark.django_db
def test_signed_out_reaches_nothing(client):
    assert client.get("/api/settings/branding").status_code in (401, 403)
    assert client.put("/api/settings/branding", "{}",
                      content_type="application/json").status_code in (401, 403)


# ---------------------------------------------------------------- practice isolation

@pytest.mark.django_db
def test_a_save_in_one_practice_changes_nothing_in_another(api, ff, tenant_b):
    other_owner = _member(tenant_b, "FF")
    before = Tenant.objects.get(pk=tenant_b.pk)
    assert put(api.as_(ff), GOOD).status_code == 200
    assert upload(api.as_(ff), "mark", image(128, 128)).status_code == 200

    after = Tenant.objects.get(pk=tenant_b.pk)
    assert (after.email_display_name, after.email_header_color, after.email_accent_color,
            after.brand_footer_text, after.email_mark_id, after.branding_updated_at) == (
        before.email_display_name, before.email_header_color, before.email_accent_color,
        before.brand_footer_text, before.email_mark_id, before.branding_updated_at)
    seen = api.as_(other_owner).get("/api/settings/branding").json()
    assert seen["display_name"] == "" and seen["has_mark"] is False


@pytest.mark.django_db
def test_the_mark_and_logo_are_always_the_requesters_own(api, ff, tenant_b):
    other_owner = _member(tenant_b, "FF")
    mine = image(128, 128)
    assert upload(api.as_(ff), "mark", mine).status_code == 200
    assert upload(api.as_(ff), "logo", image(400, 100), "logo.png").status_code == 200

    assert api.as_(ff).get("/api/branding/mark").content == mine
    theirs = api.as_(other_owner).get("/api/branding/mark")
    assert theirs["Content-Type"] == "image/svg+xml" and theirs.content != mine
    assert b">TB<" in theirs.content                       # Tenant B's initials
    assert api.as_(other_owner).get("/api/branding/logo").status_code == 404


@pytest.mark.django_db
def test_a_client_sees_their_own_practices_mark(api, ff, fcc, tenant_b):
    _member(tenant_b, "FF")
    mine = image(128, 128)
    upload(api.as_(ff), "mark", mine)
    assert api.as_(fcc).get("/api/branding/mark").content == mine


# ---------------------------------------------------------------- D2 defaults

@pytest.mark.django_db
def test_an_unbranded_practice_wears_its_name_over_neutral_grays(api, ff, seeded_tenant):
    body = api.as_(ff).get("/api/branding").json()
    assert body["palette"]["header"] == email_layout.DEFAULT_HEADER_COLOR
    assert body["palette"]["accent"] == email_layout.DEFAULT_ACCENT_COLOR
    assert body["mark_url"] == "/api/branding/mark"
    mark = api.as_(ff).get("/api/branding/mark")
    assert mark["Content-Type"] == "image/svg+xml" and b">TA<" in mark.content
    settings = api.as_(ff).get("/api/settings/branding").json()
    assert settings["branding_updated_at"] is None


def test_the_neutral_defaults_pass_every_contrast_rule():
    checks = contrast.check(email_layout.DEFAULT_HEADER_COLOR, email_layout.DEFAULT_ACCENT_COLOR)
    assert all(c.ok for c in checks), [c.as_dict() for c in checks]


def test_initials():
    assert branding.initials("Blue Sky Business Consulting") == "BS"
    assert branding.initials("Executives Now") == "EN"
    assert branding.initials("acme") == "A"
    assert branding.initials("& Co") == "C"
    assert branding.initials("") == "·"


def test_the_initials_mark_escapes_and_validates_what_it_is_given():
    # Only each word's first letter or digit is used, so markup never reaches
    # the SVG; escaping is a second guard behind that.
    svg = branding.initials_svg("<script> Evil", color="red;stroke:url(x)")
    assert "<script" not in svg and ">E<" in svg
    assert email_layout.DEFAULT_HEADER_COLOR in svg


# ---------------------------------------------------------------- D4 contrast

@pytest.mark.parametrize("pair", REFERENCE["ratios"])
def test_contrast_ratios_match_the_shared_reference(pair):
    assert round(contrast.ratio(pair["a"], pair["b"]), 2) == pair["ratio"]


@pytest.mark.parametrize("pair", REFERENCE["text_on"])
def test_text_on_a_fill_matches_the_shared_reference(pair):
    assert contrast.text_on(pair["fill"]) == pair["text"]


@pytest.mark.parametrize("case", REFERENCE["verdicts"])
def test_verdicts_match_the_shared_reference(case):
    checks = contrast.check(case["primary"], case["accent"])
    assert [c.rule for c in checks if c.blocks and not c.ok] == case["blocked"]
    assert [c.rule for c in checks if not c.blocks and not c.ok] == case["warned"]


@pytest.mark.django_db
def test_executives_now_colors_save_with_a_warning_not_a_refusal(api, ff):
    response = put(api.as_(ff), GOOD)
    assert response.status_code == 200
    warned = [c for c in response.json()["contrast"] if not c["ok"]]
    assert [c["rule"] for c in warned] == ["accent_on_white"] and not warned[0]["blocks"]


@pytest.mark.django_db
def test_a_primary_too_light_for_white_text_is_refused(api, ff, seeded_tenant):
    response = put(api.as_(ff), {**GOOD, "primary_color": "#7FB3E0", "accent_color": "#0A3A65"})
    assert response.status_code == 400
    assert "Primary color against white" in response.json()["errors"]["primary_color"]
    assert Tenant.objects.get(pk=seeded_tenant.pk).branding_updated_at is None


@pytest.mark.django_db
def test_an_accent_that_vanishes_on_the_primary_is_refused(api, ff):
    response = put(api.as_(ff), {**GOOD, "accent_color": "#1A4A75"})
    assert response.status_code == 400 and "accent_color" in response.json()["errors"]


@pytest.mark.django_db
@pytest.mark.parametrize("field,value,needle", [
    ("primary_color", "navy", "six-digit hex"),
    ("accent_color", "#F582", "six-digit hex"),
    ("display_name", "x" * 81, "at most 80"),
    ("footer_text", "x" * 501, "at most 500"),
    ("footer_text", "\n".join("line" for _ in range(7)), "at most 6 lines"),
])
def test_bad_values_are_refused_with_a_reason(api, ff, field, value, needle):
    response = put(api.as_(ff), {**GOOD, field: value})
    assert response.status_code == 400 and needle in response.json()["errors"][field]


@pytest.mark.django_db
def test_a_save_is_recorded(api, ff, seeded_tenant):
    put(api.as_(ff), GOOD)
    tenant = Tenant.objects.get(pk=seeded_tenant.pk)
    assert (tenant.email_display_name, tenant.email_header_color, tenant.brand_footer_text) == (
        "Acme Advisory", "#0A3A65", "12 Main St\nacme.example")
    assert tenant.branding_updated_at is not None
    assert AuditEvent.all_objects.filter(tenant=tenant, verb="branding.updated").count() == 1


# ---------------------------------------------------------------- D6 images

@pytest.mark.django_db
@pytest.mark.parametrize("kind,content,name,needle", [
    ("mark", image(128, 96), "m.png", "must be square"),
    ("mark", image(48, 48), "m.png", "at least 64"),
    ("mark", image(128, 128, "JPEG"), "m.jpg", "Use a PNG"),
    ("mark", b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "m.svg", "Use a PNG"),
    ("logo", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "l.svg", "PNG or a JPEG"),
    ("logo", b"\x89PNG" + b"0" * (600 * 1024), "l.png", "the limit is 500 KB"),
])
def test_images_that_break_the_rules_are_refused(api, ff, kind, content, name, needle):
    response = upload(api.as_(ff), kind, content, name)
    assert response.status_code == 400 and needle in response.json()["detail"]


@pytest.mark.django_db
def test_a_logo_is_fitted_and_never_enlarged(api, ff, seeded_tenant):
    body = upload(api.as_(ff), "logo", image(520, 168, "JPEG"), "l.jpg").json()
    assert body["uploaded"]["shown_at"] == [260, 84] and body["has_logo"]
    small = upload(api.as_(ff), "logo", image(100, 40), "l.png").json()
    assert small["uploaded"]["shown_at"] == [100, 40]


@pytest.mark.django_db
def test_clear_and_reset(api, ff, seeded_tenant):
    client = api.as_(ff)
    put(client, GOOD)
    upload(client, "mark", image(128, 128))
    assert client.delete("/api/settings/branding/mark").json()["has_mark"] is False
    reset = client.post("/api/settings/branding/reset").json()
    assert reset["display_name"] == "" and reset["footer_text"] == ""
    assert reset["primary_color"] == email_layout.DEFAULT_HEADER_COLOR
    assert reset["branding_updated_at"] is None
    verbs = set(AuditEvent.all_objects.filter(tenant=seeded_tenant)
                .values_list("verb", flat=True))
    assert {"branding.updated", "branding.mark_set", "branding.mark_cleared",
            "branding.reset"} <= verbs


@pytest.mark.django_db
def test_the_command_applies_the_same_rules(seeded_tenant, tmp_path):
    jpeg = tmp_path / "mark.jpg"
    jpeg.write_bytes(image(128, 128, "JPEG"))
    with pytest.raises(CommandError, match="Use a PNG"):
        call_command("set_email_logo", str(jpeg), "--mark", "--tenant", seeded_tenant.slug)
    png = tmp_path / "mark.png"
    png.write_bytes(image(112, 112))
    call_command("set_email_logo", str(png), "--mark", "--tenant", seeded_tenant.slug)
    tenant = Tenant.objects.get(pk=seeded_tenant.pk)
    assert tenant.email_mark_id and tenant.email_mark_width == 56
