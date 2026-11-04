"""The Google reviews feed's routes (`docs/google_reviews_feed.md`).

The connection is the practice owner's to make, on the company page; the
Google account that signs in is whoever manages the client's Business
Profile. Setting a KPI's reviews measure is the practice owner's and
associates', as the rest of the scorecard's setup is. Every route finds the
company through `access.company_for`, so another practice's company is 404.

GET    /api/scorecard/reviews/connection/?company=          its state (no token)
POST   /api/scorecard/reviews/connection/start/             {company}: the Google consent URL
GET    /api/scorecard/reviews/connection/choices/?company=&account=   accounts, locations
PUT    /api/scorecard/reviews/connection/                   {company, account, location, ...}
POST   /api/scorecard/reviews/connection/test/              {company}: one read-only call
DELETE /api/scorecard/reviews/connection/?company=
GET    /api/scorecard/reviews/latest/?company=              the latest reviews, read-only
GET    /api/scorecard/reviews/feed/?company=&kpi=
PUT    /api/scorecard/reviews/feed/                         {company, kpi, measure, star?}
DELETE /api/scorecard/reviews/feed/?company=&kpi=           stop it; its readings stay

The consent comes back through Gmail's callback (`/accounts/gmail/callback`),
told apart by this consent's own state, so the OAuth client needs no second
redirect URI.
"""

from __future__ import annotations

from django.conf import settings as dj_settings
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from rest_framework.response import Response

from apps.tenancy.models import AuditEvent, Role

from . import feeds, google_reviews
from .models import GoogleReview, GoogleReviewsConnection, Kpi, KpiReviewsFeed
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404

OWNER_ONLY = "Only the practice owner connects a company's Google Business Profile."


def _owner_only(request):
    if request.membership.role != Role.FF:
        return Response({"detail": OWNER_ONLY}, status=403)
    return None


def _demo_refusal():
    from config import environment

    if environment.is_demo():
        return Response({"detail": google_reviews.DEMO_REFUSAL}, status=409)
    return None


def _payload(connection):
    from config import environment

    if connection is None:
        return {"connected": False, "demo": environment.is_demo()}
    return {
        "connected": True, "demo": environment.is_demo(),
        "google_email": connection.google_email,
        "account": connection.account_name, "account_label": connection.account_label,
        "location": connection.location_name, "location_title": connection.location_title,
        "chosen": bool(connection.location_name),
        "average_rating": float(connection.average_rating)
        if connection.average_rating is not None else None,
        "total_review_count": connection.total_review_count,
        "not_approved": connection.not_approved,
        "not_approved_text": google_reviews.NOT_APPROVED if connection.not_approved else "",
        "checked_at": connection.checked_at.isoformat() if connection.checked_at else None,
        "check_ok": connection.check_ok, "check_detail": connection.check_detail,
        "last_read_at": connection.last_read_at.isoformat() if connection.last_read_at
        else None,
        "last_error": connection.last_error,
        "stored": GoogleReview.all_objects.filter(connection=connection).count(),
    }


def _connection(company):
    return GoogleReviewsConnection.objects.filter(company=company).first()


class ReviewsConnectionView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response(_payload(_connection(reader.company)))

    def put(self, request):
        """The account and location, from Google's own lists."""
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)) \
                or (refusal := _demo_refusal()):
            return refusal
        connection = _connection(reader.company)
        if connection is None:
            return Response({"detail": "Sign in with Google first."}, status=400)
        account = str(request.data.get("account") or "").strip()
        location = str(request.data.get("location") or "").strip()
        if not account.startswith("accounts/") or not location.startswith("locations/"):
            return Response({"detail": "Choose the account and the location from the lists."},
                            status=400)
        if location != connection.location_name:
            # Another location's reviews are not this one's.
            GoogleReview.all_objects.filter(connection=connection).delete()
            connection.average_rating = connection.total_review_count = None
            connection.last_read_at = connection.last_success_at = None
        connection.account_name, connection.location_name = account[:120], location[:120]
        connection.account_label = str(request.data.get("account_label") or "")[:200]
        connection.location_title = str(request.data.get("location_title") or "")[:200]
        connection.checked_at, connection.check_ok, connection.check_detail = None, None, ""
        connection.last_error, connection.not_approved = "", False
        connection.save()
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.reviews_location_chosen",
            target_type="company", target_id=reader.company.pk,
            payload={"location": connection.location_name, "title": connection.location_title})
        # The first read, now, so the card has something to show.
        try:
            google_reviews.sync(connection, google_reviews.client_for(connection))
        except (google_reviews.ReviewsUnavailable, google_reviews.ReviewsRefused) as exc:
            google_reviews.failed(connection, exc)
        connection.refresh_from_db()
        return Response(_payload(connection))

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = _connection(reader.company)
        if connection is not None:
            connection.delete()           # the token and the stored reviews with it
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="scorecard.reviews_removed",
                target_type="company", target_id=reader.company.pk, payload={})
        return Response(_payload(None))


