from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import CompanyOwnedMixin, TimeStampedMixin


class Site(TimeStampedMixin, CompanyOwnedMixin):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    
    
    def is_authorized_user(self, user):
        return self.users.filter(user_id=user.id).exists()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uq_site_company_name"
            )
        ]

    def __str__(self):
        return self.name


class BillingCategory(TimeStampedMixin, CompanyOwnedMixin):
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


class SiteCashType(models.TextChoices):
    DEPOSIT = "deposit", "Deposit"
    WITHDRAWAL = "withdrawal", "Withdrawal"
    COST = "cost", "Cost"


class SiteCash(TimeStampedMixin, CompanyOwnedMixin):
    site = models.ForeignKey(
        Site,
        on_delete=models.RESTRICT,
        related_name="cash_entries",
    )
    billing = models.ForeignKey(
        BillingCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_entries",
        help_text="Optional billing category; nullable for all types.",
    )
    type = models.CharField(max_length=16, choices=SiteCashType.choices)
    date = models.DateField(default=timezone.localdate)
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.get_type_display()} {self.amount} @ {self.date}"


class PrivateSiteCashType(models.TextChoices):
    BILL = "bill", "Bill"
    COST = "cost", "Cost"


class PrivateSiteCash(TimeStampedMixin, CompanyOwnedMixin):
    site = models.ForeignKey(
        Site,
        on_delete=models.RESTRICT,
        related_name="private_cash_entries",
    )
    billing = models.ForeignKey(
        BillingCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="private_cash_entries",
        help_text="Optional billing category; null means site-general.",
    )
    type = models.CharField(max_length=16, choices=PrivateSiteCashType.choices)
    date = models.DateField(default=timezone.localdate)
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    note = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.get_type_display()} {self.amount} @ {self.date}"
