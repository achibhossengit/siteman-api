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
    PAYMENT = "payment", "Payment"
    RETURN = "return", "Return"


class LabourPaymentCategory(models.TextChoices):
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
    type = models.CharField(
        max_length=16, 
        choices=LabourPaymentType.choices,
        default=LabourPaymentType.PAYMENT,
        help_text="Payment or Return",
    )
    category = models.CharField(
        max_length=16,
        choices=LabourPaymentCategory.choices,
        null=True,
        blank=True,
        help_text="Must be empty for returns.",
    )
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)
    is_sealed = models.BooleanField(
        default=False,
        help_text="True = immutable",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        type=LabourPaymentType.RETURN,
                        category__isnull=True,
                    )
                ),
                name="chk_labour_payment_category_by_type",
            ),
            models.UniqueConstraint(
                fields=["date", "labour", "type"],
                name="uq_labour_payment_date_labour_type",
            ),
        ]

    def __str__(self):
        return f"Note: {self.note} Amount: {self.amount} Type: {self.get_type_display()}"
