from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models


class ActivityAction(models.TextChoices):
    ADDITION = "addition", "Addition"
    CHANGE = "change", "Change"
    DELETION = "deletion", "Deletion"


class ActivityLog(models.Model):
    """Append-only audit row (F14). Never update or delete.

    Create is usually covered by ``created_by`` on business models; this log
    is for change/deletion (and rare create on models without created_by).
    Seal / site-close side-effects are not logged here.
    """

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    # Named ``site`` (not ``site_id``) so ``site_id=<int>`` still works on create.
    # CASCADE: deleting a site drops its activity logs.
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="activity_logs",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    action_flag = models.CharField(max_length=16, choices=ActivityAction.choices)
    changes = models.JSONField(
        help_text='Per-field diff: {"field": {"before": ..., "after": ...}}',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["company", "site", "-created_at"]),
            models.Index(fields=["site", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["actor"]),
        ]

    def __str__(self):
        return f"{self.get_action_flag_display()} {self.content_type}#{self.object_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Activity logs are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Activity logs are immutable and cannot be deleted.")
