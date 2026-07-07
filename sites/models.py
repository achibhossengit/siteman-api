from django.db import models
from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin


class Site(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name
