from django import forms
from django.contrib import admin
from django.db import transaction

from core.exceptions import SubscriptionError
from core.services import SubscriptionService
from .models import Labour, Attendance, LabourPayment, LabourSession


class LabourAdminForm(forms.ModelForm):
    class Meta:
        model = Labour
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()

        company = cleaned.get("company") or self.instance.company
        if company is None:
            return cleaned

        self._validate_current_site(cleaned, company)
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
        "last_session_date",
        "is_active",
    )
    list_display_links = ("name",)
    list_filter = ("is_active", "company", "current_site")
    search_fields = ("name",)
    autocomplete_fields = ("company", "current_site")
    readonly_fields = ("last_session_date", "created_at", "updated_at")


admin.site.register(Attendance)
admin.site.register(LabourPayment)
admin.site.register(LabourSession)
