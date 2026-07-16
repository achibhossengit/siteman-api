from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from django.utils import timezone

from core import status_codes
from .models import Labour, LabourPayment, LabourPaymentType


class LabourListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Labour
        fields = [
            "id",
            "name",
            "current_site",
            "default_attendance",
            "default_salary",
            "default_fooding",
            "is_active",
        ]


class LabourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Labour
        fields = [
            "id",
            "name",
            "current_site",
            "default_attendance",
            "default_salary",
            "default_fooding",
            "is_active",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def _company(self):
        return self.context["request"].user.company

    def validate_name(self, value):
        qs = Labour.objects.filter(company=self._company(), name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A labour with this name already exists.",
                code=status_codes.LABOUR_NAME_EXISTS,
            )
        return value

    def validate_current_site(self, site):
        if site is None:
            return site
        if site.company_id != self._company().id:
            raise serializers.ValidationError(
                "Site does not belong to your company.",
                code=status_codes.SITE_WRONG_COMPANY,
            )
        if site.is_closed:
            raise serializers.ValidationError(
                "Cannot assign labour to a closed site.",
                code=status_codes.SITE_CLOSED,
            )
        return site


class LabourPaymentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabourPayment
        fields = [
            "id",
            "date",
            "type",
            "category",
            "amount",
            "note",
            "site",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class LabourPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabourPayment
        fields = [
            "id",
            "labour",
            "site",
            "date",
            "type",
            "category",
            "amount",
            "note",
            "is_sealed",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "labour",
            "site",
            "is_sealed",
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
