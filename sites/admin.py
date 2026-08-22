from django.contrib import admin

from core.admin import CompanyListFilter, DateRangeFilter, ReadOnlyModelAdmin, SiteListFilter
from .models import BillingCategory, PrivateSiteCash, Site, SiteCash


@admin.register(Site)
class SiteAdmin(ReadOnlyModelAdmin):
    list_display = (
        "name",
        "is_active",
        "is_closed",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = (("company", CompanyListFilter), "is_active", "is_closed", ("created_at", DateRangeFilter))
    search_fields = ("name", "company__name")


@admin.register(BillingCategory)
class BillingCategoryAdmin(ReadOnlyModelAdmin):
    list_display = (
        "name",
        "display_order",
        "is_active",
        "is_done",
    )
    list_display_links = ("name",)
    list_filter = (
        ("company", CompanyListFilter),
        SiteListFilter,
        "is_active",
        "is_done",
    )
    search_fields = ("name", "site__name", "company__name")


@admin.register(SiteCash)
class SiteCashAdmin(ReadOnlyModelAdmin):
    list_display = (
        "date",
        "type",
        "amount",
        "billing",
    )
    list_display_links = ("date",)
    list_filter = (
        ("company", CompanyListFilter),
        SiteListFilter,
        "type",
        ("date", DateRangeFilter),
    )
    search_fields = ("note", "site__name", "company__name")
    list_select_related = ("billing",)


@admin.register(PrivateSiteCash)
class PrivateSiteCashAdmin(ReadOnlyModelAdmin):
    list_display = (
        "date",
        "type",
        "amount",
        "billing",
    )
    list_display_links = ("date",)
    list_filter = (
        ("company", CompanyListFilter),
        SiteListFilter,
        "type",
        ("date", DateRangeFilter),
    )
    search_fields = ("note", "site__name", "company__name")
    list_select_related = ("billing",)
