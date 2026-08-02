from django import forms
from django.contrib import admin
from django.db import transaction
from core.exceptions import SubscriptionError

from accounts.models import User, UserSite
from core.services import SubscriptionService
from .models import BillingCategory, Site, SiteCash, PrivateSiteCash


class SiteAdminForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()

        company = cleaned.get("company") or self.instance.company
        if company is None:
            return cleaned

        name = cleaned.get("name")
        if name:
            qs = Site.objects.filter(company=company, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("name", "A site with this name already exists.")

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


class BillingCategoryInline(admin.TabularInline):
    model = BillingCategory
    extra = 0
    fields = ("name", "display_order", "is_active", "is_done")
    ordering = ("display_order",)


class SiteUserInline(admin.TabularInline):
    """Users assigned to this site (same company only).

    Existing rows are read-only; only add and delete are allowed.
    """

    model = UserSite
    fk_name = "site"
    extra = 0
    fields = ("user",)
    verbose_name = "assigned user"
    verbose_name_plural = "assigned users"

    def has_change_permission(self, request, obj=None):
        return False

    def get_formset(self, request, obj=None, **kwargs):
        self.parent_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            parent = getattr(self, "parent_obj", None)
            if parent is not None and parent.company_id:
                kwargs["queryset"] = User.objects.filter(
                    company_id=parent.company_id
                ).order_by("name")
            else:
                kwargs["queryset"] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    form = SiteAdminForm
    inlines = [BillingCategoryInline, SiteUserInline]
    list_display = (
        "id",
        "name",
        "company",
        "is_active",
        "is_closed",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = ("is_active", "company")
    search_fields = ("name",)
    autocomplete_fields = ("company",)
    readonly_fields = ("closed_at", "created_at", "updated_at")

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if not obj.company_id:
                obj.company = form.instance.company
            obj.save()
        formset.save_m2m()


admin.site.register(BillingCategory)
admin.site.register(SiteCash)
admin.site.register(PrivateSiteCash)
