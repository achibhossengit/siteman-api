from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from core.admin import CompanyListFilter, DateRangeFilter, ReadOnlyModelAdmin, SiteListFilter
from .models import BillingCategory, PrivateSiteCash, Site, SiteCash
from .reset import preview_site_reset, reset_site


@admin.register(Site)
class SiteAdmin(ReadOnlyModelAdmin):
    change_form_template = "admin/sites/site/change_form.html"
    list_display = (
        "name",
        "is_active",
        "is_closed",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = (("company", CompanyListFilter), "is_active", "is_closed", ("created_at", DateRangeFilter))
    search_fields = ("name", "company__name")

    def has_reset_permission(self, request):
        return request.user.is_superuser

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        return [
            path(
                "<path:object_id>/reset/",
                self.admin_site.admin_view(self.reset_view),
                name="%s_%s_reset" % info,
            ),
            *super().get_urls(),
        ]

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_reset_site"] = bool(object_id) and self.has_reset_permission(
            request
        )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def reset_view(self, request, object_id, extra_context=None):
        if not self.has_reset_permission(request):
            raise PermissionDenied
        site = self.get_object(request, unquote(object_id))
        if site is None:
            return self._get_obj_does_not_exist_redirect(
                request, self.opts, object_id
            )

        counts = preview_site_reset(site)
        counts.pop("session_ids", None)
        error = None
        if request.method == "POST":
            confirm_name = request.POST.get("confirm_name", "")
            if confirm_name != site.name:
                error = "Site name did not match."
            else:
                counts = reset_site(site, actor=request.user)
                self.message_user(
                    request,
                    f"Reset “{site}”: {counts['daily_records']} daily records, "
                    f"{counts['labour_sessions']} sessions, "
                    f"{counts['site_cash']} cash, "
                    f"{counts['private_site_cash']} private cash, "
                    f"{counts['billing_categories']} billing categories, "
                    f"{counts['activity_logs']} activity logs.",
                    messages.SUCCESS,
                )
                return HttpResponseRedirect(
                    reverse("admin:sites_site_change", args=[site.pk])
                )

        context = {
            **self.admin_site.each_context(request),
            **(extra_context or {}),
            "opts": self.opts,
            "original": site,
            "counts": counts,
            "error": error,
            "title": f"Reset site {site}",
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "admin/sites/site/reset_confirmation.html",
            context,
        )


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
        "file",
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
