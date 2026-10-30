"""Signing tokens never reach production's log (owner, 2026-10-29): a signing
link is its signer's whole authentication, and the access log had it whole,
in paths and in the Referer of the page's own requests."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from gunicorn.config import Config

from config.error_log import TracebackOnly
from config.log_masking import MaskedAccessLogger, mask

TOKEN = "fake-signing-token_0123456789abcdefABCDEF"


def test_mask_takes_the_token_out_of_every_place_it_is_logged():
    cases = {
        f"GET /api/sign/{TOKEN} HTTP/1.1": "GET /api/sign/<token> HTTP/1.1",
        f"/api/sign/{TOKEN}/pdf": "/api/sign/<token>/pdf",
        f"/api/sign/{TOKEN}/decline": "/api/sign/<token>/decline",
        f"https://app.getexecutivesnow.com/sign/{TOKEN}":
            "https://app.getexecutivesnow.com/sign/<token>",
        f"https://app.getexecutivesnow.com/sign/{TOKEN}?x=1#y":
            "https://app.getexecutivesnow.com/sign/<token>?x=1#y",
        f"via=sign%3A{TOKEN}&size=2": "via=sign%3A<token>&size=2",
        f"via=sign%3a{TOKEN}": "via=sign%3a<token>",
        f"via=sign:{TOKEN}": "via=sign:<token>",
    }
    for logged, masked in cases.items():
        assert mask(logged) == masked


def test_mask_leaves_everything_else_alone():
    for text in ("GET /auth/sign-out HTTP/1.1", "/api/documents/d1/countersign/",
                 "/api/pay/abc/pdf", "via=pay%3Aabc", "-", "Mozilla/5.0 (X11; Linux x86_64)"):
        assert mask(text) == text


def _access_line(environ: dict) -> str:
    """The line gunicorn writes with the production start's access log."""
    cfg = Config()
    cfg.set("accesslog", "-")
    logger = MaskedAccessLogger(cfg)
    base = {"REQUEST_METHOD": "GET", "SERVER_PROTOCOL": "HTTP/1.1", "REMOTE_ADDR": "100.64.0.9",
            "HTTP_USER_AGENT": "Mozilla/5.0", "QUERY_STRING": ""}
    environ = {**base, **environ}
    resp = SimpleNamespace(status="200 OK", sent=12629, headers=[])
    req = SimpleNamespace(headers=[("REFERER", environ.get("HTTP_REFERER", ""))])
    return cfg.access_log_format % logger.atoms(resp, req, environ, timedelta(seconds=0))


def test_the_access_log_masks_the_path_and_the_referer():
    line = _access_line({
        "RAW_URI": f"/api/sign/{TOKEN}/pdf", "PATH_INFO": f"/api/sign/{TOKEN}/pdf",
        "HTTP_REFERER": f"https://app.getexecutivesnow.com/sign/{TOKEN}"})
    assert TOKEN not in line
    assert ('"GET /api/sign/<token>/pdf HTTP/1.1" 200 12629 '
            '"https://app.getexecutivesnow.com/sign/<token>" "Mozilla/5.0"') in line


def test_the_access_log_masks_the_branding_call():
    line = _access_line({"RAW_URI": f"/api/branding?via=sign%3A{TOKEN}",
                         "PATH_INFO": "/api/branding", "QUERY_STRING": f"via=sign%3A{TOKEN}"})
    assert TOKEN not in line and "/api/branding?via=sign%3A<token>" in line


def test_production_starts_gunicorn_with_the_masking_logger():
    start = (Path(__file__).resolve().parent.parent / "scripts/start_web.sh").read_text()
    assert "--logger-class config.log_masking.MaskedAccessLogger" in start
    assert "--access-logfile -" in start


def test_a_server_error_on_a_signing_path_is_logged_masked():
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        record = logging.LogRecord("django.request", logging.ERROR, __file__, 1,
                                   "Internal Server Error: %s", (f"/api/sign/{TOKEN}/pdf",),
                                   (type(exc), exc, exc.__traceback__))
    text = TracebackOnly().format(record)
    assert TOKEN not in text and "Internal Server Error: /api/sign/<token>/pdf" in text
