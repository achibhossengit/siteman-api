from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.validators import UniqueTogetherValidator

from core import status_codes
from .models import DailyRecord, Labour, LabourSession
from .services import affected_rows_match, is_latest_labour_session


class LabourRecordDateValidationMixin:
    """Shared date rules for daily labour records."""

    # Validate that the date is not in the future.
    def validate_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError(
                "Date cannot be in the future.",
                code=status_codes.RECORD_FUTURE_DATE,
            )
        return value

    # Validate that the date is after the labour's last session date.
    def validate(self, attrs):
        attrs = super().validate(attrs)
        labour = attrs.get("labour") or self.context.get("labour")
        if labour is None and self.instance is not None:
            labour = self.instance.labour

        record_date = attrs.get("date")
        if record_date is None:
            record_date = (
                self.instance.date
                if self.instance is not None
                else timezone.localdate()
            )

        if (
            labour is not None
            and labour.last_session_date is not None
            and record_date <= labour.last_session_date
        ):
            raise serializers.ValidationError(
                {
                    "date": ErrorDetail(
                        "Date must be after the labour's last session date.",
                        code=status_codes.RECORD_DATE_NOT_AFTER_LAST_SESSION,
                    )
                }
            )
        return attrs


class DailyRecordValueValidationMixin:
    """Require at least one meaningful day value.
    
    present: attendance
    extra_earn: extra earnings for the day.
    fooding_pay: fooding pay for the day.
    advance_pay: advance pay for the day.
    return_amount: return amount for the day.
    """

    _VALUE_FIELDS = (
        "present",
        "extra_earn",
        "fooding_pay",
        "advance_pay",
        "return_amount",
    )

    @staticmethod
    def _is_zero(value):
        if value is None:
            return True
        if isinstance(value, Decimal):
            return value == 0
        return value == 0

    def validate(self, attrs):
        attrs = super().validate(attrs)
        resolved = {}
        for field in self._VALUE_FIELDS:
            if field in attrs:
                resolved[field] = attrs[field]
            elif self.instance is not None:
                resolved[field] = getattr(self.instance, field)
            else:
                resolved[field] = None

        if all(self._is_zero(resolved[field]) for field in self._VALUE_FIELDS):
            raise serializers.ValidationError(
                "At least one of present, extra_earn, fooding_pay, "
                "advance_pay, or return_amount is required.",
                code=status_codes.DAILY_RECORD_VALUE_REQUIRED,
            )
        return attrs


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
            "last_session_date",
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
            "last_session_date",
            "is_active",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "company",
            "last_session_date",
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
        user = self.context["request"].user
        if site is None:
            if not user.is_companyadmin:
                raise serializers.ValidationError(
                    "Only company admin can leave labour unassigned.",
                    code=status_codes.LABOUR_UNASSIGNED,
                )
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
        if not user.is_companyadmin and not site.is_authorized_user(user):
            raise serializers.ValidationError(
                "You can only assign labour to a site you belong to.",
                code=status_codes.UNAUTHORIZED_SITE,
            )
        return site

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = self.context["request"].user
        # Create with omitted current_site would leave labour unassigned;
        # non-admins must explicitly pick a site they belong to.
        if (
            not user.is_companyadmin
            and self.instance is None
            and "current_site" not in attrs
        ):
            raise serializers.ValidationError(
                {
                    "current_site": serializers.ErrorDetail(
                        "Only company admin can leave labour unassigned.",
                        code=status_codes.LABOUR_UNASSIGNED,
                    )
                }
            )
        return attrs


