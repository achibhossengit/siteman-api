from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from activity.models import ActivityLog


class Command(BaseCommand):
    help = (
        "Delete activity logs older than ACTIVITY_LOG_RETENTION_DAYS "
        "(default 180)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override retention days from settings.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many rows would be deleted without deleting.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is None:
            days = getattr(settings, "ACTIVITY_LOG_RETENTION_DAYS", 180)
        if days < 1:
            self.stderr.write("Retention days must be >= 1.")
            return

        cutoff = timezone.now() - timedelta(days=days)
        qs = ActivityLog.objects.filter(created_at__lt=cutoff)
        count = qs.count()
        if options["dry_run"]:
            self.stdout.write(
                f"Would delete {count} activity log(s) older than {days} day(s) "
                f"(before {cutoff.isoformat()})."
            )
            return

        deleted, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} activity log(s) older than {days} day(s)."
            )
        )
