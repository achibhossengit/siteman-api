from rest_framework import serializers

from .models import ActivityLog


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


class ActivityLogReviewSerializer(serializers.Serializer):
    review_note = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
    )


class ActivityLogBulkReviewSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=500,
    )

    def validate_ids(self, value):
        # Preserve order while dropping duplicates.
        return list(dict.fromkeys(value))
