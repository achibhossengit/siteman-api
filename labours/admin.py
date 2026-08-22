from django.contrib import admin

from core.admin import (
    CompanyListFilter,
    CurrentSiteListFilter,
    DateRangeFilter,
    ReadOnlyModelAdmin,
    SiteListFilter,
)
from .models import DailyRecord, Labour, LabourSession


@admin.register(Labour)
class LabourAdmin(ReadOnlyModelAdmin):
    list_display = (
        "name",
        "is_active",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = (
        ("company", CompanyListFilter),
        CurrentSiteListFilter,
        "is_active",
        ("created_at", DateRangeFilter),
    )
    search_fields = ("name",)


@admin.register(DailyRecord)
class DailyRecordAdmin(ReadOnlyModelAdmin):
    list_display = (
        "date",
        "labour",
        "present",
        "wage",
        "is_sealed",
    )
    list_display_links = ("date",)
    list_filter = (
        ("company", CompanyListFilter),
        SiteListFilter,
        "is_sealed",
        ("date", DateRangeFilter),
    )
    search_fields = ("labour__name", "site__name", "note", "company__name")
    list_select_related = ("labour",)


@admin.register(LabourSession)
class LabourSessionAdmin(ReadOnlyModelAdmin):
    list_display = (
        "labour",
        "start_date",
        "end_date",
        "present_days",
        "salary_earnings",
        "affected_rows",
    )
    list_display_links = ("labour",)
    list_filter = (
        ("company", CompanyListFilter),
        ("start_date", DateRangeFilter),
        ("end_date", DateRangeFilter),
    )
    search_fields = ("labour__name", "company__name")
    list_select_related = ("labour",)