class ReviewsStartView(Base):
    def post(self, request):
        from apps.crm.services import gmail_oauth

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)) \
                or (refusal := _demo_refusal()):
            return refusal
        if not gmail_oauth.is_configured(request.tenant):
            return Response({"detail": "Google sign-in isn't configured on this server."},
                            status=409)
        state = gmail_oauth.new_state()
        request.session[google_reviews.STATE_KEY] = {"state": state,
                                                     "company": str(reader.company.pk)}
        return Response({"url": google_reviews.consent_url(request.tenant, state)})


class ReviewsChoicesView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)) \
                or (refusal := _demo_refusal()):
            return refusal
        connection = _connection(reader.company)
        if connection is None:
            return Response({"detail": "Sign in with Google first."}, status=400)
        out = {"accounts": [], "locations": [], "error": "", "not_approved": False}
        try:
            client = google_reviews.client_for(connection)
            out["accounts"] = client.accounts()
            account = str(request.query_params.get("account") or "")
            if account.startswith("accounts/"):
                out["locations"] = client.locations(account)
        except google_reviews.NotApproved as exc:
            out["error"], out["not_approved"] = str(exc), True
        except (google_reviews.ReviewsUnavailable, google_reviews.ReviewsRefused) as exc:
            out["error"] = str(exc)
        return Response(out)


class ReviewsTestView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = _connection(reader.company)
        if connection is None or not connection.location_name:
            return Response({"detail": "Sign in with Google and choose the location first."},
                            status=400)
        not_approved = False
        try:
            got = google_reviews.client_for(connection).reviews_page(
                connection.account_name, connection.location_name, page_size=1)
            average, total = got.get("averageRating"), got.get("totalReviewCount") or 0
            detail, ok = (f"Connected: {total} review{'' if total == 1 else 's'}"
                          + (f", {average} average." if average is not None else ".")), True
        except google_reviews.NotApproved as exc:
            detail, ok, not_approved = str(exc), False, True
        except (google_reviews.ReviewsUnavailable, google_reviews.ReviewsRefused) as exc:
            detail, ok = str(exc), False
        connection.checked_at, connection.check_ok, connection.check_detail = \
            timezone.now(), ok, detail
        connection.not_approved = not_approved
        connection.save(update_fields=["checked_at", "check_ok", "check_detail", "not_approved",
                                       "updated_at"])
        return Response(_payload(connection))


class ReviewsLatestView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        connection = _connection(reader.company)
        return Response({**_payload(connection),
                         "reviews": google_reviews.latest(connection) if connection else []})


# ------------------------------------------------------------- the consent

def is_reviews_consent(request) -> bool:
    return google_reviews.is_reviews_consent(request)


