from django.core.files.storage import default_storage
from rest_framework import serializers

from .models import ActivityEntityType, ActivityLog


class PendingActivitySerializer(serializers.Serializer):
    """Slim unreviewed log attached to a business-entity list row."""

    id = serializers.IntegerField()
    action = serializers.CharField()


def public_file_url(stored):
    """Turn a stored media key into the same public URL SiteCash.file returns."""
    if not stored:
        return None
    if isinstance(stored, str) and stored.startswith(("http://", "https://", "/")):
        return stored
    return default_storage.url(stored)


def expand_file_urls_in_changes(entity_type, changes):
    """Rewrite ``file`` paths to public URLs for API responses; leave DB as-is."""
    if entity_type != ActivityEntityType.SITE_CASH or not changes:
        return changes
    if "file" not in changes:
        return changes
    value = changes["file"]
    expanded = dict(changes)
    if isinstance(value, dict) and ("old" in value or "new" in value):
        expanded["file"] = {
            "old": public_file_url(value.get("old")),
            "new": public_file_url(value.get("new")),
        }
    else:
        expanded["file"] = public_file_url(value)
    return expanded


class ActivityLogSerializer(serializers.ModelSerializer):
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.name",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "site",
            "labour",
            "labour_name",
            "actor",
            "actor_name",
            "action",
            "entity_type",
            "entity_id",
            "business_date",
            "changes",
            "reviewed_at",
            "reviewed_by",
            "reviewed_by_name",
            "review_note",
            "created_at",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["changes"] = expand_file_urls_in_changes(
            instance.entity_type, instance.changes
        )
        return data


class ActivityLogReviewSerializer(serializers.Serializer):
    """POST ``/activities/review`` — one or many ids."""

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=500,
    )

    def validate_ids(self, value):
        # Preserve order while dropping duplicates.
        return list(dict.fromkeys(value))
