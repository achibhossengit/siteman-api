from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models

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