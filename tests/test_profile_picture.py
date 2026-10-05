"""Profile pictures (docs/ui3_top_bar_settings_profile.md §6).

Two families are the point: **practice isolation** (a picture is never served
across practices) and **role boundaries** (a client user never gets another
client company's people; nobody changes anyone's picture but their own)."""

from __future__ import annotations

import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.tenancy import avatars, storage
from apps.tenancy.models import StoredFile

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory

UPLOAD = "/api/me/profile/picture"


def image(fmt="PNG", size=(600, 400), color=(200, 30, 30), mode="RGB", **save):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format=fmt, **save)
    return out.getvalue()


def upload(client, content, name="me.png", content_type="image/png"):
    return client.post(UPLOAD, {"picture": SimpleUploadedFile(name, content, content_type)})


def picture_of(membership):
    return f"/api/people/{membership.pk}/picture"


def with_picture(api, membership):
    assert upload(api.as_(membership), image()).status_code == 200
    membership.refresh_from_db()
    return membership


def member(tenant, role, company=None):
    if role in ("FCC", "ECC") and company is None:
        company = ClientCompanyFactory(tenant=tenant)
    return MembershipFactory(tenant=tenant, role=role, client_company=company)


# ------------------------------------------------------------------ uploading

@pytest.mark.django_db
@pytest.mark.parametrize("fmt,content_type", [
    ("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp"),
])
def test_whatever_is_sent_a_256_square_jpeg_is_stored(seeded_tenant, ff, api, fmt, content_type):
    response = upload(api.as_(ff), image(fmt, size=(900, 500)), "me", content_type)

    assert response.status_code == 200, response.content
    ff.refresh_from_db()
    stored = ff.avatar
    assert stored.purpose == "avatar" and stored.content_type == "image/jpeg"
    assert stored.object_key.startswith(f"avatars/{seeded_tenant.slug}/")
    assert not stored.object_key.startswith(storage.RECORDINGS_PREFIX)
    with Image.open(io.BytesIO(storage.read(stored))) as kept:
        assert (kept.format, kept.size) == ("JPEG", (256, 256))
    assert stored.byte_size < 60_000
    assert response.json()["picture_url"].startswith(picture_of(ff))
    assert api.as_(ff).get("/api/me").json()["picture_url"] == response.json()["picture_url"]


@pytest.mark.django_db
def test_the_original_file_and_its_hidden_data_are_not_kept(seeded_tenant, ff, api):
    exif = Image.Exif()
    exif[0x010F] = "SECRET-CAMERA-MAKE"
    original = image("JPEG", exif=exif)
    assert b"SECRET-CAMERA-MAKE" in original

    upload(api.as_(ff), original, "me.jpg", "image/jpeg")

    ff.refresh_from_db()
    kept = storage.read(ff.avatar)
    assert kept != original and b"SECRET-CAMERA-MAKE" not in kept


@pytest.mark.django_db
def test_a_transparent_picture_is_flattened_not_blackened(seeded_tenant, ff, api):
    upload(api.as_(ff), image("PNG", mode="RGBA", color=(0, 0, 0, 0)))
    ff.refresh_from_db()
    with Image.open(io.BytesIO(storage.read(ff.avatar))) as kept:
        assert kept.getpixel((128, 128)) == (255, 255, 255)


@pytest.mark.django_db
@pytest.mark.parametrize("content,name,content_type", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
     "me.svg", "image/svg+xml"),
    (b"GIF89a" + b"\x00" * 64, "me.gif", "image/gif"),
    (b"not a picture at all", "me.png", "image/png"),
    (b"%PDF-1.4 pretending", "me.jpg", "image/jpeg"),
    (b"", "me.png", "image/png"),
])
def test_anything_that_is_not_a_jpeg_png_or_webp_is_refused(
    seeded_tenant, ff, api, content, name, content_type
):
    response = upload(api.as_(ff), content, name, content_type)

    assert response.status_code == 400 and "picture" in response.json()
    ff.refresh_from_db()
    assert ff.avatar is None and not StoredFile.all_objects.filter(purpose="avatar").exists()


@pytest.mark.django_db
def test_a_real_gif_is_refused_whatever_it_is_called(seeded_tenant, ff, api):
    response = upload(api.as_(ff), image("GIF"), "me.png", "image/png")
    assert response.status_code == 400
    assert "JPEG, PNG or WebP" in response.json()["picture"]


@pytest.mark.django_db
def test_more_than_five_megabytes_is_refused(seeded_tenant, ff, api):
    response = upload(api.as_(ff), b"\xff\xd8" + b"0" * (avatars.MAX_BYTES + 1), "big.jpg",
                      "image/jpeg")
    assert response.status_code == 400 and "5 MB" in response.json()["picture"]


@pytest.mark.django_db
def test_no_file_is_refused(seeded_tenant, ff, api):
    assert api.as_(ff).post(UPLOAD, {}).status_code == 400


@pytest.mark.django_db
def test_a_new_picture_replaces_and_deletes_the_old_one(seeded_tenant, ff, api):
    with_picture(api, ff)
    first = ff.avatar
    first_url = api.as_(ff).get("/api/me").json()["picture_url"]

    upload(api.as_(ff), image(color=(10, 200, 10)))

    ff.refresh_from_db()
    assert ff.avatar_id != first.pk
    assert not StoredFile.all_objects.filter(pk=first.pk).exists()
    assert not storage.exists(first)
    # A new address, so no browser shows the old face from its cache.
    assert api.as_(ff).get("/api/me").json()["picture_url"] != first_url


