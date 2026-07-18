from rest_framework import serializers
from django.utils import timezone

from core import status_codes
from .models import Site, SiteCash


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
                code=status_codes.SITE_NAME_EXISTS,
            )
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.closed_at is not None:
            raise serializers.ValidationError(
                "Closed sites cannot be edited.", code=status_codes.SITE_CLOSED
            )
        return attrs


class SiteCashListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteCash
        fields = [
            "id",
            "date",
            "type",
            "category",
            "amount",
            "note",
            "billing",
            "created_at",
            "updated_at",
        ]


class SiteCashSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteCash
        fields = [
            "id",
            "site",
            "billing",
            "type",
            "category",
            "date",
            "amount",
            "note",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError(
                "Date cannot be in the future.",
                code=status_codes.RECORD_FUTURE_DATE,
            )
        return value

    def validate_billing(self, billing):
        if billing is None:
            return billing

        site_id = (
            self.instance.site_id
            if self.instance is not None
            else int(self.context["view"].kwargs["site_pk"])
        )
        if billing.site_id != site_id:
            raise serializers.ValidationError(
                "Billing category must belong to this site.",
                code=status_codes.INVALID,
            )
        return billing
