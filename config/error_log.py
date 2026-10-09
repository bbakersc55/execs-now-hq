"""A server error leaves its traceback in the service's log (owner, 2026-10-08).

Before this, a 500 on the demo or in production left one line in the access
log and nothing else: Django writes tracebacks to the console only in debug.
The demo's sign-in failed for an hour with no way to read why.

**The traceback only.** Each frame's file, line and function, the line of
code, and the exception's type with the first line of its message. Never
local variables, never the request's body, headers, cookies or query string:
those can carry tokens and client data. The rest of an exception's message is
dropped for the same reason: a database error names the row it choked on in
the lines after the first.
"""

from __future__ import annotations

import logging
import traceback

MESSAGE_MOST = 300


def _summary(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0][:MESSAGE_MOST] if text else ""
    name = f"{type(exc).__module__}.{type(exc).__qualname__}"
    return f"{name}: {first}" if first else name


class TracebackOnly(logging.Formatter):
    """`<time> ERROR <what Django said>` and then the frames."""

    def format(self, record: logging.LogRecord) -> str:
        # `getMessage` is Django's own "Internal Server Error: /path": the
        # path without its query string. Nothing else of the record is read,
        # so the request Django attaches to it never reaches the log.
        lines = [f"{self.formatTime(record)} {record.levelname} {record.getMessage()}"]
        if record.exc_info and record.exc_info[1] is not None:
            lines += self._frames(record.exc_info[1])
        return "\n".join(lines)

    def _frames(self, exc: BaseException) -> list[str]:
        out = []
        cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
        if cause is not None:
            out += self._frames(cause)
            out.append("  ... which led to:")
        out.append("Traceback (most recent call last):")
        for frame in traceback.extract_tb(exc.__traceback__):
            out.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
            if frame.line:
                out.append(f"    {frame.line}")
        out.append(_summary(exc))
        return out


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"traceback_only": {"()": "config.error_log.TracebackOnly"}},
    "handlers": {
        "server_errors": {"class": "logging.StreamHandler", "level": "ERROR",
                          "formatter": "traceback_only"},
    },
    "loggers": {
        # A request that ended in a server error, in every environment.
        "django.request": {"handlers": ["server_errors"], "level": "ERROR",
                           "propagate": False},
    },
}
