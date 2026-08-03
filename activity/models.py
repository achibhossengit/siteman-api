from django.conf import settings
from django.db import models

from core.models import CompanyOwnedMixin


class ActivityAction(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    DELETED = "deleted", "Deleted"


class ActivityEntityType(models.TextChoices):
    USER = "user", "User"
    SITE = "site", "Site"
    BILLING_CATEGORY = "billing_category", "Billing category"
    SITE_CASH = "site_cash", "Site cash"
    PRIVATE_SITE_CASH = "private_site_cash", "Private site cash"
    LABOUR = "labour", "Labour"
    LABOUR_PAYMENT = "labour_payment", "Labour payment"
    ATTENDANCE = "attendance", "Attendance"
    LABOUR_SESSION = "labour_session", "Labour session"


class ActivityLog(CompanyOwnedMixin):
    """Append-only audit row for business mutations (retention-purged later).

    Soft-references the target via ``entity_type`` + ``entity_id`` so deleting
    the business row does not remove history. ``created_at`` is the action
    time (when the user performed create/update/delete), not the business
    date on the record.
    """

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        help_text="Denormalized site scope when the entity is site-related.",
    )
    labour = models.ForeignKey(
        "labours.Labour",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        help_text="Denormalized labour when the entity is labour-related.",
    )
    labour_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Snapshot of labour name at action time (for client messages).",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    actor_name = models.CharField(
        max_length=255,
        help_text="Snapshot of actor display name at action time.",
    )
    action = models.CharField(max_length=16, choices=ActivityAction.choices)
    entity_type = models.CharField(
        max_length=32,
        choices=ActivityEntityType.choices,
    )
    entity_id = models.BigIntegerField(
        help_text="PK of the business row at action time (may no longer exist).",
    )
    business_date = models.DateField(
        null=True,
        blank=True,
        help_text="Record's business date when applicable (e.g. attendance.date).",
    )
    changes = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Create: key-field snapshot. Update: {field: {old, new}}. "
            "Delete: last snapshot."
        ),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_activity_logs",
    )
    review_note = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Optional note when an auditor marks this log reviewed.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the action was performed (audit clock).",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["company", "-created_at"],
                name="actlog_company_created_idx",
            ),
            models.Index(
                fields=["site", "-created_at"],
                name="actlog_site_created_idx",
            ),
            models.Index(
                fields=["labour", "-created_at"],
                name="actlog_labour_created_idx",
            ),
            models.Index(
                fields=["entity_type", "entity_id"],
                name="actlog_entity_idx",
            ),
            models.Index(
                fields=["company", "reviewed_at"],
                name="actlog_company_reviewed_idx",
            ),
            models.Index(
                fields=["actor", "-created_at"],
                name="actlog_actor_created_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.action} {self.entity_type}:{self.entity_id} "
            f"by {self.actor_name} @ {self.created_at}"
        )
