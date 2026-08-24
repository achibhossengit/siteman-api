import uuid
from decimal import Decimal
from pathlib import Path

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import CompanyOwnedMixin, TimeStampedMixin


def labour_photo_upload_to(instance, filename):
    ext = Path(filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    company_id = instance.company_id or "none"
    return f"labours/{company_id}/{uuid.uuid4().hex}{ext}"


class Labour(TimeStampedMixin, CompanyOwnedMixin):
    current_site = models.ForeignKey(
        "sites.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labours",
        help_text="One site at a time; reassign = move. NULL = unassigned.",
    )
    name = models.CharField(max_length=255)
    photo = models.ImageField(
        upload_to=labour_photo_upload_to,
        null=True,
        blank=True,
    )
    default_attendance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("1"),
    )
    default_salary = models.IntegerField(validators=[MinValueValidator(0)], default=0)
    default_fooding = models.IntegerField(validators=[MinValueValidator(0)], default=0)
    last_session_date = models.DateField(
        null=True,
        blank=True,
        help_text="Cached latest labour session end_date; new records must be after this.",
    )
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


class DailyRecord(TimeStampedMixin, CompanyOwnedMixin):
    """One row per labour per date: attendance + cash movement."""

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
        related_name="daily_records",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.RESTRICT,
        related_name="daily_records",
    )
    billing = models.ForeignKey(
        "sites.BillingCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_records",
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
    wage = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Snapshot from labour.default_salary.",
    )
    extra_earn = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Extra work amount for the day.",
    )
    fooding_pay = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Fooding cash paid this day.",
    )
    advance_pay = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Advance cash paid this day.",
    )
    return_amount = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Cash returned by labour this day.",
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
                name="uq_daily_record_date_labour",
            ),
        ]

    def __str__(self):
        return f"{self.labour} @ {self.date} (present={self.present})"


class LabourSession(TimeStampedMixin, CompanyOwnedMixin):
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
    present_days = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    salary_earnings = models.BigIntegerField(validators=[MinValueValidator(0)])
    extra_earnings = models.BigIntegerField(validators=[MinValueValidator(0)])
    total_fooding_pay = models.BigIntegerField(validators=[MinValueValidator(0)])
    total_advance_pay = models.BigIntegerField(validators=[MinValueValidator(0)])
    total_return = models.BigIntegerField(validators=[MinValueValidator(0)])
    affected_rows = models.PositiveIntegerField(
        help_text="DailyRecord rows sealed into this session.",
    )
    # it may be negative.
    previous_payable = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["labour", "start_date"],
                name="uq_labour_session_labour_start_date",
            ),
            models.UniqueConstraint(
                fields=["labour", "end_date"],
                name="uq_labour_session_labour_end_date",
            ),
        ]

    @property
    def total_earnings(self):
        return self.salary_earnings + self.extra_earnings

    @property
    def total_payment(self):
        return self.total_fooding_pay + self.total_advance_pay

    @property
    def payable(self):
        return self.total_earnings + self.total_return - self.total_payment

    @property
    def cumulative_payable(self):
        return self.previous_payable + self.payable

    def __str__(self):
        return f"{self.labour} ({self.start_date} - {self.end_date})"
