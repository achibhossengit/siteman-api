from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import CompanyOwnedMixin, CreatedByMixin, TimeStampedMixin


class Labour(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    current_site = models.ForeignKey(
        "sites.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labours",
        help_text="One site at a time; reassign = move.",
    )
    name = models.CharField(max_length=255)
    default_attendance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("1"),
    )
    default_salary = models.IntegerField(validators=[MinValueValidator(0)], default=0)
    default_fooding = models.IntegerField(validators=[MinValueValidator(0)], default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="uq_labour_company_name",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class LabourPaymentType(models.TextChoices):
    ADVANCE = "advance", "Advance"
    FOODING = "fooding", "Fooding"


class LabourPayment(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    labour = models.ForeignKey(
        Labour,
        on_delete=models.RESTRICT,
        related_name="payments",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.RESTRICT,
        related_name="labour_payments",
    )
    date = models.DateField(default=timezone.localdate)
    type = models.CharField(max_length=16, choices=LabourPaymentType.choices, default=LabourPaymentType.FOODING)
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)
    site_total = models.BigIntegerField(
        help_text="Per-site running total across all payment types.",
    )
    is_sealed = models.BooleanField(
        default=False,
        help_text="True = immutable",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["labour", "date"],
                name="uq_labour_payment_labour_date",
            ),
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_type_display()} {self.amount} ({self.labour})"


class LabourReturn(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    labour = models.ForeignKey(
        Labour,
        on_delete=models.RESTRICT,
        related_name="returns",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.RESTRICT,
        related_name="labour_returns",
    )
    date = models.DateField(default=timezone.localdate)
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)
    site_total = models.BigIntegerField()
    is_sealed = models.BooleanField(
        default=False,
        help_text="True = immutable",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["labour", "date"],
                name="uq_labour_return_labour_date",
            ),
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"Return {self.amount} ({self.labour})"
