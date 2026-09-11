"""One-time Phase 2 move: local MEDIA_ROOT content -> gs://<bucket>/<object_key>.

Rows are not touched. The local layout was always <bucket>/<object_key>, so
every row already names the object it will point at; this only puts the bytes
there. Local files are left in place — deleting them is a separate decision.

Dry run by default. Each copy is read back through the app's own key and
compared by SHA-256 before it counts, so "copied" means "verified identical",
not "the upload call returned".
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenancy import storage
from apps.tenancy.models import StoredFile


class Command(BaseCommand):
    help = "Copy stored_file content from MEDIA_ROOT to GCS, verifying each object."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Actually upload. Without it, only the plan is printed.")

    def handle(self, *args, **options):
        local = storage.LocalBackend(Path(settings.MEDIA_ROOT))
        gcs = storage.GcsBackend()
        apply = options["apply"]

        # Several rows can share one key (the flyer-collision bug), so the unit
        # of work is the object, not the row.
        objects = {}
        for row in StoredFile.all_objects.all().order_by("created_at"):
            objects.setdefault((row.bucket, row.object_key), []).append(row)

        self.stdout.write(f"{'APPLY' if apply else 'DRY RUN'}: {len(objects)} objects "
                          f"referenced by {sum(map(len, objects.values()))} rows, "
                          f"from {settings.MEDIA_ROOT}")
        copied = already = no_source = 0
        for (bucket, key), rows in objects.items():
            content = local.read(bucket, key)
            label = f"gs://{bucket}/{key} ({len(rows)} row{'s' * (len(rows) > 1)})"
            if not content:
                no_source += 1
                self.stdout.write(self.style.WARNING(f"  no local content  {label}"))
                continue
            digest = hashlib.sha256(content).hexdigest()
            remote_size = gcs.size(bucket, key)
            if remote_size is not None:
                same = hashlib.sha256(gcs.read(bucket, key) or b"").hexdigest() == digest
                already += same
                style = self.style.SUCCESS if same else self.style.ERROR
                self.stdout.write(style(
                    f"  {'already there' if same else 'DIFFERS IN GCS'}     {label}"
                ))
                continue
            if not apply:
                self.stdout.write(f"  would copy        {label}  {len(content)} bytes  sha256 {digest[:12]}")
                continue
            gcs.write(bucket, key, content, rows[0].content_type)
            back = gcs.read(bucket, key) or b""
            if hashlib.sha256(back).hexdigest() != digest:
                raise storage.StorageUnavailable(f"{label}: read-back does not match the source.")
            copied += 1
            self.stdout.write(self.style.SUCCESS(
                f"  copied, verified  {label}  {len(back)} bytes  sha256 {digest[:12]}"
            ))

        self.stdout.write(f"copied {copied}, already present {already}, "
                          f"no local content {no_source}")
