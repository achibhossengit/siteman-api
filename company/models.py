from django.db import models
from core.models import TimeStampedMixin


class Company(TimeStampedMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