class DailyRecordListSerializer(serializers.ModelSerializer):
    billing_name = serializers.CharField(
        source="billing.name", read_only=True, allow_null=True
    )

    class Meta:
        model = DailyRecord
        fields = [
            "id",
            "date",
            "present",
            "wage",
            "extra_earn",
            "fooding_pay",
            "advance_pay",
            "return_amount",
            "note",
            "billing",
            "billing_name",
            "site",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class DailyRecordSerializer(
    DailyRecordValueValidationMixin,
    LabourRecordDateValidationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = DailyRecord
        fields = [
            "id",
            "labour",
            "site",
            "billing",
            "date",
            "present",
            "wage",
            "extra_earn",
            "fooding_pay",
            "advance_pay",
            "return_amount",
            "note",
            "is_sealed",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "labour",
            "site",
            "is_sealed",
            "company",
            "created_at",
            "updated_at",
        ]
        # labour is read_only, so DRF will not auto-build UniqueTogetherValidator.
        validators = [
            UniqueTogetherValidator(
                queryset=DailyRecord.objects.all(),
                fields=["date", "labour"],
            )
        ]

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        # labour is read_only (from URL); inject so UniqueTogetherValidator can run.
        labour = self.context.get("labour")
        if labour is not None and "labour" not in attrs:
            attrs["labour"] = labour
        return attrs

    def validate_billing(self, billing):
        if billing is None:
            return billing

        labour = self.context["labour"]
        site_id = (
            self.instance.site_id
            if self.instance is not None
            else labour.current_site_id
        )
        if billing.company_id != labour.company_id or billing.site_id != site_id:
            raise serializers.ValidationError(
                "Billing category must belong to this labour's current site.",
                code=status_codes.INVALID,
            )

        if self.instance is None and not billing.is_active:
            raise serializers.ValidationError(
                "Billing category must be active.",
                code=status_codes.BILLING_CATEGORY_INACTIVE,
            )

        return billing

    def create(self, validated_data):
        if "wage" not in validated_data or validated_data.get("wage") is None:
            labour = validated_data.get("labour") or self.context.get("labour")
            if labour is not None:
                validated_data["wage"] = labour.default_salary
        return super().create(validated_data)


class SiteDailyRecordListSerializer(serializers.ModelSerializer):
    labour_name = serializers.CharField(source="labour.name", read_only=True)
    labour_current_site = serializers.IntegerField(
        source="labour.current_site_id", read_only=True, allow_null=True
    )
    billing_name = serializers.CharField(
        source="billing.name", read_only=True, allow_null=True
    )

    class Meta:
        model = DailyRecord
        fields = [
            "id",
            "labour_id",
            "labour_name",
            "labour_current_site",
            "date",
            "present",
            "wage",
            "extra_earn",
            "fooding_pay",
            "advance_pay",
            "return_amount",
            "note",
            "billing",
            "billing_name",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class SiteDailyRecordSerializer(
    DailyRecordValueValidationMixin,
    LabourRecordDateValidationMixin,
    serializers.ModelSerializer,
):
    """Bulk-create item for ``/sites/<site_pk>/daily-records``.

    ``labour`` comes from the payload; ``site`` from the URL.
    """

    class Meta:
        model = DailyRecord
        fields = [
            "id",
            "labour",
            "site",
            "billing",
            "date",
            "present",
            "wage",
            "extra_earn",
            "fooding_pay",
            "advance_pay",
            "return_amount",
            "note",
            "is_sealed",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "is_sealed",
            "company",
            "created_at",
            "updated_at",
        ]

    def validate_labour(self, labour):
        request = self.context["request"]
        site_id = int(self.context["view"].kwargs["site_pk"])

        if labour.company_id != request.user.company_id:
            raise serializers.ValidationError(
                "Labour not found.",
                code=status_codes.INVALID,
            )
        if not labour.is_active:
            raise serializers.ValidationError(
                "This labour is inactive; no changes can be made.",
                code=status_codes.LABOUR_INACTIVE,
            )
        if labour.current_site_id != site_id:
            raise serializers.ValidationError(
                "Labour is not assigned to this site.",
                code=status_codes.INVALID,
            )
        return labour

    def validate_billing(self, billing):
        if billing is None:
            return billing

        request = self.context["request"]
        site_id = int(self.context["view"].kwargs["site_pk"])
        if billing.company_id != request.user.company_id or billing.site_id != site_id:
            raise serializers.ValidationError(
                "Billing category must belong to this site.",
                code=status_codes.INVALID,
            )

        # This endpoint only creates records, so billing must be active.
        if not billing.is_active:
            raise serializers.ValidationError(
                "Billing category must be active.",
                code=status_codes.BILLING_CATEGORY_INACTIVE,
            )

        return billing

    def create(self, validated_data):
        if "wage" not in validated_data or validated_data.get("wage") is None:
            labour = validated_data.get("labour")
            if labour is not None:
                validated_data["wage"] = labour.default_salary
        return super().create(validated_data)


class LabourSessionListSerializer(serializers.Serializer):
    # make id optional because session list may contain running session
    # which does not have an id
    id = serializers.IntegerField(read_only=True, required=False)
    start_date = serializers.DateField(read_only=True)
    end_date = serializers.DateField(read_only=True)
    payable = serializers.IntegerField(read_only=True)
    cumulative_payable = serializers.IntegerField(read_only=True)


class LabourSessionSerializer(serializers.ModelSerializer):
    total_earnings = serializers.IntegerField(read_only=True)
    total_payment = serializers.IntegerField(read_only=True)
    payable = serializers.IntegerField(read_only=True)
    cumulative_payable = serializers.IntegerField(read_only=True)

    # Helps client decide deleteability before calling the API.
    is_modified = serializers.SerializerMethodField()
    is_latest = serializers.SerializerMethodField()

    class Meta:
        model = LabourSession
        fields = [
            "id",
            "start_date",
            "end_date",
            "present_days",
            "salary_earnings",
            "extra_earnings",
            "total_fooding_pay",
            "total_advance_pay",
            "total_payment",
            "total_return",
            "previous_payable",
            "total_earnings",
            "payable",
            "cumulative_payable",
            "is_modified",
            "is_latest",
            "created_at",
            "updated_at",
        ]

    def get_is_modified(self, obj) -> bool:
        return not affected_rows_match(obj)

    def get_is_latest(self, obj) -> bool:
        return is_latest_labour_session(obj)


class RunningLabourSessionSerializer(serializers.Serializer):
    """Live open-period preview (not a persisted LabourSession)."""

    start_date = serializers.DateField(allow_null=True)
    end_date = serializers.DateField(allow_null=True)
    present_days = serializers.DecimalField(max_digits=12, decimal_places=2)
    salary_earnings = serializers.IntegerField()
    extra_earnings = serializers.IntegerField()
    total_fooding_pay = serializers.IntegerField()
    total_advance_pay = serializers.IntegerField()
    total_payment = serializers.IntegerField()
    total_return = serializers.IntegerField()
    total_earnings = serializers.IntegerField()
    payable = serializers.IntegerField()
    previous_payable = serializers.IntegerField()
    cumulative_payable = serializers.IntegerField()
