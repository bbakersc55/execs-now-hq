"""Run a manage.py command with the app's clock moved (proofs only, 2026-11-17).

    .venv/bin/python scripts/moved_clock.py 2027-01-01T16:00:00+00:00 runserver 127.0.0.1:8199 --noreload

`django.utils.timezone.now` answers that moment plus the time since the
command started, so the server (or command) lives on a later day, as the
tests' `at()` does inside one test. Refuses any database but a proof's own
(a name ending in _nmi_proof or _walk): never `execsnowhq_local`.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    target = datetime.fromisoformat(sys.argv[1])
    if target.tzinfo is None:
        sys.exit("Give the moment with its offset, e.g. 2027-01-01T16:00:00+00:00.")
    database = os.environ.get("DATABASE_URL", "").rstrip("/").rsplit("/", 1)[-1]
    if not database.endswith(("_nmi_proof", "_walk")):
        sys.exit(f"Refused: {database or 'the configured database'} is not a proof's own.")
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    from django.utils import timezone

    real_now, started = timezone.now, datetime.now(UTC)
    with mock.patch("django.utils.timezone.now",
                    side_effect=lambda: target + (real_now() - started)):
        execute_from_command_line(["manage.py", *sys.argv[2:]])


if __name__ == "__main__":
    main()
