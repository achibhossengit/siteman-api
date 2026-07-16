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


class CompanyConfig(models.Model):
    company = models.OneToOneField(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="config",
    )
    labour_transfer_allowed = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company.name
