"""The Railway backup (Phase 7): what can be checked without Google or Railway.

The script itself runs only on Railway, so it is **written, not exercised** until
runbook C10. These tests pin the decisions it makes: what is copied, what is
pruned, and the order of the steps.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("gcs_backup", ROOT / "scripts" / "gcs_backup.py")
gcs_backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gcs_backup)


def test_split_reads_bucket_and_prefix():
    assert gcs_backup.split("gs://execs-now-hq-db-backups") == ("execs-now-hq-db-backups", "")
    assert gcs_backup.split("gs://b/media/execs-now-hq-media/") == ("b", "media/execs-now-hq-media")


def test_recordings_are_never_copied_and_nothing_is_deleted():
    source = {"flyers/a.pdf": (10, "x"), "recordings/n1.webm": (99, "r"),
              "outbox/b.pdf": (5, "y")}
    dest = {"outbox/b.pdf": (5, "y"), "flyers/gone-from-source.pdf": (3, "z")}
    assert gcs_backup.to_copy(source, dest, r"^recordings/") == ["flyers/a.pdf"]


def test_a_changed_file_is_copied_again():
    assert gcs_backup.to_copy({"flyers/a.pdf": (10, "new")},
                              {"flyers/a.pdf": (10, "old")}, None) == ["flyers/a.pdf"]


def test_pruning_touches_only_old_dumps():
    now = dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)
    old, new = now - dt.timedelta(days=31), now - dt.timedelta(days=2)
    names = [("execsnowhq_prod_20260829_080000.sql.gz", old),
             ("execsnowhq_prod_20260927_080000.sql.gz", new),
             ("media/execs-now-hq-media/flyers/a.pdf", old)]
    assert gcs_backup.expired(names, days=30, now=now) == [
        "execsnowhq_prod_20260829_080000.sql.gz"], "the media copy is never pruned by age"


def test_the_script_keeps_the_laptop_scripts_safeguards_in_order():
    script = (ROOT / "scripts" / "backup_db_railway.sh").read_text()
    steps = [script.index(s) for s in (
        "pg_dump --no-owner --no-privileges", 'if [ "${SIZE}" -lt 1024 ]',
        "\"${HELPER}\" upload", "\"${HELPER}\" sync", "\"${HELPER}\" prune")]
    assert steps == sorted(steps), "dump, size floor, upload, media, prune — in that order"
    assert "set -euo pipefail" in script
    assert "execsnowhq_prod_" in script
