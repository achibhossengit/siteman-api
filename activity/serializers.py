from rest_framework import serializers

from .models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    content_type = serializers.CharField(source="content_type.model", read_only=True)
    app_label = serializers.CharField(source="content_type.app_label", read_only=True)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "company",
            "site_id",
            "actor",
            "app_label",
            "content_type",
            "object_id",
            "action_flag",
            "changes",
            "created_at",
        ]
        read_only_fields = fields
