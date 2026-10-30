"""Signing tokens never reach the service's log (owner, 2026-10-29).

A signing link is the whole of its signer's authentication, and production's
access log had it whole: in the path of every `/api/sign/<token>` request and
in the Referer of each one the page made from `/sign/<token>`, and in the
branding call's `via=sign:<token>`. `mask` replaces the token with `<token>`
wherever it appears in a logged string; the access log (gunicorn's
`--logger-class`, `scripts/start_web.sh`) and a server error's line
(`config/error_log.py`) both go through it.
"""

from __future__ import annotations

import re

from gunicorn import glogging

MASK = "<token>"

#: `/sign/<token>` (the page) and `/api/sign/<token>[/pdf|/decline]`, in a
#: path or a full URL; and `via=sign:<token>`, with the colon encoded or not.
_SIGN_PATH = re.compile(r'(/(?:api/)?sign/)[^/?#\s"]+')
_SIGN_VIA = re.compile(r'(via=sign(?::|%3[Aa]))[^&#\s"]+')


def mask(text: str) -> str:
    return _SIGN_VIA.sub(rf"\g<1>{MASK}", _SIGN_PATH.sub(rf"\g<1>{MASK}", text))


class MaskedAccessLogger(glogging.Logger):
    """gunicorn's logger with every string of an access line masked: the
    request line, path, query string and Referer, and any header or environ
    value a log format could name."""

    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        return {key: mask(value) if isinstance(value, str) else value
                for key, value in atoms.items()}
