from django.contrib import admin

from .models import Site


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
    list_filter = ("is_active", "company")
    search_fields = ("name",)
    autocomplete_fields = ("company",)
    exclude = ("created_by",)
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
