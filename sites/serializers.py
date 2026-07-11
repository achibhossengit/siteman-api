from rest_framework import serializers

from .models import Site


class SiteListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "is_active",
            "is_closed",
        ]

class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "is_active",
            "is_closed",
            "closed_at",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "company",
            "is_closed",
            "closed_at",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if self.instance is not None and self.instance.closed_at is not None:
            raise serializers.ValidationError(
                "Closed sites cannot be edited.", code="site_closed"
            )
        return attrs
