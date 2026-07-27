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
        help_text="One site at a time; reassign = move. NULL = unassigned.",
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
    last_session_date = models.DateField(null=True, blank=True)
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
    )
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)
    is_sealed = models.BooleanField(
        default=False,
        help_text="True = immutable",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "labour", "type"],
                name="uq_labour_payment_date_labour_type",
            ),
        ]

    def __str__(self):
        return f"Note: {self.note} Amount: {self.amount} Type: {self.get_type_display()}"


class Attendance(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    PRESENT_CHOICES = [
        (Decimal("0"), "0"),
        (Decimal("0.5"), "0.5"),
        (Decimal("1"), "1"),
        (Decimal("1.5"), "1.5"),
        (Decimal("2"), "2"),
        (Decimal("2.5"), "2.5"),
        (Decimal("3"), "3"),
    ]
    
    labour = models.ForeignKey(
        Labour,
        on_delete=models.RESTRICT,
        related_name="attendances",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.RESTRICT,
        related_name="attendances",
    )
    billing = models.ForeignKey(
        "sites.BillingCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendances",
        help_text="Optional billing category; site may run without categories.",
    )
    date = models.DateField(default=timezone.localdate)
    present = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        choices=PRESENT_CHOICES,
    )
    salary = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Snapshot from labour.default_salary.",
    )
    extra = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Extra work amount for the day.",
    )
    note = models.CharField(max_length=255, null=True, blank=True)
    is_sealed = models.BooleanField(
        default=False,
        help_text="True = immutable; set by work-session seal.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "labour"],
                name="uq_attendance_date_labour",
            ),
        ]

    def __str__(self):
        return f"{self.labour} @ {self.date} (present={self.present})"


class LabourSession(TimeStampedMixin, CompanyOwnedMixin, CreatedByMixin):
    labour = models.ForeignKey(
        Labour,
        on_delete=models.RESTRICT,
        related_name="sessions",
    )
    start_date = models.DateField(
        help_text="First record date after the previous session ended.",
    )
    end_date = models.DateField(
        help_text="Last sealed record date.",
    )
    created_date = models.DateField(default=timezone.localdate)
    present_days = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    salary_earnings = models.BigIntegerField(validators=[MinValueValidator(0)])
    extra_earnings = models.BigIntegerField(validators=[MinValueValidator(0)])
    total_payment = models.BigIntegerField(validators=[MinValueValidator(0)])
    total_return = models.BigIntegerField(validators=[MinValueValidator(0)])
    affected_attendance_rows = models.PositiveIntegerField(
        help_text="Attendance rows sealed into this session.",
    )
    affected_payment_rows = models.PositiveIntegerField(
        help_text="Payment rows sealed into this session.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_date", "labour"],
                name="uq_labour_session_created_date_labour",
            ),
        ]

    @property
    def total_earnings(self):
        return self.salary_earnings + self.extra_earnings

    @property
    def payable(self):
        return self.total_earnings + self.total_return - self.total_payment

    def __str__(self):
        return f"{self.labour} ({self.start_date} - {self.end_date})"
