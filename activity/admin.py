from django.contrib import admin

from core.admin import CompanyListFilter, DateRangeFilter, ReadOnlyModelAdmin, SiteListFilter
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(ReadOnlyModelAdmin):
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
