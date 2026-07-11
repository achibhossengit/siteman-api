from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.postgres.fields import ArrayField
from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin

NON_NEGATIVE = MinValueValidator(0)
LIMIT_FLOOR = MinValueValidator(-1)


def default_present_choices():
    return [Decimal("0.5"), Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"), Decimal("3.0")]

class Site(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

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

    attendance_per_labour_per_day_limit = models.IntegerField(
        default=1,
        validators=[LIMIT_FLOOR],
        help_text="-1 means no limit.",
    )
    extra_per_labour_per_day_limit = models.IntegerField(
        default=1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )
    fooding_per_labour_per_day_limit = models.IntegerField(
        default=1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )
    advance_per_labour_per_day_limit = models.IntegerField(
        default=-1, validators=[LIMIT_FLOOR], help_text="-1 means no limit."
    )

    attendance_present_choices = ArrayField(
        models.DecimalField(max_digits=3, decimal_places=1),
        default=default_present_choices,
        help_text="Allowed present values per attendance row.",
    )

    salary_min = models.IntegerField(validators=[NON_NEGATIVE], default=0)
    salary_max = models.IntegerField(validators=[NON_NEGATIVE], default=2000)
    fooding_min = models.IntegerField(validators=[NON_NEGATIVE], default=0)
    fooding_max = models.IntegerField(validators=[NON_NEGATIVE], default=1000)
    advance_min = models.IntegerField(validators=[NON_NEGATIVE], default=0)
    advance_max = models.IntegerField(validators=[NON_NEGATIVE], default=100000)

    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        # DB-level integrity checks: each range non-negative and min <= max
        constraints = [
            models.CheckConstraint(
                condition=models.Q(salary_min__gte=0)
                & models.Q(salary_max__gte=models.F("salary_min")),
                name="chk_siteconfig_salary_range",
            ),
            models.CheckConstraint(
                condition=models.Q(fooding_min__gte=0)
                & models.Q(fooding_max__gte=models.F("fooding_min")),
                name="chk_siteconfig_fooding_range",
            ),
            models.CheckConstraint(
                condition=models.Q(advance_min__gte=0)
                & models.Q(advance_max__gte=models.F("advance_min")),
                name="chk_siteconfig_advance_range",
            ),
        ]

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
