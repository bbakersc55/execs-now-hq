"""The owner's form on its own domain, white-labelled (owner, 2026-11-19).

On a form's domain only the form answers: its pages (/<token>), its API
(/api/f/...), its logo and icon, and its own built bundle (/static/forms/...).
Anything else gets the form's own plain not-found page. Nothing on those pages
loads from ENHQ's host, and nothing names Execs NOW HQ, Executives Now, the
practice or anyone in it.

A domain also has to be added to the web service in Railway, pointed at it in
DNS, and listed in INTAKE_FORM_HOSTS (it joins ALLOWED_HOSTS): see
docs/p14_intake_forms.md. Until then links use ENHQ's host and the slug.
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.utils.html import escape

TOKEN_PATH = re.compile(r"^/(?P<token>[A-Za-z0-9_-]{20,100})/?$")
ALLOWED = re.compile(r"^/(?:api/f/[A-Za-z0-9_-]{1,100}(?:/.*)?|static/forms/.+|"
                     r"api/forms/[a-z0-9-]+/(?:logo|icon))$")
#: Seconds a host -> form lookup is trusted before the database is asked again.
CACHE_SECONDS = 60
_cache: dict = {"at": 0.0, "hosts": {}}

POLICY = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
          "font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
          "base-uri 'none'; form-action 'self'; object-src 'none'")


def _hosts() -> dict:
    from .models import IntakeForm

    now = time.monotonic()
    if now - _cache["at"] > CACHE_SECONDS:
        _cache["hosts"] = {f.domain.lower(): f.pk for f in
                           IntakeForm.all_objects.exclude(domain="").only("pk", "domain")}
        _cache["at"] = now
    return _cache["hosts"]


def forget():
    """After a form's domain changes."""
    _cache["at"] = 0.0


def form_for_host(host: str):
    from .models import IntakeForm

    form_id = _hosts().get((host or "").split(":")[0].lower().rstrip("."))
    return IntakeForm.all_objects.select_related("company").filter(pk=form_id).first() \
        if form_id else None


def live_hosts() -> set:
    return {h.lower() for h in getattr(settings, "INTAKE_FORM_HOSTS", [])}


class FormDomainMiddleware:
    """First in the chain after SecurityMiddleware, so even static files
    answer only the form's own on its domain."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        form = form_for_host(request.META.get("HTTP_HOST", ""))
        if form is None:
            return self.get_response(request)
        request.intake_form = form
        path = request.path_info
        match = TOKEN_PATH.match(path)
        if match and request.method in ("GET", "HEAD"):
            return shell(request, token=match.group("token"), form=form)
        if ALLOWED.match(path):
            return self.get_response(request)
        return not_found(form)


# ------------------------------------------------------------ pages

def _branding(form) -> dict:
    from .models import IntakeForm  # noqa: F401

    colors = {"primary": "#428227", "primary_dark": "#356A1F", "heading": "#36424A",
              "text": "#4A4A4A", "background": "#FAF9F5", "accent": "#006BA6",
              "error": "#B3261E", **(form.colors or {})}
    return {"brand_name": form.brand_name, "title": form.title, "slug": form.slug,
            "colors": colors, "contact_phone": form.contact_phone,
            "contact_email": form.contact_email,
            "logo": f"/api/forms/{form.slug}/logo" if form.logo_id else "",
            "icon": f"/api/forms/{form.slug}/icon" if form.icon_id else ""}


@lru_cache(maxsize=1)
def _built_index() -> str | None:
    for base in (Path(settings.STATIC_ROOT) / "forms",
                 settings.BASE_DIR / "frontend" / "dist" / "forms"):
        path = base / "index.html"
        if path.is_file():
            return path.read_text()
    return None


#: An icon the browser shows instead of asking the host for /favicon.ico.
BLANK_ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'"
              "%3E%3C/svg%3E")


def _head(form) -> str:
    brand = _branding(form)
    icon = brand["icon"] or BLANK_ICON
    config = json.dumps(brand).replace("<", "\\u003c")
    title = f"{form.title} · {form.brand_name}"
    return (f"<title>{escape(title)}</title>"
            f'<link rel="icon" href="{escape(icon)}" />'
            f'<meta name="theme-color" content="{escape(brand["colors"]["primary"])}" />'
            f'<script type="application/json" id="intake-config">{config}</script>')


def _respond(html: str, status=200) -> HttpResponse:
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = POLICY
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def shell(request, token=None, slug=None, form=None):
    """The owner's form page (the built bundle in `dist/forms`), with the
    form's own title, icon and look. A token that doesn't resolve still gets
    the page: it shows the form's own "this link isn't valid" screen."""
    from .models import IntakeForm

    if form is None:
        form = IntakeForm.all_objects.filter(slug=slug).first()
        if form is None:
            return _respond(_plain("This page isn't here", "Check the link you were sent.",
                                   None), 404)
    index = _built_index()
    if index is None:
        return _respond(_plain(form.title, "This form isn't available just now. Please try "
                               "again later.", form), 503)
    html = re.sub(r"<title>.*?</title>", "", index, count=1, flags=re.S)
    html = re.sub(r'<link rel="icon"[^>]*>', "", html)
    html = html.replace("</head>", _head(form) + "</head>", 1)
    return _respond(html)


def not_found(form) -> HttpResponse:
    return _respond(_plain("This page isn't here",
                           "Check the link you were sent, or get in touch with us.", form), 404)


def _plain(heading: str, text: str, form) -> str:
    brand = _branding(form) if form is not None else None
    colors = brand["colors"] if brand else {"background": "#FFFFFF", "heading": "#333333",
                                            "text": "#444444"}
    contact = ""
    if brand and (brand["contact_phone"] or brand["contact_email"]):
        bits = [escape(b) for b in (brand["contact_phone"], brand["contact_email"]) if b]
        contact = f'<p class="c">{" · ".join(bits)}</p>'
    logo = f'<img src="{escape(brand["logo"])}" alt="{escape(brand["brand_name"])}" />' \
        if brand and brand["logo"] else (f"<strong>{escape(brand['brand_name'])}</strong>"
                                         if brand else "")
    title = f"{heading} · {brand['brand_name']}" if brand else heading
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\" />"
            '<meta name="viewport" content="width=device-width, initial-scale=1" />'
            f"<title>{escape(title)}</title>"
            f'<link rel="icon" href="{escape((brand or {}).get("icon") or BLANK_ICON)}" />'
            "<style>body{margin:0;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
            f"background:{colors['background']};color:{colors['text']}}}"
            "main{max-width:520px;margin:12vh auto;padding:24px;text-align:center}"
            f"h1{{color:{colors['heading']};font-size:1.5rem}}"
            "img{max-height:48px;max-width:240px}.c{margin-top:32px;font-size:.95rem}"
            "</style></head><body><main>"
            f"{logo}<h1>{escape(heading)}</h1><p>{escape(text)}</p>{contact}"
            "</main></body></html>")
