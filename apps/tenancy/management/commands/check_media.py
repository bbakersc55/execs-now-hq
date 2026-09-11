"""Reconcile `stored_file` rows against the bytes in storage.

The restore drill's media half needs an answer to "did the blobs come back?",
and counting files does not answer it — the question is whether every row the
database references has content behind it.

This is also the check that would have caught the 0-byte attachment bug before
a partner did: rows existed, sizes were recorded, and not one file had ever
been written.

Since Phase 2 it compares SIZES, not just presence: one listing per bucket
gives every object's size for free, and a truncated object that "exists" is
the same failure as a missing one, discovered later. It runs against whichever
backend STORAGE_BACKEND selects — GCS day to day, `local` in the restore drill.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.tenancy import storage
from apps.tenancy.models import StoredFile


class Command(BaseCommand):
    help = "Report stored_file rows whose content is missing from storage or the wrong size."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict", action="store_true",
            help="Exit non-zero if any row is missing its content or has the "
                 "wrong size. For the restore drill and for CI.",
        )
        parser.add_argument(
            "--exclude-purpose", action="append", default=[], metavar="PURPOSE",
            help="Skip rows with this purpose (repeatable). The restore drill "
                 "passes recording_audio: recordings are not in the backup, by "
                 "design, so retention can delete them.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        excluded = set(options["exclude_purpose"])
        all_rows = list(StoredFile.all_objects.all().order_by("purpose", "object_key"))
        rows = [r for r in all_rows if r.purpose not in excluded]

        by_bucket = defaultdict(list)
        for row in rows:
            by_bucket[row.bucket].append(row)

        self.stdout.write(f"backend          : {settings.STORAGE_BACKEND}")
        listings = {}
        for bucket in sorted(by_bucket):
            try:
                listings[bucket] = storage.sizes(bucket)
            except storage.StorageUnavailable as exc:
                # Not a pass and not a list of missing files: the check did not run.
                self.stdout.write(self.style.ERROR(f"Could not check {bucket}: {exc}"))
                raise SystemExit(2)

        missing, wrong_size, present, total_bytes = [], [], 0, 0
        for row in rows:
            actual = listings[row.bucket].get(row.object_key)
            if not actual:
                missing.append(row)
            elif actual != row.byte_size:
                wrong_size.append((row, actual))
            else:
                present += 1
                total_bytes += actual

        referenced = {(r.bucket, r.object_key) for r in all_rows}
        orphans = sum(
            1 for bucket, objects in listings.items()
            for key in objects if (bucket, key) not in referenced
        )

        self.stdout.write(f"stored_file rows : {len(all_rows)}")
        if excluded:
            self.stdout.write(
                f"  skipped        : {len(all_rows) - len(rows)} "
                f"({', '.join(sorted(excluded))})"
            )
        self.stdout.write(f"content present  : {present} ({total_bytes} bytes)")
        self.stdout.write(f"content MISSING  : {len(missing)}")
        self.stdout.write(f"WRONG SIZE       : {len(wrong_size)}")
        # Informational: an object with no row is the harmless direction (a
        # write whose row never landed). It is never counted as a failure.
        self.stdout.write(f"objects, no row  : {orphans}")

        for row in missing:
            self.stdout.write(self.style.ERROR(
                f"  missing  {row.purpose:18} {row.object_key} "
                f"(recorded {row.byte_size} bytes)"
            ))
        for row, actual in wrong_size:
            self.stdout.write(self.style.ERROR(
                f"  size     {row.purpose:18} {row.object_key} "
                f"(recorded {row.byte_size}, stored {actual})"
            ))

        if missing or wrong_size:
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
