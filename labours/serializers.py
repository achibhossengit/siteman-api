from decimal import Decimal

from rest_framework import serializers

from core import status_codes
from .models import Labour


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

    def validate(self, attrs):
        attrs = super().validate(attrs)

        config = getattr(self._company(), "config", None)
        if config is None:
            return attrs

        def resolve(field):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, None)

        salary = resolve("default_salary")
        fooding = resolve("default_fooding")
        attendance = resolve("default_attendance")

        errors = {}

        if salary is not None and not (
            config.salary_min <= salary <= config.salary_max
        ):
            errors["default_salary"] = (
                f"Must be between {config.salary_min} and {config.salary_max}."
            )

        if fooding is not None and not (
            config.fooding_min <= fooding <= config.fooding_max
        ):
            errors["default_fooding"] = (
                f"Must be between {config.fooding_min} and {config.fooding_max}."
            )

        if attendance is not None:
            allowed = [Decimal(str(choice)) for choice in config.attendance_present_choices]
            if Decimal(str(attendance)) not in allowed:
                allowed_display = ", ".join(str(choice) for choice in allowed)
                errors["default_attendance"] = (
                    f"Must be one of: {allowed_display}."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
