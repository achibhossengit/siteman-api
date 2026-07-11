from django import forms
from django.contrib import admin
from django.db import transaction
from core.exceptions import SubscriptionError

from core.services import SubscriptionService
from .models import BillingCategory, Site, SiteConfig


class SiteAdminForm(forms.ModelForm):
    class Meta:
        model = Site
        exclude = ("created_by",)
        
    def clean(self):
        cleaned = super().clean()

        company = cleaned.get("company") or self.instance.company
        if company is None:
            return cleaned

        is_closed = cleaned.get("is_closed", self.instance.is_closed)

        is_add = self.instance.pk is None

        try:
            if (is_add and not is_closed) or (
                self.instance.pk and self.instance.is_closed and not is_closed
            ):
                SubscriptionService.validate_open_site_limit(company)

        except SubscriptionError as e:
            raise forms.ValidationError(e)
        return cleaned

class SiteConfigInline(admin.StackedInline):
    model = SiteConfig
    can_delete = False
    exclude = ("company",)
    readonly_fields = ("updated_at",)


class BillingCategoryInline(admin.TabularInline):
    model = BillingCategory
    extra = 0
    fields = ("name", "display_order", "is_active", "is_done")
    ordering = ("display_order",)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    form = SiteAdminForm
    list_display = (
        "id",
        "name",
        "company",
        "is_active",
        "is_closed",
        "created_by",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = ("is_active", "company")
    search_fields = ("name",)
    autocomplete_fields = ("company",)
    exclude = ("created_by",)
    readonly_fields = ("closed_at", "created_at", "updated_at")

    def get_inlines(self, request, obj=None):
        # Inlines only on the change page: the config row is created by the
        # post_save signal, so it doesn't exist until the site is saved.
        return (SiteConfigInline, BillingCategoryInline) if obj else ()

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if not obj.company_id:
                obj.company = form.instance.company
            if hasattr(obj, "created_by_id") and not obj.created_by_id:
                obj.created_by = request.user
            obj.save()
        formset.save_m2m()
