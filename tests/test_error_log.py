"""A server error leaves its traceback in the log, and only its traceback
(owner, 2026-10-08): never local variables, never anything of the request."""

from __future__ import annotations

import io
import logging

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import path

from config.error_log import TracebackOnly

SECRET_LOCAL = "token-in-a-local-variable-9f3a"
SECRET_BODY = "client-data-in-the-body-71cc"
SECRET_QUERY = "token-in-the-query-string-55b0"
SECRET_HEADER = "cookie-or-header-value-e2d4"
SECRET_DETAIL = "dana.reyes@northwind.example"


def breaks(request):
    held = SECRET_LOCAL                                    # noqa: F841
    try:
        raise KeyError("the first thing that went wrong")
    except KeyError as first:
        raise RuntimeError("could not save the row\n"
                           f"DETAIL: Key (email)=({SECRET_DETAIL}) already exists.") from first


def fine(request):
    return HttpResponse("ok")


urlpatterns = [path("breaks/", breaks), path("fine/", fine)]


@pytest.fixture
def written():
    """What the server-error handler would write, caught."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.ERROR)
    handler.setFormatter(TracebackOnly())
    logger = logging.getLogger("django.request")
    logger.addHandler(handler)
    yield stream
    logger.removeHandler(handler)


def test_every_environment_logs_server_errors_with_this_formatter():
    config = settings.LOGGING
    assert config["disable_existing_loggers"] is False
    assert config["loggers"]["django.request"]["handlers"] == ["server_errors"]
    assert config["handlers"]["server_errors"]["formatter"] == "traceback_only"
    assert config["formatters"]["traceback_only"]["()"] == "config.error_log.TracebackOnly"
    # And it is what is installed (the test runner may add handlers of its own).
    assert any(isinstance(handler.formatter, TracebackOnly) and handler.level == logging.ERROR
               for handler in logging.getLogger("django.request").handlers)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_a_server_error_is_logged_as_its_traceback_and_nothing_else(written):
    client = Client(raise_request_exception=False)
    response = client.post(f"/breaks/?token={SECRET_QUERY}", data={"note": SECRET_BODY},
                           HTTP_COOKIE=f"sessionid={SECRET_HEADER}",
                           HTTP_AUTHORIZATION=f"Bearer {SECRET_HEADER}")
    assert response.status_code == 500

    text = written.getvalue()
    # What a person needs to find the cause.
    assert "Internal Server Error: /breaks/" in text
    assert "Traceback (most recent call last):" in text
    assert "test_error_log.py" in text and "in breaks" in text
    assert "RuntimeError: could not save the row" in text
    assert "KeyError" in text and "which led to" in text, "the cause is there too"
    # What must never be there.
    for secret in (SECRET_LOCAL, SECRET_BODY, SECRET_QUERY, SECRET_HEADER, SECRET_DETAIL):
        assert secret not in text
    assert "DETAIL" not in text, "only the first line of an exception's message"
    assert "sessionid" not in text and "Bearer" not in text


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_a_request_that_works_or_is_merely_refused_logs_nothing(written):
    client = Client(raise_request_exception=False)
    assert client.get("/fine/").status_code == 200
    assert client.get("/nowhere/").status_code == 404
    assert written.getvalue() == ""


def test_a_long_message_is_cut():
    try:
        raise ValueError("x" * 5000)
    except ValueError as exc:
        record = logging.LogRecord("django.request", logging.ERROR, __file__, 1,
                                   "Internal Server Error: %s", ("/x/",),
                                   (type(exc), exc, exc.__traceback__))
    assert len(TracebackOnly().format(record)) < 1200
