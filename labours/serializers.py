from rest_framework import serializers

from core import status_codes
from .models import Labour, LabourSession
from .services import affected_rows_match, is_latest_labour_session


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
            "created_date",
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
