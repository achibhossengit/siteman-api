from rest_framework import serializers
from django.utils import timezone

from activity.serializers import PendingActivitySerializer
from core import status_codes
from .models import BillingCategory, PrivateSiteCash, Site, SiteCash


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
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "company",
            "is_closed",
            "closed_at",
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


class BillingCategoryListSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingCategory
        fields = [
            "id",
            "name",
            "display_order",
            "is_active",
            "is_done",
            "created_at",
            "updated_at",
        ]


class BillingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingCategory
        fields = [
            "id",
            "site",
            "name",
            "display_order",
            "is_active",
            "is_done",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "company",
            "created_at",
            "updated_at",
        ]


class SiteLedgerValidationMixin:
    """Date + billing validation shared by site-nested ledger serializers."""

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


class SiteCashListSerializer(serializers.ModelSerializer):
    pending_activities = serializers.SerializerMethodField()

    class Meta:
        model = SiteCash
        fields = [
            "id",
            "date",
            "type",
            "amount",
            "note",
            "billing",
            "created_at",
            "updated_at",
            "pending_activities",
        ]

    def get_pending_activities(self, obj):
        items = self.context.get("pending_activities_map", {}).get(obj.pk, [])
        return PendingActivitySerializer(items, many=True).data


class SiteCashSerializer(SiteLedgerValidationMixin, serializers.ModelSerializer):
    class Meta:
        model = SiteCash
        fields = [
            "id",
            "site",
            "billing",
            "type",
            "date",
            "amount",
            "note",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "company",
            "created_at",
            "updated_at",
        ]


class PrivateSiteCashListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrivateSiteCash
        fields = [
            "id",
            "date",
            "type",
            "amount",
            "note",
            "billing",
            "created_at",
            "updated_at",
        ]


class PrivateSiteCashSerializer(SiteLedgerValidationMixin, serializers.ModelSerializer):
    class Meta:
        model = PrivateSiteCash
        fields = [
            "id",
            "site",
            "billing",
            "type",
            "date",
            "amount",
            "note",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "company",
            "created_at",
            "updated_at",
        ]


class SiteDailyReportSerializer(serializers.Serializer):
    """GET ``/sites/<pk>/daily-reports`` response (``date`` or ``date__gte``/``date__lte``)."""

    site = serializers.IntegerField()
    present_count = serializers.DecimalField(max_digits=12, decimal_places=2)
    labour_payment = serializers.IntegerField()
    labour_return = serializers.IntegerField()
    deposit = serializers.IntegerField()
    withdrawal = serializers.IntegerField()
    site_cost = serializers.IntegerField()
    total_cost = serializers.IntegerField()
    remaining = serializers.IntegerField()
    previous_balance = serializers.IntegerField()
    balance = serializers.IntegerField()
    # Included only when the user has ``sites.view_privatesitecash``.
    total_salary = serializers.IntegerField(required=False)
    extra_earnings = serializers.IntegerField(required=False)
