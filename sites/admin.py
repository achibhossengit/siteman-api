from django.contrib import admin

from .models import BillingCategory, Site, SiteConfig


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
    list_display = (
        "id",
        "name",
        "company",
        "is_active",
        "closed_at",
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
