from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from core.models import CreatedByMixin, TimeStampedMixin


# class Plan(TimeStampedMixin, CreatedByMixin):
#     name = models.CharField(max_length=100)
#     open_site_limit = models.IntegerField(help_text="-1 means no limit.")
#     active_user_limit = models.IntegerField(default=-1)
#     active_labour_limit = models.IntegerField(default=-1)

#     def __str__(self):
#         return self.name


# class PlanVariant(TimeStampedMixin, CreatedByMixin):
#     plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="variants")
#     duration = models.PositiveIntegerField(help_text="Term length in days.")
#     price = models.IntegerField()
#     discount_price = models.IntegerField(help_text="Final price after discount.")
#     is_active = models.BooleanField(default=True)

#     class Meta:
#         constraints = [
#             models.UniqueConstraint(
#                 fields=["plan", "duration"], name="uq_planvariant_plan_duration"
#             )
#         ]

#     def __str__(self):
#         return f"{self.plan.name} ({self.duration} days)"


# class CustomPlan(TimeStampedMixin, CreatedByMixin):
#     company = models.ForeignKey(
#         "company.Company",
#         on_delete=models.CASCADE,
#         related_name="custom_plans",
#         help_text="A negotiated deal created for one specific company.",
#     )
#     open_site_limit = models.IntegerField(help_text="-1 means no limit.")
#     active_user_limit = models.IntegerField(default=-1)
#     active_labour_limit = models.IntegerField(default=-1)
#     duration = models.PositiveIntegerField(help_text="Term length in days.")
#     price = models.IntegerField(help_text="Negotiated fixed price for the full term.")
#     is_active = models.BooleanField(
#         default=True, help_text="Retire an old deal without deleting it."
#     )

#     def __str__(self):
#         return f"{self.company} custom ({self.duration} days)"


class Subscription(TimeStampedMixin):
    company = models.OneToOneField(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="subscription",
        help_text="One row per company — the current entitlement cache, updated in place.",
    )
    # variant = models.ForeignKey(
    #     PlanVariant,
    #     on_delete=models.PROTECT,
    #     null=True,
    #     blank=True,
    #     related_name="subscriptions",
    # )
    # custom_plan = models.ForeignKey(
    #     CustomPlan,
    #     on_delete=models.PROTECT,
    #     null=True,
    #     blank=True,
    #     related_name="subscriptions",
    #     help_text="The negotiated deal this company is on; suggests the next renewal billing.",
    # )
    open_site_limit = models.IntegerField(default=0, help_text="Snapshot; -1 means no limit.")
    active_user_limit = models.IntegerField(default=0)
    active_labour_limit = models.IntegerField(default=0)
    paid_until = models.DateField(
        null=True,
        blank=True,
        help_text="From the succeeding payment; null = never activated. Free is an ordinary plan tier.",
    )

    def __str__(self):
        return f"{self.company} until {self.paid_until}"


class Payment(TimeStampedMixin, CreatedByMixin):
    class Method(models.TextChoices):
        GATEWAY = "gateway", "Gateway"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        help_text="Nulled on company delete — the financial record survives.",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    method = models.CharField(max_length=10, choices=Method.choices)
    # variant = models.ForeignKey(
    #     PlanVariant,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     related_name="payments",
    # )
    # custom_plan = models.ForeignKey(
    #     CustomPlan,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     related_name="payments",
    # )
    amount = models.IntegerField(
        help_text="Locked from the variant discount price or custom plan price at payment time."
    )
    period_start = models.DateField(
        null=True, blank=True, help_text="Coverage start; set when the payment succeeds."
    )
    period_end = models.DateField(
        null=True,
        blank=True,
        help_text="period_start + the variant/custom plan duration.",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    transaction_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Gateway txn id; null for manual.",
    )
    # gateway_payload = models.JSONField(null=True, blank=True)
    
    def __str__(self):
        return f"Payment #{self.pk} — {self.company} ({self.status})"
