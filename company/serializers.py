from django.contrib.auth.models import Group
from django.db.models import F
from rest_framework import serializers

from sites.serializers import SiteListSerializer
from sites.models import Site
from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    """Tenant company. API writes are limited to name and labour transfer."""

    sites = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

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
            "sites",
            "groups",
        )
        read_only_fields = (
            "id",
            "site_limit",
            "active_user_limit",
            "active_labour_limit",
            "paid_until",
            "sites",
            "groups",
        )

    def get_sites(self, obj):
        qs = Site.objects.filter(company_id=obj.pk).order_by("name", "id")
        return SiteListSerializer(qs, many=True).data

    def get_groups(self, obj):
        return list(
            Group.objects.values("id", "name", type=F("profile__type"),)
        )


class CompanyDeleteSerializer(serializers.Serializer):
    """Confirm the acting user's password before deleting the company."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value
