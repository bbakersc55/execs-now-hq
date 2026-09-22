"""The startup check: refuse to start rather than fail in front of somebody.

Registered as a Django system check, which `runserver` and `qcluster` both run
before they do anything. An `Error` makes them **abort**, printing what is
missing and how to fix it.

**Only on those two commands.** The check imports WeasyPrint and the Google
client libraries to prove they work, which costs about a second — worth paying
once when a server starts, not on every `manage.py` invocation, and not on the
one command that would fix the problem. Anything else, including `migrate` and
`check` itself, is unaffected unless you ask for it with `--tag runtime`.
"""

from __future__ import annotations

import sys

from django.core.checks import Error, Tags, register

from config.startup import missing

#: The long-running processes. A person starting one of these is about to rely
#: on the app working; a person running `migrate` is not yet.
SERVER_COMMANDS = {"runserver", "qcluster"}

RUNTIME = "runtime"


def starting_a_server(argv=None) -> bool:
    argv = sys.argv if argv is None else argv
    return len(argv) > 1 and argv[1] in SERVER_COMMANDS


def asked_for_explicitly(argv=None) -> bool:
    """`manage.py check --tag runtime` runs it anywhere — which is what a
    deploy script or a CI step should call."""
    argv = sys.argv if argv is None else argv
    return RUNTIME in argv


@register(Tags.compatibility, RUNTIME)
def runtime_imports(app_configs, **kwargs):
    """Every deferred import the app depends on, proved before we start.

    These imports live inside the functions that use them, so nothing here
    fails at boot and nothing fails in the test suite, which fakes exactly
    these boundaries. Without this check the first sign of a missing package
    is a person hitting the feature. *(Added 2026-09-22, after
    `google-api-python-client` reached Module 5's Drive client without ever
    reaching `requirements.txt`.)*
    """
    if not (starting_a_server() or asked_for_explicitly()):
        return []
    return [
        Error(
            f"{need.module} will not import, so {need.why} cannot work.",
            hint=(f"{need.distribution} is missing or broken: {exc}. "
                  "Run `.venv/bin/pip install -r requirements.txt` — after any "
                  "pull, this is the fix."),
            id=f"execsnowhq.E001.{need.distribution}",
        )
        for need, exc in missing()
    ]