@pytest.mark.django_db
def test_removing_goes_back_to_initials_and_deletes_the_file(seeded_tenant, ff, api):
    with_picture(api, ff)
    stored = ff.avatar

    response = api.as_(ff).delete(UPLOAD)

    assert response.status_code == 200 and response.json()["picture_url"] is None
    ff.refresh_from_db()
    assert ff.avatar is None and not storage.exists(stored)
    assert api.as_(ff).get(picture_of(ff)).status_code == 404
    # Removing when there is none is not an error.
    assert api.as_(ff).delete(UPLOAD).status_code == 200


# -------------------------------------------------------------- whose it is

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC", "ECC"])
def test_every_role_sets_its_own_picture_and_only_its_own(seeded_tenant, api, role):
    me = member(seeded_tenant, role)
    bystander = member(seeded_tenant, "VA")

    assert upload(api.as_(me), image()).status_code == 200

    me.refresh_from_db()
    bystander.refresh_from_db()
    assert me.avatar is not None and bystander.avatar is None
    assert api.as_(me).get(picture_of(me)).status_code == 200


@pytest.mark.django_db
def test_a_picture_cannot_be_changed_or_removed_while_acting_as_its_owner(
    seeded_tenant, ff, api
):
    target = with_picture(api, member(seeded_tenant, "FCC"))
    kept = target.avatar_id
    client = api.as_(ff)
    assert client.post("/api/act-as/", json.dumps({"membership": str(target.pk)}),
                       content_type="application/json").status_code == 201

    assert upload(client, image(color=(1, 2, 3))).status_code == 403
    assert client.delete(UPLOAD).status_code == 403

    target.refresh_from_db()
    ff.refresh_from_db()
    assert target.avatar_id == kept and ff.avatar is None


@pytest.mark.django_db
def test_signed_out_sets_removes_and_sees_nothing(seeded_tenant, ff, api, client):
    with_picture(api, ff)
    assert upload(client, image()).status_code == 401
    assert client.delete(UPLOAD).status_code == 401
    assert client.get(picture_of(ff)).status_code == 401


@pytest.mark.django_db
def test_setting_a_picture_needs_the_csrf_token(seeded_tenant, ff):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    strict.force_login(ff.user)
    assert upload(strict, image()).status_code == 403
    assert strict.delete(UPLOAD).status_code == 403


# ---------------------------------------------------------- who may see whom

@pytest.mark.django_db
def test_a_picture_is_never_served_across_practices(tenant_a, tenant_b, api):
    """Practice isolation: not found, for every role, with or without the
    version on the address."""
    b_owner = with_picture(api, MembershipFactory(tenant=tenant_b, role="FF"))
    b_client = with_picture(api, member(tenant_b, "FCC"))
    url = api.as_(b_owner).get("/api/me").json()["picture_url"]

    for role in ("FF", "CF", "VA", "FCC", "ECC"):
        outsider = api.as_(member(tenant_a, role))
        for path in (url, picture_of(b_owner), picture_of(b_client)):
            assert outsider.get(path).status_code == 404, (role, path)
    assert api.as_(b_owner).get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_staff_see_everyone_in_their_practice(seeded_tenant, api, role):
    viewer = api.as_(member(seeded_tenant, role))
    for other in ("FF", "CF", "VA", "FCC", "ECC"):
        target = with_picture(api, member(seeded_tenant, other))
        response = viewer.get(picture_of(target))
        assert response.status_code == 200, (role, other)
        assert response["Content-Type"] == "image/jpeg"
        assert "private" in response["Cache-Control"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_user_sees_their_company_and_the_staff_and_no_other_client(
    seeded_tenant, api, role
):
    ours = ClientCompanyFactory(tenant=seeded_tenant)
    theirs = ClientCompanyFactory(tenant=seeded_tenant)
    me = with_picture(api, member(seeded_tenant, role, ours))
    colleague = with_picture(api, member(seeded_tenant, "ECC", ours))
    staff = [with_picture(api, member(seeded_tenant, r)) for r in ("FF", "CF", "VA")]
    strangers = [with_picture(api, member(seeded_tenant, r, theirs)) for r in ("FCC", "ECC")]
    viewer = api.as_(me)

    for allowed in (me, colleague, *staff):
        assert viewer.get(picture_of(allowed)).status_code == 200
    for stranger in strangers:
        assert viewer.get(picture_of(stranger)).status_code == 404


@pytest.mark.django_db
def test_a_revoked_persons_picture_is_not_served(seeded_tenant, ff, api):
    from django.utils import timezone

    gone = with_picture(api, member(seeded_tenant, "VA"))
    type(gone).all_objects.filter(pk=gone.pk).update(revoked_at=timezone.now())
    assert api.as_(ff).get(picture_of(gone)).status_code == 404


@pytest.mark.django_db
def test_someone_without_a_picture_and_a_nonsense_id_are_both_not_found(seeded_tenant, ff, api):
    assert api.as_(ff).get(picture_of(member(seeded_tenant, "VA"))).status_code == 404
    assert api.as_(ff).get("/api/people/not-an-id/picture").status_code == 404


@pytest.mark.django_db
def test_acting_as_a_client_sees_only_what_that_client_may(seeded_tenant, ff, api):
    ours = ClientCompanyFactory(tenant=seeded_tenant)
    theirs = ClientCompanyFactory(tenant=seeded_tenant)
    target = member(seeded_tenant, "FCC", ours)
    stranger = with_picture(api, member(seeded_tenant, "FCC", theirs))
    client = api.as_(ff)
    assert client.get(picture_of(stranger)).status_code == 200
    client.post("/api/act-as/", json.dumps({"membership": str(target.pk)}),
                content_type="application/json")

    assert client.get(picture_of(stranger)).status_code == 404
