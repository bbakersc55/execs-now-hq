from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from apps.aiconnect import urls as aiconnect_urls

from apps.accounts import google_external, microsoft_signin
from apps.accounts import views as account_views
from apps.billing import views_pay as billing_pay
from apps.billing import views_proof as billing_proof
from apps.cardpages import views as cardpages_views
from apps.crm import views_gmail, views_microsoft
from apps.crm import views_site_leads as crm_site_leads
from apps.esign import views_sign as esign_sign
from apps.agreements import views_public as agreement_public
from apps.intake import hosts as intake_hosts
from apps.intake import views_public as intake_public
from apps.finance.bankfeeds import views as bank_views
from apps.strategy import views_precall as strategy_precall
from apps.work import views_cadence as work_cadence
from apps.crm import views_unsubscribe as crm_unsubscribe
from apps.scorecard import views_rails as scorecard_rails
from config import spa

urlpatterns = [
    # Django's admin answers on the laptop only (2026-11-27,
    # docs/p17_security_updates.md): no app registers a model with it, and in
    # production and on the demo it was a sign-in form with nothing behind it.
    *([path("admin/", admin.site.urls)] if settings.ADMIN_ENABLED else []),
    # Tier 1 Gmail connect (FR-6.3b). A separate consent from sign-in (C2),
    # so a separate callback — registered on the OAuth client alongside
    # allauth's. Declared BEFORE the allauth include so the path is ours.
    path("accounts/gmail/callback", views_gmail.gmail_callback,
         name="gmail-callback"),
    path("accounts/microsoft/callback", views_microsoft.microsoft_callback,
         name="microsoft-callback"),
    # P2 D1: staff sign-in is email first; External practices sign in through
    # the second OAuth client. Declared BEFORE the allauth include.
    path("accounts/google/start", google_external.google_start, name="google-start"),
    path("accounts/microsoft/start", microsoft_signin.start, name="microsoft-start"),
    path("accounts/google/external/callback", google_external.google_external_callback,
         name="google-external-callback"),
    # allauth: only the pages the sign-in uses; the rest answer "not found",
    # sign-up included (apps/accounts/urls_allauth.py).
    path("accounts/", include("apps.accounts.urls_allauth")),
    # AI apps' OAuth 2.1 authorization server (P7, apps/aiconnect/oauth.py).
    *aiconnect_urls.oauth_patterns,
    # The marketing site's "Request demo access" form, forwarded by the site's
    # own server with the shared secret (apps/crm/views_site_leads.py).
    re_path(r"^api/public/leads/?$", crm_site_leads.leads, name="public-leads"),
    path("api/branding", account_views.branding, name="branding"),
    # The practice's logo for client-facing pages: no id in the URL, so it can
    # only ever serve the requesting tenant's own (white-label).
    path("api/branding/logo", account_views.branding_logo, name="branding-logo"),
    path("api/branding/mark", account_views.branding_mark, name="branding-mark"),
    path("api/me", account_views.me, name="me"),
    path("api/me/profile", account_views.profile, name="profile"),
    path("api/", include("apps.crm.urls")),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.notes.urls")),
    path("api/", include("apps.work.urls")),
    path("api/", include("apps.strategy.urls")),
    path("api/", include("apps.meetings.urls")),
    path("api/", include("apps.platform.urls")),
    path("api/", include("apps.notify.urls")),
    path("api/", include("apps.calendars.urls")),
    path("api/", include("apps.billing.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.personal.urls")),
    path("api/", include("apps.aiconnect.urls")),
    path("api/", include("apps.centers.urls")),
    path("api/", include("apps.plans.urls")),
    path("api/", include("apps.tools.urls")),
    path("api/", include("apps.sops.urls")),
    path("api/", include("apps.scorecard.urls")),
    path("api/", include("apps.esign.urls")),
    path("api/", include("apps.intake.urls")),
    path("api/", include("apps.agreements.urls")),
    # Intake forms, the owner's side (docs/p14_intake_forms.md): a personal
    # link, no session. White label: nothing here names the practice.
    path("api/f/<str:token>", intake_public.form_page, name="intake-form"),
    path("api/f/<str:token>/answers", intake_public.answers, name="intake-answers"),
    path("api/f/<str:token>/secret", intake_public.secret, name="intake-secret"),
    path("api/f/<str:token>/files", intake_public.files, name="intake-files"),
    path("api/f/<str:token>/files/<str:file_id>", intake_public.file_delete,
         name="intake-file"),
    path("api/f/<str:token>/submit", intake_public.submit, name="intake-submit"),
    path("api/f/<str:token>/another", intake_public.another, name="intake-another"),
    path("api/forms/<slug:slug>/<str:which>", intake_public.form_image, name="intake-image"),
    # Owner agreements, the owner's side (docs/p15_owner_agreements.md): the
    # same white-label pages, on the same form domain.
    path("api/fa/<str:token>", agreement_public.agreement_page, name="agreement-page"),
    path("api/fa/<str:token>/details", agreement_public.details, name="agreement-details"),
    path("api/fa/<str:token>/sign", agreement_public.sign, name="agreement-sign"),
    path("api/fa/<str:token>/onboarding", agreement_public.onboarding,
         name="agreement-onboarding"),
    path("api/fa/<str:token>/pdf", agreement_public.owner_pdf, name="agreement-pdf"),
    path("forms/<slug:slug>/a/<str:token>", intake_hosts.agreement_shell,
         name="agreement-shell"),
    path("forms/<slug:slug>/<str:token>", intake_hosts.shell, name="intake-page"),
    path("forms/<slug:slug>", intake_hosts.shell, name="intake-page-bare"),
    # FR-3.33a — the cadence link from a digest footer. No session: the signed
    # token IS the authentication, and it grants that one capability. Under
    # /api/ so the app's own page can render it (the dev proxy forwards /api);
    # the link in the email points at the app route that calls this.
    path("api/cadence/<str:token>", work_cadence.cadence_link, name="cadence-link"),
    path("api/unsubscribe/<str:token>/one-click", crm_unsubscribe.one_click,
         name="unsubscribe-one-click"),
    path("api/unsubscribe/<str:token>", crm_unsubscribe.unsubscribe_link,
         name="unsubscribe-link"),
    # FR-4.6 / matrix 10.13 — the pre-call form. A public page authenticated by
    # one token, which can read and answer nothing but its own session's
    # pre-call questions.
    path("api/strategy/precall/<str:token>", strategy_precall.precall_form,
         name="precall-form"),
    path("api/pay/<str:token>", billing_pay.pay_page, name="pay-page"),
    path("api/pay/<str:token>/pdf", billing_pay.pay_pdf, name="pay-pdf"),
    path("api/pay/<str:token>/form-failed", billing_pay.pay_form_failed,
         name="pay-form-failed"),
    # E-signature: the signing page, by its one-use link (apps/esign/links.py).
    path("api/sign/<str:token>", esign_sign.sign_page, name="sign-page"),
    path("api/sign/<str:token>/pdf", esign_sign.sign_pdf, name="sign-pdf"),
    path("api/sign/<str:token>/decline", esign_sign.sign_decline, name="sign-decline"),
    path("api/strategy/precall/<str:token>/complete", strategy_precall.precall_complete,
         name="precall-complete"),
    path("accounts/refused", account_views.login_refused, name="login-refused"),
    path("auth/sign-out", account_views.sign_out, name="sign-out"),
    path("auth/magic/request", account_views.request_magic_link, name="magic-request"),
    # C3.3: GET renders a confirmation page; only POST consumes the token.
    path("auth/magic/<str:token>", account_views.magic_link_landing, name="magic-landing"),
    path("healthz", spa.healthz, name="healthz"),
    # Bank feeds: Plaid's webhook, verified by its signature (docs/p6_bank_feeds.md).
    path("webhooks/plaid", bank_views.plaid_webhook, name="plaid-webhook"),
    # P13: the connector rails' addresses. The token is the key; no session.
    path("webhooks/kpi/<str:token>/", scorecard_rails.kpi_webhook, name="kpi-webhook"),
    path("webhooks/company/<str:token>/", scorecard_rails.company_webhook,
         name="company-webhook"),
    # Browser notifications' service worker, at the root so it serves every page.
    path("sw.js", spa.service_worker, name="service-worker"),
    # P4 part 1: the token proof, laptop and sandbox only (404 elsewhere).
    path("dev/nmi-proof", billing_proof.proof_page, name="nmi-proof"),
    path("dev/nmi-proof/run", billing_proof.proof_run, name="nmi-proof-run"),
    # P16: where browsers report the app pages' policy violations. Outside
    # /api/ so no gate of the app's stands in the way (docs/p16_card_page_scripts.md).
    path("csp-report", cardpages_views.csp_report, name="csp-report"),
    # Last: every other path is the React app's (production; Phase 7). The
    # server's own prefixes are excluded so a mistyped API URL is a 404, not
    # a page of HTML.
    re_path(r"^(?!api/|admin/|accounts/|auth/|static/|media/|healthz|webhooks/).*$",
            spa.app_shell, name="app-shell"),
]
