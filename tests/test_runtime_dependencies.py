"""The suite must not be able to pass with a runtime dependency missing.

**This file exists because it once could.** Module 5's Drive client imports
`googleapiclient`, which was installed on the laptop and never added to
`requirements.txt`. Every test passed — the meeting tests run against a fake
at exactly that boundary — and the real path died with `ModuleNotFoundError`
the first time a folder was connected.

Three guards, in the order they would have caught it:

1. **Every deferred third-party import in the app is declared** in
   `config.startup.NEEDS`. This is the one that would have failed the moment
   `drive.py` was written, before anything was pinned or not pinned.
2. **Every declared import actually imports**, which is what a fresh checkout
   or a Railway build has to satisfy.
3. **Every one is pinned in `requirements.txt` at the version installed here**,
   which is the failure that actually happened: importable locally, absent
   from the file that builds every other environment.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from importlib.metadata import PackageNotFoundError, version

import pytest

from config import checks, startup

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Roots that need no declaring: first-party, and the frameworks without which
#: `manage.py` itself would not run. If Django is missing, no check of ours is
#: going to be the thing that says so.
EXEMPT_ROOTS = {"apps", "config", "tests", "django", "django_q", "rest_framework"}


def deferred_import_roots() -> dict[str, set[str]]:
    """Every third-party import written *inside a function* in app code.

    A deferred import is invisible at startup by design — that is why they are
    written this way — so the price is that nothing proves it works until
    somebody uses the feature. This is the list of imports that have bought
    that trade, and each one has to be declared.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(list((ROOT / "apps").rglob("*.py"))
                       + list((ROOT / "config").rglob("*.py"))):
        tree = ast.parse(path.read_text())
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for function in functions:
            for node in ast.walk(function):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root in EXEMPT_ROOTS or root in sys.stdlib_module_names:
                        continue
                    found.setdefault(root, set()).add(
                        str(path.relative_to(ROOT)))
    return found


def test_every_deferred_import_in_the_app_is_declared():
    """Guard 1 — the one that closes the class, not just the instance.

    Adding a new third-party import inside a function fails here until it is
    added to `config.startup.NEEDS`, which is what makes the startup check and
    the two tests below cover it.
    """
    declared = {need.module.split(".")[0] for need in startup.NEEDS}
    undeclared = {root: sorted(where) for root, where
                  in deferred_import_roots().items() if root not in declared}

    assert not undeclared, (
        "These are imported inside functions, so nothing will notice they are "
        "missing until somebody uses the feature. Add each to "
        f"config.startup.NEEDS: {undeclared}")


@pytest.mark.parametrize("need", startup.NEEDS, ids=[n.module for n in startup.NEEDS])
def test_every_declared_import_actually_imports(need):
    """Guard 2 — the real module, not a fake. A fresh checkout, a new laptop
    and a Railway build all have to satisfy this."""
    assert not startup.missing((need,)), (
        f"{need.module} will not import, so {need.why} cannot work. "
        "Run `.venv/bin/pip install -r requirements.txt`.")


def pinned_requirements() -> dict[str, str]:
    """`requirements.txt` as `{normalised name: version}`."""
    pins = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or "==" not in line:
            continue
        name, pinned = line.split("==", 1)
        pins[re.sub(r"[-_.]+", "-", name).lower()] = pinned.strip()
    return pins


@pytest.mark.parametrize("need", startup.NEEDS, ids=[n.distribution for n in startup.NEEDS])
def test_every_declared_import_is_pinned_at_the_installed_version(need):
    """Guard 3 — the failure that actually happened.

    Importing proves the package is on *this* laptop. Only the pin puts it in
    every other environment, and a pin that has drifted from what is installed
    means the suite is proving something about an environment nobody else gets.
    """
    pins = pinned_requirements()
    name = re.sub(r"[-_.]+", "-", need.distribution).lower()

    assert name in pins, (
        f"{need.distribution} provides {need.module}, which {need.why} needs, "
        "and it is not in requirements.txt. It works here and nowhere else.")

    try:
        installed = version(need.distribution)
    except PackageNotFoundError:                        # pragma: no cover
        pytest.fail(f"{need.distribution} is not installed in this environment.")
    assert pins[name] == installed, (
        f"requirements.txt pins {need.distribution}=={pins[name]} but "
        f"{installed} is installed. Whichever is right, the other environments "
        "get the pin.")


def test_the_startup_check_refuses_and_says_what_is_missing():
    """The refusal names the package, what it breaks, and the one command that
    fixes it — because the person reading it has just pulled."""
    ghost = startup.Need("no_such_module_at_all", "ghost-lib",
                         "nothing — this is the test's own")
    found = startup.missing((ghost,))

    assert len(found) == 1
    need, exc = found[0]
    assert need is ghost
    assert "no_such_module_at_all" in str(exc)


@pytest.mark.parametrize("argv,expected", [
    (["manage.py", "runserver", "8100"], True),
    (["manage.py", "qcluster"], True),
    (["manage.py", "migrate"], False),
    (["manage.py", "shell"], False),
    (["manage.py"], False),
    ([], False),
])
def test_the_check_runs_when_a_server_starts_and_not_otherwise(argv, expected):
    """It imports WeasyPrint and the Google libraries to prove they work,
    which costs about a second. Worth paying when a server starts; not worth
    paying on every `manage.py` call, and least of all on the command someone
    is running to fix it."""
    assert checks.starting_a_server(argv) is expected


def test_the_check_can_be_asked_for_anywhere():
    """`manage.py check --tag runtime` is what a deploy step should call."""
    assert checks.asked_for_explicitly(["manage.py", "check", "--tag", "runtime"])
    assert not checks.asked_for_explicitly(["manage.py", "check"])