def callback(request):
    """Google's answer to the Business Profile consent: the connection's
    token, or why not. Ends on the company page."""
    from apps.crm.models import Company
    from apps.crm.services import gmail_oauth, secrets
    from config import environment

    started = request.session.pop(google_reviews.STATE_KEY, None) or {}
    root = dj_settings.APP_ROOT_URL.rstrip("/")
    company_id = started.get("company") or ""

    def back(**params):
        from urllib.parse import urlencode

        path = f"/companies/{company_id}" if company_id else "/companies"
        return HttpResponseRedirect(f"{root}{path}?{urlencode(params)}")

    membership = getattr(request, "membership", None)
    if membership is None or membership.role != Role.FF:
        return back(reviews_error="Only the practice owner connects a Business Profile, so "
                                  "nothing was stored.")
    if environment.is_demo():
        return back(reviews_error=google_reviews.DEMO_REFUSAL)
    company = Company.objects.filter(pk=company_id).first() if company_id else None
    if company is None:
        return back(reviews_error="That company is not in this practice. Nothing was stored.")
    if request.GET.get("error") or not request.GET.get("code"):
        return back(reviews_error="Google sign-in did not complete. Nothing was stored.")
    try:
        tokens = gmail_oauth.exchange_code(request.GET["code"], tenant=membership.tenant)
        email = gmail_oauth.account_email(tokens["access_token"])
    except gmail_oauth.GmailOAuthError as exc:
        return back(reviews_error=str(exc))
    if not google_reviews.granted(tokens):
        return back(reviews_error="Consent was given without access to the Business Profile. "
                                  "Nothing was stored. Connect again and allow it.")
    connection = GoogleReviewsConnection.objects.filter(company=company).first()
    made = connection is None
    connection = connection or GoogleReviewsConnection(tenant=membership.tenant, company=company,
                                                       created_by=request.user)
    connection.token_ciphertext = secrets.encrypt(tokens["refresh_token"])
    connection.google_email = email[:254]
    connection.checked_at, connection.check_ok, connection.check_detail = None, None, ""
    connection.last_error, connection.not_approved = "", False
    connection.save()
    AuditEvent.objects.create(
        tenant=membership.tenant, actor=request.user,
        verb="scorecard.reviews_connected" if made else "scorecard.reviews_reconnected",
        target_type="company", target_id=company.pk, payload={"google_email": email})
    return back(reviews_connected=email)


# ----------------------------------------------------------- a KPI's feed

def _kpi(request, data):
    reader = _reader(request, data.get("company"))
    kpi = Kpi.objects.filter(pk=_uuid_or_404(data.get("kpi")), scorecard__company=reader.company,
                             archived_at__isnull=True).select_related(
        "scorecard", "scorecard__company").first()
    if kpi is None:
        raise Http404
    return reader, kpi


def _feed_payload(feed):
    if feed is None or not feed.active:
        return None
    return {"measure": feed.measure, "star": feed.star,
            "label": google_reviews.MEASURES.get(feed.measure, ("",))[0],
            "text": feeds.reviews_source_text(feed),
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at
            else None, "last_error": feed.last_error, **feeds.read_open_payload(feed)}


class ReviewsFeedView(Base):
    def get(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        connection = _connection(reader.company)
        return Response({"kpi": {"id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
                                 "per_person": kpi.per_person,
                                 "read_open_default": feeds.reads_open_by_default(kpi)},
                         "connected": bool(connection and connection.location_name),
                         "location_title": connection.location_title if connection else "",
                         # The menu is fixed and local: never waits on Google.
                         "measures": google_reviews.menu(),
                         "feed": _feed_payload(KpiReviewsFeed.objects.filter(kpi=kpi).first())})

    def put(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        measure = str(request.data.get("measure") or "")
        try:
            star = int(request.data.get("star")) if request.data.get("star") not in (None, "") \
                else None
        except (TypeError, ValueError):
            star = None
        try:
            google_reviews.check_fits(kpi, measure, star)
        except google_reviews.ReviewsRefused as exc:
            return Response({"measure": str(exc)}, status=400)
        if not google_reviews.MEASURES[measure][2]:
            star = None
        connection = _connection(reader.company)
        if connection is None or not connection.location_name:
            return Response({"detail": f"{reader.company.name} has no Google Business Profile "
                                       "location connected yet."}, status=409)
        feeds.stop_other_feeds(kpi, Kpi.Feed.REVIEWS)
        before = KpiReviewsFeed.all_objects.filter(kpi=kpi).first()
        read_open = feeds.read_open_choice(request.data, before.read_open if before else None)
        feed, _ = KpiReviewsFeed.all_objects.update_or_create(
            kpi=kpi, defaults={"tenant_id": kpi.tenant_id, "measure": measure, "star": star,
                               "active": True, "last_error": "", "error_since": None,
                               "last_success_at": None, "created_by": request.user,
                               "read_open": read_open})
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_set",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "reviews",
                     "measure": measure, "star": star})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.REVIEWS)
        feed.refresh_from_db()
        result = feeds.run_reviews(feed, _today(request))
        feed.refresh_from_db()
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        KpiReviewsFeed.objects.filter(kpi=kpi).update(active=False, updated_at=timezone.now())
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_stopped",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "reviews"})
        return Response({"feed": None})
