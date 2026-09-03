from rest_framework import serializers

from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    """Tenant company. API writes are limited to name and labour transfer."""

    class Meta:
        model = Company
        fields = (
            "id",
            "name",
            "site_limit",
            "active_user_limit",
            "active_labour_limit",
            "paid_until",
            "labour_transfer_allowed",
        )
        read_only_fields = (
            "id",
            "site_limit",
            "active_user_limit",
            "active_labour_limit",
            "paid_until",
        )


class CompanyDeleteSerializer(serializers.Serializer):
    """Confirm the acting user's password before deleting the company."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value
