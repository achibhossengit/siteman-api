from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from django.utils import timezone

from core import status_codes
from .models import Attendance, Labour, LabourPayment, LabourSession


class LabourRecordDateValidationMixin:
    """Shared date rules for labour payment and attendance records."""

    def validate_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError(
                "Date cannot be in the future.",
                code=status_codes.RECORD_FUTURE_DATE,
            )
        return value

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
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "company",
            "last_session_date",
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


class LabourPaymentSerializer(
    LabourRecordDateValidationMixin, serializers.ModelSerializer
):
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


class SiteLabourPaymentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabourPayment
        fields = [
            "id",
            "labour",
            "date",
            "type",
            "category",
            "amount",
            "note",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class SiteLabourPaymentSerializer(
    LabourRecordDateValidationMixin, serializers.ModelSerializer
):
    """Bulk-create item for ``/sites/<site_pk>/labour-payments``.

    Unlike LabourPaymentSerializer, ``labour`` comes from the payload
    and ``site`` from the URL.
    """

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
            "site",
            "is_sealed",
            "company",
            "created_by",
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


class SiteLabourAttendanceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = [
            "id",
            "labour",
            "date",
            "present",
            "salary",
            "extra",
            "note",
            "billing",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class SiteLabourAttendanceSerializer(
    LabourRecordDateValidationMixin, serializers.ModelSerializer
):
    """Bulk-create item for ``/sites/<site_pk>/labour-attendances``.

    Unlike AttendanceSerializer, ``labour`` comes from the payload
    and ``site`` from the URL.
    """

    class Meta:
        model = Attendance
        fields = [
            "id",
            "labour",
            "site",
            "billing",
            "date",
            "present",
            "salary",
            "extra",
            "note",
            "is_sealed",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "site",
            "is_sealed",
            "company",
            "created_by",
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


class AttendanceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = [
            "id",
            "date",
            "present",
            "salary",
            "extra",
            "note",
            "billing",
            "site",
            "is_sealed",
            "created_at",
            "updated_at",
        ]


class AttendanceSerializer(
    LabourRecordDateValidationMixin, serializers.ModelSerializer
):
    class Meta:
        model = Attendance
        fields = [
            "id",
            "labour",
            "site",
            "billing",
            "date",
            "present",
            "salary",
            "extra",
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

    def validate_billing(self, billing):
        if billing is None:
            return billing

        labour = self.context["labour"]
        site_id = self.instance.site_id if self.instance is not None else labour.current_site_id
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


class LabourSessionSerializer(serializers.ModelSerializer):
    total_earnings = serializers.IntegerField(read_only=True)
    payable = serializers.IntegerField(read_only=True)

    class Meta:
        model = LabourSession
        fields = [
            "id",
            "labour",
            "start_date",
            "end_date",
            "created_date",
            "present_days",
            "salary_earnings",
            "extra_earnings",
            "total_payment",
            "total_return",
            "total_earnings",
            "payable",
            "company",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
