from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.models import TimeStampedMixin


def default_paid_until():
    return timezone.localdate() + timedelta(days=14)


class Company(TimeStampedMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    site_limit = models.IntegerField(
        default=2,
        help_text="Max sites; -1 means no limit.",
    )
    active_user_limit = models.IntegerField(
        default=4,
        help_text="Max active users; -1 means no limit.",
    )
    active_labour_limit = models.IntegerField(
        default=30,
        help_text="Max active labour; -1 means no limit.",
    )
    paid_until = models.DateField(
        null=True,
        blank=True,
        default=default_paid_until,
    )
    labour_transfer_allowed = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
