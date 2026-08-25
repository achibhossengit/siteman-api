from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from core.orphan_photos import (
    delete_storage_keys,
    find_orphan_keys,
    get_referenced_photo_keys,
    list_stored_photo_objects,
)


class Command(BaseCommand):
    help = (
        "Delete orphaned user/labour photos under users/ and labours/ that are "
        "not referenced in the database. Intended for cron; default keeps "
        "recent objects for a support window."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List orphans that would be deleted without deleting.",
        )
        parser.add_argument(
            "--min-age-hours",
            type=int,
            default=None,
            help=(
                "Only delete objects older than this many hours "
                "(default: PHOTO_ORPHAN_MIN_AGE_HOURS)."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Allow purge when the DB has no photo references but storage "
                "still has users/ or labours/ objects."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Delete at most this many orphans (after age filter).",
        )

    def handle(self, *args, **options):
        min_age_hours = options["min_age_hours"]
        if min_age_hours is None:
            min_age_hours = getattr(settings, "PHOTO_ORPHAN_MIN_AGE_HOURS", 168)
        if min_age_hours < 0:
            raise CommandError("--min-age-hours must be >= 0")
        if options["limit"] is not None and options["limit"] < 0:
            raise CommandError("--limit must be >= 0")

        storage = default_storage
        referenced = get_referenced_photo_keys()
        stored = list_stored_photo_objects(storage)

        if not referenced and stored and not options["force"]:
            raise CommandError(
                "No photo references in the database, but storage still has "
                f"{len(stored)} object(s) under users/ and labours/. "
                "Refusing to purge (possible wrong DB). Pass --force to override."
            )

        orphans, skipped_new = find_orphan_keys(
            stored,
            referenced,
            min_age=timedelta(hours=min_age_hours),
        )
        if options["limit"] is not None:
            orphans = orphans[: options["limit"]]

        self.stdout.write(
            f"Referenced: {len(referenced)}; "
            f"stored under users|labours: {len(stored)}; "
            f"orphans (age>={min_age_hours}h): {len(orphans)}; "
            f"skipped: {skipped_new}."
        )

        if options["dry_run"]:
            for key in orphans:
                self.stdout.write(f"would delete: {key}")
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would delete {len(orphans)} orphan photo(s)."
                )
            )
            return

        try:
            deleted = delete_storage_keys(orphans, storage, dry_run=False)
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted} orphan photo(s).")
        )
