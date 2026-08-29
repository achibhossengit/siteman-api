"""Find and delete media objects not referenced by User, Labour, or SiteCash."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.storage import Storage, default_storage
from django.utils import timezone

from labours.models import Labour
from sites.models import SiteCash

PHOTO_PREFIXES = ("users/", "labours/", "sitecash/")
PREFIX_LABEL = "users/, labours/, and sitecash/"
DELETE_BATCH_SIZE = 1000


@dataclass(frozen=True)
class StoredObject:
    key: str
    last_modified: datetime | None


@dataclass(frozen=True)
class PurgeResult:
    referenced_count: int
    stored_count: int
    orphan_count: int
    deleted_count: int
    skipped_new_count: int
    dry_run: bool
    orphans: tuple[str, ...]


def get_referenced_photo_keys() -> set[str]:
    """Keys currently stored on User.photo, Labour.photo, and SiteCash.file."""
    User = get_user_model()
    keys: set[str] = set()
    for qs, field in (
        (User.objects.exclude(photo="").exclude(photo__isnull=True), "photo"),
        (Labour.objects.exclude(photo="").exclude(photo__isnull=True), "photo"),
        (SiteCash.objects.exclude(file="").exclude(file__isnull=True), "file"),
    ):
        for name in qs.values_list(field, flat=True):
            if name:
                keys.add(name)
    return keys


def _is_s3_storage(storage: Storage) -> bool:
    return hasattr(storage, "bucket") and hasattr(storage, "connection")


def list_stored_photo_objects(storage: Storage | None = None) -> list[StoredObject]:
    """List objects under users/, labours/, and sitecash/ on default media storage."""
    storage = storage or default_storage
    if _is_s3_storage(storage):
        return _list_s3_photo_objects(storage)
    return _list_filesystem_photo_objects(storage)


def _list_s3_photo_objects(storage: Storage) -> list[StoredObject]:
    client = storage.connection.meta.client
    bucket = storage.bucket_name
    found: list[StoredObject] = []
    paginator = client.get_paginator("list_objects_v2")
    for prefix in PHOTO_PREFIXES:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents") or ():
                key = obj.get("Key")
                if not key or key.endswith("/"):
                    continue
                found.append(
                    StoredObject(key=key, last_modified=obj.get("LastModified"))
                )
    return found


def _list_filesystem_photo_objects(storage: Storage) -> list[StoredObject]:
    location = Path(getattr(storage, "location", "") or ".")
    found: list[StoredObject] = []
    for prefix in PHOTO_PREFIXES:
        root = location / prefix.rstrip("/")
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(location).as_posix()
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=dt_timezone.utc)
            found.append(StoredObject(key=rel, last_modified=mtime))
    return found


def find_orphan_keys(
    stored: list[StoredObject],
    referenced: set[str],
    *,
    min_age: timedelta,
    now: datetime | None = None,
) -> tuple[list[str], int]:
    """Return (orphan keys old enough to delete, count skipped as too new)."""
    now = now or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, timezone.get_current_timezone())
    cutoff = now - min_age
    orphans: list[str] = []
    skipped_new = 0
    for obj in stored:
        if obj.key in referenced:
            continue
        modified = obj.last_modified
        if modified is not None:
            if timezone.is_naive(modified):
                modified = timezone.make_aware(
                    modified, timezone.get_current_timezone()
                )
            if modified > cutoff:
                skipped_new += 1
                continue
        orphans.append(obj.key)
    return orphans, skipped_new


def delete_storage_keys(
    keys: list[str],
    storage: Storage | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """Delete keys from storage. Uses S3 DeleteObjects in batches when possible."""
    if not keys:
        return 0
    if dry_run:
        return 0

    storage = storage or default_storage
    if _is_s3_storage(storage):
        return _delete_s3_keys(storage, keys)
    deleted = 0
    for key in keys:
        storage.delete(key)
        deleted += 1
    return deleted


def _delete_s3_keys(storage: Storage, keys: list[str]) -> int:
    client = storage.connection.meta.client
    bucket = storage.bucket_name
    deleted = 0
    for i in range(0, len(keys), DELETE_BATCH_SIZE):
        batch = keys[i : i + DELETE_BATCH_SIZE]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={
                "Objects": [{"Key": key} for key in batch],
                "Quiet": True,
            },
        )
        errors = response.get("Errors") or ()
        deleted += len(batch) - len(errors)
        if errors:
            details = ", ".join(
                f"{err.get('Key')}: {err.get('Code')}" for err in errors[:5]
            )
            raise RuntimeError(f"R2/S3 delete failed for some keys: {details}")
    return deleted


def purge_orphan_photos(
    *,
    min_age_hours: int = 168,
    dry_run: bool = False,
    force: bool = False,
    storage: Storage | None = None,
) -> PurgeResult:
    """
    Delete media keys under users/, labours/, and sitecash/ that no DB row references.

    When the DB has zero file refs but storage still has objects, refuse unless
    ``force`` is True (guards against a wrong database).
    """
    if min_age_hours < 0:
        raise ValueError("min_age_hours must be >= 0")

    storage = storage or default_storage
    referenced = get_referenced_photo_keys()
    stored = list_stored_photo_objects(storage)
    orphans, skipped_new = find_orphan_keys(
        stored,
        referenced,
        min_age=timedelta(hours=min_age_hours),
    )

    if not referenced and stored and not force:
        raise RuntimeError(
            "No media references in the database, but storage still has "
            f"{len(stored)} object(s) under {PREFIX_LABEL}. "
            "Refusing to purge (possible wrong DB). Pass --force to override."
        )

    deleted = delete_storage_keys(orphans, storage, dry_run=dry_run)
    return PurgeResult(
        referenced_count=len(referenced),
        stored_count=len(stored),
        orphan_count=len(orphans),
        deleted_count=deleted if not dry_run else 0,
        skipped_new_count=skipped_new,
        dry_run=dry_run,
        orphans=tuple(orphans),
    )
