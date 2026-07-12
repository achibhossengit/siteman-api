from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.postgres.fields import ArrayField
from core.models import TimeStampedMixin


NON_NEGATIVE = MinValueValidator(0)

def default_present_choices():
    return [Decimal("0.5"), Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"), Decimal("3.0")]

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

    def __str__(self):
        return self.company.name

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