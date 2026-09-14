from django.contrib import admin

from core.admin import CompanyListFilter, DateRangeFilter, SiteListFilter
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "entity_type",
        "action",
        "business_date",
    )
    list_display_links = ("created_at",)
    list_filter = (
        ("company", CompanyListFilter),
        SiteListFilter,
        "entity_type",
        "action",
        ("created_at", DateRangeFilter),
        ("business_date", DateRangeFilter),
    )
    search_fields = ("actor_name", "labour_name", "company__name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
