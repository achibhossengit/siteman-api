from django.db import models
from django.core.validators import MinValueValidator
from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin

LIMIT_FLOOR = MinValueValidator(-1)

class Site(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uq_site_company_name"
            )
        ]

    def __str__(self):
        return self.name
    

class SiteConfig(CompanyOwnedMixin):
    site = models.OneToOneField(
        Site,
        on_delete=models.CASCADE,
        related_name="config",
    )

    # Windows (in days) gating create/update/delete of daily financial records:
    # sitecost, sitecash, sitecashreturn, dailyattendance, extrawork,
    # labouradvancepay, labourfoodingpay, labourreturn.
    daily_record_create_window = models.IntegerField(default=1)
    daily_record_update_window = models.IntegerField(default=1)
    daily_record_delete_window = models.IntegerField(default=1)

    attendance_limit_per_day = models.IntegerField(
        default=1,
        validators=[LIMIT_FLOOR],
        help_text="-1 means no limit.",
    )
    extra_limit_per_day = models.IntegerField(
        default=1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )
    fooding_limit_per_day = models.IntegerField(
        default=1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )
    advance_limit_per_day = models.IntegerField(
        default=-1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )

    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Config for {self.site}"


class BillingCategory(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="billing_categories",
    )
    name = models.CharField(max_length=255, help_text="e.g. Basement, Floor-1.")
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_done = models.BooleanField(
        default=False, help_text="Mark as done => deactivates."
    )

    class Meta:
        verbose_name_plural = "billing categories"
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name"], name="uq_billingcategory_site_name"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.site})"
