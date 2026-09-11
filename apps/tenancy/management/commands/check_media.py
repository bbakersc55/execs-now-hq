"""Reconcile `stored_file` rows against the bytes on disk.

The restore drill's media half needs an answer to "did the blobs come back?",
and counting files does not answer it — the question is whether every row the
database references has content behind it.

This is also the check that would have caught the 0-byte attachment bug before
a partner did: rows existed, sizes were recorded, and not one file had ever
been written.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.tenancy import storage
from apps.tenancy.models import StoredFile


class Command(BaseCommand):
    help = "Report stored_file rows whose content is missing from storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict", action="store_true",
            help="Exit non-zero if any row is missing its content. For the "
                 "restore drill and for CI.",
        )

    def handle(self, *args, **options):
        rows = list(StoredFile.all_objects.all().order_by("purpose", "object_key"))
        missing, present, total_bytes = [], 0, 0

        for row in rows:
            if storage.exists(row):
                present += 1
                total_bytes += row.byte_size
            else:
                missing.append(row)

        self.stdout.write(f"stored_file rows : {len(rows)}")
        self.stdout.write(f"content present  : {present} ({total_bytes} bytes)")
        self.stdout.write(f"content MISSING  : {len(missing)}")

        for row in missing:
            self.stdout.write(self.style.ERROR(
                f"  missing  {row.purpose:18} {row.object_key} "
                f"(recorded {row.byte_size} bytes)"
            ))

        if missing:
            self.stdout.write("")
            self.stdout.write(
                "A missing file is not recoverable from the database. Re-upload it; "
                "any send that would attach one is refused rather than delivering an "
                "empty document."
            )
            if options["strict"]:
                raise SystemExit(1)
        else:
            self.stdout.write(self.style.SUCCESS(
                "Every stored_file row has its content."
            ))
