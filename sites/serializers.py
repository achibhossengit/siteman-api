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

    def validate_name(self, value):
        company = self.context["request"].user.company
        qs = Site.objects.filter(company=company, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A site with this name already exists.",
                code="site_name_exists",
            )
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.closed_at is not None:
            raise serializers.ValidationError(
                "Closed sites cannot be edited.", code="site_closed"
            )
        return attrs
