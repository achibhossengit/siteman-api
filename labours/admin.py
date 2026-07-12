from decimal import Decimal

from django import forms
from django.contrib import admin
from django.db import transaction

from core.exceptions import SubscriptionError
from core.services import SubscriptionService
from .models import Labour


class LabourAdminForm(forms.ModelForm):
    class Meta:
        model = Labour
        exclude = ("created_by",)

    def clean(self):
        cleaned = super().clean()

        company = cleaned.get("company") or self.instance.company
        if company is None:
            return cleaned

        self._validate_current_site(cleaned, company)
        self._validate_defaults(cleaned, company)
        self._validate_labour_limit(cleaned, company)

        return cleaned

    def _validate_current_site(self, cleaned, company):
        site = cleaned.get("current_site")
        if site is None:
            return
        if site.company_id != company.id:
            self.add_error("current_site", "Site does not belong to this company.")
        elif site.is_closed:
            self.add_error("current_site", "Cannot assign labour to a closed site.")

    def _validate_defaults(self, cleaned, company):
        config = getattr(company, "config", None)
        if config is None:
            return

        salary = cleaned.get("default_salary")
        fooding = cleaned.get("default_fooding")
        attendance = cleaned.get("default_attendance")

        if salary is not None and not (config.salary_min <= salary <= config.salary_max):
            self.add_error(
                "default_salary",
                f"Must be between {config.salary_min} and {config.salary_max}.",
            )

        if fooding is not None and not (
            config.fooding_min <= fooding <= config.fooding_max
        ):
            self.add_error(
                "default_fooding",
                f"Must be between {config.fooding_min} and {config.fooding_max}.",
            )

        if attendance is not None:
            allowed = [Decimal(str(c)) for c in config.attendance_present_choices]
            if Decimal(str(attendance)) not in allowed:
                allowed_display = ", ".join(str(c) for c in allowed)
                self.add_error(
                    "default_attendance",
                    f"Must be one of: {allowed_display}.",
                )

    def _validate_labour_limit(self, cleaned, company):
        is_active = cleaned.get("is_active", self.instance.is_active)
        is_add = self.instance.pk is None
        # Only a newly active labour consumes a slot: on add, or when reactivating.
        becomes_active = (is_add and is_active) or (
            self.instance.pk and not self.instance.is_active and is_active
        )
        if not becomes_active:
            return
        try:
            with transaction.atomic():
                SubscriptionService.validate_active_labour_limit(company)
        except SubscriptionError as e:
            raise forms.ValidationError(e)


@admin.register(Labour)
class LabourAdmin(admin.ModelAdmin):
    form = LabourAdminForm
    list_display = (
        "id",
        "name",
        "company",
        "current_site",
        "default_attendance",
        "default_salary",
        "default_fooding",
        "is_active",
    )
    list_display_links = ("name",)
    list_filter = ("is_active", "company", "current_site")
    search_fields = ("name",)
    autocomplete_fields = ("company", "current_site")
    exclude = ("created_by",)
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
