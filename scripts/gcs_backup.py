"""The storage half of scripts/backup_db_railway.sh (Phase 7).

What `gcloud storage cp / rsync / rm` do in the laptop script, done with the
google-cloud-storage library the app already depends on, as the backup-writer
service account (GOOGLE_SA_BACKUP_JSON). Standalone: no Django, so it runs
even if the app's settings would not import.

    python scripts/gcs_backup.py upload FILE gs://bucket
    python scripts/gcs_backup.py sync gs://src gs://dst/prefix --exclude REGEX
    python scripts/gcs_backup.py prune gs://bucket --days 30
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def _client():
    from google.cloud import storage
    from google.oauth2 import service_account

    try:
        info = json.loads(os.environ["GOOGLE_SA_BACKUP_JSON"])
    except KeyError:
        sys.exit("!! GOOGLE_SA_BACKUP_JSON is not set (runbook A4a).")
    except ValueError:
        sys.exit("!! GOOGLE_SA_BACKUP_JSON is set but is not valid JSON.")   # never echoed
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return storage.Client(project=info.get("project_id"), credentials=credentials)


def split(url: str) -> tuple[str, str]:
    """gs://bucket/some/prefix -> ("bucket", "some/prefix")."""
    if not url.startswith("gs://"):
        raise ValueError(f"not a gs:// URL: {url!r}")
    bucket, _, prefix = url[len("gs://"):].partition("/")
    return bucket, prefix.strip("/")


def upload(client, path: str, dest: str) -> None:
    bucket, prefix = split(dest)
    name = f"{prefix}/{Path(path).name}" if prefix else Path(path).name
    blob = client.bucket(bucket).blob(name)
    blob.upload_from_filename(path)
    blob.reload()
    if blob.size != Path(path).stat().st_size:
        sys.exit(f"!! Uploaded {blob.size} bytes of {Path(path).stat().st_size}.")
    print(f"    gs://{bucket}/{name} ({blob.size} bytes)")


def to_copy(source: dict[str, tuple[int, str]], dest: dict[str, tuple[int, str]],
            exclude: str | None) -> list[str]:
    """Names to copy: not excluded, and missing or different at the
    destination (size and MD5 both compared). Deletions are never
    propagated — a file deleted by accident stays recoverable."""
    pattern = re.compile(exclude) if exclude else None
    return sorted(name for name, meta in source.items()
                  if not (pattern and pattern.search(name)) and dest.get(name) != meta)


def sync(client, src: str, dst: str, exclude: str | None) -> None:
    src_bucket, src_prefix = split(src)
    dst_bucket, dst_prefix = split(dst)

    def listing(bucket, prefix):
        cut = len(prefix) + 1 if prefix else 0
        return {b.name[cut:]: (b.size, b.md5_hash)
                for b in client.list_blobs(bucket, prefix=f"{prefix}/" if prefix else None)}

    source = listing(src_bucket, src_prefix)
    names = to_copy(source, listing(dst_bucket, dst_prefix), exclude)
    s, d = client.bucket(src_bucket), client.bucket(dst_bucket)
    for name in names:
        # Server-side copy: nothing passes through this container.
        s.copy_blob(s.blob(f"{src_prefix}/{name}" if src_prefix else name), d,
                    f"{dst_prefix}/{name}" if dst_prefix else name)
    print(f"    {len(names)} copied, {len(source) - len(names)} already there or excluded")


def expired(names_and_times, *, days: int, now: dt.datetime) -> list[str]:
    cutoff = now - dt.timedelta(days=days)
    return sorted(name for name, created in names_and_times
                  if name.endswith(".sql.gz") and created < cutoff)


def prune(client, dest: str, days: int) -> None:
    bucket, prefix = split(dest)
    blobs = {b.name: b for b in client.list_blobs(bucket, prefix=prefix or None)}
    old = expired(((n, b.time_created) for n, b in blobs.items()), days=days,
                  now=dt.datetime.now(dt.timezone.utc))
    for name in old:
        print(f"    deleting gs://{bucket}/{name}")
        blobs[name].delete()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("upload"); p.add_argument("path"); p.add_argument("dest")
    p = sub.add_parser("sync"); p.add_argument("src"); p.add_argument("dst")
    p.add_argument("--exclude")
    p = sub.add_parser("prune"); p.add_argument("dest"); p.add_argument("--days", type=int,
                                                                        default=30)
    args = parser.parse_args(argv)
    client = _client()
    if args.command == "upload":
        upload(client, args.path, args.dest)
    elif args.command == "sync":
        sync(client, args.src, args.dst, args.exclude)
    else:
        prune(client, args.dest, args.days)


if __name__ == "__main__":
    main()
